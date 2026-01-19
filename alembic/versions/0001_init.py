"""init

Revision ID: 0001_init
Revises: 
Create Date: 2026-01-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "community",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=250), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("external_id", sa.String(length=150), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_community_key", "community", ["key"], unique=True)
    op.create_index("ix_community_external_id", "community", ["external_id"], unique=False)

    op.create_table(
        "participant",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("community_id", sa.UUID(as_uuid=True), sa.ForeignKey("community.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=250), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=True),
        sa.Column("external_id", sa.String(length=150), nullable=True),
        sa.Column("email", sa.String(length=250), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_participant_community_id", "participant", ["community_id"], unique=False)
    op.create_index("ix_participant_key", "participant", ["key"], unique=False)
    op.create_index("ix_participant_external_id", "participant", ["external_id"], unique=False)
    op.create_unique_constraint("uq_participant_community_key", "participant", ["community_id", "key"])

    op.create_table(
        "membership",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("community_id", sa.UUID(as_uuid=True), sa.ForeignKey("community.id", ondelete="CASCADE"), nullable=False),
        sa.Column("participant_id", sa.UUID(as_uuid=True), sa.ForeignKey("participant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=80), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voting_weight", sa.Numeric(12, 6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_membership_community_id", "membership", ["community_id"], unique=False)
    op.create_index("ix_membership_participant_id", "membership", ["participant_id"], unique=False)

    op.create_table(
        "site",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("community_id", sa.UUID(as_uuid=True), sa.ForeignKey("community.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=250), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_site_community_id", "site", ["community_id"], unique=False)
    op.create_index("ix_site_key", "site", ["key"], unique=False)
    op.create_unique_constraint("uq_site_community_key", "site", ["community_id", "key"])

    op.create_table(
        "meter",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("community_id", sa.UUID(as_uuid=True), sa.ForeignKey("community.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", sa.UUID(as_uuid=True), sa.ForeignKey("site.id", ondelete="SET NULL"), nullable=True),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=250), nullable=False),
        sa.Column("pod_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_meter_community_id", "meter", ["community_id"], unique=False)
    op.create_index("ix_meter_site_id", "meter", ["site_id"], unique=False)
    op.create_index("ix_meter_key", "meter", ["key"], unique=False)
    op.create_index("ix_meter_pod_code", "meter", ["pod_code"], unique=False)
    op.create_unique_constraint("uq_meter_community_key", "meter", ["community_id", "key"])

    op.create_table(
        "asset",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("community_id", sa.UUID(as_uuid=True), sa.ForeignKey("community.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", sa.UUID(as_uuid=True), sa.ForeignKey("site.id", ondelete="SET NULL"), nullable=True),
        sa.Column("meter_id", sa.UUID(as_uuid=True), sa.ForeignKey("meter.id", ondelete="SET NULL"), nullable=True),
        sa.Column("owner_id", sa.UUID(as_uuid=True), sa.ForeignKey("participant.id", ondelete="SET NULL"), nullable=True),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=250), nullable=False),
        sa.Column("asset_type", sa.String(length=50), nullable=False),
        sa.Column("rated_power_kw", sa.Numeric(14, 6), nullable=True),
        sa.Column("rated_energy_kwh", sa.Numeric(14, 6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_asset_community_id", "asset", ["community_id"], unique=False)
    op.create_index("ix_asset_site_id", "asset", ["site_id"], unique=False)
    op.create_index("ix_asset_meter_id", "asset", ["meter_id"], unique=False)
    op.create_index("ix_asset_owner_id", "asset", ["owner_id"], unique=False)
    op.create_index("ix_asset_key", "asset", ["key"], unique=False)
    op.create_unique_constraint("uq_asset_community_key", "asset", ["community_id", "key"])

    op.create_table(
        "tariff",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("community_id", sa.UUID(as_uuid=True), sa.ForeignKey("community.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=250), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tariff_community_id", "tariff", ["community_id"], unique=False)
    op.create_index("ix_tariff_key", "tariff", ["key"], unique=False)
    op.create_unique_constraint("uq_tariff_community_key", "tariff", ["community_id", "key"])

    op.create_table(
        "timeseries",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("community_id", sa.UUID(as_uuid=True), sa.ForeignKey("community.id", ondelete="CASCADE"), nullable=False),
        sa.Column("observed_asset_id", sa.UUID(as_uuid=True), sa.ForeignKey("asset.id", ondelete="SET NULL"), nullable=True),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=250), nullable=False),
        sa.Column("metric", sa.String(length=100), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("observed_entity_kind", sa.String(length=50), nullable=False, server_default="asset"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_timeseries_community_id", "timeseries", ["community_id"], unique=False)
    op.create_index("ix_timeseries_observed_asset_id", "timeseries", ["observed_asset_id"], unique=False)
    op.create_index("ix_timeseries_key", "timeseries", ["key"], unique=False)
    op.create_unique_constraint("uq_timeseries_community_key", "timeseries", ["community_id", "key"])

    op.create_table(
        "topology_edge",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("community_id", sa.UUID(as_uuid=True), sa.ForeignKey("community.id", ondelete="CASCADE"), nullable=False),
        sa.Column("src_key", sa.String(length=100), nullable=False),
        sa.Column("src_type", sa.String(length=50), nullable=False),
        sa.Column("predicate", sa.String(length=100), nullable=False),
        sa.Column("dst_key", sa.String(length=100), nullable=False),
        sa.Column("dst_type", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_topology_edge_community_id", "topology_edge", ["community_id"], unique=False)
    op.create_index("ix_topology_edge_src_key", "topology_edge", ["src_key"], unique=False)
    op.create_index("ix_topology_edge_dst_key", "topology_edge", ["dst_key"], unique=False)
    op.create_index("ix_topology_edge_predicate", "topology_edge", ["predicate"], unique=False)
    op.create_unique_constraint(
        "uq_topology_edge_unique",
        "topology_edge",
        ["community_id", "src_key", "src_type", "predicate", "dst_key", "dst_type"],
    )


def downgrade() -> None:
    op.drop_table("topology_edge")
    op.drop_table("timeseries")
    op.drop_table("tariff")
    op.drop_table("asset")
    op.drop_table("meter")
    op.drop_table("site")
    op.drop_table("membership")
    op.drop_table("participant")
    op.drop_table("community")
