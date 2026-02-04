# celine_registry/models.py
from __future__ import annotations

import uuid

from sqlalchemy import String, ForeignKey, UniqueConstraint, Index, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from celine.rec_registry.db.session import Base


class Community(Base):
    __tablename__ = "community"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Stable external identifier
    key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    # Expanded, absolute IRI (actionable API IRI or explicit IRI from YAML)
    iri: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Forward-compatible extension fields
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Community-scoped dependents: replacement import deletes these by deleting Community
    participants: Mapped[list["Participant"]] = relationship(
        back_populates="community",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="community",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    sites: Mapped[list["Site"]] = relationship(
        back_populates="community",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    assets: Mapped[list["Asset"]] = relationship(
        back_populates="community",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    meters: Mapped[list["Meter"]] = relationship(
        back_populates="community",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Participant(Base):
    __tablename__ = "participant"
    __table_args__ = (
        UniqueConstraint("community_id", "key", name="uq_participant_community_key"),
        Index("ix_participant_community_id", "community_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    community_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("community.id", ondelete="CASCADE"),
        nullable=False,
    )

    key: Mapped[str] = mapped_column(String(128), nullable=False)
    iri: Mapped[str] = mapped_column(Text, nullable=False)

    # Optional participant typing (org/individual/dso/etc.)
    kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Optional expanded IRI for auth identity (e.g., Keycloak subject IRI)
    auth_iri: Mapped[str | None] = mapped_column(Text, nullable=True)

    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    community: Mapped["Community"] = relationship(back_populates="participants")

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="participant",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Membership(Base):
    __tablename__ = "membership"
    __table_args__ = (
        UniqueConstraint("community_id", "key", name="uq_membership_community_key"),
        UniqueConstraint(
            "community_id", "participant_id", name="uq_membership_community_participant"
        ),
        Index("ix_membership_community_id", "community_id"),
        Index("ix_membership_participant_id", "participant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    community_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("community.id", ondelete="CASCADE"),
        nullable=False,
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("participant.id", ondelete="CASCADE"),
        nullable=False,
    )

    key: Mapped[str] = mapped_column(String(128), nullable=False)
    iri: Mapped[str] = mapped_column(Text, nullable=False)

    # Expanded IRIs (no CURIEs)
    role_iri: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_iri: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional temporal validity (kept string to avoid date parsing policy constraints)
    valid_from: Mapped[str | None] = mapped_column(String(64), nullable=True)
    valid_to: Mapped[str | None] = mapped_column(String(64), nullable=True)

    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    community: Mapped["Community"] = relationship(back_populates="memberships")
    participant: Mapped["Participant"] = relationship(back_populates="memberships")


class Site(Base):
    __tablename__ = "site"
    __table_args__ = (
        UniqueConstraint("community_id", "key", name="uq_site_community_key"),
        Index("ix_site_community_id", "community_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    community_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("community.id", ondelete="CASCADE"),
        nullable=False,
    )

    key: Mapped[str] = mapped_column(String(128), nullable=False)
    iri: Mapped[str] = mapped_column(Text, nullable=False)

    name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Keep as a simple string; can be normalized later (geo areas, municipalities, etc.)
    area: Mapped[str | None] = mapped_column(String(256), nullable=True)

    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    community: Mapped["Community"] = relationship(back_populates="sites")


class Asset(Base):
    __tablename__ = "asset"
    __table_args__ = (
        UniqueConstraint("community_id", "key", name="uq_asset_community_key"),
        Index("ix_asset_community_id", "community_id"),
        Index("ix_asset_owner_participant_id", "owner_participant_id"),
        Index("ix_asset_site_id", "site_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    community_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("community.id", ondelete="CASCADE"),
        nullable=False,
    )

    owner_participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("participant.id", ondelete="CASCADE"),
        nullable=False,
    )

    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("site.id", ondelete="SET NULL"),
        nullable=True,
    )

    key: Mapped[str] = mapped_column(String(128), nullable=False)
    iri: Mapped[str] = mapped_column(Text, nullable=False)

    # Expanded IRI for asset category/type (PV, storage, etc.)
    category_iri: Mapped[str | None] = mapped_column(Text, nullable=True)

    name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    community: Mapped["Community"] = relationship(back_populates="assets")


class Meter(Base):
    __tablename__ = "meter"
    __table_args__ = (
        UniqueConstraint("community_id", "key", name="uq_meter_community_key"),
        Index("ix_meter_community_id", "community_id"),
        Index("ix_meter_owner_participant_id", "owner_participant_id"),
        Index("ix_meter_site_id", "site_id"),
        Index("ix_meter_sensor_id", "sensor_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    community_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("community.id", ondelete="CASCADE"),
        nullable=False,
    )

    owner_participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("participant.id", ondelete="CASCADE"),
        nullable=False,
    )

    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("site.id", ondelete="SET NULL"),
        nullable=True,
    )

    key: Mapped[str] = mapped_column(String(128), nullable=False)
    iri: Mapped[str] = mapped_column(Text, nullable=False)

    # External sensor identifier as provided by the operator (used to locate timeseries elsewhere)
    sensor_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Optional POD code (Italy)
    pod: Mapped[str | None] = mapped_column(String(64), nullable=True)

    name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    community: Mapped["Community"] = relationship(back_populates="meters")
