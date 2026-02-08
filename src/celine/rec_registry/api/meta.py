"""
Meta API routes (health, version, etc.)
"""

from fastapi import APIRouter

router = APIRouter(tags=["meta"])


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@router.get("/version")
async def version():
    """API version info."""
    return {
        "api_version": "1.0.0",
        "schema_version": "0.4",
    }
