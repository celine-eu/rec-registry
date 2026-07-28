"""
Access policy middleware with JWT authentication and in-process policy evaluation.

Rules:
- Public paths (/health, /version, /docs, etc.): no auth required
- /me* paths: require valid JWT user
- /admin* paths: require valid JWT user + policies check
- All other paths: pass through (no auth required)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import parse_qs

from celine.sdk.auth import JwtUser
from celine.sdk.auth.jwt import extract_groups
from celine.sdk.policies import (
    Action,
    CachedPolicyEngine,
    PolicyEngine,
    PolicyInput,
    Resource,
    ResourceType,
    Subject,
    SubjectType,
)
from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from celine.rec_registry.core.settings import settings

logger = logging.getLogger(__name__)

REQUEST_USER_KEY = "user"

# Methods that only read. Everything else mutates and is authorized separately.
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _wants_purge(query: str) -> bool:
    """Whether a delete asks for permanent erasure rather than deactivation.

    Read from the raw query string because the authorization decision is made
    before the route parses anything. Anything not explicitly truthy is a soft
    delete: the safe reading of an ambiguous request is the recoverable one.
    """
    return parse_qs(query).get("purge", ["false"])[-1].strip().lower() in _TRUTHY


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
    - /admin*: require valid JWT + in-process policy check
    - Other paths: pass through
    """

    def __init__(self, app):
        super().__init__(app)

        # Initialize in-process policy engine
        self._policy_engine: CachedPolicyEngine | None = None
        if settings.policies_enabled:
            try:
                # Create base engine
                engine = PolicyEngine(
                    policies_dir=settings.policies_dir,
                    data_dir=settings.policies_data_dir,
                )
                engine.load()

                # Wrap with cache
                self._policy_engine = CachedPolicyEngine(
                    engine=engine,
                    enabled=settings.policies_cache_enabled,
                )

                logger.info(
                    f"Policy engine initialized: "
                    f"{engine.policy_count} policies loaded, "
                    f"packages: {engine.get_packages()}"
                )
            except Exception as e:
                logger.error(f"Failed to initialize policy engine: {e}")
                raise

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
        if path.startswith("/me") or path.startswith("/user"):
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
                    action=self._get_admin_action(
                        path, request.method, request.url.query
                    ),
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

    def _get_admin_action(self, path: str, method: str, query: str = "") -> str:
        """Name the action an admin request performs.

        Derived from the path *and* the method, because reading a community and
        rewriting its members are not the same permission. While every admin
        route was a read this distinction did not exist; now that a service
        account can create members it does, and granting a writer the ability to
        read everything — or a reader the ability to write — is the kind of
        over-grant `rec-registry.admin` was already too broad for.

        `rec-registry.admin` continues to satisfy all of these: the shared scope
        matcher treats `{service}.admin` as covering `{service}.*`, so nothing
        that works today stops working.
        """
        if "lookup" in path:
            return "lookup"
        if "import" in path:
            return "import"
        if "export" in path:
            return "export"

        if method in _READ_METHODS:
            return "read"

        # Writes are named by what they touch. Assets is checked first because an
        # asset path contains "/members" too.
        if "/assets" in path:
            return "assets.write"
        if "/members" in path:
            # Erasure is not deactivation. Deactivating a member is recoverable;
            # purging them takes their assets with it and cannot be undone, so it
            # is a grant an operator can withhold from a service that otherwise
            # manages members.
            if method == "DELETE" and _wants_purge(query):
                return "members.purge"
            return "members.write"
        return "community.write"

    def _get_resource_id(self, path: str) -> str:
        """Extract resource identifier from path."""
        return path.strip("/") or "root"

    async def _extract_user(self, request: Request) -> JwtUser | None:
        """Extract and validate user from JWT token."""
        auth_header = request.headers.get(settings.auth_header_name)
        if not auth_header:
            return None

        try:
            return JwtUser.from_token(auth_header, oidc=settings.oidc)
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
        """Check authorization via in-process policy evaluation."""
        if self._policy_engine is None:
            return Decision(True)

        request_id = request.headers.get("X-Request-ID", "unknown")

        # Build resource attributes
        resource_attributes = {"user_sub": user.get_username()}
        if user.email:
            resource_attributes["user_email"] = user.email

        # Extract scopes from JWT claims
        scopes = user.claims.get("scope", "")
        if isinstance(scopes, str):
            scopes = scopes.split()
        elif not isinstance(scopes, list):
            scopes = []

        groups = extract_groups(user.claims)

        # Build policy input
        policy_input = PolicyInput(
            subject=Subject(
                id=user.get_username(),
                type=SubjectType.USER,
                groups=groups,
                scopes=scopes,
                claims=user.claims,
            ),
            resource=Resource(
                type=ResourceType(settings.policies_resource_type),
                id=resource_id,
                attributes=resource_attributes,
            ),
            action=Action(
                name=action,
                context={},
            ),
            environment={
                "request_id": request_id,
                "timestamp": time.time(),
                "path": request.url.path,
                "method": request.method,
            },
        )

        try:
            # Evaluate policy in-process
            decision = self._policy_engine.evaluate_decision(
                policy_package=settings.policies_package,
                policy_input=policy_input,
            )

            if decision.cached:
                logger.debug(f"Policy decision from cache: allowed={decision.allowed}")
            else:
                logger.info(
                    f"Policy decision: allowed={decision.allowed}, "
                    f"reason={decision.reason}, "
                    f"policy={decision.policy}"
                )

            return Decision(
                allowed=decision.allowed,
                reason=decision.reason or None,
            )

        except Exception as e:
            logger.error(f"Policy evaluation error: {e}", exc_info=True)
            # Fail closed - deny access on error
            return Decision(False, reason="Authorization check failed")


# =============================================================================
# FastAPI Dependencies
# =============================================================================


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
