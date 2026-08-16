# CELINE REC Registry

API for modelling Renewable Energy Communities (RECs). Manages communities, members, assets, delivery points, and grid topology. Provides self-service endpoints for participants and administrative endpoints for managers, with import/export of community bundles in YAML format.

## Features

- Multi-community support with v0.5 schema
- Self-service user API (profile, membership, assets, delivery points)
- Admin API for community management, cross-community lookup, and batch operations
- **Runtime member management** — create, update, deactivate members and their delivery points and assets, one at a time
- YAML-based import/export with full replace semantics, guarded so a restore cannot silently delete a live community
- In-process OPA policy evaluation for authorization
- CLI (`celine-rec-registry`) for import, export, listing, and lookup operations
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
| `PATCH /admin/communities/{key}` | Update community metadata, areas |
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
```

## Documentation

| Document | Description |
|---|---|
| [Requirements](docs/specifications/index.md) | What the service must do — 58 requirements, each named by a test |
| [Decisions](docs/decisions/index.md) | Why a technical choice was made |
| [Data Model](docs/data-model.md) | Community, Member, Asset schema; JSONB fields; relationships |
| [API Reference](docs/api-reference.md) | All endpoint groups, query params, responses |
| [Import & Export](docs/import-export.md) | Bundle format, replace semantics, the `force` guard, CLI usage |
| [AGENTS.md](AGENTS.md) | Operational setup: invariants, authorization model, the two write paths |
| [Development](docs/development.md) | Setup, configuration, migrations, project layout |

## License

Apache 2.0 — Copyright © 2025 Spindox Labs
