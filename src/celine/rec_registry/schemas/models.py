"""
Pydantic response models for REC Registry API.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

from celine.rec_registry.schemas.bundle import AreaBoundaryIn, MemberIn

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


class AreaBoundary(BaseModel):
    """The primary-substation boundary an area references (REQ-0067)."""

    source: str
    id: str


class Area(BaseModel):
    name: str
    # One primary substation (REQ-0067). An area stored before the rule has no
    # boundary, and may list any number of nodes; both are answered as stored.
    boundary: AreaBoundary | None = None
    topology: list[str] = Field(default_factory=list)
    location: Location | None = None
    geometry: dict[str, Any] | None = None  # GeoJSON geometry (Point, Polygon, MultiPolygon, …)

    @field_validator("boundary", mode="before")
    @classmethod
    def _stored_boundary(cls, value: Any) -> Any:
        # Before v0.7 an area's unknown keys were stored as given, so a row may
        # hold a `boundary` that is not one. Answered as none rather than as a
        # `500` on every read of the community.
        if isinstance(value, dict) and all(
            isinstance(value.get(k), str) for k in ("source", "id")
        ):
            return value
        return None


class TopologyNode(BaseModel):
    """One grid topology node, named as the bundle names it (REQ-0072).

    The fields are the bundle's `TopologyNodeIn` fields, under the same names:
    `operator_id` (a key of the community's `operators`, since schema v0.5) and
    `parent` (the id of the node above this one). Before 1.6.0 this model
    answered `operator`, a v0.4 name nothing has stored since, so it was
    always `null` while the stored `operator_id` was never returned.
    """

    id: str
    type: str
    name: str | None = None
    operator_id: str | None = None
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
    did: str | None = None
    name: str
    role: str
    area: str
    status: str
    delivery_points_count: int = 0


class MemberDetail(BaseModel):
    id: str
    key: str
    user_id: str
    did: str | None = None
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
    # Present so a batch answer can be attributed back to the DID that was asked
    # about, the same job `owner_user_id` does for `GlobalAssetLookup`.
    did: str | None = None
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
    # Returned, unlike `user_id`, because the two are not the same kind of
    # omission: the caller already knows the username they authenticated with,
    # and does not know the DID an onboarding service minted on their behalf.
    did: str | None = None


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
    did: str | None = None
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

# One number, read by both batch models. Writing it twice is how the two came to
# disagree in the first place — the bound arrived with the newer endpoint and was
# not applied to the older one, and nothing about two literals would have stopped
# that happening again.
#
# The value is arbitrary; what is load-bearing is that a bound exists. Raising it
# widens a data-exfiltration path — it is a security decision wearing the clothes
# of a validation constant.
MAX_BATCH_LOOKUP_IDS = 500


class SensorIdsBatchRequest(BaseModel):
    """Sensors to resolve owners for.

    Bounded for the same reason as its sibling below, and by the same number.
    Sensor ids are less guessable than usernames, which makes this the weaker
    enumeration path — but not the weaker *bulk extraction* one: a caller
    holding a list of them resolves every owner and community in one request.
    """

    sensor_ids: list[str] = Field(..., max_length=MAX_BATCH_LOOKUP_IDS)


class UserIdsBatchRequest(BaseModel):
    """Members to resolve assets for.

    Bounded on purpose. A caller that can name ten thousand people in one
    request has a dump of the registry, not a lookup, and the endpoint is
    reachable by anything holding `rec-registry.lookup`.
    """

    user_ids: list[str] = Field(..., max_length=MAX_BATCH_LOOKUP_IDS)


class DidsBatchRequest(BaseModel):
    """Members to resolve by their dataspace DID.

    Bounded by the same constant as its two siblings, for the same reason: a
    caller naming ten thousand DIDs in one request has a dump of the registry
    rather than a lookup.

    A DID is the identifier a consent record is written in, so the set the
    caller holds is the set of people who consented — and this endpoint turns
    that into the supply points they hold. Which makes the bound the same
    security decision it is on the other two.
    """

    dids: list[str] = Field(..., max_length=MAX_BATCH_LOOKUP_IDS)

# =============================================================================
# Write requests (Admin)
# =============================================================================
#
# Member and asset payloads reuse the bundle component models rather than
# declaring parallel ones: a member created through the API and one that arrived
# in a YAML bundle must be the same row, and two schemas for the same object
# drift on the first schema-version bump.


class MemberCreate(MemberIn):
    """Create one member. `key` is minted from the community's own numbering
    when omitted, so a caller with no opinion still gets `ex-00007` rather than
    something that reads as foreign in an exported bundle."""

    key: str | None = None
    # Declared so it merges into `Member.extra` at the level `PATCH` merges it.
    # Left undeclared, `extra="allow"` copied it in as one more unknown key, and
    # a client sending the same body to both routes got `extra.extra` on create
    # and `extra` on patch. Not declared on the bundle `MemberIn`: there a
    # member's unknown keys already are the top level of `extra`.
    extra: dict[str, Any] | None = None


class MemberPatch(BaseModel):
    """Partial update. Absent fields are left alone, never cleared.

    `delivery_points` is deliberately absent: it is a JSONB list, and a patch
    that happened to omit it would otherwise read as "this member now has none".
    It has its own sub-resource.
    """

    user_id: str | None = None
    # The route ../onboarding writes the dataspace identity through, because the
    # DID is minted a step after the member is registered. Reassigning one that
    # another member already holds is `409`; re-sending a member its own DID is
    # a no-op success, because that write sits inside a retriable step.
    did: str | None = None
    name: str | None = None
    type: str | None = None
    role: str | None = None
    area: str | None = None
    status: str | None = None
    extra: dict[str, Any] | None = None


def _no_default(schema: dict[str, Any]) -> None:
    """Drop a `"default": null` that would contradict a non-nullable type."""
    schema.pop("default", None)


class MemberProfilePatch(BaseModel):
    """A member's role and area, and nothing else (REQ-0070).

    At least one of the two, and no other key: a body that could carry a
    `user_id` would hand the narrower `members.profile.write` grant the identity
    rewrite REQ-0022 exists to stop. Absent fields are left alone; neither may
    be sent as `null`, since a member always has both.

    The values are checked against their sets by the route, with a coded `422`
    (`invalid_role`, `unknown_area`; REQ-0066), not here — a validation error
    here has no `code`.
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra={"minProperties": 1})

    # Optional but never `null`: `SkipJsonSchema[None]` keeps `null` out of the
    # published schema, since the validator below refuses it with a `422`.
    role: str | SkipJsonSchema[None] = Field(
        default=None,
        description="One of consumer, prosumer, producer, operator, admin.",
        json_schema_extra=_no_default,
    )
    area: str | SkipJsonSchema[None] = Field(
        default=None,
        description="A key of the community's `areas`.",
        json_schema_extra=_no_default,
    )

    @model_validator(mode="after")
    def _names_one_and_no_null(self) -> "MemberProfilePatch":
        if not self.model_fields_set:
            raise ValueError("name at least one of role, area")
        for name in sorted(self.model_fields_set):
            if getattr(self, name) is None:
                raise ValueError(f"{name} may not be null")
        return self


class MemberStatusChange(BaseModel):
    """Move a member through `pending → active → suspended → inactive`."""

    status: str
    reason: str | None = None


class AssetUpsert(BaseModel):
    """Create or replace one asset of a member.

    `properties` is validated against the model for `asset_type`, so an EV
    charger cannot be stored with a heat pump's fields.
    """

    key: str
    asset_type: str
    properties: dict[str, Any] = JsonField("AssetUpsertProperties")


class DeletionReport(BaseModel):
    """What a delete did.

    `purged` distinguishes deactivation from erasure — the same endpoint does
    both, and the caller should be able to tell which happened.
    """

    community_key: str
    member_key: str
    purged: bool
    status: str | None = None
    assets_removed: int = 0


def _no_default_area(schema: dict[str, Any]) -> None:
    """Drop the `"default": null` of a field that is refused when absent."""
    schema.pop("default", None)


class AreaUpsert(BaseModel):
    """Create or replace one area of a community.

    One primary substation (REQ-0067): `boundary` references it and `topology`
    lists exactly one node id, `boundary.id`, a `primary_substation` node of
    the community's topology. Anything else — no boundary, a list of them or a
    malformed one included — is `422 invalid_area_boundary`; `boundary`
    accepts anything in the model only so that each of those is refused with
    that code rather than as a validation error.
    """

    name: str
    boundary: AreaBoundaryIn | SkipJsonSchema[Any] = Field(
        default=None,
        union_mode="left_to_right",
        description="The primary-substation boundary, `{source, id}`. Required.",
        json_schema_extra=_no_default_area,
    )
    location: Location | None = None
    geometry: dict[str, Any] | None = None
    topology: list[str] = Field(
        default_factory=list,
        description="Exactly one node id: `boundary.id`.",
    )


class AreaRename(BaseModel):
    """Move an area to a new key, with its members (REQ-0079).

    `new_key` only; any other key is `422`. A key that is not an area key —
    letters, digits, `-` and `_`, starting with a letter or digit, at most 128
    characters — is refused `422 invalid_area_key`.
    """

    model_config = ConfigDict(extra="forbid")

    new_key: str = Field(description="The key the area is moved to.")


class AreaRenamed(BaseModel):
    """What a rename did (REQ-0079): the two keys, how many members moved, and
    the whole community after it, so the caller can see the others are still
    there."""

    old_key: str
    new_key: str
    members_moved: int = Field(
        description="Members of the community, of any status, moved to `new_key`."
    )
    community: CommunityDetail


class CommunityPatch(BaseModel):
    """Partial update of community metadata.

    Areas and topology are not here: they are collections with their own
    identity, and a patch omitting them must not read as "this community now
    has none".
    """

    name: str | None = None
    description: str | None = None
    legal: dict[str, Any] | None = None
    links: dict[str, Any] | None = None
    contact: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None
    extra: dict[str, Any] | None = None
