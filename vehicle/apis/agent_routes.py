"""Endpoints for interacting with the agentic components of the connected vehicle platform."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
import logging
import uuid
from typing import TYPE_CHECKING, Union

from models.agent_request import (
    AgentQueryRequest,
    AnalysisRequest,
    ServiceRecommendationRequest,
)
from models.agent_response import AgentServiceResponse, StreamingChunk


logger = logging.getLogger(__name__)

# Create router
router = APIRouter(
    prefix="/agent",
    tags=["Agents"],  # Using "Agents" as a tag example
)

# Lazy import to avoid circular dependency with agents.agent_manager
if TYPE_CHECKING:
    from agents.agent_manager import AgentManager  # type: ignore


async def _resolve_agent_manager() -> "AgentManager":
    """Lazy dependency resolver to avoid circular import at module import time."""
    from agents.agent_manager import AgentManager

    return AgentManager()


def _build_service_response(raw: dict, session_id: str, vehicle_id: str | None = None) -> AgentServiceResponse:
    return AgentServiceResponse(
        response=raw.get("response", ""),
        success=raw.get("success", True),
        session_id=session_id,
        plugins_used=raw.get("plugins_used", []),
        execution_time=raw.get("execution_time", 0),
        data=raw.get("data"),
        fallback_used=raw.get("fallback_used", False),
        error=raw.get("error"),
        vehicle_id=vehicle_id,
    )


def _streaming_chunk_from(raw: dict, session_id: str) -> StreamingChunk:
    return StreamingChunk(
        response=raw.get("response", ""),
        complete=raw.get("complete", False),
        plugins_used=raw.get("plugins_used", []),
        error=raw.get("error"),
        session_id=session_id,
    )


# Debug marker to confirm module import success (helps distinguish import vs runtime attach issues)
logger.debug("agent_routes module imported successfully")

# Agent system entry point with streaming support
@router.post("/ask", response_model=None)
async def ask_agent(request: AgentQueryRequest, agent_manager: "AgentManager" = Depends(_resolve_agent_manager)):
    session_id = request.session_id or str(uuid.uuid4())
    context = request.context or {}
    context["session_id"] = session_id
    agent_type = context.get("agent_type")
    if agent_type:
        agent_type_mapping = {
            "remote-access": "remote_access",
            "safety-emergency": "safety_emergency",
            "charging-energy": "charging_energy",
            "information-services": "information_services",
            "feature-control": "vehicle_feature_control",
            "diagnostics-battery": "diagnostics_battery",
            "alerts-notifications": "alerts_notifications",
        }
        context["agent_type"] = agent_type_mapping.get(agent_type, agent_type)
    if request.stream:
        async def stream_generator():
            async for chunk in agent_manager.process_request_stream(request.query, context):
                yield f"data: {_streaming_chunk_from(chunk, session_id).model_dump_json(by_alias=True)}\n\n"
        return StreamingResponse(stream_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})
    raw = await agent_manager.process_request(request.query, context)
    return _build_service_response(raw, session_id)


# Pattern helper to reduce duplication
async def _handle_direct_agent(request: AgentQueryRequest, agent_key: str, agent_manager: "AgentManager") -> Union[AgentServiceResponse, StreamingResponse]:
    session_id = request.session_id or str(uuid.uuid4())
    context = request.context or {}
    context.update({"agent_type": agent_key, "session_id": session_id})
    if request.stream:
        async def stream_generator():
            async for chunk in agent_manager.process_request_stream(request.query, context):
                yield f"data: {_streaming_chunk_from(chunk, session_id).model_dump_json(by_alias=True)}\n\n"
        return StreamingResponse(stream_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})
    raw = await agent_manager.process_request(request.query, context)
    return _build_service_response(raw, session_id)


@router.post("/remote-access", response_model=None)
async def query_remote_access(
    request: AgentQueryRequest,
    agent_manager: "AgentManager" = Depends(_resolve_agent_manager),
):
    """Query the Remote Access Agent directly"""
    return await _handle_direct_agent(request, "remote_access", agent_manager)


@router.post("/safety-emergency", response_model=None)
async def query_safety_emergency(
    request: AgentQueryRequest,
    agent_manager: "AgentManager" = Depends(_resolve_agent_manager),
):
    """Query the Safety & Emergency Agent directly"""
    return await _handle_direct_agent(request, "safety_emergency", agent_manager)


@router.post("/charging-energy", response_model=None)
async def query_charging_energy(
    request: AgentQueryRequest,
    agent_manager: "AgentManager" = Depends(_resolve_agent_manager),
):
    """Query the Charging & Energy Agent directly"""
    return await _handle_direct_agent(request, "charging_energy", agent_manager)


@router.post("/information-services", response_model=None)
async def query_information_services(
    request: AgentQueryRequest,
    agent_manager: "AgentManager" = Depends(_resolve_agent_manager),
):
    """Query the Information Services Agent directly"""
    return await _handle_direct_agent(request, "information_services", agent_manager)


@router.post("/feature-control", response_model=None)
async def query_feature_control(
    request: AgentQueryRequest,
    agent_manager: "AgentManager" = Depends(_resolve_agent_manager),
):
    """Query the Vehicle Feature Control Agent directly"""
    return await _handle_direct_agent(request, "vehicle_feature_control", agent_manager)


@router.post("/diagnostics-battery", response_model=None)
async def query_diagnostics_battery(
    request: AgentQueryRequest,
    agent_manager: "AgentManager" = Depends(_resolve_agent_manager),
):
    """Query the Diagnostics & Battery Agent directly"""
    return await _handle_direct_agent(request, "diagnostics_battery", agent_manager)


@router.post("/alerts-notifications", response_model=None)
async def query_alerts_notifications(
    request: AgentQueryRequest,
    agent_manager: "AgentManager" = Depends(_resolve_agent_manager),
):
    """Query the Alerts & Notifications Agent directly"""
    return await _handle_direct_agent(request, "alerts_notifications", agent_manager)


# Analytics endpoints that use agent capabilities
@router.post("/analyze/vehicle-data")
async def analyze_vehicle_data_endpoint(request: AnalysisRequest, agent_manager: "AgentManager" = Depends(_resolve_agent_manager)) -> AgentServiceResponse:
    session_id = str(uuid.uuid4())
    context = {"agent_type": "diagnostics_battery", "vehicle_id": request.vehicle_id, "time_period": request.time_period, "metrics": request.metrics, "session_id": session_id}
    raw = await agent_manager.process_request("Run a full diagnostic analysis on my vehicle", context)
    return _build_service_response(raw, session_id, vehicle_id=request.vehicle_id)

@router.post("/recommend/services")
async def recommend_services_endpoint(request: ServiceRecommendationRequest, agent_manager: "AgentManager" = Depends(_resolve_agent_manager)) -> AgentServiceResponse:
    session_id = str(uuid.uuid4())
    context = {"agent_type": "vehicle_feature_control", "vehicle_id": request.vehicle_id, "mileage": request.mileage, "last_service_date": request.last_service_date, "session_id": session_id}
    raw = await agent_manager.process_request("Recommend vehicle services based on my vehicle condition", context)
    return _build_service_response(raw, session_id, vehicle_id=request.vehicle_id)