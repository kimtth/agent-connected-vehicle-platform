from typing import Any, Optional, Dict, List
from models.base import BaseSchemaModel


class AgentQueryRequest(BaseSchemaModel):
    query: str
    context: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None
    stream: Optional[bool] = False


class AnalysisRequest(BaseSchemaModel):
    vehicle_id: str
    time_period: Optional[str] = "7d"
    metrics: Optional[List[str]] = None


class ServiceRecommendationRequest(BaseSchemaModel):
    vehicle_id: str
    mileage: Optional[int] = None
    last_service_date: Optional[str] = None


class EmergencyCallRequest(BaseSchemaModel):
    emergency_type: Optional[str] = "general"  # general, medical, fire, police


class CollisionReportRequest(BaseSchemaModel):
    severity: str = "unknown"  # minor, major, severe, unknown
    location: Optional[Dict[str, float]] = None


class TheftReportRequest(BaseSchemaModel):
    description: Optional[str] = None
    last_seen_location: Optional[Dict[str, float]] = None


class DoorControlRequest(BaseSchemaModel):
    action: str  # lock, unlock


class EngineControlRequest(BaseSchemaModel):
    action: str  # start, stop


class LightsControlRequest(BaseSchemaModel):
    light_type: str = "headlights"  # headlights, interior_lights, hazard_lights
    action: str = "on"  # on, off


class ClimateControlRequest(BaseSchemaModel):
    temperature: Optional[int] = 22
    action: str = "set_temperature"  # heating, cooling, set_temperature
    auto: bool = True


class WindowsControlRequest(BaseSchemaModel):
    action: str = "up"  # up, down
    windows: str = "all"  # all, driver, passenger
