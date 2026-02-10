"""
Community API routes (Admin).

Provides:
- List/get communities
- List/get members
- List/get assets
- Delivery points lookup
- Meters convenience endpoint
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from celine.rec_registry.db.session import get_session
from celine.rec_registry.db.models import Community, Member, Asset
from celine.rec_registry.core.settings import settings
from celine.rec_registry.schemas.models import (
    # Community
    CommunityListItem,
    CommunityDetail,
    TopologyResponse,
    PaginatedResponse,
    # Member
    MemberListItem,
    MemberDetail,
    DeliveryPointsResponse,
    DeliveryPoint,
    # Delivery Points
    DeliveryPointWithOwner,
    DeliveryPointLookup,
    MemberRef,
    # Assets
    AssetListItem,
    AssetDetail,
    MeterListItem,
    Area,
    TopologyNode,
)

router = APIRouter()


# =============================================================================
# Communities
# =============================================================================


@router.get(
    "/communities",
    response_model=PaginatedResponse[CommunityListItem],
)
async def list_communities(
    session: AsyncSession = Depends(get_session),
    key: str | None = Query(default=None, description="Filter by community key"),
    limit: int = Query(
        default=settings.default_page_size, ge=1, le=settings.max_page_size
    ),
    cursor: str | None = Query(default=None, description="Pagination cursor"),
):
    """List all communities."""
    q = select(Community)
    if key:
        q = q.where(Community.key == key)

    rows = (await session.scalars(q)).all()

    items = [
        CommunityListItem(
            id=str(c.id),
            key=c.key,
            name=c.name,
            description=c.description,
            areas={k: Area(**v) for k, v in (c.areas or {}).items()},
        )
        for c in rows
    ]

    # Paginate
    if cursor:
        items = [x for x in items if x.key > cursor]
    items = sorted(items, key=lambda x: x.key)
    page = items[:limit]
    next_cursor = page[-1].key if len(page) == limit else None

    return PaginatedResponse(items=page, next_cursor=next_cursor)


@router.get(
    "/communities/{community_key}",
    response_model=CommunityDetail,
)
async def get_community(
    community_key: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a community by key with full details."""
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    return CommunityDetail(
        id=str(c.id),
        key=c.key,
        name=c.name,
        description=c.description,
        legal=c.legal or {},
        links=c.links or {},
        contact=c.contact or {},
        settings=c.settings or {},
        areas={k: Area(**v) for k, v in (c.areas or {}).items()},
        topology=[TopologyNode(**n) for n in (c.topology or [])],
        extra=c.extra or {},
        created_at=c.created_at.isoformat() if c.created_at else None,
        updated_at=c.updated_at.isoformat() if c.updated_at else None,
    )


@router.get(
    "/communities/{community_key}/topology",
    response_model=TopologyResponse,
)
async def get_community_topology(
    community_key: str,
    session: AsyncSession = Depends(get_session),
):
    """Get community grid topology."""
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    return TopologyResponse(topology=[TopologyNode(**n) for n in (c.topology or [])])


# =============================================================================
# Members
# =============================================================================


@router.get(
    "/communities/{community_key}/members",
    response_model=PaginatedResponse[MemberListItem],
)
async def list_members(
    community_key: str,
    session: AsyncSession = Depends(get_session),
    role: str | None = Query(default=None, description="Filter by role"),
    status: str | None = Query(default=None, description="Filter by status"),
    area: str | None = Query(default=None, description="Filter by area"),
    limit: int = Query(
        default=settings.default_page_size, ge=1, le=settings.max_page_size
    ),
    cursor: str | None = Query(default=None, description="Pagination cursor"),
):
    """List members of a community."""
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    q = select(Member).where(Member.community_id == c.id)
    if role:
        q = q.where(Member.role == role)
    if status:
        q = q.where(Member.status == status)
    if area:
        q = q.where(Member.area == area)

    rows = (await session.scalars(q)).all()

    items = [
        MemberListItem(
            id=str(m.id),
            key=m.key,
            user_id=m.user_id,
            name=m.name,
            role=m.role,
            area=m.area,
            status=m.status,
            delivery_points_count=len(m.delivery_points) if m.delivery_points else 0,
        )
        for m in rows
    ]

    # Paginate
    if cursor:
        items = [x for x in items if x.key > cursor]
    items = sorted(items, key=lambda x: x.key)
    page = items[:limit]
    next_cursor = page[-1].key if len(page) == limit else None

    return PaginatedResponse(items=page, next_cursor=next_cursor)


@router.get(
    "/communities/{community_key}/members/{member_key}",
    response_model=MemberDetail,
)
async def get_member(
    community_key: str,
    member_key: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a member by key with full details."""
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    m = await session.scalar(
        select(Member).where(Member.community_id == c.id, Member.key == member_key)
    )
    if m is None:
        raise HTTPException(status_code=404, detail="Member not found")

    return MemberDetail(
        id=str(m.id),
        key=m.key,
        user_id=m.user_id,
        name=m.name,
        role=m.role,
        area=m.area,
        status=m.status,
        delivery_points=[DeliveryPoint(**dp) for dp in (m.delivery_points or [])],
        extra=m.extra or {},
        created_at=m.created_at.isoformat() if m.created_at else None,
        updated_at=m.updated_at.isoformat() if m.updated_at else None,
    )


@router.get(
    "/communities/{community_key}/members/by-user-id/{user_id:path}",
    response_model=MemberDetail,
)
async def get_member_by_user_id(
    community_key: str,
    user_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a member by their external user_id."""
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    m = await session.scalar(
        select(Member).where(Member.community_id == c.id, Member.user_id == user_id)
    )
    if m is None:
        raise HTTPException(status_code=404, detail="Member not found")

    return MemberDetail(
        id=str(m.id),
        key=m.key,
        user_id=m.user_id,
        name=m.name,
        role=m.role,
        area=m.area,
        status=m.status,
        delivery_points=[DeliveryPoint(**dp) for dp in (m.delivery_points or [])],
        extra=m.extra or {},
        created_at=m.created_at.isoformat() if m.created_at else None,
        updated_at=m.updated_at.isoformat() if m.updated_at else None,
    )


@router.get(
    "/communities/{community_key}/members/{member_key}/delivery-points",
    response_model=DeliveryPointsResponse,
)
async def get_member_delivery_points(
    community_key: str,
    member_key: str,
    session: AsyncSession = Depends(get_session),
):
    """Get delivery points for a member."""
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    m = await session.scalar(
        select(Member).where(Member.community_id == c.id, Member.key == member_key)
    )
    if m is None:
        raise HTTPException(status_code=404, detail="Member not found")

    return DeliveryPointsResponse(
        delivery_points=[DeliveryPoint(**dp) for dp in (m.delivery_points or [])]
    )


# =============================================================================
# Delivery Points
# =============================================================================


@router.get(
    "/communities/{community_key}/delivery-points",
    response_model=PaginatedResponse[DeliveryPointWithOwner],
)
async def list_delivery_points(
    community_key: str,
    session: AsyncSession = Depends(get_session),
    dp_type: str | None = Query(
        default=None, alias="type", description="Filter by type"
    ),
    active: bool | None = Query(default=None, description="Filter by active status"),
    limit: int = Query(
        default=settings.default_page_size, ge=1, le=settings.max_page_size
    ),
    cursor: str | None = Query(default=None, description="Pagination cursor"),
):
    """List all delivery points in a community."""
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    members = (
        await session.scalars(select(Member).where(Member.community_id == c.id))
    ).all()

    items: list[DeliveryPointWithOwner] = []
    for m in members:
        for dp in m.delivery_points or []:
            if dp_type and dp.get("type") != dp_type:
                continue
            if active is not None and dp.get("active", True) != active:
                continue

            items.append(
                DeliveryPointWithOwner(
                    id=dp.get("id", ""),
                    key=dp.get("id", ""),
                    type=dp.get("type", ""),
                    description=dp.get("description"),
                    address=dp.get("address"),
                    tariff=dp.get("tariff"),
                    active=dp.get("active", True),
                    member_key=m.key,
                    member_name=m.name,
                )
            )

    # Paginate
    if cursor:
        items = [x for x in items if x.key > cursor]
    items = sorted(items, key=lambda x: x.key)
    page = items[:limit]
    next_cursor = page[-1].key if len(page) == limit else None

    return PaginatedResponse(items=page, next_cursor=next_cursor)


@router.get(
    "/communities/{community_key}/delivery-points/by-id/{dp_id:path}",
    response_model=DeliveryPointLookup,
)
async def get_delivery_point_by_id(
    community_key: str,
    dp_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Find a delivery point by its ID."""
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    members = (
        await session.scalars(select(Member).where(Member.community_id == c.id))
    ).all()

    for m in members:
        for dp in m.delivery_points or []:
            if dp.get("id") == dp_id:
                return DeliveryPointLookup(
                    delivery_point=DeliveryPoint(**dp),
                    member=MemberRef(
                        key=m.key,
                        user_id=m.user_id,
                        name=m.name,
                        role=m.role,
                    ),
                )

    raise HTTPException(status_code=404, detail="Delivery point not found")


# =============================================================================
# Assets
# =============================================================================


@router.get(
    "/communities/{community_key}/assets",
    response_model=PaginatedResponse[AssetListItem],
)
async def list_assets(
    community_key: str,
    session: AsyncSession = Depends(get_session),
    asset_type: str | None = Query(default=None, description="Filter by asset type"),
    owner: str | None = Query(default=None, description="Filter by owner member key"),
    limit: int = Query(
        default=settings.default_page_size, ge=1, le=settings.max_page_size
    ),
    cursor: str | None = Query(default=None, description="Pagination cursor"),
):
    """List assets in a community."""
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    q = (
        select(Asset, Member)
        .join(Member, Asset.owner_id == Member.id)
        .where(Asset.community_id == c.id)
    )
    if asset_type:
        q = q.where(Asset.asset_type == asset_type)
    if owner:
        q = q.where(Member.key == owner)

    rows = (await session.execute(q)).all()

    items = [
        AssetListItem(
            id=str(a.id),
            key=a.key,
            asset_type=a.asset_type,
            name=a.name,
            owner_key=m.key,
            owner_user_id=m.user_id,
            sensor_id=a.sensor_id,
            device_type=a.device.get("type") if a.device else None,
        )
        for a, m in rows
    ]

    # Paginate
    if cursor:
        items = [x for x in items if x.key > cursor]
    items = sorted(items, key=lambda x: x.key)
    page = items[:limit]
    next_cursor = page[-1].key if len(page) == limit else None

    return PaginatedResponse(items=page, next_cursor=next_cursor)


@router.get(
    "/communities/{community_key}/assets/{asset_key}",
    response_model=AssetDetail,
)
async def get_asset(
    community_key: str,
    asset_key: str,
    session: AsyncSession = Depends(get_session),
):
    """Get an asset by key with full details."""
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    result = await session.execute(
        select(Asset, Member)
        .join(Member, Asset.owner_id == Member.id)
        .where(Asset.community_id == c.id, Asset.key == asset_key)
    )
    row = result.first()

    if row is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    a, m = row
    return AssetDetail(
        id=str(a.id),
        key=a.key,
        asset_type=a.asset_type,
        name=a.name,
        owner_key=m.key,
        owner_user_id=m.user_id,
        sensor_id=a.sensor_id,
        properties=a.properties or {},
        device=a.device or {},
        relationships=a.relationships or {},
        extra=a.extra or {},
        created_at=a.created_at.isoformat() if a.created_at else None,
        updated_at=a.updated_at.isoformat() if a.updated_at else None,
    )


@router.get(
    "/communities/{community_key}/assets/by-sensor-id/{sensor_id:path}",
    response_model=AssetDetail,
)
async def get_asset_by_sensor_id(
    community_key: str,
    sensor_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get an asset by its sensor_id."""
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    result = await session.execute(
        select(Asset, Member)
        .join(Member, Asset.owner_id == Member.id)
        .where(Asset.community_id == c.id, Asset.sensor_id == sensor_id)
    )
    row = result.first()

    if row is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    a, m = row
    return AssetDetail(
        id=str(a.id),
        key=a.key,
        asset_type=a.asset_type,
        name=a.name,
        owner_key=m.key,
        owner_user_id=m.user_id,
        sensor_id=a.sensor_id,
        properties=a.properties or {},
        device=a.device or {},
        relationships=a.relationships or {},
        extra=a.extra or {},
        created_at=a.created_at.isoformat() if a.created_at else None,
        updated_at=a.updated_at.isoformat() if a.updated_at else None,
    )


# =============================================================================
# Meters (convenience)
# =============================================================================


@router.get(
    "/communities/{community_key}/meters",
    response_model=PaginatedResponse[MeterListItem],
)
async def list_meters(
    community_key: str,
    session: AsyncSession = Depends(get_session),
    owner: str | None = Query(default=None, description="Filter by owner member key"),
    limit: int = Query(
        default=settings.default_page_size, ge=1, le=settings.max_page_size
    ),
    cursor: str | None = Query(default=None, description="Pagination cursor"),
):
    """List meters in a community."""
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    q = (
        select(Asset, Member)
        .join(Member, Asset.owner_id == Member.id)
        .where(Asset.community_id == c.id, Asset.asset_type == "meter")
    )
    if owner:
        q = q.where(Member.key == owner)

    rows = (await session.execute(q)).all()

    items = [
        MeterListItem(
            id=str(a.id),
            key=a.key,
            name=a.name,
            sensor_id=a.sensor_id,
            meter_type=a.properties.get("meter_type") if a.properties else None,
            pod=a.properties.get("pod") if a.properties else None,
            device=a.device or {},
            owner_key=m.key,
            owner_user_id=m.user_id,
        )
        for a, m in rows
    ]

    # Paginate
    if cursor:
        items = [x for x in items if x.key > cursor]
    items = sorted(items, key=lambda x: x.key)
    page = items[:limit]
    next_cursor = page[-1].key if len(page) == limit else None

    return PaginatedResponse(items=page, next_cursor=next_cursor)
