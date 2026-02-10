"""
Pydantic response models for REC Registry API.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


def JsonField(name: str):
    """Create a dict field with explicit schema name to avoid duplicates."""
    return Field(default_factory=dict, json_schema_extra={"title": name})


# =============================================================================
# Generic Pagination
# =============================================================================


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


class CountedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int


# =============================================================================
# Embedded Types
# =============================================================================


class Location(BaseModel):
    lat: float
    lon: float


class Area(BaseModel):
    name: str
    location: Location


class TopologyNode(BaseModel):
    id: str
    type: str
    name: str | None = None
    operator: str | None = None
    parent: str | None = None
    area: dict[str, Any] = JsonField("TopologyNodeArea")


class DeliveryPoint(BaseModel):
    id: str
    type: str
    description: str | None = None
    address: str | None = None
    tariff: str | None = None
    active: bool = True


class Device(BaseModel):
    type: str | None = None
    model: str | None = None
    serial_number: str | None = None
    mac_address: str | None = None
    firmware_version: str | None = None


class AssetRelationships(BaseModel):
    measures: list[str] = Field(default_factory=list)
    paired_with: str | None = None


# =============================================================================
# Admin API - Community Responses
# =============================================================================


class CommunityListItem(BaseModel):
    id: str
    key: str
    name: str
    description: str | None = None
    areas: dict[str, Area] = JsonField("CommunityListItemAreas")


class CommunityDetail(BaseModel):
    id: str
    key: str
    name: str
    description: str | None = None
    legal: dict[str, Any] = JsonField("CommunityDetailLegal")
    links: dict[str, Any] = JsonField("CommunityDetailLinks")
    contact: dict[str, Any] = JsonField("CommunityDetailContact")
    settings: dict[str, Any] = JsonField("CommunityDetailSettings")
    areas: dict[str, Area] = JsonField("CommunityDetailAreas")
    topology: list[TopologyNode] = Field(default_factory=list)
    extra: dict[str, Any] = JsonField("CommunityDetailExtra")
    created_at: str | None = None
    updated_at: str | None = None


class TopologyResponse(BaseModel):
    topology: list[TopologyNode] = Field(default_factory=list)


# =============================================================================
# Admin API - Member Responses
# =============================================================================


class MemberListItem(BaseModel):
    id: str
    key: str
    user_id: str
    name: str
    role: str
    area: str
    status: str
    delivery_points_count: int = 0


class MemberDetail(BaseModel):
    id: str
    key: str
    user_id: str
    name: str
    role: str
    area: str
    status: str
    delivery_points: list[DeliveryPoint] = Field(default_factory=list)
    extra: dict[str, Any] = JsonField("MemberDetailExtra")
    created_at: str | None = None
    updated_at: str | None = None


class DeliveryPointsResponse(BaseModel):
    delivery_points: list[DeliveryPoint] = Field(default_factory=list)


# =============================================================================
# Admin API - Delivery Point Responses
# =============================================================================


class DeliveryPointWithOwner(BaseModel):
    id: str
    key: str
    type: str
    description: str | None = None
    address: str | None = None
    tariff: str | None = None
    active: bool = True
    member_key: str
    member_name: str


class MemberRef(BaseModel):
    key: str
    user_id: str
    name: str
    role: str


class DeliveryPointLookup(BaseModel):
    delivery_point: DeliveryPoint
    member: MemberRef


# =============================================================================
# Admin API - Asset Responses
# =============================================================================


class AssetListItem(BaseModel):
    id: str
    key: str
    asset_type: str
    name: str
    owner_key: str
    owner_user_id: str
    sensor_id: str | None = None
    device_type: str | None = None


class AssetDetail(BaseModel):
    id: str
    key: str
    asset_type: str
    name: str
    owner_key: str
    owner_user_id: str
    sensor_id: str | None = None
    properties: dict[str, Any] = JsonField("AssetDetailProperties")
    device: dict[str, Any] = JsonField("AssetDetailDevice")
    relationships: dict[str, Any] = JsonField("AssetDetailRelationships")
    extra: dict[str, Any] = JsonField("AssetDetailExtra")
    created_at: str | None = None
    updated_at: str | None = None


class MeterListItem(BaseModel):
    id: str
    key: str
    name: str
    sensor_id: str | None = None
    meter_type: str | None = None
    pod: str | None = None
    device: dict[str, Any] = JsonField("MeterListItemDevice")
    owner_key: str
    owner_user_id: str


# =============================================================================
# Admin API - Lookup Responses
# =============================================================================


class CommunityRef(BaseModel):
    id: str
    key: str
    name: str


class MemberInCommunity(BaseModel):
    id: str
    key: str
    user_id: str
    name: str
    role: str
    status: str


class AssetRef(BaseModel):
    id: str
    key: str
    asset_type: str
    name: str
    sensor_id: str | None = None


class LookupByUserIdResponse(BaseModel):
    community: CommunityRef
    member: MemberInCommunity


class LookupBySensorIdResponse(BaseModel):
    community: CommunityRef
    member: MemberInCommunity
    asset: AssetRef


class LookupByDeliveryPointResponse(BaseModel):
    community: CommunityRef
    member: MemberRef
    delivery_point: DeliveryPoint


class GlobalMemberLookup(BaseModel):
    id: str
    key: str
    user_id: str
    name: str
    role: str
    area: str
    status: str
    delivery_points: list[DeliveryPoint] = Field(default_factory=list)
    community_key: str
    community_name: str


class GlobalAssetLookup(BaseModel):
    id: str
    key: str
    asset_type: str
    name: str
    sensor_id: str | None = None
    properties: dict[str, Any] = JsonField("GlobalAssetLookupProperties")
    device: dict[str, Any] = JsonField("GlobalAssetLookupDevice")
    relationships: dict[str, Any] = JsonField("GlobalAssetLookupRelationships")
    owner_key: str
    owner_user_id: str
    community_key: str
    community_name: str


# =============================================================================
# User API - Self-service Responses
# =============================================================================


class UserProfile(BaseModel):
    sub: str
    email: str | None = None
    name: str | None = None
    preferred_username: str | None = None


class UserMemberSummary(BaseModel):
    key: str
    name: str
    role: str
    area: str
    status: str


class UserCommunitySummary(BaseModel):
    key: str
    name: str
    description: str | None = None


class UserMembership(BaseModel):
    member: UserMemberSummary
    community: UserCommunitySummary
    delivery_points_count: int = 0
    assets_count: dict[str, int] = JsonField("UserMembershipAssetsCount")


class UserMeResponse(BaseModel):
    profile: UserProfile
    membership: UserMembership | None = None


class UserMemberDetail(BaseModel):
    key: str
    name: str
    role: str
    area: str
    status: str
    delivery_points: list[DeliveryPoint] = Field(default_factory=list)
    extra: dict[str, Any] = JsonField("UserMemberDetailExtra")
    created_at: str | None = None
    updated_at: str | None = None


class UserCommunityDetail(BaseModel):
    key: str
    name: str
    description: str | None = None
    legal: dict[str, Any] = JsonField("UserCommunityDetailLegal")
    links: dict[str, Any] = JsonField("UserCommunityDetailLinks")
    contact: dict[str, Any] = JsonField("UserCommunityDetailContact")
    settings: dict[str, Any] = JsonField("UserCommunityDetailSettings")
    areas: dict[str, Area] = JsonField("UserCommunityDetailAreas")
    topology: list[TopologyNode] = Field(default_factory=list)
    your_area: str
    your_role: str


class UserAsset(BaseModel):
    key: str
    asset_type: str
    name: str
    sensor_id: str | None = None
    properties: dict[str, Any] = JsonField("UserAssetProperties")
    device: dict[str, Any] = JsonField("UserAssetDevice")
    relationships: dict[str, Any] = JsonField("UserAssetRelationships")


class UserAssetDetail(BaseModel):
    key: str
    asset_type: str
    name: str
    sensor_id: str | None = None
    properties: dict[str, Any] = JsonField("UserAssetDetailProperties")
    device: dict[str, Any] = JsonField("UserAssetDetailDevice")
    relationships: dict[str, Any] = JsonField("UserAssetDetailRelationships")
    extra: dict[str, Any] = JsonField("UserAssetDetailExtra")
    created_at: str | None = None
    updated_at: str | None = None


class UserAssetsResponse(BaseModel):
    items: list[UserAsset]
    total: int


class UserDeliveryPointsResponse(BaseModel):
    items: list[DeliveryPoint]
    total: int
