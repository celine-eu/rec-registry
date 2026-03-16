# API Reference

Interactive OpenAPI docs are available at `http://localhost:8000/docs`.

## Output Formats

All endpoints that return registry data support the `format` query parameter:

| Value | Content-Type | Description |
|---|---|---|
| `json` (default) | `application/json` | Plain JSON object |
| `jsonld` | `application/ld+json` | JSON-LD with `@context` reference |

JSON-LD responses include `"@context": "https://celine-eu.github.io/ontologies/celine.jsonld"` and use expanded IRIs only.

---

## User Routes

Read-only endpoints for querying registry data.

### `GET /user/communities`

List all communities.

**Query params:**
- `format` — output format (`json` or `jsonld`)

### `GET /user/communities/{key}`

Retrieve a single community by its key.

### `GET /user/communities/{key}/members`

List all members of a community.

**Query params:**
- `role` — filter by member role (`producer`, `consumer`, `prosumer`)
- `format` — output format

### `GET /user/members/{id}`

Retrieve a single member.

### `GET /user/members/{id}/assets`

List all assets belonging to a member.

**Query params:**
- `asset_type` — filter by asset type

### `GET /user/assets`

List all assets. Supports filtering:

**Query params:**
- `community` — filter by community key
- `member` — filter by member ID
- `asset_type` — filter by asset type

### `GET /user/sites`

List all sites. Supports filtering:

**Query params:**
- `community` — filter by community key
- `member` — filter by member ID

---

## Admin Routes

Endpoints for data management. Protected by the auth/ACL middleware seam (placeholder in current release).

### `GET /admin/export`

Export the full community graph as a YAML bundle.

**Query params:**
- `community` (required) — community key to export

**Response:** `application/yaml` — v0.4 bundle format (see [import-export.md](https://celine-eu.github.io/projects/rec-registry/docs/import-export.md)).

### `GET /admin/import`

Validate a YAML bundle without applying it.

**Request:** `multipart/form-data` with `file` field containing the YAML bundle.

**Response:** Validation result.

### `POST /admin/import`

Replace the full community graph from a YAML bundle. Deletes the existing community and all related entities, then recreates from the bundle.

**Request:** `multipart/form-data` with `file` field.

**Response:** `201` on success.

---

## Meta Routes

### `GET /health`

Health check endpoint. No authentication required. Returns `{"status": "ok"}`.

### `GET /.well-known/jsonld-context`

Redirects to the CELINE JSON-LD context document.
