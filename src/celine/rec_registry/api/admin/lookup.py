"""
Global lookup API routes (Admin).

Provides cross-community lookups:
- Find community by user_id
- Find community by sensor_id
- Find community by delivery point
- Find member by user_id
- Find asset by sensor_id
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from celine.rec_registry.db.session import get_session
from celine.rec_registry.db.models import Community, Member, Asset
from celine.rec_registry.schemas.models import (
    CommunityRef,
    MemberRef,
    MemberInCommunity,
    AssetRef,
    DeliveryPoint,
    LookupByUserIdResponse,
    LookupBySensorIdResponse,
    LookupByDeliveryPointResponse,
    GlobalMemberLookup,
    GlobalAssetLookup,
)

router = APIRouter()


# =============================================================================
# Global Lookups
# =============================================================================


@router.get(
    "/lookup/community-by-user-id/{user_id:path}",
    response_model=LookupByUserIdResponse,
)
async def lookup_community_by_user_id(
    user_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Find which community a user belongs to."""
    result = await session.execute(
        select(Member, Community)
        .join(Community, Member.community_id == Community.id)
        .where(Member.user_id == user_id)
    )
    row = result.first()

    if row is None:
        raise HTTPException(status_code=404, detail="User not found in any community")

    m, c = row
    return LookupByUserIdResponse(
        community=CommunityRef(
            id=str(c.id),
            key=c.key,
            name=c.name,
        ),
        member=MemberInCommunity(
            id=str(m.id),
            key=m.key,
            user_id=m.user_id,
            name=m.name,
            role=m.role,
            status=m.status,
        ),
    )


@router.get(
    "/lookup/community-by-sensor-id/{sensor_id:path}",
    response_model=LookupBySensorIdResponse,
)
async def lookup_community_by_sensor_id(
    sensor_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Find which community a meter belongs to."""
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
    return LookupBySensorIdResponse(
        community=CommunityRef(
            id=str(c.id),
            key=c.key,
            name=c.name,
        ),
        member=MemberInCommunity(
            id=str(m.id),
            key=m.key,
            user_id=m.user_id,
            name=m.name,
            role=m.role,
            status=m.status,
        ),
        asset=AssetRef(
            id=str(a.id),
            key=a.key,
            asset_type=a.asset_type,
            name=a.name,
            sensor_id=a.sensor_id,
        ),
    )


@router.get(
    "/lookup/community-by-delivery-point/{dp_id:path}",
    response_model=LookupByDeliveryPointResponse,
)
async def lookup_community_by_delivery_point(
    dp_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Find which community a delivery point belongs to."""
    result = await session.execute(
        select(Member, Community).join(Community, Member.community_id == Community.id)
    )

    for m, c in result.all():
        for dp in m.delivery_points or []:
            if dp.get("id") == dp_id:
                return LookupByDeliveryPointResponse(
                    community=CommunityRef(
                        id=str(c.id),
                        key=c.key,
                        name=c.name,
                    ),
                    member=MemberRef(
                        key=m.key,
                        user_id=m.user_id,
                        name=m.name,
                        role=m.role,
                    ),
                    delivery_point=DeliveryPoint(**dp),
                )

    raise HTTPException(
        status_code=404, detail="Delivery point not found in any community"
    )


@router.get(
    "/lookup/member-by-user-id/{user_id:path}",
    response_model=GlobalMemberLookup,
)
async def lookup_member_by_user_id(
    user_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Find a member by user_id across all communities."""
    result = await session.execute(
        select(Member, Community)
        .join(Community, Member.community_id == Community.id)
        .where(Member.user_id == user_id)
    )
    row = result.first()

    if row is None:
        raise HTTPException(status_code=404, detail="Member not found")

    m, c = row
    return GlobalMemberLookup(
        id=str(m.id),
        key=m.key,
        user_id=m.user_id,
        name=m.name,
        role=m.role,
        area=m.area,
        status=m.status,
        delivery_points=[DeliveryPoint(**dp) for dp in (m.delivery_points or [])],
        community_key=c.key,
        community_name=c.name,
    )


@router.get(
    "/lookup/asset-by-sensor-id/{sensor_id:path}",
    response_model=GlobalAssetLookup,
)
async def lookup_asset_by_sensor_id(
    sensor_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Find an asset by sensor_id across all communities."""
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
    return GlobalAssetLookup(
        id=str(a.id),
        key=a.key,
        asset_type=a.asset_type,
        name=a.name,
        sensor_id=a.sensor_id,
        properties=a.properties or {},
        device=a.device or {},
        relationships=a.relationships or {},
        owner_key=m.key,
        owner_user_id=m.user_id,
        community_key=c.key,
        community_name=c.name,
    )
