"""
Pydantic schemas for v0.4 Registry Bundle format.

Matches the v0.4 bundle structure:
- version, schema_version, metadata
- community with id, name, description, areas
- members dict keyed by member_id
- member assets organized by type (pv, storage, meter, etc.)
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
    location: str | None = None
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
    location: str | None = None
    relationships: AssetRelationshipsIn = Field(default_factory=AssetRelationshipsIn)


class MeterAssetIn(BaseModel):
    """Meter asset."""
    model_config = ConfigDict(extra="allow")
    
    name: str
    sensor_id: str
    meter_type: str  # consumption, production, bidirectional, import, export
    protocol: str | None = None
    installation_date: str | None = None
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
    installation_date: str | None = None
    location: str | None = None
    relationships: AssetRelationshipsIn = Field(default_factory=AssetRelationshipsIn)


class HeatPumpAssetIn(BaseModel):
    """Heat pump asset."""
    model_config = ConfigDict(extra="allow")
    
    name: str
    thermal_power: float
    electrical_power: float | None = None
    cop: float | None = None
    eer: float | None = None
    heat_pump_type: str | None = None  # air_to_air, air_to_water, ground_source, water_source
    reversible: bool | None = None
    installation_date: str | None = None
    location: str | None = None
    relationships: AssetRelationshipsIn = Field(default_factory=AssetRelationshipsIn)


class LoadAssetIn(BaseModel):
    """Load asset."""
    model_config = ConfigDict(extra="allow")
    
    name: str
    load_type: str | None = None  # hvac, lighting, appliance, industrial, other
    rated_power: float | None = None
    controllable: bool | None = None
    priority: str | None = None  # critical, high, medium, low
    location: str | None = None
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
    areas: dict[str, AreaIn] = Field(default_factory=dict)
    assets: AssetCollectionIn = Field(default_factory=AssetCollectionIn)  # Community-owned assets


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
