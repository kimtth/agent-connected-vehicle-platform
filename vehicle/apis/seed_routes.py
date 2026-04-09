from fastapi import APIRouter, Body, HTTPException
from typing import Optional
from datetime import datetime, timezone
import uuid
import random
import logging

from azure.cosmos_db import get_cosmos_client
from models.seed import (
    SeedResult,
    BulkSeedRequest,
    BulkSeedConfig,
    BulkSeedCreated,
    BulkSeedSummary,
    SeedStatus,
)
from models.vehicle_profile import VehicleProfile
from models.status import VehicleStatus
from models.service import Service
from models.command import Command
from models.notification import Notification

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dev", tags=["Development Seeding"])
LAST_SEED_SUMMARY: Optional[BulkSeedSummary] = None


def _now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


@router.post("/seed", response_model=SeedResult)
async def seed_dev_data(vehicle_id: Optional[str] = None):
    """Create a test vehicle profile and initial status for development."""
    client = get_cosmos_client()
    if not await client.ensure_connected():
        raise HTTPException(status_code=503, detail="Database service unavailable")

    # Ensure vehicle_id
    vehicle_id = vehicle_id or str(uuid.uuid4())
    created_vehicle = False
    try:
        existing = await client.get_vehicle(vehicle_id)
        if not existing:
            profile = VehicleProfile(
                vehicle_id=vehicle_id,
                make="Demo",
                model="Car",
                year=2024,
                status="Active",
                last_location={"latitude": 43.6532, "longitude": -79.3832},
            )
            await client.create_vehicle(profile.model_dump(by_alias=True, exclude_none=True))
            created_vehicle = True

        status = VehicleStatus(
            vehicle_id=vehicle_id,
            battery=82,
            temperature=36,
            speed=0,
            oil_remaining=75,
            odometer=12456,
            engine_temp=70,
            timestamp=_now_iso(),
        )
        await client.update_vehicle_status(vehicle_id, status.model_dump(by_alias=True, exclude_none=True))

        return SeedResult(
            vehicle_id=vehicle_id,
            created_vehicle=created_vehicle,
            status_seeded=True,
        )
    except Exception as e:
        logger.error(f"Seed failed for {vehicle_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Seeding failed: {str(e)}")


@router.post("/seed/bulk", response_model=BulkSeedSummary)
async def seed_dev_data_bulk(req: BulkSeedRequest = Body(...)):
    client = get_cosmos_client()
    if not await client.ensure_connected():
        raise HTTPException(status_code=503, detail="Database service unavailable")

    cfg = BulkSeedConfig(
        vehicles=req.vehicles,
        commands_per_vehicle=req.commands_per_vehicle,
        notifications_per_vehicle=req.notifications_per_vehicle,
        services_per_vehicle=req.services_per_vehicle,
        statuses_per_vehicle=req.statuses_per_vehicle,
    )

    created = BulkSeedCreated(
        vehicles=0,
        statuses=0,
        services=0,
        commands=0,
        notifications=0,
        vehicle_ids=[],
    )

    makes = ["Tesla", "Toyota", "Ford", "BMW", "Hyundai"]
    models = ["Cyber Truck", "Model 3", "RAV4", "F-150", "X3", "Elantra"]
    service_codes = ["OIL_CHANGE", "TIRE_ROTATION", "BRAKE_SERVICE"]
    command_types = ["lock_doors", "unlock_doors", "start_engine", "stop_engine"]
    notification_types = ["service_reminder", "low_battery_alert", "speed_alert"]

    try:
        for _ in range(cfg.vehicles):
            vehicle_id = str(uuid.uuid4())
            profile = VehicleProfile(
                vehicle_id=vehicle_id,
                make=random.choice(makes),
                model=random.choice(models),
                year=random.choice([2021, 2022, 2023, 2024]),
                status=random.choice(["Active", "Inactive", "Maintenance"]),
                last_location={"latitude": 43.6532, "longitude": -79.3832},
            )
            await client.create_vehicle(profile.model_dump(by_alias=True, exclude_none=True))
            created.vehicles += 1
            created.vehicle_ids.append(vehicle_id)

            for _n in range(cfg.statuses_per_vehicle):
                status = VehicleStatus(
                    vehicle_id=vehicle_id,
                    battery=random.randint(50, 100),
                    temperature=random.randint(15, 40),
                    speed=random.choice([0, random.randint(10, 120)]),
                    oil_remaining=random.randint(40, 100),
                    odometer=random.randint(1000, 150000),
                    engine_temp=random.randint(60, 110),
                    timestamp=_now_iso(),
                )
                await client.update_vehicle_status(vehicle_id, status.model_dump(by_alias=True, exclude_none=True))
                created.statuses += 1

            for _n in range(cfg.services_per_vehicle):
                service = Service(
                    id=str(uuid.uuid4()),
                    vehicle_id=vehicle_id,
                    service_code=random.choice(service_codes),
                    description="Auto-generated test service",
                    start_date=_now_iso(),
                    end_date=_now_iso(),
                    next_service_date=_now_iso(),
                    mileage=random.randint(1000, 150000),
                    next_service_mileage=random.randint(1000, 150000) + 5000,
                    cost=round(random.uniform(50.0, 500.0), 2),
                    location="Service Center 1",
                    technician="Tech A",
                    invoice_number=f"INV-{random.randint(10000, 99999)}",
                    service_status="Completed",
                    service_type=random.choice(["Scheduled", "Repair"]),
                )
                await client.create_service(service.model_dump(by_alias=True, exclude_none=True))
                created.services += 1

            for _n in range(cfg.commands_per_vehicle):
                command = Command(
                    id=str(uuid.uuid4()),
                    command_id=str(uuid.uuid4()),
                    vehicle_id=vehicle_id,
                    command_type=random.choice(command_types),
                    parameters={
                        'param1': 'value1',
                        'param2': 'value2'
                    },
                    status=random.choice(["Sent", "Processing", "Completed"]),
                    timestamp=_now_iso(),
                )
                await client.create_command(command.model_dump(by_alias=True, exclude_none=True))
                created.commands += 1

            for _n in range(cfg.notifications_per_vehicle):
                notification = Notification(
                    id=str(uuid.uuid4()),
                    vehicle_id=vehicle_id,
                    type=random.choice(notification_types),
                    message="Auto-generated test notification",
                    timestamp=_now_iso(),
                    read=False,
                    severity=random.choice(["low", "medium", "high"]),
                    source=random.choice(["Vehicle", "System"]),
                    action_required=False,
                )
                await client.create_notification(notification.model_dump(by_alias=True, exclude_none=True))
                created.notifications += 1

        summary = BulkSeedSummary(
            ok=True,
            config=cfg,
            created=created,
            azure_cosmos_connected=True,
        )
        global LAST_SEED_SUMMARY
        LAST_SEED_SUMMARY = summary
        return summary
    except Exception as e:
        logger.error(f"Bulk seed failed: {e}")
        raise HTTPException(status_code=500, detail=f"Bulk seeding failed: {str(e)}")


@router.get("/seed/status", response_model=SeedStatus)
async def seed_status():
    enabled, connected = _cosmos_status()
    return SeedStatus(
        azure_cosmos_enabled=enabled,
        azure_cosmos_connected=connected,
        last_seed=LAST_SEED_SUMMARY,
    )