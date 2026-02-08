"""
Initial migration for v0.4 REC Registry schema.

Creates simplified schema:
- community: REC community with embedded areas
- member: community members with role, status, area
- asset: all asset types in one table with type discriminator

Revision ID: 0001_v04_schema
Revises: None
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_v04_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old tables if they exist (clean slate)
    op.execute("DROP TABLE IF EXISTS meter CASCADE")
    op.execute("DROP TABLE IF EXISTS asset CASCADE")
    op.execute("DROP TABLE IF EXISTS site CASCADE")
    op.execute("DROP TABLE IF EXISTS membership CASCADE")
    op.execute("DROP TABLE IF EXISTS participant CASCADE")
    op.execute("DROP TABLE IF EXISTS community CASCADE")

    # ==========================================================================
    # Community table
    # ==========================================================================
    op.create_table(
        "community",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "areas",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_community_key", "community", ["key"], unique=True)

    # ==========================================================================
    # Member table
    # ==========================================================================
    op.create_table(
        "member",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "community_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("community.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=256), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("area", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    
    # Member indexes
    op.create_index("ix_member_community_id", "member", ["community_id"])
    op.create_index("ix_member_user_id", "member", ["user_id"])
    op.create_index("ix_member_role", "member", ["role"])
    op.create_index("ix_member_status", "member", ["status"])
    
    # Member unique constraints
    op.create_unique_constraint(
        "uq_member_community_key", "member", ["community_id", "key"]
    )
    op.create_unique_constraint(
        "uq_member_community_user_id", "member", ["community_id", "user_id"]
    )

    # ==========================================================================
    # Asset table (unified for all asset types)
    # ==========================================================================
    op.create_table(
        "asset",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "community_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("community.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("member.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("asset_type", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("sensor_id", sa.String(length=256), nullable=True),
        sa.Column(
            "properties",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "relationships",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    
    # Asset indexes
    op.create_index("ix_asset_community_id", "asset", ["community_id"])
    op.create_index("ix_asset_owner_id", "asset", ["owner_id"])
    op.create_index("ix_asset_type", "asset", ["asset_type"])
    
    # Partial index for sensor_id lookups (only where sensor_id is not null)
    op.execute("""
        CREATE INDEX ix_asset_sensor_id ON asset (sensor_id)
        WHERE sensor_id IS NOT NULL
    """)
    
    # Composite index for community + sensor_id lookups
    op.execute("""
        CREATE INDEX ix_asset_community_sensor ON asset (community_id, sensor_id)
        WHERE sensor_id IS NOT NULL
    """)
    
    # Asset unique constraint
    op.create_unique_constraint(
        "uq_asset_community_key", "asset", ["community_id", "key"]
    )


def downgrade() -> None:
    op.drop_table("asset")
    op.drop_table("member")
    op.drop_table("community")
