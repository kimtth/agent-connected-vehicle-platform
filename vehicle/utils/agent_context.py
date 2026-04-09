from typing import Dict, Optional, Any


def extract_vehicle_id(
    context: Optional[Any], vehicle_id: Optional[str] = None
) -> Optional[str]:
    """
    Return vehicle_id if provided, otherwise try to extract it from the given context object.
    """
    if vehicle_id:
        return vehicle_id

    try:
        current_context = context.get_current()
        if current_context and hasattr(current_context, "arguments"):
            return current_context.arguments.get("vehicleId")
    except Exception:
        pass
    return None


async def validate_command(
    command_id: str, command_type: str, parameters: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Validate a command before execution

    Args:
        command_id: Command ID
        command_type: Type of command
        parameters: Command parameters

    Returns:
        Validation results
    """
    valid_commands = {
        "start_engine": ["ignition_level"],
        "stop_engine": [],
        "lock_doors": ["doors"],
        "unlock_doors": ["doors"],
        "activate_climate": ["temperature", "fan_speed"],
    }

    if command_type not in valid_commands:
        return {
            "valid": False,
            "error": f"Unknown command type: {command_type}",
            "commandId": command_id,
        }

    # Check required parameters
    required_params = valid_commands[command_type]
    if parameters:
        missing_params = [p for p in required_params if p not in parameters]
        if missing_params:
            return {
                "valid": False,
                "error": f"Missing required parameters: {', '.join(missing_params)}",
                "commandId": command_id,
            }
    elif required_params:
        return {
            "valid": False,
            "error": "Missing parameters object",
            "commandId": command_id,
        }

    return {"valid": True, "commandId": command_id, "commandType": command_type}
