"""One active holder per sensor id, across the whole registry (REQ-0069).

A sensor id is how a reading finds its owner (REQ-0039). Two members holding one
would double-count every reading of it in every consumer that joins readings to
members, and nothing downstream can tell — so the registry refuses the write
that would make a second one, on every path that can: the asset ``PUT``,
creating a member with assets, a status change to ``active``, and the bundle
import (ADR-0004).

The rules, in one place because each is easy to lose:

* **Only an ``active`` member holds a sensor.** Deactivating one releases its
  sensors; reactivating one re-checks them.
* **The comparison is on the trimmed id**, and new writes store it trimmed. An
  id that is blank after trimming is missing (REQ-0035). "Trimmed" has one
  definition, ``core.sensor_id.WHITESPACE``, used by Python and by the SQL
  that compares rows already stored (``trimmed_sql``) alike — so a legacy row
  stored with a tab, newline or no-break space around the id still counts.
* **A write that can make a member hold a sensor locks that member's row
  first** (``lock_member``): an attach, and a move to ``active``. An attach to
  a member who is not active is not checked, and a reactivation checks the
  member's sensors — without the row lock, the two running at once would each
  miss the other's uncommitted half and leave two active holders. Member row
  before advisory locks, always, so no two writers wait on each other in a
  cycle.
* **Check and write run under one transaction-scoped advisory lock keyed on the
  trimmed id.** Neither of two writers attaching one sensor at once can see the
  other's uncommitted row, and no unique index can express "among active
  members", so the lock is what serialises them. Several ids are locked in
  sorted order, so two writers never wait on each other in a cycle.
* **The refusal names nobody outside the addressed community.** A holder inside
  it may be named by member key, as the DID clash names its holder (REQ-0060);
  a holder elsewhere is not named, and neither is its community (REQ-0045).

Nothing here logs a sensor id.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from celine.rec_registry.core.sensor_id import WHITESPACE, normalise_sensor_id
from celine.rec_registry.db.models import Asset, Community, Member

__all__ = [
    "ACTIVE",
    "Holding",
    "SensorHeld",
    "active_holders",
    "ensure_sensors_free",
    "held_message",
    "lock_member",
    "lock_sensors",
    "member_sensor_ids",
    "normalise_sensor_id",
    "trimmed_sql",
]

ACTIVE = "active"

# The first key of the two-key advisory lock, so these locks cannot collide with
# any other advisory lock taken on the same database. The value is arbitrary;
# it only has to be this module's alone.
_LOCK_NAMESPACE = 0x5E45_0001


class SensorHeld(Exception):
    """Another active member holds this sensor. Answered as ``409 sensor_held``."""


@dataclass(frozen=True)
class Holding:
    """One active member holding one (trimmed) sensor id."""

    sensor_id: str
    community_id: uuid.UUID
    member_id: uuid.UUID
    member_key: str
    asset_key: str


def trimmed_sql(column):
    """``column`` trimmed in SQL exactly as ``normalise_sensor_id`` trims it.

    ``btrim`` with an explicit character set: its one-argument form strips only
    the ASCII space, which is not what Python strips.
    """
    return func.btrim(column, WHITESPACE)


async def lock_member(session: AsyncSession, member: Member) -> None:
    """``SELECT … FOR UPDATE`` the member's row and refresh ``member`` from it.

    Serialises every write that can make this member hold a sensor — an attach
    and a reactivation — so each sees the other's committed result: the status
    and the sensor ids read after this call are current, and stay so until the
    caller's transaction ends.
    """
    await session.execute(
        select(Member)
        .where(Member.id == member.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def lock_sensors(session: AsyncSession, sensor_ids: Iterable[str]) -> None:
    """Take the transaction-scoped advisory lock of each id, in sorted order.

    Released by the commit or rollback that ends the caller's transaction, so
    the check that follows and the write after it happen under it.
    """
    for sensor_id in sorted(set(sensor_ids)):
        await session.execute(
            text("select pg_advisory_xact_lock(:ns, hashtext(:sensor_id))"),
            {"ns": _LOCK_NAMESPACE, "sensor_id": sensor_id},
        )


async def active_holders(
    session: AsyncSession,
    sensor_ids: Iterable[str],
    *,
    exclude_member_id: uuid.UUID | None = None,
    exclude_community_key: str | None = None,
) -> list[Holding]:
    """Every active member holding one of these trimmed ids, anywhere."""
    wanted = sorted(set(sensor_ids))
    if not wanted:
        return []

    trimmed = trimmed_sql(Asset.sensor_id)
    query = (
        select(trimmed, Asset.community_id, Member.id, Member.key, Asset.key)
        .join(Member, Member.id == Asset.owner_id)
        .where(Asset.sensor_id.isnot(None), trimmed.in_(wanted), Member.status == ACTIVE)
    )
    if exclude_member_id is not None:
        query = query.where(Member.id != exclude_member_id)
    if exclude_community_key is not None:
        query = query.join(Community, Community.id == Asset.community_id).where(
            Community.key != exclude_community_key
        )

    rows = (await session.execute(query)).all()
    return [
        Holding(
            sensor_id=row[0],
            community_id=row[1],
            member_id=row[2],
            member_key=row[3],
            asset_key=row[4],
        )
        for row in rows
    ]


def held_message(holding: Holding, community_id: uuid.UUID) -> str:
    """The refusal's sentence, naming the holder only inside the community."""
    if holding.community_id == community_id:
        return (
            f"This sensor is already held by member {holding.member_key!r}; "
            "detach it there first"
        )
    return "This sensor is already held by another active member"


async def ensure_sensors_free(
    session: AsyncSession,
    *,
    community_id: uuid.UUID,
    member_id: uuid.UUID | None,
    sensor_ids: Iterable[str],
) -> None:
    """Lock these ids and refuse if another active member holds any of them.

    ``member_id`` is the member about to hold them — ``None`` for one not
    created yet. Its own holdings are not a clash: attaching a sensor a member
    already holds is the idempotent replace of REQ-0028.

    Must be called inside the transaction that then performs the write.
    """
    wanted = sorted({s for s in sensor_ids if s})
    if not wanted:
        return
    await lock_sensors(session, wanted)
    holders = await active_holders(session, wanted, exclude_member_id=member_id)
    if holders:
        # Prefer a holder the caller may be told about.
        holders.sort(key=lambda h: h.community_id != community_id)
        raise SensorHeld(held_message(holders[0], community_id))


async def member_sensor_ids(session: AsyncSession, member_id: uuid.UUID) -> list[str]:
    """The trimmed sensor ids of every meter a member holds.

    Read after ``lock_member`` when it decides a reactivation, so an attach
    committed meanwhile is among them.
    """
    rows = await session.scalars(
        select(Asset.sensor_id).where(
            Asset.owner_id == member_id, Asset.sensor_id.isnot(None)
        )
    )
    return sorted({s for s in (normalise_sensor_id(v) for v in rows) if s})
