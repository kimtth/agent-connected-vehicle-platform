"""
Azure Cosmos DB client for the Connected Car Platform.
Provides data access and change feed functionality.
"""

import os
import logging
import asyncio
from typing import Dict, Any, List, Optional, AsyncGenerator
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from azure.cosmos.aio import CosmosClient
from azure.cosmos import PartitionKey
from azure.core.exceptions import AzureError
from azure.identity.aio import (
    AzureCliCredential,
    DefaultAzureCredential,
    ManagedIdentityCredential,
)
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from utils.logging_config import get_logger
from models.status import VehicleStatus
from models.vehicle_profile import VehicleProfile
from models.service import Service
from models.command import Command
from models.notification import Notification


# Get logger for this module
logger = get_logger(__name__)


class CosmosDBClient:
    """Azure Cosmos DB client implementation for Connected Car Platform"""

    # Partition key strategy: use only /vehicleId (camelCase). No legacy snake_case duplication.

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return
        for name in ["azure", "azure.core.pipeline.policies.http_logging_policy", "aiohttp"]:
            logging.getLogger(name).setLevel(logging.WARNING)

        # Core configuration - Handle both old and new endpoint formats for backward compatibility
        self.endpoint = os.getenv("COSMOS_DB_ENDPOINT")
        if self.endpoint:
            # Handle backward compatibility: remove :443 port if present
            if self.endpoint.endswith(":443/"):
                self.endpoint = self.endpoint.replace(":443/", "/")
            # Ensure endpoint ends with /
            elif not self.endpoint.endswith("/"):
                self.endpoint = self.endpoint + "/"

        self.key = os.getenv("COSMOS_DB_KEY")
        self.use_aad_auth = os.getenv("COSMOS_DB_USE_AAD", "false").lower() == "true"
        self.database_name = os.getenv("COSMOS_DB_DATABASE", "VehiclePlatformDB")

        # Container names (hardcoded – override via env was never used)
        self.vehicles_container_name = "vehicles"
        self.services_container_name = "services"
        self.commands_container_name = "commands"
        self.notifications_container_name = "notifications"
        self.status_container_name = "vehiclestatus"

        # Client instances
        self.client = None
        self.database = None
        self.vehicles_container = None
        self.services_container = None
        self.commands_container = None
        self.notifications_container = None
        self.status_container = None

        # Session/credential handle for proper cleanup
        self._credential = None

        # Connection state management
        self.is_connecting = False
        self.connected = False
        self.connection_error = None
        self.last_connection_attempt = None
        self.connection_retry_delay = 10  # Increased from 5 seconds

        # Health check configuration
        self.health_check_interval = 30  # seconds
        self.last_health_check = None

        self._cleanup_scheduled = False
        self._connection_lock = asyncio.Lock()
        self._validate_configuration()
        self._initialized = True
        self._closing = False

    def _validate_configuration(self):
        return bool(self.endpoint and self.database_name and (self.use_aad_auth or self.key))

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _ensure_timestamp(doc: Dict[str, Any]):
        """Inject ISO timestamp if missing but _ts present."""
        if doc and "timestamp" not in doc and "_ts" in doc:
            doc["timestamp"] = (
                datetime.fromtimestamp(doc["_ts"], tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )
        return doc

    @staticmethod
    def _ensure_timestamp(doc: Dict[str, Any]):
        """Inject ISO timestamp if missing but _ts present."""
        if doc and "timestamp" not in doc and "_ts" in doc:
            doc["timestamp"] = (
                datetime.fromtimestamp(doc["_ts"], tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )
        return doc

    async def _query_one(
        self,
        container,
        query: str,
        params: List[Dict[str, Any]],
        *,
        partition_key: Optional[str] = None,
        model_cls=None,
    ):
        """Generic single-item query + model mapping (now camelCase-normalized)."""
        if not container:
            return None
        try:
            items = container.query_items(
                query=query,
                parameters=params,
                partition_key=partition_key if partition_key is not None else None,
            )
            async for item in items:
                self._ensure_timestamp(item)
                return model_cls(**item) if model_cls else item
            return None
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return None

    async def connect(self):
        if not self.endpoint or not self.database_name:
            return False
        async with self._connection_lock:
            if self.is_connecting or (self.connected and self._is_connection_healthy()):
                return self.connected
            if self.last_connection_attempt and datetime.now() - self.last_connection_attempt < timedelta(seconds=self.connection_retry_delay):
                return self.connected
            self.is_connecting = True
            self.last_connection_attempt = datetime.now()
            try:
                await self._cleanup_client()
                if self._is_azure_environment() or self.use_aad_auth:
                    success = await self._connect_with_aad()
                elif self.key:
                    success = await self._connect_with_master_key()
                else:
                    return False
                if success:
                    await self._ensure_containers_exist()
                    await self._verify_connection()
                    self.connected = True
                    return True
                return False
            except Exception as e:
                self.connection_error = str(e)
                self.connected = False
                await self._cleanup_client()
                return False
            finally:
                self.is_connecting = False

    def _is_azure_environment(self) -> bool:
        azure_vars = ["WEBSITE_SITE_NAME", "WEBSITE_INSTANCE_ID", "MSI_ENDPOINT", "IDENTITY_ENDPOINT"]
        return any(os.getenv(var) for var in azure_vars)

    async def _connect_with_aad(self):
        if self._is_azure_environment():
            self._credential = ManagedIdentityCredential()
        else:
            tenant_id = os.getenv("AZURE_TENANT_ID") or os.getenv("AZD_TENANT_ID") or os.getenv("AZURE_AD_TENANT_ID")
            try:
                self._credential = (
                    AzureCliCredential(tenant_id=tenant_id)
                    if tenant_id
                    else AzureCliCredential()
                )
                await self._credential.get_token("https://management.azure.com/.default")
            except Exception:
                self._credential = DefaultAzureCredential(
                    exclude_cli_credential=True,
                    exclude_developer_cli_credential=True,
                    exclude_interactive_browser_credential=True,
                )
        self.client = CosmosClient(self.endpoint, credential=self._credential)
        await self._ensure_database_exists()
        self.database = self.client.get_database_client(self.database_name)
        self._initialize_containers()
        return True

    async def _connect_with_master_key(self):
        try:
            self.client = CosmosClient(self.endpoint, credential=self.key)
            await self._ensure_database_exists()
            self.database = self.client.get_database_client(self.database_name)
            self._initialize_containers()
            return True
        except AzureError as e:
            if "authorization is disabled" in str(e).lower() or "forbidden" in str(e).lower():
                self.use_aad_auth = True
                return await self._connect_with_aad()
            raise

    async def _ensure_database_exists(self):
        """Ensure the database exists, create if it doesn't"""
        try:
            # Try to read the database to check if it exists
            database_client = self.client.get_database_client(self.database_name)
            await database_client.read()
            logger.info(f"Database '{self.database_name}' already exists")
        except CosmosResourceNotFoundError:
            # Database doesn't exist, create it
            logger.info(f"Creating database '{self.database_name}'...")
            await self.client.create_database(id=self.database_name)
            logger.info(f"Database '{self.database_name}' created successfully")
        except Exception as e:
            logger.error(f"Error checking/creating database: {e}")
            raise

    def _initialize_containers(self):
        """Initialize container clients with proper configuration"""
        self.vehicles_container = self.database.get_container_client(
            self.vehicles_container_name
        )
        self.services_container = self.database.get_container_client(
            self.services_container_name
        )
        self.commands_container = self.database.get_container_client(
            self.commands_container_name
        )
        self.notifications_container = self.database.get_container_client(
            self.notifications_container_name
        )
        self.status_container = self.database.get_container_client(
            self.status_container_name
        )

    async def _ensure_containers_exist(self):
        """Ensure all required containers exist, create if they don't"""
        container_configs = {
            self.vehicles_container_name: ("/vehicleId", None),
            self.services_container_name: ("/vehicleId", None),
            self.commands_container_name: ("/vehicleId", 86400),
            self.notifications_container_name: ("/vehicleId", 2592000),
            self.status_container_name: ("/vehicleId", 604800),
        }
        for container_name, (partition_key, ttl) in container_configs.items():
            try:
                await self.database.get_container_client(container_name).read()
                logger.debug(f"Container '{container_name}' already exists")
            except CosmosResourceNotFoundError:
                logger.info(f"Creating container '{container_name}' with partition key '{partition_key}'...")
                container_props = {
                    "id": container_name,
                    "partition_key": PartitionKey(path=partition_key),
                }
                if ttl is not None:
                    container_props["default_ttl"] = ttl
                await self.database.create_container(**container_props)
                logger.info(f"Container '{container_name}' created successfully")
            except Exception as e:
                logger.error(f"Error checking/creating container '{container_name}': {e}")
                raise
        self._initialize_containers()

    async def _verify_connection(self):
        self.last_health_check = datetime.now()
        return True

    def _is_connection_healthy(self):
        """Check if connection is healthy based on last health check"""
        if not self.last_health_check:
            return False
        return datetime.now() - self.last_health_check < timedelta(
            seconds=self.health_check_interval
        )

    def _is_transport_closed_error(self, err: Exception) -> bool:
        """Return True when the underlying HTTP transport is already closed."""
        try:
            msg = str(err).lower()
            return (
                "http transport has already been closed" in msg
                or "transport has already been closed" in msg
            )
        except Exception:
            return False

    def is_active(self) -> bool:
        """True if client is connected and not closing."""
        return self.connected and not self._closing

    async def ensure_connected(self):
        """Ensure we have a valid connection with automatic retry"""
        if self._closing:  # new guard
            return False
        if self.connected and self._is_connection_healthy():
            return True

        if not self.is_connecting:
            return await self.connect()

        # Wait for existing connection attempt with timeout
        max_wait = 30  # seconds
        wait_time = 0
        while self.is_connecting and wait_time < max_wait:
            await asyncio.sleep(1)
            wait_time += 1

        return self.connected

    async def close(self):
        self._closing = True
        async with self._connection_lock:
            await self._cleanup_client()

    async def _cleanup_client(self):
        self.vehicles_container = None
        self.services_container = None
        self.commands_container = None
        self.notifications_container = None
        self.status_container = None
        self.database = None
        if self.client:
            await self._safe_close_client(self.client)
            self.client = None
        if self._credential:
            await self._credential.close()
            self._credential = None
        self.connected = False

    async def _safe_close_client(self, client):
        try:
            await asyncio.wait_for(client.close(), timeout=10.0)
        except (asyncio.TimeoutError, Exception):
            pass

    # Context manager support for proper resource management
    async def __aenter__(self):
        """Async context manager entry"""
        await self.ensure_connected()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

    # Vehicle Status operations

    async def get_vehicle_status(self, vehicle_id: str) -> Optional[VehicleStatus]:
        if self._closing or not await self.ensure_connected():
            return None
        query = "SELECT * FROM c WHERE c.vehicleId = @vehicleId ORDER BY c._ts DESC OFFSET 0 LIMIT 1"
        return await self._query_one(
            self.status_container,
            query,
            [{"name": "@vehicleId", "value": vehicle_id}],
            partition_key=vehicle_id,
            model_cls=VehicleStatus,
        )

    async def list_vehicle_status(self, vehicle_id: str, limit: int = 10) -> List[VehicleStatus]:
        if self._closing or not await self.ensure_connected():
            return []
        query = "SELECT TOP @limit * FROM c WHERE c.vehicleId = @vehicleId ORDER BY c._ts DESC"
        items = self.status_container.query_items(
            query=query,
            parameters=[
                {"name": "@vehicleId", "value": vehicle_id},
                {"name": "@limit", "value": limit},
            ],
            partition_key=vehicle_id
        )
        result = []
        async for item in items:
            self._ensure_timestamp(item)
            result.append(VehicleStatus(**item))
        return result

    async def subscribe_to_vehicle_status(self, vehicle_id: str) -> AsyncGenerator[VehicleStatus, None]:
        if self._closing:
            return
        latest_status = await self.get_vehicle_status(vehicle_id)
        last_timestamp_epoch = 0
        if latest_status:
            yield latest_status
            try:
                if latest_status.timestamp:
                    last_timestamp_epoch = int(datetime.fromisoformat(latest_status.timestamp.replace("Z", "")).timestamp())
            except Exception:
                pass
        while not self._closing and self.connected:
            if not self.connected and not await self.ensure_connected():
                break
            try:
                items = self.status_container.query_items(
                    query="SELECT * FROM c WHERE c.vehicleId = @vehicleId AND c._ts > @lastTs ORDER BY c._ts DESC",
                    parameters=[
                        {"name": "@vehicleId", "value": vehicle_id},
                        {"name": "@lastTs", "value": last_timestamp_epoch},
                    ],
                    partition_key=vehicle_id
                )
                had_updates = False
                async for item in items:
                    if "timestamp" not in item and "_ts" in item:
                        item["timestamp"] = datetime.fromtimestamp(item["_ts"], tz=timezone.utc).isoformat().replace("+00:00", "Z")
                    yield VehicleStatus(**item)
                    had_updates = True
                    last_timestamp_epoch = max(last_timestamp_epoch, item.get("_ts", 0))
                await asyncio.sleep(1.0 if had_updates else 5.0)
            except (asyncio.CancelledError, Exception):
                if self._closing or self._is_transport_closed_error(Exception):
                    break
                await asyncio.sleep(10.0)

    async def update_vehicle_status(self, vehicle_id: str, status_data: Dict[str, Any]) -> VehicleStatus:
        if not await self.ensure_connected():
            return VehicleStatus(vehicle_id=vehicle_id)
        sanitized = status_data.copy()
        sanitized.pop("vehicleId", None)
        model = VehicleStatus(vehicle_id=vehicle_id, **sanitized)
        body = model.model_dump(by_alias=True, exclude_none=True)
        body["vehicleId"] = vehicle_id
        body["id"] = str(uuid.uuid4())
        body["timestamp"] = self._now_iso()
        created = await self.status_container.create_item(body=body)
        self._ensure_timestamp(created)
        return VehicleStatus(**created)

    # Vehicles operations

    async def create_vehicle(self, vehicle_data: Dict[str, Any]) -> VehicleProfile:
        if not await self.ensure_connected():
            return VehicleProfile(**vehicle_data)
        vehicle = vehicle_data if isinstance(vehicle_data, VehicleProfile) else VehicleProfile(**vehicle_data)
        doc = vehicle.model_dump(by_alias=True, exclude_none=True)
        doc.setdefault("id", str(uuid.uuid4()))
        doc.setdefault("vehicleId", doc["id"])
        created = await self.vehicles_container.create_item(body=doc)
        return VehicleProfile(**created)

    async def list_vehicles(self) -> List[VehicleProfile]:
        if not await self.ensure_connected():
            return []
        items = self.vehicles_container.query_items(query="SELECT * FROM c")
        return [VehicleProfile(**item) async for item in items]

    async def get_vehicle(self, vehicle_id: str) -> Optional[VehicleProfile]:
        """Get a single vehicle by vehicle_id."""
        if not await self.ensure_connected() or not self.vehicles_container:
            logger.warning("No Cosmos DB connection. Cannot get vehicle.")
            return None
        query = "SELECT TOP 1 * FROM c WHERE c.vehicleId = @vehicleId"
        params = [{"name": "@vehicleId", "value": vehicle_id}]
        # First attempt with partition key
        result = await self._query_one(
            self.vehicles_container,
            query,
            params,
            partition_key=vehicle_id,
            model_cls=VehicleProfile,
        )
        if result:
            return result
        # Fallback cross-partition
        return await self._query_one(
            self.vehicles_container, query, params, model_cls=VehicleProfile
        )

    # Services operations

    async def create_service(self, service_data: Dict[str, Any]) -> Service:
        """Create a new service record"""
        if not await self.ensure_connected() or not self.services_container:
            logger.warning("No Cosmos DB connection. Cannot create service.")
            return Service(**service_data)
        try:
            service = (
                service_data
                if isinstance(service_data, Service)
                else Service(**service_data)
            )
            doc = service.model_dump(by_alias=True, exclude_none=True)
            if "id" not in doc:
                doc["id"] = str(uuid.uuid4())
            if "vehicleId" not in doc and service_data.get("vehicleId"):
                doc["vehicleId"] = service_data["vehicleId"]
            created = await self.services_container.create_item(body=doc)
            return Service(**created)
        except Exception as e:
            logger.error(f"Error creating service: {e}")
            return Service(**service_data)

    async def list_services(self, vehicle_id: str) -> List[Service]:
        if self._closing or not await self.ensure_connected():
            return []
        items = self.services_container.query_items(
            query="SELECT * FROM c WHERE c.vehicleId = @vehicleId",
            parameters=[{"name": "@vehicleId", "value": vehicle_id}],
            partition_key=vehicle_id
        )
        return [Service(**item) async for item in items]

    # Commands operations

    async def create_command(self, command_data: Dict[str, Any]) -> Command:
        """Create a new command"""
        if not await self.ensure_connected() or not self.commands_container:
            logger.warning("No Cosmos DB connection. Cannot create command.")
            return Command(**command_data)
        try:
            command = (
                command_data
                if isinstance(command_data, Command)
                else Command(**command_data)
            )
            doc = command.model_dump(by_alias=True, exclude_none=True)
            if "id" not in doc:
                doc["id"] = str(uuid.uuid4())
            if "vehicleId" not in doc and command_data.get("vehicleId"):
                doc["vehicleId"] = command_data["vehicleId"]
            created = await self.commands_container.create_item(body=doc)
            return Command(**created)
        except Exception as e:
            logger.error(f"Error creating command: {e}")
            return Command(**command_data)

    async def update_command(
        self, command_id: str, updated_data: Dict[str, Any]
    ) -> Optional[Command]:
        """Update an existing command"""
        if not await self.ensure_connected() or not self.commands_container:
            logger.warning("No Cosmos DB connection. Cannot update command.")
            return None
        try:
            query = "SELECT * FROM c WHERE c.commandId = @id OR c.command_id = @id OR c.id = @id"
            params = [{"name": "@id", "value": command_id}]
            items = self.commands_container.query_items(query=query, parameters=params)
            existing = None
            async for item in items:
                existing = item
                break
            if not existing:
                logger.warning(f"Command {command_id} not found")
                return None
            # Merge
            for k, v in updated_data.items():
                existing[k] = v
            # Normalize through model
            cmd_model = Command(**existing)
            doc = cmd_model.model_dump(by_alias=True, exclude_none=True)
            # Persist via upsert to avoid partition_key forwarding issues
            replaced = await self.commands_container.upsert_item(body=doc)
            return Command(**replaced)
        except Exception as e:
            logger.error(f"Error updating command {command_id}: {e}")
            return None

    async def list_commands(self, vehicle_id: str = None) -> List[Command]:
        if self._closing or not await self.ensure_connected():
            return []
        if vehicle_id:
            items = self.commands_container.query_items(
                query="SELECT * FROM c WHERE c.vehicleId = @vehicleId ORDER BY c._ts DESC",
                parameters=[{"name": "@vehicleId", "value": vehicle_id}],
                partition_key=vehicle_id
            )
        else:
            items = self.commands_container.query_items(query="SELECT * FROM c ORDER BY c._ts DESC")
        return [Command(**item) async for item in items]

    async def create_notification(self, notification_data: Dict[str, Any]) -> Notification:
        if not await self.ensure_connected():
            return Notification(**notification_data)
        notification = notification_data if isinstance(notification_data, Notification) else Notification(**notification_data)
        doc = notification.model_dump(by_alias=True, exclude_none=True)
        doc.setdefault("id", str(uuid.uuid4()))
        if "vehicleId" not in doc and notification_data.get("vehicleId"):
            doc["vehicleId"] = notification_data["vehicleId"]
        created = await self.notifications_container.create_item(body=doc)
        return Notification(**created)

    async def list_notifications(self, vehicle_id: str = None) -> List[Notification]:
        if not await self.ensure_connected():
            return []
        if vehicle_id:
            items = self.notifications_container.query_items(
                query="SELECT * FROM c WHERE c.vehicleId = @vehicleId ORDER BY c._ts DESC",
                parameters=[{"name": "@vehicleId", "value": vehicle_id}],
                partition_key=vehicle_id
            )
        else:
            items = self.notifications_container.query_items(query="SELECT * FROM c ORDER BY c._ts DESC")
        return [Notification(**item) async for item in items]

    async def mark_notification_read(
        self, notificationId: str
    ) -> Optional[Notification]:
        if self._closing:
            return None
        if not await self.ensure_connected() or not self.notifications_container:
            logger.warning("No Cosmos DB connection. Cannot mark notification read.")
            return None
        try:
            query = "SELECT TOP 1 * FROM c WHERE c.id = @id"
            params = [{"name": "@id", "value": notificationId}]
            existing = await self._query_one(
                self.notifications_container, query, params
            )
            if not existing:
                logger.warning(f"Notification {notificationId} not found")
                return None
            existing["read"] = True
            model = Notification(**existing)
            doc = model.model_dump(by_alias=True, exclude_none=True)
            replaced = await self.notifications_container.upsert_item(body=doc)
            return Notification(**replaced)
        except Exception as e:
            logger.error(f"Error marking notification read: {e}")
            return None

    async def delete_notification(self, notificationId: str) -> bool:
        if self._closing:
            return False
        if not await self.ensure_connected() or not self.notifications_container:
            logger.warning("No Cosmos DB connection. Cannot delete notification.")
            return False
        try:
            query = "SELECT TOP 1 c.id, c.vehicleId FROM c WHERE c.id = @id"
            params = [{"name": "@id", "value": notificationId}]
            items = self.notifications_container.query_items(
                query=query, parameters=params
            )
            async for item in items:
                await self.notifications_container.delete_item(
                    item=notificationId, partition_key=item.get("vehicleId")
                )
                return True
            logger.warning(f"Notification {notificationId} not found")
            return False
        except Exception as e:
            logger.error(f"Error deleting notification: {e}")
            return False

    # Container name env overrides removed – defaults are always used


@lru_cache(maxsize=1)
def get_cosmos_client():
    return CosmosDBClient()


async def get_cosmos_client_connected():
    client = get_cosmos_client()
    await client.ensure_connected()
    return client
