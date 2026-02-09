"""
Community API routes.

Provides:
- List/get communities (with topology, legal, links, contact, settings)
- List/get members (with delivery_points, lookup by user_id)
- List/get assets (with device info, lookup by sensor_id)
- Delivery points lookup
- Topology endpoints
- Global lookups (community by member, member by user_id, etc.)
"""

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from celine.rec_registry.db.session import get_session
from celine.rec_registry.db.models import Community, Member, Asset
from celine.rec_registry.core.settings import settings

router = APIRouter()


# =============================================================================
# Pagination Helper
# =============================================================================


def _paginate(
    items: list[dict[str, Any]],
    limit: int,
    cursor: str | None,
    key_field: str = "key",
) -> tuple[list[dict[str, Any]], str | None]:
    """
    Simple cursor-based pagination.

    Cursor is the last key returned; next page starts after that key.
    """
    if cursor:
        items = [x for x in items if x.get(key_field, "") > cursor]
    items = sorted(items, key=lambda x: x.get(key_field, ""))
    page = items[:limit]
    next_cursor = page[-1][key_field] if len(page) == limit else None
    return page, next_cursor


# =============================================================================
# Communities
# =============================================================================


@router.get("/communities")
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
        {
            "id": str(c.id),
            "key": c.key,
            "name": c.name,
            "description": c.description,
            "areas": c.areas,
        }
        for c in rows
    ]

    page, next_cursor = _paginate(items, limit, cursor)
    return {"items": page, "next_cursor": next_cursor}


@router.get("/communities/{community_key}")
async def get_community(
    community_key: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a community by key with full details."""
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    return {
        "id": str(c.id),
        "key": c.key,
        "name": c.name,
        "description": c.description,
        "legal": c.legal,
        "links": c.links,
        "contact": c.contact,
        "settings": c.settings,
        "areas": c.areas,
        "topology": c.topology,
        "extra": c.extra,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


@router.get("/communities/{community_key}/topology")
async def get_community_topology(
    community_key: str,
    session: AsyncSession = Depends(get_session),
):
    """Get community grid topology."""
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    return {"topology": c.topology or []}


# =============================================================================
# Members
# =============================================================================


@router.get("/communities/{community_key}/members")
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
        {
            "id": str(m.id),
            "key": m.key,
            "user_id": m.user_id,
            "name": m.name,
            "role": m.role,
            "area": m.area,
            "status": m.status,
            "delivery_points_count": len(m.delivery_points) if m.delivery_points else 0,
        }
        for m in rows
    ]

    page, next_cursor = _paginate(items, limit, cursor)
    return {"items": page, "next_cursor": next_cursor}


@router.get("/communities/{community_key}/members/{member_key}")
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

    return {
        "id": str(m.id),
        "key": m.key,
        "user_id": m.user_id,
        "name": m.name,
        "role": m.role,
        "area": m.area,
        "status": m.status,
        "delivery_points": m.delivery_points,
        "extra": m.extra,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


@router.get("/communities/{community_key}/members/by-user-id/{user_id:path}")
async def get_member_by_user_id(
    community_key: str,
    user_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a member by their external user_id (e.g., Keycloak UUID)."""
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    m = await session.scalar(
        select(Member).where(Member.community_id == c.id, Member.user_id == user_id)
    )
    if m is None:
        raise HTTPException(status_code=404, detail="Member not found")

    return {
        "id": str(m.id),
        "key": m.key,
        "user_id": m.user_id,
        "name": m.name,
        "role": m.role,
        "area": m.area,
        "status": m.status,
        "delivery_points": m.delivery_points,
        "extra": m.extra,
    }


@router.get("/communities/{community_key}/members/{member_key}/delivery-points")
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

    return {"delivery_points": m.delivery_points or []}


# =============================================================================
# Delivery Points Lookup
# =============================================================================


@router.get("/communities/{community_key}/delivery-points")
async def list_delivery_points(
    community_key: str,
    session: AsyncSession = Depends(get_session),
    dp_type: str | None = Query(
        default=None, alias="type", description="Filter by type (pod, cups, etc.)"
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

    items = []
    for m in members:
        for dp in m.delivery_points or []:
            # Apply filters
            if dp_type and dp.get("type") != dp_type:
                continue
            if active is not None and dp.get("active", True) != active:
                continue

            items.append(
                {
                    "id": dp.get("id"),
                    "key": dp.get("id"),  # Use id as key for pagination
                    "type": dp.get("type"),
                    "description": dp.get("description"),
                    "address": dp.get("address"),
                    "tariff": dp.get("tariff"),
                    "active": dp.get("active", True),
                    "member_key": m.key,
                    "member_name": m.name,
                }
            )

    page, next_cursor = _paginate(items, limit, cursor)
    return {"items": page, "next_cursor": next_cursor}


@router.get("/communities/{community_key}/delivery-points/by-id/{dp_id:path}")
async def get_delivery_point_by_id(
    community_key: str,
    dp_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Find a delivery point by its ID (POD, CUPS, etc.)."""
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    members = (
        await session.scalars(select(Member).where(Member.community_id == c.id))
    ).all()

    for m in members:
        for dp in m.delivery_points or []:
            if dp.get("id") == dp_id:
                return {
                    "delivery_point": dp,
                    "member": {
                        "key": m.key,
                        "user_id": m.user_id,
                        "name": m.name,
                        "role": m.role,
                    },
                }

    raise HTTPException(status_code=404, detail="Delivery point not found")


# =============================================================================
# Assets
# =============================================================================


@router.get("/communities/{community_key}/assets")
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
        {
            "id": str(a.id),
            "key": a.key,
            "asset_type": a.asset_type,
            "name": a.name,
            "owner_key": m.key,
            "owner_user_id": m.user_id,
            "sensor_id": a.sensor_id,
            "device_type": a.device.get("type") if a.device else None,
        }
        for a, m in rows
    ]

    page, next_cursor = _paginate(items, limit, cursor)
    return {"items": page, "next_cursor": next_cursor}


@router.get("/communities/{community_key}/assets/{asset_key}")
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
    return {
        "id": str(a.id),
        "key": a.key,
        "asset_type": a.asset_type,
        "name": a.name,
        "owner_key": m.key,
        "owner_user_id": m.user_id,
        "sensor_id": a.sensor_id,
        "properties": a.properties,
        "device": a.device,
        "relationships": a.relationships,
        "extra": a.extra,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


@router.get("/communities/{community_key}/assets/by-sensor-id/{sensor_id:path}")
async def get_asset_by_sensor_id(
    community_key: str,
    sensor_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a meter asset by its sensor_id."""
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    result = await session.execute(
        select(Asset, Member)
        .join(Member, Asset.owner_id == Member.id)
        .where(
            Asset.community_id == c.id,
            Asset.sensor_id == sensor_id,
        )
    )
    row = result.first()

    if row is None:
        raise HTTPException(status_code=404, detail="Meter not found")

    a, m = row
    return {
        "id": str(a.id),
        "key": a.key,
        "asset_type": a.asset_type,
        "name": a.name,
        "owner_key": m.key,
        "owner_user_id": m.user_id,
        "sensor_id": a.sensor_id,
        "properties": a.properties,
        "device": a.device,
        "relationships": a.relationships,
    }


# =============================================================================
# Meters (convenience alias for meter assets)
# =============================================================================


@router.get("/communities/{community_key}/meters")
async def list_meters(
    community_key: str,
    session: AsyncSession = Depends(get_session),
    owner: str | None = Query(default=None, description="Filter by owner member key"),
    limit: int = Query(
        default=settings.default_page_size, ge=1, le=settings.max_page_size
    ),
    cursor: str | None = Query(default=None, description="Pagination cursor"),
):
    """List meters in a community (shortcut for assets?asset_type=meter)."""
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
        {
            "id": str(a.id),
            "key": a.key,
            "name": a.name,
            "sensor_id": a.sensor_id,
            "meter_type": a.properties.get("meter_type") if a.properties else None,
            "pod": a.properties.get("pod") if a.properties else None,
            "device": a.device,
            "owner_key": m.key,
            "owner_user_id": m.user_id,
        }
        for a, m in rows
    ]

    page, next_cursor = _paginate(items, limit, cursor)
    return {"items": page, "next_cursor": next_cursor}
