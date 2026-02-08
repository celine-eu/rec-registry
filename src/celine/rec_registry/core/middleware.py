"""
Access policy middleware for authorization.

Currently allows all requests; designed for future extension with
role-based access control.
"""

from dataclasses import dataclass
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


@dataclass(frozen=True)
class Decision:
    """Authorization decision."""
    allowed: bool
    reason: str | None = None


class AccessPolicy:
    """
    Base access policy - allows all requests.
    
    Subclass and override methods to implement custom authorization logic.
    """

    async def allow_admin(self, request: Request) -> Decision:
        """Check if admin endpoints are allowed."""
        return Decision(True)

    async def allow_write(self, request: Request) -> Decision:
        """Check if write operations are allowed."""
        return Decision(True)

    async def allow_read(self, request: Request) -> Decision:
        """Check if read operations are allowed."""
        return Decision(True)


class PolicyMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces access policy on all requests.
    """

    def __init__(self, app, policy: AccessPolicy | None = None):
        super().__init__(app)
        self.policy = policy or AccessPolicy()

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method.upper()
        is_admin = path.startswith("/admin")
        is_write = method in {"POST", "PUT", "PATCH", "DELETE"}

        # Check admin access
        if is_admin:
            decision = await self.policy.allow_admin(request)
            if not decision.allowed:
                return JSONResponse(
                    {"detail": decision.reason or "Admin access denied"},
                    status_code=403,
                )

        # Check write access (non-admin routes)
        if is_write and not is_admin:
            decision = await self.policy.allow_write(request)
            if not decision.allowed:
                return JSONResponse(
                    {"detail": decision.reason or "Write access denied"},
                    status_code=403,
                )

        return await call_next(request)
