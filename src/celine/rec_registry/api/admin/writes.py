"""
Write API routes (Admin).

Members, their delivery points and assets, and community metadata — the state
that changes at runtime, when a manager approves somebody rather than when a
YAML bundle is imported.

Every route here keeps one rule: **no write may reduce a sibling.** `PUT` on a
member replaces that member, not the member list; patching a member does not
clear its delivery points; upserting an area does not drop the others. The only
endpoint that deletes what it was not given is the bundle import, which says so
in its name and now refuses without `force`.

Reads for these same resources live in `communities.py`.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import ValidationError
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from celine.rec_registry.core.area_boundary import (
    AREA_KEY_RULE,
    area_boundary_refusals,
    areas_referencing,
    child_nodes,
    is_area_key,
    node_write_refusals,
)
from celine.rec_registry.core.errors import ErrorCode, RegistryError, error_responses
from celine.rec_registry.core.member_values import OutOfSet, member_value_refusals
from celine.rec_registry.db.models import Asset, Community, Member
from celine.rec_registry.db.session import get_session
from celine.rec_registry.schemas.bundle import (
    DeliveryPointIn,
    EVChargerAssetIn,
    HeatPumpAssetIn,
    LoadAssetIn,
    MeterAssetIn,
    PVAssetIn,
    StorageAssetIn,
    TopologyNodeIn,
)
from celine.rec_registry.schemas.models import (
    Area,
    AreaRename,
    AreaRenamed,
    AreaUpsert,
    AssetDetail,
    AssetUpsert,
    CommunityDetail,
    CommunityPatch,
    DeletionReport,
    DeliveryPoint,
    DeliveryPointsResponse,
    MemberAreaPut,
    MemberCreate,
    MemberDetail,
    MemberNamePut,
    MemberPatch,
    MemberProfilePatch,
    MemberRolePut,
    MemberStatusChange,
    TopologyNode,
)
from celine.rec_registry.services import members as member_service

router = APIRouter()

# Asset payloads are validated against the model for their type, so an EV
# charger cannot be stored carrying a heat pump's fields.
ASSET_MODELS = {
    "pv": PVAssetIn,
    "storage": StorageAssetIn,
    "meter": MeterAssetIn,
    "ev_charger": EVChargerAssetIn,
    "heat_pump": HeatPumpAssetIn,
    "load": LoadAssetIn,
}

def _refuse_out_of_set(found: list[OutOfSet]) -> None:
    """``422`` with the first value's code; the detail names every one (REQ-0066)."""
    if found:
        raise RegistryError(422, "; ".join(f.detail for f in found), found[0].code)


async def _check_member_values(
    session: AsyncSession, community: Community, fields: dict
) -> None:
    """Hold ``role``, ``status`` and ``area`` among ``fields`` to their sets.

    A field absent from ``fields``, or ``None`` in it — which a patch leaves
    alone — is not checked. Checking an area locks the community's row first
    (``lock_community``), so the area cannot be deleted between this check and
    the caller's commit.
    """
    given = {
        name: fields[name]
        for name in ("role", "status", "area")
        if fields.get(name) is not None
    }
    if "area" in given:
        await member_service.lock_community(session, community, share=True)
        given["areas"] = list((community.areas or {}).keys())
    _refuse_out_of_set(member_value_refusals(**given))


def _check_status(status: str | None) -> None:
    if status is not None:
        _refuse_out_of_set(member_value_refusals(status=status))


def _sensor_held(exc: member_service.SensorHeld) -> RegistryError:
    return RegistryError(409, str(exc), ErrorCode.SENSOR_HELD)


def _delivery_point_held(exc: member_service.DeliveryPointHeld) -> RegistryError:
    return RegistryError(409, str(exc), ErrorCode.DELIVERY_POINT_HELD)


def _asset_key_too_long(exc: member_service.AssetKeyTooLong) -> RegistryError:
    return RegistryError(422, str(exc), ErrorCode.ASSET_KEY_TOO_LONG)


def _member_detail(member: Member) -> MemberDetail:
    return MemberDetail(
        id=str(member.id),
        key=member.key,
        user_id=member.user_id,
        did=member.did,
        name=member.name,
        role=member.role,
        area=member.area,
        status=member.status,
        delivery_points=[DeliveryPoint(**dp) for dp in (member.delivery_points or [])],
        extra=member.extra or {},
        created_at=member.created_at.isoformat() if member.created_at else None,
        updated_at=member.updated_at.isoformat() if member.updated_at else None,
    )


async def _resolve(
    session: AsyncSession, community_key: str, member_key: str | None = None
):
    try:
        community = await member_service.resolve_community(session, community_key)
        if member_key is None:
            return community, None
        member = await member_service.resolve_member(session, community, member_key)
        return community, member
    except member_service.MemberNotFound as exc:
        raise RegistryError(404, str(exc), exc.code) from exc


# =============================================================================
# Members
# =============================================================================


@router.post(
    "/communities/{community_key}/members",
    response_model=MemberDetail,
    status_code=201,
    responses=error_responses(404, 409, 422),
)
async def create_member(
    community_key: str,
    payload: MemberCreate,
    session: AsyncSession = Depends(get_session),
):
    """Create one member.

    Answers `409` when the key or `user_id` is already taken, naming the
    existing key so a caller can switch to `PATCH`. It does not overwrite: the
    caller asked to create, and silently updating somebody else's row is how a
    retry with a changed payload rewrites the wrong person.

    A concurrent create answers `409` too — the unique index refuses it, and the
    service translates that back into the same conflict.

    An `active` member created with meters is `409 sensor_held` when another
    active member, in any community, holds one of their sensors (REQ-0069),
    and one created with delivery points, or with meters naming a `pod`, is
    `409 delivery_point_held` when another active member holds one of those
    (REQ-0085, REQ-0093).
    An asset key longer than 128 characters is `422 asset_key_too_long`
    (REQ-0028).

    `role` and `status` outside their sets are `422 invalid_role` /
    `invalid_status`, and an `area` that is not a key of the community's
    areas is `422 unknown_area` (REQ-0066).
    """
    community, _ = await _resolve(session, community_key)

    await _check_member_values(
        session,
        community,
        {"role": payload.role, "status": payload.status, "area": payload.area},
    )

    member_in = payload.model_copy(update={"key": None})
    try:
        member, warnings = await member_service.create_member(
            session, community, member_in, key=payload.key
        )
    except member_service.MemberConflict as exc:
        raise RegistryError(409, str(exc), exc.code) from exc
    except member_service.SensorHeld as exc:
        raise _sensor_held(exc) from exc
    except member_service.DeliveryPointHeld as exc:
        raise _delivery_point_held(exc) from exc
    except member_service.AssetKeyTooLong as exc:
        raise _asset_key_too_long(exc) from exc

    await session.commit()
    await session.refresh(member)

    detail = _member_detail(member)
    if warnings:
        detail.extra = {**detail.extra, "import_warnings": warnings}
    return detail


@router.patch(
    "/communities/{community_key}/members/{member_key}",
    response_model=MemberDetail,
    responses=error_responses(404, 409, 422),
)
async def patch_member(
    community_key: str,
    member_key: str,
    payload: MemberPatch,
    session: AsyncSession = Depends(get_session),
):
    """Partially update a member. Absent fields are left alone.

    Reassigning a `user_id` that belongs to somebody else is `409`, whether the
    clash was already committed or arrives concurrently.

    **This is also how a member's dataspace DID is written**, because the DID is
    minted a step after the member is registered — there is no separate route
    for it, since a dedicated write would have to be added to
    `TestNoWriteReducesASibling` to earn nothing `PATCH` does not already do.
    Its clash check differs from the `user_id` one beside it in two ways, and
    both matter:

    * **It is registry-wide.** `ix_member_did` is global, so the check cannot be
      scoped to the community in the path. It covers active members only
      (REQ-0096), so only an active holder clashes, and only with a member
      that is active after the patch.
    * **It names the holder only inside the addressed community.** Saying which
      member of *another* community holds a DID would answer a question the
      caller did not ask about people they were not addressing — the same
      enumeration reasoning as REQ-0045.

    Re-sending a member the DID it already holds is a no-op success: onboarding
    writes it from a retriable step, so the same write arriving twice must not
    be a conflict.

    Setting `status: active` on a member that was not active re-checks its
    sensors, delivery points and meters' `pod`, and the whole patch is refused
    `409 sensor_held` / `409 delivery_point_held` when another active member
    holds one (REQ-0069, REQ-0085, REQ-0093).

    `role` and `area` are still accepted here, for `members.write` holders,
    and held to the same sets as on `PATCH …/profile`: `422 invalid_role`,
    `invalid_status`, `unknown_area` (REQ-0066). A role change leaves the
    member's assets as they are.
    """
    community, member = await _resolve(session, community_key, member_key)

    patch = payload.model_dump(exclude_unset=True)
    await _check_member_values(session, community, patch)

    if "user_id" in patch and patch["user_id"]:
        clash = await session.scalar(
            select(Member).where(
                Member.community_id == community.id,
                Member.user_id == patch["user_id"],
                Member.key != member.key,
            )
        )
        if clash is not None:
            raise RegistryError(
                409,
                f"user_id {patch['user_id']!r} already belongs to member "
                f"{clash.key!r}",
                ErrorCode.USER_ID_TAKEN,
            )

    # Only an active holder clashes, and only when this member ends the patch
    # active: `ix_member_did` covers active members alone (REQ-0096). A
    # reactivation that brings a held DID back is refused by the index at
    # commit, below.
    if (
        "did" in patch
        and patch["did"]
        and (patch.get("status") or member.status) == member_service.ACTIVE
    ):
        # `Member.id`, not `Member.key`: keys repeat across communities and this
        # query does not filter by one, so excluding by key would also exclude a
        # same-keyed member of a different community — the very holder that has
        # to be found.
        clash = await session.scalar(
            select(Member).where(
                Member.did == patch["did"],
                Member.status == member_service.ACTIVE,
                Member.id != member.id,
            )
        )
        if clash is not None:
            if clash.community_id == community.id:
                detail = (
                    f"did {patch['did']!r} already belongs to member {clash.key!r}"
                )
            else:
                detail = f"did {patch['did']!r} already belongs to another member"
            raise RegistryError(409, detail, ErrorCode.DID_TAKEN)

    try:
        await member_service.ensure_reactivation_allowed(
            session, community, member, patch.get("status")
        )
    except member_service.SensorHeld as exc:
        raise _sensor_held(exc) from exc
    except member_service.DeliveryPointHeld as exc:
        raise _delivery_point_held(exc) from exc

    await member_service.apply_member_patch(member, patch)
    try:
        await session.commit()
    except IntegrityError as exc:
        # The clash check above cannot see a row another writer has not committed
        # yet, so the unique index is what refuses this one. Same answer either way.
        await session.rollback()
        conflict = member_service.member_conflict_from(
            exc,
            key=member_key,
            user_id=patch.get("user_id"),
            did=patch.get("did"),
        )
        if conflict is None:
            raise
        raise RegistryError(409, str(conflict), conflict.code) from exc

    await session.refresh(member)
    return _member_detail(member)


@router.patch(
    "/communities/{community_key}/members/{member_key}/profile",
    response_model=MemberDetail,
    responses=error_responses(404, 422),
)
async def patch_member_profile(
    community_key: str,
    member_key: str,
    payload: MemberProfilePatch,
    session: AsyncSession = Depends(get_session),
):
    """Correct a member's role and area, and nothing else (REQ-0070).

    The body is `{role?, area?}`: at least one of the two, and no other key —
    an empty body, an unknown key, `null`, or a key the general `PATCH`
    accepts (`user_id`, `did`, `status`, `name`, `extra`) is `422` and changes
    nothing. Absent fields are left alone.

    Derives `members.profile.write` (REQ-0063), which
    `rec-registry.members.profile.write`, `rec-registry.members.write` and
    `rec-registry.admin` satisfy (REQ-0064): a community dashboard can be
    given this and nothing more.

    `role` outside its set is `422 invalid_role`; an `area` that is not a key
    of the community's areas is `422 unknown_area` (REQ-0066). A role change
    leaves the member's assets as they are; the member's status is not
    looked at.
    """
    community, member = await _resolve(session, community_key, member_key)

    patch = payload.model_dump(exclude_unset=True)
    await _check_member_values(session, community, patch)

    await member_service.apply_member_patch(member, patch)
    await session.commit()
    await session.refresh(member)
    return _member_detail(member)


async def _put_member_fields(
    session: AsyncSession, community_key: str, member_key: str, fields: dict
) -> MemberDetail:
    """Write one field group of a member, checked as the general `PATCH` checks it.

    The value checks are the general `PATCH`'s own (`_check_member_values`,
    REQ-0066) and the write is its own (`apply_member_patch`), so a field
    written here and one written there cannot be held to different rules.
    """
    community, member = await _resolve(session, community_key, member_key)
    await _check_member_values(session, community, fields)
    await member_service.apply_member_patch(member, fields)
    await session.commit()
    await session.refresh(member)
    return _member_detail(member)


@router.put(
    "/communities/{community_key}/members/{member_key}/name",
    response_model=MemberDetail,
    responses=error_responses(404),
)
async def put_member_name(
    community_key: str,
    member_key: str,
    payload: MemberNamePut,
    session: AsyncSession = Depends(get_session),
):
    """Set a member's name, and nothing else (REQ-0083).

    The body is `{name}`: the one key, not `null`, and no other — anything
    else is `422` (FastAPI's validation body) and changes nothing. Derives
    `members.name.write` (REQ-0081), which `rec-registry.members.name.write`,
    `rec-registry.members.write` and `rec-registry.admin` satisfy (REQ-0082).
    """
    return await _put_member_fields(
        session, community_key, member_key, {"name": payload.name}
    )


@router.put(
    "/communities/{community_key}/members/{member_key}/role",
    response_model=MemberDetail,
    responses=error_responses(404, 422),
)
async def put_member_role(
    community_key: str,
    member_key: str,
    payload: MemberRolePut,
    session: AsyncSession = Depends(get_session),
):
    """Set a member's role, and nothing else (REQ-0083).

    The body is `{role}`, and no other key. A role outside the set is
    `422 invalid_role`, as on the general `PATCH` (REQ-0066). Derives
    `members.role.write` (REQ-0081), which `rec-registry.members.role.write`,
    `rec-registry.members.profile.write`, `rec-registry.members.write` and
    `rec-registry.admin` satisfy (REQ-0082). A role change leaves the
    member's assets as they are.
    """
    return await _put_member_fields(
        session, community_key, member_key, {"role": payload.role}
    )


@router.put(
    "/communities/{community_key}/members/{member_key}/area",
    response_model=MemberDetail,
    responses=error_responses(404, 422),
)
async def put_member_area(
    community_key: str,
    member_key: str,
    payload: MemberAreaPut,
    session: AsyncSession = Depends(get_session),
):
    """Set a member's area, and nothing else (REQ-0083).

    The body is `{area}`, and no other key. An area that is not a key of the
    community's areas is `422 unknown_area`, checked under the community's
    row as on the general `PATCH` (REQ-0066). Derives `members.area.write`
    (REQ-0081), which `rec-registry.members.area.write`,
    `rec-registry.members.profile.write`, `rec-registry.members.write` and
    `rec-registry.admin` satisfy (REQ-0082).
    """
    return await _put_member_fields(
        session, community_key, member_key, {"area": payload.area}
    )


@router.post(
    "/communities/{community_key}/members/{member_key}/status",
    response_model=MemberDetail,
    responses=error_responses(404, 409, 422),
)
async def change_member_status(
    community_key: str,
    member_key: str,
    payload: MemberStatusChange,
    session: AsyncSession = Depends(get_session),
):
    """Move a member through the lifecycle explicitly.

    Separate from `PATCH` because a status change is the transition an operator
    reasons about — and because it reads clearly in an audit log, which a
    generic field update does not.

    A move to `active` re-checks the member's sensors, delivery points and
    meters' `pod`: when another active member took one meanwhile it answers
    `409 sensor_held` / `409 delivery_point_held` and the status is left as
    it was (REQ-0069, REQ-0085, REQ-0093).
    """
    community, member = await _resolve(session, community_key, member_key)

    _check_status(payload.status)

    try:
        await member_service.ensure_reactivation_allowed(
            session, community, member, payload.status
        )
    except member_service.SensorHeld as exc:
        raise _sensor_held(exc) from exc
    except member_service.DeliveryPointHeld as exc:
        raise _delivery_point_held(exc) from exc

    member.status = payload.status
    if payload.reason:
        member.extra = {**(member.extra or {}), "status_reason": payload.reason}

    did = member.did  # read before the rollback below expires the row
    try:
        await session.commit()
    except IntegrityError as exc:
        # A move to `active` while another active member holds this member's
        # DID: `ix_member_did` covers active members only (REQ-0096).
        await session.rollback()
        conflict = member_service.member_conflict_from(exc, did=did)
        if conflict is None:
            raise
        raise RegistryError(409, str(conflict), conflict.code) from exc
    await session.refresh(member)
    return _member_detail(member)


@router.delete(
    "/communities/{community_key}/members/{member_key}",
    response_model=DeletionReport,
    responses=error_responses(404),
)
async def delete_member(
    community_key: str,
    member_key: str,
    purge: bool = Query(
        default=False,
        description=(
            "Permanently remove the member and its assets. Requires the "
            "rec-registry.members.purge grant. Without it the member is "
            "deactivated, which is reversible."
        ),
    ),
    session: AsyncSession = Depends(get_session),
):
    """Deactivate a member, or erase one.

    Deactivation is the default because a member who leaves still has historical
    metering data, past consents and provenance elsewhere in the platform that
    reference them — and `Asset` cascades on delete, so a real removal silently
    takes their meters too.

    `purge=true` is for an erasure request. It is authorized separately from
    ordinary member writes, so a service that manages members day to day cannot
    perform one.
    """
    community, member = await _resolve(session, community_key, member_key)

    if not purge:
        member.status = "inactive"
        await session.commit()
        return DeletionReport(
            community_key=community.key,
            member_key=member.key,
            purged=False,
            status=member.status,
        )

    asset_count = (
        await session.scalar(
            select(func.count())
            .select_from(Asset)
            .where(Asset.owner_id == member.id)
        )
    ) or 0

    await session.delete(member)
    await session.commit()

    return DeletionReport(
        community_key=community.key,
        member_key=member_key,
        purged=True,
        status=None,
        assets_removed=int(asset_count),
    )


# =============================================================================
# Delivery points
# =============================================================================


@router.put(
    "/communities/{community_key}/members/{member_key}/delivery-points/{point_id}",
    response_model=DeliveryPointsResponse,
    responses=error_responses(404, 409),
)
async def upsert_delivery_point(
    community_key: str,
    member_key: str,
    point_id: str,
    payload: DeliveryPointIn,
    replaces: str | None = Query(
        default=None,
        description=(
            "Correct a delivery point: the id of the member's point this one "
            "replaces. In one transaction the new point is added, this one "
            "removed, and the member's meters whose `pod` named it are "
            "relinked to the new id. `404` when the member has no such point."
        ),
    ),
    session: AsyncSession = Depends(get_session),
):
    """Add or replace one supply point, keeping the others.

    A sub-resource rather than a field on the member, because `delivery_points`
    is a JSONB list: a member gaining a second supply point must not lose the
    first, which is exactly what a naive whole-field update does.

    **`?replaces={old}` corrects a point in one write** (REQ-0084): the new
    point is added, `old` (trimmed, case-insensitive) is removed, and the
    member's meters whose `properties.pod` named `old` are relinked to the
    new id, as the path spells it — all in one transaction, so a failure
    leaves both points and every link as they were. `404` when `old` is not
    this member's point. The query never changes the action: this route
    derives `members.delivery_points.write` either way (REQ-0081).

    An `active` member taking a point another active member holds, in any
    community, is `409 delivery_point_held` (REQ-0085), and nothing changes.
    """
    community, member = await _resolve(session, community_key, member_key)

    if payload.id != point_id:
        raise HTTPException(
            422, f"Body id {payload.id!r} does not match path id {point_id!r}"
        )

    try:
        await member_service.put_delivery_point(
            session, community, member, payload, replaces=replaces
        )
    except member_service.DeliveryPointNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except member_service.DeliveryPointHeld as exc:
        raise _delivery_point_held(exc) from exc

    await session.commit()
    await session.refresh(member)

    return DeliveryPointsResponse(
        delivery_points=[DeliveryPoint(**dp) for dp in (member.delivery_points or [])]
    )


@router.delete(
    "/communities/{community_key}/members/{member_key}/delivery-points/{point_id}",
    response_model=DeliveryPointsResponse,
    responses=error_responses(404, 409),
)
async def remove_delivery_point(
    community_key: str,
    member_key: str,
    point_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Remove one supply point, keeping the others.

    Refused `409 delivery_point_linked` while one of the member's meters
    names it as its `pod` (REQ-0084): correct it with `PUT …?replaces=`, or
    detach the meter, first.
    """
    _, member = await _resolve(session, community_key, member_key)

    try:
        await member_service.remove_unlinked_delivery_point(session, member, point_id)
    except member_service.DeliveryPointNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except member_service.DeliveryPointLinked as exc:
        raise RegistryError(409, str(exc), ErrorCode.DELIVERY_POINT_LINKED) from exc

    await session.commit()
    await session.refresh(member)

    return DeliveryPointsResponse(
        delivery_points=[DeliveryPoint(**dp) for dp in (member.delivery_points or [])]
    )


# =============================================================================
# Assets
# =============================================================================


@router.put(
    "/communities/{community_key}/members/{member_key}/assets/{asset_key}",
    response_model=AssetDetail,
    status_code=200,
    responses=error_responses(404, 409, 422),
)
async def upsert_asset(
    community_key: str,
    member_key: str,
    asset_key: str,
    payload: AssetUpsert,
    session: AsyncSession = Depends(get_session),
):
    """Create or replace one asset, leaving the member's other assets alone.

    Answers `409` when the key already belongs to another member of the
    community — asset keys are unique per community, not per member, so a key
    that looks free to this member may not be.

    A concurrent upsert of the same key by the same member is **not** a
    conflict: the service applies it to the row the other writer created and
    answers `200`, because a create-or-replace is idempotent and a race means
    only that the two arrived in an order neither cared about.

    **A meter is attached here** — by convention at `meter-<sensor id>`, the id
    trimmed (REQ-0071). The outcomes a caller tells apart by `code`:

    * `200` — attached, or already attached to this member (a no-op replace);
    * `409 sensor_held` — another active member, in any community, holds the
      sensor (REQ-0069); a holder outside this community is not named;
    * `409 delivery_point_held` — the meter's `pod` is not one of the member's
      own delivery points, and another active member, in any community, holds
      it as a delivery point or through a meter of its own (REQ-0093); named
      as REQ-0085 names a holder;
    * `409 asset_key_taken` — another member of this community holds the key
      (with the convention: an inactive member still holding the asset).

    The sensor id is stored trimmed; one blank after trimming is `422`. An
    asset key longer than 128 characters is `422 asset_key_too_long` — with the
    convention, a sensor id longer than 122 (REQ-0028).

    Answers the stored asset.
    """
    community, member = await _resolve(session, community_key, member_key)

    if payload.key != asset_key:
        raise HTTPException(
            422, f"Body key {payload.key!r} does not match path key {asset_key!r}"
        )

    model = ASSET_MODELS.get(payload.asset_type)
    if model is None:
        raise HTTPException(
            422,
            f"Unknown asset_type {payload.asset_type!r}; expected one of "
            f"{', '.join(sorted(ASSET_MODELS))}",
        )

    try:
        validated = model(**payload.properties)
    except ValidationError as exc:
        raise HTTPException(422, f"Invalid {payload.asset_type} asset: {exc}") from exc

    if payload.asset_type == "meter" and not member_service.normalise_sensor_id(
        validated.sensor_id
    ):
        # A meter without a sensor id is unreachable rather than incomplete
        # (REQ-0035); the bundle path skips one, a single write refuses it.
        raise HTTPException(422, "Invalid meter asset: sensor_id is blank")

    try:
        asset = await member_service.upsert_asset(
            session,
            community=community,
            member=member,
            asset_key=asset_key,
            asset_type=payload.asset_type,
            payload=validated,
        )
    except member_service.AssetKeyTaken as exc:
        raise RegistryError(409, str(exc), ErrorCode.ASSET_KEY_TAKEN) from exc
    except member_service.SensorHeld as exc:
        raise _sensor_held(exc) from exc
    except member_service.DeliveryPointHeld as exc:
        raise _delivery_point_held(exc) from exc
    except member_service.AssetKeyTooLong as exc:
        raise _asset_key_too_long(exc) from exc

    await session.commit()
    await session.refresh(asset)

    return AssetDetail(
        id=str(asset.id),
        key=asset.key,
        asset_type=asset.asset_type,
        name=asset.name,
        owner_key=member.key,
        owner_user_id=member.user_id,
        sensor_id=asset.sensor_id,
        properties=asset.properties or {},
        device=asset.device or {},
        relationships=asset.relationships or {},
        extra=asset.extra or {},
        created_at=asset.created_at.isoformat() if asset.created_at else None,
        updated_at=asset.updated_at.isoformat() if asset.updated_at else None,
    )


@router.delete(
    "/communities/{community_key}/members/{member_key}/assets/{asset_key}",
    status_code=204,
    responses=error_responses(404),
)
async def delete_asset(
    community_key: str,
    member_key: str,
    asset_key: str,
    session: AsyncSession = Depends(get_session),
):
    """Remove one asset. Assets carry no history of their own, so this is a
    real delete — unlike a member, whose removal would cascade.

    **This is how a meter is detached** (REQ-0071): a hard delete, after which
    the sensor is free to be attached elsewhere. An asset the member does not
    hold is `404 asset_not_found`.
    """
    community, member = await _resolve(session, community_key, member_key)

    asset = await session.scalar(
        select(Asset).where(
            Asset.community_id == community.id,
            Asset.owner_id == member.id,
            Asset.key == asset_key,
        )
    )
    if asset is None:
        raise RegistryError(404, f"Asset {asset_key!r} not found", ErrorCode.ASSET_NOT_FOUND)

    await session.delete(asset)
    await session.commit()
    return Response(status_code=204)


# =============================================================================
# Community
# =============================================================================


@router.patch(
    "/communities/{community_key}",
    response_model=CommunityDetail,
    responses=error_responses(404),
)
async def patch_community(
    community_key: str,
    payload: CommunityPatch,
    session: AsyncSession = Depends(get_session),
):
    """Update community metadata. Areas and topology have their own routes
    (`…/areas/{key}`, `…/areas/{key}/rename`, `…/topology/{node_id}`), and
    this never touches either."""
    community, _ = await _resolve(session, community_key)

    patch = payload.model_dump(exclude_unset=True)
    for field in ("name", "description", "legal", "links", "contact", "settings"):
        if field in patch and patch[field] is not None:
            setattr(community, field, patch[field])
    if "extra" in patch and patch["extra"] is not None:
        community.extra = {**(community.extra or {}), **patch["extra"]}

    await session.commit()
    await session.refresh(community)

    return CommunityDetail(
        id=str(community.id),
        key=community.key,
        name=community.name,
        description=community.description,
        legal=community.legal or {},
        links=community.links or {},
        contact=community.contact or {},
        settings=community.settings or {},
        areas={k: Area(**v) for k, v in (community.areas or {}).items()},
        topology=[TopologyNode(**n) for n in (community.topology or [])],
        extra=community.extra or {},
        created_at=community.created_at.isoformat() if community.created_at else None,
        updated_at=community.updated_at.isoformat() if community.updated_at else None,
    )


@router.put(
    "/communities/{community_key}/areas/{area_key}",
    response_model=CommunityDetail,
    responses=error_responses(404, 422),
)
async def upsert_area(
    community_key: str,
    area_key: str,
    payload: AreaUpsert,
    session: AsyncSession = Depends(get_session),
):
    """Add or replace one area, keeping the others.

    Topology assignments change more often than the community does, so this is a
    sub-resource rather than part of the community patch.

    **An area is one primary substation** (REQ-0067): `boundary: {source, id}`
    with `source` `gse_cabine_primarie`, and `topology` listing exactly one node
    id — `boundary.id`, a node of the community's topology whose `type` is
    `primary_substation`. No other area of the community may carry the same
    `boundary.id`. Anything else is `422 invalid_area_boundary` and changes
    nothing — including a node the community's topology does not hold yet,
    which has to be written first. Areas stored before the rule are not
    re-judged, except that the written area may not share their boundary id.

    **The key is an area key** — letters, digits, `-` and `_`, starting with a
    letter or digit, at most 128 characters, what a rename accepts — or the
    write is `422 invalid_area_key` and changes nothing. An area stored under
    another key is read as stored; a rename moves it onto one that keeps the
    rule.
    """
    community, _ = await _resolve(session, community_key)
    if not is_area_key(area_key):
        raise RegistryError(
            422,
            f"The area key is not a valid area key: {AREA_KEY_RULE}",
            ErrorCode.INVALID_AREA_KEY,
        )
    # Exclusively, and before reading the siblings: two writers putting two
    # areas onto one substation at once are serialised here, and the second
    # sees the first's boundary (REQ-0067). Also what `delete_area` takes.
    await member_service.lock_community(session, community, share=False)

    entry = {"name": payload.name, "topology": list(payload.topology)}
    if payload.boundary is not None:
        # Judged below before anything is stored; only an `AreaBoundaryIn`
        # passes, so what is stored is always `{source, id}`.
        boundary = payload.boundary
        entry["boundary"] = (
            boundary.model_dump() if hasattr(boundary, "model_dump") else boundary
        )
    if payload.location is not None:
        entry["location"] = payload.location.model_dump()
    if payload.geometry is not None:
        entry["geometry"] = payload.geometry

    areas = {**(community.areas or {}), area_key: entry}
    refusals = area_boundary_refusals(
        areas, community.topology or [], only=[area_key]
    )
    if refusals:
        raise RegistryError(
            422, "; ".join(refusals), ErrorCode.INVALID_AREA_BOUNDARY
        )

    community.areas = areas
    await session.commit()
    await session.refresh(community)

    return await patch_community(
        community_key, CommunityPatch(), session
    )


@router.delete(
    "/communities/{community_key}/areas/{area_key}",
    response_model=CommunityDetail,
    responses=error_responses(404, 409),
)
async def delete_area(
    community_key: str,
    area_key: str,
    session: AsyncSession = Depends(get_session),
):
    """Remove an area, unless members still reference it.

    Refusing is the point: an orphaned `Member.area` is a dangling reference
    that nothing else in the system checks, and it would surface much later as a
    member who belongs to an area that does not exist.
    """
    community, _ = await _resolve(session, community_key)
    # Exclusively, before counting: a member write moving somebody into this
    # area holds the row shared until it commits, so the count below sees it
    # (REQ-0066).
    await member_service.lock_community(session, community, share=False)

    areas = community.areas or {}
    if area_key not in areas:
        raise HTTPException(404, f"Area {area_key!r} not found")

    in_use = await session.scalar(
        select(func.count())
        .select_from(Member)
        .where(Member.community_id == community.id, Member.area == area_key)
    )
    if in_use:
        raise RegistryError(
            409,
            f"Area {area_key!r} is still referenced by {in_use} member(s); "
            "move them first",
            ErrorCode.AREA_IN_USE,
        )

    community.areas = {k: v for k, v in areas.items() if k != area_key}
    await session.commit()

    return await patch_community(community_key, CommunityPatch(), session)


@router.post(
    "/communities/{community_key}/areas/{area_key}/rename",
    response_model=AreaRenamed,
    responses=error_responses(404, 409, 422),
)
async def rename_area(
    community_key: str,
    area_key: str,
    payload: AreaRename,
    session: AsyncSession = Depends(get_session),
):
    """Move an area to a new key, with its members, in one write (REQ-0079).

    The area — name, boundary, topology, as stored — is written under
    `new_key`, every member of the community whose `area` is `area_key`
    (active or not) is moved to `new_key`, and `area_key` is removed: one
    transaction, under the community's row taken exclusively, so no reader
    sees both keys, or a member in an area that does not exist, or two areas
    on one boundary (REQ-0067). Nothing else changes — not the other areas,
    not the members' other fields, not their assets.

    This is how an onboarding template sync renames an area whose substation
    the registry already holds under another key: an area `PUT` under the new
    key would be refused (one area per boundary), and the old key cannot be
    deleted while members hold it.

    Refused, changing nothing: `422 invalid_area_key` for a `new_key` that is
    not an area key; `404 area_not_found` for an `area_key` the community does
    not have; `409 area_key_taken` for a `new_key` it already has. Derives
    `community.write`.
    """
    community, _ = await _resolve(session, community_key)

    try:
        moved = await member_service.rename_area(
            session, community, area_key, payload.new_key
        )
    except member_service.AreaRenameRefused as exc:
        raise RegistryError(exc.status, str(exc), exc.code) from exc

    await session.commit()
    await session.refresh(community)

    return AreaRenamed(
        old_key=area_key,
        new_key=payload.new_key,
        members_moved=moved,
        community=await patch_community(community_key, CommunityPatch(), session),
    )


# =============================================================================
# Topology nodes
# =============================================================================


@router.put(
    "/communities/{community_key}/topology/{node_id}",
    response_model=CommunityDetail,
    responses=error_responses(404, 422),
)
async def upsert_topology_node(
    community_key: str,
    node_id: str,
    payload: TopologyNodeIn,
    session: AsyncSession = Depends(get_session),
):
    """Add or replace one topology node, keeping the others (REQ-0072).

    Nodes merge by `id`, as delivery points do: re-sending an existing id
    replaces that node where it stands, and a new id is appended. The body is
    the bundle's topology node — `id`, `type`, and optionally `name`,
    `operator_id`, `parent`, `area` — under the names every read answers;
    other keys are not stored. The body `id` must match the path, or `422`.

    **A node write never breaks an area that keeps the one-substation rule**
    (REQ-0067): changing the `type` of a node such an area lists away from
    `primary_substation` is `422 invalid_area_boundary` and changes nothing.
    This is the route an onboarding template sync writes a community's
    substations through, before the areas that reference them.

    Answers the whole community, so the caller can see the others are still
    there.
    """
    community, _ = await _resolve(session, community_key)

    if payload.id != node_id:
        raise HTTPException(
            422, f"Body id {payload.id!r} does not match path id {node_id!r}"
        )

    # Exclusively, before reading the areas: an area `PUT` onto this node at
    # the same moment is serialised on the same row (REQ-0067).
    await member_service.lock_community(session, community, share=False)

    before = list(community.topology or [])
    after = member_service.merge_topology_node(before, payload)
    refusals = node_write_refusals(community.areas or {}, before, after, node_id)
    if refusals:
        raise RegistryError(
            422, "; ".join(refusals), ErrorCode.INVALID_AREA_BOUNDARY
        )

    community.topology = after
    await session.commit()
    await session.refresh(community)

    return await patch_community(community_key, CommunityPatch(), session)


@router.delete(
    "/communities/{community_key}/topology/{node_id}",
    response_model=CommunityDetail,
    responses=error_responses(404, 409),
)
async def delete_topology_node(
    community_key: str,
    node_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Remove one topology node, unless something still references it (REQ-0072).

    A node an area lists is `409 topology_node_in_use`, naming the areas —
    whether or not those areas keep the one-substation rule — so the areas are
    changed or deleted first. So is a node another node names as its
    `parent`, naming those nodes by id, so they are re-parented or deleted
    first. A node the community does not have is `404`.
    """
    community, _ = await _resolve(session, community_key)
    # Exclusively, before reading the areas: an area `PUT` naming this node at
    # the same moment either commits first and is counted, or finds it gone.
    await member_service.lock_community(session, community, share=False)

    topology = list(community.topology or [])
    if not any(n.get("id") == node_id for n in topology):
        raise HTTPException(404, f"Topology node {node_id!r} not found")

    in_use = areas_referencing(community.areas or {}, node_id)
    if in_use:
        named = ", ".join(repr(k) for k in in_use)
        raise RegistryError(
            409,
            f"Topology node {node_id!r} is still referenced by area(s) {named}; "
            "change or delete them first",
            ErrorCode.TOPOLOGY_NODE_IN_USE,
        )

    children = child_nodes(topology, node_id)
    if children:
        named = ", ".join(repr(k) for k in children)
        raise RegistryError(
            409,
            f"Topology node {node_id!r} is the parent of node(s) {named}; "
            "re-parent or delete them first",
            ErrorCode.TOPOLOGY_NODE_IN_USE,
        )

    community.topology = member_service.remove_topology_node(topology, node_id)
    await session.commit()

    return await patch_community(community_key, CommunityPatch(), session)
