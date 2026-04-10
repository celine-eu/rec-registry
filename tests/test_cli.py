"""
CLI tests.

Uses typer.testing.CliRunner with httpx.post patched to avoid real network calls.
Authentication is bypassed by passing --token directly.
"""

import json
import pathlib
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from celine.rec_registry.cli.main import app

runner = CliRunner()

EXAMPLE_YAML = str(
    pathlib.Path(__file__).parent.parent / "recs" / "rec-example.yaml"
)

HTTPX_POST = "celine.rec_registry.cli.main.httpx.post"


def make_http_response(
    body: dict,
    status_code: int = 200,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.text = json.dumps(body)
    return resp


class TestImportCommand:
    def test_dry_run_prints_community_key(self):
        report = {
            "community_key": "example_rec",
            "deleted": {"community": 0, "member": 0, "asset": 0},
            "inserted": {"community": 1, "member": 17, "asset": 33},
            "warnings": [],
        }
        with patch(HTTPX_POST, return_value=make_http_response(report)):
            result = runner.invoke(
                app,
                [
                    "import",
                    "--file", EXAMPLE_YAML,
                    "--token", "fake-jwt-token",
                    "--dry-run",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "example_rec" in result.output
        assert "Dry run" in result.output

    def test_live_import_prints_success(self):
        report = {
            "community_key": "example_rec",
            "deleted": {"community": 1, "member": 5, "asset": 10},
            "inserted": {"community": 1, "member": 17, "asset": 33},
            "warnings": [],
        }
        with patch(HTTPX_POST, return_value=make_http_response(report)):
            result = runner.invoke(
                app,
                [
                    "import",
                    "--file", EXAMPLE_YAML,
                    "--token", "fake-jwt-token",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "example_rec" in result.output
        assert "success" in result.output.lower()

    def test_http_error_response_exits_nonzero(self):
        error_body = {"detail": "Forbidden"}
        with patch(
            HTTPX_POST, return_value=make_http_response(error_body, status_code=403)
        ):
            result = runner.invoke(
                app,
                [
                    "import",
                    "--file", EXAMPLE_YAML,
                    "--token", "fake-jwt-token",
                ],
            )

        assert result.exit_code != 0

    def test_import_sends_authorization_header(self):
        report = {
            "community_key": "example_rec",
            "deleted": {},
            "inserted": {},
            "warnings": [],
        }
        mock_post = MagicMock(return_value=make_http_response(report))
        with patch(HTTPX_POST, mock_post):
            runner.invoke(
                app,
                [
                    "import",
                    "--file", EXAMPLE_YAML,
                    "--token", "my-secret-token",
                ],
            )

        _, call_kwargs = mock_post.call_args
        assert call_kwargs["headers"]["Authorization"] == "Bearer my-secret-token"

    def test_import_sends_dry_run_flag_in_payload(self):
        report = {
            "community_key": "example_rec",
            "deleted": {},
            "inserted": {},
            "warnings": [],
        }
        mock_post = MagicMock(return_value=make_http_response(report))
        with patch(HTTPX_POST, mock_post):
            runner.invoke(
                app,
                [
                    "import",
                    "--file", EXAMPLE_YAML,
                    "--token", "fake-jwt-token",
                    "--dry-run",
                ],
            )

        _, call_kwargs = mock_post.call_args
        assert call_kwargs["json"]["dry_run"] is True
