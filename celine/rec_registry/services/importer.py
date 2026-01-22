from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from celine.rec_registry.schemas.bundle import RegistryBundleIn
from celine.rec_registry.schemas.iri import expand_iri, api_iri
from celine.rec_registry.db.models import (
    Community,
    Participant,
    Membership,
    Site,
    Asset,
    Meter,
)


def _extra(d: dict[str, Any], known: set[str]) -> dict[str, Any]:
    return {k: v for k, v in (d or {}).items() if k not in known and v is not None}


async def replacement_import_bundle(
    session: AsyncSession,
    bundle: RegistryBundleIn,
    *,
    base_url: str,
    dry_run: bool = False,
) -> tuple[str, dict[str, int], dict[str, int], list[str]]:
    warnings: list[str] = []
    ctx = bundle.context
    base = ctx.base if ctx else None
    prefixes = ctx.prefixes if ctx else {}

    community_key = bundle.community.key
    community_iri = expand_iri(
        bundle.community.iri or api_iri(base_url, f"communities/{community_key}"),
        base=base,
        prefixes=prefixes,
    )

    deleted = {
        k: 0
        for k in ["community", "participant", "membership", "site", "asset", "meter"]
    }
    existing = await session.scalar(
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

    if existing is not None:
        deleted["community"] = 1
        deleted["participant"] = len(existing.participants)
        deleted["membership"] = len(existing.memberships)
        deleted["site"] = len(existing.sites)
        deleted["asset"] = len(existing.assets)
        deleted["meter"] = len(existing.meters)
        if not dry_run:
            await session.delete(existing)
            await session.flush()

    inserted = {
        k: 0
        for k in ["community", "participant", "membership", "site", "asset", "meter"]
    }

    if dry_run:
        inserted["community"] = 1
        inserted["participant"] = len(bundle.participants)
        inserted["membership"] = len(bundle.memberships)
        inserted["site"] = len(bundle.sites)
        inserted["asset"] = len(bundle.assets)
        inserted["meter"] = sum(
            1 for m in bundle.meters if m.sensor_id
        )  # skip placeholders
        return community_key, deleted, inserted, warnings

    c_known = {"key", "iri", "name", "description"}
    community = Community(
        key=community_key,
        iri=community_iri,
        name=bundle.community.name,
        description=bundle.community.description,
        extra=_extra(bundle.community.model_dump(), c_known),
    )
    session.add(community)
    await session.flush()
    inserted["community"] = 1

    participant_by_key: dict[str, Participant] = {}
    p_known = {"key", "iri", "kind", "name", "auth_iri"}
    for p in bundle.participants:
        p_iri = expand_iri(
            p.iri
            or api_iri(base_url, f"communities/{community_key}/participants/{p.key}"),
            base=base,
            prefixes=prefixes,
        )
        auth_iri = (
            expand_iri(p.auth_iri, base=base, prefixes=prefixes) if p.auth_iri else None
        )
        obj = Participant(
            community_id=community.id,
            key=p.key,
            iri=p_iri,
            kind=p.kind,
            name=p.name,
            auth_iri=auth_iri,
            extra=_extra(p.model_dump(), p_known),
        )
        session.add(obj)
        participant_by_key[p.key] = obj
    await session.flush()
    inserted["participant"] = len(participant_by_key)

    site_by_key: dict[str, Site] = {}
    s_known = {"key", "iri", "name", "area"}
    for s in bundle.sites:
        s_iri = expand_iri(
            s.iri or api_iri(base_url, f"communities/{community_key}/sites/{s.key}"),
            base=base,
            prefixes=prefixes,
        )
        obj = Site(
            community_id=community.id,
            key=s.key,
            iri=s_iri,
            name=s.name,
            area=s.area,
            extra=_extra(s.model_dump(), s_known),
        )
        session.add(obj)
        site_by_key[s.key] = obj
    await session.flush()
    inserted["site"] = len(site_by_key)

    m_known = {
        "key",
        "iri",
        "participant_key",
        "role",
        "status",
        "valid_from",
        "valid_to",
    }
    for m in bundle.memberships:
        owner = participant_by_key.get(m.participant)
        if owner is None:
            warnings.append(
                f"membership {m.key}: unknown participant {m.participant}; skipped"
            )
            continue

        m_iri = expand_iri(
            m.iri
            or api_iri(base_url, f"communities/{community_key}/memberships/{m.key}"),
            base=base,
            prefixes=prefixes,
        )
        role_iri = expand_iri(m.role, base=base, prefixes=prefixes) if m.role else None
        status_iri = (
            expand_iri(m.status, base=base, prefixes=prefixes) if m.status else None
        )
        obj = Membership(
            community_id=community.id,
            participant_id=owner.id,
            key=m.key,
            iri=m_iri,
            role_iri=role_iri,
            status_iri=status_iri,
            valid_from=m.valid_from,
            valid_to=m.valid_to,
            extra=_extra(m.model_dump(), m_known),
        )
        session.add(obj)
        inserted["membership"] += 1
    await session.flush()

    a_known = {"key", "iri", "owner_participant_key", "site_key", "category", "name"}
    for a in bundle.assets:
        owner_key = a.owner.ref
        owner = participant_by_key.get(owner_key)
        if owner is None:
            warnings.append(f"asset {a.key}: unknown owner {owner_key}; skipped")
            continue
        site = site_by_key.get(a.located_at) if a.located_at else None
        a_iri = expand_iri(
            a.iri or api_iri(base_url, f"communities/{community_key}/assets/{a.key}"),
            base=base,
            prefixes=prefixes,
        )
        cat_iri = (
            expand_iri(a.category, base=base, prefixes=prefixes) if a.category else None
        )
        obj = Asset(
            community_id=community.id,
            owner_participant_id=owner.id,
            site_id=site.id if site else None,
            key=a.key,
            iri=a_iri,
            category_iri=cat_iri,
            name=a.name,
            extra=_extra(a.model_dump(), a_known),
        )
        session.add(obj)
        inserted["asset"] += 1
    await session.flush()

    me_known = {
        "key",
        "iri",
        "owner_participant_key",
        "site_key",
        "sensor_id",
        "pod",
        "name",
    }

    for me in bundle.meters:
        owner_key = me.owner.ref if me.owner else None
        owner = participant_by_key.get(owner_key) if owner_key else None
        if owner is None:
            warnings.append(f"meter {me.key}: unknown owner {owner_key}; skipped")
            continue

        # Per rule: skip placeholders without sensor_id
        if not me.sensor_id:
            warnings.append(f"meter {me.key}: missing sensor_id; skipped")
            continue

        site_key = getattr(me, "located_at", None)
        site = site_by_key.get(site_key) if site_key else None

        me_iri = expand_iri(
            me.iri or api_iri(base_url, f"communities/{community_key}/meters/{me.key}"),
            base=base,
            prefixes=prefixes,
        )

        obj = Meter(
            community_id=community.id,
            owner_participant_id=owner.id,
            site_id=site.id if site else None,
            key=me.key,
            iri=me_iri,
            sensor_id=me.sensor_id,
            pod=getattr(me, "pod", None),
            name=getattr(me, "name", None),
            # keep forward-compat metadata (datasets, etc.) in extra
            extra=_extra(
                me.model_dump(),
                {"key", "iri", "owner", "located_at", "sensor_id", "pod", "name"},
            ),
        )
        session.add(obj)
        inserted["meter"] += 1

    await session.flush()

    return community_key, deleted, inserted, warnings
