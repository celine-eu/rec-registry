# API Reference

Interactive OpenAPI docs are available at `http://localhost:8004/docs`.

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

**Request body:** list of sensor ID strings.

---

## Admin Routes — Management

Import/export operations. Prefix: `/admin`.

### `POST /admin/import`

Import a community from a JSON bundle. Full replace: deletes existing community graph and recreates from bundle. Atomic operation.

**Request body:** JSON bundle (see [Import & Export](import-export.md)).

**Response:** `ImportReport` with created counts.

### `POST /admin/import/yaml`

Import one or more communities from a YAML multidocument body. Each document is a separate community bundle.

**Request body:** `text/yaml` — multidocument YAML.

**Response:** `MultiImportReport` with per-community results.

### `GET /admin/export`

Export communities as YAML multidocument.

**Response:** `text/plain` — YAML bundle(s).

---

## Meta Routes

### `GET /health`

Health check. Returns `{"status": "ok"}`.

### `GET /version`

Service version information.
