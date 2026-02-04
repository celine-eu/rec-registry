from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from celine.rec_registry.db.session import get_session
from celine.rec_registry.db.models import (
    Community,
    Participant,
    Membership,
    Site,
    Asset,
    Meter,
)
from celine.rec_registry.api.util import format_param, maybe_jsonld, Format

router = APIRouter(tags=["registry"])


def _cursor_slice(items, limit: int, cursor: str | None):
    # Simple cursor: cursor is last key returned
    if cursor:
        items = [x for x in items if x["key"] > cursor]
    items = sorted(items, key=lambda x: x["key"])
    page = items[:limit]
    next_cursor = page[-1]["key"] if len(page) == limit else None
    return page, next_cursor


@router.get("/communities")
async def list_communities(
    session: AsyncSession = Depends(get_session),
    fmt: Format = Depends(format_param),
    key: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(default=None),
):
    q = select(Community)
    if key:
        q = q.where(Community.key == key)
    rows = (await session.scalars(q)).all()

    items = [
        {
            "id": c.iri,
            "key": c.key,
            "iri": c.iri,
            "name": c.name,
            "description": c.description,
            "extra": c.extra,
        }
        for c in rows
    ]
    page, next_cursor = _cursor_slice(items, limit, cursor)
    payload = {"items": page, "next_cursor": next_cursor}
    return maybe_jsonld(fmt, payload)


@router.get("/communities/{community_key}")
async def get_community(
    community_key: str,
    session: AsyncSession = Depends(get_session),
    fmt: Format = Depends(format_param),
):
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")
    payload = {
        "id": c.iri,
        "key": c.key,
        "iri": c.iri,
        "name": c.name,
        "description": c.description,
        "extra": c.extra,
    }
    return maybe_jsonld(fmt, payload)


@router.get("/communities/{community_key}/participants")
async def list_participants(
    community_key: str,
    session: AsyncSession = Depends(get_session),
    fmt: Format = Depends(format_param),
    kind: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(default=None),
):
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")
    q = select(Participant).where(Participant.community_id == c.id)
    if kind:
        q = q.where(Participant.kind == kind)
    rows = (await session.scalars(q)).all()
    items = [
        {
            "id": p.iri,
            "key": p.key,
            "iri": p.iri,
            "kind": p.kind,
            "name": p.name,
            "auth_iri": p.auth_iri,
            "extra": p.extra,
        }
        for p in rows
    ]
    page, next_cursor = _cursor_slice(items, limit, cursor)
    return maybe_jsonld(fmt, {"items": page, "next_cursor": next_cursor})


@router.get("/communities/{community_key}/memberships")
async def list_memberships(
    community_key: str,
    session: AsyncSession = Depends(get_session),
    fmt: Format = Depends(format_param),
    participant: str | None = Query(default=None, description="participant key"),
    role_iri: str | None = Query(default=None),
    status_iri: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(default=None),
):
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    q = (
        select(Membership, Participant)
        .join(Participant, Membership.participant_id == Participant.id)
        .where(Membership.community_id == c.id)
    )
    if participant:
        q = q.where(Participant.key == participant)
    if role_iri:
        q = q.where(Membership.role_iri == role_iri)
    if status_iri:
        q = q.where(Membership.status_iri == status_iri)

    rows = (await session.execute(q)).all()
    items = []
    for m, p in rows:
        items.append(
            {
                "id": m.iri,
                "key": m.key,
                "iri": m.iri,
                "community": c.iri,
                "participant": p.iri,
                "role_iri": m.role_iri,
                "status_iri": m.status_iri,
                "valid_from": m.valid_from,
                "valid_to": m.valid_to,
                "extra": m.extra,
            }
        )
    page, next_cursor = _cursor_slice(items, limit, cursor)
    return maybe_jsonld(fmt, {"items": page, "next_cursor": next_cursor})


@router.get("/communities/{community_key}/sites")
async def list_sites(
    community_key: str,
    session: AsyncSession = Depends(get_session),
    fmt: Format = Depends(format_param),
    area: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(default=None),
):
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")
    q = select(Site).where(Site.community_id == c.id)
    if area:
        q = q.where(Site.area == area)
    rows = (await session.scalars(q)).all()
    items = [
        {
            "id": s.iri,
            "key": s.key,
            "iri": s.iri,
            "name": s.name,
            "area": s.area,
            "extra": s.extra,
        }
        for s in rows
    ]
    page, next_cursor = _cursor_slice(items, limit, cursor)
    return maybe_jsonld(fmt, {"items": page, "next_cursor": next_cursor})


@router.get("/communities/{community_key}/assets")
async def list_assets(
    community_key: str,
    session: AsyncSession = Depends(get_session),
    fmt: Format = Depends(format_param),
    owner: str | None = Query(default=None, description="owner participant key"),
    category_iri: str | None = Query(default=None),
    site: str | None = Query(default=None, description="site key"),
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(default=None),
):
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    q = (
        select(Asset, Participant, Site)
        .join(Participant, Asset.owner_participant_id == Participant.id)
        .outerjoin(Site, Asset.site_id == Site.id)
        .where(Asset.community_id == c.id)
    )
    if owner:
        q = q.where(Participant.key == owner)
    if category_iri:
        q = q.where(Asset.category_iri == category_iri)
    if site:
        q = q.where(Site.key == site)

    rows = (await session.execute(q)).all()
    items = []
    for a, p, s in rows:
        items.append(
            {
                "id": a.iri,
                "key": a.key,
                "iri": a.iri,
                "owner": p.iri,
                "site": s.iri if s else None,
                "category_iri": a.category_iri,
                "name": a.name,
                "extra": a.extra,
            }
        )
    page, next_cursor = _cursor_slice(items, limit, cursor)
    return maybe_jsonld(fmt, {"items": page, "next_cursor": next_cursor})


@router.get("/communities/{community_key}/meters")
async def list_meters(
    community_key: str,
    session: AsyncSession = Depends(get_session),
    fmt: Format = Depends(format_param),
    owner: str | None = Query(default=None, description="owner participant key"),
    site: str | None = Query(default=None, description="site key"),
    sensor_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(default=None),
):
    c = await session.scalar(select(Community).where(Community.key == community_key))
    if c is None:
        raise HTTPException(status_code=404, detail="Community not found")

    q = (
        select(Meter, Participant, Site)
        .join(Participant, Meter.owner_participant_id == Participant.id)
        .outerjoin(Site, Meter.site_id == Site.id)
        .where(Meter.community_id == c.id)
    )
    if owner:
        q = q.where(Participant.key == owner)
    if site:
        q = q.where(Site.key == site)
    if sensor_id:
        q = q.where(Meter.sensor_id == sensor_id)

    rows = (await session.execute(q)).all()
    items = []
    for m, p, s in rows:
        items.append(
            {
                "id": m.iri,
                "key": m.key,
                "iri": m.iri,
                "owner": p.iri,
                "site": s.iri if s else None,
                "sensor_id": m.sensor_id,
                "pod": m.pod,
                "name": m.name,
                "extra": m.extra,
            }
        )
    page, next_cursor = _cursor_slice(items, limit, cursor)
    return maybe_jsonld(fmt, {"items": page, "next_cursor": next_cursor})
