"""
Pydantic schemas for v0.4 Registry Bundle format.

Supports:
- Community with legal, links, contact, settings, areas, topology
- Members with delivery_points
- Assets with device specifications
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# Location / Area
# =============================================================================

class LocationIn(BaseModel):
    """Geographic location."""
    model_config = ConfigDict(extra="allow")

    lat: float
    lon: float


class AreaIn(BaseModel):
    """Community area definition."""
    model_config = ConfigDict(extra="allow")

    name: str
    location: LocationIn


# =============================================================================
# Topology
# =============================================================================

class TopologyNodeIn(BaseModel):
    """Grid topology node (substation, transformer, etc.)."""
    model_config = ConfigDict(extra="allow")

    id: str
    type: str  # primary_substation, secondary_substation, transformer, feeder
    name: str | None = None
    operator: str | None = None
    parent: str | None = None
    area: dict | None = None  # GeoJSON geometry


# =============================================================================
# Community Details
# =============================================================================

class LegalInfoIn(BaseModel):
    """Legal and administrative details."""
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    vat: str | None = None
    fiscal_code: str | None = None
    legal_form: str | None = None
    registration_number: str | None = None
    registered_office: str | None = None


class LinksIn(BaseModel):
    """Public URLs for the community."""
    model_config = ConfigDict(extra="allow")

    website: str | None = None
    logo: str | None = None
    privacy_policy: str | None = None
    terms: str | None = None
    statute: str | None = None
    regulations: str | None = None


class ContactIn(BaseModel):
    """Contact information."""
    model_config = ConfigDict(extra="allow")

    email: str | None = None
    pec: str | None = None
    phone: str | None = None
    address: str | None = None


class SettingsIn(BaseModel):
    """Operational settings."""
    model_config = ConfigDict(extra="allow")

    timezone: str | None = None
    currency: str | None = None
    energy_unit: str | None = None
    power_unit: str | None = None


# =============================================================================
# Delivery Points
# =============================================================================

class DeliveryPointIn(BaseModel):
    """Physical delivery point (POD, CUPS, PRM, etc.)."""
    model_config = ConfigDict(extra="allow")

    id: str
    type: str  # pod, cups, prm, malo, ean, mpan, other
    description: str | None = None
    address: str | None = None
    tariff: str | None = None
    active: bool = True


# =============================================================================
# Device Specification
# =============================================================================

class DeviceIn(BaseModel):
    """SAREF-inspired device specification."""
    model_config = ConfigDict(extra="allow")

    type: str | None = None  # shelly, fronius, sma, etc.
    model: str | None = None
    serial_number: str | None = None
    mac_address: str | None = None
    firmware_version: str | None = None


# =============================================================================
# Asset Relationships
# =============================================================================

class AssetRelationshipsIn(BaseModel):
    """Relationships between assets."""
    model_config = ConfigDict(extra="allow")

    measures: list[str] = Field(default_factory=list)
    paired_with: str | None = None


# =============================================================================
# Asset Types
# =============================================================================

class PVAssetIn(BaseModel):
    """PV system asset."""
    model_config = ConfigDict(extra="allow")

    name: str
    rated_power: float | None = None
    panel_type: str | None = None
    inverter_power: float | None = None
    orientation: float | None = None
    tilt_angle: float | None = None
    installation_date: str | None = None
    device: DeviceIn | None = None
    relationships: AssetRelationshipsIn = Field(default_factory=AssetRelationshipsIn)


class StorageAssetIn(BaseModel):
    """Battery storage asset."""
    model_config = ConfigDict(extra="allow")

    name: str
    capacity: float | None = None
    max_charge_power: float | None = None
    max_discharge_power: float | None = None
    battery_type: str | None = None
    round_trip_efficiency: float | None = None
    installation_date: str | None = None
    device: DeviceIn | None = None
    relationships: AssetRelationshipsIn = Field(default_factory=AssetRelationshipsIn)


class MeterAssetIn(BaseModel):
    """Meter asset."""
    model_config = ConfigDict(extra="allow")

    name: str
    sensor_id: str
    meter_type: str  # consumption, production, bidirectional, import, export
    pod: str | None = None  # reference to delivery point id
    protocol: str | None = None
    installation_date: str | None = None
    device: DeviceIn | None = None
    relationships: AssetRelationshipsIn = Field(default_factory=AssetRelationshipsIn)


class EVChargerAssetIn(BaseModel):
    """EV charger asset."""
    model_config = ConfigDict(extra="allow")

    name: str
    max_power: float
    charger_type: str  # ac_level1, ac_level2, dc_fast, dc_ultra_fast
    connector_types: list[str] = Field(default_factory=list)
    smart_charging: bool | None = None
    bidirectional: bool | None = None
    num_ports: int | None = None
    installation_date: str | None = None
    device: DeviceIn | None = None
    relationships: AssetRelationshipsIn = Field(default_factory=AssetRelationshipsIn)


class HeatPumpAssetIn(BaseModel):
    """Heat pump asset."""
    model_config = ConfigDict(extra="allow")

    name: str
    thermal_power: float
    electrical_power: float | None = None
    cop: float | None = None
    eer: float | None = None
    scop: float | None = None
    seer: float | None = None
    heat_pump_type: str | None = None  # air_to_air, air_to_water, ground_source, water_source
    reversible: bool | None = None
    refrigerant: str | None = None
    installation_date: str | None = None
    device: DeviceIn | None = None
    relationships: AssetRelationshipsIn = Field(default_factory=AssetRelationshipsIn)


class LoadAssetIn(BaseModel):
    """Load asset."""
    model_config = ConfigDict(extra="allow")

    name: str
    load_type: str | None = None  # hvac, lighting, appliance, industrial, process, etc.
    rated_power: float | None = None
    min_power: float | None = None
    controllable: bool | None = None
    priority: str | None = None  # critical, high, medium, low
    flexibility_kw: float | None = None
    device: DeviceIn | None = None
    relationships: AssetRelationshipsIn = Field(default_factory=AssetRelationshipsIn)


# =============================================================================
# Asset Collection
# =============================================================================

class AssetCollectionIn(BaseModel):
    """Collection of assets organized by type."""
    model_config = ConfigDict(extra="allow")

    pv: dict[str, PVAssetIn] = Field(default_factory=dict)
    storage: dict[str, StorageAssetIn] = Field(default_factory=dict)
    meter: dict[str, MeterAssetIn] = Field(default_factory=dict)
    ev_charger: dict[str, EVChargerAssetIn] = Field(default_factory=dict)
    heat_pump: dict[str, HeatPumpAssetIn] = Field(default_factory=dict)
    load: dict[str, LoadAssetIn] = Field(default_factory=dict)


# =============================================================================
# Member
# =============================================================================

class MemberIn(BaseModel):
    """Community member."""
    model_config = ConfigDict(extra="allow")

    user_id: str
    name: str
    role: str  # consumer, prosumer, producer, operator, admin
    area: str  # reference to community area key
    status: str  # pending, active, suspended, inactive
    delivery_points: list[DeliveryPointIn] = Field(default_factory=list)
    assets: AssetCollectionIn = Field(default_factory=AssetCollectionIn)


# =============================================================================
# Community
# =============================================================================

class CommunityIn(BaseModel):
    """Community definition."""
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    description: str | None = None
    legal: LegalInfoIn | None = None
    links: LinksIn | None = None
    contact: ContactIn | None = None
    settings: SettingsIn | None = None
    areas: dict[str, AreaIn] = Field(default_factory=dict)
    topology: list[TopologyNodeIn] = Field(default_factory=list)


# =============================================================================
# Metadata
# =============================================================================

class MetadataIn(BaseModel):
    """Registry metadata."""
    model_config = ConfigDict(extra="allow")

    created: str | None = None
    updated: str | None = None
    updated_by: str | None = None
    description: str | None = None


# =============================================================================
# Registry Bundle
# =============================================================================

class RegistryBundleIn(BaseModel):
    """
    Complete registry bundle for import.
    
    Matches v0.4 structure.
    """
    model_config = ConfigDict(extra="allow")

    version: str = "1.0"
    schema_version: str = "1.0"
    metadata: MetadataIn | None = None
    community: CommunityIn
    members: dict[str, MemberIn] = Field(default_factory=dict)


# =============================================================================
# Admin Schemas
# =============================================================================

class ImportRequest(BaseModel):
    """Import request payload."""
    bundle: RegistryBundleIn
    dry_run: bool = False


class ImportReport(BaseModel):
    """Import operation report."""
    community_key: str
    deleted: dict[str, int] = Field(default_factory=dict)
    inserted: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
