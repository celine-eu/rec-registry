from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from celine.rec_registry.schemas.import_yaml import CommunityImportDoc

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


@dataclass
class MappedCommunity:
    community_key: str
    community: Community
    participants: list[Participant]
    memberships: list[Membership]
    sites: list[Site]
    meters: list[Meter]
    assets: list[Asset]
    tariffs: list[Tariff]
    timeseries: list[TimeSeries]
    topology_edges: list[TopologyEdge]


def map_yaml_to_orm(doc: CommunityImportDoc):
    """Map an ergonomic YAML document into ORM instances.

    This is the *single* adaptation point for YAML structure changes.
    """

    community = Community(
        key=doc.community.key,
        name=doc.community.name,
        description=doc.community.description,
        external_id=doc.community.external_id,
    )

    # Build lookup maps
    participant_by_key: dict[str, Participant] = {}
    site_by_key: dict[str, Site] = {}
    meter_by_key: dict[str, Meter] = {}

    participants: list[Participant] = []
    for p in doc.participants:
        email = None
        if isinstance(p.contacts, dict):
            email = p.contacts.get("email")
        participant = Participant(
            key=p.key,
            name=p.name,
            kind=p.kind,
            external_id=p.external_id,
            email=email,
        )
        participants.append(participant)
        participant_by_key[p.key] = participant

    sites: list[Site] = []
    for s in doc.sites:
        lat = s.geo.lat if s.geo else None
        lon = s.geo.lon if s.geo else None
        site = Site(
            key=s.key,
            name=s.name,
            address=s.address,
            lat=lat,
            lon=lon,
            community=community,
        )
        sites.append(site)
        site_by_key[s.key] = site

    meters: list[Meter] = []
    for m in doc.meters:
        meter = Meter(key=m.key, name=m.name, pod_code=m.pod_code)
        if m.site:
            if m.site not in site_by_key:
                raise ValueError(f"Meter '{m.key}' references unknown site '{m.site}'")
            meter.site = site_by_key[m.site]
        meters.append(meter)
        meter_by_key[m.key] = meter

    assets: list[Asset] = []
    for a in doc.assets:
        asset = Asset(
            key=a.key,
            name=a.name,
            asset_type=a.type,
            rated_power_kw=a.rated_power_kw,
            rated_energy_kwh=a.rated_energy_kwh,
            community=community,
        )
        if a.site:
            if a.site not in site_by_key:
                raise ValueError(f"Asset '{a.key}' references unknown site '{a.site}'")
            asset.site = site_by_key[a.site]
        if a.meter:
            if a.meter not in meter_by_key:
                raise ValueError(
                    f"Asset '{a.key}' references unknown meter '{a.meter}'"
                )
            asset.meter = meter_by_key[a.meter]
        if a.owner:
            if a.owner not in participant_by_key:
                raise ValueError(
                    f"Asset '{a.key}' references unknown owner '{a.owner}'"
                )
            asset.owner = participant_by_key[a.owner]
        assets.append(asset)

    tariffs: list[Tariff] = []
    for t in doc.tariffs:
        tariffs.append(
            Tariff(
                key=t.key,
                name=t.name,
                currency=t.currency,
                notes=t.notes,
                community=community,
            )
        )

    def _parse_dt(value: str | datetime | None):
        if not value:
            return None
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc)
        # Accept RFC3339-like strings (e.g. 2025-01-01T00:00:00Z)
        v = value.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        return datetime.fromisoformat(v).astimezone(timezone.utc)

    memberships: list[Membership] = []
    for m in doc.memberships:
        if m.participant not in participant_by_key:
            raise ValueError(
                f"Membership references unknown participant '{m.participant}'"
            )
        memberships.append(
            Membership(
                participant=participant_by_key[m.participant],
                role=m.role,
                valid_from=_parse_dt(m.valid_from),
                valid_to=_parse_dt(m.valid_to),
                voting_weight=m.voting_weight,
                community=community,
            )
        )

    timeseries: list[TimeSeries] = []
    for ts in doc.timeseries:
        t = TimeSeries(
            key=ts.key,
            name=ts.name,
            metric=ts.metric,
            unit=ts.unit,
            observed_entity_kind=(
                "community" if ts.observed_entity == doc.community.key else "asset"
            ),
        )
        if t.observed_entity_kind == "asset":
            # observed_entity is an asset key
            asset_lookup = {a.key: a for a in assets}
            if ts.observed_entity not in asset_lookup:
                raise ValueError(
                    f"TimeSeries '{ts.key}' references unknown asset '{ts.observed_entity}'"
                )
            t.observed_entity = asset_lookup[ts.observed_entity]
        timeseries.append(t)

    edges: list[TopologyEdge] = []
    if doc.topology and doc.topology.edges:
        known_keys = {doc.community.key: "community"}
        known_keys.update({p.key: "participant" for p in participants})
        known_keys.update({s.key: "site" for s in sites})
        known_keys.update({m.key: "meter" for m in meters})
        known_keys.update({a.key: "asset" for a in assets})
        known_keys.update({t.key: "tariff" for t in tariffs})
        known_keys.update({ts.key: "timeseries" for ts in timeseries})

        for e in doc.topology.edges:
            src_key = e.from_
            dst_key = e.to
            if src_key not in known_keys:
                raise ValueError(f"Topology edge references unknown from '{src_key}'")
            if dst_key not in known_keys:
                raise ValueError(f"Topology edge references unknown to '{dst_key}'")
            edges.append(
                TopologyEdge(
                    src_key=src_key,
                    src_type=known_keys[src_key],
                    predicate=e.predicate,
                    dst_key=dst_key,
                    dst_type=known_keys[dst_key],
                )
            )

    return MappedCommunity(
        community_key=doc.community.key,
        community=community,
        participants=participants,
        memberships=memberships,
        sites=sites,
        meters=meters,
        assets=assets,
        tariffs=tariffs,
        timeseries=timeseries,
        topology_edges=edges,
    )
