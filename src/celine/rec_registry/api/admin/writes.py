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
)
from celine.rec_registry.schemas.models import (
    Area,
    AreaUpsert,
    AssetDetail,
    AssetUpsert,
    CommunityDetail,
    CommunityPatch,
    DeletionReport,
    DeliveryPoint,
    DeliveryPointsResponse,
    MemberCreate,
    MemberDetail,
    MemberPatch,
    MemberProfilePatch,
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
    active member, in any community, holds one of their sensors (REQ-0069).
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
      scoped to the community in the path.
    * **It names the holder only inside the addressed community.** Saying which
      member of *another* community holds a DID would answer a question the
      caller did not ask about people they were not addressing — the same
      enumeration reasoning as REQ-0045.

    Re-sending a member the DID it already holds is a no-op success: onboarding
    writes it from a retriable step, so the same write arriving twice must not
    be a conflict.

    Setting `status: active` on a member that was not active re-checks its
    sensors, and the whole patch is refused `409 sensor_held` when another
    active member holds one (REQ-0069).

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

    if "did" in patch and patch["did"]:
        # `Member.id`, not `Member.key`: keys repeat across communities and this
        # query does not filter by one, so excluding by key would also exclude a
        # same-keyed member of a different community — the very holder that has
        # to be found.
        clash = await session.scalar(
            select(Member).where(
                Member.did == patch["did"],
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

    A move to `active` re-checks the member's sensors: when another active
    member took one meanwhile it answers `409 sensor_held` and the status is
    left as it was (REQ-0069).
    """
    community, member = await _resolve(session, community_key, member_key)

    _check_status(payload.status)

    try:
        await member_service.ensure_reactivation_allowed(
            session, community, member, payload.status
        )
    except member_service.SensorHeld as exc:
        raise _sensor_held(exc) from exc

    member.status = payload.status
    if payload.reason:
        member.extra = {**(member.extra or {}), "status_reason": payload.reason}

    await session.commit()
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
    responses=error_responses(404),
)
async def upsert_delivery_point(
    community_key: str,
    member_key: str,
    point_id: str,
    payload: DeliveryPointIn,
    session: AsyncSession = Depends(get_session),
):
    """Add or replace one supply point, keeping the others.

    A sub-resource rather than a field on the member, because `delivery_points`
    is a JSONB list: a member gaining a second supply point must not lose the
    first, which is exactly what a naive whole-field update does.
    """
    _, member = await _resolve(session, community_key, member_key)

    if payload.id != point_id:
        raise HTTPException(
            422, f"Body id {payload.id!r} does not match path id {point_id!r}"
        )

    member.delivery_points = member_service.merge_delivery_point(
        member.delivery_points or [], payload
    )
    await session.commit()
    await session.refresh(member)

    return DeliveryPointsResponse(
        delivery_points=[DeliveryPoint(**dp) for dp in (member.delivery_points or [])]
    )


@router.delete(
    "/communities/{community_key}/members/{member_key}/delivery-points/{point_id}",
    response_model=DeliveryPointsResponse,
    responses=error_responses(404),
)
async def remove_delivery_point(
    community_key: str,
    member_key: str,
    point_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Remove one supply point, keeping the others."""
    _, member = await _resolve(session, community_key, member_key)

    existing = member.delivery_points or []
    if not any(dp.get("id") == point_id for dp in existing):
        raise HTTPException(404, f"Delivery point {point_id!r} not found")

    member.delivery_points = member_service.remove_delivery_point(existing, point_id)
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
    """Update community metadata. Areas and topology have their own routes."""
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
    responses=error_responses(404),
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
    """
    community, _ = await _resolve(session, community_key)

    entry = {"name": payload.name, "topology": payload.topology}
    if payload.location is not None:
        entry["location"] = payload.location.model_dump()
    if payload.geometry is not None:
        entry["geometry"] = payload.geometry

    community.areas = {**(community.areas or {}), area_key: entry}
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
