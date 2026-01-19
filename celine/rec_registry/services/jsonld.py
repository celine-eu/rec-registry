from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

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
from celine.rec_registry.services.iri import community_iri, context_iri, entity_iri


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except Exception:
        return None


# JSON-LD type aliases (mapped in @context)
TYPE_COMMUNITY = "Community"
TYPE_PARTICIPANT = "Participant"
TYPE_MEMBERSHIP = "Membership"
TYPE_SITE = "Site"
TYPE_METER = "Meter"
TYPE_ASSET = "Asset"
TYPE_TARIFF = "Tariff"
TYPE_TIMESERIES = "TimeSeries"
TYPE_EDGE = "TopologyEdge"


def serialize_community(
    base_url: str, c: Community, include_context: bool, version: str | None = None
) -> Dict[str, Any]:
    obj: Dict[str, Any] = {
        "@id": community_iri(base_url, c.key),
        "@type": TYPE_COMMUNITY,
        "name": c.name,
    }
    if include_context:
        obj["@context"] = context_iri(base_url, version)
    if c.description:
        obj["description"] = c.description
    if c.external_id:
        obj["external_id"] = c.external_id
    return obj


def serialize_participant(
    base_url: str, community_key: str, p: Participant
) -> Dict[str, Any]:
    return {
        "@id": entity_iri(base_url, community_key, "participants", p.key),
        "@type": TYPE_PARTICIPANT,
        "name": p.name,
        "kind": p.kind,
        "external_id": p.external_id,
        "email": p.email,
    }


def serialize_membership(
    base_url: str, community_key: str, m: Membership, participant_key: str
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "@id": entity_iri(base_url, community_key, "memberships", str(m.id)),
        "@type": TYPE_MEMBERSHIP,
        "participant": entity_iri(
            base_url, community_key, "participants", participant_key
        ),
        "role": m.role,
    }
    if m.valid_from:
        out["validFrom"] = m.valid_from.isoformat()
    if m.valid_to:
        out["validTo"] = m.valid_to.isoformat()
    if m.voting_weight is not None:
        out["votingWeight"] = _to_float(m.voting_weight)
    return out


def serialize_site(base_url: str, community_key: str, s: Site) -> Dict[str, Any]:
    return {
        "@id": entity_iri(base_url, community_key, "sites", s.key),
        "@type": TYPE_SITE,
        "name": s.name,
        "address": s.address,
        "lat": s.lat,
        "lon": s.lon,
    }


def serialize_meter(
    base_url: str, community_key: str, m: Meter, site_key: Optional[str]
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "@id": entity_iri(base_url, community_key, "meters", m.key),
        "@type": TYPE_METER,
        "name": m.name,
    }
    if m.pod_code:
        out["podCode"] = m.pod_code
    if site_key:
        out["site"] = entity_iri(base_url, community_key, "sites", site_key)
    return out


def serialize_asset(
    base_url: str,
    community_key: str,
    a: Asset,
    site_key: Optional[str],
    meter_key: Optional[str],
    owner_key: Optional[str],
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "@id": entity_iri(base_url, community_key, "assets", a.key),
        "@type": TYPE_ASSET,
        "name": a.name,
        "assetType": a.asset_type,
    }
    if site_key:
        out["site"] = entity_iri(base_url, community_key, "sites", site_key)
    if meter_key:
        out["meter"] = entity_iri(base_url, community_key, "meters", meter_key)
    if owner_key:
        out["owner"] = entity_iri(base_url, community_key, "participants", owner_key)
    if a.rated_power_kw is not None:
        out["ratedPowerKw"] = _to_float(a.rated_power_kw)
    if a.rated_energy_kwh is not None:
        out["ratedEnergyKwh"] = _to_float(a.rated_energy_kwh)
    return out


def serialize_tariff(base_url: str, community_key: str, t: Tariff) -> Dict[str, Any]:
    return {
        "@id": entity_iri(base_url, community_key, "tariffs", t.key),
        "@type": TYPE_TARIFF,
        "name": t.name,
        "currency": t.currency,
        "notes": t.notes,
    }


def serialize_timeseries(
    base_url: str, community_key: str, ts: TimeSeries, observed_iri: str
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "@id": entity_iri(base_url, community_key, "timeseries", ts.key),
        "@type": TYPE_TIMESERIES,
        "name": ts.name,
        "metric": ts.metric,
        "observedEntity": observed_iri,
    }
    if ts.unit:
        out["unit"] = ts.unit
    return out


def serialize_edge(
    base_url: str, community_key: str, e: TopologyEdge
) -> Dict[str, Any]:
    def resolve(t: str, k: str) -> str:
        if t == "community":
            return community_iri(base_url, community_key)
        collection_map = {
            "participant": "participants",
            "membership": "memberships",
            "site": "sites",
            "meter": "meters",
            "asset": "assets",
            "tariff": "tariffs",
            "timeseries": "timeseries",
        }
        col = collection_map.get(t)
        return entity_iri(base_url, community_key, col or "entities", k)

    return {
        "@id": entity_iri(base_url, community_key, "topology/edges", str(e.id)),
        "@type": TYPE_EDGE,
        "from": resolve(e.src_type, e.src_key),
        "predicate": e.predicate,
        "to": resolve(e.dst_type, e.dst_key),
    }


async def build_community_graph(
    session: AsyncSession, base_url: str, community_key: str, version: str | None = None
) -> Dict[str, Any]:
    # Fetch community
    c = (
        await session.execute(select(Community).where(Community.key == community_key))
    ).scalar_one_or_none()
    if c is None:
        raise KeyError("community_not_found")

    # Preload collections
    participants = (
        (
            await session.execute(
                select(Participant).where(Participant.community_id == c.id)
            )
        )
        .scalars()
        .all()
    )
    memberships = (
        (
            await session.execute(
                select(Membership).where(Membership.community_id == c.id)
            )
        )
        .scalars()
        .all()
    )
    sites = (
        (await session.execute(select(Site).where(Site.community_id == c.id)))
        .scalars()
        .all()
    )
    meters = (
        (await session.execute(select(Meter).where(Meter.community_id == c.id)))
        .scalars()
        .all()
    )
    assets = (
        (await session.execute(select(Asset).where(Asset.community_id == c.id)))
        .scalars()
        .all()
    )
    tariffs = (
        (await session.execute(select(Tariff).where(Tariff.community_id == c.id)))
        .scalars()
        .all()
    )
    timeseries = (
        (
            await session.execute(
                select(TimeSeries).where(TimeSeries.community_id == c.id)
            )
        )
        .scalars()
        .all()
    )
    edges = (
        (
            await session.execute(
                select(TopologyEdge).where(TopologyEdge.community_id == c.id)
            )
        )
        .scalars()
        .all()
    )

    # maps for keys
    participant_by_id = {str(p.id): p for p in participants}
    site_by_id = {str(s.id): s for s in sites}
    meter_by_id = {str(m.id): m for m in meters}
    asset_by_id = {str(a.id): a for a in assets}

    graph: List[Dict[str, Any]] = []

    graph.append(
        serialize_community(base_url, c, include_context=False, version=version)
    )

    for p in participants:
        graph.append(serialize_participant(base_url, c.key, p))

    for m in memberships:
        p = participant_by_id.get(m.participant_id)
        graph.append(
            serialize_membership(
                base_url, c.key, m, participant_key=p.key if p else "unknown"
            )
        )

    for s in sites:
        graph.append(serialize_site(base_url, c.key, s))

    for m in meters:
        site = site_by_id.get(m.site_id) if m.site_id else None
        sk = site.key if site else None

        graph.append(serialize_meter(base_url, c.key, m, site_key=sk))

    for asset in assets:
        site = site_by_id.get(asset.site_id) if asset.site_id else None
        sk = site.key if site is not None else None

        meter = meter_by_id.get(asset.meter_id) if asset.meter_id else None
        mk = meter.key if meter is not None else None

        owner = participant_by_id.get(asset.owner_id) if asset.owner_id else None
        ok = owner.key if owner is not None else None

        graph.append(
            serialize_asset(
                base_url, c.key, asset, site_key=sk, meter_key=mk, owner_key=ok
            )
        )

    for t in tariffs:
        graph.append(serialize_tariff(base_url, c.key, t))

    for ts in timeseries:
        if ts.observed_entity_kind == "community":
            observed_iri = community_iri(base_url, c.key)
        else:

            asset = (
                asset_by_id.get(ts.observed_asset_id) if ts.observed_asset_id else None
            )

            observed_iri = (
                entity_iri(base_url, c.key, "assets", asset.key)
                if asset
                else community_iri(base_url, c.key)
            )
        graph.append(
            serialize_timeseries(base_url, c.key, ts, observed_iri=observed_iri)
        )

    for e in edges:
        graph.append(serialize_edge(base_url, c.key, e))

    return {
        "@context": context_iri(base_url, version),
        "@graph": graph,
    }
