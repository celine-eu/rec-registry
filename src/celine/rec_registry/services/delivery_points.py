"""One active holder per delivery point, across the whole registry (REQ-0085).

A delivery point (a POD) is how a member's consent and settlement find their
supply. Two active members holding one is, in practice, a mistyped POD that
happens to be somebody else's — and every consumer joining supply to members
would then attribute one supply point to two people. So the registry refuses
the write that would make a second holder, on every path that can: the
delivery-point ``PUT`` (with or without ``replaces``), creating a member with
delivery points, a status change to ``active``, and the bundle import
(ADR-0012). It is the rule ``services/sensors.py`` keeps for sensor ids, kept
the same way:

* **Only an ``active`` member holds a delivery point.** Deactivating one
  releases its points; reactivating one re-checks them. A point's own
  ``active`` flag is not read: an active member holds every point it lists.
* **The comparison is on the trimmed, lower-cased id.** Trimmed by
  ``core.sensor_id.WHITESPACE`` in Python and in SQL alike, lower-cased by
  ``str.lower`` and Postgres ``lower`` — which agree on the ASCII a POD is
  written in. The id is stored as the caller spelled it; only the comparison
  normalises.
* **A write that can make a member hold a point locks that member's row
  first** (``sensors.lock_member``), then one transaction-scoped advisory lock
  per normalised id, in sorted order, after any sensor locks the same write
  takes. Community row, member rows, sensor locks, delivery-point locks: the
  order every write takes them in, so no two writers wait in a cycle.
* **The refusal names nobody outside the addressed community** (REQ-0045,
  REQ-0060): a holder inside it may be named by member key, a holder
  elsewhere is not named, and neither is its community.

**A meter's ``pod`` is a holding too** (REQ-0093). A meter names the supply
it reads in ``properties.pod``; it may name one of its owner's own delivery
points, or a POD no other active member holds — through its delivery points or
through a meter of its own. So the holders this module compares are every
active member listing the id as a delivery point *or* owning a meter whose
``pod`` is the id, and the same ``delivery_point_held`` refusal guards a meter
attach as it guards a delivery point.

Nothing here logs a delivery-point id.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from celine.rec_registry.core.delivery_point_id import (
    find_duplicate_delivery_points,
    normalise_delivery_point_id,
)
from celine.rec_registry.core.sensor_id import WHITESPACE

__all__ = [
    "CommunityDuplicate",
    "DeliveryPointHeld",
    "DeliveryPointHolding",
    "active_delivery_point_holders",
    "community_duplicates",
    "delivery_point_held_message",
    "ensure_delivery_points_free",
    "lock_delivery_points",
    "member_delivery_point_ids",
    "member_meter_pod_ids",
    "normalise_delivery_point_id",
]

ACTIVE = "active"

# The first key of the two-key advisory lock: this module's alone, distinct from
# the sensor locks' (`sensors._LOCK_NAMESPACE`), so a POD and a sensor id that
# happen to hash alike never wait on each other.
_LOCK_NAMESPACE = 0x5E45_0002


class DeliveryPointHeld(Exception):
    """Another active member holds this delivery point.

    Answered as ``409 delivery_point_held`` (``422`` on an import, where the
    bundle is what is wrong).
    """


@dataclass(frozen=True)
class DeliveryPointHolding:
    """One active member holding one (normalised) delivery-point id."""

    point_id: str
    community_id: uuid.UUID
    member_id: uuid.UUID
    member_key: str


def member_delivery_point_ids(points: Sequence[dict[str, Any]] | None) -> list[str]:
    """The normalised ids of a stored ``delivery_points`` list, sorted, distinct."""
    return sorted(
        {
            p
            for p in (normalise_delivery_point_id(dp.get("id")) for dp in points or [])
            if p
        }
    )


async def member_meter_pod_ids(
    session: AsyncSession, member_id: uuid.UUID
) -> list[str]:
    """The normalised ``pod`` of each of this member's meters, sorted, distinct."""
    rows = (
        await session.execute(
            text(
                "select properties ->> 'pod' as pod from asset "
                "where owner_id = cast(:member_id as uuid) and asset_type = 'meter'"
            ),
            {"member_id": str(member_id)},
        )
    ).all()
    return sorted({p for p in (normalise_delivery_point_id(r.pod) for r in rows) if p})


async def lock_delivery_points(session: AsyncSession, point_ids: Iterable[str]) -> None:
    """Take the transaction-scoped advisory lock of each normalised id, sorted.

    Released by the commit or rollback that ends the caller's transaction.
    """
    for point_id in sorted(set(point_ids)):
        await session.execute(
            text("select pg_advisory_xact_lock(:ns, hashtext(:point_id))"),
            {"ns": _LOCK_NAMESPACE, "point_id": point_id},
        )


# Every active member's holdings, one row per member and id, compared on the
# normalised id: its delivery points (REQ-0085) and its meters' `pod`
# (REQ-0093). `jsonb_typeof` guards a row whose column is not a list, which no
# write produces but a hand-edited row could hold.
_HOLDERS_SQL = text(
    """
    select distinct h.point_id, m.community_id, m.id as member_id,
           m.key as member_key
      from (
            select dm.id as member_id,
                   lower(btrim(dp.value ->> 'id', cast(:ws as text))) as point_id
              from member dm
             cross join lateral jsonb_array_elements(
                   case when jsonb_typeof(dm.delivery_points) = 'array'
                        then dm.delivery_points else '[]'::jsonb end) as dp(value)
            union all
            select a.owner_id as member_id,
                   lower(btrim(a.properties ->> 'pod', cast(:ws as text))) as point_id
              from asset a
             where a.asset_type = 'meter'
           ) as h
      join member m on m.id = h.member_id
      join community c on c.id = m.community_id
     where m.status = :active
       and h.point_id in :wanted
       and (cast(:exclude_member_id as uuid) is null
            or m.id <> cast(:exclude_member_id as uuid))
       and (cast(:exclude_community_key as text) is null
            or c.key <> cast(:exclude_community_key as text))
    """
).bindparams(bindparam("wanted", expanding=True))


async def active_delivery_point_holders(
    session: AsyncSession,
    point_ids: Iterable[str],
    *,
    exclude_member_id: uuid.UUID | None = None,
    exclude_community_key: str | None = None,
) -> list[DeliveryPointHolding]:
    """Every active member holding one of these normalised ids, anywhere —
    as a delivery point or as a meter's ``pod``."""
    wanted = sorted(set(point_ids))
    if not wanted:
        return []
    rows = (
        await session.execute(
            _HOLDERS_SQL,
            {
                "ws": WHITESPACE,
                "active": ACTIVE,
                "wanted": wanted,
                "exclude_member_id": (
                    str(exclude_member_id) if exclude_member_id is not None else None
                ),
                "exclude_community_key": exclude_community_key,
            },
        )
    ).all()
    return [
        DeliveryPointHolding(
            point_id=row.point_id,
            community_id=row.community_id,
            member_id=row.member_id,
            member_key=row.member_key,
        )
        for row in rows
    ]


def delivery_point_held_message(
    holding: DeliveryPointHolding, community_id: uuid.UUID
) -> str:
    """The refusal's sentence, naming the holder only inside the community."""
    if holding.community_id == community_id:
        return (
            f"This delivery point is already held by member {holding.member_key!r}; "
            "check it with the member"
        )
    return "This delivery point is already held by another active member"


async def ensure_delivery_points_free(
    session: AsyncSession,
    *,
    community_id: uuid.UUID,
    member_id: uuid.UUID | None,
    point_ids: Iterable[str | None],
) -> None:
    """Lock these normalised ids and refuse if another active member holds one.

    ``member_id`` is the member about to hold them — ``None`` for one not
    created yet. Its own holdings are not a clash. Must be called inside the
    transaction that then performs the write, after the member row lock and
    any sensor locks.
    """
    wanted = sorted({p for p in point_ids if p})
    if not wanted:
        return
    await lock_delivery_points(session, wanted)
    holders = await active_delivery_point_holders(
        session, wanted, exclude_member_id=member_id
    )
    if holders:
        # Prefer a holder the caller may be told about.
        holders.sort(key=lambda h: h.community_id != community_id)
        raise DeliveryPointHeld(delivery_point_held_message(holders[0], community_id))


# Every active member's delivery points, anywhere, whose compared id is also
# held by an active member of the addressed community: one statement, the
# community's own holders among the rows (REQ-0087).
_SHARED_WITH_COMMUNITY_SQL = text(
    """
    with dp as (
        select c.key as community_key, m.key as member_key, m.community_id,
               d.value ->> 'id' as stored_id,
               lower(btrim(d.value ->> 'id', cast(:ws as text))) as point_id
          from member m
          join community c on c.id = m.community_id
         cross join lateral jsonb_array_elements(
               case when jsonb_typeof(m.delivery_points) = 'array'
                    then m.delivery_points else '[]'::jsonb end) as d(value)
         where m.status = :active
    )
    select community_key, member_key, community_id, stored_id
      from dp
     where point_id in (
           select point_id from dp where community_id = cast(:community_id as uuid)
     )
    """
)


@dataclass(frozen=True)
class CommunityDuplicate:
    """One delivery point an active member of the community shares (REQ-0087)."""

    point_id: str
    #: ``(member key, stored id)`` of each active holder in the community.
    holders: list[tuple[str, str]]
    #: How many active members of *other* communities hold it; never who.
    held_elsewhere: int


async def community_duplicates(
    session: AsyncSession, community_id: uuid.UUID, community_key: str
) -> list[CommunityDuplicate]:
    """The delivery points of this community held by more than one active member.

    One query (``_SHARED_WITH_COMMUNITY_SQL``) fetches every active holder of
    every point the community's active members hold; which of them is a
    duplicate is decided by ``find_duplicate_delivery_points`` — the CLI's own
    finder (REQ-0086), fed the rows in the export's shape — so the two cannot
    disagree. Holders outside the community are counted, never named.
    """
    rows = (
        await session.execute(
            _SHARED_WITH_COMMUNITY_SQL,
            {"ws": WHITESPACE, "active": ACTIVE, "community_id": str(community_id)},
        )
    ).all()

    # The rows, in the shape `GET /admin/export` answers, one bundle per community.
    bundles: dict[str, dict[str, Any]] = {}
    stored: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        members = bundles.setdefault(
            row.community_key, {"community": {"id": row.community_key}, "members": {}}
        )["members"]
        member = members.setdefault(
            row.member_key, {"status": ACTIVE, "delivery_points": []}
        )
        member["delivery_points"].append({"id": row.stored_id})
        if row.community_id == community_id:
            point_id = normalise_delivery_point_id(row.stored_id)
            if point_id:
                stored.setdefault((point_id, row.member_key), set()).add(row.stored_id)

    result: list[CommunityDuplicate] = []
    for point_id, held_by in find_duplicate_delivery_points(list(bundles.values())):
        here = [m for c, m in held_by if c == community_key]
        if not here:
            continue
        result.append(
            CommunityDuplicate(
                point_id=point_id,
                holders=[
                    (member_key, stored_id)
                    for member_key in here
                    for stored_id in sorted(stored.get((point_id, member_key), ()))
                ],
                held_elsewhere=len(held_by) - len(here),
            )
        )
    return result
