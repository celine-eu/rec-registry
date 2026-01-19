from __future__ import annotations

from fastapi import APIRouter

from celine.rec_registry.core.settings import settings

router = APIRouter(tags=["meta"])


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/version")
async def version():
    return {"name": "celine-rec-registry", "version": "0.1.0", "context_version": settings.context_version}
