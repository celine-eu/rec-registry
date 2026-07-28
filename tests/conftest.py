import os

# Must be set before any app module imports so settings picks them up.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test_rec")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("POLICIES_ENABLED", "false")

import pathlib
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from celine.rec_registry.schemas.bundle import RegistryBundleIn
from celine.rec_registry.api.admin.management import router as management_router
from celine.rec_registry.db.session import get_session

EXAMPLE_YAML = pathlib.Path(__file__).parent.parent / "recs" / "rec-example.yaml"


@pytest.fixture(scope="session")
def example_data() -> dict:
    with open(EXAMPLE_YAML) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def example_bundle(example_data) -> RegistryBundleIn:
    return RegistryBundleIn(**example_data)


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.scalar = AsyncMock(return_value=None)
    session.flush = AsyncMock()
    session.delete = AsyncMock()
    session.add = MagicMock()

    begin_cm = MagicMock()
    begin_cm.__aenter__ = AsyncMock(return_value=None)
    begin_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin_cm)
    return session


@pytest.fixture
def app(mock_session):
    """Minimal FastAPI app without PolicyMiddleware."""
    test_app = FastAPI()
    test_app.include_router(management_router, prefix="/admin")

    async def override_session():
        yield mock_session

    test_app.dependency_overrides[get_session] = override_session
    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


# =============================================================================
# Live-database fixtures
# =============================================================================
#
# The write API and the bundle importer have to produce the same rows — that is
# the property that keeps an exported community re-importable after members have
# been created through the API. A mocked session cannot show it, so these tests
# run against a real PostgreSQL and skip when none is reachable.

PG_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:securepassword123@localhost:15432/postgres",
)


@pytest.fixture(scope="session")
def pg_url() -> str:
    return PG_URL


SCHEMA = "rec_registry_test"


@pytest.fixture
async def pg_engine(pg_url):
    """An engine bound to a throwaway schema, dropped afterwards.

    A schema rather than a database so the fixture needs no CREATE DATABASE
    rights and leaves nothing behind if a test aborts mid-way.

    `search_path` is set as a connection setting rather than executed on the
    session: running `SET` through the session would open a transaction, and the
    import route then cannot `session.begin()` its own.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from celine.rec_registry.db.session import Base

    bootstrap = create_async_engine(pg_url, future=True)
    try:
        async with bootstrap.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
            await conn.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))
    except Exception as exc:  # pragma: no cover - environment dependent
        await bootstrap.dispose()
        pytest.skip(f"No database available at {pg_url}: {exc}")
    finally:
        await bootstrap.dispose()

    engine = create_async_engine(
        pg_url,
        future=True,
        connect_args={"server_settings": {"search_path": SCHEMA}},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()
    cleanup = create_async_engine(pg_url, future=True)
    async with cleanup.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
    await cleanup.dispose()


@pytest.fixture
async def pg_session(pg_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with maker() as session:
        yield session


@pytest.fixture
async def live_client(pg_engine):
    """An HTTP client over the real routers, backed by the live schema.

    `httpx.AsyncClient` over an ASGI transport rather than `TestClient`: the
    latter drives the app from its own event loop, while the session belongs to
    the test's — and asyncpg connections cannot cross loops.
    """
    import httpx
    from fastapi import FastAPI

    from celine.rec_registry.api.admin.communities import router as communities_router
    from celine.rec_registry.api.admin.management import router as management_router
    from celine.rec_registry.api.admin.writes import router as writes_router

    app = FastAPI()
    app.include_router(management_router, prefix="/admin")
    app.include_router(communities_router, prefix="/admin")
    app.include_router(writes_router, prefix="/admin")

    # A fresh session per request, as production does. Sharing one across
    # requests leaves a transaction open from the previous call, and the import
    # route — which opens its own — then fails for a reason no real caller hits.
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(pg_engine, expire_on_commit=False)

    async def override_session():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client
