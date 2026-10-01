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
        """@verifies REQ-0054"""
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
        """@verifies REQ-0054"""
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
        """@verifies REQ-0056"""
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
        """@verifies REQ-0054"""
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
        """@verifies REQ-0055"""
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
        # `force` rides along on every import: the destructive default is off,
        # and the CLI has to say so explicitly rather than omit the parameter.
        assert call_kwargs["params"] == {"dry_run": "true", "force": "false"}

    def test_import_posts_to_yaml_endpoint(self):
        """@verifies REQ-0054"""
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
        """@verifies REQ-0054"""
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
        """@verifies REQ-0056"""
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
        """@verifies REQ-0056"""
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
        """@verifies REQ-0056"""
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
        """@verifies REQ-0056"""
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
        """@verifies REQ-0056"""
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


# =============================================================================
# duplicate-sensors — the read-only report of pre-existing duplicates
# =============================================================================


def _export_doc(community: str, members: dict) -> dict:
    return {
        "community": {"id": community, "name": community},
        "members": {
            key: {
                "status": status,
                "assets": {
                    "meter": {
                        f"meter-{i}": {"name": "M", "sensor_id": sensor, "meter_type": "consumption"}
                        for i, sensor in enumerate(sensors)
                    }
                },
            }
            for key, (status, sensors) in members.items()
        },
    }


class TestFindDuplicateSensors:
    def test_a_sensor_held_by_two_active_members_across_communities(self):
        """@verifies REQ-0076"""
        from celine.rec_registry.cli.main import find_duplicate_sensors

        docs = [
            _export_doc("example-rec-a", {"ex-00001": ("active", ["SEN-1"])}),
            _export_doc("example-rec-b", {"ex-00009": ("active", [" SEN-1 "])}),
        ]

        assert find_duplicate_sensors(docs) == [
            ("SEN-1", [("example-rec-a", "ex-00001"), ("example-rec-b", "ex-00009")])
        ]

    def test_members_who_are_not_active_hold_nothing(self):
        """@verifies REQ-0076"""
        from celine.rec_registry.cli.main import find_duplicate_sensors

        docs = [
            _export_doc(
                "example-rec",
                {
                    "ex-00001": ("active", ["SEN-1"]),
                    "ex-00002": ("inactive", ["SEN-1"]),
                    "ex-00003": ("pending", ["SEN-1"]),
                },
            )
        ]

        assert find_duplicate_sensors(docs) == []

    def test_one_member_holding_an_id_twice_is_one_holder(self):
        """@verifies REQ-0076"""
        from celine.rec_registry.cli.main import find_duplicate_sensors

        docs = [_export_doc("example-rec", {"ex-00001": ("active", ["SEN-1", "SEN-1 "])})]

        assert find_duplicate_sensors(docs) == []


class TestDuplicateSensorsCommand:
    def _run(self, text: str, status: int = 200):
        resp = MagicMock()
        resp.status_code = status
        resp.text = text
        get = MagicMock(return_value=resp)
        post = MagicMock()
        with patch(HTTPX_GET, get), patch(HTTPX_POST, post):
            result = runner.invoke(app, ["duplicate-sensors", "--token", "fake-jwt-token"])
        return result, get, post

    def test_no_duplicates_exits_zero(self):
        """@verifies REQ-0076"""
        import yaml

        text = yaml.safe_dump(_export_doc("example-rec", {"ex-00001": ("active", ["SEN-1"])}))
        result, _, _ = self._run(text)

        assert result.exit_code == 0, result.output
        assert "No sensor id" in result.output

    def test_duplicates_are_listed_and_exit_non_zero(self):
        """@verifies REQ-0076"""
        import yaml

        text = yaml.safe_dump_all(
            [
                _export_doc("example-rec-a", {"ex-00001": ("active", ["SEN-1"])}),
                _export_doc("example-rec-b", {"ex-00009": ("active", ["SEN-1"])}),
            ]
        )
        result, _, _ = self._run(text)

        assert result.exit_code == 1, result.output
        assert "SEN-1\texample-rec-a\tex-00001\t2" in result.output
        assert "SEN-1\texample-rec-b\tex-00009\t2" in result.output

    def test_it_only_reads_the_export(self):
        """It never writes: one GET of `/admin/export`, no other request.

        @verifies REQ-0076
        """
        result, get, post = self._run("")

        assert result.exit_code == 0, result.output
        get.assert_called_once()
        assert get.call_args.args[0].endswith("/admin/export")
        assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer fake-jwt-token"
        post.assert_not_called()

    def test_an_unreadable_registry_is_not_reported_as_clean(self):
        """@verifies REQ-0076"""
        result, _, _ = self._run('{"detail": "Forbidden"}', status=403)

        assert result.exit_code == 2


# =============================================================================
# duplicate-delivery-points — the read-only report of PODs held twice (REQ-0086)
# =============================================================================


def _dp_doc(community: str, members: dict) -> dict:
    return {
        "community": {"id": community, "name": community},
        "members": {
            key: {
                "status": status,
                "delivery_points": [{"id": pod, "type": "pod"} for pod in pods],
            }
            for key, (status, pods) in members.items()
        },
    }


POD = "IT001E00000001"


class TestFindDuplicateDeliveryPoints:
    def test_a_point_held_by_two_active_members_across_communities(self):
        """Compared trimmed and case-insensitively, reported in that form.

        @verifies REQ-0086
        """
        from celine.rec_registry.cli.main import find_duplicate_delivery_points

        docs = [
            _dp_doc("example-rec-a", {"ex-00001": ("active", [POD])}),
            _dp_doc("example-rec-b", {"ex-00009": ("active", [f" {POD.lower()}\t"])}),
            _dp_doc("example-rec-c", {"ex-00005": ("active", [f"\u00a0{POD}"])}),
        ]

        assert find_duplicate_delivery_points(docs) == [
            (
                POD.lower(),
                [
                    ("example-rec-a", "ex-00001"),
                    ("example-rec-b", "ex-00009"),
                    ("example-rec-c", "ex-00005"),
                ],
            )
        ]

    def test_two_holders_in_one_community_are_listed_too(self):
        """@verifies REQ-0086"""
        from celine.rec_registry.cli.main import find_duplicate_delivery_points

        docs = [
            _dp_doc(
                "example-rec",
                {"ex-00001": ("active", [POD]), "ex-00002": ("active", [POD])},
            )
        ]

        assert find_duplicate_delivery_points(docs) == [
            (POD.lower(), [("example-rec", "ex-00001"), ("example-rec", "ex-00002")])
        ]

    def test_members_who_are_not_active_hold_nothing(self):
        """@verifies REQ-0086"""
        from celine.rec_registry.cli.main import find_duplicate_delivery_points

        docs = [
            _dp_doc(
                "example-rec",
                {
                    "ex-00001": ("active", [POD]),
                    "ex-00002": ("inactive", [POD]),
                    "ex-00003": ("pending", [POD]),
                    "ex-00004": ("suspended", [POD]),
                },
            )
        ]

        assert find_duplicate_delivery_points(docs) == []

    def test_one_member_listing_a_point_twice_is_one_holder(self):
        """@verifies REQ-0086"""
        from celine.rec_registry.cli.main import find_duplicate_delivery_points

        docs = [_dp_doc("example-rec", {"ex-00001": ("active", [POD, POD.lower()])})]

        assert find_duplicate_delivery_points(docs) == []

    def test_blank_and_malformed_points_are_skipped(self):
        """@verifies REQ-0086"""
        from celine.rec_registry.cli.main import find_duplicate_delivery_points

        docs = [
            _dp_doc("example-rec", {"ex-00001": ("active", ["  "]), "ex-00002": ("active", [" "])}),
            {"community": {"id": "x"}, "members": {"m": {"status": "active", "delivery_points": ["bad", None, {"id": 7}]}}},
            "not a bundle",
        ]

        assert find_duplicate_delivery_points(docs) == []


class TestDuplicateDeliveryPointsCommand:
    def _run(self, text: str, status: int = 200):
        resp = MagicMock()
        resp.status_code = status
        resp.text = text
        get = MagicMock(return_value=resp)
        post = MagicMock()
        with patch(HTTPX_GET, get), patch(HTTPX_POST, post):
            result = runner.invoke(
                app, ["duplicate-delivery-points", "--token", "fake-jwt-token"]
            )
        return result, get, post

    def test_no_duplicates_exits_zero(self):
        """@verifies REQ-0086"""
        import yaml

        text = yaml.safe_dump(_dp_doc("example-rec", {"ex-00001": ("active", [POD])}))
        result, _, _ = self._run(text)

        assert result.exit_code == 0, result.output
        assert "No delivery point" in result.output

    def test_duplicates_are_listed_one_line_per_holder_and_exit_non_zero(self):
        """@verifies REQ-0086"""
        import yaml

        text = yaml.safe_dump_all(
            [
                _dp_doc("example-rec-a", {"ex-00001": ("active", [POD])}),
                _dp_doc("example-rec-b", {"ex-00009": ("active", [POD.lower()])}),
            ]
        )
        result, _, _ = self._run(text)

        assert result.exit_code == 1, result.output
        assert "delivery_point\tcommunity\tmember\tactive_holders" in result.output
        assert f"{POD.lower()}\texample-rec-a\tex-00001\t2" in result.output
        assert f"{POD.lower()}\texample-rec-b\tex-00009\t2" in result.output

    def test_it_only_reads_the_export(self):
        """One GET of `/admin/export`, no other request.

        @verifies REQ-0086
        """
        result, get, post = self._run("")

        assert result.exit_code == 0, result.output
        get.assert_called_once()
        assert get.call_args.args[0].endswith("/admin/export")
        assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer fake-jwt-token"
        post.assert_not_called()

    def test_an_unreadable_registry_is_not_reported_as_clean(self):
        """@verifies REQ-0086"""
        result, _, _ = self._run('{"detail": "Forbidden"}', status=403)

        assert result.exit_code == 2


# =============================================================================
# invalid-area-boundaries — the read-only report of areas breaking REQ-0067
# =============================================================================


def _area_doc(community: str, areas: dict, topology: list) -> dict:
    return {
        "community": {"id": community, "name": community, "areas": areas, "topology": topology},
        "members": {},
    }


def _good(community: str = "example-rec") -> dict:
    from tests.substations import substation_graph

    graph = substation_graph("north", "south")
    return _area_doc(community, graph["areas"], graph["topology"])


def _broken(community: str = "example-rec-old") -> dict:
    from tests.substations import substation_area, substation_code, substation_node

    two_nodes = substation_area("East", 3)
    two_nodes["topology"].append(substation_code(4))
    return _area_doc(
        community,
        {
            "legacy": {"name": "Legacy", "topology": [substation_code(1)]},
            "east": two_nodes,
            "north": substation_area("North", 1),
        },
        [substation_node(n) for n in (1, 3, 4)],
    )


class TestFindInvalidAreaBoundaries:
    def test_a_community_that_keeps_the_rule_reports_nothing(self):
        """@verifies REQ-0078"""
        from celine.rec_registry.cli.main import find_invalid_area_boundaries

        assert find_invalid_area_boundaries([_good()]) == []

    def test_every_broken_rule_is_reported_by_community(self):
        """Judged with the check the writes use, over every area.

        @verifies REQ-0078
        """
        from celine.rec_registry.cli.main import find_invalid_area_boundaries
        from celine.rec_registry.core.area_boundary import area_boundary_refusals

        broken = _broken()
        found = find_invalid_area_boundaries([_good(), broken])

        expected = area_boundary_refusals(
            broken["community"]["areas"], broken["community"]["topology"]
        )
        assert found == sorted(("example-rec-old", d) for d in expected)
        assert any("'legacy'" in d and "no boundary" in d for _, d in found)
        assert any("'east'" in d and "2 topology nodes" in d for _, d in found)
        assert not any("'north'" in d for _, d in found)

    def test_a_key_that_is_not_an_area_key_is_reported(self):
        """A stored key a re-import would refuse `invalid_area_key` (REQ-0067),
        judged with the function the import uses, before the boundary lines.

        @verifies REQ-0078
        """
        from tests.substations import substation_area, substation_node

        from celine.rec_registry.cli.main import find_invalid_area_boundaries
        from celine.rec_registry.core.area_boundary import area_key_refusals

        areas = {
            "north zone": substation_area("North", 1),
            "south.2": substation_area("South", 2),
            "east": substation_area("East", 3),
        }
        doc = _area_doc(
            "example-rec-old", areas, [substation_node(n) for n in (1, 2, 3)]
        )

        found = find_invalid_area_boundaries([_good(), doc])

        assert found == sorted(("example-rec-old", d) for d in area_key_refusals(areas))
        assert len(found) == 2
        assert any("'north zone'" in d and "not an area key" in d for _, d in found)
        assert any("'south.2'" in d for _, d in found)
        assert not any("'east'" in d for _, d in found)

    def test_a_refusal_names_no_boundary_or_node_id(self):
        """@verifies REQ-0078"""
        from celine.rec_registry.cli.main import find_invalid_area_boundaries

        for _, detail in find_invalid_area_boundaries([_broken()]):
            assert "AC000E" not in detail

    def test_a_community_with_no_areas_reports_nothing(self):
        """@verifies REQ-0078"""
        from celine.rec_registry.cli.main import find_invalid_area_boundaries

        doc = {"community": {"id": "example-rec", "name": "x"}, "members": {}}
        assert find_invalid_area_boundaries([doc]) == []


class TestInvalidAreaBoundariesCommand:
    def _run(self, text: str, status: int = 200):
        resp = MagicMock()
        resp.status_code = status
        resp.text = text
        get = MagicMock(return_value=resp)
        post = MagicMock()
        with patch(HTTPX_GET, get), patch(HTTPX_POST, post):
            result = runner.invoke(
                app, ["invalid-area-boundaries", "--token", "fake-jwt-token"]
            )
        return result, get, post

    def test_none_exits_zero(self):
        """@verifies REQ-0078"""
        import yaml

        result, _, _ = self._run(yaml.safe_dump(_good()))

        assert result.exit_code == 0, result.output
        assert "keeps the one-substation rule" in result.output

    def test_broken_areas_are_listed_and_exit_non_zero(self):
        """@verifies REQ-0078"""
        import yaml

        result, _, _ = self._run(yaml.safe_dump_all([_good(), _broken()]))

        assert result.exit_code == 1, result.output
        assert "community\trefusal" in result.output
        assert "example-rec-old\tarea 'legacy' carries no boundary" in result.output
        assert "example-rec\t" not in result.output.replace("example-rec-old\t", "")

    def test_it_only_reads_the_export(self):
        """One GET of `/admin/export`, no other request.

        @verifies REQ-0078
        """
        result, get, post = self._run("")

        assert result.exit_code == 0, result.output
        get.assert_called_once()
        assert get.call_args.args[0].endswith("/admin/export")
        assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer fake-jwt-token"
        post.assert_not_called()

    def test_an_unreadable_registry_is_not_reported_as_clean(self):
        """@verifies REQ-0078"""
        result, _, _ = self._run('{"detail": "Forbidden"}', status=403)

        assert result.exit_code == 2
