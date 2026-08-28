"""
Exporter service for v0.4 Registry Bundles.

Exports community data to the v0.4 YAML format.
"""

from __future__ import annotations

from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from celine.rec_registry.db.models import Community, Member, Asset
from celine.rec_registry.core.versions import (
    CURRENT_SCHEMA_VERSION,
    MANIFEST_VERSION,
)
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

    # Build areas dict — pass through all stored fields (location, geometry, metadata)
    areas = {}
    for area_key, area_data in (community.areas or {}).items():
        areas[area_key] = dict(area_data)
        areas[area_key].setdefault("name", area_key)

    # Build community section
    community_dict: dict[str, Any] = {
        "id": community.key,
        "name": community.name,
    }

    if community.description:
        community_dict["description"] = community.description

    # Add legal, links, contact, settings if present
    if community.legal:
        community_dict["legal"] = community.legal

    if community.links:
        community_dict["links"] = community.links

    if community.contact:
        community_dict["contact"] = community.contact

    if community.settings:
        community_dict["settings"] = community.settings

    # operators stored in extra (no dedicated DB column)
    operators = (community.extra or {}).get("operators")
    if operators:
        community_dict["operators"] = operators

    community_dict["areas"] = areas

    # Add topology if present
    if community.topology:
        community_dict["topology"] = community.topology

    # Build members dict
    members = {}
    for member in sorted(community.members, key=lambda m: m.key):
        member_assets = _build_asset_collection(member.assets)

        member_dict: dict[str, Any] = {"user_id": member.user_id}

        # Only when it has one. A community with no dataspace would otherwise
        # export a `did: null` on every member, which reads as a field somebody
        # forgot to fill in rather than one that does not apply here.
        if member.did:
            member_dict["did"] = member.did

        member_dict["name"] = member.name

        # type stored in extra (no dedicated DB column)
        member_type = (member.extra or {}).get("type")
        if member_type:
            member_dict["type"] = member_type

        member_dict["role"] = member.role
        member_dict["area"] = member.area
        member_dict["status"] = member.status

        # Add delivery_points if present
        if member.delivery_points:
            member_dict["delivery_points"] = member.delivery_points

        # Add assets
        member_dict["assets"] = member_assets

        # Add any remaining extra fields (type already handled above)
        remaining_member_extra = {k: v for k, v in (member.extra or {}).items() if k != "type"}
        if remaining_member_extra:
            member_dict.update(remaining_member_extra)

        members[member.key] = member_dict

    # Build bundle
    bundle: dict[str, Any] = {
        # The version of the document being written, not the version of the
        # bundle some of these rows arrived in. An export is built from today's
        # model, so it conforms to today's schema whatever it was imported as —
        # stamping the older number on it would be a more convincing lie than
        # the `1.0` that used to be here, which matched nothing at all.
        "version": MANIFEST_VERSION,
        "schema_version": CURRENT_SCHEMA_VERSION,
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
        "community": community_dict,
        "members": members,
    }

    # Add remaining extra fields to community (operators already handled above)
    remaining_extra = {k: v for k, v in (community.extra or {}).items() if k != "operators"}
    if remaining_extra:
        bundle["community"].update(remaining_extra)

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
    collection: dict[str, dict] = {
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

        # Add device specification
        if asset.device:
            asset_dict["device"] = asset.device

        # Add relationships
        if asset.relationships:
            asset_dict["relationships"] = asset.relationships

        # Add extra fields
        if asset.extra:
            asset_dict.update(asset.extra)

        collection[asset_type][asset.key] = asset_dict

    # Remove empty collections
    return {k: v for k, v in collection.items() if v}
