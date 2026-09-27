# API Reference

## Authorization

`/admin` routes need a JWT and an OPA decision. The action is derived from the
path **and** the HTTP method, so reads and writes are separate grants. Only the
route's fixed segments are read, each at its position: a member key, asset key or
any other id containing `lookup`, `import` or `export` never changes the action,
and a path matching no route derives `admin`, which only `rec-registry.admin`
satisfies (REQ-0065).

| Action | Reached by | Scope |
|---|---|---|
| `read` | any `GET` under `/admin` | `rec-registry.read` |
| `members.write` | write methods on `…/members…`, delivery points included | `rec-registry.members.write` |
| `members.purge` | `DELETE …/members/{key}?purge=true` | `rec-registry.members.purge` |
| `assets.write` | write methods on `…/assets…` | `rec-registry.assets.write` |
| `community.write` | write methods on a community or its areas | `rec-registry.community.write` |
| `import` / `export` | `/admin/import*`, `/admin/export` | `rec-registry.import` / `.export` |
| `lookup` | `/admin/lookup/*` | `rec-registry.lookup` |
| `assets.lookup` | `/admin/lookup/assets-by-user-ids`, `/admin/lookup/members-by-dids` | `rec-registry.lookup` |

`rec-registry.admin` satisfies all of them (the shared matcher treats
`{service}.admin` as covering `{service}.*`), so existing tokens keep working —
but **do not give it to a service account**. Grant the actions it calls: a
service that registers approved participants needs `members.write`, one that
attaches meters needs `assets.write`, and neither has any business importing,
exporting or purging.

Interactive OpenAPI docs are available at `http://localhost:8004/docs`.

## Refusal codes

A refusal a caller is expected to act on answers

```json
{"detail": "This sensor is already held by another active member", "code": "sensor_held"}
```

`detail` is a sentence for people and stays a string; branch on `code`, never on
the wording (REQ-0073). The OpenAPI document names the body `ErrorResponse` and the
codes `ErrorCode`.

| Code | Status | Refusal |
|---|---|---|
| `community_not_found` | `404` | a write naming an unknown community |
| `member_not_found` | `404` | a write naming a member the community does not have |
| `asset_not_found` | `404` | deleting an asset the member does not hold |
| `member_key_taken` | `409` | the member key is taken in the community |
| `user_id_taken` | `409` | the `user_id` is taken in the community |
| `did_taken` | `409` | the DID is held by another member anywhere |
| `asset_key_taken` | `409` | the asset key is held by another member of the community |
| `asset_key_too_long` | `422` | the asset key is longer than 128 characters (asset `PUT`, member create, import) |
| `sensor_held` | `409` (`422` on an import) | another active member, in any community, holds the sensor |
| `area_in_use` | `409` | deleting an area members still reference |
| `invalid_status` | `422` | a status outside `pending`, `active`, `suspended`, `inactive` |

Other refusals — FastAPI's validation errors, a body id or key that does not match
the path, the import's `force` guard — keep the plain `{"detail": ...}` body. A route
that answers a coded `422` documents its `422` as `oneOf` `ErrorResponse` and
`HTTPValidationError` (whose `detail` is a list): both arrive with that status.

---

## User Routes

Self-service endpoints scoped to the authenticated user's membership. Prefix: `/user`.

### `GET /user`

Profile summary: user info, community membership, asset counts by type.

### `GET /user/member`

Own member detail (key, name, role, area, status, delivery points).

### `GET /user/community`

Detail of the community the user belongs to.

### `GET /user/assets`

List own assets.

**Query params:**
- `asset_type` — filter by asset type (`pv`, `meter`, `storage`, `ev_charger`, `heat_pump`, `load`)

### `GET /user/assets/{asset_key}`

Detail of a specific owned asset.

### `GET /user/delivery-points`

List own delivery points.

---

## Admin Routes — Communities

Community browsing and detail endpoints. Prefix: `/admin`.

### `GET /admin/communities`

Paginated list of communities.

**Query params:**
- `key` — filter by community key
- `limit` — page size (default 50, max 500)
- `cursor` — pagination cursor

### `GET /admin/communities/{community_key}`

Community detail including areas, topology, legal, contact, settings.

### `GET /admin/communities/{community_key}/topology`

Grid topology nodes for a community.

### `GET /admin/communities/{community_key}/members`

Paginated list of members.

**Query params:**
- `role` — filter by role (`consumer`, `prosumer`, `producer`, `operator`, `admin`)
- `status` — filter by status (`pending`, `active`, `suspended`, `inactive`)
- `area` — filter by area key
- `limit`, `cursor` — pagination

### `GET /admin/communities/{community_key}/members/{member_key}`

Member detail.

### `GET /admin/communities/{community_key}/members/by-user-id/{user_id}`

Lookup member by user ID within a community.

### `GET /admin/communities/{community_key}/members/{member_key}/delivery-points`

Delivery points for a specific member.

### `GET /admin/communities/{community_key}/delivery-points`

Paginated list of all delivery points in a community.

**Query params:**
- `type` — filter by delivery point type
- `active` — filter by active status
- `limit`, `cursor` — pagination

### `GET /admin/communities/{community_key}/delivery-points/by-id/{dp_id}`

Lookup a specific delivery point by its ID.

### `GET /admin/communities/{community_key}/assets`

Paginated list of community assets.

**Query params:**
- `asset_type` — filter by type
- `owner` — filter by member key
- `limit`, `cursor` — pagination

### `GET /admin/communities/{community_key}/assets/{asset_key}`

Asset detail.

### `GET /admin/communities/{community_key}/assets/by-sensor-id/{sensor_id}`

Lookup asset by sensor ID within a community.

### `GET /admin/communities/{community_key}/meters`

Convenience endpoint listing meter-type assets with POD and meter type info.

**Query params:**
- `owner` — filter by member key
- `limit`, `cursor` — pagination

---

## Admin Routes — Lookup

Cross-community lookups. Prefix: `/admin/lookup`.

### `GET /admin/lookup/community-by-user-id/{user_id}`

Find which community a user belongs to.

### `GET /admin/lookup/community-by-sensor-id/{sensor_id}`

Find which community owns a given sensor.

### `GET /admin/lookup/community-by-delivery-point/{dp_id}`

Find which community a delivery point belongs to.

### `GET /admin/lookup/member-by-user-id/{user_id}`

Lookup member details by user ID across communities.

### `GET /admin/lookup/asset-by-sensor-id/{sensor_id}`

Lookup asset details by sensor ID across communities.

### `POST /admin/lookup/assets-by-sensor-ids`

Batch lookup: resolve multiple sensor IDs to assets in a single request.

**Request body:** `{sensor_ids: [...]}`, at most 500.

### `POST /admin/lookup/assets-by-user-ids`

Batch lookup: resolve the assets owned by a set of members, across communities.
Every row carries `owner_user_id`, so the caller can attribute it back to the
member it asked about.

**Request body:** `{user_ids: [...]}`, at most 500.

### `POST /admin/lookup/members-by-dids`

Batch lookup: resolve the members holding a set of dataspace DIDs, across
communities. Every row carries its `did`, plus the member's `user_id`, delivery
points and community.

**Members, not assets** — deliberately. A participant is registered with a
declared supply point and no asset at all, because a meter's `sensor_id` is
assigned at physical installation. An asset-shaped answer would be empty for
everyone whose meter is not commissioned yet; a commissioned meter stays
reachable through `assets-by-user-ids` and the `user_id` in the same row.

**Request body:** `{dids: [...]}`, at most 500.

All three batch routes share one bound, and none of them is an enumeration
oracle: an identifier matching nothing contributes no row and is never a `404`.

---

## Admin Routes — Management

Import/export operations. Prefix: `/admin`.

### `POST /admin/import`

Import a community from a JSON bundle. Full replace: deletes existing community graph and recreates from bundle. Atomic operation.

**Destructive.** Overwriting a community that already exists requires `force: true` and otherwise answers `409`, naming the members and assets that would have been deleted. See [Import & Export](import-export.md#the-force-guard).

**Request body:** `{bundle, dry_run, force}` (see [Import & Export](import-export.md)).

**Response:** `ImportReport` with created counts. A dry run also lists in
`refusals` (`[{code, detail}]`) every invariant refusal the import would make.

**Refused whole**, before anything is deleted, with `422` and the invariant's
`code`, when the bundle breaks an invariant the runtime writes keep — today
`sensor_held`: one trimmed sensor id held by two active members of the bundle, or
by one of them and an active member of another community (that community and
member are not named); or `asset_key_too_long`: an asset key over 128 characters. The replaced community's own current rows do not count.

### `POST /admin/import/yaml`

Import one or more communities from a YAML multidocument body. Each document is a separate community bundle.

**Request body:** `text/yaml` — multidocument YAML. Query: `dry_run`, `force`.

**Response:** `MultiImportReport` with per-community results. A bundle breaking an
invariant refuses the whole request as `POST /admin/import` does.

### `GET /admin/export`

Export communities as YAML multidocument.

**Response:** `text/plain` — YAML bundle(s).

---

## Admin Routes — Writes

Runtime changes to a community. Prefix: `/admin`.

Every route here keeps one rule: **no write reduces a sibling.** `PUT` on a
member replaces that member, not the member list; patching a member does not
clear its delivery points; upserting an area does not drop the others. The only
endpoint that deletes what it was not given is the bundle import above.

### `POST /admin/communities/{community_key}/members`

Create one member, with its delivery points and assets.

`key` is optional — when omitted it is minted from the community's own
numbering (`ex-00001` → `ex-00002`), so a caller with no opinion still gets a key
that reads correctly in an exported bundle.

`did` is optional and unique across the whole registry, unlike `key` and
`user_id`, which are unique per community. It is usually written afterwards
rather than here — see `PATCH` below.

`extra` is optional, and its keys are merged into the member's `extra` at the
top level — the same place `PATCH` puts them. Other body keys that are not member
fields are kept in `extra` too.

**Responses:** `201` with the member; `409` when the key or `user_id` is already
taken (`member_key_taken`, `user_id_taken`), naming the existing key so the caller
can switch to `PATCH`, or when the `did` is already held by another member
anywhere in the registry (`did_taken`); `409 sensor_held` when an `active` member
is created with a meter whose sensor another active member holds; `404
community_not_found`; `422 invalid_status`.

### `PATCH /admin/communities/{community_key}/members/{member_key}`

Partial update. Absent fields are left alone, never cleared.

`delivery_points` is deliberately not accepted here — it is a JSONB list, and a
patch that happened to omit it would read as "this member now has none". Use the
delivery-point routes.

**This is how a member's dataspace `did` is written**, because the identity is
minted a step after the member is registered. Re-sending a member the DID it
already holds is a `200` that changes nothing, so the write is safe to retry.

**Responses:** `200`; `409 user_id_taken` if the new `user_id` belongs to another
member of the community, or `409 did_taken` if the new `did` belongs to any other
member in the registry. A DID clash inside the addressed community names the
holding member; one in another community does not, because which member of which
other community holds a DID is not the caller's question. `status: active` on a
member that was not active re-checks its sensors: `409 sensor_held`, and nothing
in the patch is applied, when another active member holds one.

### `POST /admin/communities/{community_key}/members/{member_key}/status`

Move a member through `pending → active → suspended → inactive`, with an optional
`reason` recorded on the member.

A move to `active` re-checks the member's sensors — only an active member holds
one — and answers `409 sensor_held`, leaving the status unchanged, when another
active member took one meanwhile. An unknown status is `422 invalid_status`.

### `DELETE /admin/communities/{community_key}/members/{member_key}`

**Deactivates** the member (`status = inactive`). A member who leaves still has
metering history, past consents and provenance elsewhere that reference them, and
assets cascade on a real delete.

`?purge=true` erases the member and its assets permanently. It requires the
separate `rec-registry.members.purge` grant, so a service that manages members
day to day cannot perform one.

**Response:** `DeletionReport` — `purged` tells the caller which happened.

### `PUT|DELETE /admin/communities/{ck}/members/{mk}/delivery-points/{point_id}`

Add, replace or remove one supply point, keeping the others. The body `id` must
match the path (`422` otherwise).

### `PUT|DELETE /admin/communities/{ck}/members/{mk}/assets/{asset_key}`

Create, replace or remove one asset. `properties` is validated against the model
for `asset_type` (`pv`, `storage`, `meter`, `ev_charger`, `heat_pump`, `load`),
so an EV charger cannot be stored carrying a heat pump's fields.

**Attaching a meter** is a `PUT` at `meter-<sensor id>`, the id trimmed:

```json
{"key": "meter-SEN-1", "asset_type": "meter",
 "properties": {"name": "Meter", "sensor_id": "SEN-1", "meter_type": "consumption"}}
```

| Outcome | Answer |
|---|---|
| attached | `200` with the stored asset (`AssetDetail`) |
| already attached to this member | `200`, nothing changes |
| another active member, in any community, holds the sensor | `409 sensor_held` — the holder is named by key only inside this community |
| another member of this community holds the key (with the convention: an inactive member still holding the asset) | `409 asset_key_taken` |
| the sensor id is blank after trimming | `422` |
| the asset key is longer than 128 characters | `422 asset_key_too_long` |

Sensor ids are compared and stored trimmed (of any Unicode whitespace); only an `active` member holds one, so
a write to a member that is not active is checked when it is reactivated.

**Detaching** is `DELETE` on the same path: a hard delete, `204`, after which the
sensor may be attached elsewhere. An asset the member does not hold is `404
asset_not_found`; an unknown member `404 member_not_found`.

### `PATCH /admin/communities/{community_key}`

Update community metadata. It does not touch areas or topology, for the same
reason the member patch does not touch delivery points: areas have their own
route, below, and topology has no write route — it changes only through a bundle
import.

### `PUT|DELETE /admin/communities/{community_key}/areas/{area_key}`

Add, replace or remove one area. Deleting is refused with `409 area_in_use`
while members still reference it — an orphaned `Member.area` is a dangling
reference nothing else checks.

---

## Meta Routes

### `GET /health`

Health check. Returns `{"status": "ok"}`.

### `GET /version`

Service version information.
