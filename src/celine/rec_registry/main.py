"""
CELINE REC Registry API - Main application.
"""

from fastapi import FastAPI

from celine.rec_registry.core.middleware import PolicyMiddleware
from celine.rec_registry.api.meta import router as meta_router
from celine.rec_registry.api.user import router as user_router

from celine.rec_registry.api.admin.communities import router as communities_router
from celine.rec_registry.api.admin.lookup import router as lookup_router
from celine.rec_registry.api.admin.management import router as management_router

app = FastAPI(
    title="CELINE REC Registry API",
    description="Registry API for Renewable Energy Communities (v0.4 schema)",
    version="1.0.0",
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
