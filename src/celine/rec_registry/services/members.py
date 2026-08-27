"""Member and asset writes, shared by the bundle importer and the admin API.

Both paths build the same rows, so they build them here. Two implementations of
"what a member row looks like" would drift on the first schema change, and the
symptom would be a community that exports differently depending on how its
members arrived — which is exactly the property `test_round_trip` pins.

The rules these functions keep, in one place because they are easy to lose:

* **A write never reduces a sibling.** Replacing a member replaces that member,
  not the member list. There is no collection-level replace outside the bundle
  importer, which announces itself.
* **Removing somebody is not the same as deactivating them.** ``Asset`` cascades
  on member delete, so a real delete silently takes the meters with it. The
  default is ``status = inactive``.
* **JSONB collections merge by identity, not by position.** A member gaining a
  second supply point must not lose the first.
* **The application check produces the message; the database makes it true.**
  ``member`` carries unique indexes on ``(community_id, key)`` and
  ``(community_id, user_id)``, so two writers whose pre-checks both pass — neither
  can see the other's uncommitted row — do not both insert. The loser's
  ``IntegrityError`` is translated back into the same ``MemberConflict`` the check
  raises, so a race and an observed duplicate are indistinguishable to a caller.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from celine.rec_registry.db.models import Asset, Community, Member
from celine.rec_registry.schemas.bundle import (
    AssetCollectionIn,
    DeliveryPointIn,
    MemberIn,
)

# Reused rather than reimplemented: the importer already knows how to flatten a
# bundle asset into a row, and an asset created through the API must be
# indistinguishable from one that arrived in a bundle.
from celine.rec_registry.services.importer import (
    _create_assets,
    _extract_device,
    _extract_extra,
    _extract_properties,
    _extract_relationships,
)

__all__ = [
    "MemberConflict",
    "MemberNotFound",
    "apply_member_patch",
    "build_delivery_points",
    "build_member_extra",
    "create_assets_for_member",
    "create_member",
    "member_conflict_from",
    "merge_delivery_point",
    "next_member_key",
    "remove_delivery_point",
    "resolve_community",
    "resolve_member",
]

# Fields the model stores in columns; anything else on a MemberIn lands in `extra`.
_MEMBER_COLUMNS = {
    "user_id",
    "name",
    "type",
    "role",
    "area",
    "status",
    "delivery_points",
    "assets",
}

_NUMBERED_KEY = re.compile(r"^(?P<prefix>.+?)-(?P<digits>\d+)$")

_DEFAULT_KEY_PREFIX = "member"
_DEFAULT_KEY_WIDTH = 5


class MemberConflict(Exception):
    """A member with this key or user_id already exists in the community."""


class MemberNotFound(Exception):
    """No such member in this community."""


# The unique indexes behind the two application-level checks. Named rather than
# matched loosely, so an unrelated constraint failure is not reported as
# "already exists" — a misleading 409 is worse than a 500 that claims nothing.
_MEMBER_KEY_CONSTRAINT = "uq_member_community_key"
_MEMBER_USER_ID_CONSTRAINT = "uq_member_community_user_id"


def member_conflict_from(
    exc: IntegrityError, *, key: str | None = None, user_id: str | None = None
) -> MemberConflict | None:
    """Translate a member unique-violation into the conflict the checks raise.

    The pre-checks in `create_member` and `patch_member` cannot see an
    uncommitted row, so two concurrent writers both pass them and the database
    refuses the second. Without this the caller gets a `500` for something the
    API already has a `409` for.

    Returns ``None`` when the violation is not one of the two member unique
    indexes; the caller re-raises rather than guessing.
    """
    detail = str(getattr(exc, "orig", exc))

    if _MEMBER_KEY_CONSTRAINT in detail:
        return MemberConflict(f"Member {key!r} already exists in this community")
    if _MEMBER_USER_ID_CONSTRAINT in detail:
        return MemberConflict(
            f"A member with user_id {user_id!r} already exists in this community"
        )
    return None


# ── lookups ───────────────────────────────────────────────────────────────────


async def resolve_community(session: AsyncSession, community_key: str) -> Community:
    community = await session.scalar(
        select(Community).where(Community.key == community_key)
    )
    if community is None:
        raise MemberNotFound(f"Community {community_key!r} not found")
    return community


async def resolve_member(
    session: AsyncSession, community: Community, member_key: str
) -> Member:
    member = await session.scalar(
        select(Member).where(
            Member.community_id == community.id, Member.key == member_key
        )
    )
    if member is None:
        raise MemberNotFound(f"Member {member_key!r} not found")
    return member


# ── key minting ───────────────────────────────────────────────────────────────


def next_member_key(existing: Sequence[str]) -> str:
    """Mint the next member key, following whatever pattern the community uses.

    Communities number their members (``gl-00001``), and a caller that has no
    opinion should get the next one in that series rather than a UUID that reads
    as foreign in an exported bundle. The prefix and zero-padding are taken from
    the highest-numbered existing key; a community with none starts at
    ``member-00001``.
    """
    prefix = _DEFAULT_KEY_PREFIX
    width = _DEFAULT_KEY_WIDTH
    highest = 0

    for key in existing:
        match = _NUMBERED_KEY.fullmatch(key)
        if match is None:
            continue
        number = int(match.group("digits"))
        if number >= highest:
            highest = number
            prefix = match.group("prefix")
            width = len(match.group("digits"))

    return f"{prefix}-{highest + 1:0{width}d}"


# ── field building, shared with the importer ──────────────────────────────────


def build_delivery_points(points: Iterable[DeliveryPointIn]) -> list[dict[str, Any]]:
    """Flatten delivery points to the JSONB shape the model stores."""
    result: list[dict[str, Any]] = []
    for point in points:
        entry: dict[str, Any] = {"id": point.id, "type": point.type}
        if point.description:
            entry["description"] = point.description
        if point.address:
            entry["address"] = point.address
        if point.tariff:
            entry["tariff"] = point.tariff
        entry["active"] = point.active
        result.append(entry)
    return result


def build_member_extra(member_in: MemberIn) -> dict[str, Any]:
    """Everything on a member that is not a column, including its schema.org type."""
    return {
        **({"type": member_in.type} if member_in.type else {}),
        **_extract_extra(member_in, _MEMBER_COLUMNS),
    }


def merge_delivery_point(
    existing: Sequence[dict[str, Any]], point: DeliveryPointIn
) -> list[dict[str, Any]]:
    """Add or replace one delivery point, keeping the others.

    Identity is the point id, not the list position: a member gaining a second
    supply point must not lose the first, and re-sending one must update it
    rather than duplicate it.
    """
    incoming = build_delivery_points([point])[0]
    merged = [dict(dp) for dp in existing if dp.get("id") != point.id]
    merged.append(incoming)
    return merged


def remove_delivery_point(
    existing: Sequence[dict[str, Any]], point_id: str
) -> list[dict[str, Any]]:
    return [dict(dp) for dp in existing if dp.get("id") != point_id]


# ── writes ────────────────────────────────────────────────────────────────────


async def create_member(
    session: AsyncSession,
    community: Community,
    member_in: MemberIn,
    *,
    key: str | None = None,
) -> tuple[Member, list[str]]:
    """Create one member and its assets. Returns the member and any warnings.

    Refuses a duplicate ``key`` or ``user_id`` rather than overwriting: the
    caller asked to create, and silently updating somebody else's row is how a
    retry with a changed payload rewrites the wrong person.

    Raises ``MemberConflict`` whether the duplicate was seen by the check below
    or refused by the unique index underneath it.
    """
    existing = (
        await session.scalars(select(Member).where(Member.community_id == community.id))
    ).all()

    if key is None:
        key = next_member_key([m.key for m in existing])
    elif any(m.key == key for m in existing):
        raise MemberConflict(f"Member {key!r} already exists in this community")

    if any(m.user_id == member_in.user_id for m in existing):
        raise MemberConflict(
            f"A member with user_id {member_in.user_id!r} already exists in this "
            "community"
        )

    member = Member(
        community_id=community.id,
        key=key,
        user_id=member_in.user_id,
        name=member_in.name,
        role=member_in.role,
        area=member_in.area,
        status=member_in.status,
        delivery_points=build_delivery_points(member_in.delivery_points),
        extra=build_member_extra(member_in),
    )
    session.add(member)
    try:
        await session.flush()
    except IntegrityError as exc:
        # A writer got here first between the check above and this insert. The
        # transaction is dead either way, and this function has one caller, which
        # answers 409 and does nothing else with the session.
        await session.rollback()
        conflict = member_conflict_from(exc, key=key, user_id=member_in.user_id)
        if conflict is None:
            raise
        raise conflict from exc

    warnings: list[str] = []
    if member_in.assets:
        warnings = await create_assets_for_member(
            session, community_id=community.id, owner_id=member.id, assets=member_in.assets
        )
        await session.flush()

    return member, warnings


async def apply_member_patch(
    member: Member, patch: dict[str, Any]
) -> Member:
    """Apply a partial update. Absent keys are left alone, not cleared.

    ``delivery_points`` is deliberately **not** patchable here — it is a JSONB
    list, and a partial update that happens to omit it would otherwise read as
    "this member now has none". It has its own sub-resource.
    """
    for field in ("name", "role", "area", "status", "user_id"):
        if field in patch and patch[field] is not None:
            setattr(member, field, patch[field])

    if "type" in patch and patch["type"] is not None:
        member.extra = {**(member.extra or {}), "type": patch["type"]}

    if "extra" in patch and patch["extra"] is not None:
        # Merge rather than replace: `extra` accumulates fields from several
        # sources, and a caller that knows about one should not erase the rest.
        member.extra = {**(member.extra or {}), **patch["extra"]}

    return member


async def create_assets_for_member(
    session: AsyncSession,
    *,
    community_id,
    owner_id,
    assets: AssetCollectionIn,
) -> list[str]:
    """Create assets for a member, exactly as a bundle import would."""
    return await _create_assets(
        session, community_id=community_id, owner_id=owner_id, assets=assets
    )


async def upsert_asset(
    session: AsyncSession,
    *,
    community: Community,
    member: Member,
    asset_key: str,
    asset_type: str,
    payload: Any,
) -> Asset:
    """Create or replace one asset of a member, leaving its siblings alone."""
    existing = await session.scalar(
        select(Asset).where(
            Asset.community_id == community.id,
            Asset.owner_id == member.id,
            Asset.key == asset_key,
        )
    )

    base_exclude = {"name", "relationships", "device"}
    sensor_id = getattr(payload, "sensor_id", None)
    exclude = base_exclude | ({"sensor_id"} if sensor_id is not None else set())

    fields = dict(
        asset_type=asset_type,
        name=payload.name,
        sensor_id=sensor_id,
        properties=_extract_properties(payload, exclude),
        device=_extract_device(payload),
        relationships=_extract_relationships(payload),
    )

    if existing is None:
        existing = Asset(
            community_id=community.id, owner_id=member.id, key=asset_key, **fields
        )
        session.add(existing)
    else:
        for name, value in fields.items():
            setattr(existing, name, value)

    await session.flush()
    return existing
