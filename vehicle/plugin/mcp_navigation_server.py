from typing import Dict, Any
from fastmcp import FastMCP
from utils.logging_config import get_logger
from plugin.mcp_mock_data import generate_directions
from starlette.requests import Request
from starlette.responses import PlainTextResponse


logger = get_logger(__name__)
mcp_navigation_server = FastMCP("navigation_service")

@mcp_navigation_server.custom_route("/health", methods=["GET"])
async def health_check(_: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")

@mcp_navigation_server.tool
def get_directions(destination: str, latitude: float, longitude: float) -> Dict[str, Any]:
    """
    Get navigation directions for a given destination and start location.
    """
    try:
        resp = generate_directions(destination, latitude, longitude)
        return resp
    except Exception as e:
        logger.error(f"Error retrieving directions: {e}")
        raise

def start_navigation_server(host: str | None = None, port: int = 8004):
    """
    Start the navigation MCP server.
    """
    if host is None:
        host = "127.0.0.1"
    logger.info(f"Starting Navigation MCP server on {host}:{port}")
    mcp_navigation_server.run(
        transport="http",
        host=host,
        port=port,
        path="/mcp",
        uvicorn_config={"ws": "websockets"},
    )
    logger.info(f"Navigation MCP server exited on {host}:{port}")
