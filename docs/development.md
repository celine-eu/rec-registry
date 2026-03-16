# Development

## Prerequisites

- Python ≥ 3.11
- PostgreSQL 14+
- `uv` package manager

## Environment Variables

| Variable | Description | Example |
|---|---|---|
| `DATABASE_URL` | PostgreSQL async connection string | `postgresql+asyncpg://postgres:postgres@localhost:5432/celine_registry` |
| `BASE_URL` | Public base URL of the service (used for IRI generation) | `http://localhost:8000` |

## Local Setup

```bash
# Install dependencies
uv sync

# Configure environment
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/celine_registry"
export BASE_URL="http://localhost:8000"

# Run migrations
uv run alembic upgrade head

# Start development server
uv run uvicorn celine_registry.main:app --reload --host 0.0.0.0 --port 8000
```

## Docker Compose

```bash
docker compose up -d
```

Starts PostgreSQL and the registry API. Apply migrations with:

```bash
docker compose run --rm api alembic upgrade head
```

## Alembic Migrations

```bash
# Apply pending migrations
uv run alembic upgrade head

# Create a new migration
uv run alembic revision --autogenerate -m "add site table"

# Downgrade one step
uv run alembic downgrade -1
```

## Testing

```bash
uv run pytest -q
```

Tests use a separate test database. Set `DATABASE_URL` to a test instance or use the Docker Compose test profile.

## Project Layout

```
src/
  celine_registry/
    main.py           # FastAPI app factory
    models.py         # SQLAlchemy ORM models
    schemas.py        # Pydantic request/response schemas
    routes/
      user.py         # Read-only user endpoints
      admin.py        # Import/export endpoints
    jsonld.py         # JSON-LD serialization
    bundle.py         # YAML bundle parser and validator
alembic/
  versions/           # Migration scripts
```
