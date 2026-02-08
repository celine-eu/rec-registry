"""
Exporter service for v0.4 Registry Bundles.

Exports community data to the v0.4 YAML format.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from celine.rec_registry.db.models import Community, Member, Asset
from celine.rec_registry.core.yaml_io import dump_yaml


async def export_community_bundle(
    session: AsyncSession,
    *,
    community_key: str,
) -> dict:
    """
    Export a community to v0.4 bundle format.

    Args:
        session: Database session
        community_key: Community key to export

    Returns:
        Dict representing the bundle (can be serialized to YAML)

    Raises:
        KeyError: If community not found
    """
    community = await session.scalar(
        select(Community)
        .options(
            selectinload(Community.members).selectinload(Member.assets),
            selectinload(Community.assets),
        )
        .where(Community.key == community_key)
    )

    if community is None:
        raise KeyError(f"Community not found: {community_key}")

    # Build areas dict
    areas = {}
    for area_key, area_data in (community.areas or {}).items():
        areas[area_key] = {
            "name": area_data.get("name", area_key),
            "location": area_data.get("location", {"lat": 0, "lon": 0}),
        }

    # Build members dict
    members = {}
    for member in sorted(community.members, key=lambda m: m.key):
        member_assets = _build_asset_collection(member.assets)

        members[member.key] = {
            "user_id": member.user_id,
            "name": member.name,
            "role": member.role,
            "area": member.area,
            "status": member.status,
            "assets": member_assets,
        }

        # Add any extra fields
        if member.extra:
            members[member.key].update(member.extra)

    # Build bundle
    bundle = {
        "version": "1.0",
        "schema_version": "1.0",
        "metadata": {
            "created": (
                community.created_at.strftime("%Y-%m-%d")
                if community.created_at
                else None
            ),
            "updated": (
                community.updated_at.strftime("%Y-%m-%d")
                if community.updated_at
                else None
            ),
            "updated_by": "system",
            "description": community.description or f"{community.name} registry",
        },
        "community": {
            "id": community.key,
            "name": community.name,
            "description": community.description,
            "areas": areas,
        },
        "members": members,
    }

    # Add community extra fields
    if community.extra:
        bundle["community"].update(community.extra)

    return bundle


async def export_community_bundle_yaml(
    session: AsyncSession,
    *,
    community_key: str,
) -> str:
    """
    Export a community to v0.4 YAML format.

    Args:
        session: Database session
        community_key: Community key to export

    Returns:
        YAML string

    Raises:
        KeyError: If community not found
    """
    bundle = await export_community_bundle(session, community_key=community_key)
    return dump_yaml(bundle)


def _build_asset_collection(assets: list[Asset]) -> dict:
    """Build asset collection dict organized by type."""
    collection = {
        "pv": {},
        "storage": {},
        "meter": {},
        "ev_charger": {},
        "heat_pump": {},
        "load": {},
    }

    for asset in sorted(assets, key=lambda a: a.key):
        asset_type = asset.asset_type

        if asset_type not in collection:
            # Unknown type - store in a generic bucket
            asset_type = "load"  # fallback

        asset_dict: dict[str, Any] = {
            "name": asset.name,
        }

        # Add sensor_id for meters
        if asset_type == "meter" and asset.sensor_id:
            asset_dict["sensor_id"] = asset.sensor_id

        # Add type-specific properties
        if asset.properties:
            asset_dict.update(asset.properties)

        # Add relationships
        if asset.relationships:
            asset_dict["relationships"] = asset.relationships

        # Add extra fields
        if asset.extra:
            asset_dict.update(asset.extra)

        collection[asset_type][asset.key] = asset_dict

    # Remove empty collections
    return {k: v for k, v in collection.items() if v}
