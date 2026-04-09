from datetime import datetime
from typing import Any, Optional, Dict
from .base import BaseSchemaModel

# Assuming global camelCase alias generation is configured centrally (models.py),
# so we only specify explicit aliases where names differ.

class ActionResponse(BaseSchemaModel):
    message: Optional[str] = ""
    data: Any
    success: Optional[bool] = True

class AIResponse(BaseSchemaModel):
    response: str

class SpeechTokenResponse(BaseSchemaModel):
    token: str
    region: str

class GenericPayloadResponse(BaseSchemaModel):
    payload: Dict[str, Any]

class InfoResponse(BaseSchemaModel):
    status: str
    version: str
    azure_cosmos_enabled: bool
    azure_cosmos_connected: bool

class HealthServices(BaseSchemaModel):
    api: str
    cosmos_db: str
    mcp_weather: str
    mcp_traffic: str
    mcp_poi: str
    mcp_navigation: str

class HealthResponse(BaseSchemaModel):
    status: str
    timestamp: datetime
    services: HealthServices

class CommandHistoryItem(BaseSchemaModel):
    timestamp: str
    command: str
    status: str
    response: Optional[str] = ""
    error: Optional[str] = ""

class CommandSubmitResponse(BaseSchemaModel):
    command_id: str

class Notification(BaseSchemaModel):
    id: str
    vehicle_id: str
    type: str
    message: str
    timestamp: datetime
    read: bool = False

class CreateNotificationResponse(BaseSchemaModel):
    id: str
    status: str
    data: Any

class MarkNotificationReadResponse(BaseSchemaModel):
    id: str
    status: str
    data: Any

class GenericDetailResponse(BaseSchemaModel):
    detail: str


class FleetMetrics(BaseSchemaModel):
    total_vehicles: int
    active_vehicles: int
    low_battery: int
    maintenance_needed: int
    avg_battery: float
    total_distance: float
