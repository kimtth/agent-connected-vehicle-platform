"""
Minimal Azure AD authentication middleware:
- Only /api* routes are authenticated; all other paths skip auth entirely
- Validates incoming Bearer JWT (if present / required) for /api routes
- Attaches decoded token to request.state.user
- NEVER redirects - only returns JSON 401 for /api paths when auth fails
"""

import os
import logging
from typing import Optional
from jwt import PyJWKClient, ExpiredSignatureError
from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class AzureADMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, tenant_id: Optional[str] = None):
        super().__init__(app)
        self.tenant_id = tenant_id or os.getenv("AZURE_TENANT_ID")
        self.auth_required = os.getenv("AZURE_AUTH_REQUIRED", "false").lower() == "true"
        self.issuer_v2 = f"https://login.microsoftonline.com/{self.tenant_id}/v2.0" if self.tenant_id else None
        self.jwks_uri = "https://login.microsoftonline.com/common/discovery/keys"
        self.jwk_client = PyJWKClient(self.jwks_uri)
        raw_audience = os.getenv("AZURE_CLIENT_ID")
        if raw_audience:
            guid = raw_audience.replace("api://", "") if raw_audience.startswith("api://") else raw_audience
            self.audiences = [raw_audience, guid] if raw_audience.startswith("api://") else [raw_audience, f"api://{raw_audience}"]
        else:
            self.audiences = []
        self.exclude_exact = {"/", "/health", "/api/info", "/api/health", "/api/debug/cosmos", "/openapi.json", "/favicon.ico"}
        self.exclude_prefixes = ("/docs", "/static", "/redoc", "/api/dev/seed")

    def _attempt_token_retrieval(self, request: Request) -> Optional[str]:
        raw = (request.headers.get("X-Auth-Token") or request.headers.get("X-Authorization") or 
               request.query_params.get("access_token") or 
               request.cookies.get("access_token") or request.cookies.get("auth_token") or request.cookies.get("token") or 
               os.getenv("DEV_BEARER_TOKEN"))
        if raw:
            raw = raw.strip()
            return raw if raw.lower().startswith("bearer ") else f"Bearer {raw}"
        return None

    def _get_signing_key(self, token: str) -> Optional[str]:
        try:
            return self.jwk_client.get_signing_key_from_jwt(token).key
        except Exception:
            return None

    async def dispatch(self, request: Request, call_next):
        path = request.url.path.rstrip("/") if request.url.path != "/" else "/"
        if os.getenv("API_TEST_MODE") == "true" or not path.startswith("/api") or request.method == "OPTIONS" or path in self.exclude_exact or any(path.startswith(p) for p in self.exclude_prefixes if p.startswith("/api/")):
            return await call_next(request)
        if not (self.tenant_id and self.issuer_v2 and self.jwks_uri):
            return JSONResponse(status_code=500, content={"detail": "Azure AD auth not configured"}) if self.auth_required else await call_next(request)
        auth_header = request.headers.get("Authorization") or request.headers.get("authorization") or self._attempt_token_retrieval(request)
        if not auth_header:
            return JSONResponse(status_code=401, content={"detail": "Authorization required"}, headers={"WWW-Authenticate": "Bearer"}) if self.auth_required else await call_next(request)
        try:
            scheme, token = auth_header.split(" ", 1)
            if scheme.lower() != "bearer":
                raise ValueError()
        except ValueError:
            return JSONResponse(status_code=401, content={"detail": "Invalid authorization header format"}) if self.auth_required else await call_next(request)
        decoded = await self._validate_token(token)
        if not decoded:
            return JSONResponse(status_code=401, content={"detail": "Invalid or expired token"}) if self.auth_required else await call_next(request)
        request.state.user = decoded
        return await call_next(request)

    async def _validate_token(self, token: str) -> Optional[dict]:
        try:
            signing_key = self._get_signing_key(token)
            if not signing_key:
                return None
            for audience in self.audiences:
                try:
                    return jwt.decode(token, signing_key, algorithms=["RS256"], audience=audience, issuer=self.issuer_v2, options={"verify_aud": True, "verify_iss": True, "verify_exp": True})
                except (jwt.InvalidAudienceError, jwt.InvalidIssuerError):
                    continue
                except ExpiredSignatureError:
                    return None
            return None
        except Exception:
            return None


class AzureADBearer(HTTPBearer):
    """
    Optional per-route auth dependency.

    NOT required if global AzureADMiddleware + AZURE_AUTH_REQUIRED=true
    already protects all routes.

    Keep/use when you need:
      - Selective protection (set AZURE_AUTH_REQUIRED=false globally; add Depends(AzureADBearer()))
      - Easier unit tests (mock dependency instead of middleware)

    Returns decoded claims dict or raises (401/500) when auth is required;
    returns None in optional mode if token missing/invalid.

    Usage:
        from .azure_auth import AzureADBearer
        get_user = AzureADBearer()
        @app.get("/secure")
        async def secure(user=Depends(get_user)):
            return {"user": user}
    """

    def __init__(self, auto_error: bool = True):
        super().__init__(auto_error=auto_error)
        self.tenant_id = os.getenv("AZURE_TENANT_ID")
        self.auth_required = os.getenv("AZURE_AUTH_REQUIRED", "false").lower() == "true"
        self.issuer_v2 = f"https://login.microsoftonline.com/{self.tenant_id}/v2.0" if self.tenant_id else None
        self.jwks_uri = "https://login.microsoftonline.com/common/discovery/keys"
        self.jwk_client = PyJWKClient(self.jwks_uri)
        raw_audience = os.getenv("AZURE_CLIENT_ID")
        if raw_audience:
            guid = raw_audience.replace("api://", "") if raw_audience.startswith("api://") else raw_audience
            self.audiences = [raw_audience, guid] if raw_audience.startswith("api://") else [raw_audience, f"api://{raw_audience}"]
        else:
            self.audiences = []

    def _get_signing_key(self, token: str) -> Optional[str]:
        """Get signing key from JWKS endpoint."""
        try:
            key_obj = self.jwk_client.get_signing_key_from_jwt(token)
            return key_obj.key
        except Exception as exc:
            if self.auth_required:
                logger.error(
                    "AzureADBearer: failed to get signing key from %s - %s",
                    self.jwks_uri,
                    str(exc),
                )
            return None

    async def __call__(self, request: Request) -> Optional[dict]:
        credentials: HTTPAuthorizationCredentials = await super().__call__(request)
        if not credentials or credentials.scheme.lower() != "bearer":
            if self.auth_required:
                raise HTTPException(status_code=401, detail="Authorization required", headers={"WWW-Authenticate": "Bearer"})
            return None
        if not (self.tenant_id and self.issuer_v2):
            if self.auth_required:
                raise HTTPException(status_code=500, detail="Azure AD auth not configured")
            return None
        signing_key = self._get_signing_key(credentials.credentials)
        if not signing_key:
            if self.auth_required:
                raise HTTPException(status_code=401, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
            return None
        try:
            for audience in self.audiences:
                try:
                    return jwt.decode(credentials.credentials, signing_key, algorithms=["RS256"], audience=audience, issuer=self.issuer_v2, options={"verify_aud": True, "verify_iss": True, "verify_exp": True})
                except (jwt.InvalidAudienceError, jwt.InvalidIssuerError):
                    continue
        except ExpiredSignatureError:
            if self.auth_required:
                raise HTTPException(status_code=401, detail="Token expired")
        except Exception:
            if self.auth_required:
                raise HTTPException(status_code=401, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
        return None
