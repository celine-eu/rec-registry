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
