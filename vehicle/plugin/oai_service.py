import os
from agent_framework.openai import OpenAIChatClient
from utils.logging_config import get_logger

logger = get_logger(__name__)

_AZURE_ENVIRONMENT_VARS = [
    "WEBSITE_SITE_NAME", "WEBSITE_INSTANCE_ID",
    "MSI_ENDPOINT", "IDENTITY_ENDPOINT",
]


def _is_azure_environment() -> bool:
    return any(os.getenv(v) for v in _AZURE_ENVIRONMENT_VARS)


def _get_azure_credential():
    """Return an Azure credential for managed-identity / CLI-based Azure OpenAI auth."""
    from azure.identity import (
        AzureCliCredential,
        DefaultAzureCredential,
        ManagedIdentityCredential,
    )

    if _is_azure_environment():
        logger.info("Azure environment detected – using ManagedIdentityCredential for OpenAI")
        return ManagedIdentityCredential()

    tenant_id = os.getenv("AZURE_TENANT_ID")
    try:
        cred = AzureCliCredential(tenant_id=tenant_id) if tenant_id else AzureCliCredential()
        logger.info("Using AzureCliCredential for OpenAI (tenant=%s)", tenant_id or "default")
        return cred
    except Exception:
        pass

    logger.info("Falling back to DefaultAzureCredential for OpenAI")
    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


def create_chat_client() -> OpenAIChatClient:
    """
    Factory: returns an OpenAIChatClient that auto-detects the auth method.

    Routing precedence:
      1. OPENAI_API_KEY              → OpenAI (non-Azure)
      2. AZURE_OPENAI_API_KEY        → Azure OpenAI with API key
      3. AZURE_OPENAI_ENDPOINT (only) → Azure OpenAI with managed identity / CLI credential

    Env vars consumed by OpenAIChatClient:
      Azure : AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_MODEL
      OpenAI: OPENAI_API_KEY, OPENAI_MODEL
    """
    if os.getenv("OPENAI_API_KEY"):
        logger.info("Using OpenAI with API key")
        return OpenAIChatClient()

    if os.getenv("AZURE_OPENAI_API_KEY"):
        logger.info("Using Azure OpenAI with API key")
        return OpenAIChatClient()

    if os.getenv("AZURE_OPENAI_ENDPOINT"):
        logger.info("Using Azure OpenAI with managed identity / CLI credential")
        return OpenAIChatClient(credential=_get_azure_credential())

    raise ValueError(
        "No AI provider configured. "
        "Set OPENAI_API_KEY, AZURE_OPENAI_API_KEY, or AZURE_OPENAI_ENDPOINT."
    )
