from fastapi import APIRouter, HTTPException, Depends
from utils.logging_config import get_logger
from models.api_responses import ActionResponse
from models.agent_request import (
    EmergencyCallRequest,
    CollisionReportRequest,
    TheftReportRequest,
)
from agents.agent_manager import AgentManager

logger = get_logger(__name__)
router = APIRouter(
    prefix="/vehicles/{vehicle_id}/emergency", tags=["Emergency & Safety"]
)


async def _get_agent_manager() -> AgentManager:
    return AgentManager()


@router.post("/call", response_model=ActionResponse)
async def emergency_call(
    vehicle_id: str,
    request: EmergencyCallRequest,
    agent_manager=Depends(_get_agent_manager),
):
    """Initiate an emergency call"""
    try:
        context = {
            "vehicle_id": vehicle_id,
            "query": f"emergency call {request.emergency_type}",
            "session_id": f"emergency_{vehicle_id}",
            "emergency_type": request.emergency_type,
            "agent_type": "safety_emergency",
        }
        response = await agent_manager.process_request(
            f"I need to make an emergency call for {request.emergency_type} emergency",
            context,
        )
        if not response.get("success", False):
            raise HTTPException(
                status_code=400,
                detail=response.get("response", "Failed to initiate emergency call"),
            )
        return ActionResponse(data=response)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error initiating emergency call for vehicle {vehicle_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/collision", response_model=ActionResponse)
async def report_collision(
    vehicle_id: str,
    request: CollisionReportRequest,
    agent_manager=Depends(_get_agent_manager),
):
    """Report a collision incident"""
    try:
        context = {
            "vehicle_id": vehicle_id,
            "query": f"collision report {request.severity}",
            "session_id": f"collision_{vehicle_id}",
            "collision_severity": request.severity,
            "collision_location": request.location,
            "agent_type": "safety_emergency",
        }
        response = await agent_manager.process_request(
            f"I need to report a {request.severity} collision", context
        )
        if not response.get("success", False):
            raise HTTPException(
                status_code=400,
                detail=response.get("response", "Failed to report collision"),
            )
        return ActionResponse(data=response)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reporting collision for vehicle {vehicle_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/theft", response_model=ActionResponse)
async def report_theft(
    vehicle_id: str,
    request: TheftReportRequest,
    agent_manager=Depends(_get_agent_manager),
):
    """Report vehicle theft"""
    try:
        context = {
            "vehicle_id": vehicle_id,
            "query": "theft report",
            "session_id": f"theft_{vehicle_id}",
            "theft_description": request.description,
            "last_location": request.last_seen_location,
            "agent_type": "safety_emergency",
        }
        response = await agent_manager.process_request(
            f"I need to report my vehicle as stolen. {request.description or ''}",
            context,
        )
        if not response.get("success", False):
            raise HTTPException(
                status_code=400,
                detail=response.get("response", "Failed to report theft"),
            )
        return ActionResponse(data=response)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reporting theft for vehicle {vehicle_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/sos", response_model=ActionResponse)
async def activate_sos(
    vehicle_id: str,
    agent_manager=Depends(_get_agent_manager),
):
    """Activate SOS emergency response"""
    try:
        context = {
            "vehicle_id": vehicle_id,
            "query": "SOS emergency",
            "session_id": f"sos_{vehicle_id}",
            "agent_type": "safety_emergency",
        }
        response = await agent_manager.process_request(
            "EMERGENCY SOS - I need immediate help", context
        )
        if not response.get("success", False):
            raise HTTPException(
                status_code=400,
                detail=response.get("response", "Failed to activate SOS"),
            )
        return ActionResponse(data=response)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error activating SOS for vehicle {vehicle_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
