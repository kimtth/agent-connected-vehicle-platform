from typing import Dict, Any
from fastmcp import FastMCP
from utils.logging_config import get_logger
from plugin.mcp_mock_data import generate_pois
from starlette.requests import Request
from starlette.responses import PlainTextResponse


logger = get_logger(__name__)
mcp_poi_server = FastMCP("poi_service")

@mcp_poi_server.custom_route("/health", methods=["GET"])
async def health_check(_: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")

@mcp_poi_server.tool
def find_pois(category: str, latitude: float, longitude: float) -> Dict[str, Any]:
    """
    Find points of interest for a given category and location.
    """
    try:
        resp = generate_pois(category, latitude, longitude)
        return resp
    except Exception as e:
        logger.error(f"Error retrieving POIs: {e}")
        raise

def start_poi_server(host: str | None = None, port: int = 8003):
    """
    Start the POI MCP server.
    """
    if host is None:
        host = "127.0.0.1"
    logger.info(f"Starting POI MCP server on {host}:{port}")
    mcp_poi_server.run(
        transport="http",
        host=host,
        port=port,
        path="/mcp",
        uvicorn_config={"ws": "websockets"},
    )
    logger.info(f"POI MCP server exited on {host}:{port}")

