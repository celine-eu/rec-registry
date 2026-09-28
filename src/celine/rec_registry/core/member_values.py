"""A member's role and status are closed sets, and its area is one of its community's (REQ-0066).

The sets are the ones the published JSON Schemas (v0.4–v0.7) and the platform
ontology (``celine:MemberRole``, ``celine:MemberStatus``) already declare;
``tests/test_member_values.py`` holds them to the schema in the repository.

Every path that writes a member asks ``member_value_refusals`` — creating one,
both ``PATCH`` routes, the status route and the bundle import — so the answer is
the same whichever way a member arrives (``the-two-write-paths``). The models
keep the fields as plain ``str`` on purpose: a pydantic ``Literal`` would refuse
with FastAPI's list-shaped ``422`` and no ``code``, and a caller could not tell
a wrong role from a malformed body (REQ-0073).

The CLI's ``out-of-set-values`` report (REQ-0077) reads the same sets, so the
report and the check cannot disagree about what is out of set.

A refusal names the offending value and the valid ones: role, status and area
keys are registry vocabulary, never personal data.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from celine.rec_registry.core.errors import ErrorCode

MEMBER_ROLES: tuple[str, ...] = ("consumer", "prosumer", "producer", "operator", "admin")
MEMBER_STATUSES: tuple[str, ...] = ("pending", "active", "suspended", "inactive")

_UNSET = object()


@dataclass(frozen=True)
class OutOfSet:
    """One field of one member holding a value outside its set."""

    field: str
    value: object
    code: ErrorCode
    detail: str


def _one_of(values: Iterable[str]) -> str:
    return ", ".join(values) or "(none)"


def member_value_refusals(
    *,
    role: object = _UNSET,
    status: object = _UNSET,
    area: object = _UNSET,
    areas: Iterable[str] | None = None,
) -> list[OutOfSet]:
    """Every out-of-set value among the fields given, in field order.

    A field not passed is not checked — a patch checks only what it names.
    ``area`` is checked against ``areas``, the keys of the community's areas;
    a community with no areas has no valid area.
    """
    found: list[OutOfSet] = []
    if role is not _UNSET and role not in MEMBER_ROLES:
        found.append(
            OutOfSet(
                "role",
                role,
                ErrorCode.INVALID_ROLE,
                f"role {role!r} is not one of {_one_of(MEMBER_ROLES)}",
            )
        )
    if status is not _UNSET and status not in MEMBER_STATUSES:
        found.append(
            OutOfSet(
                "status",
                status,
                ErrorCode.INVALID_STATUS,
                f"status {status!r} is not one of {_one_of(MEMBER_STATUSES)}",
            )
        )
    if area is not _UNSET:
        keys = sorted(areas or ())
        if area not in keys:
            found.append(
                OutOfSet(
                    "area",
                    area,
                    ErrorCode.UNKNOWN_AREA,
                    f"area {area!r} is not one of this community's areas: "
                    f"{_one_of(keys)}",
                )
            )
    return found
