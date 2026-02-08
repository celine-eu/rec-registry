"""
CELINE REC Registry - Database Models (v0.4 Schema)

Simplified flat model:
- Community: REC community with embedded areas, topology, legal, links, contact, settings
- Member: Community member with role, status, area reference, delivery_points
- Asset: All asset types (pv, storage, meter, ev_charger, heat_pump, load) in one table
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import String, ForeignKey, UniqueConstraint, Index, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from celine.rec_registry.db.session import Base


class Community(Base):
    """
    Renewable Energy Community.
    
    Areas stored as embedded JSONB:
    {
        "area_north": {"name": "North Area", "location": {"lat": 45.0, "lon": 11.0}},
        ...
    }
    
    Topology stored as JSONB list:
    [
        {"id": "PS-001", "type": "primary_substation", "name": "...", "operator": "..."},
        {"id": "SS-001", "type": "secondary_substation", "parent": "PS-001", ...},
    ]
    
    Legal, links, contact, settings stored as JSONB dicts.
    """
    __tablename__ = "community"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Stable key identifier (e.g., "my_rec")
    key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Embedded areas as JSONB
    areas: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # Grid topology as JSONB list of nodes
    topology: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )

    # Legal information as JSONB
    # {name, vat, fiscal_code, legal_form, registration_number, registered_office}
    legal: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # Public links as JSONB
    # {website, logo, privacy_policy, terms, statute, regulations}
    links: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # Contact information as JSONB
    # {email, pec, phone, address}
    contact: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # Operational settings as JSONB
    # {timezone, currency, energy_unit, power_unit}
    settings: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # Extension fields for future use
    extra: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    members: Mapped[list["Member"]] = relationship(
        back_populates="community",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    assets: Mapped[list["Asset"]] = relationship(
        back_populates="community",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_community_key", "key", unique=True),
    )


class Member(Base):
    """
    Community member (participant).
    
    - key: internal member key (e.g., "gl-00001")
    - user_id: external identity system identifier (e.g., Keycloak UUID)
    - role: consumer, prosumer, producer, operator, admin
    - status: pending, active, suspended, inactive
    - area: reference to community area key
    - delivery_points: list of physical delivery points (POD, CUPS, etc.)
    
    Delivery points stored as JSONB list:
    [
        {"id": "IT001E...", "type": "pod", "description": "Main", "tariff": "...", "active": true},
        ...
    ]
    """
    __tablename__ = "member"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    community_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("community.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Internal key (e.g., "gl-00001")
    key: Mapped[str] = mapped_column(String(128), nullable=False)

    # External user identifier (e.g., Keycloak UUID)
    user_id: Mapped[str] = mapped_column(String(256), nullable=False)

    name: Mapped[str] = mapped_column(String(256), nullable=False)

    # Role: consumer, prosumer, producer, operator, admin
    role: Mapped[str] = mapped_column(String(64), nullable=False)

    # Reference to area key in community.areas
    area: Mapped[str] = mapped_column(String(128), nullable=False)

    # Status: pending, active, suspended, inactive
    status: Mapped[str] = mapped_column(String(64), nullable=False)

    # Delivery points as JSONB list
    delivery_points: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )

    # Extension fields
    extra: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    community: Mapped["Community"] = relationship(back_populates="members")
    assets: Mapped[list["Asset"]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("community_id", "key", name="uq_member_community_key"),
        UniqueConstraint("community_id", "user_id", name="uq_member_community_user_id"),
        Index("ix_member_community_id", "community_id"),
        Index("ix_member_user_id", "user_id"),
        Index("ix_member_role", "role"),
        Index("ix_member_status", "status"),
    )


class Asset(Base):
    """
    Unified asset table for all asset types.
    
    asset_type: pv, storage, meter, ev_charger, heat_pump, load
    
    Type-specific properties stored in JSONB `properties`:
    - pv: rated_power, panel_type, inverter_power, orientation, tilt_angle
    - storage: capacity, max_charge_power, max_discharge_power, battery_type
    - meter: meter_type, pod, protocol
    - ev_charger: max_power, charger_type, connector_types, smart_charging, bidirectional
    - heat_pump: thermal_power, electrical_power, cop, eer, heat_pump_type
    - load: load_type, rated_power, controllable, priority
    
    For meters, sensor_id is promoted to a column for efficient lookup.
    
    Device specification stored in JSONB `device`:
    {type, model, serial_number, mac_address, firmware_version}
    
    Relationships stored in JSONB `relationships`:
    - measures: list of asset keys this asset measures
    - paired_with: asset key this asset is paired with
    """
    __tablename__ = "asset"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    community_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("community.id", ondelete="CASCADE"),
        nullable=False,
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("member.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Asset key (e.g., "pv-gl-00002", "meter-gl-00002")
    key: Mapped[str] = mapped_column(String(128), nullable=False)

    # Asset type discriminator
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)

    name: Mapped[str] = mapped_column(String(256), nullable=False)

    # Promoted column for meter sensor_id (enables efficient lookup)
    # Only populated for asset_type='meter'
    sensor_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Type-specific properties as JSONB
    properties: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # SAREF-inspired device specification as JSONB
    # {type, model, serial_number, mac_address, firmware_version}
    device: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # Asset relationships as JSONB
    # {"measures": ["asset-key-1", "asset-key-2"], "paired_with": "asset-key-3"}
    relationships: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # Extension fields
    extra: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    community: Mapped["Community"] = relationship(back_populates="assets")
    owner: Mapped["Member"] = relationship(back_populates="assets")

    __table_args__ = (
        UniqueConstraint("community_id", "key", name="uq_asset_community_key"),
        Index("ix_asset_community_id", "community_id"),
        Index("ix_asset_owner_id", "owner_id"),
        Index("ix_asset_type", "asset_type"),
        # Partial index for meter sensor_id lookups (only where sensor_id is not null)
        Index(
            "ix_asset_sensor_id",
            "sensor_id",
            postgresql_where=(sensor_id.isnot(None)),
        ),
        # Composite index for common query: find meters by community + sensor_id
        Index(
            "ix_asset_community_sensor",
            "community_id",
            "sensor_id",
            postgresql_where=(sensor_id.isnot(None)),
        ),
    )
