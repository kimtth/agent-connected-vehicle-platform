from typing import Dict, Any
from fastmcp import FastMCP
from utils.logging_config import get_logger
from plugin.mcp_mock_data import generate_traffic
from starlette.requests import Request
from starlette.responses import PlainTextResponse


logger = get_logger(__name__)
mcp_traffic_server = FastMCP("traffic_service")


@mcp_traffic_server.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


@mcp_traffic_server.tool
def get_traffic(route: str, latitude: float, longitude: float) -> Dict[str, Any]:
    """
    Get traffic information for a given route or location.
    """
    try:
        resp = generate_traffic(route, latitude, longitude)
        return resp
    except Exception as e:
        logger.error(f"Error retrieving traffic info: {e}")
        raise


def start_traffic_server(host: str | None = None, port: int = 8002):
    if host is None:
        host = "127.0.0.1"
    logger.info(f"Starting Traffic MCP server on {host}:{port}")
    mcp_traffic_server.run(
        transport="http",
        host=host,
        port=port,
        path="/mcp",
        uvicorn_config={"ws": "websockets"},
    )
    logger.info(f"Traffic MCP server exited on {host}:{port}")
