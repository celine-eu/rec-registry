"""
CLI tests.

Uses typer.testing.CliRunner with httpx.post/get patched to avoid real network calls.
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
HTTPX_GET = "celine.rec_registry.cli.main.httpx.get"


def make_http_response(
    body,
    status_code: int = 200,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.text = json.dumps(body) if isinstance(body, dict) else body
    return resp


class TestImportCommand:
    def _multi_report(self, community_key="example_rec", deleted=None, inserted=None):
        return {
            "reports": [
                {
                    "community_key": community_key,
                    "deleted": deleted or {"community": 0, "member": 0, "asset": 0},
                    "inserted": inserted or {"community": 1, "member": 17, "asset": 33},
                    "warnings": [],
                }
            ],
            "dry_run": False,
        }

    def test_dry_run_prints_community_key(self):
        with patch(HTTPX_POST, return_value=make_http_response(self._multi_report())):
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
        with patch(HTTPX_POST, return_value=make_http_response(self._multi_report())):
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
        mock_post = MagicMock(return_value=make_http_response(self._multi_report()))
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

    def test_import_sends_dry_run_query_param(self):
        mock_post = MagicMock(return_value=make_http_response(self._multi_report()))
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
        assert call_kwargs["params"] == {"dry_run": "true"}

    def test_import_posts_to_yaml_endpoint(self):
        mock_post = MagicMock(return_value=make_http_response(self._multi_report()))
        with patch(HTTPX_POST, mock_post):
            runner.invoke(
                app,
                [
                    "import",
                    "--file", EXAMPLE_YAML,
                    "--token", "fake-jwt-token",
                ],
            )

        call_args, _ = mock_post.call_args
        assert call_args[0].endswith("/admin/import/yaml")

    def test_import_sends_raw_yaml_body(self):
        mock_post = MagicMock(return_value=make_http_response(self._multi_report()))
        with patch(HTTPX_POST, mock_post):
            runner.invoke(
                app,
                [
                    "import",
                    "--file", EXAMPLE_YAML,
                    "--token", "fake-jwt-token",
                ],
            )

        _, call_kwargs = mock_post.call_args
        assert "content" in call_kwargs
        assert isinstance(call_kwargs["content"], bytes)


class TestExportCommand:
    YAML_BODY = "version: '1.0'\ncommunity:\n  id: rec1\n"

    def test_export_single_community_to_stdout(self):
        with patch(HTTPX_GET, return_value=make_http_response(self.YAML_BODY)):
            result = runner.invoke(
                app,
                [
                    "export",
                    "--community", "rec1",
                    "--token", "fake-jwt-token",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "rec1" in result.output

    def test_export_sends_community_query_param(self):
        mock_get = MagicMock(return_value=make_http_response(self.YAML_BODY))
        with patch(HTTPX_GET, mock_get):
            runner.invoke(
                app,
                [
                    "export",
                    "--community", "rec1",
                    "--token", "fake-jwt-token",
                ],
            )

        _, call_kwargs = mock_get.call_args
        assert call_kwargs["params"] == [("community", "rec1")]

    def test_export_multiple_communities(self):
        mock_get = MagicMock(return_value=make_http_response(self.YAML_BODY))
        with patch(HTTPX_GET, mock_get):
            runner.invoke(
                app,
                [
                    "export",
                    "--community", "rec1",
                    "--community", "rec2",
                    "--token", "fake-jwt-token",
                ],
            )

        _, call_kwargs = mock_get.call_args
        assert call_kwargs["params"] == [("community", "rec1"), ("community", "rec2")]

    def test_export_all_communities_sends_no_community_param(self):
        mock_get = MagicMock(return_value=make_http_response(self.YAML_BODY))
        with patch(HTTPX_GET, mock_get):
            runner.invoke(
                app,
                [
                    "export",
                    "--token", "fake-jwt-token",
                ],
            )

        _, call_kwargs = mock_get.call_args
        assert call_kwargs["params"] == []

    def test_export_sends_authorization_header(self):
        mock_get = MagicMock(return_value=make_http_response(self.YAML_BODY))
        with patch(HTTPX_GET, mock_get):
            runner.invoke(
                app,
                [
                    "export",
                    "--token", "my-secret-token",
                ],
            )

        _, call_kwargs = mock_get.call_args
        assert call_kwargs["headers"]["Authorization"] == "Bearer my-secret-token"
