import os
import time
import requests
from fastapi import APIRouter, HTTPException
from azure.identity import DefaultAzureCredential
from models.api_request import AskAIRequest
from models.api_responses import AIResponse, SpeechTokenResponse, GenericPayloadResponse
from agent_framework import Agent
from plugin.oai_service import create_chat_client

router = APIRouter(prefix="/speech", tags=["Speech"])

# Simple in-memory token cache (Speech tokens valid ~10 min)
_TOKEN_CACHE = {"token": None, "expires": 0, "region": None}

# Cognitive Services token scope for managed identity auth
_COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"


def _get_bearer_token() -> str:
    """Obtain an Entra ID bearer token for Cognitive Services."""
    credential = DefaultAzureCredential()
    token = credential.get_token(_COGNITIVE_SCOPE)
    return token.token


def _get_speech_auth_headers() -> dict:
    """Return auth headers using either API key or managed identity."""
    speech_key = os.getenv("AZURE_SPEECH_KEY")
    if speech_key:
        return {"Ocp-Apim-Subscription-Key": speech_key}
    return {"Authorization": f"Bearer {_get_bearer_token()}"}


def _issue_speech_token():
    speech_region = os.getenv("AZURE_SPEECH_REGION")
    if not speech_region:
        raise HTTPException(status_code=500, detail="Speech region not configured")
    url = f"https://{speech_region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    headers = _get_speech_auth_headers()
    try:
        resp = requests.post(url, headers=headers, timeout=5)
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to reach Speech service: {exc}"
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    # Cache for 9 minutes (token lifetime 10 minutes)
    _TOKEN_CACHE.update(
        {"token": resp.text, "expires": time.time() + 9 * 60, "region": speech_region}
    )


def _issue_ice_token():
    speech_region = os.getenv("AZURE_SPEECH_REGION")
    if not speech_region:
        raise HTTPException(status_code=500, detail="Speech region not configured")
    url = f"https://{speech_region}.tts.speech.microsoft.com/cognitiveservices/avatar/relay/token/v1"
    headers = {"Accept": "application/json", **_get_speech_auth_headers()}
    try:
        resp = requests.get(url, headers=headers, timeout=5)
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to reach ICE token service: {exc}"
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
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
