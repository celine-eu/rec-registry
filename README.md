# celine-registry

Registry API for CELINE REC composition (communities, participants, memberships, sites, assets, meters).

## Implemented requirements

- Admin import/export:
  - `POST /admin/import` replacement import (delete community graph and recreate).
  - `GET /admin/export?community={key}` export YAML bundle.
- Output format:
  - `?format=json` (default)
  - `?format=jsonld`
- JSON-LD context is never embedded and always references:
  - https://celine-eu.github.io/ontologies/celine.jsonld
- API outputs expanded IRIs only (no CURIE output).
- Subleaf endpoints with filters, no `?include`.
- Middleware seam for future auth/ACL on `/admin/*` and write methods.

## Dev quickstart

```bash
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/celine_registry"
export BASE_URL="http://localhost:8000"

alembic upgrade head
uvicorn celine_registry.main:app --reload --host 0.0.0.0 --port 8000