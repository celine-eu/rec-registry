# REC Registry — Operational Setup

## Objectives

- Model a Renewable Energy Community around a well-known structure: communities, members, delivery points, assets, grid topology
- Serve participants (self-service) and managers (admin) from one store
- Accept a community as a versioned YAML bundle **and** let it change at runtime, without those two paths diverging
- Hold the member identity the rest of the platform joins on (`user_id`, POD, sensor id)

## What this service holds

**Personal data, deliberately.** Member names, delivery point identifiers (POD/CUPS) and asset serial numbers are personal data, and this registry is inside the CELINE perimeter that may hold them. That distinguishes it from the dataspace services, which hold codes, pseudonymous DIDs and hashes only. When integrating, keep that boundary in mind: a value that is fine here may not cross into a dataspace payload.

## Tech Stack

- **Package:** `celine.rec_registry` (namespace package)
- **Framework:** FastAPI, async
- **Models/config:** Pydantic v2, Pydantic Settings
- **Database:** PostgreSQL (JSONB throughout), Alembic migrations in `./alembic/`
- **AuthZ:** in-process OPA (`policies/**/*.rego`) evaluated by `PolicyMiddleware`
- **Auth:** JWT via `celine.sdk.auth`
- **CLI:** `celine-rec-registry` (typer)
- **Package management:** uv + hatchling

## Project Layout

```
./
├── src/celine/rec_registry/
│   ├── main.py                 # App factory, router wiring, middleware
│   ├── api/
│   │   ├── user.py             # Self-service (/user) — read-only
│   │   ├── meta.py             # /health, /version
│   │   └── admin/
│   │       ├── communities.py  # Admin READS: communities, members, assets, delivery points
│   │       ├── writes.py       # Admin WRITES: members, assets, delivery points, community
│   │       ├── lookup.py       # Cross-community lookup by user/sensor/delivery point
│   │       └── management.py   # Bundle import/export
│   ├── services/
│   │   ├── importer.py         # Replacement import of a YAML bundle
│   │   ├── exporter.py         # Bundle export (the backup half of import)
│   │   └── members.py          # Row-building shared by the importer and the write API
│   ├── schemas/
│   │   ├── bundle.py           # `*In` component models — the bundle contract
│   │   └── models.py           # Response models + write requests
│   ├── db/models.py            # Community, Member, Asset
│   └── core/middleware.py      # Auth + policy enforcement
├── policies/celine/            # OPA rego: scopes.rego + rec_registry/access.rego
├── alembic/
├── recs/                       # Example bundles
├── schemas/community/v0.5/     # Published JSON Schema
└── docs/
```

## Data Model

Three tables, all community-scoped.

| Entity | Natural key | Notes |
|---|---|---|
| `Community` | `key` | `areas`, `topology`, `legal`, `links`, `contact`, `settings`, `extra` — JSONB |
| `Member` | `(community_id, key)` **and** `(community_id, user_id)`, both unique | `role`, `status`, `area`, `delivery_points` (JSONB list), `extra` |
| `Asset` | `(community_id, owner_id, key)` | `asset_type`, `properties`, `device`, `relationships`; `sensor_id` promoted to a column for lookup |

`Member.status` is the lifecycle: `pending | active | suspended | inactive`.

`Asset` cascades on member delete (`ondelete="CASCADE"`) — which is why deleting a member is a status change by default (see below).

## The two write paths, and why they share code

A community can arrive two ways, and both must produce the same rows:

1. **A YAML bundle**, imported wholesale — how a community is seeded and how it is restored from a backup.
2. **The admin write API**, one member at a time — how a community changes when a manager approves somebody.

`services/members.py` builds the rows for both. Two implementations of "what a member row looks like" would drift on the first schema change, and the symptom would be a community that exports differently depending on how its members arrived. `tests/test_writes.py::TestRoundTrip` pins exactly that: create through the API → export → re-import → the member is still there, unchanged.

### Invariants every write keeps

- **No write reduces a sibling.** `PUT` on a member replaces that member, not the member list; patching a member does not clear its delivery points; upserting an area does not drop the others. There is no collection-level replace outside the bundle import. `tests/test_writes.py::TestNoWriteReducesASibling` exercises every write against a two-member community and checks the count afterwards.
- **Deleting a member deactivates it.** A member who leaves still has metering history, past consents and provenance elsewhere that reference them — and assets cascade. `?purge=true` erases, and is authorized separately.
- **JSONB collections merge by identity, not position.** A member gaining a second supply point must not lose the first, which is why delivery points and assets are sub-resources rather than fields.
- **Import is destructive and says so.** It deletes the community with every member and asset, then recreates it. Overwriting an existing community requires `force=true` and otherwise answers `409` naming what would have gone.

## Authorization

`PolicyMiddleware` enforces on the path prefix:

| Prefix | Rule |
|---|---|
| `/health`, `/version`, `/docs*`, `/openapi.json` | public |
| `/user*`, `/me*` | valid JWT |
| `/admin*` | valid JWT **+** an OPA decision |
| anything else | pass through, user attached if a token is present |

The **action** is derived from the path *and* the HTTP method, so reads and writes are separate grants:

| Action | Reached by | Scope |
|---|---|---|
| `read` | any `GET` under `/admin` | `rec-registry.read` |
| `members.write` | write methods on `…/members…` | `rec-registry.members.write` |
| `members.purge` | `DELETE …/members/{key}?purge=true` | `rec-registry.members.purge` |
| `assets.write` | write methods on `…/assets…` | `rec-registry.assets.write` |
| `community.write` | write methods on a community or its areas | `rec-registry.community.write` |
| `import` / `export` | `/admin/import*`, `/admin/export` | `rec-registry.import` / `.export` |
| `lookup` | `/admin/lookup/*` | `rec-registry.lookup` |

`rec-registry.admin` satisfies all of them through the admin-override rule in `policies/celine/scopes.rego` (`{service}.admin` covers `{service}.*`), so an existing admin token keeps working. **Do not grant `rec-registry.admin` to a service account** — give it the actions it calls. An onboarding service that registers approved participants needs `members.write` and `assets.write`, and has no business importing, exporting or purging.

Asset paths are checked before member paths when naming the action, because an asset path contains `/members` too.

Auth and policies are disabled in tests via `AUTH_ENABLED=false` / `POLICIES_ENABLED=false`.

## API Summary

**Self-service (`/user`, JWT):** profile, membership, community, assets, delivery points — all reads.

**Admin reads (`/admin`):**

| Method | Path |
|---|---|
| `GET` | `/admin/communities`, `/admin/communities/{key}`, `…/topology` |
| `GET` | `…/members`, `…/members/{key}`, `…/members/by-user-id/{user_id}`, `…/members/{key}/delivery-points` |
| `GET` | `…/assets`, `…/assets/{key}`, `…/assets/by-sensor-id/{id}`, `…/meters`, `…/delivery-points` |
| `GET` | `/admin/lookup/*` |
| `GET` | `/admin/export` |

**Admin writes (`/admin`):**

| Method | Path | Notes |
|---|---|---|
| `POST` | `/admin/communities/{ck}/members` | `409` on duplicate key or `user_id`; `key` minted from the community's own numbering when omitted |
| `PATCH` | `…/members/{mk}` | absent fields left alone; `delivery_points` is not patchable here |
| `POST` | `…/members/{mk}/status` | explicit lifecycle transition, with an optional reason |
| `DELETE` | `…/members/{mk}` | deactivates; `?purge=true` erases (separate grant) |
| `PUT`/`DELETE` | `…/members/{mk}/delivery-points/{id}` | merges by point id |
| `PUT`/`DELETE` | `…/members/{mk}/assets/{key}` | payload validated against the model for `asset_type` |
| `PATCH` | `/admin/communities/{ck}` | metadata only; areas and topology have their own routes |
| `PUT`/`DELETE` | `…/areas/{key}` | delete refuses while members reference the area |
| `POST` | `/admin/import`, `/admin/import/yaml` | **destructive**; `force=true` to overwrite |

## Local Development

```bash
uv sync
export DATABASE_URL="postgresql+asyncpg://postgres:securepassword123@host.docker.internal:15432/celine_rec_registry"
task db:migrate
task run            # :8004
task import:community:example
```

### Tests

```bash
uv run pytest
```

Tests marked `integration` need a live PostgreSQL and **skip automatically when none is reachable**, so the suite runs anywhere. They are the ones that prove the write API and the bundle importer agree — a mocked session cannot show that. Point them elsewhere with `TEST_DATABASE_URL`; they create and drop a `rec_registry_test` schema, so they need no `CREATE DATABASE` rights and leave nothing behind.

## Rules

- The bundle `*In` models in `schemas/bundle.py` are the contract. Write requests reuse them rather than declaring parallel shapes — two schemas for the same object drift on the first schema-version bump.
- New write endpoints go in `api/admin/writes.py`, beside the invariants they have to keep. Reads stay in `communities.py`.
- Any new write must be added to `TestNoWriteReducesASibling`.
- No partner or customer organisation names in code, tests, fixtures or docs — deployment-specific values live in the private deployment repository.
