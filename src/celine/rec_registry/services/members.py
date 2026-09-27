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
  ``member`` carries unique indexes on ``(community_id, key)``,
  ``(community_id, user_id)`` and — globally — ``did``, so two writers whose
  pre-checks both pass — neither can see the other's uncommitted row — do not
  both insert. The loser's ``IntegrityError`` is translated back into the same
  ``MemberConflict`` the check raises, so a race and an observed duplicate are
  indistinguishable to a caller.

  The DID index is the one that is **not** scoped to a community, so it is the
  one most exposed to a race — and losing that race means disclosing one
  person's supply points under another person's consent.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from celine.rec_registry.core.errors import ErrorCode
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
    ASSET_KEY_MAX_LENGTH,
    too_long_asset_keys,
    _create_assets,
    _extract_device,
    _extract_extra,
    _extract_properties,
    _extract_relationships,
)
from celine.rec_registry.services.sensors import (
    ACTIVE,
    SensorHeld,
    ensure_sensors_free,
    lock_member,
    member_sensor_ids,
    normalise_sensor_id,
)

__all__ = [
    "AssetKeyTaken",
    "AssetKeyTooLong",
    "CommunityNotFound",
    "MemberConflict",
    "MemberNotFound",
    "SensorHeld",
    "apply_member_patch",
    "build_delivery_points",
    "build_member_extra",
    "create_assets_for_member",
    "create_member",
    "ensure_reactivation_allowed",
    "member_conflict_from",
    "merge_delivery_point",
    "next_member_key",
    "remove_delivery_point",
    "lock_community",
    "resolve_community",
    "resolve_member",
]

# Fields the model stores in columns; anything else on a MemberIn lands in `extra`.
_MEMBER_COLUMNS = {
    "user_id",
    # A column, so it must be named here or `build_member_extra` puts it in
    # `extra` instead — `MemberIn` is `extra="allow"`, so a bundle carrying a
    # `did` would validate, import, and leave one member holding two records of
    # its DID that disagree.
    "did",
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
    """This member's key, user_id or DID is already taken.

    The first two clash within the community; the DID clashes anywhere in the
    registry. ``code`` says which (REQ-0073).
    """

    def __init__(self, message: str, code: ErrorCode):
        super().__init__(message)
        self.code = code


class MemberNotFound(Exception):
    """No such member in this community."""

    code = ErrorCode.MEMBER_NOT_FOUND


class CommunityNotFound(MemberNotFound):
    """No such community. A ``MemberNotFound`` so existing handlers still catch it."""

    code = ErrorCode.COMMUNITY_NOT_FOUND


class AssetKeyTaken(Exception):
    """This asset key already belongs to another member of the community."""


class AssetKeyTooLong(Exception):
    """An asset key longer than the column holds (REQ-0028).

    Refused before anything is written: the insert would fail on the column's
    length and answer a `500` that tells the caller nothing. With the meter
    convention ``meter-<sensor id>`` (REQ-0071) a long sensor id reaches this.
    """

    def __init__(self, asset_key: str):
        super().__init__(
            f"Asset key is {len(asset_key)} characters; at most "
            f"{ASSET_KEY_MAX_LENGTH} are allowed"
        )


# The unique indexes behind the two application-level checks. Named rather than
# matched loosely, so an unrelated constraint failure is not reported as
# "already exists" — a misleading 409 is worse than a 500 that claims nothing.
_MEMBER_KEY_CONSTRAINT = "uq_member_community_key"
_MEMBER_USER_ID_CONSTRAINT = "uq_member_community_user_id"
_MEMBER_DID_CONSTRAINT = "ix_member_did"
_ASSET_KEY_CONSTRAINT = "uq_asset_community_key"


def member_conflict_from(
    exc: IntegrityError,
    *,
    key: str | None = None,
    user_id: str | None = None,
    did: str | None = None,
) -> MemberConflict | None:
    """Translate a member unique-violation into the conflict the checks raise.

    The pre-checks in `create_member` and `patch_member` cannot see an
    uncommitted row, so two concurrent writers both pass them and the database
    refuses the second. Without this the caller gets a `500` for something the
    API already has a `409` for.

    Returns ``None`` when the violation is not one of the three member unique
    indexes; the caller re-raises rather than guessing.
    """
    detail = str(getattr(exc, "orig", exc))

    if _MEMBER_KEY_CONSTRAINT in detail:
        return MemberConflict(
            f"Member {key!r} already exists in this community",
            ErrorCode.MEMBER_KEY_TAKEN,
        )
    if _MEMBER_USER_ID_CONSTRAINT in detail:
        return MemberConflict(
            f"A member with user_id {user_id!r} already exists in this community",
            ErrorCode.USER_ID_TAKEN,
        )
    if _MEMBER_DID_CONSTRAINT in detail:
        # Deliberately unlike the two above: it names no holder. This index is
        # global, so the member it collided with may be in a community the
        # caller was not addressing, and saying which member holds a DID would
        # answer a question about somebody else's community.
        return MemberConflict(
            f"did {did!r} already belongs to another member", ErrorCode.DID_TAKEN
        )
    return None


# ── lookups ───────────────────────────────────────────────────────────────────


async def resolve_community(session: AsyncSession, community_key: str) -> Community:
    community = await session.scalar(
        select(Community).where(Community.key == community_key)
    )
    if community is None:
        raise CommunityNotFound(f"Community {community_key!r} not found")
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


async def lock_community(
    session: AsyncSession, community: Community, *, share: bool
) -> None:
    """Lock the community's row and refresh ``community`` from it.

    What keeps "a member's area is one of its community's" (REQ-0066) true
    when an area is deleted at the same moment a member is moved into it. A
    write that sets a member's area takes the lock ``share``d and reads the
    areas after it; deleting an area takes it exclusively before counting the
    members that reference it. Either the area delete commits first and the
    member write then finds the area gone, or the member write commits first
    and the delete then counts that member and answers ``409 area_in_use``.

    Community row before member rows before sensor advisory locks — the order
    every write here takes them in, so no two writers wait on each other in a
    cycle (``sensors.lock_member``).
    """
    await session.execute(
        select(Community)
        .where(Community.id == community.id)
        .with_for_update(read=share)
        .execution_options(populate_existing=True)
    )


# ── key minting ───────────────────────────────────────────────────────────────


def next_member_key(existing: Sequence[str]) -> str:
    """Mint the next member key, following whatever pattern the community uses.

    Communities number their members (``ex-00001``), and a caller that has no
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
    """Everything on a member that is not a column, including its schema.org type.

    A model that *declares* ``extra`` (``MemberCreate``) has it merged in at the
    top level, last, exactly as ``apply_member_patch`` merges it — so a client
    sending one body to create and to patch gets one stored shape. A bundle
    ``MemberIn`` declares no such field, so there an ``extra:`` key is one more
    unknown key, as it always was.
    """
    # Asked of the class, not the instance: on a bundle `MemberIn` an unknown
    # `extra` key is readable as an attribute too, and must not be merged.
    declared = (
        getattr(member_in, "extra", None) or {}
        if "extra" in type(member_in).model_fields
        else None
    )
    return {
        **({"type": member_in.type} if member_in.type else {}),
        **_extract_extra(
            member_in, _MEMBER_COLUMNS if declared is None else _MEMBER_COLUMNS | {"extra"}
        ),
        **(declared or {}),
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

    **A duplicate ``did`` has no check of its own here.** The two checks below
    read a list of this community's members, and DID uniqueness is registry-wide
    — a check would be a second query answering what ``ix_member_did`` already
    answers, and answering it a moment earlier buys nothing a create can use.
    """
    existing = (
        await session.scalars(select(Member).where(Member.community_id == community.id))
    ).all()

    if key is None:
        key = next_member_key([m.key for m in existing])
    elif any(m.key == key for m in existing):
        raise MemberConflict(
            f"Member {key!r} already exists in this community",
            ErrorCode.MEMBER_KEY_TAKEN,
        )

    if any(m.user_id == member_in.user_id for m in existing):
        raise MemberConflict(
            f"A member with user_id {member_in.user_id!r} already exists in this "
            "community",
            ErrorCode.USER_ID_TAKEN,
        )

    # An active member created holding meters holds their sensors from the
    # first moment, so it is checked like an attach (REQ-0069). Raises
    # `SensorHeld` before anything is inserted; the lock is held until the
    # caller's commit.
    # Before anything is inserted, so a key the column cannot hold is a coded
    # refusal rather than a failed insert.
    too_long = too_long_asset_keys(member_in.assets)
    if too_long:
        raise AssetKeyTooLong(too_long[0])

    if member_in.status == ACTIVE and member_in.assets:
        await ensure_sensors_free(
            session,
            community_id=community.id,
            member_id=None,
            sensor_ids=(
                normalise_sensor_id(m.sensor_id)
                for m in (member_in.assets.meter or {}).values()
            ),
        )

    member = Member(
        community_id=community.id,
        key=key,
        user_id=member_in.user_id,
        did=member_in.did,
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
        conflict = member_conflict_from(
            exc, key=key, user_id=member_in.user_id, did=member_in.did
        )
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


async def ensure_reactivation_allowed(
    session: AsyncSession, community: Community, member: Member, new_status: str | None
) -> None:
    """Refuse a move to ``active`` while another active member holds one of
    this member's sensors (REQ-0069).

    Only an active member holds a sensor, so a member that was not active held
    nothing, and another member may have been given its meter meanwhile.
    Reactivating it then would make two holders. Raises ``SensorHeld``; the
    caller changes nothing. A member already active is not re-checked.

    The member's row is locked first and its status and sensor ids read after
    the lock, so an attach to this member running at the same moment is
    either committed and among the ids checked, or waits and then sees the
    member active and checks itself (``upsert_asset``). Must be called in the
    transaction that then writes the status.
    """
    if new_status != ACTIVE:
        return
    await lock_member(session, member)
    if member.status == ACTIVE:
        return
    await ensure_sensors_free(
        session,
        community_id=community.id,
        member_id=member.id,
        sensor_ids=await member_sensor_ids(session, member.id),
    )


async def apply_member_patch(
    member: Member, patch: dict[str, Any]
) -> Member:
    """Apply a partial update. Absent keys are left alone, not cleared.

    ``delivery_points`` is deliberately **not** patchable here — it is a JSONB
    list, and a partial update that happens to omit it would otherwise read as
    "this member now has none". It has its own sub-resource.

    ``did`` **is** patchable, and this is the route ../onboarding uses to write
    it: the DID is minted a step after the member is registered, so it arrives
    as an update to a row that already exists rather than as a field on the
    create. Its uniqueness clash is answered by the caller — see
    ``api/admin/writes.py::patch_member``.
    """
    for field in ("name", "role", "area", "status", "user_id", "did"):
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
    """Create or replace one asset of a member, leaving its siblings alone.

    **Asset keys are unique per community, not per member** —
    ``uq_asset_community_key`` is on ``(community_id, key)``, while the lookup
    below filters by owner as well. So the insert can be refused by a row this
    function never looked at, and the two cases behind that need different
    answers:

    * **the key is already this member's.** Another writer created it between
      the select and the insert. Retry as the update it would have been had they
      been a moment earlier, and answer as if nothing happened — a
      create-or-replace is idempotent by definition, and a race means only that
      two writers arrived in an order neither cared about.
    * **the key is another member's.** ``AssetKeyTaken``. Applying the upsert
      would move somebody else's meter onto this member, which is not what
      "replace my asset" asked for, and it is a conflict whether the other row
      arrived a moment ago or last year.

    The second is not only a race: two members using one key sequentially takes
    exactly the same path, and used to be a `500`.
    """
    if len(asset_key) > ASSET_KEY_MAX_LENGTH:
        raise AssetKeyTooLong(asset_key)

    base_exclude = {"name", "relationships", "device"}
    raw_sensor_id = getattr(payload, "sensor_id", None)
    # Stored trimmed (REQ-0069). A meter's id blank after trimming is refused by
    # the route before this is reached.
    sensor_id = normalise_sensor_id(raw_sensor_id)
    exclude = base_exclude | ({"sensor_id"} if raw_sensor_id is not None else set())

    # Before the key: a sensor another active member holds is `sensor_held`
    # whoever holds the key, and a key clash is only reached for a sensor
    # nobody active holds — with `meter-<sensor id>` keys, an inactive member
    # still holding the asset (REQ-0071). Only an active member holds, so a
    # write to one that is not active is checked when it is reactivated.
    #
    # The member's row is locked, and its status re-read, before deciding: a
    # reactivation of this member running at the same moment either committed
    # first (the status now reads active and the sensor is checked here) or
    # waits for this commit and then finds this sensor among the member's
    # (`ensure_reactivation_allowed`). Without the lock each could miss the
    # other's uncommitted half and leave two active holders.
    if sensor_id is not None:
        await lock_member(session, member)
    if sensor_id is not None and member.status == ACTIVE:
        await ensure_sensors_free(
            session,
            community_id=community.id,
            member_id=member.id,
            sensor_ids=[sensor_id],
        )

    existing = await session.scalar(
        select(Asset).where(
            Asset.community_id == community.id,
            Asset.owner_id == member.id,
            Asset.key == asset_key,
        )
    )

    fields = dict(
        asset_type=asset_type,
        name=payload.name,
        sensor_id=sensor_id,
        properties=_extract_properties(payload, exclude),
        device=_extract_device(payload),
        relationships=_extract_relationships(payload),
    )

    if existing is not None:
        for name, value in fields.items():
            setattr(existing, name, value)
        await session.flush()
        return existing

    asset = Asset(
        community_id=community.id, owner_id=member.id, key=asset_key, **fields
    )

    try:
        # A SAVEPOINT, so that a refused insert costs this statement rather than
        # the whole request: unlike `create_member`, the answer here may be to
        # carry on rather than to give up, and a rolled-back transaction has
        # nothing left to carry on with. `add` goes inside it so that rolling
        # back to the savepoint also discards the pending row — otherwise the
        # next flush re-attempts the insert that just failed.
        async with session.begin_nested():
            session.add(asset)
            await session.flush()
    except IntegrityError as exc:
        if _ASSET_KEY_CONSTRAINT not in str(getattr(exc, "orig", exc)):
            raise

        winner = await session.scalar(
            select(Asset).where(
                Asset.community_id == community.id, Asset.key == asset_key
            )
        )
        if winner is None:
            # Refused by the index, and yet nothing is there to have refused it.
            # Not the case this handles; let the original error stand rather
            # than answer something invented.
            raise
        if winner.owner_id != member.id:
            raise AssetKeyTaken(
                f"Asset key {asset_key!r} already belongs to another member of "
                f"this community"
            ) from exc

        for name, value in fields.items():
            setattr(winner, name, value)
        await session.flush()
        return winner

    return asset
