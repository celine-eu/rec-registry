"""
Community API routes.

Provides:
- List/get communities
- List/get members (with lookup by user_id)
- List/get assets (with lookup by sensor_id)
- Functional lookups (community by member, member by user_id, etc.)
"""

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from celine.rec_registry.db.session import get_session
from celine.rec_registry.db.models import Community, Member, Asset
from celine.rec_registry.core.settings import settings

router = APIRouter(tags=["registry"])


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
    limit: int = Query(default=settings.default_page_size, ge=1, le=settings.max_page_size),
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
    """Get a community by key."""
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")
    
    return {
        "id": str(c.id),
        "key": c.key,
        "name": c.name,
        "description": c.description,
        "areas": c.areas,
        "extra": c.extra,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


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
    limit: int = Query(default=settings.default_page_size, ge=1, le=settings.max_page_size),
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
    """Get a member by key."""
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")
    
    m = await session.scalar(
        select(Member)
        .where(Member.community_id == c.id, Member.key == member_key)
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
    """
    Get a member by their external user_id.
    
    User ID can contain special characters (e.g., POD codes).
    """
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")
    
    m = await session.scalar(
        select(Member)
        .where(Member.community_id == c.id, Member.user_id == user_id)
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
        "extra": m.extra,
    }


# =============================================================================
# Assets
# =============================================================================

@router.get("/communities/{community_key}/assets")
async def list_assets(
    community_key: str,
    session: AsyncSession = Depends(get_session),
    asset_type: str | None = Query(default=None, description="Filter by asset type"),
    owner: str | None = Query(default=None, description="Filter by owner member key"),
    limit: int = Query(default=settings.default_page_size, ge=1, le=settings.max_page_size),
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
    """Get an asset by key."""
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
    """
    Get a meter asset by its sensor_id.
    
    Only returns assets with asset_type='meter'.
    """
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
    limit: int = Query(default=settings.default_page_size, ge=1, le=settings.max_page_size),
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
            "owner_key": m.key,
            "owner_user_id": m.user_id,
        }
        for a, m in rows
    ]
    
    page, next_cursor = _paginate(items, limit, cursor)
    return {"items": page, "next_cursor": next_cursor}


# =============================================================================
# Global Lookups (cross-community)
# =============================================================================

@router.get("/lookup/community-by-user-id/{user_id:path}")
async def lookup_community_by_user_id(
    user_id: str,
    session: AsyncSession = Depends(get_session),
):
    """
    Find which community a user belongs to by their user_id.
    
    Returns community info and member details.
    """
    result = await session.execute(
        select(Member, Community)
        .join(Community, Member.community_id == Community.id)
        .where(Member.user_id == user_id)
    )
    row = result.first()
    
    if row is None:
        raise HTTPException(status_code=404, detail="User not found in any community")
    
    m, c = row
    return {
        "community": {
            "id": str(c.id),
            "key": c.key,
            "name": c.name,
        },
        "member": {
            "id": str(m.id),
            "key": m.key,
            "user_id": m.user_id,
            "name": m.name,
            "role": m.role,
            "status": m.status,
        },
    }


@router.get("/lookup/community-by-sensor-id/{sensor_id:path}")
async def lookup_community_by_sensor_id(
    sensor_id: str,
    session: AsyncSession = Depends(get_session),
):
    """
    Find which community a meter belongs to by its sensor_id.
    
    Returns community info, member details, and asset details.
    """
    result = await session.execute(
        select(Asset, Member, Community)
        .join(Member, Asset.owner_id == Member.id)
        .join(Community, Asset.community_id == Community.id)
        .where(Asset.sensor_id == sensor_id)
    )
    row = result.first()
    
    if row is None:
        raise HTTPException(status_code=404, detail="Sensor not found in any community")
    
    a, m, c = row
    return {
        "community": {
            "id": str(c.id),
            "key": c.key,
            "name": c.name,
        },
        "member": {
            "id": str(m.id),
            "key": m.key,
            "user_id": m.user_id,
            "name": m.name,
        },
        "asset": {
            "id": str(a.id),
            "key": a.key,
            "asset_type": a.asset_type,
            "name": a.name,
            "sensor_id": a.sensor_id,
        },
    }


@router.get("/lookup/member-by-user-id/{user_id:path}")
async def lookup_member_by_user_id(
    user_id: str,
    session: AsyncSession = Depends(get_session),
):
    """
    Global lookup: find a member by user_id across all communities.
    """
    result = await session.execute(
        select(Member, Community)
        .join(Community, Member.community_id == Community.id)
        .where(Member.user_id == user_id)
    )
    row = result.first()
    
    if row is None:
        raise HTTPException(status_code=404, detail="Member not found")
    
    m, c = row
    return {
        "id": str(m.id),
        "key": m.key,
        "user_id": m.user_id,
        "name": m.name,
        "role": m.role,
        "area": m.area,
        "status": m.status,
        "community_key": c.key,
        "community_name": c.name,
    }


@router.get("/lookup/asset-by-sensor-id/{sensor_id:path}")
async def lookup_asset_by_sensor_id(
    sensor_id: str,
    session: AsyncSession = Depends(get_session),
):
    """
    Global lookup: find an asset (meter) by sensor_id across all communities.
    """
    result = await session.execute(
        select(Asset, Member, Community)
        .join(Member, Asset.owner_id == Member.id)
        .join(Community, Asset.community_id == Community.id)
        .where(Asset.sensor_id == sensor_id)
    )
    row = result.first()
    
    if row is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    a, m, c = row
    return {
        "id": str(a.id),
        "key": a.key,
        "asset_type": a.asset_type,
        "name": a.name,
        "sensor_id": a.sensor_id,
        "properties": a.properties,
        "relationships": a.relationships,
        "owner_key": m.key,
        "owner_user_id": m.user_id,
        "community_key": c.key,
        "community_name": c.name,
    }
