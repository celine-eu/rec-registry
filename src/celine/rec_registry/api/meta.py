"""
Meta API routes (health, version, etc.)
"""

from fastapi import APIRouter

from celine.rec_registry.core.versions import CURRENT_SCHEMA_VERSION, api_version

router = APIRouter(tags=["meta"])


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@router.get("/version")
async def version():
    """What is deployed here.

    Both fields are derived — `api_version` from the installed distribution and
    `schema_version` from the one constant every other reader of it uses. They
    were literals typed into this file, which is how the route came to answer
    `1.0.0` while the package was on 1.5.0, and `0.4` while nothing anywhere
    else said `0.4`.
    """
    return {
        "api_version": api_version(),
        "schema_version": CURRENT_SCHEMA_VERSION,
    }
