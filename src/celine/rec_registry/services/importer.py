"""
Importer service for registry bundles.

Implements idempotent replacement import:
1. Delete existing community by key (cascades to members and assets)
2. Insert new community, members, and assets atomically
"""

from __future__ import annotations

from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from celine.rec_registry.core.versions import (
    CURRENT_SCHEMA_VERSION,
    KNOWN_SCHEMA_VERSIONS,
)
from celine.rec_registry.db.models import Community, Member, Asset
from celine.rec_registry.schemas.bundle import (
    RegistryBundleIn,
    AssetCollectionIn,
)


def schema_version_warnings(bundle: RegistryBundleIn) -> list[str]:
    """Say something when a bundle does not declare the schema this service reads.

    **This reports; it does not refuse.** Refusing would break the one path that
    matters most here — restoring a backup — and a backup is restored when
    something has already gone wrong. So an older, unrecognised or absent
    version still imports, and the caller is told.

    That makes this a report, not a compatibility gate: an incompatible bundle
    is still accepted and partially applied. What changed is that it is no
    longer silent about it, which is all the field was ever documented to do.
    """
    declared = bundle.schema_version

    if "schema_version" not in bundle.model_fields_set:
        return [
            f"Bundle declares no schema_version; read as {CURRENT_SCHEMA_VERSION!r}."
        ]

    if declared == CURRENT_SCHEMA_VERSION:
        return []

    if declared in KNOWN_SCHEMA_VERSIONS:
        return [
            f"Bundle declares schema_version {declared!r}; this service reads "
            f"{CURRENT_SCHEMA_VERSION!r}. Imported without conversion — see "
            f"schemas/community/v{CURRENT_SCHEMA_VERSION}/README.md for what changed."
        ]

    known = ", ".join(repr(v) for v in KNOWN_SCHEMA_VERSIONS)
    return [
        f"Bundle declares schema_version {declared!r}, which is not a published "
        f"schema (known: {known}). Imported anyway; nothing validated it against "
        f"{CURRENT_SCHEMA_VERSION!r}."
    ]


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


class ImportWouldOverwrite(Exception):
    """The bundle names a community that already exists, and force was not set.

    Import is *replacement*: it deletes the existing community with all its
    members and assets, then recreates it from the bundle. That was safe while
    the YAML was the only source of members. Now that members arrive at runtime,
    re-importing a stale export is the most likely way to lose them — so the
    caller has to say they mean it.
    """

    def __init__(self, community_key: str, members: int, assets: int):
        self.community_key = community_key
        self.members = members
        self.assets = assets
        super().__init__(
            f"Community {community_key!r} already exists with {members} member(s) "
            f"and {assets} asset(s); importing would delete them. Re-run with "
            f"dry_run to see the effect, or force to accept it."
        )


async def replacement_import_bundle(
    session: AsyncSession,
    bundle: RegistryBundleIn,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, dict[str, int], dict[str, int], list[str]]:
    """
    Perform idempotent replacement import of a registry bundle.

    Args:
        session: Database session
        bundle: Parsed registry bundle
        dry_run: If True, validate without committing changes
        force: Required to overwrite a community that already exists

    Returns:
        Tuple of (community_key, deleted_counts, inserted_counts, warnings)

    Raises:
        ImportWouldOverwrite: the community exists and force was not set
    """
    # Before the dry-run return below, deliberately: a dry run is where a caller
    # looks to find out whether the file is the one they think it is.
    warnings: list[str] = schema_version_warnings(bundle)
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

        # A dry run reports the damage instead of refusing — seeing the counts is
        # exactly how a caller decides whether to pass force.
        if not force and not dry_run:
            raise ImportWouldOverwrite(
                community_key, deleted["member"], deleted["asset"]
            )

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
        area_dict: dict[str, Any] = {"name": area.name}
        if area.topology:
            area_dict["topology"] = list(area.topology)
        if area.location is not None:
            area_dict["location"] = {"lat": area.location.lat, "lon": area.location.lon}
        if area.geometry is not None:
            area_dict["geometry"] = area.geometry
        # Preserve any extra metadata fields (e.g. cod_ac, rag_soc)
        extra = _extract_extra(area, {"name", "topology", "location", "geometry"})
        area_dict.update(extra)
        areas_dict[area_key] = area_dict

    # Build topology list
    topology_list = []
    for node in bundle.community.topology:
        node_dict = {"id": node.id, "type": node.type}
        if node.name:
            node_dict["name"] = node.name
        if node.operator_id:
            node_dict["operator_id"] = node.operator_id
        if node.parent:
            node_dict["parent"] = node.parent
        if node.area:
            node_dict["area"] = node.area
        topology_list.append(node_dict)

    # Build operators dict (stored in extra — no dedicated DB column)
    operators_dict: dict[str, Any] = {}
    for op_key, op in bundle.community.operators.items():
        op_dict: dict[str, Any] = {"name": op.name}
        if op.country:
            op_dict["country"] = op.country
        if op.contact:
            op_dict["contact"] = op.contact
        extra_op = _extract_extra(op, {"name", "country", "contact"})
        op_dict.update(extra_op)
        operators_dict[op_key] = op_dict

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
        extra={
            **({"operators": operators_dict} if operators_dict else {}),
            **_extract_extra(
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
                    "operators",
                },
            ),
        },
    )
    session.add(community)
    await session.flush()

    # Create members and their assets
    member_by_key: dict[str, Member] = {}

    for member_key, member_data in bundle.members.items():
        # Built by the shared helpers the admin API also uses, so a member that
        # arrives in a bundle and one created through the API are the same row.
        from celine.rec_registry.services.members import (
            build_delivery_points,
            build_member_extra,
        )

        member = Member(
            community_id=community.id,
            key=member_key,
            user_id=member_data.user_id,
            did=member_data.did,
            name=member_data.name,
            role=member_data.role,
            area=member_data.area,
            status=member_data.status,
            delivery_points=build_delivery_points(member_data.delivery_points),
            extra=build_member_extra(member_data),
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
