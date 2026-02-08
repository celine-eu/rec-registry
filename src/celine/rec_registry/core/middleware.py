"""
Access policy middleware with JWT authentication and policies service integration.

Extracts user from JWT token and delegates authorization to policies service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from celine.sdk.auth import JwtUser
from celine.sdk.policies import AuthorizationClient, AuthorizationError

from celine.rec_registry.core.settings import settings

logger = logging.getLogger(__name__)


# Request state key for storing the authenticated user
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
        from celine.rec_registry.core.middleware import get_current_user

        @router.get("/protected")
        async def protected_route(request: Request):
            user = get_current_user(request)
            if user is None:
                raise HTTPException(401, "Not authenticated")
            return {"user_id": user.sub}
    """
    return getattr(request.state, REQUEST_USER_KEY, None)


class PolicyMiddleware(BaseHTTPMiddleware):
    """
    Middleware that:
    1. Extracts user from JWT token (if auth is enabled)
    2. Delegates authorization to policies service (if policies are enabled)
    3. Falls back to allow-all if both are disabled

    Configuration via environment variables:
    - AUTH_ENABLED: Enable JWT extraction
    - AUTH_VERIFY_JWT: Verify JWT signature (requires AUTH_JWKS_URI)
    - AUTH_JWKS_URI: JWKS endpoint for signature verification
    - POLICIES_ENABLED: Enable policies service integration
    - POLICIES_URL: Policies service base URL
    """

    def __init__(self, app):
        super().__init__(app)

        # Initialize policies client if enabled
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
        # Skip auth for health/meta endpoints
        if self._is_public_path(request.url.path):
            return await call_next(request)

        # Extract user from JWT if auth is enabled
        user: JwtUser | None = None
        if settings.auth_enabled:
            user = await self._extract_user(request)
            if user is None:
                return JSONResponse(
                    {"detail": "Authentication required"},
                    status_code=401,
                )
            # Store user in request state for route handlers
            request.state.user = user

        # Determine action based on HTTP method and path
        action = self._get_action(request)
        resource_id = self._get_resource_id(request)

        # Check authorization via policies service if enabled
        if settings.policies_enabled:
            decision = await self._check_policies(
                request=request,
                user=user,
                action=action,
                resource_id=resource_id,
            )
            if not decision.allowed:
                return JSONResponse(
                    {"detail": decision.reason or "Access denied"},
                    status_code=403,
                )

        return await call_next(request)

    def _is_public_path(self, path: str) -> bool:
        """Check if path is public (no auth required)."""
        public_paths = {"/health", "/version", "/openapi.json", "/docs", "/redoc"}
        return path in public_paths or path.startswith("/docs/")

    async def _extract_user(self, request: Request) -> JwtUser | None:
        """
        Extract and validate user from JWT token.

        Returns None if token is missing or invalid.
        """
        # Get token from header
        auth_header = request.headers.get(settings.auth_header_name)
        if not auth_header:
            logger.debug("No authorization header present")
            return None

        try:
            user = JwtUser.from_token(
                auth_header,
                verify=settings.auth_verify_jwt,
                jwks_uri=settings.auth_jwks_uri,
                audience=settings.auth_audience,
                issuer=settings.auth_issuer,
            )

            logger.debug(f"Authenticated user: {user.sub}")
            return user

        except ValueError as e:
            logger.warning(f"Invalid JWT token: {e}")
            return None
        except Exception as e:
            logger.error(f"JWT extraction error: {e}")
            return None

    def _get_action(self, request: Request) -> str:
        """
        Determine action based on HTTP method and path.

        Maps HTTP methods to policy actions:
        - GET -> read
        - POST -> create (or admin for /admin/import)
        - PUT/PATCH -> update
        - DELETE -> delete
        - /admin/* -> admin
        """
        method = request.method.upper()
        path = request.url.path

        # Admin endpoints
        if path.startswith("/admin"):
            if "import" in path:
                return "import"
            if "export" in path:
                return "export"
            return "admin"

        # Standard CRUD actions
        action_map = {
            "GET": "read",
            "POST": "create",
            "PUT": "update",
            "PATCH": "update",
            "DELETE": "delete",
        }
        return action_map.get(method, "read")

    def _get_resource_id(self, request: Request) -> str:
        """
        Extract resource identifier from request path.

        Examples:
        - /communities/my_rec -> my_rec
        - /communities/my_rec/members/m-001 -> my_rec/members/m-001
        - /admin/import -> admin/import
        - /lookup/member-by-user-id/123 -> lookup/member-by-user-id
        """
        path = request.url.path.strip("/")

        # For lookup endpoints, don't include the lookup value
        if path.startswith("lookup/"):
            parts = path.split("/")
            if len(parts) >= 2:
                return f"{parts[0]}/{parts[1]}"

        return path or "root"

    async def _check_policies(
        self,
        request: Request,
        user: JwtUser | None,
        action: str,
        resource_id: str,
    ) -> Decision:
        """
        Check authorization via policies service.

        Returns Decision with allowed=True/False and optional reason.
        """
        if self._policies_client is None:
            # Policies not configured, allow by default
            return Decision(True)

        # Get authorization header to forward
        auth_header = request.headers.get(settings.auth_header_name)

        # Get request ID for tracing
        request_id = request.headers.get("X-Request-ID")

        # Build resource attributes
        resource_attributes = {}
        if user:
            resource_attributes["user_sub"] = user.sub
            if user.email:
                resource_attributes["user_email"] = user.email

        try:
            response = await self._policies_client.authorize_detailed(
                action=action,
                resource_type=settings.policies_resource_type,
                resource_id=resource_id,
                resource_attributes=resource_attributes or None,
                authorization_header=auth_header,
                x_request_id=request_id,
                x_source_service=settings.policies_source_service,
            )

            reason = str(response.reason) if hasattr(response, "reason") else None
            return Decision(allowed=response.allowed, reason=reason)

        except AuthorizationError as e:
            logger.error(f"Policies service error: {e}")
            # On policies service error, deny by default for safety
            return Decision(False, reason="Authorization service unavailable")
        except Exception as e:
            logger.error(f"Unexpected policies error: {e}")
            return Decision(False, reason="Authorization check failed")


# =============================================================================
# FastAPI Dependency for getting current user
# =============================================================================

from fastapi import Depends, HTTPException


async def require_user(request: Request) -> JwtUser:
    """
    FastAPI dependency that requires an authenticated user.

    Usage:
        @router.get("/protected")
        async def protected_route(user: JwtUser = Depends(require_user)):
            return {"user_id": user.sub}
    """
    user = get_current_user(request)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def optional_user(request: Request) -> JwtUser | None:
    """
    FastAPI dependency that optionally returns the authenticated user.

    Usage:
        @router.get("/maybe-protected")
        async def maybe_protected(user: JwtUser | None = Depends(optional_user)):
            if user:
                return {"user_id": user.sub}
            return {"anonymous": True}
    """
    return get_current_user(request)
