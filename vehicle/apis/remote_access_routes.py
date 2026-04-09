from fastapi import APIRouter, HTTPException, Depends
from utils.logging_config import get_logger
from models.api_responses import ActionResponse
from models.agent_request import DoorControlRequest, EngineControlRequest
from agents.agent_manager import AgentManager

logger = get_logger(__name__)

router = APIRouter(
    prefix="/vehicles/{vehicle_id}/remote-access", tags=["Remote Access"]
)


async def _get_agent_manager() -> AgentManager:
    return AgentManager()


@router.post("/doors", response_model=ActionResponse)
async def control_doors(
    vehicle_id: str,
    request: DoorControlRequest,
    agent_manager=Depends(_get_agent_manager),
):
    """Lock or unlock vehicle doors remotely"""
    try:
        context = {
            "vehicle_id": vehicle_id,
            "query": f"{request.action} doors",
            "session_id": f"doors_{vehicle_id}",
        }
        response = await agent_manager.process_request(
            f"{request.action} the vehicle doors", context
        )
        if not response.get("success", False):
            raise HTTPException(
                status_code=400,
                detail=response.get("response", "Failed to control doors"),
            )
        return ActionResponse(data=response)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error controlling doors for vehicle {vehicle_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/engine", response_model=ActionResponse)
async def control_engine(
    vehicle_id: str,
    request: EngineControlRequest,
    agent_manager=Depends(_get_agent_manager),
):
    """Start or stop vehicle engine remotely"""
    try:
        context = {
            "vehicle_id": vehicle_id,
            "query": f"{request.action} engine",
            "session_id": f"engine_{vehicle_id}",
        }
        response = await agent_manager.process_request(
            f"{request.action} the vehicle engine", context
        )
        if not response.get("success", False):
            raise HTTPException(
                status_code=400,
                detail=response.get("response", "Failed to control engine"),
            )
        return ActionResponse(data=response)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error controlling engine for vehicle {vehicle_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/locate", response_model=ActionResponse)
async def locate_vehicle(
    vehicle_id: str,
    agent_manager=Depends(_get_agent_manager),
):
    """Activate horn and lights to locate vehicle"""
    try:
        context = {
            "vehicle_id": vehicle_id,
            "query": "locate vehicle",
            "session_id": f"locate_{vehicle_id}",
        }
        response = await agent_manager.process_request(
            "activate horn and lights to help me find my vehicle", context
        )
        if not response.get("success", False):
            raise HTTPException(
                status_code=400,
                detail=response.get("response", "Failed to locate vehicle"),
            )
        return ActionResponse(data=response)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error locating vehicle {vehicle_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
