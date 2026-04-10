import datetime
from typing import Any, Dict, Annotated
import uuid

from agent_framework import tool
from vehicle_azure.cosmos_db import get_cosmos_client
from utils.logging_config import get_logger
from agents.base.base_agent import format_tool_response
from models.command import Command
from pydantic import Field

logger = get_logger(__name__)

_PLUGIN = "VehicleFeatureControlPlugin"


async def _apply_status_update(vehicle_id: str, patch: Dict[str, Any]):
    """Merge patch into vehicle status and persist."""
    cosmos_client = get_cosmos_client()
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


@tool(name="handle_lights_control", description="Control vehicle lights (headlights, interior, etc.)", approval_mode="never_require")
async def handle_lights_control(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID whose lights to control")] = "",
    light_type: Annotated[str, Field(description="Type of light: headlights, interior_lights, or hazard_lights")] = "headlights",
    action: Annotated[str, Field(description="Action: on or off")] = "on",
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response(
            "Please specify which vehicle you'd like to control lights for.",
            success=False, plugin_name=_PLUGIN,
        )

    try:
        await cosmos_client.ensure_connected()

        command_obj = Command(
            id=str(uuid.uuid4()),
            command_id=f"lights_{action}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
            vehicle_id=vehicle_id,
            command_type=f"lights_{action}",
            parameters={"lightType": light_type},
            status="sent",
            timestamp=datetime.datetime.now().isoformat(),
            priority="normal",
        )
        await cosmos_client.create_command(command_obj.model_dump(by_alias=True))

        await _apply_status_update(
            vehicle_id,
            {
                "lights": {
                    "type": light_type,
                    "state": action,
                    "updatedAt": datetime.datetime.now().isoformat(),
                }
            },
        )
        return format_tool_response(
            f"I've turned {action} the {light_type.replace('_', ' ')} for your vehicle.",
            data={
                "action": f"lights_{action}",
                "vehicleId": vehicle_id,
                "lightType": light_type,
                "commandId": command_obj.command_id,
            },
            function_name="handle_lights_control", plugin_name=_PLUGIN,
        )
    except Exception:
        return format_tool_response(
            "I encountered an error while controlling the lights. Please try again.",
            success=False, function_name="handle_lights_control", plugin_name=_PLUGIN,
        )


@tool(name="handle_climate_control", description="Control vehicle climate settings", approval_mode="never_require")
async def handle_climate_control(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID whose climate to control")] = "",
    temperature: Annotated[int, Field(description="Desired temperature in Celsius (16-30)")] = 22,
    mode: Annotated[str, Field(description="Climate mode: set_temperature, heating, or cooling")] = "set_temperature",
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response(
            "Please specify which vehicle you'd like to control climate for.",
            success=False, plugin_name=_PLUGIN,
        )

    try:
        await cosmos_client.ensure_connected()

        command_obj = Command(
            id=str(uuid.uuid4()),
            command_id=f"climate_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
            vehicle_id=vehicle_id,
            command_type="climate_control",
            parameters={
                "action": mode,
                "temperature": temperature,
                "auto": True
            },
            status="sent",
            timestamp=datetime.datetime.now().isoformat(),
            priority="normal",
        )
        await cosmos_client.create_command(command_obj.model_dump(by_alias=True))

        await _apply_status_update(
            vehicle_id,
            {
                "climate": {
                    "mode": mode,
                    "temperatureC": temperature,
                    "auto": True,
                    "updatedAt": datetime.datetime.now().isoformat(),
                }
            },
        )
        return format_tool_response(
            f"I've set the climate control to {temperature}°C with {mode} mode.",
            data={
                "action": "climate_control",
                "vehicleId": vehicle_id,
                "temperature": temperature,
                "mode": mode,
                "commandId": command_obj.command_id,
            },
            function_name="handle_climate_control", plugin_name=_PLUGIN,
        )
    except Exception:
        return format_tool_response(
            "I encountered an error while adjusting the climate control. Please try again.",
            success=False, function_name="handle_climate_control", plugin_name=_PLUGIN,
        )


@tool(name="handle_windows_control", description="Control vehicle windows", approval_mode="never_require")
async def handle_windows_control(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID whose windows to control")] = "",
    action: Annotated[str, Field(description="Action: up (close) or down (open)")] = "up",
    window_position: Annotated[str, Field(description="Which windows: all, driver, or passenger")] = "all",
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response(
            "Please specify which vehicle you'd like to control windows for.",
            success=False, plugin_name=_PLUGIN,
        )

    try:
        await cosmos_client.ensure_connected()

        command_obj = Command(
            id=str(uuid.uuid4()),
            command_id=f"windows_{action}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
            vehicle_id=vehicle_id,
            command_type=f"windows_{action}",
            parameters={"windows": window_position},
            status="sent",
            timestamp=datetime.datetime.now().isoformat(),
            priority="normal",
        )
        await cosmos_client.create_command(command_obj.model_dump(by_alias=True))

        await _apply_status_update(
            vehicle_id,
            {
                "windows": {
                    "target": window_position,
                    "state": action,
                    "updatedAt": datetime.datetime.now().isoformat(),
                }
            },
        )
        window_text = f"{window_position} windows" if window_position != "all" else "all windows"
        action_text = "rolled up" if action == "up" else "rolled down"

        return format_tool_response(
            f"I've {action_text} the {window_text} for your vehicle.",
            data={
                "action": f"windows_{action}",
                "vehicleId": vehicle_id,
                "windows": window_position,
                "commandId": command_obj.command_id,
            },
            function_name="handle_windows_control", plugin_name=_PLUGIN,
        )
    except Exception:
        return format_tool_response(
            "I encountered an error while controlling the windows. Please try again.",
            success=False, function_name="handle_windows_control", plugin_name=_PLUGIN,
        )


@tool(name="handle_feature_status", description="Get current vehicle feature status", approval_mode="never_require")
async def handle_feature_status(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID to get feature status for")] = "",
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response(
            "Please specify which vehicle to check.", success=False,
            plugin_name=_PLUGIN,
        )
    try:
        await cosmos_client.ensure_connected()
        status = await cosmos_client.get_vehicle_status(vehicle_id) or {}
        features = {
            "lights": status.get("lights"),
            "climate": status.get("climate"),
            "windows": status.get("windows"),
            "doorsLocked": status.get("doorsLocked"),
            "engineRunning": status.get("engineRunning"),
        }
        return format_tool_response(
            "Feature status retrieved.",
            data={"vehicleId": vehicle_id, "features": features},
            function_name="handle_feature_status", plugin_name=_PLUGIN,
        )
    except Exception:
        return format_tool_response(
            "Unable to retrieve feature status.",
            success=False, function_name="handle_feature_status", plugin_name=_PLUGIN,
        )


VEHICLE_FEATURE_CONTROL_TOOLS = [
    handle_lights_control,
    handle_climate_control,
    handle_windows_control,
    handle_feature_status,
]
