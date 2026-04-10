# 🚗 Agentic Connected Vehicle Platform

An AI agent-driven car management system: control, diagnostics, and insights via agents.

> [!IMPORTANT]  
> The code in this repository was developed during a hackathon and implemented within a limited timeline. It is intended for demonstration purposes only.

## ✨ Features
- 🗣️ Natural-language agent interface for intuitive commands and queries
- 🚗 In-vehicle assistant for real-time driver and passenger support
- 🔒 Remote access: lock/unlock, engine start/stop
- 📍 Smart integration of weather, traffic, and points of interest (via Model Context Protocol)
- 🎛️ In-car controls for climate, lighting, and windows
- 🔧 Diagnostics and proactive maintenance
- 🔔 Real-time alerts with notifications

## 🛠️ Tech Stack
- Backend: Python 3.13+, FastAPI, Microsoft Agent Framework (`agent-framework`, `agent-framework-openai`)
- DB: Azure Cosmos DB (AAD auth)
- AI: Azure OpenAI (managed identity) / OpenAI
- Frontend: React, Tailwind CSS
- MCP: Weather, Traffic, POI, Navigation via FastMCP (sample data in plugin/mcp_mock_data.py)

> Full architecture, agent specs, and API list: see [ARCHITECTURE.md](./ARCHITECTURE.md).

### Data / Naming Conventions
- External (API, frontend, Cosmos stored docs): camelCase via Pydantic CamelModel.
- Backend Python attributes: snake_case.
- Do not manually recase dict keys—always return model instances.

## 🚀 Quick Start

```bash
# Authenticate with Azure (if needed for cloud services)
az login

# --- Frontend (web) ---
cd web
# Copy example env files and edit values before running
cp .env.example .env.development
cp .env.example .env.production
pnpm install

# --- Backend / Vehicle service ---
cd ../vehicle
# Copy backend env and edit values
cp .env.sample .env
uv sync

# --- Run services (use two terminals) ---
# Terminal A: start frontend
cd ../web
pnpm start

# Terminal B: start backend
cd ../vehicle
python main.py
```

## 🐳 Docker Deployment

> [!TIP]   
> The Dockerfile uses `uv` for Python dependency management and `pnpm` for frontend builds.

```bash
# 1. Copy and configure environment
copy .env.docker.sample .env.docker
# Edit .env.docker - update your values

# 2. Start application
docker-compose --env-file .env.docker up -d --build
# docker-compose --env-file .env.docker down -v

# 3. Seed test data
curl -X POST http://localhost:8000/api/dev/seed

# Access:
# - Application: http://localhost:8000
```

## ☁️ Azure Deployment

```bash
# (Optional) Create Azure Resource Group in your subscription
az group create --name <resource-group-name> --location <location-name>

# (Optional) Create Azure OpenAI and Speech Service.
# Be sure to edit values in params.json before deployment.

# Deploy Azure infrastructure
cd infra
powershell ./run_infra_deploy.ps1
cd ..
```

Deploy the backend package to App Service with the repository script:

```powershell
cd infra
./run_webapp_deploy.ps1 -ResourceGroup <resource-group-name> -WebAppName <app-name>
```

The deployment script:
- Regenerates `uv.lock` and `vehicle/requirements.txt` from `vehicle/pyproject.toml`
- Builds the backend zip package from the current source tree
- Ensures the App Service startup command uses Gunicorn with the Uvicorn worker
- Uploads the package with `az webapp deploy`

After deployment:
- Azure Portal: add your web app URL to Entra ID > Authentication > Single-page application > Redirect URIs
- Cosmos DB: enable the web app system-assigned managed identity and grant the required Cosmos DB data-plane role

Note: 
MCP services use deterministic sample data in plugin/mcp_mock_data.py.

## 📖 Documentation
For full API reference, architecture, and examples, see the project documentation.

### Dashboard Overview
![Platform Dashboard](./doc/dashboard.png)

### Natural Language Agent Interface
![Agent Chat Interface](./doc/agent_chat.png)

### Vehicle Simulation & Control
![Car Simulator](./doc/car_simulator.png)

### Vehicle Assistant
![Vehicle Assistant](./doc/vehicle-assistant.png)

### Remote Drive Control 
![Remote Drive Control](./doc/remote_drive.png)

> [!NOTE]  
> Remote Drive Control — developed UI only: The `gateway.py` module needs to be implemented to connect with the server of [this machine](https://github.com/Freenove/Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi). It is intended to showcase how the vehicle can be controlled through the vehicle API.  
>  
> The original code is implemented in the Python GUI client. To expose the controls to the frontend, a `gateway.py` is required to convert and transport the payload for use in the UI. 

## Create Test Data (Dev Seed)

Use the built-in dev seed endpoint to create a demo vehicle and initial status for local testing.

- Default seed (creates demo vehicle if not present):
```bash
curl -X POST http://localhost:8000/api/dev/seed
```

- Seed a specific vehicleId:
```bash
curl -X POST "http://localhost:8000/api/dev/seed?vehicleId=a640f210-dca4-4db7-931a-9f119bbe54e0"
```

- Verify the status:
```bash
curl http://localhost:8000/api/vehicles/a640f210-dca4-4db7-931a-9f119bbe54e0/status
```

Bulk seed multiple demo vehicles and related data into Cosmos DB:
```bash
curl -X POST http://localhost:8000/api/dev/seed/bulk \
  -H "Content-Type: application/json" \
  -d '{
    "vehicles": 5,
    "commandsPerVehicle": 2,
    "notificationsPerVehicle": 2,
    "servicesPerVehicle": 1,
    "statusesPerVehicle": 1
  }'
```

Check last seed summary:
```bash
curl http://localhost:8000/api/dev/seed/status
```

VS Code REST Client
- Open vehicle/seed_test_vehicle.rest and click “Send Request” on:
  - POST {{host}}/api/dev/seed
  - POST {{host}}/api/dev/seed?vehicleId={{vehicleId}}
  - POST {{host}}/api/dev/seed/bulk

Note: This endpoint is for development only. Do not expose it in production.

## 🔐 Entra ID (formerly Azure AD) Authentication — App Registration & Access Token

This step is required for API authentication in the backend and sign-in handling in the frontend.
API authentication will be skipped If `API_TEST_MODE` is set to `true`.
This environment variable is for development purposes only.

Set your backend env (vehicle/.env):
```env
AZURE_TENANT_ID=<tenant-guid>
AZURE_CLIENT_ID=api://<your-app-client-id> or <your-app-client-id>   # Application ID URI (aud)
AZURE_AUTH_REQUIRED=true
```
Frontend requests the scope (note: scope = audience + "/access_as_user"):
```env
REACT_APP_AZURE_CLIENT_ID=<client-guid>   # NOT the api:// Application ID URI
REACT_APP_AZURE_TENANT_ID=<tenant-guid>
REACT_APP_AZURE_SCOPE=api://<client-guid>/access_as_user
```

## 📜 License
MIT © kimtth
