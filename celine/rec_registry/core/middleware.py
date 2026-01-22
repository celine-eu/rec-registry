from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from .policy import AccessPolicy


class PolicyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, policy: AccessPolicy | None = None):
        super().__init__(app)
        self.policy = policy or AccessPolicy()

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method.upper()
        is_admin = path.startswith("/admin")
        is_write = method in {"POST", "PUT", "PATCH", "DELETE"}

        if is_admin:
            d = await self.policy.allow_admin(request)
            if not d.allowed:
                return JSONResponse(
                    {"detail": d.reason or "Admin access denied"}, status_code=403
                )

        if is_write and not is_admin:
            d = await self.policy.allow_write(request)
            if not d.allowed:
                return JSONResponse(
                    {"detail": d.reason or "Write access denied"}, status_code=403
                )

        return await call_next(request)
