"""
Importer service for v0.4 Registry Bundles.

Implements idempotent replacement import:
1. Delete existing community by key (cascades to members and assets)
2. Insert new community, members, and assets atomically
"""

from __future__ import annotations

from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from celine.rec_registry.db.models import Community, Member, Asset
from celine.rec_registry.schemas.bundle import (
    RegistryBundleIn,
    AssetCollectionIn,
)


def _to_dict(obj: Any) -> dict[str, Any]:
    """Convert Pydantic model or dict to dict, filtering None values."""
    if obj is None:
        return {}
    if hasattr(obj, "model_dump"):
        return {k: v for k, v in obj.model_dump().items() if v is not None}
    return dict(obj) if obj else {}


def _extract_properties(asset_data: Any, exclude_keys: set[str]) -> dict[str, Any]:
    """Extract type-specific properties from asset data."""
    if hasattr(asset_data, "model_dump"):
        data = asset_data.model_dump()
    else:
        data = dict(asset_data) if asset_data else {}

    return {k: v for k, v in data.items() if k not in exclude_keys and v is not None}


def _extract_relationships(asset_data: Any) -> dict[str, Any]:
    """Extract relationships from asset data."""
    if hasattr(asset_data, "relationships"):
        rel = asset_data.relationships
        if hasattr(rel, "model_dump"):
            return {k: v for k, v in rel.model_dump().items() if v is not None}
        return dict(rel) if rel else {}
    return {}


def _extract_device(asset_data: Any) -> dict[str, Any]:
    """Extract device specification from asset data."""
    if hasattr(asset_data, "device") and asset_data.device:
        dev = asset_data.device
        if hasattr(dev, "model_dump"):
            return {k: v for k, v in dev.model_dump().items() if v is not None}
        return dict(dev) if dev else {}
    return {}


async def replacement_import_bundle(
    session: AsyncSession,
    bundle: RegistryBundleIn,
    *,
    dry_run: bool = False,
) -> tuple[str, dict[str, int], dict[str, int], list[str]]:
    """
    Perform idempotent replacement import of a registry bundle.

    Args:
        session: Database session
        bundle: Parsed registry bundle
        dry_run: If True, validate without committing changes

    Returns:
        Tuple of (community_key, deleted_counts, inserted_counts, warnings)
    """
    warnings: list[str] = []
    community_key = bundle.community.id

    # Count what will be deleted
    deleted = {"community": 0, "member": 0, "asset": 0}

    existing = await session.scalar(
        select(Community)
        .options(
            selectinload(Community.members),
            selectinload(Community.assets),
        )
        .where(Community.key == community_key)
    )

    if existing is not None:
        deleted["community"] = 1
        deleted["member"] = len(existing.members)
        deleted["asset"] = len(existing.assets)

        if not dry_run:
            await session.delete(existing)
            await session.flush()

    # Count what will be inserted
    inserted = {"community": 1, "member": 0, "asset": 0}

    # Count members
    inserted["member"] = len(bundle.members)

    # Count assets (from members)
    for member_key, member in bundle.members.items():
        if member.assets:
            inserted["asset"] += _count_assets(member.assets)

    if dry_run:
        return community_key, deleted, inserted, warnings

    # Build areas dict
    areas_dict = {}
    for area_key, area in bundle.community.areas.items():
        areas_dict[area_key] = {
            "name": area.name,
            "location": {"lat": area.location.lat, "lon": area.location.lon},
        }

    # Build topology list
    topology_list = []
    for node in bundle.community.topology:
        node_dict = {"id": node.id, "type": node.type}
        if node.name:
            node_dict["name"] = node.name
        if node.operator:
            node_dict["operator"] = node.operator
        if node.parent:
            node_dict["parent"] = node.parent
        if node.area:
            node_dict["area"] = node.area
        topology_list.append(node_dict)

    # Create community
    community = Community(
        key=community_key,
        name=bundle.community.name,
        description=bundle.community.description,
        areas=areas_dict,
        topology=topology_list,
        legal=_to_dict(bundle.community.legal),
        links=_to_dict(bundle.community.links),
        contact=_to_dict(bundle.community.contact),
        settings=_to_dict(bundle.community.settings),
        extra=_extract_extra(
            bundle.community,
            {
                "id",
                "name",
                "description",
                "areas",
                "topology",
                "legal",
                "links",
                "contact",
                "settings",
            },
        ),
    )
    session.add(community)
    await session.flush()

    # Create members and their assets
    member_by_key: dict[str, Member] = {}

    for member_key, member_data in bundle.members.items():
        # Build delivery_points list
        delivery_points_list = []
        for dp in member_data.delivery_points:
            dp_dict = {"id": dp.id, "type": dp.type}
            if dp.description:
                dp_dict["description"] = dp.description
            if dp.address:
                dp_dict["address"] = dp.address
            if dp.tariff:
                dp_dict["tariff"] = dp.tariff
            dp_dict["active"] = dp.active
            delivery_points_list.append(dp_dict)

        member = Member(
            community_id=community.id,
            key=member_key,
            user_id=member_data.user_id,
            name=member_data.name,
            role=member_data.role,
            area=member_data.area,
            status=member_data.status,
            delivery_points=delivery_points_list,
            extra=_extract_extra(
                member_data,
                {"user_id", "name", "role", "area", "status", "delivery_points", "assets"},
            ),
        )
        session.add(member)
        member_by_key[member_key] = member

    await session.flush()

    # Create assets for each member
    for member_key, member_data in bundle.members.items():
        member = member_by_key[member_key]
        if member_data.assets:
            asset_warnings = await _create_assets(
                session,
                community_id=community.id,
                owner_id=member.id,
                assets=member_data.assets,
            )
            warnings.extend(asset_warnings)

    await session.flush()

    return community_key, deleted, inserted, warnings


def _count_assets(assets: AssetCollectionIn) -> int:
    """Count total assets in a collection."""
    count = 0
    count += len(assets.pv) if assets.pv else 0
    count += len(assets.storage) if assets.storage else 0
    count += len(assets.meter) if assets.meter else 0
    count += len(assets.ev_charger) if assets.ev_charger else 0
    count += len(assets.heat_pump) if assets.heat_pump else 0
    count += len(assets.load) if assets.load else 0
    return count


def _extract_extra(obj: Any, exclude_keys: set[str]) -> dict[str, Any]:
    """Extract extra fields not in the schema."""
    if hasattr(obj, "model_dump"):
        data = obj.model_dump()
    else:
        data = dict(obj) if obj else {}

    return {k: v for k, v in data.items() if k not in exclude_keys and v is not None}


async def _create_assets(
    session: AsyncSession,
    *,
    community_id,
    owner_id,
    assets: AssetCollectionIn,
) -> list[str]:
    """Create assets for a member."""
    warnings: list[str] = []

    # Common exclude keys for properties extraction
    base_exclude = {"name", "relationships", "device"}

    # PV assets
    for asset_key, pv in (assets.pv or {}).items():
        asset = Asset(
            community_id=community_id,
            owner_id=owner_id,
            key=asset_key,
            asset_type="pv",
            name=pv.name,
            sensor_id=None,
            properties=_extract_properties(pv, base_exclude | {"sensor_id"}),
            device=_extract_device(pv),
            relationships=_extract_relationships(pv),
        )
        session.add(asset)

    # Storage assets
    for asset_key, storage in (assets.storage or {}).items():
        asset = Asset(
            community_id=community_id,
            owner_id=owner_id,
            key=asset_key,
            asset_type="storage",
            name=storage.name,
            sensor_id=None,
            properties=_extract_properties(storage, base_exclude),
            device=_extract_device(storage),
            relationships=_extract_relationships(storage),
        )
        session.add(asset)

    # Meter assets
    for asset_key, meter in (assets.meter or {}).items():
        if not meter.sensor_id:
            warnings.append(f"Meter {asset_key}: missing sensor_id; skipped")
            continue

        asset = Asset(
            community_id=community_id,
            owner_id=owner_id,
            key=asset_key,
            asset_type="meter",
            name=meter.name,
            sensor_id=meter.sensor_id,
            properties=_extract_properties(meter, base_exclude | {"sensor_id"}),
            device=_extract_device(meter),
            relationships=_extract_relationships(meter),
        )
        session.add(asset)

    # EV Charger assets
    for asset_key, ev in (assets.ev_charger or {}).items():
        asset = Asset(
            community_id=community_id,
            owner_id=owner_id,
            key=asset_key,
            asset_type="ev_charger",
            name=ev.name,
            sensor_id=None,
            properties=_extract_properties(ev, base_exclude),
            device=_extract_device(ev),
            relationships=_extract_relationships(ev),
        )
        session.add(asset)

    # Heat pump assets
    for asset_key, hp in (assets.heat_pump or {}).items():
        asset = Asset(
            community_id=community_id,
            owner_id=owner_id,
            key=asset_key,
            asset_type="heat_pump",
            name=hp.name,
            sensor_id=None,
            properties=_extract_properties(hp, base_exclude),
            device=_extract_device(hp),
            relationships=_extract_relationships(hp),
        )
        session.add(asset)

    # Load assets
    for asset_key, load in (assets.load or {}).items():
        asset = Asset(
            community_id=community_id,
            owner_id=owner_id,
            key=asset_key,
            asset_type="load",
            name=load.name,
            sensor_id=None,
            properties=_extract_properties(load, base_exclude),
            device=_extract_device(load),
            relationships=_extract_relationships(load),
        )
        session.add(asset)

    return warnings
