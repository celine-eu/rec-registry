from __future__ import annotations

import json
from importlib import resources

from fastapi import APIRouter, Response

from celine.rec_registry.core.settings import settings

router = APIRouter(tags=["context"])


@router.get("/contexts/celine/{version}")
async def get_context(version: str):
    if version != settings.context_version:
        return Response(status_code=404)

    with resources.files("celine.rec_registry.resources").joinpath("celine-context.jsonld").open("rb") as f:
        data = f.read()

    # Serve as application/ld+json
    return Response(content=data, media_type="application/ld+json")
