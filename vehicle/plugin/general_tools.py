from typing import Dict, Any
from agent_framework import tool


@tool(name="general_inquiry", description="General plugin for vehicle inquiries.", approval_mode="never_require")
def general_inquiry(user_input: str) -> str:
    """Process general vehicle inquiries and return a formatted response."""
    if not user_input or not isinstance(user_input, str):
        return "I need more information to help you. Please provide a specific question about your vehicle."

    return f"General plugin received user input: {user_input.strip()}"


@tool(name="general_help", description="Provide general help and available capabilities.", approval_mode="never_require")
def general_help() -> Dict[str, Any]:
    """Provide help information about available vehicle capabilities."""
    return {
        "message": "I can help with remote access, safety & emergency, charging & energy, vehicle features, diagnostics, and alerts.",
        "success": True,
        "data": {
            "capabilities": [
                "remote_access", "safety_emergency", "charging_energy",
                "vehicle_feature_control", "diagnostics_battery", "alerts_notifications"
            ]
        }
    }


GENERAL_TOOLS = [general_inquiry, general_help]