"""The one definition of a delivery point's compared form (REQ-0085, REQ-0086).

Every comparison of delivery-point ids — the writes' holder check, the SQL over
rows already stored (``services.delivery_points``) and the CLI's duplicates
report over an export — trims by ``core.sensor_id.WHITESPACE`` and lower-cases,
so a POD one side considers equal the others do too. Comparison only: the id is
stored as the caller spelled it. Like ``core.sensor_id``, this imports nothing
but the standard library and that module, so the CLI can use it.
"""

from __future__ import annotations

from typing import Any

from celine.rec_registry.core.sensor_id import WHITESPACE

__all__ = ["normalise_delivery_point_id"]


def normalise_delivery_point_id(value: Any) -> str | None:
    """Trimmed, lower-cased, ``None`` when blank or not a string."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip(WHITESPACE).lower()
    return trimmed or None
