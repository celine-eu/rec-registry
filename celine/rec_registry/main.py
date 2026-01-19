from __future__ import annotations

from fastapi import FastAPI

from celine.rec_registry.api.communities import router as communities_router
from celine.rec_registry.api.contexts import router as contexts_router
from celine.rec_registry.api.meta import router as meta_router

app = FastAPI(title="CELINE REC Registry", version="0.1.0")

app.include_router(meta_router)
app.include_router(contexts_router)
app.include_router(communities_router)
