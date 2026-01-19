from __future__ import annotations

from typing import Any, List, Optional

from pydantic import Field

from .jsonld import JsonLdNode


class CommunityRead(JsonLdNode):
    name: str
    description: Optional[str] = None
    external_id: Optional[str] = None


class ParticipantRead(JsonLdNode):
    name: str
    kind: Optional[str] = None
    external_id: Optional[str] = None
    email: Optional[str] = None


class MembershipRead(JsonLdNode):
    participant: str = Field(alias="participant")
    role: str
    valid_from: Optional[str] = Field(default=None, alias="validFrom")
    valid_to: Optional[str] = Field(default=None, alias="validTo")
    voting_weight: Optional[float] = Field(default=None, alias="votingWeight")


class SiteRead(JsonLdNode):
    name: str
    address: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


class MeterRead(JsonLdNode):
    name: str
    pod_code: Optional[str] = Field(default=None, alias="podCode")
    site: Optional[str] = None


class AssetRead(JsonLdNode):
    name: str
    asset_type: str = Field(alias="assetType")
    site: Optional[str] = None
    meter: Optional[str] = None
    owner: Optional[str] = None
    rated_power_kw: Optional[float] = Field(default=None, alias="ratedPowerKw")
    rated_energy_kwh: Optional[float] = Field(default=None, alias="ratedEnergyKwh")


class TariffRead(JsonLdNode):
    name: str
    currency: Optional[str] = None
    notes: Optional[str] = None


class TimeSeriesRead(JsonLdNode):
    name: str
    metric: str
    unit: Optional[str] = None
    observed_entity: str = Field(alias="observedEntity")


class TopologyEdgeRead(JsonLdNode):
    from_id: str = Field(alias="from")
    predicate: str
    to_id: str = Field(alias="to")
