# CELINE REC Registry

API for modelling Renewable Energy Communities (RECs). Manages communities, members, assets, delivery points, and grid topology. Provides self-service endpoints for participants and administrative endpoints for managers, with import/export of community bundles in YAML format.

## Features

- Multi-community support with v0.7 schema (each area one GSE primary substation)
- Self-service user API (profile, membership, assets, delivery points)
- Admin API for community management, cross-community lookup, and batch operations
- **Runtime member management** — create, update, deactivate members and their delivery points and assets, one at a time
- YAML-based import/export with full replace semantics, guarded so a restore cannot silently delete a live community
- In-process OPA policy evaluation for authorization
- CLI (`celine-rec-registry`) for import, export, listing, and lookup operations, and read-only reports of stored rows the write checks would now refuse
- Paginated responses with cursor-based navigation

## Two ways a community changes

A community is **seeded** from a YAML bundle and **changes** through the member
API. Both paths build the same rows, so an export taken after weeks of runtime
changes re-imports to the same state.

The distinction matters because import is *replacement*: it deletes the
community with every member and asset, then recreates it from the file. That was
safe when the file was the only source of members. Now that members arrive at
runtime, restoring a stale export is the likeliest way to lose them — so
overwriting an existing community requires `force`, and is refused without it.

## Quick Start

```bash
uv sync

export DATABASE_URL="postgresql+asyncpg://postgres:securepassword123@host.docker.internal:15432/celine_rec_registry"

uv run alembic upgrade head
# or: task db:migrate

task run
# runs on port 8004
```

## API Overview

| Path prefix | Description |
|---|---|
| `GET /user` | Self-service: profile, membership, community, assets, delivery points |
| `GET /admin/communities` | List/detail communities, members, assets, delivery points, meters |
| `GET /admin/lookup/*` | Cross-community lookups by user ID, sensor ID, or delivery point |
| `POST /admin/communities/{key}/members` | Create a member; sub-resources for its delivery points and assets |
| `PUT\|DELETE /admin/communities/{key}/members/{member}/assets/meter-{sensor_id}` | Attach or detach a meter; one active holder per sensor id (`409 sensor_held`) |
| `PATCH /admin/communities/{key}/members/{member}/profile` | Correct a member's role and area, nothing else (`members.profile.write`) |
| `PUT /admin/communities/{key}/members/{member}/name\|role\|area` | Set one field of a member, granted per field (`members.name.write`, `members.role.write`, `members.area.write`) |
| `PUT\|DELETE /admin/communities/{key}/members/{member}/delivery-points/{id}` | Add or remove a delivery point (`members.delivery_points.write`); `?replaces={old}` corrects one and relinks its meters in one write; one active holder per POD (`409 delivery_point_held`); a point a meter names is not deleted (`409 delivery_point_linked`) |
| `PATCH /admin/communities/{key}` | Update community metadata (areas have their own route) |
| `PUT\|DELETE /admin/communities/{key}/areas/{area}` | Add, replace or remove one area; an area is one GSE primary substation (`422 invalid_area_boundary`) under an area key (`422 invalid_area_key`) |
| `POST /admin/communities/{key}/areas/{area}/rename` | Move an area to a new key with its members, in one write (`community.write`) |
| `PUT\|DELETE /admin/communities/{key}/topology/{node}` | Add, replace or remove one topology node; a node an area lists or another node names as `parent` is not deleted (`409 topology_node_in_use`) |
| `POST /admin/import` | Import community from JSON bundle (**destructive**) |
| `POST /admin/import/yaml` | Import communities from YAML multidocument (**destructive**) |
| `GET /admin/export` | Export communities as YAML |
| `GET /health`, `GET /version` | Service health and version |

## CLI

```bash
celine-rec-registry import --file recs/rec-example.yaml            # refuses an existing community
celine-rec-registry import --file recs/rec-example.yaml --dry-run  # see what it would replace
celine-rec-registry import --file recs/rec-example.yaml --force    # accept the replacement
celine-rec-registry export --community example_rec
celine-rec-registry list
celine-rec-registry tree --community example_rec
celine-rec-registry lookup-user --user-id <id>
celine-rec-registry lookup-sensor --sensor-id <id>
celine-rec-registry duplicate-sensors                              # read-only; exits 1 if a sensor has two active holders
celine-rec-registry duplicate-delivery-points                      # read-only; exits 1 if a POD has two active holders
celine-rec-registry out-of-set-values                              # read-only; exits 1 if a role, status or area is out of set
celine-rec-registry invalid-area-boundaries                        # read-only; exits 1 if a stored area breaks the one-substation or area-key rule
```

A refusal a caller acts on answers `{"detail": "<sentence>", "code": "<code>"}` —
see [refusal codes](docs/api-reference.md#refusal-codes).

## Documentation

| Document | Description |
|---|---|
| [Requirements](docs/specifications/index.md) | What the service must do — 79 requirements, every one named by a test, none planned |
| [Decisions](docs/decisions/index.md) | Why a technical choice was made |
| [Data Model](docs/data-model.md) | Community, Member, Asset schema; JSONB fields; relationships |
| [API Reference](docs/api-reference.md) | All endpoint groups, query params, responses |
| [Import & Export](docs/import-export.md) | Bundle format, replace semantics, the `force` guard, CLI usage, [before deploying 1.6.0](docs/import-export.md#before-deploying-160) |
| [AGENTS.md](AGENTS.md) | Operational setup: invariants, authorization model, the two write paths |
| [Development](docs/development.md) | Setup, configuration, migrations, project layout |

## License

Apache 2.0 — Copyright © 2025 Spindox Labs
