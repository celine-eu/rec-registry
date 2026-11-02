"""The one definition of a POD's keyed hash, the only form a POD leaves the registry in (REQ-0105).

``HMAC-SHA256(key, normalised id)``, both UTF-8, as 64 lowercase hex characters. The
id is normalised by removing every whitespace character (``str.split``'s definition,
which includes the non-breaking space) and upper-casing — a POD written ``it001e 0000…``
and ``IT001E0000…`` is one supply, and hashes as one.

This is *not* ``core.delivery_point_id``'s compared form (trimmed, lower-cased), on
purpose: that one compares ids inside the registry; this one is a contract with readers
outside it (the data pipelines hash distributor readings the same way), so it is pinned
by REQ-0105 and changes only with them.

Italian PODs are a small space (about 10^8 values): whoever holds the key can rebuild the
whole mapping. The key therefore never leaves the registry that holds it, and a key
change orphans every hash computed before it. Standard library only, so the CLI can use
it. Nothing here logs.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

__all__ = ["normalise_pod_for_hash", "pod_hmac"]


def normalise_pod_for_hash(value: Any) -> str | None:
    """Every whitespace character removed, upper-cased; ``None`` when blank or not a string."""
    if not isinstance(value, str):
        return None
    compact = "".join(value.split()).upper()
    return compact or None


def pod_hmac(key: str, pod_id: Any) -> str | None:
    """The POD's HMAC-SHA256 under ``key``, lowercase hex; ``None`` for a blank id."""
    normalised = normalise_pod_for_hash(pod_id)
    if normalised is None:
        return None
    return hmac.new(
        key.encode("utf-8"), normalised.encode("utf-8"), hashlib.sha256
    ).hexdigest()
