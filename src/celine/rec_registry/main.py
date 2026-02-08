"""
CELINE REC Registry API - Main application.
"""

from fastapi import FastAPI

from celine.rec_registry.core.middleware import PolicyMiddleware
from celine.rec_registry.api.admin import router as admin_router
from celine.rec_registry.api.meta import router as meta_router
from celine.rec_registry.api.communities import router as communities_router

app = FastAPI(
    title="CELINE REC Registry API",
    description="Registry API for Renewable Energy Communities",
    version="1.0.0",
)

# Add policy middleware for future auth extension
app.add_middleware(PolicyMiddleware)

# Include routers
app.include_router(meta_router)
app.include_router(admin_router)
app.include_router(communities_router)
