from fastapi import APIRouter, Depends, HTTPException
from utils.logging_config import get_logger
from models.api_responses import ActionResponse
from models.agent_request import LightsControlRequest, ClimateControlRequest, WindowsControlRequest
from agents.agent_manager import AgentManager

logger = get_logger(__name__)
router = APIRouter(
    prefix="/vehicles/{vehicle_id}/features",
    tags=["Vehicle Features"],
)


async def _get_agent_manager() -> AgentManager:
    return AgentManager()


@router.post("/lights", response_model=ActionResponse)
async def control_lights(
    vehicle_id: str,
    request: LightsControlRequest,
    agent_manager=Depends(_get_agent_manager),
):
    """Control vehicle lights (headlights, interior, hazard)"""
    try:
        context = {
            "vehicle_id": vehicle_id,
            "query": f"turn {request.action} {request.light_type}",
            "session_id": f"lights_{vehicle_id}",
        }
        response = await agent_manager.process_request(
            f"turn {request.action} the {request.light_type}", context
        )
        if not response.get("success", False):
            raise HTTPException(status_code=400, detail=response.get("response", "Failed to control lights"))
        return ActionResponse(data=response)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error controlling lights for vehicle {vehicle_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/climate", response_model=ActionResponse)
async def control_climate(
    vehicle_id: str,
    request: ClimateControlRequest,
    agent_manager=Depends(_get_agent_manager),
):
    """Control vehicle climate settings"""
    try:
        context = {
            "vehicle_id": vehicle_id,
            "query": f"set climate to {request.temperature} degrees {request.action}",
            "session_id": f"climate_{vehicle_id}",
        }
        response = await agent_manager.process_request(
            f"set the climate control to {request.temperature} degrees with {request.action}",
            context,
        )
        if not response.get("success", False):
            raise HTTPException(status_code=400, detail=response.get("response", "Failed to control climate"))
        return ActionResponse(data=response)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error controlling climate for vehicle {vehicle_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/windows", response_model=ActionResponse)
async def control_windows(
    vehicle_id: str,
    request: WindowsControlRequest,
    agent_manager=Depends(_get_agent_manager),
):
    """Control vehicle windows"""
    try:
        context = {
            "vehicle_id": vehicle_id,
            "query": f"roll {request.action} {request.windows} windows",
            "session_id": f"windows_{vehicle_id}",
        }
        response = await agent_manager.process_request(
            f"roll {request.action} the {request.windows} windows", context
        )
        if not response.get("success", False):
            raise HTTPException(status_code=400, detail=response.get("response", "Failed to control windows"))
        return ActionResponse(data=response)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error controlling windows for vehicle {vehicle_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/status", response_model=ActionResponse)
async def get_feature_status(
    vehicle_id: str,
    agent_manager=Depends(_get_agent_manager),
):
    """Get current status of vehicle features"""
    try:
        context = {
            "vehicle_id": vehicle_id,
            "session_id": f"status_{vehicle_id}",
        }
        response = await agent_manager.process_request(
            "show me the current status of vehicle features", context
        )
        return ActionResponse(data=response)
    except Exception as e:
        logger.error(f"Error getting feature status for vehicle {vehicle_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
