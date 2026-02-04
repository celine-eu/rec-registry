from fastapi import Query
from typing import Literal, Any
from celine.rec_registry.api.render import jsonld

Format = Literal["json", "jsonld"]


def format_param(
    format: Format = Query(default="json", pattern="^(json|jsonld)$")
) -> Format:
    return format


def maybe_jsonld(fmt: Format, payload: dict[str, Any]) -> dict[str, Any]:
    return jsonld(payload) if fmt == "jsonld" else payload
