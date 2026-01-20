from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ImportModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class CommunityBlock(ImportModel):
    key: str
    name: str
    description: Optional[str] = None
    external_id: Optional[str] = None


class ParticipantBlock(ImportModel):
    key: str
    name: str
    kind: Optional[str] = None
    external_id: Optional[str] = None
    contacts: Optional[dict] = None
    roles: Optional[List[str]] = None


class MembershipBlock(ImportModel):
    participant: str
    role: str
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    voting_weight: Optional[float] = None


class SiteGeo(ImportModel):
    lat: Optional[float] = None
    lon: Optional[float] = None


class SiteBlock(ImportModel):
    key: str
    name: str
    address: Optional[str] = None
    geo: Optional[SiteGeo] = None


class MeterBlock(ImportModel):
    key: str
    name: str
    pod_code: Optional[str] = None
    site: Optional[str] = None


class AssetBlock(ImportModel):
    key: str
    name: str
    type: str
    site: Optional[str] = None
    meter: Optional[str] = None
    owner: Optional[str] = None
    rated_power_kw: Optional[float] = None
    rated_energy_kwh: Optional[float] = None


class TariffBlock(ImportModel):
    key: str
    name: str
    currency: Optional[str] = None
    notes: Optional[str] = None


class TimeSeriesBlock(ImportModel):
    key: str
    name: str
    metric: str
    unit: Optional[str] = None
    observed_entity: str


class TopologyEdgeBlock(ImportModel):
    from_: str = Field(alias="from")
    predicate: str
    to: str


class TopologyBlock(ImportModel):
    edges: List[TopologyEdgeBlock] = []


class CommunityImportDoc(ImportModel):
    version: int = 1
    context: Optional[str] = None

    community: CommunityBlock
    participants: List[ParticipantBlock] = []
    memberships: List[MembershipBlock] = []
    sites: List[SiteBlock] = []
    meters: List[MeterBlock] = []
    assets: List[AssetBlock] = []
    tariffs: List[TariffBlock] = []
    timeseries: List[TimeSeriesBlock] = []
    topology: Optional[TopologyBlock] = None
