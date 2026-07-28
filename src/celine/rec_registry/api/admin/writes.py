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
from sqlalchemy.ext.asyncio import AsyncSession

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
    AssetUpsert,
    CommunityDetail,
    CommunityPatch,
    DeletionReport,
    DeliveryPoint,
    DeliveryPointsResponse,
    MemberCreate,
    MemberDetail,
    MemberPatch,
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

# The lifecycle `Member.status` has always documented but nothing could drive.
MEMBER_STATUSES = ("pending", "active", "suspended", "inactive")


def _member_detail(member: Member) -> MemberDetail:
    return MemberDetail(
        id=str(member.id),
        key=member.key,
        user_id=member.user_id,
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
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# =============================================================================
# Members
# =============================================================================


@router.post(
    "/communities/{community_key}/members",
    response_model=MemberDetail,
    status_code=201,
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
    """
    community, _ = await _resolve(session, community_key)

    if payload.status not in MEMBER_STATUSES:
        raise HTTPException(
            422, f"status must be one of {', '.join(MEMBER_STATUSES)}"
        )

    member_in = payload.model_copy(update={"key": None})
    try:
        member, warnings = await member_service.create_member(
            session, community, member_in, key=payload.key
        )
    except member_service.MemberConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await session.commit()
    await session.refresh(member)

    detail = _member_detail(member)
    if warnings:
        detail.extra = {**detail.extra, "import_warnings": warnings}
    return detail


@router.patch(
    "/communities/{community_key}/members/{member_key}",
    response_model=MemberDetail,
)
async def patch_member(
    community_key: str,
    member_key: str,
    payload: MemberPatch,
    session: AsyncSession = Depends(get_session),
):
    """Partially update a member. Absent fields are left alone."""
    community, member = await _resolve(session, community_key, member_key)

    patch = payload.model_dump(exclude_unset=True)
    if "status" in patch and patch["status"] not in MEMBER_STATUSES:
        raise HTTPException(
            422, f"status must be one of {', '.join(MEMBER_STATUSES)}"
        )

    if "user_id" in patch and patch["user_id"]:
        clash = await session.scalar(
            select(Member).where(
                Member.community_id == community.id,
                Member.user_id == patch["user_id"],
                Member.key != member.key,
            )
        )
        if clash is not None:
            raise HTTPException(
                409,
                f"user_id {patch['user_id']!r} already belongs to member "
                f"{clash.key!r}",
            )

    await member_service.apply_member_patch(member, patch)
    await session.commit()
    await session.refresh(member)
    return _member_detail(member)


@router.post(
    "/communities/{community_key}/members/{member_key}/status",
    response_model=MemberDetail,
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
    """
    _, member = await _resolve(session, community_key, member_key)

    if payload.status not in MEMBER_STATUSES:
        raise HTTPException(
            422, f"status must be one of {', '.join(MEMBER_STATUSES)}"
        )

    member.status = payload.status
    if payload.reason:
        member.extra = {**(member.extra or {}), "status_reason": payload.reason}

    await session.commit()
    await session.refresh(member)
    return _member_detail(member)


@router.delete(
    "/communities/{community_key}/members/{member_key}",
    response_model=DeletionReport,
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
    status_code=200,
)
async def upsert_asset(
    community_key: str,
    member_key: str,
    asset_key: str,
    payload: AssetUpsert,
    session: AsyncSession = Depends(get_session),
):
    """Create or replace one asset, leaving the member's other assets alone."""
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

    asset = await member_service.upsert_asset(
        session,
        community=community,
        member=member,
        asset_key=asset_key,
        asset_type=payload.asset_type,
        payload=validated,
    )
    await session.commit()
    await session.refresh(asset)

    return {
        "id": str(asset.id),
        "key": asset.key,
        "asset_type": asset.asset_type,
        "name": asset.name,
        "sensor_id": asset.sensor_id,
        "properties": asset.properties or {},
        "device": asset.device or {},
        "relationships": asset.relationships or {},
    }


@router.delete(
    "/communities/{community_key}/members/{member_key}/assets/{asset_key}",
    status_code=204,
)
async def delete_asset(
    community_key: str,
    member_key: str,
    asset_key: str,
    session: AsyncSession = Depends(get_session),
):
    """Remove one asset. Assets carry no history of their own, so this is a
    real delete — unlike a member, whose removal would cascade."""
    community, member = await _resolve(session, community_key, member_key)

    asset = await session.scalar(
        select(Asset).where(
            Asset.community_id == community.id,
            Asset.owner_id == member.id,
            Asset.key == asset_key,
        )
    )
    if asset is None:
        raise HTTPException(404, f"Asset {asset_key!r} not found")

    await session.delete(asset)
    await session.commit()
    return Response(status_code=204)


# =============================================================================
# Community
# =============================================================================


@router.patch("/communities/{community_key}", response_model=CommunityDetail)
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

    areas = community.areas or {}
    if area_key not in areas:
        raise HTTPException(404, f"Area {area_key!r} not found")

    in_use = await session.scalar(
        select(func.count())
        .select_from(Member)
        .where(Member.community_id == community.id, Member.area == area_key)
    )
    if in_use:
        raise HTTPException(
            409,
            f"Area {area_key!r} is still referenced by {in_use} member(s); "
            "move them first",
        )

    community.areas = {k: v for k, v in areas.items() if k != area_key}
    await session.commit()

    return await patch_community(community_key, CommunityPatch(), session)
