# celine_registry/bundle.py
from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict


class ContextIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    base: str | None = None
    prefixes: dict[str, str] = Field(default_factory=dict)


class Ref(BaseModel):
    """
    Generic reference object used in Greenland bundles.
    Example: {"kind":"participant","ref":"p_gl_00002"}
    """

    model_config = ConfigDict(extra="ignore")
    kind: str
    ref: str


class CommunityIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    key: str
    iri: str | None = None
    name: str | None = None
    description: str | None = None


class ParticipantIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    key: str
    iri: str | None = None
    kind: str | None = None
    name: str | None = None
    auth_iri: str | None = None


class MembershipIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    key: str
    iri: str | None = None

    # Greenland uses "participant" (string ref), not participant_key
    participant: str

    role: str | None = None
    status: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None


class SiteIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    key: str
    iri: str | None = None
    name: str | None = None
    area: str | None = None


class AssetIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    key: str
    iri: str | None = None
    category: str | None = None
    name: str | None = None

    # Greenland uses owner object and located_at string ref
    owner: Ref
    located_at: str | None = None

    datasets: list[dict] = Field(default_factory=list)


class MeterIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    key: str
    iri: str | None = None
    name: str | None = None

    owner: Ref
    located_at: str | None = None

    sensor_id: str | None = None
    pod: str | None = None

    datasets: list[dict] = Field(default_factory=list)


class RegistryBundleIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    context: ContextIn | None = None
    community: CommunityIn
    participants: list[ParticipantIn] = Field(default_factory=list)
    memberships: list[MembershipIn] = Field(default_factory=list)
    sites: list[SiteIn] = Field(default_factory=list)
    assets: list[AssetIn] = Field(default_factory=list)
    meters: list[MeterIn] = Field(default_factory=list)
