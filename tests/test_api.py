"""
API endpoint tests.

Uses a minimal FastAPI app (no PolicyMiddleware) with a mocked database session.
The importer service is patched to isolate HTTP layer concerns from DB logic.
"""

import pathlib
from unittest.mock import AsyncMock, patch

import pytest
import yaml

EXAMPLE_YAML = pathlib.Path(__file__).parent.parent / "recs" / "rec-example.yaml"

IMPORT_PATCH = "celine.rec_registry.api.admin.management.replacement_import_bundle"


def load_import_payload(dry_run: bool = True) -> dict:
    with open(EXAMPLE_YAML) as f:
        data = yaml.safe_load(f)
    return {"bundle": data, "dry_run": dry_run}


def make_import_result(
    key: str = "example_rec",
    deleted: dict | None = None,
    inserted: dict | None = None,
    warnings: list | None = None,
):
    return (
        key,
        deleted or {"community": 0, "member": 0, "asset": 0},
        inserted or {"community": 1, "member": 17, "asset": 33},
        warnings or [],
    )


class TestImportEndpoint:
    def test_dry_run_returns_200_with_report(self, client):
        payload = load_import_payload(dry_run=True)
        with patch(IMPORT_PATCH, new=AsyncMock(return_value=make_import_result())):
            resp = client.post("/admin/import", json=payload)

        assert resp.status_code == 200
        body = resp.json()
        assert body["community_key"] == "example_rec"
        assert body["inserted"]["member"] == 17
        assert body["warnings"] == []

    def test_live_import_returns_report_with_replaced_counts(self, client):
        payload = load_import_payload(dry_run=False)
        result = make_import_result(
            deleted={"community": 1, "member": 5, "asset": 10},
            inserted={"community": 1, "member": 17, "asset": 33},
        )
        with patch(IMPORT_PATCH, new=AsyncMock(return_value=result)):
            resp = client.post("/admin/import", json=payload)

        assert resp.status_code == 200
        body = resp.json()
        assert body["deleted"]["community"] == 1
        assert body["deleted"]["member"] == 5

    def test_warnings_are_included_in_response(self, client):
        payload = load_import_payload(dry_run=False)
        result = make_import_result(
            warnings=["Meter meter-x: missing sensor_id; skipped"]
        )
        with patch(IMPORT_PATCH, new=AsyncMock(return_value=result)):
            resp = client.post("/admin/import", json=payload)

        assert resp.status_code == 200
        assert len(resp.json()["warnings"]) == 1

    def test_missing_bundle_field_returns_422(self, client):
        resp = client.post("/admin/import", json={"dry_run": True})
        assert resp.status_code == 422

    def test_malformed_json_returns_422(self, client):
        resp = client.post(
            "/admin/import",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 422

    def test_import_called_with_correct_dry_run_flag(self, client):
        payload = load_import_payload(dry_run=True)
        mock_fn = AsyncMock(return_value=make_import_result())
        with patch(IMPORT_PATCH, new=mock_fn):
            client.post("/admin/import", json=payload)

        _, call_kwargs = mock_fn.call_args
        assert call_kwargs.get("dry_run") is True
