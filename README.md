# CELINE REC Registry

Read-only microservice for storing and serving Renewable Energy Community (REC) registry data as **JSON-LD** documents.

## Key features
- PostgreSQL persistence (SQLAlchemy + Alembic)
- Read-only FastAPI endpoints, returning JSON-LD with actionable `@id` IRIs
- Typer CLI to **replace** a community definition from an ergonomic YAML file (idempotent)
- Dedicated YAML mapping function (single adaptation point when YAML structure evolves)

## Run (dev)
```bash
uv venv
uv pip install -e .

export DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/celine_rec_registry"

# Run migrations
alembic upgrade head

# Start API
uvicorn celine.rec_registry.main:app --reload
```

## Import a community
```bash
celine-rec-registry import community --file path/to/community.yaml
```

## Notes
- This service stores *registry* information (structure/topology), not telemetry datapoints.
- API outputs JSON-LD compliant structures referencing the API host as the base for `@id`.
