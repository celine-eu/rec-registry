"""Refusals a caller acts on carry a machine-readable code (REQ-0073).

The body of such a refusal is ``{"detail": "<sentence>", "code": "<code>"}``.
``detail`` stays a string with its old meaning, so a client that reads only
``detail`` is unaffected; ``code`` sits beside it and is what a client branches
on — a dashboard translating "this meter is already attached" into three
languages, onboarding telling "that area is in use" from "that area does not
exist". Parsing the sentence would make its wording an API nobody knew they
were changing.

The codes are a **closed list**. One is added here by the requirement that
introduces its refusal, never ad hoc in a handler, and a code names the rule
broken — never the entity or the person: data belongs in ``detail``, under the
disclosure rule ``detail`` already follows (ADR-0008).

A refusal nobody has had to act on programmatically yet — FastAPI's own
validation errors, a body id that does not match the path — keeps the plain
``{"detail": ...}`` body.
"""

from __future__ import annotations

from enum import StrEnum

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class ErrorCode(StrEnum):
    """The closed vocabulary of REQ-0073. Renaming one is a breaking change."""

    COMMUNITY_NOT_FOUND = "community_not_found"
    MEMBER_NOT_FOUND = "member_not_found"
    ASSET_NOT_FOUND = "asset_not_found"
    MEMBER_KEY_TAKEN = "member_key_taken"
    USER_ID_TAKEN = "user_id_taken"
    DID_TAKEN = "did_taken"
    ASSET_KEY_TAKEN = "asset_key_taken"
    ASSET_KEY_TOO_LONG = "asset_key_too_long"
    SENSOR_HELD = "sensor_held"
    AREA_IN_USE = "area_in_use"
    INVALID_STATUS = "invalid_status"
    INVALID_ROLE = "invalid_role"
    UNKNOWN_AREA = "unknown_area"


class ErrorResponse(BaseModel):
    """The body of a refusal that carries a code."""

    detail: str = Field(
        description=(
            "A sentence for people. Its wording is not part of the API; "
            "branch on `code`."
        )
    )
    code: ErrorCode | None = Field(
        default=None,
        description=(
            "The rule the request broke, from a closed list (REQ-0073). Absent "
            "only on a refusal no requirement has given a code yet."
        ),
    )


class RegistryError(HTTPException):
    """An ``HTTPException`` whose body carries a code beside its detail.

    A subclass rather than a dict ``detail``, so that ``detail`` stays a string
    everywhere — including in an app that never installed the handler below,
    where this degrades to the plain body rather than to an object.
    """

    def __init__(self, status_code: int, detail: str, code: ErrorCode):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


async def _registry_error_handler(request: Request, exc: RegistryError) -> JSONResponse:
    return JSONResponse(
        {"detail": exc.detail, "code": str(exc.code)},
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


def install_error_handlers(app: FastAPI) -> None:
    """Render ``RegistryError`` as ``{"detail", "code"}`` in ``app``."""
    app.add_exception_handler(RegistryError, _registry_error_handler)


def error_responses(*statuses: int) -> dict[int | str, dict]:
    """OpenAPI ``responses`` documenting the coded body for these statuses.

    A ``422`` among them is documented as either body: the route's coded
    refusal (``ErrorResponse``) or FastAPI's own validation error
    (``HTTPValidationError``, whose ``detail`` is a list), since both arrive
    with that status and a generated client has to be able to read either.
    """
    responses: dict[int | str, dict] = {}
    for status in statuses:
        responses[status] = {
            "model": ErrorResponse,
            "description": "Refused; `code` names the rule (REQ-0073).",
        }
        if status == 422:
            # No `model` here: FastAPI would merge its `$ref` into the schema
            # beside the `oneOf`. Both components are registered by other
            # routes — `ErrorResponse` by every coded 404/409, and
            # `HTTPValidationError` by every route with a parameter that does
            # not declare its own 422; a test pins that both references resolve.
            responses[status] = {
                "description": (
                    "Refused. Either a coded refusal (`ErrorResponse`, `code` "
                    "names the rule, REQ-0073) or a request that failed "
                    "validation (`HTTPValidationError`, `detail` is a list)."
                ),
                "content": {
                    "application/json": {
                        "schema": {
                            "oneOf": [
                                {"$ref": "#/components/schemas/ErrorResponse"},
                                {"$ref": "#/components/schemas/HTTPValidationError"},
                            ]
                        }
                    }
                },
            }
    return responses
