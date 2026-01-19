from __future__ import annotations

from urllib.parse import urljoin


def api_base(request_base: str) -> str:
    # ensure trailing slash
    return request_base if request_base.endswith("/") else request_base + "/"


def community_iri(base: str, community_key: str) -> str:
    return urljoin(api_base(base), f"communities/{community_key}")


def entity_iri(base: str, community_key: str, collection: str, key: str) -> str:
    return urljoin(api_base(base), f"communities/{community_key}/{collection}/{key}")


def context_iri(base: str, version: str | None = "v1") -> str:
    return urljoin(api_base(base), f"contexts/celine/{version}")
