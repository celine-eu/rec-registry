"""Health and version — the two routes an operator reaches for first.

Small, and worth pinning anyway: `/health` is what a container orchestrator acts
on, and `/version` is the only thing that answers *"what is deployed?"* without
a shell on the pod.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from celine.rec_registry.api.meta import router as meta_router


@pytest.fixture
def meta_client() -> TestClient:
    """No database and no policy middleware.

    Deliberate: these routes must answer while the database is unreachable, and
    a fixture that needed one would prove the opposite of what is wanted.
    """
    app = FastAPI()
    app.include_router(meta_router)
    return TestClient(app)


class TestHealth:
    def test_health_is_ok_without_a_database(self, meta_client):
        """@verifies REQ-0057"""
        r = meta_client.get("/health")

        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestVersion:
    """`/version` answers what is deployed, not what was typed into a file.

    It used to answer neither: `api_version` was the literal `"1.0.0"` while the
    package was on 1.5.0, and `schema_version` was `"0.4"`, which matched
    nothing that existed anywhere. Both are now derived, and these tests are
    written so that they fail again if either goes back to being a literal —
    each compares against the source rather than against a copied value.
    """

    def test_the_api_version_is_the_installed_package_version(self, meta_client):
        """Comparing this across two environments has to mean something.

        @verifies REQ-0058
        """
        from importlib.metadata import version as package_version

        reported = meta_client.get("/version").json()["api_version"]

        assert reported == package_version("celine-rec-registry")

    def test_the_schema_version_is_the_one_the_bundle_model_defaults_to(
        self, meta_client
    ):
        """The mismatch this pins used to be the subject: the route said `0.4`
        and the bundle model defaulted to `1.0`.

        They agree now because both read `core/versions.py`, which is the point
        — four literals is how three opinions happened.

        @verifies REQ-0058
        """
        from celine.rec_registry.schemas.bundle import RegistryBundleIn

        reported = meta_client.get("/version").json()["schema_version"]
        bundle_default = RegistryBundleIn.model_fields["schema_version"].default

        assert reported == bundle_default

    def test_the_schema_version_is_one_that_exists_on_disk(self, meta_client):
        """`0.4` was reported for a while, and `1.0` defaulted to, neither of
        which named a schema in `schemas/community/`.

        @verifies REQ-0058
        """
        import pathlib

        reported = meta_client.get("/version").json()["schema_version"]
        published = pathlib.Path(__file__).parent.parent / "schemas" / "community"

        assert (published / f"v{reported}").is_dir()

    def test_version_answers_without_a_database(self, meta_client):
        """Same reason as `/health`: it is reached for when things are wrong.

        @verifies REQ-0058
        """
        r = meta_client.get("/version")

        assert r.status_code == 200
        assert set(r.json()) == {"api_version", "schema_version"}
