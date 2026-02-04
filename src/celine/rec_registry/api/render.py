from typing import Any
from celine.rec_registry.core.settings import settings


def jsonld(payload: dict[str, Any]) -> dict[str, Any]:
    return {"@context": settings.jsonld_context_url, **payload}
