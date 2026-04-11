import os
import time
import requests
from fastapi import APIRouter, HTTPException
from azure.identity import AzureCliCredential, DefaultAzureCredential, ManagedIdentityCredential
from models.api_request import AskAIRequest
from models.api_responses import AIResponse, SpeechTokenResponse, GenericPayloadResponse
from agent_framework import Agent
from plugin.oai_service import create_chat_client
from utils.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/speech", tags=["Speech"])

# Simple in-memory token cache (Speech tokens valid ~10 min)
_TOKEN_CACHE = {"token": None, "expires": 0, "region": None}

# Cognitive Services token scope for managed identity auth
_COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"

_AZURE_ENV_VARS = ["WEBSITE_SITE_NAME", "WEBSITE_INSTANCE_ID", "MSI_ENDPOINT", "IDENTITY_ENDPOINT"]


def _get_bearer_token() -> str:
    """Obtain an Entra ID bearer token for Cognitive Services.

    On App Service uses system-assigned ManagedIdentityCredential (avoids
    AZURE_CLIENT_ID being misinterpreted as a user-assigned MI client ID).
    Locally falls back to AzureCliCredential then DefaultAzureCredential.
    """
    try:
        if any(os.getenv(v) for v in _AZURE_ENV_VARS):
            credential = ManagedIdentityCredential()
        else:
            tenant_id = os.getenv("AZURE_TENANT_ID")
            try:
                credential = AzureCliCredential(tenant_id=tenant_id) if tenant_id else AzureCliCredential()
            except Exception:
                credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        token = credential.get_token(_COGNITIVE_SCOPE)
        return token.token
    except Exception as exc:
        logger.error(f"Failed to acquire Cognitive Services bearer token: {exc}")
        raise HTTPException(
            status_code=503,
            detail="Speech authentication is not configured correctly.",
        ) from exc


def _get_speech_auth_headers() -> dict:
    """Return auth headers using either API key or managed identity."""
    speech_key = os.getenv("AZURE_SPEECH_KEY")
    if speech_key:
        return {"Ocp-Apim-Subscription-Key": speech_key}
    return {"Authorization": f"Bearer {_get_bearer_token()}"}


def _get_speech_endpoint() -> str:
    """Return the base Speech endpoint.

    When a custom subdomain is configured (AZURE_SPEECH_ENDPOINT), use it
    (required for managed-identity / token auth).  Otherwise fall back to
    the regional endpoint (works only with API key).
    """
    endpoint = os.getenv("AZURE_SPEECH_ENDPOINT")
    if endpoint:
        return endpoint.rstrip("/")
    speech_region = os.getenv("AZURE_SPEECH_REGION")
    if not speech_region:
        raise HTTPException(status_code=503, detail="Speech region not configured")
    return f"https://{speech_region}.api.cognitive.microsoft.com"


def _issue_speech_token():
    base = _get_speech_endpoint()
    speech_region = os.getenv("AZURE_SPEECH_REGION")
    if not speech_region:
        raise HTTPException(status_code=503, detail="Speech region not configured")
    url = f"{base}/sts/v1.0/issueToken"
    headers = _get_speech_auth_headers()
    try:
        resp = requests.post(url, headers=headers, timeout=5)
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to reach Speech service: {exc}"
        )
    if resp.status_code != 200:
        logger.warning(
            f"Speech token request failed with status {resp.status_code}: {resp.text}"
        )
        if resp.status_code in (401, 403):
            raise HTTPException(
                status_code=503,
                detail="Speech token request was rejected. Check AZURE_SPEECH_KEY and AZURE_SPEECH_REGION.",
            )
        raise HTTPException(status_code=502, detail="Speech token request failed.")
    # Cache for 9 minutes (token lifetime 10 minutes)
    _TOKEN_CACHE.update(
        {"token": resp.text, "expires": time.time() + 9 * 60, "region": speech_region}
    )


def _issue_ice_token():
    speech_region = os.getenv("AZURE_SPEECH_REGION")
    if not speech_region:
        raise HTTPException(status_code=503, detail="Speech region not configured")
    # Ensure we have a valid speech token first (needed for relay auth)
    cached = _get_cached_token()
    # ICE relay endpoint uses the regional TTS host with the STS speech token
    url = f"https://{speech_region}.tts.speech.microsoft.com/cognitiveservices/avatar/relay/token/v1"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {cached['token']}"}
    try:
        resp = requests.get(url, headers=headers, timeout=5)
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to reach ICE token service: {exc}"
        )
    if resp.status_code != 200:
        logger.warning(
            f"Speech ICE token request failed with status {resp.status_code}: {resp.text}"
        )
        if resp.status_code in (401, 403):
            raise HTTPException(
                status_code=503,
                detail=(
                    "Speech avatar ICE token request was rejected. "
                    "Check AZURE_SPEECH_KEY, AZURE_SPEECH_REGION, and avatar support on the Speech resource."
                ),
            )
        raise HTTPException(status_code=502, detail="ICE token request failed.")
    try:
        return resp.json()
    except ValueError:
        raise HTTPException(
            status_code=502, detail="Invalid JSON response from ICE token service"
        )


def _get_cached_token():
    if time.time() >= _TOKEN_CACHE["expires"] or not _TOKEN_CACHE["token"]:
        _issue_speech_token()
    return {"token": _TOKEN_CACHE["token"], "region": _TOKEN_CACHE["region"]}


@router.get("/token", response_model=SpeechTokenResponse)
def speech_token():
    """Alias route to match frontend expectation (/api/speech/token)."""
    cached = _get_cached_token()
    return SpeechTokenResponse(**cached)


@router.get("/ice_token", response_model=GenericPayloadResponse)
def speech_ice_token():
    return GenericPayloadResponse(payload=_issue_ice_token())


@router.post("/ask_ai", response_model=AIResponse)
async def ask_ai(req: AskAIRequest):
    """
    Direct AI response using Microsoft Agent Framework.
    Supports conversation history and vehicle context.
    Accepts optional language_code from client to localize response.
    """
    try:
        client = create_chat_client()
        language_code = req.language_code  # Provided by frontend (auto-detected)

        # Enhanced system prompt for vehicle context
        system_prompt = (
            req.system
            or """You are a helpful AI assistant for a connected vehicle platform.
                You assist users with vehicle operations, diagnostics, navigation, and general inquiries.
                Keep responses concise and actionable. When asked about vehicle-specific features, provide practical guidance.

                Do not add highlight entries — this text will be used for text-to-speech.

                The response should be simple and concise. The response should be in the form of a single paragraph.
                If you don't know the answer, just say you don't know. Do not make up an answer.
                """
        )
        if language_code:
            system_prompt += f"{os.linesep} Please respond in {language_code}."

        agent = Agent(
            client=client,
            name="VehicleAssistant",
            instructions=system_prompt,
        )

        prompt = req.normalized_messages_text()
        if not prompt:
            raise HTTPException(status_code=400, detail="Empty message payload")

        result = await agent.run(prompt)
        response_text = result.text.strip() if hasattr(result, "text") else str(result).strip()

        if not response_text:
            raise HTTPException(status_code=502, detail="Empty response from AI service")

        return AIResponse(response=response_text)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI request failed: {e}")
