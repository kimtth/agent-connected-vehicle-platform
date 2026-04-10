"""
Information Services Agent for the Connected Car Platform.
"""

from typing import Dict, Any, Optional, Annotated
import json

from agent_framework import tool
from vehicle_azure.cosmos_db import get_cosmos_client
from utils.logging_config import get_logger
from agents.base.base_agent import format_tool_response
from pydantic import Field
from fastmcp import Client


logger = get_logger(__name__)

_PLUGIN = "InformationServicesPlugin"

# Module-level MCP client state
_BASE_HOST = "127.0.0.1"
_SVC_URLS = {
    "weather": f"http://{_BASE_HOST}:8001/mcp",
    "traffic": f"http://{_BASE_HOST}:8002/mcp",
    "poi": f"http://{_BASE_HOST}:8003/mcp",
    "navigation": f"http://{_BASE_HOST}:8004/mcp",
}

_weather_client = None
_traffic_client = None
_poi_client = None
_nav_client = None
_fastmcp_entered: dict[str, bool] = {
    "weather": False,
    "traffic": False,
    "poi": False,
    "navigation": False,
}

try:
    _weather_client = Client(_SVC_URLS["weather"])
    _traffic_client = Client(_SVC_URLS["traffic"])
    _poi_client = Client(_SVC_URLS["poi"])
    _nav_client = Client(_SVC_URLS["navigation"])
    logger.info(f"FastMCP clients initialized successfully for host {_BASE_HOST}")
except ImportError:
    logger.info("fastmcp library not available, using raw HTTP fallback")
except Exception as e:
    logger.warning(f"FastMCP client initialization failed, will fallback to raw HTTP: {e}")

_CLIENT_MAP = {
    "weather": _weather_client,
    "traffic": _traffic_client,
    "poi": _poi_client,
    "navigation": _nav_client,
}


async def _enter_fastmcp(service: str, client) -> bool:
    """Lazily enter (async context) the FastMCP client once."""
    if not client:
        return False
    try:
        if not _fastmcp_entered.get(service):
            await client.__aenter__()
            _fastmcp_entered[service] = True
        return True
    except Exception as e:
        logger.debug(f"FastMCP __aenter__ failed for {service}: {e}")
        return False


async def _invoke_mcp_tool(service: str, tool_name: str, **kwargs) -> dict:
    """Invoke an MCP tool using FastMCP (preferred)."""
    url = _SVC_URLS.get(service)
    if not url:
        return {"error": f"unknown service {service}"}

    client = _CLIENT_MAP.get(service)
    if not client or not await _enter_fastmcp(service, client):
        return {"error": f"{service} client unavailable"}
    try:
        result = await client.call_tool(tool_name, kwargs)
        return result if isinstance(result, dict) else {"result": result}
    except Exception as e:
        return {"error": f"{service}.{tool_name} failed", "detail": str(e)}


def _ensure_serializable(result):
    """Return a JSON-serializable representation of obj."""
    try:
        json.dumps(result)
        return result
    except (TypeError, OverflowError):
        return str(result)


async def _get_vehicle_location(vehicle_id: Optional[str]) -> Dict[str, Any]:
    """Get the vehicle's current location from Cosmos DB."""
    if not vehicle_id:
        return {}

    cosmos_client = get_cosmos_client()
    try:
        vehicle_info = await cosmos_client.get_vehicle(vehicle_id)

        if vehicle_info and "lastLocation" in vehicle_info:
            return {
                "latitude": vehicle_info["lastLocation"].get("latitude", 0),
                "longitude": vehicle_info["lastLocation"].get("longitude", 0),
            }

        return {}
    except Exception as e:
        logger.error(f"Error getting vehicle location: {e}")
        return {}


@tool(name="handle_weather", description="Get weather information for the vehicle's location", approval_mode="never_require")
async def handle_weather(
    location: Annotated[str, Field(description="Override location (city or coords)")] = "",
    vehicle_id: Annotated[str, Field(description="Vehicle GUID for location lookup")] = "",
) -> str:
    logger.info(
        f"Getting weather information for location: {location}, vehicle: {vehicle_id}"
    )

    try:
        coords = await _get_vehicle_location(vehicle_id)
        if not coords:
            coords = {"latitude": 35.6895, "longitude": 139.6917}
        latitude = coords.get("latitude", 35.6895)
        longitude = coords.get("longitude", 139.6917)
        result = await _invoke_mcp_tool(
            "weather",
            "get_weather",
            latitude=latitude,
            longitude=longitude,
        )
        serializable = _ensure_serializable(result)
        return format_tool_response(
            "Weather data retrieved.",
            data=serializable,
            function_name="handle_weather", plugin_name=_PLUGIN,
        )
    except Exception:
        return format_tool_response(
            "Error getting weather.",
            success=False, function_name="handle_weather", plugin_name=_PLUGIN,
        )


@tool(name="handle_traffic", description="Get traffic information for the vehicle's route", approval_mode="never_require")
async def handle_traffic(
    route: Annotated[str, Field(description="Route or segment description")] = "",
    vehicle_id: Annotated[str, Field(description="Vehicle GUID for current position")] = "",
) -> str:
    logger.info(
        f"Getting traffic information for route: {route}, vehicle: {vehicle_id}"
    )

    try:
        coords = await _get_vehicle_location(vehicle_id)
        result = await _invoke_mcp_tool(
            "traffic",
            "get_traffic",
            route=route or "current route",
            latitude=coords.get("latitude", 0.0),
            longitude=coords.get("longitude", 0.0),
        )
        serializable = _ensure_serializable(result)
        return format_tool_response(
            "Traffic data retrieved.",
            data=serializable,
            function_name="handle_traffic", plugin_name=_PLUGIN,
        )
    except Exception:
        return format_tool_response(
            "Error getting traffic.",
            success=False, function_name="handle_traffic", plugin_name=_PLUGIN,
        )


@tool(name="handle_pois", description="Find points of interest near the vehicle's location", approval_mode="never_require")
async def handle_pois(
    category: Annotated[str, Field(description="POI category (e.g., food, gas)")] = "",
    vehicle_id: Annotated[str, Field(description="Vehicle GUID for location lookup")] = "",
) -> str:
    logger.info(f"Finding POIs for category: {category}, vehicle: {vehicle_id}")

    try:
        coords = await _get_vehicle_location(vehicle_id)
        result = await _invoke_mcp_tool(
            "poi",
            "find_pois",
            category=category or "general",
            latitude=coords.get("latitude", 0.0),
            longitude=coords.get("longitude", 0.0),
        )
        serializable = _ensure_serializable(result)
        return format_tool_response(
            "POIs retrieved.",
            data=serializable,
            function_name="handle_pois", plugin_name=_PLUGIN,
        )
    except Exception:
        return format_tool_response(
            "Error finding POIs.",
            success=False, function_name="handle_pois", plugin_name=_PLUGIN,
        )


@tool(name="handle_navigation", description="Get navigation directions to a destination", approval_mode="never_require")
async def handle_navigation(
    destination: Annotated[str, Field(description="Destination address or place name")],
    vehicle_id: Annotated[str, Field(description="Vehicle GUID for origin")] = "",
) -> str:
    logger.info(f"Getting navigation to: {destination}, vehicle: {vehicle_id}")

    try:
        coords = await _get_vehicle_location(vehicle_id)
        result = await _invoke_mcp_tool(
            "navigation",
            "get_directions",
            destination=destination,
            latitude=coords.get("latitude", 0.0),
            longitude=coords.get("longitude", 0.0),
        )
        serializable = _ensure_serializable(result)
        return format_tool_response(
            "Navigation retrieved.",
            data=serializable,
            function_name="handle_navigation", plugin_name=_PLUGIN,
        )
    except Exception:
        return format_tool_response(
            "Error getting navigation.",
            success=False, function_name="handle_navigation", plugin_name=_PLUGIN,
        )


INFORMATION_SERVICES_TOOLS = [
    handle_weather,
    handle_traffic,
    handle_pois,
    handle_navigation,
]
