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
    def test_version_reports_an_api_version(self, meta_client):
        """@verifies REQ-0058"""
        r = meta_client.get("/version")

        assert r.status_code == 200
        assert r.json()["api_version"] == "1.0.0"

    def test_the_api_version_is_hardcoded_and_not_the_package_version(
        self, meta_client
    ):
        """`/version` cannot answer "what is deployed?" — it answers "what was
        typed into `meta.py`", which has not moved since 1.0.0 while the package
        is on 1.5.0.

        A defect (celine-eu/rec-registry#38), pinned as current behaviour so that
        wiring it to the package metadata is a visible three-part change.

        @verifies REQ-0058
        """
        from importlib.metadata import version as package_version

        reported = meta_client.get("/version").json()["api_version"]

        assert reported == "1.0.0"
        assert reported != package_version("celine-rec-registry")

    def test_the_reported_schema_version_matches_nothing_that_exists(
        self, meta_client
    ):
        """Three values live in four places, and this route holds a fourth
        opinion:

        | Place | Says |
        |---|---|
        | this route | `0.4` |
        | `recs/rec-example.yaml`, and every document | `0.5` |
        | `RegistryBundleIn`'s default | `1.0` |
        | what the exporter emits | `1.0` |

        They disagree freely because **nothing reads the field** (REQ-0018).
        Pinned as-is; the mismatch is the subject.

        @verifies REQ-0058
        """
        from celine.rec_registry.schemas.bundle import RegistryBundleIn

        reported = meta_client.get("/version").json()["schema_version"]
        bundle_default = RegistryBundleIn.model_fields["schema_version"].default

        assert reported == "0.4"
        assert bundle_default == "1.0"
        assert reported != bundle_default, "the mismatch is closed — update REQ-0058"
