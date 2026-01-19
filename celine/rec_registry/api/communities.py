from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from celine.rec_registry.db.session import get_session
from celine.rec_registry.models import Community
from celine.rec_registry.services.jsonld import build_community_graph, serialize_community
from celine.rec_registry.services.iri import context_iri

router = APIRouter(prefix="/communities", tags=["communities"])


@router.get("")
async def list_communities(
    request: Request,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Community)
    if q:
        stmt = stmt.where(Community.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(Community.key).limit(min(limit, 500)).offset(max(offset, 0))
    rows = (await session.scalars(stmt)).all()
    base = str(request.base_url)
    return {
        "@context": context_iri(base),
        "@graph": [serialize_community(base, c, include_context=False) for c in rows],
    }


@router.get("/{community_id}")
async def get_community(
    community_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    c = await session.scalar(select(Community).where(Community.key == community_id))
    if not c:
        raise HTTPException(status_code=404, detail="Community not found")
    base = str(request.base_url)
    return serialize_community(base, c, include_context=True)


@router.get("/{community_id}/graph")
async def get_community_graph(
    community_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    return await build_community_graph(session=session, base_url=str(request.base_url), community_key=community_id)
