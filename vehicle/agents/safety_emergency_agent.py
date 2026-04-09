import datetime
import uuid
from typing import Dict, Any, Annotated

from agent_framework import tool
from azure.cosmos_db import get_cosmos_client
from utils.logging_config import get_logger
from utils.vehicle_object_utils import find_vehicle, extract_location
from agents.base.base_agent import format_tool_response
from models.command import Command
from models.notification import Notification
from pydantic import Field

logger = get_logger(__name__)

_PLUGIN = "SafetyEmergencyPlugin"


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


@tool(name="handle_emergency_call", description="Handle emergency calls", approval_mode="never_require")
async def handle_emergency_call(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID needing emergency assistance")] = "",
) -> str:
    """Handle an emergency call request."""
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response(
            "Please specify which vehicle needs emergency assistance.",
            success=False, plugin_name=_PLUGIN,
        )

    try:
        await cosmos_client.ensure_connected()

        vehicles = await cosmos_client.list_vehicles()
        vehicle = find_vehicle(vehicles, vehicle_id)
        if not vehicle:
            return format_tool_response(
                f"Vehicle with ID {vehicle_id} not found.", success=False,
                plugin_name=_PLUGIN,
            )
        vehicle_status = await cosmos_client.get_vehicle_status(vehicle_id)
        location = extract_location(vehicle_status, vehicle)

        command_id = f"emergency_call_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        command_obj = Command(
            id=str(uuid.uuid4()),
            command_id=command_id,
            vehicle_id=vehicle_id,
            command_type="emergency_call",
            parameters={
                "location": location,
                "timestamp": datetime.datetime.now().isoformat(),
                "callType": "manual",
            },
            status="sent",
            timestamp=datetime.datetime.now().isoformat(),
            priority="critical",
        )
        await cosmos_client.create_command(command_obj.model_dump(by_alias=True))

        notification_id = str(uuid.uuid4())
        notification_obj = Notification(
            id=str(uuid.uuid4()),
            notification_id=notification_id,
            vehicle_id=vehicle_id,
            type="emergency_call",
            message="Emergency call initiated. Help is on the way.",
            timestamp=datetime.datetime.now().isoformat(),
            read=False,
            severity="critical",
            source="system",
            action_required=True,
            action_url=f"/emergency/{notification_id}",
        )
        await cosmos_client.create_notification(notification_obj.model_dump(by_alias=True))

        await _apply_status_update(
            vehicle_id,
            {
                "emergency": {
                    "callActive": True,
                    "type": "manual",
                    "updatedAt": datetime.datetime.now().isoformat(),
                }
            },
        )
        return format_tool_response(
            "Emergency call has been initiated. Help is on the way. "
            "Stay on the line and follow any instructions from emergency services.",
            data={
                "action": "emergency_call",
                "vehicleId": vehicle_id,
                "status": "initiated",
                "notification": notification_obj.model_dump(by_alias=True),
                "location": location,
                "commandId": command_id,
            },
            function_name="handle_emergency_call", plugin_name=_PLUGIN,
        )

    except Exception as e:
        logger.error(f"Error handling emergency call: {str(e)}")
        return format_tool_response(
            "I encountered an error while trying to initiate the emergency call. "
            "Please try again or call emergency services directly.",
            success=False, function_name="handle_emergency_call", plugin_name=_PLUGIN,
        )


@tool(name="handle_collision_alert", description="Handle collision alerts", approval_mode="never_require")
async def handle_collision_alert(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID involved in collision")] = "",
) -> str:
    """Handle a collision alert."""
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response(
            "Please specify which vehicle was involved in the collision.",
            success=False, plugin_name=_PLUGIN,
        )

    try:
        await cosmos_client.ensure_connected()

        vehicles = await cosmos_client.list_vehicles()
        vehicle = find_vehicle(vehicles, vehicle_id)
        if not vehicle:
            return format_tool_response(
                f"Vehicle with ID {vehicle_id} not found.", success=False,
                plugin_name=_PLUGIN,
            )

        vehicle_status = await cosmos_client.get_vehicle_status(vehicle_id)
        location = extract_location(vehicle_status, vehicle)

        command_id = f"collision_alert_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        command_obj = Command(
            id=str(uuid.uuid4()),
            command_id=command_id,
            vehicle_id=vehicle_id,
            command_type="collision_alert",
            parameters={
                "location": location,
                "timestamp": datetime.datetime.now().isoformat(),
                "severity": "high",
            },
            status="sent",
            timestamp=datetime.datetime.now().isoformat(),
            priority="critical",
        )
        await cosmos_client.create_command(command_obj.model_dump(by_alias=True))

        notification_id = str(uuid.uuid4())
        notification_obj = Notification(
            id=str(uuid.uuid4()),
            notification_id=notification_id,
            vehicle_id=vehicle_id,
            type="collision_alert",
            message="Collision detected. Emergency services have been notified.",
            timestamp=datetime.datetime.now().isoformat(),
            read=False,
            severity="critical",
            source="vehicle",
            action_required=True,
            action_url=f"/emergency/{notification_id}",
        )
        await cosmos_client.create_notification(notification_obj.model_dump(by_alias=True))

        await _apply_status_update(
            vehicle_id,
            {
                "collision": {
                    "detected": True,
                    "severity": "high",
                    "updatedAt": datetime.datetime.now().isoformat(),
                }
            },
        )
        return format_tool_response(
            "I've detected a collision and notified emergency services. "
            "Are you okay? Do you need any immediate assistance?",
            data={
                "action": "collision_alert",
                "vehicleId": vehicle_id,
                "status": "processed",
                "notification": notification_obj.model_dump(by_alias=True),
                "location": location,
                "commandId": command_id,
            },
            function_name="handle_collision_alert", plugin_name=_PLUGIN,
        )

    except Exception as e:
        logger.error(f"Error handling collision alert: {str(e)}")
        return format_tool_response(
            "I encountered an error while processing the collision alert. "
            "Please call emergency services directly if you need immediate assistance.",
            success=False, function_name="handle_collision_alert", plugin_name=_PLUGIN,
        )


@tool(name="handle_theft_notification", description="Handle theft notifications", approval_mode="never_require")
async def handle_theft_notification(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID suspected stolen")] = "",
) -> str:
    """Handle a theft notification."""
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response(
            "Please specify which vehicle you believe has been stolen.",
            success=False, plugin_name=_PLUGIN,
        )

    try:
        await cosmos_client.ensure_connected()

        vehicles = await cosmos_client.list_vehicles()
        vehicle = find_vehicle(vehicles, vehicle_id)
        if not vehicle:
            return format_tool_response(
                f"Vehicle with ID {vehicle_id} not found.", success=False,
                plugin_name=_PLUGIN,
            )

        vehicle_status = await cosmos_client.get_vehicle_status(vehicle_id)
        location = extract_location(vehicle_status, vehicle)

        command_id = f"theft_notification_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        command_obj = Command(
            id=str(uuid.uuid4()),
            command_id=command_id,
            vehicle_id=vehicle_id,
            command_type="theft_notification",
            parameters={
                "location": location,
                "timestamp": datetime.datetime.now().isoformat(),
                "reportedBy": "owner",
            },
            status="sent",
            timestamp=datetime.datetime.now().isoformat(),
            priority="high",
        )
        await cosmos_client.create_command(command_obj.model_dump(by_alias=True))

        notification_id = str(uuid.uuid4())
        notification_obj = Notification(
            id=str(uuid.uuid4()),
            notification_id=notification_id,
            vehicle_id=vehicle_id,
            type="theft_alert",
            message="Potential vehicle theft detected. Authorities have been notified.",
            timestamp=datetime.datetime.now().isoformat(),
            read=False,
            severity="high",
            source="system",
            action_required=True,
            action_url=f"/security/{notification_id}",
        )
        await cosmos_client.create_notification(notification_obj.model_dump(by_alias=True))

        await _apply_status_update(
            vehicle_id,
            {
                "theft": {
                    "reported": True,
                    "reportedAt": datetime.datetime.now().isoformat(),
                }
            },
        )
        return format_tool_response(
            "I've recorded your vehicle theft report and notified the authorities. "
            "The vehicle's location is being tracked, and you'll receive updates on the situation.",
            data={
                "action": "theft_notification",
                "vehicleId": vehicle_id,
                "status": "processed",
                "notification": notification_obj.model_dump(by_alias=True),
                "location": location,
                "commandId": command_id,
            },
            function_name="handle_theft_notification", plugin_name=_PLUGIN,
        )

    except Exception as e:
        logger.error(f"Error handling theft notification: {str(e)}")
        return format_tool_response(
            "I encountered an error while processing the theft notification. "
            "Please contact authorities directly to report the theft.",
            success=False, function_name="handle_theft_notification", plugin_name=_PLUGIN,
        )


@tool(name="handle_sos", description="Handle SOS requests", approval_mode="never_require")
async def handle_sos(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID for SOS request")] = "",
) -> str:
    """Handle an SOS request with immediate emergency response."""
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response(
            "Please specify which vehicle needs SOS assistance.",
            success=False, plugin_name=_PLUGIN,
        )

    try:
        await cosmos_client.ensure_connected()

        vehicles = await cosmos_client.list_vehicles()
        vehicle = find_vehicle(vehicles, vehicle_id)
        if not vehicle:
            return format_tool_response(
                f"Vehicle with ID {vehicle_id} not found.", success=False,
                plugin_name=_PLUGIN,
            )

        vehicle_status = await cosmos_client.get_vehicle_status(vehicle_id)
        location = extract_location(vehicle_status, vehicle)

        command_id = f"sos_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        command_obj = Command(
            id=str(uuid.uuid4()),
            command_id=command_id,
            vehicle_id=vehicle_id,
            command_type="sos_request",
            parameters={
                "location": location,
                "timestamp": datetime.datetime.now().isoformat(),
                "priority": "critical",
            },
            status="sent",
            timestamp=datetime.datetime.now().isoformat(),
            priority="critical",
        )
        await cosmos_client.create_command(command_obj.model_dump(by_alias=True))

        notification_obj = Notification(
            id=str(uuid.uuid4()),
            notification_id=str(uuid.uuid4()),
            vehicle_id=vehicle_id,
            type="sos_request",
            message="SOS request activated. Emergency services have been contacted.",
            timestamp=datetime.datetime.now().isoformat(),
            read=False,
            severity="critical",
            source="system",
            action_required=True,
            action_url=f"/emergency/sos/{command_id}",
        )
        await cosmos_client.create_notification(notification_obj.model_dump(by_alias=True))

        await _apply_status_update(
            vehicle_id,
            {
                "sos": {
                    "active": True,
                    "triggeredAt": datetime.datetime.now().isoformat(),
                }
            },
        )
        return format_tool_response(
            "SOS request has been activated. Emergency services have been contacted and "
            "are being dispatched to your location. Please stay calm and wait for assistance.",
            data={
                "action": "sos_request",
                "vehicleId": vehicle_id,
                "status": "activated",
                "notification": notification_obj.model_dump(by_alias=True),
                "location": location,
                "commandId": command_id,
            },
            function_name="handle_sos", plugin_name=_PLUGIN,
        )

    except Exception as e:
        logger.error(f"Error handling SOS request: {e}")
        return format_tool_response(
            "I encountered an error while processing the SOS request. "
            "Please call emergency services directly at your local emergency number.",
            success=False, function_name="handle_sos", plugin_name=_PLUGIN,
        )


SAFETY_EMERGENCY_TOOLS = [
    handle_emergency_call,
    handle_collision_alert,
    handle_theft_notification,
    handle_sos,
]
