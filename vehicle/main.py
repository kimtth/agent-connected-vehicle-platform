"""
Main application for the connected vehicle platform.
"""

import sys
import os
import asyncio
import logging
import json
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import atexit
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
import socket
import http.client
import multiprocessing
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    StreamingResponse,
    PlainTextResponse,
)
from contextlib import asynccontextmanager
from models.command import Command
from models.vehicle_profile import VehicleProfile
from models.service import Service
from models.status import VehicleStatus
from models.api_responses import (
    InfoResponse,
    HealthResponse,
    HealthServices,
    CommandHistoryItem,
    CommandSubmitResponse,
    CreateNotificationResponse,
    MarkNotificationReadResponse,
    GenericDetailResponse,
    FleetMetrics,
)
from models.notification import Notification
from dotenv import load_dotenv
from importlib import import_module
from azure.azure_auth import AzureADMiddleware
from fastapi import Request
from azure.cosmos_db import get_cosmos_client
from plugin.mcp_weather_server import start_weather_server
from plugin.mcp_traffic_server import start_traffic_server
from plugin.mcp_poi_server import start_poi_server
from plugin.mcp_navigation_server import start_navigation_server

# Configure loguru with better error handling
from utils.logging_config import configure_logging


# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Load environment variables first
load_dotenv(override=True)

# Configure logging
log_level = os.getenv("LOG_LEVEL", "INFO")
configure_logging(log_level)
logger = logging.getLogger(__name__)

# Track MCP processes for graceful shutdown
MCP_PROCESSES = []
_SERVER_INSTANCE_STARTED = False


def _stop_mcp_processes(timeout: float = 5.0):
    for p in MCP_PROCESSES:
        if p.is_alive():
            p.terminate()
            p.join(timeout)
            if p.is_alive():
                p.kill()


# Ensure cleanup on unexpected interpreter exit (best-effort)
@atexit.register
def _cleanup_at_exit():
    _stop_mcp_processes()


@asynccontextmanager
async def lifespan(app):
    logger.info("Starting up the application...")
    # Lazy create only once
    if not hasattr(app.state, "cosmos_client"):
        app.state.cosmos_client = get_cosmos_client()  # unified singleton
        logger.info("Cosmos DB client instantiated (lifespan)")
    client = app.state.cosmos_client

    if hasattr(client, "connect"):
        await client.connect()

    yield
    if hasattr(client, "close"):
        await client.close()
    if os.getenv("ENABLE_MCP", "true").lower() == "true":
        _stop_mcp_processes()


app = FastAPI(title="Connected Car Platform", lifespan=lifespan)

# Restore middlewares (Azure AD auth first, then CORS)
app.add_middleware(AzureADMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# Load routers early so they precede the catch-all /{full_path:path} route
def _load_optional_routers():
    if getattr(app.state, "routers_loaded", False):
        return
    for name, modpath in [
        ("Agents", "apis.agent_routes"),
        ("Vehicle Features", "apis.vehicle_feature_routes"),
        ("Remote Access", "apis.remote_access_routes"),
        ("Speech", "apis.speech_routes"),
        ("Emergency & Safety", "apis.emergency_routes"),
        ("Development Seeding", "apis.seed_routes"),
    ]:
        try:
            module = import_module(modpath)
            app.include_router(module.router, prefix="/api", tags=[name])
        except ImportError:
            pass
    app.state.routers_loaded = True


_load_optional_routers()


def _cosmos_status():
    try:
        client = get_cosmos_client()
    except Exception:
        return False, False
    enabled = bool(
        getattr(client, "endpoint", None)
        and (getattr(client, "key", None) or getattr(client, "use_aad_auth", False))
    )
    connected = getattr(client, "connected", False) if enabled else False
    return enabled, connected


@app.middleware("http")
async def log_user_requests(request: Request, call_next):
    corr_id = request.headers.get("X-Client-Request-Id") or str(uuid4())
    request.state.user_id = request.headers.get("X-User-Name", "anonymous")
    response = await call_next(request)
    response.headers.setdefault("X-Client-Request-Id", corr_id)
    return response


@app.get("/api/info", response_model=InfoResponse)
def get_status():
    enabled, connected = _cosmos_status()
    return InfoResponse(
        status="Connected Car Platform running",
        version="2.0.0",
        azure_cosmos_enabled=enabled,
        azure_cosmos_connected=connected,
    )


@app.get("/api/health", response_model=HealthResponse)
def health_check():
    enabled, connected = _cosmos_status()
    mcp_status = _collect_mcp_status()
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc),
        services=HealthServices(
            api="running",
            cosmos_db="connected" if connected else "disconnected",
            mcp_weather=mcp_status["weather"],
            mcp_traffic=mcp_status["traffic"],
            mcp_poi=mcp_status["poi"],
            mcp_navigation=mcp_status["navigation"],
        ),
    )


@app.get(
    "/api/vehicles/{vehicle_id}/command-history",
    response_model=list[CommandHistoryItem],
)
async def get_vehicle_command_history(vehicle_id: str):
    client = get_cosmos_client()
    if not await client.ensure_connected():
        return []
    commands = await client.list_commands(vehicle_id)
    history = [
        CommandHistoryItem(
            timestamp=cmd.get("timestamp", ""),
            command=cmd.get("command_type", "unknown"),
            status=cmd.get("status", "unknown"),
            response=cmd.get("response", ""),
            error=cmd.get("error", ""),
        )
        for cmd in commands
    ]
    history.sort(key=lambda x: x.timestamp, reverse=True)
    return history


# Submit a command (simulate external system)
@app.post("/api/command", response_model=CommandSubmitResponse)
async def submit_command(command: Command, background_tasks: BackgroundTasks):
    client = get_cosmos_client()
    await client.ensure_connected()
    command_id = str(uuid4())
    command.command_id = command_id
    command.status = "pending"
    command.timestamp = datetime.now(timezone.utc).isoformat()
    command_data = command.model_dump(by_alias=True)
    await client.create_command(command_data)
    background_tasks.add_task(process_command_async, command_data)
    return CommandSubmitResponse(command_id=command_id)


# Get command log
@app.get("/api/commands", response_model=list[Command])
async def get_commands(vehicle_id: str = None):
    client = get_cosmos_client()
    if not await client.ensure_connected():
        return []
    return await client.list_commands(vehicle_id)


# Get vehicle status (from Cosmos DB only)
@app.get("/api/vehicles/{vehicle_id}/status", response_model=VehicleStatus)
async def get_vehicle_status(vehicle_id: str):
    client = get_cosmos_client()
    if not await client.ensure_connected():
        raise HTTPException(status_code=503, detail="Database service unavailable")
    status = await client.get_vehicle_status(vehicle_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Vehicle {vehicle_id} not found")
    return status


# Stream vehicle status updates
@app.get("/api/vehicle/{vehicle_id}/status/stream")
async def stream_vehicle_status(vehicle_id: str):
    """Stream real-time status updates for a vehicle"""

    async def status_stream_generator():
        client = get_cosmos_client()
        if not await client.ensure_connected():
            yield "data: {{\"error\": \"Database service unavailable\"}}\n\n"
            return
        try:
            async for status in client.subscribe_to_vehicle_status(vehicle_id):
                payload = status.model_dump(by_alias=True) if isinstance(status, BaseModel) else status
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            pass

    response = StreamingResponse(
        status_stream_generator(), media_type="text/event-stream"
    )
    # Add CORS headers specifically for EventSource
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET"
    response.headers["Access-Control-Allow-Headers"] = "Cache-Control"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    response.headers["X-Accel-Buffering"] = "no"  # prevent proxy buffering for SSE
    return response


# Get notifications
@app.get("/api/notifications", response_model=list[Notification])
async def get_notifications(vehicle_id: str = None):
    client = get_cosmos_client()
    if not await client.ensure_connected():
        return []
    return await client.list_notifications(vehicle_id)


# Add a vehicle profile
@app.post("/api/vehicle", response_model=VehicleProfile)
async def add_vehicle(profile: VehicleProfile):
    client = get_cosmos_client()
    if not await client.ensure_connected():
        raise HTTPException(status_code=503, detail="Database service unavailable")
    return await client.create_vehicle(profile.model_dump(by_alias=True))


# List all vehicles
@app.get("/api/vehicles", response_model=list[VehicleProfile])
async def list_vehicles():
    client = get_cosmos_client()
    if not await client.ensure_connected():
        raise HTTPException(status_code=503, detail="Database service unavailable")
    return await client.list_vehicles()


# Get fleet metrics
@app.get("/api/vehicles/metrics", response_model=FleetMetrics)
async def get_fleet_metrics():
    """Get aggregated metrics for all vehicles in the fleet"""
    client = get_cosmos_client()
    if not await client.ensure_connected():
        raise HTTPException(status_code=503, detail="Database service unavailable")
    
    vehicles = await client.list_vehicles()
    if not vehicles:
        return FleetMetrics(
            total_vehicles=0,
            active_vehicles=0,
            low_battery=0,
            maintenance_needed=0,
            avg_battery=0,
            total_distance=0
        )
    
    # Fetch status for all vehicles
    statuses = []
    for vehicle in vehicles:
        try:
            status = await client.get_vehicle_status(vehicle.vehicle_id)
            if status:
                statuses.append(status)
        except Exception:
            continue
    
    if not statuses:
        return FleetMetrics(
            total_vehicles=len(vehicles),
            active_vehicles=0,
            low_battery=0,
            maintenance_needed=0,
            avg_battery=0,
            total_distance=0
        )
    
    # Calculate metrics
    active_count = sum(1 for s in statuses if (s.speed or 0) > 0)
    low_battery_count = sum(1 for s in statuses if (s.battery or 100) < 20)
    maintenance_count = sum(1 for s in statuses if (s.oil_remaining or 100) < 30 or (s.engine_temp or 0) > 100)
    avg_battery = sum((s.battery or 0) for s in statuses) / len(statuses)
    total_distance = sum((s.odometer or 0) for s in statuses)
    
    return FleetMetrics(
        total_vehicles=len(vehicles),
        active_vehicles=active_count,
        low_battery=low_battery_count,
        maintenance_needed=maintenance_count,
        avg_battery=round(avg_battery, 1),
        total_distance=round(total_distance, 1)
    )


# GET a single vehicle by ID (for fetchVehicleById)
@app.get("/api/vehicles/{vehicle_id}", response_model=VehicleProfile)
async def get_vehicle(vehicle_id: str):
    client = get_cosmos_client()
    if not await client.ensure_connected():
        raise HTTPException(status_code=503, detail="Database service unavailable")
    vehicle = await client.get_vehicle(vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"Vehicle {vehicle_id} not found")
    return vehicle


# Add a service to a vehicle
@app.post("/api/vehicles/{vehicle_id}/services", response_model=Service)
async def add_service(vehicle_id: str, service: Service):
    """Add a service record to a vehicle"""
    client = get_cosmos_client()
    await client.ensure_connected()
    service_data = service.model_dump()
    # FIX: use camelCase partition key field expected by Cosmos (vehicleId), not snake_case
    service_data["vehicleId"] = vehicle_id
    service_data["id"] = str(uuid4())
    return await client.create_service(service_data)


# List all services for a vehicle
@app.get("/api/vehicles/{vehicle_id}/services", response_model=list[Service])
async def list_services(vehicle_id: str):
    """List all services for a vehicle"""
    client = get_cosmos_client()
    # Ensure Cosmos DB is connected
    await client.ensure_connected()
    return await client.list_services(vehicle_id)


# Update a service
@app.put("/api/vehicles/{vehicle_id}/services/{serviceId}", response_model=Service)
async def update_service(vehicle_id: str, serviceId: str, service: Service):
    client = get_cosmos_client()
    await client.ensure_connected()
    data = service.model_dump()
    return await client.update_service(vehicle_id, serviceId, data)


# Delete a service
@app.delete(
    "/api/vehicles/{vehicle_id}/services/{serviceId}",
    response_model=GenericDetailResponse,
)
async def delete_service(vehicle_id: str, serviceId: str):
    client = get_cosmos_client()
    await client.ensure_connected()
    await client.delete_service(vehicle_id, serviceId)
    return GenericDetailResponse(detail=f"Service {serviceId} deleted successfully")


# Update vehicle status
@app.put("/api/vehicle/{vehicle_id}/status", response_model=VehicleStatus)
async def update_vehicle_status(vehicle_id: str, status: VehicleStatus):
    client = get_cosmos_client()
    if not await client.ensure_connected():
        raise HTTPException(status_code=503, detail="Database service unavailable")
    if status.vehicle_id != vehicle_id:
        raise HTTPException(
            status_code=400, detail="Vehicle ID in path does not match status object"
        )
    status_data = status.model_dump(by_alias=True)
    status_data["timestamp"] = datetime.now(timezone.utc).isoformat()
    return await client.update_vehicle_status(vehicle_id, status_data)


# Partial status update
@app.patch("/api/vehicle/{vehicle_id}/status", response_model=VehicleStatus)
async def patch_vehicle_status(vehicle_id: str, status_update: dict):
    client = get_cosmos_client()
    if not await client.ensure_connected():
        raise HTTPException(status_code=503, detail="Database service unavailable")
    current_status = await get_vehicle_status(vehicle_id)
    if not current_status:
        current_status = {"vehicle_id": vehicle_id}
    current_status.update(status_update)
    current_status["timestamp"] = datetime.now(timezone.utc).isoformat()
    return await client.update_vehicle_status(vehicle_id, current_status)


# Async background task to process commands
async def process_command_async(command_data):
    client = get_cosmos_client()
    if not await client.ensure_connected():
        return
    command_id = command_data.get("command_id", "") or command_data.get("commandId", "")
    vehicle_id = command_data.get("vehicle_id", "") or command_data.get("vehicleId", "")
    await client.update_command(command_id=command_id, updated_data={"status": "processing"})
    await client.update_command(
        command_id=command_id,
        updated_data={
            "status": "completed",
            "completion_time": datetime.now(timezone.utc).isoformat(),
        },
    )
    commandType = command_data.get("commandType") or command_data.get("command_type") or "unknown"
    notif = Notification(
        id=str(uuid4()),
        vehicle_id=vehicle_id,
        type="command_executed",
        message=f"Command {commandType} executed successfully.",
        timestamp=datetime.now(timezone.utc).isoformat(),
        read=False,
        severity="low",
        source="System",
        action_required=False,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    await client.create_notification(notif.model_dump())


# Create a notification (for createNotification)
@app.post("/api/notifications", response_model=CreateNotificationResponse)
async def create_notification(notification: dict):
    client = get_cosmos_client()
    await client.ensure_connected()
    result = await client.create_notification(notification)
    nid = notification.get("id")
    return CreateNotificationResponse(id=nid, status="created", data=result)


# Mark a notification as read (for markNotificationRead)
@app.put(
    "/api/notifications/{notification_id}/read",
    response_model=MarkNotificationReadResponse,
)
async def mark_notification_read(notification_id: str):
    client = get_cosmos_client()
    await client.ensure_connected()
    updated = await client.mark_notification_read(notification_id)
    if not updated:
        raise HTTPException(
            status_code=404, detail=f"Notification {notification_id} not found"
        )
    return MarkNotificationReadResponse(
        id=notification_id, status="marked_as_read", data=updated
    )


# Delete a notification (for deleteNotification)
@app.delete(
    "/api/notifications/{notification_id}", response_model=GenericDetailResponse
)
async def delete_notification(notification_id: str):
    client = get_cosmos_client()
    await client.ensure_connected()
    await client.delete_notification(notification_id)
    return GenericDetailResponse(
        detail=f"Notification {notification_id} deleted successfully"
    )


@app.get("/api/notifications/stream")
async def stream_notifications(vehicle_id: str):
    client = get_cosmos_client()
    if not await client.ensure_connected():
        async def gen():
            yield "data: {{\"error\": \"db_unavailable\"}}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    async def gen():
        last_ts = None
        while True:
            try:
                notifications = await client.list_notifications(vehicle_id)
                fresh = [n for n in notifications if last_ts is None or (getattr(n, "timestamp", None) and n.timestamp > last_ts)]
                if fresh:
                    last_ts = max([f.timestamp for f in fresh if f.timestamp], default=last_ts)
                    for f in reversed(fresh):
                        yield f"data: {json.dumps(f.model_dump(by_alias=True))}\n\n"
                await asyncio.sleep(3)
            except asyncio.CancelledError:
                break

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/debug/cosmos")
async def cosmos_debug():
    client = get_cosmos_client()
    return {
        "endpoint": getattr(client, "endpoint", None),
        "database": getattr(client, "database_name", None),
        "connected": getattr(client, "connected", None),
        "is_connecting": getattr(client, "is_connecting", None),
        "connection_error": getattr(client, "connection_error", None),
        "last_health_check": str(getattr(client, "last_health_check", None)),
        "azure_env_detected": (
            client._is_azure_environment()
            if hasattr(client, "_is_azure_environment")
            else None
        ),
    }


@app.post("/api/mcp/restart")
async def restart_mcp():
    if os.getenv("ENABLE_MCP", "true").lower() != "true":
        raise HTTPException(status_code=400, detail="MCP disabled")
    _stop_mcp_processes()
    MCP_PROCESSES.clear()
    # Restart
    _start_mcp_process(start_weather_server, "mcp_weather")
    _start_mcp_process(start_navigation_server, "mcp_navigation")
    _start_mcp_process(start_traffic_server, "mcp_traffic")
    _start_mcp_process(start_poi_server, "mcp_poi")
    return {"status": "restarted", "services": _collect_mcp_status()}


def _is_port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _collect_mcp_status() -> dict:
    """
    Probe MCP sidecar health endpoints.
    Returns dict with keys: weather, traffic, poi, navigation.
    Status values: 'running', 'down', or 'disabled'.
    """
    if os.getenv("ENABLE_MCP", "true").lower() != "true":
        return {k: "disabled" for k in ("weather", "traffic", "poi", "navigation")}

    host = "127.0.0.1"
    services = {
        "weather": 8001,
        "traffic": 8002,
        "poi": 8003,
        "navigation": 8004,
    }
    results: dict[str, str] = {}
    for name, port in services.items():
        status = "down"
        if _is_port_open(host, port):
            try:
                conn = http.client.HTTPConnection(host, port, timeout=0.4)
                conn.request("GET", "/health")
                resp = conn.getresponse()
                body = resp.read(256)  # small read
                conn.close()
                if resp.status == 200:
                    # Accept plain OK or small JSON with status ok/OK
                    try:
                        txt = body.decode("utf-8", errors="ignore").strip()
                        if not txt:
                            pass
                        elif txt.lower() == "ok":
                            status = "running"
                        else:
                            # Try JSON
                            try:
                                parsed = json.loads(txt)
                                s = str(parsed.get("status", "")).lower()
                                if s == "ok":
                                    status = "running"
                            except Exception:
                                # Non-JSON but contains OK token
                                if "ok" in txt.lower():
                                    status = "running"
                    except Exception:
                        pass
            except Exception:
                pass
        results[name] = status
    return results


def _check_port_availability(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, port))


def _start_mcp_process(func, name: str):
    p = multiprocessing.Process(target=func, name=name, daemon=True)
    p.start()
    MCP_PROCESSES.append(p)


# React frontend static files serving setup: Assumes build output is in ./public folder
directory_path = os.path.dirname(os.path.abspath(__file__))
# Root of built frontend (contains index.html and a 'static' subfolder)
build_root = os.path.join(directory_path, "public")
assets_dir = os.path.join(build_root, "static")

if not os.path.isdir(assets_dir):
    logger.warning(f"Static assets directory not found: {assets_dir}")

# Mount only the assets subdirectory so requests to /static/js/... resolve correctly
app.mount("/static", StaticFiles(directory=assets_dir), name="static")


@app.middleware("http")
async def robots_wildcard(request, call_next):
    # Serve any root-level robots*.txt (e.g. /robots.txt, /robots933456.txt, /robots-any.txt)
    path = request.url.path
    if (
        path.startswith("/robots")
        and path.endswith(".txt")
        and "/" not in path[1:].replace(path.split("/")[-1], "")  # ensure root-level
    ):
        return PlainTextResponse("User-agent: *\nDisallow:\n", status_code=200)
    return await call_next(request)


# Root must be defined BEFORE the catch-all
@app.get("/")
async def serve_root():
    index_path = os.path.join(build_root, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return {"message": "Connected Car Platform API", "frontend": "not built"}


@app.get("/{full_path:path}")
async def serve_react_app(full_path: str):
    # Don't intercept API or static asset requests
    if full_path.startswith("api/") or full_path.startswith("static/"):
        raise HTTPException(status_code=404, detail="API or static asset not found")
    index_path = os.path.join(build_root, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Frontend not built")


# End of React frontend serving setup


if __name__ == "__main__":
    # Suppress Windows-specific ConnectionResetError during shutdown
    if sys.platform == "win32":
        def suppress_connection_reset(loop, context):
            """Suppress ConnectionResetError on Windows during shutdown"""
            if "exception" in context:
                exc = context["exception"]
                if isinstance(exc, ConnectionResetError):
                    # This is expected during Windows socket cleanup
                    return
            loop.default_exception_handler(context)
        
        # Set custom exception handler for asyncio
        try:
            loop = asyncio.get_event_loop()
            loop.set_exception_handler(suppress_connection_reset)
        except RuntimeError:
            pass  # No event loop yet, will be created by uvicorn
    
    # Prevent multiple server instances
    if _SERVER_INSTANCE_STARTED:
        logger.warning("Server instance already started, skipping...")
        sys.exit(0)

    _SERVER_INSTANCE_STARTED = True

    host = os.getenv("API_HOST", "0.0.0.0")
    # Azure App Service behavior:
    # - Externally, App Service always listens on 80 (HTTP) / 443 (HTTPS).
    # - Internally, your app must bind to the port specified in the PORT env variable.
    # - If you hardcode a port (e.g., 8000), configure WEBSITES_PORT in App Settings so Azure maps traffic correctly.
    # Here: prefer PORT (runtime-assigned) and fallback to WEBSITES_PORT if set.
    dynamic_port = os.getenv("PORT") or os.getenv("WEBSITES_PORT")

    port = int(dynamic_port or 8000)
    logger.info(f"Starting. Using port {port}.")

    # Check if port is already in use
    _check_port_availability(host, port)

    logger.info(f"Starting Connected Car Platform server at http://{host}:{port}")
    ENABLE_MCP = os.getenv("ENABLE_MCP", "true").lower() == "true"
    if ENABLE_MCP:
        logger.info("MCP integration enabled")
        _start_mcp_process(start_weather_server, "mcp_weather")
        _start_mcp_process(start_navigation_server, "mcp_navigation")
        _start_mcp_process(start_traffic_server, "mcp_traffic")
        _start_mcp_process(start_poi_server, "mcp_poi")

    # Start the FastAPI app with explicit configuration
    logger.info("Initializing FastAPI application...")
    try:
        # Explicitly disable reload and set worker count to 1
        uvicorn.run(
            app,
            host=host,
            port=port,
            reload=False,  # explicit for clarity
            workers=1,  # Single worker process
            log_level=log_level.lower(),
        )
    except KeyboardInterrupt:
        logger.info("Server shutdown by user (Ctrl+C)")
    except ConnectionResetError as e:
        # Windows-specific error during shutdown - safe to ignore
        if "WinError 10054" in str(e):
            logger.debug(f"Connection reset during shutdown (expected on Windows): {e}")
        else:
            logger.error(f"Connection error: {e}")
    except Exception as e:
        logger.critical(f"API server failed to start: {e}")
        raise
    finally:
        _SERVER_INSTANCE_STARTED = False
