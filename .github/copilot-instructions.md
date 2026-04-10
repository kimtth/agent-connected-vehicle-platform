# Agentic Connected Vehicle Platform – AI Assistant Project Instructions

These instructions orient AI coding agents working in this repo. Focus on concrete, existing patterns—avoid inventing new architectures unless requested.

# Naming rules

## 🖥️ UI Components (camelCase)

- The interaction between UI and backend is handled via REST APIs, which use **camelCase** for JSON fields. The conversion between camelCase and snake_case is managed by Pydantic models in the backend.
- All UI elements follow the **camelCase** naming convention. 
- The `cosmos_db` component in the backend uses **camelCase** naming convention. 
- Backend components also follow **snake_case**. 

# 📘 Project Instruction UI

Welcome to the project! This README provides instructions for setting up and using the UI, `cosmos_db`, and backend components.


## 1. Architecture Snapshot
Backend (Python / FastAPI) lives in `vehicle/` and is the system of record + agent hub. Key layers:
- Entry point: `vehicle/main.py` – config, middleware, router loading, SSE streaming, MCP sidecar process launch (weather/traffic/poi/navigation on ports 8001–8004) and graceful shutdown.
- Routers: `vehicle/apis/*.py` grouped by domain (agents, vehicle features, remote access, emergency/safety, speech, dev seed). Loaded dynamically in `lifespan()`; missing modules are tolerated (log a warning, continue startup).
- Data access: `vehicle/vehicle_azure/cosmos_db.py` – async singleton (`get_cosmos_client()`) with resilient connect / retry, container auto-provisioning, polling-based status subscription (no change feed listener yet), camelCase storage via Pydantic models.
- Auth: `vehicle/vehicle_azure/azure_auth.py` – middleware validating Azure AD JWT if configured; supports optional mode. Accepts both raw GUID and `api://GUID` audiences, plus multiple acquisition channels (headers, query, cookies, DEV_BEARER_TOKEN env). Certain dev endpoints bypass auth.
- Agents: `vehicle/agents/*` – Microsoft Agent Framework `Agent` instances orchestrated by `AgentManager` (`agent_manager.py`). Manager aggregates domain agent tools (decorated with `@tool`) + general tools (`plugin/general_tools.py`) into a single coordinating agent and provides streaming + fallback logic.
- Plugins / AI client factory: `vehicle/plugin/oai_service.py` returns an `OpenAIChatClient` from `agent-framework-openai` which auto-detects Azure OpenAI (managed identity or API key) vs OpenAI from environment variables.
- Models: `vehicle/models/*.py` – All inherit from `CamelModel` which enforces outbound camelCase and accepts inbound snake_case or camelCase.
- Frontend (React) in `web/` (not deeply coupled—consumes REST + SSE `/api/vehicle/{id}/status/stream` and agent endpoints `/api/agent/*`).
- Dev seed + mock data: `vehicle/apis/dev_seed_routes.py` (creates demo vehicles/status) and MCP mock servers under `vehicle/plugin/mcp_*` (started as subprocesses when `ENABLE_MCP=true`).

## 2. Data & Serialization Conventions
- Always use model classes (`VehicleStatus`, `Command`, etc.) for API responses; they serialize camelCase automatically (`CamelModel`). Do NOT manually convert field names.
- Cosmos containers use partition key `/vehicleId`; queries frequently specify `partition_key=vehicleId` for efficiency—preserve this when adding queries.
- Status updates always create a new document (`update_vehicle_status` writes a fresh item with a generated `id` + timestamp). Do not mutate historical status docs.
- Commands/notifications sometimes have both `Id` and logical IDs (`command_id`); retain existing casing to avoid breaking stored items—prefer adding fields rather than renaming.

## 3. Async, Concurrency, and Streaming
- All Cosmos operations are async; ensure new endpoints `await client.ensure_connected()` before queries.
- SSE streaming of status: generator in `main.py` wraps `subscribe_to_vehicle_status()` (polls at 1s after updates, 5s idle). If extending, keep yields formatted as: `data: <json>\n\n`.
- Agent streaming: `agent_routes.ask_agent(stream=true)` uses `process_request_stream`; chunk model is `StreamingChunk` (camelCase). Maintain chunk shape for frontend compatibility.

## 4. Agent Orchestration Patterns
- `AgentManager.process_request()` builds a synthetic prompt: `Query: ...\nContext: {json}`. The single coordinating `Agent` has all domain tools registered; the LLM selects which tool to invoke via function calling.
- To add a new specialized agent: create a module under `vehicle/agents/` with `@tool`-decorated async functions (matching existing patterns), export a `*_TOOLS` list, import and concatenate the tools in `agent_manager.py._all_tools`. If a new public route form is exposed, update `agent_type_mapping` in `apis/agent_routes.py`.
- Fallback path (`_process_with_fallback`) creates a fresh `Agent` instance—keep this lightweight; avoid coupling to new heavy tools.

## 5. Azure Integration Nuances
- Auth optional by default; enforce by setting `AZURE_AUTH_REQUIRED=true`. When adding routes that must stay open for local dev, append to `exclude_prefixes` or `exclude_exact` cautiously.
- Cosmos: environment toggles AAD vs key (`COSMOS_DB_USE_AAD=true`). In local dev with AAD, code uses `AzureDeveloperCliCredential` (requires `azd auth login` / `az login`). Avoid introducing blocking credential flows inside request handlers.

## 6. Environment & Startup
Essential env vars (see `.env.sample` referenced in README):
- API: `API_HOST`, `API_PORT`, `ENABLE_MCP`
- Cosmos: `COSMOS_DB_ENDPOINT`, `COSMOS_DB_KEY` or `COSMOS_DB_USE_AAD=true`
- Auth: `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_AUTH_REQUIRED`
- AI: `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_MODEL` (managed identity) or `AZURE_OPENAI_API_KEY` (key auth) or `OPENAI_API_KEY` + `OPENAI_MODEL`
- Logging: `LOG_LEVEL`

Run backend locally:
```
cd vehicle
uv sync
python main.py
```
(Ensure `az login` first if using AAD Cosmos.)

## 7. Testing & Dev Utilities
- Minimal tests in `vehicle/tests/` are illustrative, not authoritative; use `pytest` but note some files are outdated (e.g., refer to older route shapes). Validate against current router prefixes (`/api/...`). Update tests instead of reverting APIs.
- Dev seed: POST `/api/dev/seed` (see README for bulk variants) to populate vehicles/status for UI.

## 8. Logging & Diagnostics
- Central logging configuration: `utils/logging_config.py` (invoked early in `main.py`). Avoid redefining handlers—use module loggers via `get_logger` helper.
- Noisy MCP startup warnings filtered via `_SuppressMcpLoopWarning`—preserve the filter logic if refactoring import paths.

## 9. When Extending
- Prefer adding new FastAPI routers under `vehicle/apis/` and register them in the lifespan loop to keep lazy, fault-tolerant loading.
- For new models: inherit `CamelModel` to keep serialization uniform; do not manually call `to_camel`.
- Maintain idempotent startup: avoid global side effects at import time (besides lightweight logger setup & env reads). Heavy I/O belongs in `lifespan`.
- Graceful shutdown: if you spawn new processes/threads, append them to `MCP_PROCESSES` or implement similar tracked cleanup.

## 10. Common Pitfalls to Avoid
- Calling Cosmos client connect logic per request (use `get_cosmos_client()` + `ensure_connected`).
- Returning raw dicts with snake_case keys (frontend expects camelCase per models).
- Blocking operations (e.g., long computations) inside request handlers without `await`—use background tasks or async patterns like `process_command_async`.
- Forgetting to add CORS headers for new SSE endpoints—mirror existing implementation.

## 11. Quick Reference: Key Files
- `vehicle/main.py` – server lifecycle, routes inclusion, SSE, MCP subprocess management.
- `vehicle/vehicle_azure/cosmos_db.py` – data layer & polling subscription.
- `vehicle/agents/agent_manager.py` – orchestration via Microsoft Agent Framework `Agent` with all domain tools.
- `vehicle/apis/agent_routes.py` – agent HTTP interface (+ streaming).
- `vehicle/models/base.py` – camelCase model contract.
- `vehicle/plugin/oai_service.py` – AI provider selection (OpenAIChatClient from agent-framework-openai).

---
If any convention above seems ambiguous (e.g., adding a new agent type or status field), ask for clarification before large refactors.
