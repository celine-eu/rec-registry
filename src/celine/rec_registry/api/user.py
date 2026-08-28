"""
User self-service API routes (/user).

Provides authenticated users access to their OWN information only:
- Profile from JWT
- Member details
- Community membership
- Own assets and delivery points

Security: Does NOT expose information about other users.
All responses use dedicated User* models that exclude sensitive fields.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from celine.sdk.auth import JwtUser

from celine.rec_registry.db.session import get_session
from celine.rec_registry.db.models import Community, Member, Asset
from celine.rec_registry.core.middleware import require_user
from celine.rec_registry.schemas.models import (
    # User-specific models (no sensitive data leakage)
    UserProfile,
    UserMemberSummary,
    UserCommunitySummary,
    UserMembership,
    UserMeResponse,
    UserMemberDetail,
    UserCommunityDetail,
    UserAsset,
    UserAssetDetail,
    UserAssetsResponse,
    UserDeliveryPointsResponse,
    DeliveryPoint,
    Area,
    TopologyNode,
)

router = APIRouter(prefix="/user", tags=["me"])


@router.get(
    "",
    response_model=UserMeResponse,
)
async def get_me(
    user: JwtUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Get current user's profile and membership summary.
    """
    result = await session.execute(
        select(Member, Community)
        .join(Community, Member.community_id == Community.id)
        .where(Member.user_id == user.get_username())
    )
    row = result.first()

    profile = UserProfile(
        sub=user.sub,
        email=user.email,
        name=user.name,
        preferred_username=user.preferred_username,
    )

    if row is None:
        return UserMeResponse(profile=profile, membership=None)

    member, community = row

    # Count assets by type
    assets_result = await session.execute(
        select(Asset).where(Asset.owner_id == member.id)
    )
    assets = assets_result.scalars().all()

    asset_counts: dict[str, int] = {}
    for asset in assets:
        asset_counts[asset.asset_type] = asset_counts.get(asset.asset_type, 0) + 1

    membership = UserMembership(
        member=UserMemberSummary(
            key=member.key,
            name=member.name,
            role=member.role,
            area=member.area,
            status=member.status,
            did=member.did,
        ),
        community=UserCommunitySummary(
            key=community.key,
            name=community.name,
            description=community.description,
        ),
        delivery_points_count=(
            len(member.delivery_points) if member.delivery_points else 0
        ),
        assets_count=asset_counts,
    )

    return UserMeResponse(profile=profile, membership=membership)


@router.get(
    "/member",
    response_model=UserMemberDetail,
)
async def get_my_member(
    user: JwtUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Get current user's full member details.

    Note: Does not include user_id in response (user already knows it).

    It **does** include `did`, and the two omissions are not the same kind. The
    caller knows the username they authenticated with, so returning it would put
    an identity into one more response body for nothing. They do not know the
    dataspace DID — an onboarding service minted it on their behalf, one step
    after registration — and it is the identifier their consent records are
    written in. Withholding it means a participant cannot see, in the one place
    that is theirs, which dataspace identity is acting for them.
    """
    member = await session.scalar(
        select(Member).where(Member.user_id == user.get_username())
    )

    if member is None:
        raise HTTPException(
            status_code=403, detail="You are not a member of any community"
        )

    return UserMemberDetail(
        key=member.key,
        name=member.name,
        role=member.role,
        area=member.area,
        status=member.status,
        did=member.did,
        delivery_points=[DeliveryPoint(**dp) for dp in (member.delivery_points or [])],
        extra=member.extra or {},
        created_at=member.created_at.isoformat() if member.created_at else None,
        updated_at=member.updated_at.isoformat() if member.updated_at else None,
    )


@router.get(
    "/community",
    response_model=UserCommunityDetail,
)
async def get_my_community(
    user: JwtUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Get the community the current user belongs to.

    Includes user's own area and role for context.
    """
    result = await session.execute(
        select(Member, Community)
        .join(Community, Member.community_id == Community.id)
        .where(Member.user_id == user.get_username())
    )
    row = result.first()

    if row is None:
        raise HTTPException(
            status_code=403, detail="You are not a member of any community"
        )

    member, community = row

    return UserCommunityDetail(
        key=community.key,
        name=community.name,
        description=community.description,
        legal=community.legal or {},
        links=community.links or {},
        contact=community.contact or {},
        settings=community.settings or {},
        areas={k: Area(**v) for k, v in (community.areas or {}).items()},
        topology=[TopologyNode(**n) for n in (community.topology or [])],
        your_area=member.area,
        your_role=member.role,
    )


@router.get(
    "/assets",
    response_model=UserAssetsResponse,
)
async def get_my_assets(
    user: JwtUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    asset_type: str | None = Query(default=None, description="Filter by asset type"),
):
    """
    Get current user's assets.

    Note: Does not include owner info (user already knows it's theirs).
    """
    member = await session.scalar(
        select(Member).where(Member.user_id == user.get_username())
    )

    if member is None:
        raise HTTPException(
            status_code=403, detail="You are not a member of any community"
        )

    query = select(Asset).where(Asset.owner_id == member.id)
    if asset_type:
        query = query.where(Asset.asset_type == asset_type)

    assets = (await session.scalars(query)).all()

    items = [
        UserAsset(
            key=a.key,
            asset_type=a.asset_type,
            name=a.name,
            sensor_id=a.sensor_id,
            properties=a.properties or {},
            device=a.device or {},
            relationships=a.relationships or {},
        )
        for a in sorted(assets, key=lambda x: x.key)
    ]

    return UserAssetsResponse(items=items, total=len(items))


@router.get(
    "/assets/{asset_key}",
    response_model=UserAssetDetail,
)
async def get_my_asset(
    asset_key: str,
    user: JwtUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Get a specific asset owned by the current user.
    """
    member = await session.scalar(
        select(Member).where(Member.user_id == user.get_username())
    )

    if member is None:
        raise HTTPException(
            status_code=403, detail="You are not a member of any community"
        )

    asset = await session.scalar(
        select(Asset).where(Asset.owner_id == member.id, Asset.key == asset_key)
    )

    if asset is None:
        raise HTTPException(
            status_code=404, detail="Asset not found or not owned by you"
        )

    return UserAssetDetail(
        key=asset.key,
        asset_type=asset.asset_type,
        name=asset.name,
        sensor_id=asset.sensor_id,
        properties=asset.properties or {},
        device=asset.device or {},
        relationships=asset.relationships or {},
        extra=asset.extra or {},
        created_at=asset.created_at.isoformat() if asset.created_at else None,
        updated_at=asset.updated_at.isoformat() if asset.updated_at else None,
    )


@router.get(
    "/delivery-points",
    response_model=UserDeliveryPointsResponse,
)
async def get_my_delivery_points(
    user: JwtUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Get current user's delivery points.
    """
    member = await session.scalar(
        select(Member).where(Member.user_id == user.get_username())
    )

    if member is None:
        raise HTTPException(
            status_code=403, detail="You are not a member of any community"
        )

    items = [DeliveryPoint(**dp) for dp in (member.delivery_points or [])]

    return UserDeliveryPointsResponse(items=items, total=len(items))
