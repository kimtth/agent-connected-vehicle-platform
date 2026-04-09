import datetime
import uuid
from typing import Dict, Any, Optional, Annotated

from agent_framework import tool
from azure.cosmos_db import get_cosmos_client
from utils.logging_config import get_logger
from utils.vehicle_object_utils import find_vehicle, ensure_dict
from agents.base.base_agent import format_tool_response
from models.command import Command
from pydantic import Field
import random

logger = get_logger(__name__)

_PLUGIN = "ChargingEnergyPlugin"


async def _apply_status_update(vehicle_id: str, patch: Dict[str, Any]):
    """Merge patch into vehicle status and persist."""
    cosmos_client = get_cosmos_client()
    try:
        current = await cosmos_client.get_vehicle_status(vehicle_id) or {}
        if isinstance(current, dict):
            current_status = current
        else:
            try:
                current_status = current.model_dump()
            except Exception:
                current_status = {}
        current_status.update(patch)
        if hasattr(cosmos_client, "update_vehicle_status"):
            await cosmos_client.update_vehicle_status(vehicle_id, current_status)
        elif hasattr(cosmos_client, "set_vehicle_status"):
            await cosmos_client.set_vehicle_status(vehicle_id, current_status)
        else:
            container = getattr(cosmos_client, "status_container", None)
            if container:
                doc = {"id": vehicle_id, "vehicle_id": vehicle_id, **current_status}
                await container.upsert_item(doc)
    except Exception as e:
        logger.debug(f"Status update skipped ({vehicle_id}): {e}")


async def _get_vehicle_location(vehicle_id: Optional[str]) -> Dict[str, Any]:
    """Get the vehicle's current location from Cosmos DB."""
    if not vehicle_id:
        return {}

    cosmos_client = get_cosmos_client()
    try:
        vehicle = await cosmos_client.get_vehicle(vehicle_id)

        if vehicle:
            if "lastLocation" in vehicle:
                return vehicle["lastLocation"]

        if vehicle and "lastLocation" in vehicle:
            return {
                "latitude": vehicle["lastLocation"].get("latitude", 0),
                "longitude": vehicle["lastLocation"].get("longitude", 0),
            }

        return {}
    except Exception as e:
        logger.error(f"Error getting vehicle location: {str(e)}")
        return {}


async def _get_nearest_charging_station_distance(vehicle_id: Optional[str]) -> Optional[float]:
    """Get the distance to the nearest charging station."""
    try:
        location = await _get_vehicle_location(vehicle_id)

        if not location:
            return None

        # Dev: Generate random location (for testing)
        async def _random_station_items():
            for i in range(6):
                lat = location.get("latitude", 0) + random.uniform(-0.05, 0.05)
                lon = location.get("longitude", 0) + random.uniform(-0.05, 0.05)
                yield {
                    "id": f"dev-{i}",
                    "name": f"Dev Station {i+1}",
                    "location": {"latitude": lat, "longitude": lon},
                }

        items = _random_station_items()

        nearest_distance = None
        async for item in items:
            station_location = item.get("location", {})
            station_lat = station_location.get("latitude", 0)
            station_lon = station_location.get("longitude", 0)
            vehicle_lat = location.get("latitude", 0)
            vehicle_lon = location.get("longitude", 0)

            distance = (
                (station_lat - vehicle_lat) ** 2 + (station_lon - vehicle_lon) ** 2
            ) ** 0.5 * 111

            if nearest_distance is None or distance < nearest_distance:
                nearest_distance = distance

        return round(nearest_distance, 1) if nearest_distance is not None else None
    except Exception as e:
        logger.error(f"Error finding nearest charging station: {str(e)}")
        return None


@tool(name="handle_charging_stations", description="Find nearby charging stations", approval_mode="never_require")
async def handle_charging_stations(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID to locate nearby chargers for")] = "",
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response(
            "Please specify which vehicle you're using to search for charging stations.",
            success=False, plugin_name=_PLUGIN,
        )

    try:
        location = await _get_vehicle_location(vehicle_id)

        if not location:
            return format_tool_response(
                "I couldn't determine your vehicle's location to find nearby charging stations.",
                success=False, plugin_name=_PLUGIN,
            )

        await cosmos_client.ensure_connected()

        charging_stations_container = cosmos_client.charging_stations_container
        if not charging_stations_container:
            logger.warning("Charging stations container not available")
            return format_tool_response(
                "Charging station data is currently unavailable.", success=False,
                plugin_name=_PLUGIN,
            )

        query = "SELECT * FROM c"
        items = charging_stations_container.query_items(
            query=query, enable_cross_partition_query=True
        )

        nearby_stations = []
        async for item in items:
            station_location = item.get("location", {})
            station_lat = station_location.get("latitude", 0)
            station_lon = station_location.get("longitude", 0)
            vehicle_lat = location.get("latitude", 0)
            vehicle_lon = location.get("longitude", 0)

            distance = (
                (station_lat - vehicle_lat) ** 2 + (station_lon - vehicle_lon) ** 2
            ) ** 0.5 * 111

            if distance < 10:
                nearby_stations.append(
                    {
                        "name": item.get("name", "Unknown Station"),
                        "powerLevel": item.get("powerLevel", "Unknown"),
                        "distanceKm": round(distance, 1),
                        "available": item.get("availablePorts", 0) > 0,
                        "provider": item.get("provider", "Unknown Network"),
                        "costPerKwh": item.get("costPerKwh", 0.0),
                        "connectorTypes": item.get("connectorTypes", []),
                        "isOperational": item.get("isOperational", True),
                    }
                )

        nearby_stations.sort(key=lambda s: s["distanceKm"])

        if not nearby_stations:
            return format_tool_response(
                "I couldn't find any charging stations near your current location.",
                success=False, plugin_name=_PLUGIN,
            )

        stations_text = "\n".join(
            [
                f"• {station['name']} - {station['distanceKm']} km away, "
                f"{station['powerLevel']}, {'Available' if station['available'] else 'Occupied'}"
                for station in nearby_stations
            ]
        )

        return format_tool_response(
            f"I found {len(nearby_stations)} charging stations near you:\n\n{stations_text}",
            data={"stations": nearby_stations, "vehicleId": vehicle_id},
            function_name="handle_charging_stations", plugin_name=_PLUGIN,
        )
    except Exception as e:
        logger.error(f"Error retrieving charging stations: {str(e)}")
        return format_tool_response(
            "I encountered an error while retrieving charging stations. Please try again later.",
            success=False, function_name="handle_charging_stations", plugin_name=_PLUGIN,
        )


@tool(name="handle_charging_status", description="Check charging status and battery", approval_mode="never_require")
async def handle_charging_status(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID to check charging status for")] = "",
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response(
            "Please specify which vehicle you'd like to check the charging status for.",
            success=False, plugin_name=_PLUGIN,
        )

    try:
        vehicle_status = await cosmos_client.get_vehicle_status(vehicle_id)

        if not vehicle_status:
            return format_tool_response(
                "I couldn't retrieve the charging status for your vehicle.",
                success=False, plugin_name=_PLUGIN,
            )

        battery_level = vehicle_status.get("battery", 0)
        engine_status = "on" if int(vehicle_status.get("engineTemp", "")) > 0 else "off"

        vehicles = await cosmos_client.list_vehicles()
        vehicle_obj = find_vehicle(vehicles, vehicle_id)
        if not vehicle_obj:
            return format_tool_response(
                "I couldn't find details for your vehicle.", success=False,
                plugin_name=_PLUGIN,
            )

        is_charging = engine_status == "off" and battery_level > 0 and battery_level < 100

        charging_status = {
            "isCharging": is_charging,
            "batteryLevel": battery_level,
            "timeRemaining": 60 if is_charging else None,
            "chargingPower": 7.2 if is_charging else None,
        }

        if charging_status["isCharging"]:
            response_text = (
                f"Your vehicle is currently charging. The battery level is {charging_status['batteryLevel']}%. "
                f"Estimated time to full charge: {charging_status['timeRemaining']} minutes. "
                f"Current charging power: {charging_status['chargingPower']} kW."
            )
        else:
            response_text = f"Your vehicle is not currently charging. The battery level is {charging_status['batteryLevel']}%."

        return format_tool_response(
            response_text,
            data={"chargingStatus": charging_status, "vehicleId": vehicle_id},
            function_name="handle_charging_status", plugin_name=_PLUGIN,
        )
    except Exception as e:
        logger.error(f"Error retrieving charging status: {str(e)}")
        return format_tool_response(
            "I encountered an error while retrieving the charging status. Please try again later.",
            success=False, function_name="handle_charging_status", plugin_name=_PLUGIN,
        )


@tool(name="handle_start_charging", description="Start vehicle charging", approval_mode="never_require")
async def handle_start_charging(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID to start charging")] = "",
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response(
            "Please specify which vehicle you'd like to start charging.",
            success=False, plugin_name=_PLUGIN,
        )

    try:
        vehicle_status = await cosmos_client.get_vehicle_status(vehicle_id)

        vehicles = await cosmos_client.list_vehicles()
        vehicle_obj = find_vehicle(vehicles, vehicle_id)
        if not vehicle_obj:
            return format_tool_response(
                "I couldn't find details for your vehicle.", success=False,
                plugin_name=_PLUGIN,
            )

        battery_level = vehicle_status.get("battery", 0)

        await cosmos_client.ensure_connected()
        command_obj = Command(
            id=str(uuid.uuid4()),
            command_id=f"charge-{str(uuid.uuid4())[:8]}",
            vehicle_id=vehicle_id,
            command_type="start_charging",
            parameters={},
            status="pending",
            timestamp=datetime.datetime.now().isoformat(),
            priority="normal",
        )
        result = await cosmos_client.create_command(command_obj.model_dump(by_alias=True))

        if result:
            await _apply_status_update(
                vehicle_id,
                {
                    "charging": True,
                    "lastChargeCommandId": command_obj.command_id,
                    "chargeStartedAt": datetime.datetime.now().isoformat(),
                },
            )
            return format_tool_response(
                f"I've started charging your vehicle. The current battery level is "
                f"{battery_level}% and the estimated time to full charge is "
                f"about {(100 - battery_level) * 2} minutes at a standard charging rate.",
                data={
                    "action": "start_charging",
                    "vehicleId": vehicle_id,
                    "status": "success",
                    "commandId": command_obj.command_id,
                },
                function_name="handle_start_charging", plugin_name=_PLUGIN,
            )
        else:
            return format_tool_response(
                "I couldn't start charging your vehicle. The command was not processed.",
                success=False,
                data={
                    "action": "start_charging",
                    "vehicleId": vehicle_id,
                    "status": "failed",
                    "error": "Command processing failed",
                },
                function_name="handle_start_charging", plugin_name=_PLUGIN,
            )
    except Exception as e:
        logger.error(f"Error starting charging: {str(e)}")
        return format_tool_response(
            "I encountered an error while trying to start charging. Please try again later.",
            success=False, function_name="handle_start_charging", plugin_name=_PLUGIN,
        )


@tool(name="handle_stop_charging", description="Stop vehicle charging", approval_mode="never_require")
async def handle_stop_charging(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID to stop charging")] = "",
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response(
            "Please specify which vehicle you'd like to stop charging.",
            success=False, plugin_name=_PLUGIN,
        )

    try:
        vehicle_status = await cosmos_client.get_vehicle_status(vehicle_id)

        vehicles = await cosmos_client.list_vehicles()
        vehicle_obj = find_vehicle(vehicles, vehicle_id)
        if not vehicle_obj:
            return format_tool_response(
                "I couldn't find details for your vehicle.", success=False,
                plugin_name=_PLUGIN,
            )

        battery_level = vehicle_status.get("battery", 0)

        await cosmos_client.ensure_connected()
        command_obj = Command(
            id=str(uuid.uuid4()),
            command_id=f"stop-charge-{str(uuid.uuid4())[:8]}",
            vehicle_id=vehicle_id,
            command_type="stop_charging",
            parameters={},
            status="pending",
            timestamp=datetime.datetime.now().isoformat(),
            priority="normal",
        )
        result = await cosmos_client.create_command(command_obj.model_dump(by_alias=True))

        if result:
            await _apply_status_update(
                vehicle_id,
                {
                    "charging": False,
                    "lastChargeCommandId": command_obj.command_id,
                    "chargeStoppedAt": datetime.datetime.now().isoformat(),
                },
            )
            return format_tool_response(
                f"I've stopped charging your vehicle. The final battery level is "
                f"{battery_level}%.",
                data={
                    "action": "stop_charging",
                    "vehicleId": vehicle_id,
                    "status": "success",
                    "commandId": command_obj.command_id,
                },
                function_name="handle_stop_charging", plugin_name=_PLUGIN,
            )
        else:
            return format_tool_response(
                "I couldn't stop charging your vehicle. The command was not processed.",
                success=False,
                data={
                    "action": "stop_charging",
                    "vehicleId": vehicle_id,
                    "status": "failed",
                    "error": "Command processing failed",
                },
                function_name="handle_stop_charging", plugin_name=_PLUGIN,
            )
    except Exception as e:
        logger.error(f"Error stopping charging: {str(e)}")
        return format_tool_response(
            "I encountered an error while trying to stop charging. Please try again later.",
            success=False, function_name="handle_stop_charging", plugin_name=_PLUGIN,
        )


@tool(name="handle_energy_usage", description="Get energy usage metrics", approval_mode="never_require")
async def handle_energy_usage(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID to retrieve energy usage for")] = "",
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response(
            "Please specify which vehicle you'd like to check energy usage for.",
            success=False, plugin_name=_PLUGIN,
        )

    try:
        vehicles = await cosmos_client.list_vehicles()
        vehicle_obj = find_vehicle(vehicles, vehicle_id)
        if not vehicle_obj:
            return format_tool_response(
                "I couldn't find details for your vehicle.", success=False,
                plugin_name=_PLUGIN,
            )

        status_container = await cosmos_client.status_container

        query = "SELECT * FROM c WHERE c.vehicle_id = @vehicleId ORDER BY c._ts DESC OFFSET 0 LIMIT 20"
        parameters = [{"name": "@vehicleId", "value": vehicle_id}]

        items = status_container.query_items(query=query, parameters=parameters)

        statuses = []
        async for item in items:
            statuses.append(item)

        battery_levels = [
            s.get("battery", 0) for s in statuses if "battery" in s
        ]

        if not battery_levels:
            energy_usage = {
                "totalKwh": 18.5,
                "avgEfficiency": 16.7,
                "regenerativeBraking": 2.3,
                "costEstimate": 4.62,
            }
        else:
            battery_capacity_kwh = 75.0

            if len(battery_levels) > 1:
                battery_diff = sum(
                    [
                        max(0, battery_levels[i] - battery_levels[i + 1])
                        for i in range(len(battery_levels) - 1)
                    ]
                )

                total_kwh = (battery_diff / 100) * battery_capacity_kwh

                mileage_readings = [
                    s.get("mileage", 0) for s in statuses if "mileage" in s
                ]

                if len(mileage_readings) > 1:
                    distance = abs(mileage_readings[0] - mileage_readings[-1])
                    avg_efficiency = (total_kwh / max(1, distance)) * 100
                else:
                    avg_efficiency = 16.7

                regen_kwh = total_kwh * 0.12

                energy_usage = {
                    "totalKwh": round(total_kwh, 1),
                    "avgEfficiency": round(avg_efficiency, 1),
                    "regenerativeBraking": round(regen_kwh, 1),
                    "costEstimate": round(total_kwh * 0.25, 2),
                }
            else:
                energy_usage = {
                    "totalKwh": 18.5,
                    "avgEfficiency": 16.7,
                    "regenerativeBraking": 2.3,
                    "costEstimate": 4.62,
                }

        return format_tool_response(
            f"Here's your energy usage summary:\n\n"
            f"• Total energy used: {energy_usage['totalKwh']} kWh\n"
            f"• Average efficiency: {energy_usage['avgEfficiency']} kWh/100 km\n"
            f"• Energy recovered from regenerative braking: {energy_usage['regenerativeBraking']} kWh\n"
            f"• Estimated cost: ${energy_usage['costEstimate']}",
            data={"energyUsage": energy_usage, "vehicleId": vehicle_id},
            function_name="handle_energy_usage", plugin_name=_PLUGIN,
        )
    except Exception as e:
        logger.error(f"Error retrieving energy usage: {str(e)}")
        return format_tool_response(
            "I encountered an error while retrieving energy usage data. Please try again later.",
            success=False, function_name="handle_energy_usage", plugin_name=_PLUGIN,
        )


@tool(name="handle_range_estimation", description="Estimate vehicle range", approval_mode="never_require")
async def handle_range_estimation(
    vehicle_id: Annotated[str, Field(description="Vehicle GUID to estimate range for")] = "",
) -> str:
    cosmos_client = get_cosmos_client()
    if not vehicle_id:
        return format_tool_response(
            "Please specify which vehicle you'd like to estimate range for.",
            success=False, plugin_name=_PLUGIN,
        )

    try:
        vehicle_status = await cosmos_client.get_vehicle_status(vehicle_id)

        vehicles = await cosmos_client.list_vehicles()
        vehicle_obj = find_vehicle(vehicles, vehicle_id)
        if not vehicle_obj:
            return format_tool_response(
                "I couldn't find details for your vehicle.", success=False,
                plugin_name=_PLUGIN,
            )
        vehicle = ensure_dict(vehicle_obj)

        battery_level = vehicle_status.get("battery", 0)

        brand = vehicle.get("make", "")
        model = vehicle.get("model", "")

        base_range = 450

        if brand == "Tesla":
            if "Model S" in model or "Model X" in model:
                base_range = 560
            else:
                base_range = 510
        elif "e-tron" in model or "Taycan" in model:
            base_range = 400
        elif "Bolt" in model or "Mach-E" in model:
            base_range = 380

        estimated_range_km = int(base_range * (battery_level / 100))
        estimated_range_eco_km = int(estimated_range_km * 1.12)

        nearest_station_km = await _get_nearest_charging_station_distance(vehicle_id)

        range_data = {
            "batteryLevel": battery_level,
            "estimatedRangeKm": estimated_range_km,
            "estimatedRangeEcoKm": estimated_range_eco_km,
            "nearestStationKm": (nearest_station_km if nearest_station_km else "Unknown"),
        }
        return format_tool_response(
            f"Based on your current battery level of {range_data['batteryLevel']}%, "
            f"your estimated range is {range_data['estimatedRangeKm']} km. "
            f"In eco mode, you could potentially reach {range_data['estimatedRangeEcoKm']} km. "
            f"The nearest charging station is {range_data['nearestStationKm']} km away.",
            data={"rangeData": range_data, "vehicleId": vehicle_id},
            function_name="handle_range_estimation", plugin_name=_PLUGIN,
        )
    except Exception as e:
        logger.error(f"Error estimating range: {str(e)}")
        return format_tool_response(
            "I encountered an error while estimating your vehicle's range. Please try again later.",
            success=False, function_name="handle_range_estimation", plugin_name=_PLUGIN,
        )


CHARGING_ENERGY_TOOLS = [
    handle_charging_stations,
    handle_charging_status,
    handle_start_charging,
    handle_stop_charging,
    handle_energy_usage,
    handle_range_estimation,
]
