from fastapi import FastAPI
from celine.rec_registry.core.middleware import PolicyMiddleware
from celine.rec_registry.api.admin import router as admin_router
from celine.rec_registry.api.meta import router as meta
from celine.rec_registry.api.communities import router as communities_router

app = FastAPI(title="CELINE Registry API", version="0.1.0")
app.add_middleware(PolicyMiddleware)

app.include_router(meta)
app.include_router(admin_router)
app.include_router(communities_router)
