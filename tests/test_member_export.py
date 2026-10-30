"""The member export: what the pipelines read about members, and nothing that names one.

`GET /admin/export/members` answers, per community, its areas' boundary and topology
node ids and, per member, the member key, area, role, type, status and sensor ids. No
user id, name, DID, delivery point or extra leaves through it: the pipelines need
membership, not the person (REQ-0100).

Synthetic values only: placeholder e-mails, PODs and substation codes.
"""

from __future__ import annotations

import pytest

from celine.rec_registry.core.middleware import PolicyMiddleware
from tests.substations import substation_graph

action = PolicyMiddleware._get_admin_action

ROUTE = "/admin/export/members"

# Personal values the bundle carries. None of them may appear in the export.
PERSONAL = [
    "member.one@example.org",
    "member.two@example.org",
    "Participant One",
    "Participant Two",
    "did:web:dataspace.example:ex-00001",
    "IT001E00000001",
    "IT001E00000002",
    "Main residence",
    "declared-secret",
]


def _meter(sensor_id: str, pod: str) -> dict:
    return {
        "name": f"Meter {sensor_id}",
        "meter_type": "consumption",
        "sensor_id": sensor_id,
        "pod": pod,
    }


def _bundle(key: str) -> dict:
    return {
        "version": "1.0",
        "schema_version": "0.7",
        "community": {
            "id": key,
            "name": "Export Community",
            **substation_graph("north", "south"),
        },
        "members": {
            "ex-00001": {
                "user_id": "member.one@example.org",
                "name": "Participant One",
                "did": "did:web:dataspace.example:ex-00001",
                "type": "schema:Person",
                "role": "prosumer",
                "area": "north",
                "status": "active",
                "delivery_points": [
                    {"id": "IT001E00000001", "type": "pod", "description": "Main residence"}
                ],
                "assets": {
                    "meter": {
                        "meter-ex-sensor-0001": _meter("ex-sensor-0001", "IT001E00000001")
                    }
                },
                "declared": {"note": "declared-secret"},
            },
            "ex-00002": {
                "user_id": "member.two@example.org",
                "name": "Participant Two",
                "type": "schema:Person",
                "role": "consumer",
                "area": "south",
                "status": "suspended",
                "delivery_points": [{"id": "IT001E00000002", "type": "pod"}],
                "assets": {
                    "meter": {
                        "meter-ex-sensor-0002": _meter("ex-sensor-0002", "IT001E00000002")
                    }
                },
            },
        },
    }


async def _seed(client, key: str = "export-rec", *, members: bool = True) -> str:
    bundle = _bundle(key)
    if not members:
        # A sensor or POD has one active holder registry-wide (REQ-0069, REQ-0085).
        bundle["members"] = {}
    r = await client.post("/admin/import", json={"bundle": bundle, "dry_run": False})
    assert r.status_code == 200, r.text
    return key


class TestTheRouteHasItsOwnShape:
    def test_reading_it_is_the_export_action(self):
        """@verifies REQ-0100"""
        assert action(None, ROUTE, "GET") == "export"

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_any_other_method_derives_admin(self, method):
        """@verifies REQ-0100"""
        assert action(None, ROUTE, method) == "admin"

    @pytest.mark.parametrize("word", ["members", "lookup", "import", "export", "x"])
    def test_a_longer_path_derives_admin(self, word):
        """Only the fixed segments are read (REQ-0065): nothing after `members`
        can pick a narrower action.

        @verifies REQ-0100
        """
        assert action(None, f"{ROUTE}/{word}", "GET") == "admin"


@pytest.mark.integration
class TestTheMemberExport:
    async def test_it_carries_exactly_the_listed_fields(self, live_client):
        """@verifies REQ-0100"""
        key = await _seed(live_client)

        r = await live_client.get(ROUTE)

        assert r.status_code == 200, r.text
        assert r.json() == {
            "communities": [
                {
                    "community": key,
                    "areas": {
                        "north": {"boundary_id": "AC000E00001", "topology_ids": ["AC000E00001"]},
                        "south": {"boundary_id": "AC000E00002", "topology_ids": ["AC000E00002"]},
                    },
                    "members": [
                        {
                            "key": "ex-00001",
                            "area": "north",
                            "role": "prosumer",
                            "type": "schema:Person",
                            "status": "active",
                            "sensor_ids": ["ex-sensor-0001"],
                        },
                        {
                            "key": "ex-00002",
                            "area": "south",
                            "role": "consumer",
                            "type": "schema:Person",
                            "status": "suspended",
                            "sensor_ids": ["ex-sensor-0002"],
                        },
                    ],
                }
            ]
        }

    async def test_no_personal_value_reaches_it(self, live_client):
        """@verifies REQ-0100"""
        await _seed(live_client)

        r = await live_client.get(ROUTE)

        assert r.status_code == 200, r.text
        assert [v for v in PERSONAL if v in r.text] == []

    async def test_a_community_can_be_named(self, live_client):
        """@verifies REQ-0100"""
        await _seed(live_client, "export-rec")
        await _seed(live_client, "other-rec", members=False)

        r = await live_client.get(ROUTE, params={"community": "other-rec"})

        assert r.status_code == 200, r.text
        assert [c["community"] for c in r.json()["communities"]] == ["other-rec"]

    async def test_an_unknown_community_is_404(self, live_client):
        """@verifies REQ-0100"""
        await _seed(live_client)

        r = await live_client.get(ROUTE, params={"community": "no-such-rec"})

        assert r.status_code == 404
        assert "no-such-rec" in r.json()["detail"]
