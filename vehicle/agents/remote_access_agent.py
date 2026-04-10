import datetime
import uuid
from typing import Dict, Any, Annotated

from agent_framework import tool
from vehicle_azure.cosmos_db import get_cosmos_client
from utils.logging_config import get_logger
from utils.vehicle_object_utils import find_vehicle
from agents.base.base_agent import format_tool_response
from models.command import Command
from pydantic import Field

logger = get_logger(__name__)

_PLUGIN = "RemoteAccessPlugin"


async def _apply_status_update(cosmos_client, vehicle_id: str, patch: Dict[str, Any]):
    try:
        current = await cosmos_client.get_vehicle_status(vehicle_id) or {}
        if not isinstance(current, dict):
            try:
                current = current.model_dump()
            except Exception:
                current = {}
        current.update(patch)
        if hasattr(cosmos_client, "update_vehicle_status"):
            await cosmos_client.update_vehicle_status(vehicle_id, current)
        elif hasattr(cosmos_client, "set_vehicle_status"):
            await cosmos_client.set_vehicle_status(vehicle_id, current)
        else:
            container = getattr(cosmos_client, "status_container", None)
            if container:
                await container.upsert_item({"id": vehicle_id, "vehicle_id": vehicle_id, **current})
    except Exception as e:
        logger.debug(f"Status update skipped ({vehicle_id}): {e}")


@tool(name="handle_door_lock", description="Handle a door lock/unlock request.", approval_mode="never_require")
async def handle_door_lock(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID to lock/unlock")] = "",
    lock: Annotated[bool, Field(description="True to lock, False to unlock")] = True,
) -> str:
    cosmos_client = get_cosmos_client()
    action = "lock" if lock else "unlock"
    if not vehicle_id:
        return format_tool_response("Please specify which vehicle you'd like to control.", success=False, plugin_name=_PLUGIN)

    try:
        await cosmos_client.ensure_connected()
        vehicles = await cosmos_client.list_vehicles()
        vehicle = find_vehicle(vehicles, vehicle_id)
        if not vehicle:
            return format_tool_response(f"Vehicle with ID {vehicle_id} not found.", success=False, plugin_name=_PLUGIN)

        command_type = "lock_doors" if lock else "unlock_doors"
        command_id = f"remote_access_{action}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"

        command_obj = Command(
            id=str(uuid.uuid4()),
            command_id=command_id,
            vehicle_id=vehicle_id,
            command_type=command_type.lower(),
            parameters={"doors": "all"},
            status="sent",
            timestamp=datetime.datetime.now().isoformat(),
            priority="normal",
        )
        await cosmos_client.create_command(command_obj.model_dump(by_alias=True))

        await _apply_status_update(cosmos_client, vehicle_id, {
            "doorsLocked": lock,
            "doorsUpdatedAt": datetime.datetime.now().isoformat(),
            "lastDoorCommandId": command_id,
        })
        return format_tool_response(
            f"I've {action}ed your vehicle doors.",
            data={"action": f"door_{action}", "vehicleId": vehicle_id, "commandId": command_id},
            function_name="handle_door_lock", plugin_name=_PLUGIN,
        )
    except Exception as e:
        logger.error(f"Error handling door lock request: {e}")
        return format_tool_response(
            f"I encountered an error while trying to {action} the doors. Please try again.",
            success=False, function_name="handle_door_lock", plugin_name=_PLUGIN,
        )


@tool(name="handle_engine_control", description="Handle remote engine start/stop request.", approval_mode="never_require")
async def handle_engine_control(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID to start/stop engine")] = "",
    start: Annotated[bool, Field(description="True to start engine, False to stop")] = True,
) -> str:
    cosmos_client = get_cosmos_client()
    action = "start" if start else "stop"
    if not vehicle_id:
        return format_tool_response(
            "Please specify which vehicle you'd like to control the engine for.",
            success=False, plugin_name=_PLUGIN,
        )

    try:
        await cosmos_client.ensure_connected()
        vehicles = await cosmos_client.list_vehicles()
        vehicle = find_vehicle(vehicles, vehicle_id)
        if not vehicle:
            return format_tool_response(f"Vehicle with ID {vehicle_id} not found.", success=False, plugin_name=_PLUGIN)

        command_type = "start_engine" if start else "stop_engine"
        command_id = f"engine_{action}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"

        command_obj = Command(
            id=str(uuid.uuid4()),
            command_id=command_id,
            vehicle_id=vehicle_id,
            command_type=command_type.lower(),
            parameters={"remote": True},
            status="sent",
            timestamp=datetime.datetime.now().isoformat(),
            priority="high",
        )
        await cosmos_client.create_command(command_obj.model_dump(by_alias=True))

        await _apply_status_update(cosmos_client, vehicle_id, {
            "engineRunning": start,
            "engineUpdatedAt": datetime.datetime.now().isoformat(),
            "lastEngineCommandId": command_id,
        })
        verb = "stopped" if action == "stop" else f"{action}ed"
        return format_tool_response(
            f"I've {verb} your vehicle engine remotely.",
            data={"action": f"engine_{action}", "vehicleId": vehicle_id, "commandId": command_id},
            function_name="handle_engine_control", plugin_name=_PLUGIN,
        )
    except Exception:
        return format_tool_response(
            f"I encountered an error while trying to {action} the engine. Please try again.",
            success=False, function_name="handle_engine_control", plugin_name=_PLUGIN,
        )


@tool(name="handle_horn_lights", description="Handle horn and lights activation to locate vehicle.", approval_mode="never_require")
async def handle_horn_lights(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID to activate horn/lights")] = "",
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response("vehicle_id is required", success=False, plugin_name=_PLUGIN)

    try:
        await cosmos_client.ensure_connected()
        command_id = f"horn_lights_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"

        command_obj = Command(
            id=str(uuid.uuid4()),
            command_id=command_id,
            vehicle_id=vehicle_id,
            command_type="horn_lights",
            parameters={"duration": 10},
            status="sent",
            timestamp=datetime.datetime.now().isoformat(),
            priority="normal",
        )
        await cosmos_client.create_command(command_obj.model_dump(by_alias=True))

        await _apply_status_update(cosmos_client, vehicle_id, {
            "locateMode": {
                "active": True,
                "durationSec": 10,
                "activatedAt": datetime.datetime.now().isoformat(),
                "commandId": command_id,
            }
        })
        return format_tool_response(
            "I've activated the horn and lights to help you locate your vehicle.",
            data={"action": "HORN_LIGHTS", "vehicleId": vehicle_id, "commandId": command_id},
            function_name="handle_horn_lights", plugin_name=_PLUGIN,
        )
    except Exception as e:
        logger.error(f"Error activating horn and lights: {e}")
        return format_tool_response(
            "I encountered an error while activating horn and lights. Please try again.",
            success=False, function_name="handle_horn_lights", plugin_name=_PLUGIN,
        )


REMOTE_ACCESS_TOOLS = [handle_door_lock, handle_engine_control, handle_horn_lights]
