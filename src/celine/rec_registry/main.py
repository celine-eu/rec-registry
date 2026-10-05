"""
CELINE REC Registry API - Main application.
"""

from celine.sdk.audit import configure_audit
from celine.sdk.posture import docs_urls
from fastapi import FastAPI

from celine.rec_registry.core.access_log import install_access_log_redaction
from celine.rec_registry.core.errors import install_error_handlers
from celine.rec_registry.core.middleware import PolicyMiddleware
from celine.rec_registry.core.posture import enforce_posture
from celine.rec_registry.core.settings import settings
from celine.rec_registry.core.versions import CURRENT_SCHEMA_VERSION, api_version
from celine.rec_registry.api.meta import router as meta_router
from celine.rec_registry.api.user import router as user_router

from celine.rec_registry.api.admin.communities import router as communities_router
from celine.rec_registry.api.admin.lookup import router as lookup_router
from celine.rec_registry.api.admin.writes import router as writes_router
from celine.rec_registry.api.admin.management import router as management_router

# The service name every `celine.audit` record of this process carries (REQ-0091).
configure_audit("rec-registry")


def create_app():
    # Refuse development defaults before anything acts on them (REQ-0088): the
    # policy engine is loaded by the middleware below, and the first request
    # opens the database pool. Only CELINE_ENV=dev relaxes this; unset is
    # hardened.
    enforce_posture(settings)

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
        # /docs, /redoc and /openapi.json only under CELINE_ENV=dev, or with
        # CELINE_PUBLIC_DOCS=true (REQ-0092). `app.openapi()` is unaffected,
        # which is what `../celine-sdk` and the schema tests read.
        **docs_urls(),
    )

    # Authentication and in-process authorization. Configured by (see
    # core/settings.py and .env.example):
    # - CELINE_OIDC_BASE_URL, CELINE_OIDC_JWKS_URI, CELINE_OIDC_AUDIENCE: the
    #   issuer and keys every JWT is verified against (always verified)
    # - AUTH_ENABLED, AUTH_HEADER_NAME: optional user extraction on paths
    #   outside /admin and /user, which always require a JWT
    # - POLICIES_ENABLED, POLICIES_DIR, POLICIES_DATA_DIR, POLICIES_PACKAGE,
    #   POLICIES_CACHE_*: the Rego bundle evaluated in-process for /admin
    # Turning AUTH_ENABLED or POLICIES_ENABLED off is refused unless
    # CELINE_ENV=dev (REQ-0088).
    app.add_middleware(PolicyMiddleware)

    # Refusals a caller acts on answer {"detail", "code"} (REQ-0073).
    install_error_handlers(app)

    # uvicorn's access line prints the path, which carries asset keys
    # (`meter-<sensor_id>`), sensor, user and delivery-point ids: the line
    # keeps its shape, not the ids (REQ-0080).
    install_access_log_redaction()

    # Include routers
    app.include_router(user_router)
    app.include_router(meta_router)

    app.include_router(prefix="/admin", tags=["admin"], router=management_router)
    app.include_router(prefix="/admin", tags=["admin"], router=communities_router)
    app.include_router(prefix="/admin", tags=["admin"], router=lookup_router)
    app.include_router(prefix="/admin", tags=["admin"], router=writes_router)

    return app
