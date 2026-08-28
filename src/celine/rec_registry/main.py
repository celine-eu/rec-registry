"""
CELINE REC Registry API - Main application.
"""

from fastapi import FastAPI

from celine.rec_registry.core.middleware import PolicyMiddleware
from celine.rec_registry.core.versions import CURRENT_SCHEMA_VERSION, api_version
from celine.rec_registry.api.meta import router as meta_router
from celine.rec_registry.api.user import router as user_router

from celine.rec_registry.api.admin.communities import router as communities_router
from celine.rec_registry.api.admin.lookup import router as lookup_router
from celine.rec_registry.api.admin.writes import router as writes_router
from celine.rec_registry.api.admin.management import router as management_router


def create_app():
    # The two values here are derived for the same reason `/version` derives its
    # own (REQ-0058): they were literals, and literals nobody reads drift. This
    # pair drifts *further* than most, because `info.version` is what
    # `../celine-sdk` names its snapshot of this API after — a version that does
    # not move while the document does means a generated client is overwritten
    # in place, and no consumer can tell the API changed.
    app = FastAPI(
        title="CELINE REC Registry API",
        description=(
            "Registry API for Renewable Energy Communities "
            f"(bundle schema v{CURRENT_SCHEMA_VERSION})"
        ),
        version=api_version(),
    )

    # Add policy middleware for authentication and authorization
    # Configuration via environment variables:
    # - AUTH_ENABLED: Enable JWT authentication
    # - AUTH_VERIFY_JWT: Verify JWT signatures
    # - AUTH_JWKS_URI: JWKS endpoint for verification
    # - POLICIES_ENABLED: Enable policies service integration
    # - POLICIES_URL: Policies service URL
    app.add_middleware(PolicyMiddleware)

    # Include routers
    app.include_router(user_router)
    app.include_router(meta_router)

    app.include_router(prefix="/admin", tags=["admin"], router=management_router)
    app.include_router(prefix="/admin", tags=["admin"], router=communities_router)
    app.include_router(prefix="/admin", tags=["admin"], router=lookup_router)
    app.include_router(prefix="/admin", tags=["admin"], router=writes_router)

    return app
