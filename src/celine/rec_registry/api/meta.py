from __future__ import annotations
from pathlib import Path

from fastapi import APIRouter

from celine.rec_registry.core.settings import settings

router = APIRouter(tags=["meta"])


@router.get("/health")
async def health():
    return {"status": "ok"}
