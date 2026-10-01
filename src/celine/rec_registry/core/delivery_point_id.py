"""The one definition of a delivery point's compared form (REQ-0085, REQ-0086).

Every comparison of delivery-point ids — the writes' holder check, the SQL over
rows already stored (``services.delivery_points``), and the duplicates report,
both the CLI's over an export (REQ-0086) and the per-community read (REQ-0087) — trims by ``core.sensor_id.WHITESPACE`` and lower-cases,
so a POD one side considers equal the others do too. Comparison only: the id is
stored as the caller spelled it. Like ``core.sensor_id``, this imports nothing
but the standard library and that module, so the CLI can use it.
"""

from __future__ import annotations

from typing import Any

from celine.rec_registry.core.sensor_id import WHITESPACE

__all__ = ["find_duplicate_delivery_points", "normalise_delivery_point_id"]


def normalise_delivery_point_id(value: Any) -> str | None:
    """Trimmed, lower-cased, ``None`` when blank or not a string."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip(WHITESPACE).lower()
    return trimmed or None


def find_duplicate_delivery_points(
    bundles: list[dict[str, Any]],
) -> list[tuple[str, list[tuple[str, str]]]]:
    """Every delivery point held by more than one active member (REQ-0086).

    Reads exported bundles, as `GET /admin/export` answers them, and returns
    ``(delivery point, [(community key, member key), …])`` sorted by point.
    Only an ``active`` member holds a point (REQ-0085), and ids are compared
    trimmed and lower-cased — by ``normalise_delivery_point_id``, the
    registry's own definition — so ` IT001E…`, `it001e…` and `IT001E…` are one,
    reported in that compared form. A member listing one point twice is one
    holder, not two.
    """
    holders: dict[str, set[tuple[str, str]]] = {}
    for bundle in bundles:
        if not isinstance(bundle, dict):
            continue
        community_key = str((bundle.get("community") or {}).get("id", ""))
        for member_key, member in (bundle.get("members") or {}).items():
            if not isinstance(member, dict) or member.get("status") != "active":
                continue
            for point in member.get("delivery_points") or []:
                if not isinstance(point, dict):
                    continue
                point_id = normalise_delivery_point_id(point.get("id"))
                if point_id:
                    holders.setdefault(point_id, set()).add(
                        (community_key, str(member_key))
                    )
    return [
        (point_id, sorted(held_by))
        for point_id, held_by in sorted(holders.items())
        if len(held_by) > 1
    ]
