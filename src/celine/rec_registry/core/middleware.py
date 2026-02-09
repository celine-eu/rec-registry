"""
Access policy middleware with JWT authentication and policies service integration.

Rules:
- Public paths (/health, /version, /docs, etc.): no auth required
- /me* paths: require valid JWT user
- /admin* paths: require valid JWT user + policies check
- All other paths: pass through (no auth required)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from celine.sdk.auth import JwtUser
from celine.sdk.policies import AuthorizationClient, AuthorizationError

from celine.rec_registry.core.settings import settings

logger = logging.getLogger(__name__)

REQUEST_USER_KEY = "user"


@dataclass(frozen=True)
class Decision:
    """Authorization decision."""

    allowed: bool
    reason: str | None = None


def get_current_user(request: Request) -> JwtUser | None:
    """
    Get the authenticated user from the request state.

    Usage in route handlers:
        user = get_current_user(request)
    """
    return getattr(request.state, REQUEST_USER_KEY, None)


class PolicyMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces authentication and authorization rules:

    - Public paths: no auth required
    - /me*: require valid JWT
    - /admin*: require valid JWT + policies service check
    - Other paths: pass through
    """

    def __init__(self, app):
        super().__init__(app)

        self._policies_client: AuthorizationClient | None = None
        if settings.policies_enabled:
            self._policies_client = AuthorizationClient(
                base_url=settings.policies_url,
                timeout=settings.policies_timeout,
            )
            logger.info(f"Policies client initialized: {settings.policies_url}")

        logger.info(
            f"PolicyMiddleware initialized: "
            f"auth_enabled={settings.auth_enabled}, "
            f"policies_enabled={settings.policies_enabled}"
        )

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Public paths - no auth required
        if self._is_public_path(path):
            return await call_next(request)

        # /me* paths - require valid JWT
        if path.startswith("/me"):
            user = await self._extract_user(request)
            if user is None:
                return JSONResponse(
                    {"detail": "Authentication required"},
                    status_code=401,
                )
            request.state.user = user
            return await call_next(request)

        # /admin* paths - require valid JWT + policies check
        if path.startswith("/admin"):
            user = await self._extract_user(request)
            if user is None:
                return JSONResponse(
                    {"detail": "Authentication required"},
                    status_code=401,
                )
            request.state.user = user

            # Check policies if enabled
            if settings.policies_enabled:
                decision = await self._check_policies(
                    request=request,
                    user=user,
                    action=self._get_admin_action(path),
                    resource_id=self._get_resource_id(path),
                )
                if not decision.allowed:
                    return JSONResponse(
                        {"detail": decision.reason or "Access denied"},
                        status_code=403,
                    )

            return await call_next(request)

        # All other paths - pass through, optionally extract user if token present
        if settings.auth_enabled:
            user = await self._extract_user(request)
            if user:
                request.state.user = user

        return await call_next(request)

    def _is_public_path(self, path: str) -> bool:
        """Check if path is public (no auth required)."""
        public_paths = {"/health", "/version", "/openapi.json", "/docs", "/redoc"}
        return path in public_paths or path.startswith("/docs/")

    def _get_admin_action(self, path: str) -> str:
        """Get action name for admin paths."""
        if "import" in path:
            return "import"
        if "export" in path:
            return "export"
        return "admin"

    def _get_resource_id(self, path: str) -> str:
        """Extract resource identifier from path."""
        return path.strip("/") or "root"

    async def _extract_user(self, request: Request) -> JwtUser | None:
        """Extract and validate user from JWT token."""
        auth_header = request.headers.get(settings.auth_header_name)
        if not auth_header:
            return None

        try:
            return JwtUser.from_token(
                auth_header,
                verify=settings.auth_verify_jwt,
                jwks_uri=settings.auth_jwks_uri,
                audience=settings.auth_audience,
                issuer=settings.auth_issuer,
            )
        except ValueError as e:
            logger.warning(f"Invalid JWT token: {e}")
            return None
        except Exception as e:
            logger.error(f"JWT extraction error: {e}")
            return None

    async def _check_policies(
        self,
        request: Request,
        user: JwtUser,
        action: str,
        resource_id: str,
    ) -> Decision:
        """Check authorization via policies service."""
        if self._policies_client is None:
            return Decision(True)

        auth_header = request.headers.get(settings.auth_header_name)
        request_id = request.headers.get("X-Request-ID")

        resource_attributes = {"user_sub": user.sub}
        if user.email:
            resource_attributes["user_email"] = user.email

        try:
            response = await self._policies_client.authorize_detailed(
                action=action,
                resource_type=settings.policies_resource_type,
                resource_id=resource_id,
                resource_attributes=resource_attributes,
                authorization_header=auth_header,
                x_request_id=request_id,
                x_source_service=settings.policies_source_service,
            )
            reason = getattr(response, "reason", None)
            return Decision(allowed=response.allowed, reason=reason)

        except AuthorizationError as e:
            logger.error(f"Policies service error: {e}")
            return Decision(False, reason="Authorization service unavailable")
        except Exception as e:
            logger.error(f"Unexpected policies error: {e}")
            return Decision(False, reason="Authorization check failed")


# =============================================================================
# FastAPI Dependencies
# =============================================================================

from fastapi import HTTPException


async def require_user(request: Request) -> JwtUser:
    """FastAPI dependency that requires an authenticated user."""
    user = get_current_user(request)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def optional_user(request: Request) -> JwtUser | None:
    """FastAPI dependency that optionally returns the authenticated user."""
    return get_current_user(request)
