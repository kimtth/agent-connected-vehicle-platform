import datetime
import uuid
from typing import Annotated

from agent_framework import tool
from vehicle_azure.cosmos_db import get_cosmos_client
from utils.logging_config import get_logger
from utils.vehicle_object_utils import notification_to_dict
from agents.base.base_agent import format_tool_response
from models.notification import Notification
from pydantic import Field

logger = get_logger(__name__)

_PLUGIN = "AlertsNotificationsPlugin"


@tool(name="handle_alert_status", description="Check the status of all vehicle alerts", approval_mode="never_require")
async def handle_alert_status(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID to check")] = "",
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response("Please specify which vehicle you'd like to check alert status for.", success=False, plugin_name=_PLUGIN)
    try:
        await cosmos_client.ensure_connected()
        alerts_raw = await cosmos_client.list_notifications(vehicle_id)
        alerts = [notification_to_dict(a) for a in alerts_raw]
        alerts = [
            a for a in alerts
            if a.get("type", "").endswith("_alert") or a.get("severity", "") in ["high", "critical"]
            or a.get("Type", "").endswith("_alert") or a.get("Severity", "") in ["high", "critical"]
        ]
        if not alerts:
            return format_tool_response("There are no active alerts for your vehicle at this time.", data={"alerts": [], "vehicleId": vehicle_id}, plugin_name=_PLUGIN)
        unack = [a for a in alerts if not a.get("read", a.get("Read", False))]
        text = "\n".join([
            f"* {(a.get('type') or a.get('Type','')).replace('_',' ').title()}: "
            f"{a.get('message', a.get('Message','No message'))} "
            f"({a.get('severity', a.get('Severity','medium'))} severity, "
            f"{'unacknowledged' if not a.get('read', a.get('Read', False)) else 'acknowledged'})"
            for a in alerts
        ])
        return format_tool_response(
            f"Alert status: {len(alerts)} alerts, {len(unack)} unacknowledged.\n\n{text}",
            data={"alerts": alerts, "unacknowledgedCount": len(unack), "vehicleId": vehicle_id},
            function_name="handle_alert_status", plugin_name=_PLUGIN,
        )
    except Exception as e:
        logger.error(f"Error retrieving vehicle alerts: {e}")
        return format_tool_response("I'm having trouble retrieving your vehicle's alert information. Please try again later.", success=False, function_name="handle_alert_status", plugin_name=_PLUGIN)


@tool(name="handle_speed_alert", description="Set a speed alert for a vehicle", approval_mode="never_require")
async def handle_speed_alert(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID to set speed alert for")] = "",
    speed_limit: Annotated[float, Field(description="Speed limit in km/h (20-200)")] = 120.0,
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response("Please specify which vehicle you'd like to set a speed alert for.", success=False, plugin_name=_PLUGIN)
    try:
        await cosmos_client.ensure_connected()
        notification_obj = Notification(
            id=str(uuid.uuid4()),
            notification_id=str(uuid.uuid4()),
            vehicle_id=vehicle_id,
            type="speed_alert",
            message=f"Speed alert set for {speed_limit} km/h",
            timestamp=datetime.datetime.now().isoformat(),
            read=False,
            severity="medium",
            source="system",
            action_required=False,
            parameters={"speedLimit": speed_limit},
        )
        await cosmos_client.create_notification(notification_obj.model_dump(by_alias=True))
        return format_tool_response(
            f"I've set a speed alert for {speed_limit} km/h. You'll receive a notification if the vehicle exceeds this speed.",
            data={"action": "setSpeedAlert", "vehicleId": vehicle_id, "speedLimit": speed_limit, "notification": notification_obj.model_dump(by_alias=True)},
            function_name="handle_speed_alert", plugin_name=_PLUGIN,
        )
    except Exception as e:
        logger.error(f"Error setting speed alert: {e}")
        return format_tool_response("I encountered an error when trying to set the speed alert. Please try again later.", success=False, function_name="handle_speed_alert", plugin_name=_PLUGIN)


@tool(name="handle_curfew_alert", description="Set a curfew alert for a vehicle", approval_mode="never_require")
async def handle_curfew_alert(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID to set curfew alert for")] = "",
    start_time: Annotated[str, Field(description="Curfew start time (HH:MM)")] = "22:00",
    end_time: Annotated[str, Field(description="Curfew end time (HH:MM)")] = "06:00",
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response("Please specify which vehicle you'd like to set a curfew alert for.", success=False, plugin_name=_PLUGIN)
    try:
        await cosmos_client.ensure_connected()
        notification_obj = Notification(
            id=str(uuid.uuid4()),
            notification_id=str(uuid.uuid4()),
            vehicle_id=vehicle_id,
            type="curfew_alert",
            message=f"Curfew alert set from {start_time} to {end_time}",
            timestamp=datetime.datetime.now().isoformat(),
            read=False,
            severity="medium",
            source="system",
            action_required=False,
            parameters={"startTime": start_time, "endTime": end_time},
        )
        await cosmos_client.create_notification(notification_obj.model_dump(by_alias=True))
        return format_tool_response(
            f"I've set a curfew alert from {start_time} to {end_time}. You'll receive a notification if the vehicle is used during these hours.",
            data={"action": "setCurfewAlert", "vehicleId": vehicle_id, "startTime": start_time, "endTime": end_time, "notification": notification_obj.model_dump(by_alias=True)},
            function_name="handle_curfew_alert", plugin_name=_PLUGIN,
        )
    except Exception as e:
        logger.error(f"Error setting curfew alert: {e}")
        return format_tool_response("I encountered an error when trying to set the curfew alert. Please try again later.", success=False, function_name="handle_curfew_alert", plugin_name=_PLUGIN)


@tool(name="handle_battery_alert", description="Set a battery alert for a vehicle", approval_mode="never_require")
async def handle_battery_alert(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID to set battery alert for")] = "",
    threshold: Annotated[float, Field(description="Battery threshold percentage (5-50)")] = 20.0,
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response("Please specify which vehicle you'd like to set a battery alert for.", success=False, plugin_name=_PLUGIN)
    try:
        await cosmos_client.ensure_connected()
        notification_obj = Notification(
            id=str(uuid.uuid4()),
            notification_id=str(uuid.uuid4()),
            vehicle_id=vehicle_id,
            type="battery_alert",
            message=f"Battery alert set for {threshold}%",
            timestamp=datetime.datetime.now().isoformat(),
            read=False,
            severity="medium",
            source="system",
            action_required=False,
            parameters={"threshold": threshold},
        )
        await cosmos_client.create_notification(notification_obj.model_dump(by_alias=True))
        return format_tool_response(
            f"I've set a battery alert for {threshold}%. You'll receive a notification if the battery level falls below this threshold.",
            data={"action": "setBatteryAlert", "vehicleId": vehicle_id, "threshold": threshold, "notification": notification_obj.model_dump(by_alias=True)},
            function_name="handle_battery_alert", plugin_name=_PLUGIN,
        )
    except Exception as e:
        logger.error(f"Error setting battery alert: {e}")
        return format_tool_response("I encountered an error when trying to set the battery alert. Please try again later.", success=False, function_name="handle_battery_alert", plugin_name=_PLUGIN)


@tool(name="handle_notification_settings", description="View and adjust notification settings", approval_mode="never_require")
async def handle_notification_settings(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID to inspect settings for")] = "",
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response("Please specify which vehicle you'd like to check notification settings for.", success=False, plugin_name=_PLUGIN)
    try:
        await cosmos_client.ensure_connected()
        notifications_raw = await cosmos_client.list_notifications(vehicle_id)
        notifications = [notification_to_dict(n) for n in notifications_raw]
        types = {
            (n.get("type") or n.get("Type") or "")
            for n in notifications
            if (n.get("type") or n.get("Type") or "").endswith("_alert")
        }
        settings = {
            "speedAlerts": "speed_alert" in types,
            "curfewAlerts": "curfew_alert" in types,
            "batteryAlerts": "battery_alert" in types,
            "maintenanceAlerts": ("maintenance_alert" in types) or ("service_alert" in types),
            "geofenceAlerts": "geofence_alert" in types,
            "notificationChannels": {"email": True, "push": True, "sms": False},
        }
        enabled = [k for k, v in settings.items() if v and k != "notificationChannels"]
        ch = [c for c, v in settings["notificationChannels"].items() if v]
        text = f"Enabled alerts: {', '.join(enabled) if enabled else 'None'}\nNotification channels: {', '.join(ch)}"
        return format_tool_response(
            f"Notification settings for your vehicle:\n\n{text}",
            data={"settings": settings, "vehicleId": vehicle_id},
            function_name="handle_notification_settings", plugin_name=_PLUGIN,
        )
    except Exception as e:
        logger.error(f"Error retrieving notification settings: {e}")
        return format_tool_response("I'm having trouble retrieving your notification settings. Please try again later.", success=False, function_name="handle_notification_settings", plugin_name=_PLUGIN)


ALERTS_NOTIFICATIONS_TOOLS = [handle_alert_status, handle_speed_alert, handle_curfew_alert, handle_battery_alert, handle_notification_settings]
