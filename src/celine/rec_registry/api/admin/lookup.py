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
from sqlalchemy.orm import selectinload

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
# Global Lookups (cross-community)
# =============================================================================


@router.get("/lookup/community-by-user-id/{user_id:path}")
async def lookup_community_by_user_id(
    user_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Find which community a user belongs to by their user_id."""
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
    """Find which community a meter belongs to by its sensor_id."""
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


@router.get("/lookup/community-by-delivery-point/{dp_id:path}")
async def lookup_community_by_delivery_point(
    dp_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Find which community a delivery point belongs to by its ID."""
    # Query all members and search for matching delivery point
    result = await session.execute(
        select(Member, Community).join(Community, Member.community_id == Community.id)
    )

    for m, c in result.all():
        for dp in m.delivery_points or []:
            if dp.get("id") == dp_id:
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
                    },
                    "delivery_point": dp,
                }

    raise HTTPException(
        status_code=404, detail="Delivery point not found in any community"
    )


@router.get("/lookup/member-by-user-id/{user_id:path}")
async def lookup_member_by_user_id(
    user_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Global lookup: find a member by user_id across all communities."""
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
        "delivery_points": m.delivery_points,
        "community_key": c.key,
        "community_name": c.name,
    }


@router.get("/lookup/asset-by-sensor-id/{sensor_id:path}")
async def lookup_asset_by_sensor_id(
    sensor_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Global lookup: find an asset (meter) by sensor_id across all communities."""
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
        "device": a.device,
        "relationships": a.relationships,
        "owner_key": m.key,
        "owner_user_id": m.user_id,
        "community_key": c.key,
        "community_name": c.name,
    }
