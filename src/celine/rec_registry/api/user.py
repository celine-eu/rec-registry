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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from celine.sdk.audit import audit_denied
from celine.sdk.auth import JwtUser

from celine.rec_registry.db.session import get_session
from celine.rec_registry.db.models import Community, Member, Asset
from celine.rec_registry.core.errors import ErrorCode, RegistryError, error_responses
from celine.rec_registry.core.middleware import require_user
from celine.rec_registry.services.sensors import ACTIVE
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


def _not_a_member(user: JwtUser, request: Request) -> RegistryError:
    """``403 not_a_member``: the caller's username names no member (REQ-0047).

    Coded so a client — dataset-api's row filter among them — tells "this
    person is not a member" from every other refusal by ``code`` rather than
    by the sentence (REQ-0073). Recorded on ``celine.audit`` with the caller
    (REQ-0091).
    """
    audit_denied(
        "rec-registry.user.read",
        caller=user,
        reason=ErrorCode.NOT_A_MEMBER.value,
        request=request,
    )
    return RegistryError(
        403, "You are not a member of any community", ErrorCode.NOT_A_MEMBER
    )


def _ambiguous_member(user: JwtUser, request: Request) -> RegistryError:
    """``409 ambiguous_member``: more than one active member answers (REQ-0095)."""
    audit_denied(
        "rec-registry.user.read",
        caller=user,
        reason=ErrorCode.AMBIGUOUS_MEMBER.value,
        request=request,
    )
    return RegistryError(
        409,
        "You are an active member of more than one community, and this request "
        "does not say which one",
        ErrorCode.AMBIGUOUS_MEMBER,
    )


async def _resolve_member(
    session: AsyncSession, user: JwtUser, request: Request
) -> tuple[Member, Community] | None:
    """The caller's own member row, and its community — or ``None``.

    **Only an active member answers (REQ-0094).** A released (`inactive`),
    `suspended` or `pending` row is the same as no row: it holds no sensor and
    no delivery point (REQ-0069, REQ-0085), and dataset-api builds its live
    row filter from what these routes return. Answering from an inactive row
    kept a released member reading their old meters — and, once the POD was
    given to somebody else, the new occupant's.

    **More than one active row is narrowed by the token, never picked
    (REQ-0095).** `user_id` is unique per community only, so one username can
    be active in two. The token's `organization` aliases are community keys;
    exactly one active row inside them is the answer. Anything else — none of
    them in the token, or still two — is ``409 ambiguous_member``: the first
    row of an unordered query is whichever the planner returned.
    """
    rows = (
        await session.execute(
            select(Member, Community)
            .join(Community, Member.community_id == Community.id)
            .where(Member.user_id == user.get_username(), Member.status == ACTIVE)
        )
    ).all()
    if len(rows) == 0:
        return None
    if len(rows) == 1:
        return tuple(rows[0])

    aliases = {org.alias for org in user.organizations}
    in_token = [row for row in rows if row[1].key in aliases]
    if len(in_token) == 1:
        return tuple(in_token[0])
    raise _ambiguous_member(user, request)


@router.get(
    "",
    responses=error_responses(409),
    response_model=UserMeResponse,
)
async def get_me(
    request: Request,
    user: JwtUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Get current user's profile and membership summary.
    """
    row = await _resolve_member(session, user, request)

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
    responses=error_responses(403, 409),
    response_model=UserMemberDetail,
)
async def get_my_member(
    request: Request,
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
    row = await _resolve_member(session, user, request)

    if row is None:
        raise _not_a_member(user, request)
    member, _ = row

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
    responses=error_responses(403, 409),
    response_model=UserCommunityDetail,
)
async def get_my_community(
    request: Request,
    user: JwtUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Get the community the current user belongs to.

    Includes user's own area and role for context.
    """
    row = await _resolve_member(session, user, request)

    if row is None:
        raise _not_a_member(user, request)

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
    responses=error_responses(403, 409),
    response_model=UserAssetsResponse,
)
async def get_my_assets(
    request: Request,
    user: JwtUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    asset_type: str | None = Query(default=None, description="Filter by asset type"),
):
    """
    Get current user's assets.

    Note: Does not include owner info (user already knows it's theirs).
    """
    row = await _resolve_member(session, user, request)

    if row is None:
        raise _not_a_member(user, request)
    member, _ = row

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
    responses=error_responses(403, 409),
    response_model=UserAssetDetail,
)
async def get_my_asset(
    asset_key: str,
    request: Request,
    user: JwtUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Get a specific asset owned by the current user.
    """
    row = await _resolve_member(session, user, request)

    if row is None:
        raise _not_a_member(user, request)
    member, _ = row

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
    responses=error_responses(403, 409),
    response_model=UserDeliveryPointsResponse,
)
async def get_my_delivery_points(
    request: Request,
    user: JwtUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Get current user's delivery points.
    """
    row = await _resolve_member(session, user, request)

    if row is None:
        raise _not_a_member(user, request)
    member, _ = row

    items = [DeliveryPoint(**dp) for dp in (member.delivery_points or [])]

    return UserDeliveryPointsResponse(items=items, total=len(items))
