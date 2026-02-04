from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from celine.rec_registry.db.models import Community
from celine.rec_registry.core.yaml_io import dump_yaml


async def export_community_bundle_yaml(
    session: AsyncSession, *, community_key: str
) -> str:
    community = await session.scalar(
        select(Community)
        .options(
            selectinload(Community.participants),
            selectinload(Community.memberships),
            selectinload(Community.sites),
            selectinload(Community.assets),
            selectinload(Community.meters),
        )
        .where(Community.key == community_key)
    )
    if community is None:
        raise KeyError(f"Community not found: {community_key}")

    participants = sorted(community.participants, key=lambda x: x.key)
    memberships = sorted(community.memberships, key=lambda x: x.key)
    sites = sorted(community.sites, key=lambda x: x.key)
    assets = sorted(community.assets, key=lambda x: x.key)
    meters = sorted(community.meters, key=lambda x: x.key)

    p_by_id = {p.id: p for p in participants}
    s_by_id = {s.id: s for s in sites}

    bundle = {
        "context": {"base": None, "prefixes": {}},
        "community": {
            "key": community.key,
            "iri": community.iri,
            "name": community.name,
            "description": community.description,
            **(community.extra or {}),
        },
        "participants": [
            {
                "key": p.key,
                "iri": p.iri,
                "kind": p.kind,
                "name": p.name,
                "auth_iri": p.auth_iri,
                **(p.extra or {}),
            }
            for p in participants
        ],
        "memberships": [
            {
                "key": m.key,
                "iri": m.iri,
                "participant_key": (
                    p_by_id.get(m.participant_id).key
                    if p_by_id.get(m.participant_id)
                    else None
                ),
                "role": m.role_iri,
                "status": m.status_iri,
                "valid_from": m.valid_from,
                "valid_to": m.valid_to,
                **(m.extra or {}),
            }
            for m in memberships
        ],
        "sites": [
            {
                "key": s.key,
                "iri": s.iri,
                "name": s.name,
                "area": s.area,
                **(s.extra or {}),
            }
            for s in sites
        ],
        "assets": [
            {
                "key": a.key,
                "iri": a.iri,
                "owner_participant_key": (
                    p_by_id.get(a.owner_participant_id).key
                    if p_by_id.get(a.owner_participant_id)
                    else None
                ),
                "site_key": (
                    s_by_id.get(a.site_id).key
                    if (a.site_id and s_by_id.get(a.site_id))
                    else None
                ),
                "category": a.category_iri,
                "name": a.name,
                **(a.extra or {}),
            }
            for a in assets
        ],
        "meters": [
            {
                "key": m.key,
                "iri": m.iri,
                "owner_participant_key": (
                    p_by_id.get(m.owner_participant_id).key
                    if p_by_id.get(m.owner_participant_id)
                    else None
                ),
                "site_key": (
                    s_by_id.get(m.site_id).key
                    if (m.site_id and s_by_id.get(m.site_id))
                    else None
                ),
                "sensor_id": m.sensor_id,
                "pod": m.pod,
                "name": m.name,
                **(m.extra or {}),
            }
            for m in meters
        ],
    }

    return dump_yaml(bundle)
