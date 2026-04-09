import json
from typing import Dict, Any, Optional


def format_tool_response(
    message: str, success: bool = True, data: Optional[Dict[str, Any]] = None,
    function_name: str = "", plugin_name: str = "",
) -> str:
    """Return a JSON-formatted string to preserve structure through the LLM layer."""
    resp: Dict[str, Any] = {
        "message": message,
        "success": success,
        "plugins_used": [f"{plugin_name}.{function_name}"] if function_name else ([plugin_name] if plugin_name else []),
    }
    if data:
        resp["data"] = data
    return json.dumps(resp)