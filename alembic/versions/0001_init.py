from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "community",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("iri", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.String(length=256), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "participant",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "community_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("community.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("iri", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=256), nullable=True),
        sa.Column("auth_iri", sa.Text(), nullable=True),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint("community_id", "key", name="uq_participant_community_key"),
    )
    op.create_index("ix_participant_community_id", "participant", ["community_id"])

    op.create_table(
        "site",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "community_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("community.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("iri", sa.Text(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=True),
        sa.Column("area", sa.String(length=256), nullable=True),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint("community_id", "key", name="uq_site_community_key"),
    )
    op.create_index("ix_site_community_id", "site", ["community_id"])

    op.create_table(
        "membership",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "community_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("community.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "participant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("participant.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("iri", sa.Text(), nullable=False),
        sa.Column("role_iri", sa.Text(), nullable=True),
        sa.Column("status_iri", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.String(length=64), nullable=True),
        sa.Column("valid_to", sa.String(length=64), nullable=True),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint("community_id", "key", name="uq_membership_community_key"),
        sa.UniqueConstraint(
            "community_id", "participant_id", name="uq_membership_community_participant"
        ),
    )
    op.create_index("ix_membership_community_id", "membership", ["community_id"])
    op.create_index("ix_membership_participant_id", "membership", ["participant_id"])

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
            "owner_participant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("participant.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "site_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("site.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("iri", sa.Text(), nullable=False),
        sa.Column("category_iri", sa.Text(), nullable=True),
        sa.Column("name", sa.String(length=256), nullable=True),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint("community_id", "key", name="uq_asset_community_key"),
    )
    op.create_index("ix_asset_community_id", "asset", ["community_id"])
    op.create_index("ix_asset_owner_participant_id", "asset", ["owner_participant_id"])
    op.create_index("ix_asset_site_id", "asset", ["site_id"])

    op.create_table(
        "meter",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "community_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("community.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_participant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("participant.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "site_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("site.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("iri", sa.Text(), nullable=False),
        sa.Column("sensor_id", sa.String(length=256), nullable=True),
        sa.Column("pod", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=256), nullable=True),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint("community_id", "key", name="uq_meter_community_key"),
    )
    op.create_index("ix_meter_community_id", "meter", ["community_id"])
    op.create_index("ix_meter_owner_participant_id", "meter", ["owner_participant_id"])
    op.create_index("ix_meter_site_id", "meter", ["site_id"])
    op.create_index("ix_meter_sensor_id", "meter", ["sensor_id"])


def downgrade() -> None:
    op.drop_table("meter")
    op.drop_table("asset")
    op.drop_table("membership")
    op.drop_table("site")
    op.drop_table("participant")
    op.drop_table("community")
