"""
Global lookup API routes (Admin).

Provides cross-community lookups:
- Find community by user_id
- Find community by sensor_id
- Find community by delivery point
- Find member by user_id
- Find asset by sensor_id
- Find assets owned by a set of members
- Find members holding a set of dataspace DIDs
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from celine.rec_registry.core.errors import ErrorCode, RegistryError, error_responses
from celine.rec_registry.db.session import get_session
from celine.rec_registry.db.models import Community, Member, Asset
from celine.rec_registry.services.sensors import ACTIVE
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
    DidsBatchRequest,
    SensorIdsBatchRequest,
    UserIdsBatchRequest,
)

router = APIRouter()


# Every lookup below that starts from a person or a device answers from the
# **active** member only (REQ-0097 – REQ-0099). Release leaves the row
# `inactive`, with its `user_id`, its meters and its delivery points; answering
# from it attributed a POD's new occupant to the person who left, and handed a
# released member's old meter to anything joining on the answer. More than one
# active match is refused, never picked: the first row of an unordered query is
# whichever the planner returned.


def _ambiguous() -> RegistryError:
    """``409 ambiguous_member``, naming nobody (REQ-0098, REQ-0099)."""
    return RegistryError(
        409,
        "More than one active member answers this lookup",
        ErrorCode.AMBIGUOUS_MEMBER,
    )


def _the_one(rows):
    """The single row, ``None`` for none, ``409`` for more than one."""
    if len(rows) > 1:
        raise _ambiguous()
    return rows[0] if rows else None


# =============================================================================
# Global Lookups
# =============================================================================

@router.get(
    "/lookup/community-by-user-id/{user_id:path}",
    operation_id="lookup_community_by_user_id",
    response_model=LookupByUserIdResponse,
    responses=error_responses(409),
)
async def lookup_community_by_user_id(
    user_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Find which community a user is an active member of (REQ-0098)."""
    result = await session.execute(
        select(Member, Community)
        .join(Community, Member.community_id == Community.id)
        .where(Member.user_id == user_id, Member.status == ACTIVE)
    )
    row = _the_one(result.all())

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
    operation_id="lookup_community_by_sensor_id",
    response_model=LookupBySensorIdResponse,
    responses=error_responses(409),
)
async def lookup_community_by_sensor_id(
    sensor_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Find which community a meter belongs to, through its active owner (REQ-0099)."""
    result = await session.execute(
        select(Asset, Member, Community)
        .join(Member, Asset.owner_id == Member.id)
        .join(Community, Asset.community_id == Community.id)
        .where(Asset.sensor_id == sensor_id, Member.status == ACTIVE)
    )
    row = _the_one(result.all())

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
    operation_id="lookup_community_by_delivery_point",
    response_model=LookupByDeliveryPointResponse,
    responses=error_responses(409),
)
async def lookup_community_by_delivery_point(
    dp_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Find which community a delivery point belongs to, through its active
    holder (REQ-0099)."""
    result = await session.execute(
        select(Member, Community)
        .join(Community, Member.community_id == Community.id)
        .where(Member.status == ACTIVE)
    )

    matches = [
        (m, c, dp)
        for m, c in result.all()
        for dp in m.delivery_points or []
        if dp.get("id") == dp_id
    ]
    match = _the_one(matches)
    if match is None:
        raise HTTPException(
            status_code=404, detail="Delivery point not found in any community"
        )

    m, c, dp = match
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


@router.get(
    "/lookup/member-by-user-id/{user_id:path}",
    operation_id="lookup_member_by_user_id",
    response_model=GlobalMemberLookup,
    responses=error_responses(409),
)
async def lookup_member_by_user_id(
    user_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Find the active member with this user_id, across all communities (REQ-0098)."""
    result = await session.execute(
        select(Member, Community)
        .join(Community, Member.community_id == Community.id)
        .where(Member.user_id == user_id, Member.status == ACTIVE)
    )
    row = _the_one(result.all())

    if row is None:
        raise HTTPException(status_code=404, detail="Member not found")

    m, c = row
    return GlobalMemberLookup(
        id=str(m.id),
        key=m.key,
        user_id=m.user_id,
        did=m.did,
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
    operation_id="lookup_asset_by_sensor_id",
    response_model=GlobalAssetLookup,
    responses=error_responses(409),
)
async def lookup_asset_by_sensor_id(
    sensor_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Find the asset an active member holds under this sensor_id (REQ-0099)."""
    result = await session.execute(
        select(Asset, Member, Community)
        .join(Member, Asset.owner_id == Member.id)
        .join(Community, Asset.community_id == Community.id)
        .where(Asset.sensor_id == sensor_id, Member.status == ACTIVE)
    )
    row = _the_one(result.all())

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

@router.post(
    "/lookup/assets-by-sensor-ids",
    operation_id="lookup_assets_by_sensor_ids",
    response_model=list[GlobalAssetLookup],
)
async def lookup_assets_by_sensor_ids(
    body: SensorIdsBatchRequest,
    session: AsyncSession = Depends(get_session),
):
    """Find assets by multiple sensor_ids across all communities.

    The mirror of ``assets-by-user-ids``: this one starts from a device and
    finds its owner, that one starts from owners and finds their devices.

    **Bounded**, at the same 500 as its sibling. Both are reachable by anything
    holding ``rec-registry.lookup``, and a caller that can name ten thousand
    sensors in one request has a dump of the registry rather than a lookup.

    **A sensor id that matches nothing contributes no row** rather than failing
    the request: the caller asked about a set, and one absent member of it does
    not make the rest unanswerable. Nor does one whose owner is not active
    (REQ-0099).
    """
    if not body.sensor_ids:
        return []

    result = await session.execute(
        select(Asset, Member, Community)
        .join(Member, Asset.owner_id == Member.id)
        .join(Community, Asset.community_id == Community.id)
        .where(Asset.sensor_id.in_(body.sensor_ids), Member.status == ACTIVE)
    )

    return [
        GlobalAssetLookup(
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
        for a, m, c in result.all()
    ]


@router.post(
    "/lookup/assets-by-user-ids",
    operation_id="lookup_assets_by_user_ids",
    response_model=list[GlobalAssetLookup],
    responses=error_responses(409),
)
async def lookup_assets_by_user_ids(
    body: UserIdsBatchRequest,
    session: AsyncSession = Depends(get_session),
):
    """Find assets owned by multiple members, across all communities.

    The mirror of ``assets-by-sensor-ids``: that one starts from a device and
    finds its owner, this one starts from owners and finds their devices.

    **Why it exists.** A dataspace query is authorised for a *set of people* —
    the subjects who consented — not for the caller. The existing self-service
    path (``GET /user/assets``) can only answer "mine", because it resolves the
    member from the caller's own token. Widening *that* endpoint to take a list
    would turn a self-service route into a directory with no scope check in
    front of it, so the batch form belongs here, behind the admin policy.

    **No enumeration oracle.** A ``user_id`` that does not exist and a member
    who owns nothing are indistinguishable — both contribute no rows. The caller
    supplies the ids, so any difference in the answer would make this a way to
    discover who is registered.

    **Active owners only (REQ-0097).** A released member's row keeps its
    meters, and a consent-gated query built from it would read whoever holds
    that POD now. A member who is not active contributes no rows, exactly as
    an unknown id does. A user id active in more than one community is
    ``409 ambiguous_member``, naming nobody: the route has no community to
    scope by, and answering both would join one person's consent to two
    communities' meters.
    """
    if not body.user_ids:
        return []

    ambiguous = await session.scalar(
        select(Member.user_id)
        .where(Member.user_id.in_(body.user_ids), Member.status == ACTIVE)
        .group_by(Member.user_id)
        .having(func.count(Member.id) > 1)
        .limit(1)
    )
    if ambiguous is not None:
        raise RegistryError(
            409,
            "A user id in this request is an active member of more than one community",
            ErrorCode.AMBIGUOUS_MEMBER,
        )

    result = await session.execute(
        select(Asset, Member, Community)
        .join(Member, Asset.owner_id == Member.id)
        .join(Community, Asset.community_id == Community.id)
        .where(Member.user_id.in_(body.user_ids), Member.status == ACTIVE)
    )

    return [
        GlobalAssetLookup(
            id=str(a.id),
            key=a.key,
            asset_type=a.asset_type,
            name=a.name,
            sensor_id=a.sensor_id,
            properties=a.properties or {},
            device=a.device or {},
            relationships=a.relationships or {},
            owner_key=m.key,
            # The caller needs this to attribute rows back to the member it
            # asked about — the whole point of a batch lookup.
            owner_user_id=m.user_id,
            community_key=c.key,
            community_name=c.name,
        )
        for a, m, c in result.all()
    ]


@router.post(
    "/lookup/members-by-dids",
    operation_id="lookup_members_by_dids",
    response_model=list[GlobalMemberLookup],
)
async def lookup_members_by_dids(
    body: DidsBatchRequest,
    session: AsyncSession = Depends(get_session),
):
    """Find the members holding a set of dataspace DIDs, across all communities.

    **Why it exists.** The connector answers *who consents* in DIDs; this
    registry knows *what they hold*; nothing joined the two. Resolving a DID
    through the identity registry to a Keycloak user id does not close the gap,
    because `Member.user_id` holds a Keycloak *username* and the identifier that
    hop returns matches no row here. So the DID is stored on the member and this
    is the join.

    **Members, not assets** — and that is the part it would be easy to get
    wrong. Mirroring `assets-by-user-ids` exactly would lose the supply point in
    the common case: ../onboarding writes the declared POD into
    `Member.delivery_points` and registers **no assets**, because a meter's
    `sensor_id` is assigned at physical installation, long after onboarding. An
    asset-shaped answer is therefore empty for every participant whose meter has
    not been commissioned yet. `GlobalMemberLookup` already carries
    `delivery_points`; a commissioned meter stays reachable through the
    `user_id` in the same row and the existing `assets-by-user-ids`.

    **Bounded**, at the same 500 as the other two batch routes and from the same
    constant.

    **No enumeration oracle.** A DID that belongs to nobody and a member holding
    no supply points are indistinguishable — an unknown DID contributes no row
    and is not a `404`. The caller supplies the DIDs, so any difference between
    those answers would make this a way to discover who is registered.

    Every row carries its `did`, which is what lets the caller attribute the row
    back to the DID it asked about.
    """
    if not body.dids:
        return []

    result = await session.execute(
        select(Member, Community)
        .join(Community, Member.community_id == Community.id)
        .where(Member.did.in_(body.dids))
    )

    return [
        GlobalMemberLookup(
            id=str(m.id),
            key=m.key,
            user_id=m.user_id,
            did=m.did,
            name=m.name,
            role=m.role,
            area=m.area,
            status=m.status,
            delivery_points=[DeliveryPoint(**dp) for dp in (m.delivery_points or [])],
            community_key=c.key,
            community_name=c.name,
        )
        for m, c in result.all()
    ]
