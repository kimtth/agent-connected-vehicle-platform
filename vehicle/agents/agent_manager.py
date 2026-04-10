from typing import Dict, Any, Optional, AsyncGenerator, List
import json

from agent_framework import Agent
from vehicle_azure.cosmos_db import get_cosmos_client

from agents.alerts_notifications_agent import ALERTS_NOTIFICATIONS_TOOLS
from agents.charging_energy_agent import CHARGING_ENERGY_TOOLS
from agents.diagnostics_battery_agent import DIAGNOSTICS_BATTERY_TOOLS
from agents.information_services_agent import INFORMATION_SERVICES_TOOLS
from agents.remote_access_agent import REMOTE_ACCESS_TOOLS
from agents.safety_emergency_agent import SAFETY_EMERGENCY_TOOLS
from agents.vehicle_feature_control_agent import VEHICLE_FEATURE_CONTROL_TOOLS
from plugin.oai_service import create_chat_client
from plugin.general_tools import GENERAL_TOOLS
from utils.logging_config import get_logger
from utils.vehicle_object_utils import ensure_dict
from models.agent_response import (
    ParsedAgentMessage,
    AgentResponse,
    StreamingChunk,
)

logger = get_logger(__name__)


class AgentManager:
    """
    Vehicle AgentManager using Microsoft Agent Framework.
    Coordinates specialized agents for vehicle operations and provides a unified interface.
    """

    def __init__(self):
        self.cosmos_client = get_cosmos_client()
        self._all_tools = (
            REMOTE_ACCESS_TOOLS
            + SAFETY_EMERGENCY_TOOLS
            + CHARGING_ENERGY_TOOLS
            + INFORMATION_SERVICES_TOOLS
            + VEHICLE_FEATURE_CONTROL_TOOLS
            + DIAGNOSTICS_BATTERY_TOOLS
            + ALERTS_NOTIFICATIONS_TOOLS
            + GENERAL_TOOLS
        )
        client = create_chat_client()
        self.manager = Agent(
            client=client,
            name="VehicleManagerAgent",
            instructions=(
                "You are a vehicle management coordinator that routes requests to specialized tools. "
                "Analyze the user's request and context to determine the appropriate tool. "
                "Provide clear, helpful responses and indicate which tools were used. "
                "Highlight keywords in the response. Be concise. "
                "Output with markdown format."
            ),
            tools=self._all_tools,
        )
        # Session for multi-turn conversations (keyed by session_id)
        self._sessions: Dict[str, Any] = {}

    def _get_session(self, session_id: str):
        """Get or create a session for multi-turn conversations."""
        if session_id not in self._sessions:
            self._sessions[session_id] = self.manager.create_session()
        return self._sessions[session_id]

    async def _get_vehicle_data(self, vehicle_id: str) -> Optional[Dict[str, Any]]:
        if not vehicle_id:
            return None
        await self.cosmos_client.ensure_connected()
        vehicle = await self.cosmos_client.get_vehicle(vehicle_id)
        return ensure_dict(vehicle)

    async def _enrich_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        enriched_context = context.copy()
        vehicle_id = context.get("vehicleId")
        if not vehicle_id:
            return enriched_context
        vehicle_data = await self._get_vehicle_data(vehicle_id)
        if vehicle_data:
            enriched_context["vehicleData"] = vehicle_data
            enriched_context["vehicleId"] = vehicle_id
        vehicle_status = ensure_dict(await self.cosmos_client.get_vehicle_status(vehicle_id))
        if vehicle_status:
            enriched_context["vehicleStatus"] = vehicle_status
        return enriched_context

    def _parse_response_safely(self, response_content, plugins_used: Optional[List[str]] = None) -> ParsedAgentMessage:
        if hasattr(response_content, "text"):
            content = response_content.text
        elif hasattr(response_content, "content"):
            content = response_content.content
        else:
            content = str(response_content)
        content = content.strip() if content else ""
        if content.startswith("{") and content.endswith("}"):
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    return ParsedAgentMessage(
                        message=parsed.get("message") or content,
                        status=parsed.get("status") or "completed",
                        plugins_used=parsed.get("plugins_used") or [],
                        data=parsed.get("data"),
                    )
            except json.JSONDecodeError:
                pass
        return ParsedAgentMessage(
            message=content or "Command executed successfully.",
            plugins_used=[]
        )

    def _build_agent_response(
        self,
        parsed: ParsedAgentMessage,
        fallback_used: bool = False,
        error: Optional[str] = None,
    ) -> AgentResponse:
        return AgentResponse(
            response=parsed.message or "The command has been processed successfully.",
            success=parsed.status == "completed",
            plugins_used=parsed.plugins_used or [],
            data=parsed.data,
            fallback_used=fallback_used,
            error=error,
        )

    async def process_request(self, query: str, context: Dict[str, Any]) -> Dict[str, Any]:
        session_id = context.get("session_id", "default")
        context["query"] = query
        enriched_context = await self._enrich_context(context)
        session = self._get_session(session_id)
        prompt = f"Query: {query}\nContext: {json.dumps(enriched_context, default=str)}"
        try:
            result = await self.manager.run(prompt, session=session)
            parsed = self._parse_response_safely(result)
            return self._build_agent_response(parsed).model_dump(by_alias=True)
        except Exception:
            return await self._process_with_fallback(query, enriched_context)

    async def _process_with_fallback(self, query: str, enriched_context: Dict[str, Any]) -> Dict[str, Any]:
        client = create_chat_client()
        fallback_agent = Agent(
            client=client,
            name="VehicleManagerFallback",
            instructions="You are a vehicle management coordinator. Analyze the user's request and provide a helpful response.",
            tools=self._all_tools,
        )
        prompt = f"Query: {query}\nContext: {json.dumps(enriched_context, default=str)}"
        result = await fallback_agent.run(prompt)
        parsed = self._parse_response_safely(result)
        return self._build_agent_response(parsed, fallback_used=True).model_dump(by_alias=True)

    async def process_request_stream(self, query: str, context: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        session_id = context.get("session_id", "default")
        context["query"] = query
        enriched_context = await self._enrich_context(context)
        yield StreamingChunk(response="Processing your request...", complete=False).model_dump(by_alias=True)

        session = self._get_session(session_id)
        prompt = f"Query: {query}\nContext: {json.dumps(enriched_context, default=str)}"
        full_response = ""
        try:
            async for chunk in self.manager.run(prompt, session=session, stream=True):
                text = ""
                if hasattr(chunk, "text") and chunk.text:
                    text = chunk.text
                elif isinstance(chunk, str):
                    text = chunk
                if text:
                    text = text.replace("\r", "")
                    full_response += text
                    yield StreamingChunk(response=full_response, complete=False, plugins_used=[]).model_dump(by_alias=True)
            parsed = self._parse_response_safely(full_response or "I processed your request.")
            yield StreamingChunk(response=parsed.message, complete=True, plugins_used=parsed.plugins_used or []).model_dump(by_alias=True)
        except Exception as e:
            yield StreamingChunk(response="Error processing request.", complete=True, plugins_used=[], error=str(e)).model_dump(by_alias=True)


# FastAPI scoped dependency factory
async def get_agent_manager() -> AgentManager:
    return AgentManager()
