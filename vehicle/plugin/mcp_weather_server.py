"""
Weather MCP server implementation for the Connected Car Platform using FastMCP.

This module provides weather data through the Model Context Protocol (MCP).
"""
from typing import Dict, Any, List
from fastmcp import FastMCP
from utils.logging_config import get_logger
from plugin.mcp_mock_data import generate_weather, generate_forecast
from starlette.requests import Request
from starlette.responses import PlainTextResponse


logger = get_logger(__name__)
mcp_weather_server = FastMCP("weather_service")

@mcp_weather_server.custom_route("/health", methods=["GET"])
async def health_check(_: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")

@mcp_weather_server.tool
def get_weather(latitude: float, longitude: float) -> Dict[str, Any]:
    """
    Get weather information for a given location.
    """
    try:
        resp = generate_weather(latitude, longitude)
        return resp
    except Exception as e:
        logger.error(f"Error retrieving weather information: {e}")
        raise

@mcp_weather_server.tool
def get_forecast(latitude: float, longitude: float, days: int = 3) -> List[Dict[str, Any]]:
    """
    Get weather forecast for a given location.
    """
    try:
        return generate_forecast(latitude, longitude, days)
    except Exception as e:
        logger.error(f"Error retrieving weather forecast: {e}")
        raise

def start_weather_server(host: str | None = None, port: int = 8001):
    """
    Initialize and start the weather MCP server.
    """
    if host is None:
        host = "127.0.0.1"
    logger.info(f"Starting Weather MCP server on {host}:{port}")
    mcp_weather_server.run(
        transport="http",
        host=host,
        port=port,
        path="/mcp",
        uvicorn_config={"ws": "websockets"},
    )
    logger.info(f"Weather MCP server exited on {host}:{port}")


