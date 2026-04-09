"""
Diagnostics & Battery Agent for the Connected Car Platform.

This agent oversees vehicle diagnostics, battery status, and system health reports.
"""

from typing import Dict, Any, Optional, List, Annotated
from datetime import datetime, timedelta, timezone

from agent_framework import tool
from azure.cosmos_db import get_cosmos_client
from utils.logging_config import get_logger
from utils.vehicle_object_utils import find_vehicle, ensure_dict
from agents.base.base_agent import format_tool_response
from models.base import BaseSchemaModel
from pydantic import Field

logger = get_logger(__name__)

_PLUGIN = "DiagnosticsBatteryPlugin"


# Data models for structured responses
class DiagnosticsData(BaseSchemaModel):
    diagnostics: Dict[str, Any]
    issues: List[str]
    status: str
    vehicle_id: str


class BatteryData(BaseSchemaModel):
    # electric
    level: Optional[int] = None
    range_km: Optional[int] = None
    health: Optional[int] = None
    charging: Optional[bool] = None
    charge_rate_kw: Optional[int] = None
    estimated_replacement: Optional[str] = None
    # combustion
    voltage: Optional[float] = None
    last_replaced: Optional[str] = None
    # shared
    vehicle_type: Optional[str] = None


class BatteryStatusData(BaseSchemaModel):
    battery: BatteryData
    vehicle_id: str
    vehicle_type: Optional[str] = None


class SystemHealthReport(BaseSchemaModel):
    overall_status: str
    components: Dict[str, str]
    issues: List[str]
    recommendations: List[str]


class SystemHealthData(BaseSchemaModel):
    system_health: SystemHealthReport
    vehicle_id: str
    failed_commands: int


class MaintenanceItem(BaseSchemaModel):
    type: str
    interval_miles: Optional[int] = None
    interval_months: Optional[int] = None
    last_service: Optional[str] = None
    next_due: Optional[str] = None
    status: Optional[str] = None
    next_due_mileage: Optional[int] = None


class MaintenanceCheckData(BaseSchemaModel):
    maintenance_items: List[MaintenanceItem]
    vehicle_id: str


def _coerce_datetime(iso_str: str) -> Optional[datetime]:
    """Safely parse ISO timestamps and normalize tz handling."""
    if not iso_str:
        return None
    try:
        ds = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ds)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        return None


@tool(name="handle_diagnostics", description="Run diagnostics on vehicle systems", approval_mode="never_require")
async def handle_diagnostics(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID to run diagnostics on")] = "",
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response(
            "Please specify which vehicle you'd like to run diagnostics for.",
            success=False, plugin_name=_PLUGIN,
        )

    try:
        await cosmos_client.ensure_connected()

        vehicle_status = await cosmos_client.get_vehicle_status(vehicle_id)
        if not vehicle_status:
            return format_tool_response(
                "No recent vehicle status data is available for diagnostics.",
                success=False, plugin_name=_PLUGIN,
            )
        vehicle_status_dict = ensure_dict(vehicle_status)

        vehicles = await cosmos_client.list_vehicles()
        vehicle_obj = find_vehicle(vehicles, vehicle_id)
        if not vehicle_obj:
            return format_tool_response(
                "Vehicle details are not available for diagnostics.", success=False,
                plugin_name=_PLUGIN,
            )

        diagnostics_data = {}
        issues = []

        battery_level = vehicle_status_dict.get("battery", 0)
        if battery_level < 20:
            issues.append("Low battery level detected")

        temperature = vehicle_status_dict.get(
            "temperature", vehicle_status_dict.get("Temperature", 0)
        )
        if temperature > 90:
            issues.append("High engine/system temperature detected")

        oil_level = vehicle_status_dict.get("oilRemaining", 0)
        if oil_level < 25:
            issues.append("Low oil level detected")

        services = await cosmos_client.list_services(vehicle_id)
        service_dicts = [ensure_dict(s) for s in services] if services else []
        if service_dicts:
            sorted_services = sorted(
                service_dicts, key=lambda s: s.get("startDate", ""), reverse=True
            )
            if sorted_services:
                last_service = sorted_services[0]
                last_service_date = last_service.get("startDate", "")
                try:
                    service_date = _coerce_datetime(last_service_date)
                    if service_date:
                        now_utc = datetime.now(timezone.utc)
                        months_since = (now_utc - service_date).days // 30
                        if months_since > 6:
                            issues.append(
                                f"Regular maintenance due (last service: {months_since} months ago)"
                            )
                    else:
                        logger.debug(f"Unrecognized service date format: {last_service_date}")
                except Exception as e:
                    logger.warning(f"Could not parse service date: {e}")

        status = "Issues detected" if issues else "All systems normal"

        if issues:
            issues_text = "\n".join([f"• {issue}" for issue in issues])
            response_text = f"Diagnostic check complete. Issues detected:\n\n{issues_text}\n\nI recommend scheduling a service appointment."
        else:
            response_text = "Diagnostic check complete. All vehicle systems are operating normally."

        return format_tool_response(
            response_text,
            data=DiagnosticsData(
                diagnostics=diagnostics_data,
                issues=issues,
                status=status,
                vehicle_id=vehicle_id,
            ).model_dump(by_alias=True),
            function_name="handle_diagnostics", plugin_name=_PLUGIN,
        )
    except Exception as e:
        logger.error(f"Error running diagnostics: {str(e)}")
        return format_tool_response(
            "I encountered an error while running diagnostics. Please try again later.",
            success=False, function_name="handle_diagnostics", plugin_name=_PLUGIN,
        )


@tool(name="handle_battery_status", description="Check battery status and health", approval_mode="never_require")
async def handle_battery_status(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID to check battery status for")] = "",
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response(
            "Please specify which vehicle you'd like to check battery status for.",
            success=False, plugin_name=_PLUGIN,
        )

    try:
        await cosmos_client.ensure_connected()

        vehicle_status = await cosmos_client.get_vehicle_status(vehicle_id)
        if not vehicle_status:
            return format_tool_response(
                "No recent battery status data is available.", success=False,
                plugin_name=_PLUGIN,
            )
        vehicle_status_dict = ensure_dict(vehicle_status)

        vehicles = await cosmos_client.list_vehicles()
        vehicle_obj = find_vehicle(vehicles, vehicle_id)
        if not vehicle_obj:
            return format_tool_response(
                "Vehicle details are not available for battery status.",
                success=False, plugin_name=_PLUGIN,
            )
        vehicle = ensure_dict(vehicle_obj)

        battery_level = vehicle_status_dict.get(
            "batteryLevel",
            vehicle_status_dict.get("Battery", vehicle.get("BatteryLevel", 0)),
        )

        base_range = 400

        make = vehicle.get("make", "")
        model = vehicle.get("model", "")

        if make == "Tesla":
            base_range = 500
        elif "e-tron" in model or "EQS" in model:
            base_range = 450
        elif "iX" in model or "Taycan" in model:
            base_range = 420

        range_km = int(base_range * (battery_level / 100))

        charging = False
        charge_rate = 0

        status_history_raw = await cosmos_client.list_vehicle_status(
            vehicle_id, limit=5
        )
        status_history = [ensure_dict(s) for s in status_history_raw]
        if len(status_history) > 1:
            sorted_history = sorted(
                status_history,
                key=lambda x: x.get("timestamp", ""),
                reverse=True,
            )
            latest = sorted_history[0]
            previous = sorted_history[-1]
            latest_level = latest.get("battery", 0)
            previous_level = previous.get("battery", 0)
            if latest_level > previous_level:
                charging = True
                charge_rate = 11

        battery_data = {
            "level": battery_level,
            "range_km": range_km,
            "health": 100
            - max(
                0,
                min(
                    15,
                    (
                        vehicle.get("year", datetime.now().year)
                        - datetime.now().year
                        + 10
                    )
                    * 1.5,
                ),
            ),
            "charging": charging,
            "charge_rate_kw": charge_rate if charging else 0,
            "estimated_replacement": f"{max(1, 8 - (datetime.now().year - vehicle.get('year', datetime.now().year)))} years",
        }

        charging_status = (
            "currently charging" if battery_data["charging"] else "not charging"
        )
        charging_info = (
            f" and {charging_status}" if battery_data["charge_rate_kw"] > 0 else ""
        )

        vehicle_age = datetime.now().year - vehicle.get("year", datetime.now().year)

        voltage = max(11.8, min(14.2, 13.0 - (vehicle_age * 0.1)))
        health = max(70, 100 - (vehicle_age * 5))

        replacement = "Not needed"
        if health < 75:
            replacement = "Within 6 months"
        if health < 70:
            replacement = "Soon"

        battery_data = {
            "voltage": round(voltage, 1),
            "health": health,
            "last_replaced": f"{max(1, min(48, vehicle_age * 12))} months ago",
            "estimated_replacement": replacement,
        }

        voltage_status = "normal"
        if battery_data["voltage"] < 12.2:
            voltage_status = "low"
        elif battery_data["voltage"] > 14.0:
            voltage_status = "high"

        battery_response = BatteryStatusData(
            battery=BatteryData(
                voltage=battery_data.get("voltage"),
                level=battery_data.get("level"),
                range_km=battery_data.get("range_km"),
                health=battery_data.get("health"),
                last_replaced=battery_data.get("last_replaced"),
                charging=battery_data.get("charging"),
                charge_rate_kw=battery_data.get("charge_rate_kw"),
                estimated_replacement=battery_data.get("estimated_replacement"),
                vehicle_type=battery_data.get("vehicle_type"),
            ),
            vehicle_id=vehicle_id,
            vehicle_type=battery_data.get("vehicle_type"),
        )

        message_parts = []

        if "voltage" in battery_data:
            message_parts.append(
                f"12V battery status: Voltage is {battery_data['voltage']}V ({voltage_status}), "
                f"health is {battery_data['health']}%. "
                f"Battery was last replaced {battery_data['last_replaced']}. "
                f"Recommendation: {battery_data['estimated_replacement']}."
            )

        if "level" in battery_data:
            message_parts.append(
                f"Battery status: {battery_data['level']}% charge level with an estimated range of {battery_data['range_km']} km. "
                f"The battery health is {battery_data['health']}%{charging_info}. "
                f"Estimated battery replacement in {battery_data['estimated_replacement']}."
            )

        combined_message = " ".join(message_parts)

        return format_tool_response(
            combined_message,
            data=battery_response.model_dump(by_alias=True),
            function_name="handle_battery_status", plugin_name=_PLUGIN,
        )
    except Exception as e:
        logger.error(f"Error checking battery status: {str(e)}")
        return format_tool_response(
            "I encountered an error while checking battery status. Please try again later.",
            success=False, function_name="handle_battery_status", plugin_name=_PLUGIN,
        )


@tool(name="handle_system_health", description="Check system health and status", approval_mode="never_require")
async def handle_system_health(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID to check system health for")] = "",
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response(
            "Please specify which vehicle you'd like to check system health for.",
            success=False, plugin_name=_PLUGIN,
        )

    try:
        await cosmos_client.ensure_connected()

        vehicle_status = await cosmos_client.get_vehicle_status(vehicle_id)
        if not vehicle_status:
            return format_tool_response(
                "No recent vehicle status data is available for system health check.",
                success=False, plugin_name=_PLUGIN,
            )
        vehicle_status_dict = ensure_dict(vehicle_status)

        commands_raw = await cosmos_client.list_commands(vehicle_id)
        commands = [ensure_dict(c) for c in commands_raw]
        recent_commands = sorted(
            commands, key=lambda c: c.get("timestamp", ""), reverse=True
        )[:10]
        failed_commands = [
            cmd for cmd in recent_commands if cmd.get("status", "") == "Failed"
        ]

        system_health = {
            "overall_status": "Good",
            "components": {
                "engine": "Normal",
                "transmission": "Normal",
                "brakes": "Normal",
                "battery": "Good",
                "electrical": "Normal",
                "connectivity": "Connected",
            },
            "issues": [],
            "recommendations": [],
        }

        temperature = vehicle_status_dict.get("temperature", 0)

        if temperature > 90:
            system_health["components"]["engine"] = "Warning"
            system_health["issues"].append("High engine temperature detected")
            system_health["recommendations"].append("Check cooling system")

        battery_level = vehicle_status_dict.get("battery", 0)

        if battery_level < 20:
            system_health["components"]["battery"] = "Low"
            system_health["issues"].append("Low battery level")
            system_health["recommendations"].append("Charge battery soon")

        if failed_commands:
            system_health["components"]["connectivity"] = "Warning"
            system_health["issues"].append(
                f"{len(failed_commands)} recent command failures"
            )
            system_health["recommendations"].append("Check vehicle connectivity")

        warning_components = [
            k
            for k, v in system_health["components"].items()
            if v in ["Warning", "Low"]
        ]
        if warning_components:
            system_health["overall_status"] = (
                "Warning" if len(warning_components) <= 2 else "Critical"
            )

        if system_health["issues"]:
            issues_text = "\n".join(
                [f"• {issue}" for issue in system_health["issues"]]
            )
            recommendations_text = "\n".join(
                [f"• {rec}" for rec in system_health["recommendations"]]
            )
            response_text = f"System health check complete. Status: {system_health['overall_status']}\n\nIssues found:\n{issues_text}\n\nRecommendations:\n{recommendations_text}"
        else:
            response_text = "System health check complete. All vehicle systems are operating normally."

        return format_tool_response(
            response_text,
            data=SystemHealthData(
                system_health=SystemHealthReport(
                    overall_status=system_health["overall_status"],
                    components=system_health["components"],
                    issues=system_health["issues"],
                    recommendations=system_health["recommendations"],
                ),
                vehicle_id=vehicle_id,
                failed_commands=len(failed_commands),
            ).model_dump(by_alias=True),
            function_name="handle_system_health", plugin_name=_PLUGIN,
        )
    except Exception as e:
        logger.error(f"Error checking system health: {e}")
        return format_tool_response(
            "I encountered an error while checking system health. Please try again later.",
            success=False, function_name="handle_system_health", plugin_name=_PLUGIN,
        )


@tool(name="handle_maintenance_check", description="Check vehicle maintenance schedule", approval_mode="never_require")
async def handle_maintenance_check(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID to check maintenance for")] = "",
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response(
            "Please specify which vehicle you'd like to check maintenance for.",
            success=False, plugin_name=_PLUGIN,
        )

    try:
        await cosmos_client.ensure_connected()

        vehicles = await cosmos_client.list_vehicles()
        vehicle_obj = find_vehicle(vehicles, vehicle_id)
        if not vehicle_obj:
            return format_tool_response(
                "Vehicle details are not available for maintenance check.",
                success=False, plugin_name=_PLUGIN,
            )
        services = await cosmos_client.list_services(vehicle_id)
        service_dicts = [ensure_dict(s) for s in services] if services else []

        maintenance_items = []

        maintenance_items.append(
            {"type": "Oil Change", "interval_miles": 5000, "interval_months": 6}
        )

        maintenance_items.extend(
            [
                {
                    "type": "Tire Rotation",
                    "interval_miles": 6000,
                    "interval_months": 6,
                },
                {
                    "type": "Brake Inspection",
                    "interval_miles": 12000,
                    "interval_months": 12,
                },
                {
                    "type": "Air Filter",
                    "interval_miles": 15000,
                    "interval_months": 12,
                },
                {
                    "type": "Cabin Filter",
                    "interval_miles": 15000,
                    "interval_months": 12,
                },
            ]
        )

        maintenance_items.append(
            {
                "type": "Battery Health Check",
                "interval_miles": 10000,
                "interval_months": 12,
            }
        )

        for item in maintenance_items:
            matching_services = [
                s
                for s in service_dicts
                if s.get("serviceCode", "").lower().replace("_", " ")
                == item["type"].lower()
            ]

            item["last_service"] = "Never"
            item["next_due"] = "Soon"
            item["status"] = "Overdue"

            if matching_services:
                sorted_services = sorted(
                    matching_services,
                    key=lambda s: s.get("startDate", ""),
                    reverse=True,
                )

                last_service = sorted_services[0]
                try:
                    service_date = _coerce_datetime(last_service.get("startDate", ""))
                    service_mileage = last_service.get("mileage", 0)
                    if not service_date:
                        raise ValueError("Unrecognized date format")
                    item["last_service"] = service_date.strftime("%Y-%m-%d")
                    next_date = service_date + timedelta(days=30 * item["interval_months"])
                    next_mileage = service_mileage + item["interval_miles"]
                    item["next_due_mileage"] = next_mileage
                    now_utc = datetime.now(timezone.utc)
                    months_since = (now_utc - service_date).days // 30
                    if months_since >= item["interval_months"]:
                        item["status"] = "Overdue"
                        item["next_due"] = "Immediately"
                    elif months_since >= item["interval_months"] * 0.8:
                        item["status"] = "Due Soon"
                        item["next_due"] = next_date.strftime("%Y-%m-%d")
                    else:
                        item["status"] = "OK"
                        item["next_due"] = next_date.strftime("%Y-%m-%d")
                except Exception as e:
                    logger.warning(f"Could not parse service date: {e}")

        attention_items = [
            item
            for item in maintenance_items
            if item.get("status") in ["Overdue", "Due Soon"]
        ]
        if attention_items:
            items_text = "\n".join(
                [
                    "• {type}: {status}, next due {next_due}{mileage_part}".format(
                        type=item["type"],
                        status=item["status"],
                        next_due=item["next_due"],
                        mileage_part=(
                            f" (~{item['next_due_mileage']} mi)"
                            if item.get("next_due_mileage")
                            and item["next_due"] not in ["Soon", "Immediately"]
                            else ""
                        ),
                    )
                    for item in attention_items
                ]
            )
            response_text = f"Maintenance check: The following items require attention:\n\n{items_text}"
        else:
            response_text = "Maintenance check: All maintenance items are up to date."

        return format_tool_response(
            response_text,
            data=MaintenanceCheckData(
                maintenance_items=[MaintenanceItem(**mi) for mi in maintenance_items],
                vehicle_id=vehicle_id,
            ).model_dump(by_alias=True),
            function_name="handle_maintenance_check", plugin_name=_PLUGIN,
        )
    except Exception as e:
        logger.error(f"Error checking maintenance: {str(e)}")
        return format_tool_response(
            "I encountered an error while checking maintenance status. Please try again later.",
            success=False, function_name="handle_maintenance_check", plugin_name=_PLUGIN,
        )


DIAGNOSTICS_BATTERY_TOOLS = [
    handle_diagnostics,
    handle_battery_status,
    handle_system_health,
    handle_maintenance_check,
]
