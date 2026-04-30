# CELINE REC Registry

API for modelling Renewable Energy Communities (RECs). Manages communities, members, assets, delivery points, and grid topology. Provides self-service endpoints for participants and administrative endpoints for managers, with import/export of community bundles in YAML format.

## Features

- Multi-community support with v0.5 schema
- Self-service user API (profile, membership, assets, delivery points)
- Admin API for community management, cross-community lookup, and batch operations
- YAML-based import/export with full replace semantics
- In-process OPA policy evaluation for authorization
- CLI (`celine-rec-registry`) for import, export, listing, and lookup operations
- Paginated responses with cursor-based navigation

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
| `POST /admin/import` | Import community from JSON bundle |
| `POST /admin/import/yaml` | Import communities from YAML multidocument |
| `GET /admin/export` | Export communities as YAML |
| `GET /health`, `GET /version` | Service health and version |

## CLI

```bash
celine-rec-registry import --file recs/rec-example.yaml
celine-rec-registry export --community example_rec
celine-rec-registry list
celine-rec-registry tree --community example_rec
celine-rec-registry lookup-user --user-id <id>
celine-rec-registry lookup-sensor --sensor-id <id>
```

## Documentation

| Document | Description |
|---|---|
| [Data Model](docs/data-model.md) | Community, Member, Asset schema; JSONB fields; relationships |
| [API Reference](docs/api-reference.md) | All endpoint groups, query params, responses |
| [Import & Export](docs/import-export.md) | Bundle format, replace semantics, CLI usage |
| [Development](docs/development.md) | Setup, configuration, migrations, project layout |

## License

Apache 2.0 — Copyright © 2025 Spindox Labs
