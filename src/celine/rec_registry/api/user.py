"""
User self-service API routes (/me).

Provides authenticated users access to their own information:
- Profile from JWT
- Member details
- Community membership
- Own assets and delivery points

Does NOT expose information about other users.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from celine.sdk.auth import JwtUser

from celine.rec_registry.db.session import get_session
from celine.rec_registry.db.models import Community, Member, Asset
from celine.rec_registry.core.middleware import require_user

router = APIRouter(prefix="/user", tags=["me"])


@router.get("")
async def get_me(
    user: JwtUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Get current user's profile and membership information.

    Returns:
    - JWT profile information
    - Community membership (if any)
    - Member details
    - Summary of owned assets
    """
    result = await session.execute(
        select(Member, Community)
        .join(Community, Member.community_id == Community.id)
        .where(Member.user_id == user.sub)
    )
    row = result.first()

    response = {
        "profile": {
            "sub": user.sub,
            "email": user.email,
            "name": user.name,
            "preferred_username": user.preferred_username,
        },
        "membership": None,
    }

    if row:
        member, community = row

        # Count assets by type
        assets_result = await session.execute(
            select(Asset).where(Asset.owner_id == member.id)
        )
        assets = assets_result.scalars().all()

        asset_counts = {}
        for asset in assets:
            asset_counts[asset.asset_type] = asset_counts.get(asset.asset_type, 0) + 1

        response["membership"] = {
            "member": {
                "key": member.key,
                "name": member.name,
                "role": member.role,
                "area": member.area,
                "status": member.status,
            },
            "community": {
                "key": community.key,
                "name": community.name,
                "description": community.description,
            },
            "delivery_points_count": (
                len(member.delivery_points) if member.delivery_points else 0
            ),
            "assets_count": asset_counts,
        }

    return response


@router.get("/member")
async def get_my_member(
    user: JwtUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Get current user's full member details including delivery points.
    """
    member = await session.scalar(select(Member).where(Member.user_id == user.sub))

    if member is None:
        raise HTTPException(
            status_code=404, detail="You are not a member of any community"
        )

    return {
        "key": member.key,
        "user_id": member.user_id,
        "name": member.name,
        "role": member.role,
        "area": member.area,
        "status": member.status,
        "delivery_points": member.delivery_points,
        "extra": member.extra,
        "created_at": member.created_at.isoformat() if member.created_at else None,
        "updated_at": member.updated_at.isoformat() if member.updated_at else None,
    }


@router.get("/community")
async def get_my_community(
    user: JwtUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Get the community the current user belongs to.
    """
    result = await session.execute(
        select(Member, Community)
        .join(Community, Member.community_id == Community.id)
        .where(Member.user_id == user.sub)
    )
    row = result.first()

    if row is None:
        raise HTTPException(
            status_code=404, detail="You are not a member of any community"
        )

    member, community = row

    return {
        "key": community.key,
        "name": community.name,
        "description": community.description,
        "legal": community.legal,
        "links": community.links,
        "contact": community.contact,
        "settings": community.settings,
        "areas": community.areas,
        "topology": community.topology,
        "your_area": member.area,
        "your_role": member.role,
    }


@router.get("/assets")
async def get_my_assets(
    user: JwtUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    asset_type: str | None = Query(default=None, description="Filter by asset type"),
):
    """
    Get current user's assets. Optionally filter by asset_type.
    """
    member = await session.scalar(select(Member).where(Member.user_id == user.sub))

    if member is None:
        raise HTTPException(
            status_code=404, detail="You are not a member of any community"
        )

    query = select(Asset).where(Asset.owner_id == member.id)
    if asset_type:
        query = query.where(Asset.asset_type == asset_type)

    assets = (await session.scalars(query)).all()

    return {
        "items": [
            {
                "key": a.key,
                "asset_type": a.asset_type,
                "name": a.name,
                "sensor_id": a.sensor_id,
                "properties": a.properties,
                "device": a.device,
                "relationships": a.relationships,
            }
            for a in sorted(assets, key=lambda x: x.key)
        ],
        "total": len(assets),
    }


@router.get("/assets/{asset_key}")
async def get_my_asset(
    asset_key: str,
    user: JwtUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Get a specific asset owned by the current user.
    """
    member = await session.scalar(select(Member).where(Member.user_id == user.sub))

    if member is None:
        raise HTTPException(
            status_code=404, detail="You are not a member of any community"
        )

    asset = await session.scalar(
        select(Asset).where(Asset.owner_id == member.id, Asset.key == asset_key)
    )

    if asset is None:
        raise HTTPException(
            status_code=404, detail="Asset not found or not owned by you"
        )

    return {
        "key": asset.key,
        "asset_type": asset.asset_type,
        "name": asset.name,
        "sensor_id": asset.sensor_id,
        "properties": asset.properties,
        "device": asset.device,
        "relationships": asset.relationships,
        "extra": asset.extra,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
    }


@router.get("/delivery-points")
async def get_my_delivery_points(
    user: JwtUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Get current user's delivery points (PODs, CUPS, etc.).
    """
    member = await session.scalar(select(Member).where(Member.user_id == user.sub))

    if member is None:
        raise HTTPException(
            status_code=404, detail="You are not a member of any community"
        )

    return {
        "items": member.delivery_points or [],
        "total": len(member.delivery_points) if member.delivery_points else 0,
    }
