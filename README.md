# rec-registry

Read-only JSON-LD API for REC (Renewable Energy Community) composition. Exposes communities, participants, memberships, sites, assets, and meters following DCAT-AP conventions and the CELINE ontology.

## Features

- DCAT-AP compatible responses
- JSON-LD output with IRI expansion (no CURIEs)
- `?format=json` (default) and `?format=jsonld` query parameter
- JSON-LD context always references `https://celine-eu.github.io/ontologies/celine.jsonld`
- Admin import/export with full replace semantics
- Subleaf endpoints with query filters
- Auth/ACL middleware seam on `/admin/*` and write methods

## Quick Start

```bash
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/celine_registry"
export BASE_URL="http://localhost:8000"

alembic upgrade head
uvicorn celine_registry.main:app --reload --host 0.0.0.0 --port 8000
```

## API Overview

| Path prefix | Description |
|---|---|
| `GET /user/communities` | List all communities |
| `GET /user/communities/{key}` | Community detail |
| `GET /user/communities/{key}/members` | Members of a community |
| `GET /user/assets` | List assets (filterable by community, member) |
| `GET /admin/import` | Validate a YAML bundle |
| `POST /admin/import` | Replace community graph from YAML bundle |
| `GET /admin/export?community={key}` | Export full YAML bundle |

## Documentation

| Document | Description |
|---|---|
| [Data Model](https://celine-eu.github.io/projects/rec-registry/docs/data-model.md) | Community, Member, Asset schema; JSONB fields; relationships |
| [API Reference](https://celine-eu.github.io/projects/rec-registry/docs/api-reference.md) | All endpoint groups, query params, output formats |
| [Import & Export](https://celine-eu.github.io/projects/rec-registry/docs/import-export.md) | Bundle format, replace semantics, idempotency |
| [Development](https://celine-eu.github.io/projects/rec-registry/docs/development.md) | DATABASE_URL, Alembic migrations, local dev, testing |

## License

Apache 2.0 — Copyright © 2025 Spindox Labs
