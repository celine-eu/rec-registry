from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from celine.rec_registry.models import (
    Asset,
    Community,
    Membership,
    Meter,
    Participant,
    Site,
    Tariff,
    TimeSeries,
    TopologyEdge,
)
from celine.rec_registry.schemas.import_yaml import CommunityImportDoc
from celine.rec_registry.services.yaml_mapping import map_yaml_to_orm


def _stable_hash(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


async def replace_community_from_doc(
    session: AsyncSession, doc: CommunityImportDoc
) -> dict[str, int | str]:
    """Replace a community definition (drop previous, insert new).

    Idempotent: importing the same content yields the same final state.
    """
    mapped = map_yaml_to_orm(doc)

    # Load existing community by key, if any
    existing = await session.scalar(
        select(Community).where(Community.key == mapped.community_key)
    )

    if existing:
        # Delete dependents explicitly (avoid relying on ORM cascades for bulk ops)
        cid = existing.id
        await session.execute(
            delete(TopologyEdge).where(TopologyEdge.community_id == cid)
        )
        await session.execute(delete(TimeSeries).where(TimeSeries.community_id == cid))
        await session.execute(delete(Tariff).where(Tariff.community_id == cid))
        await session.execute(delete(Asset).where(Asset.community_id == cid))
        await session.execute(delete(Meter).where(Meter.community_id == cid))
        await session.execute(delete(Site).where(Site.community_id == cid))
        await session.execute(delete(Membership).where(Membership.community_id == cid))
        await session.execute(
            delete(Participant).where(Participant.community_id == cid)
        )
        await session.execute(delete(Community).where(Community.id == cid))
        await session.flush()

    # Insert new graph
    session.add(mapped.community)
    await session.flush()  # get community id

    community_id = str(mapped.community.id)

    for p in mapped.participants:
        p.community_id = community_id
        session.add(p)
    await session.flush()

    for s in mapped.sites:
        s.community_id = community_id
        session.add(s)
    await session.flush()

    for m in mapped.meters:
        m.community_id = community_id
        session.add(m)
    await session.flush()

    for a in mapped.assets:
        a.community_id = community_id
        session.add(a)
    await session.flush()

    for t in mapped.tariffs:
        t.community_id = community_id
        session.add(t)
    await session.flush()

    for ts in mapped.timeseries:
        ts.community_id = community_id
        session.add(ts)
    await session.flush()

    for mem in mapped.memberships:
        mem.community_id = community_id
        session.add(mem)
    await session.flush()

    for e in mapped.topology_edges:
        e.community_id = community_id
        session.add(e)
    await session.flush()

    return {
        "participants": len(mapped.participants),
        "memberships": len(mapped.memberships),
        "sites": len(mapped.sites),
        "meters": len(mapped.meters),
        "assets": len(mapped.assets),
        "tariffs": len(mapped.tariffs),
        "timeseries": len(mapped.timeseries),
        "topology_edges": len(mapped.topology_edges),
    }
