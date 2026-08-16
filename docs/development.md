# Development

## Prerequisites

- Python >= 3.12
- PostgreSQL 14+
- `uv` package manager
- `task` (go-task)

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL async connection string | `postgresql+asyncpg://postgres:securepassword123@host.docker.internal:15432/celine_rec_registry` |
| `DATABASE_ECHO` | Log SQL statements | `false` |
| `BASE_URL` | Public base URL of the service | `http://api.celine.localhost/rec-registry` |
| `DEFAULT_PAGE_SIZE` | Default pagination page size | `50` |
| `MAX_PAGE_SIZE` | Maximum pagination page size | `500` |
| `AUTH_ENABLED` | Enable JWT authentication | `true` |
| `AUTH_HEADER_NAME` | HTTP header for auth token | `authorization` |
| `OIDC__*` | OIDC settings (from `celine-sdk`) | audience: `svc-rec-registry` |
| `POLICIES_ENABLED` | Enable OPA policy evaluation | `true` |
| `POLICIES_DIR` | Directory containing `.rego` files | `./policies` |
| `POLICIES_DATA_DIR` | Optional directory for policy data JSON | — |
| `POLICIES_PACKAGE` | OPA package to evaluate | `celine.rec_registry.access` |
| `POLICIES_CACHE_ENABLED` | Enable in-memory decision cache | `true` |
| `POLICIES_CACHE_TTL` | Cache TTL in seconds | `300` |

## Local Setup

```bash
uv sync

# Run migrations
task db:migrate

# Start development server (port 8004)
task run
```

## Taskfile Commands

| Command | Description |
|---|---|
| `task run` | Start dev server on port 8004 |
| `task debug` | Start with debugger (port 48004) |
| `task db:migrate` | Run `alembic upgrade head` |
| `task db:revision` | Create new Alembic migration |
| `task import:community -- --file <path>` | Import a community YAML bundle |
| `task import:community:example` | Import the example community |
| `task release` | Run semantic-release |

## Alembic Migrations

```bash
# Apply pending migrations
task db:migrate

# Create a new migration
task db:revision -- -m "add delivery points"

# Or directly:
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "description"
uv run alembic downgrade -1
```

## Testing

```bash
uv run pytest -q
```

Tests marked `integration` need a real PostgreSQL and **skip when none is reachable**, so
a green run means different things depending on whether one was up — with no database, the
write, lookup and self-service tests do not run:

```bash
uv run pytest -q -m integration    # only those; TEST_DATABASE_URL overrides the connection
```

Each run creates and drops a throwaway `rec_registry_test` schema, so it needs no
`CREATE DATABASE` rights.

A test declares which requirement it covers with a `@verifies REQ-####` tag in its
docstring; see [the requirements](specifications/index.md) and, for the working procedure,
`.agents/playbooks/testing.md`.

## Project Layout

```
src/celine/rec_registry/
  main.py                    # FastAPI app factory (create_app)
  db/
    models.py                # SQLAlchemy ORM: Community, Member, Asset
    session.py               # Async session management
  schemas/
    models.py                # Pydantic response schemas
    bundle.py                # Bundle import schemas (v0.5)
  api/
    user.py                  # Self-service user endpoints
    meta.py                  # Health, version
    admin/
      communities.py         # Community/member/asset browsing (reads)
      writes.py              # Runtime member/asset/area writes
      lookup.py              # Cross-community lookups
      management.py          # Import/export operations
  services/
    members.py               # Row building, shared by the importer and the write API
    importer.py              # Bundle import logic
    exporter.py              # YAML export logic
  core/
    settings.py              # Pydantic settings
    middleware.py             # Auth/policy middleware
    yaml_io.py               # YAML parsing utilities
  cli/
    main.py                  # CLI entry point (celine-rec-registry)
    config.py                # CLI configuration
policies/                    # OPA .rego policy files
alembic/
  versions/                  # Migration scripts
tests/
  conftest.py                # Fixtures, including the live-database ones
docs/
  specifications/            # What the service must do; REQ-#### identifiers
  decisions/                 # Why a technical choice was made
```
