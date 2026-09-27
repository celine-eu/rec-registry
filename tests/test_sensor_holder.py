"""One active holder per sensor id, attaching and detaching a meter, and the codes
a refusal carries.

A sensor id is how a reading finds its owner. Two active members holding one
double-count every reading of it downstream, and nothing there can tell — so
every path that can make an active member hold a sensor refuses a second one:
the asset `PUT`, creating a member with meters, a move to `active`, and the
bundle import (ADR-0004). A community manager attaches a meter by typing the id
printed on the device, with nothing to pick from, so the registry's answer is
the only feedback they get: attached, already attached, `sensor_held`, or
`asset_key_taken` — told apart by `code`, never by the sentence (ADR-0008).

Fixtures are generic: `example-rec`, `ex-0000n`, `SEN-…`.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from celine.rec_registry.core.errors import ErrorCode
from celine.rec_registry.schemas.bundle import MeterAssetIn
from celine.rec_registry.services import members as member_service
from celine.rec_registry.services.sensors import normalise_sensor_id

pytestmark = pytest.mark.asyncio


# =============================================================================
# Helpers
# =============================================================================


def _member(key: str, user_id: str, *, status: str = "active", meters=None) -> dict:
    payload = {
        "key": key,
        "user_id": user_id,
        "name": "Example Member",
        "role": "consumer",
        "area": "north",
        "status": status,
    }
    if meters:
        payload["assets"] = {
            "meter": {
                asset_key: {
                    "name": "Meter",
                    "sensor_id": sensor_id,
                    "meter_type": "consumption",
                }
                for asset_key, sensor_id in meters.items()
            }
        }
    return payload


def _meter(sensor_id: str, key: str | None = None) -> dict:
    return {
        "key": key or f"meter-{sensor_id.strip()}",
        "asset_type": "meter",
        "properties": {
            "name": "Meter",
            "sensor_id": sensor_id,
            "meter_type": "consumption",
        },
    }


def _bundle(key: str, members: dict | None = None) -> dict:
    return {
        "version": "1.0",
        "schema_version": "0.6",
        "community": {
            "id": key,
            "name": "Example Community",
            "areas": {"north": {"name": "north"}, "south": {"name": "south"}},
        },
        "members": members or {},
    }


async def _community(client, key: str = "example-rec", members: dict | None = None):
    r = await client.post("/admin/import", json={"bundle": _bundle(key, members)})
    assert r.status_code == 200, r.text
    return key


async def _add(client, community: str, key: str, user_id: str, **kwargs):
    r = await client.post(
        f"/admin/communities/{community}/members", json=_member(key, user_id, **kwargs)
    )
    assert r.status_code == 201, r.text
    return key


async def _attach(client, community: str, member: str, sensor_id: str, key=None):
    body = _meter(sensor_id, key)
    return await client.put(
        f"/admin/communities/{community}/members/{member}/assets/{body['key']}",
        json=body,
    )


async def _assets(client, community: str, owner: str | None = None) -> list[dict]:
    params = {"owner": owner} if owner else {}
    r = await client.get(f"/admin/communities/{community}/assets", params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _refusal(r, status: int, code: str) -> str:
    """Assert the coded body of REQ-0073 and hand back the sentence."""
    assert r.status_code == status, r.text
    body = r.json()
    assert body["code"] == code, body
    assert isinstance(body["detail"], str), "detail must stay a string"
    return body["detail"]


# =============================================================================
# The trimmed form — pure
# =============================================================================


class TestTheTrimmedForm:
    @pytest.mark.parametrize(
        "raw,stored",
        [
            ("SEN-1", "SEN-1"),
            ("  SEN-1 ", "SEN-1"),
            ("\tSEN-1\n", "SEN-1"),
            ("\u00a0SEN-1\u00a0", "SEN-1"),
            ("\u2003SEN-1\r\n", "SEN-1"),
        ],
    )
    def test_a_sensor_id_is_compared_and_stored_trimmed(self, raw, stored):
        """@verifies REQ-0069"""
        assert normalise_sensor_id(raw) == stored

    @pytest.mark.parametrize("raw", [None, "", "   ", "\t\n"])
    def test_blank_after_trimming_is_missing(self, raw):
        """@verifies REQ-0069"""
        assert normalise_sensor_id(raw) is None

    def test_trimmed_means_what_python_strips(self):
        """One definition for Python and SQL: the spelled-out set is exactly the
        characters `str.isspace()` accepts, so `normalise_sensor_id` agrees with
        `str.strip()` and the SQL `btrim` given the same set agrees with both.

        @verifies REQ-0069
        """
        import sys

        from celine.rec_registry.core.sensor_id import WHITESPACE

        expected = {c for c in map(chr, range(sys.maxunicode + 1)) if c.isspace()}
        assert set(WHITESPACE) == expected
        assert len(WHITESPACE) == len(expected)


# =============================================================================
# The asset PUT
# =============================================================================


@pytest.mark.integration
class TestAttachingAMeter:
    async def test_a_meter_is_attached_at_its_sensor_key(self, live_client):
        """@verifies REQ-0071"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")

        r = await _attach(live_client, c, "ex-00001", "SEN-1")

        assert r.status_code == 200, r.text
        assert r.json()["key"] == "meter-SEN-1"
        assert r.json()["sensor_id"] == "SEN-1"

    async def test_attaching_it_again_to_the_same_member_is_a_no_op(self, live_client):
        """@verifies REQ-0071"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        first = await _attach(live_client, c, "ex-00001", "SEN-1")

        again = await _attach(live_client, c, "ex-00001", "SEN-1")

        assert again.status_code == 200, again.text
        assert again.json()["id"] == first.json()["id"]
        assert [a["key"] for a in await _assets(live_client, c)] == ["meter-SEN-1"]

    async def test_the_sensor_id_is_stored_trimmed(self, live_client):
        """@verifies REQ-0069"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")

        r = await _attach(live_client, c, "ex-00001", "  SEN-1  ", key="meter-SEN-1")

        assert r.status_code == 200, r.text
        assert r.json()["sensor_id"] == "SEN-1"

    async def test_a_blank_sensor_id_is_refused(self, live_client):
        """@verifies REQ-0071"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")

        r = await _attach(live_client, c, "ex-00001", "   ", key="meter-blank")

        assert r.status_code == 422, r.text
        assert await _assets(live_client, c) == []

    async def test_a_sensor_another_active_member_holds_is_sensor_held(self, live_client):
        """Inside the community the holder is named, as the DID clash names its.

        @verifies REQ-0069
        @verifies REQ-0071
        """
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        await _add(live_client, c, "ex-00002", "kc-0002")
        assert (await _attach(live_client, c, "ex-00001", "SEN-1")).status_code == 200

        r = await _attach(live_client, c, "ex-00002", "SEN-1")

        detail = _refusal(r, 409, "sensor_held")
        assert "ex-00001" in detail
        assert "SEN-1" not in detail
        assert [a["key"] for a in await _assets(live_client, c, "ex-00002")] == []

    async def test_the_comparison_is_on_the_trimmed_id(self, live_client):
        """@verifies REQ-0069"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        await _add(live_client, c, "ex-00002", "kc-0002")
        await _attach(live_client, c, "ex-00001", "SEN-1")

        r = await _attach(live_client, c, "ex-00002", " SEN-1 ", key="other-key")

        _refusal(r, 409, "sensor_held")

    async def test_an_untrimmed_id_already_stored_still_counts(self, live_client, pg_engine):
        """Rows written before ids were trimmed are compared trimmed too.

        @verifies REQ-0069
        """
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        await _add(live_client, c, "ex-00002", "kc-0002")
        await _attach(live_client, c, "ex-00001", "SEN-1")
        async with pg_engine.begin() as conn:
            await conn.execute(text("update asset set sensor_id = '  SEN-1 '"))

        r = await _attach(live_client, c, "ex-00002", "SEN-1")

        _refusal(r, 409, "sensor_held")

    async def test_a_holder_in_another_community_is_not_named(self, live_client):
        """Neither the member nor its community: which member of which other
        community holds a sensor is the enumeration REQ-0045 refuses.

        @verifies REQ-0069
        """
        a = await _community(live_client, "example-rec-a")
        b = await _community(live_client, "example-rec-b")
        await _add(live_client, a, "ex-00001", "kc-0001")
        await _add(live_client, b, "ex-00009", "kc-0009")
        assert (await _attach(live_client, a, "ex-00001", "SEN-1")).status_code == 200

        r = await _attach(live_client, b, "ex-00009", "SEN-1")

        detail = _refusal(r, 409, "sensor_held")
        assert "ex-00001" not in detail
        assert "example-rec-a" not in detail

    async def test_an_inactive_member_holds_nothing(self, live_client):
        """Deactivating releases the sensor: another community may take it.

        @verifies REQ-0069
        """
        a = await _community(live_client, "example-rec-a")
        b = await _community(live_client, "example-rec-b")
        await _add(live_client, a, "ex-00001", "kc-0001")
        await _add(live_client, b, "ex-00009", "kc-0009")
        await _attach(live_client, a, "ex-00001", "SEN-1")
        await live_client.delete(f"/admin/communities/{a}/members/ex-00001")

        r = await _attach(live_client, b, "ex-00009", "SEN-1")

        assert r.status_code == 200, r.text

    async def test_an_inactive_member_still_holding_the_key_is_asset_key_taken(
        self, live_client
    ):
        """Not `sensor_held`: nobody active holds the sensor, and the remedy
        differs — delete that asset, then attach.

        @verifies REQ-0071
        """
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        await _add(live_client, c, "ex-00002", "kc-0002")
        await _attach(live_client, c, "ex-00001", "SEN-1")
        await live_client.delete(f"/admin/communities/{c}/members/ex-00001")

        r = await _attach(live_client, c, "ex-00002", "SEN-1")

        _refusal(r, 409, "asset_key_taken")

    async def test_attaching_to_a_member_who_is_not_active_is_not_checked(
        self, live_client
    ):
        """Only an active member holds, so the check waits for the reactivation.

        @verifies REQ-0069
        """
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        await _add(live_client, c, "ex-00002", "kc-0002", status="pending")
        await _attach(live_client, c, "ex-00001", "SEN-1")

        r = await _attach(live_client, c, "ex-00002", "SEN-1", key="pending-meter")

        assert r.status_code == 200, r.text


# =============================================================================
# Detaching
# =============================================================================


@pytest.mark.integration
class TestDetachingAMeter:
    async def test_detaching_deletes_the_asset(self, live_client):
        """@verifies REQ-0071"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        await _attach(live_client, c, "ex-00001", "SEN-1")

        r = await live_client.delete(
            f"/admin/communities/{c}/members/ex-00001/assets/meter-SEN-1"
        )

        assert r.status_code == 204, r.text
        assert await _assets(live_client, c) == []

    async def test_a_detached_sensor_can_be_attached_to_someone_else(self, live_client):
        """@verifies REQ-0071"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        await _add(live_client, c, "ex-00002", "kc-0002")
        await _attach(live_client, c, "ex-00001", "SEN-1")
        await live_client.delete(
            f"/admin/communities/{c}/members/ex-00001/assets/meter-SEN-1"
        )

        r = await _attach(live_client, c, "ex-00002", "SEN-1")

        assert r.status_code == 200, r.text

    async def test_deleting_an_asset_the_member_does_not_hold_is_404(self, live_client):
        """Including one another member of the community holds.

        @verifies REQ-0028
        @verifies REQ-0071
        """
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        await _add(live_client, c, "ex-00002", "kc-0002")
        await _attach(live_client, c, "ex-00001", "SEN-1")

        absent = await live_client.delete(
            f"/admin/communities/{c}/members/ex-00002/assets/meter-SEN-9"
        )
        someone_elses = await live_client.delete(
            f"/admin/communities/{c}/members/ex-00002/assets/meter-SEN-1"
        )

        _refusal(absent, 404, "asset_not_found")
        _refusal(someone_elses, 404, "asset_not_found")
        assert [a["key"] for a in await _assets(live_client, c, "ex-00001")] == [
            "meter-SEN-1"
        ]


# =============================================================================
# Creating a member with meters
# =============================================================================


@pytest.mark.integration
class TestCreatingAMemberWithMeters:
    async def test_an_active_member_with_a_held_sensor_is_refused(self, live_client):
        """@verifies REQ-0069"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        await _attach(live_client, c, "ex-00001", "SEN-1")

        r = await live_client.post(
            f"/admin/communities/{c}/members",
            json=_member("ex-00002", "kc-0002", meters={"m-2": " SEN-1"}),
        )

        _refusal(r, 409, "sensor_held")
        missing = await live_client.get(f"/admin/communities/{c}/members/ex-00002")
        assert missing.status_code == 404

    async def test_across_communities_too(self, live_client):
        """@verifies REQ-0069"""
        a = await _community(live_client, "example-rec-a")
        b = await _community(live_client, "example-rec-b")
        await _add(live_client, a, "ex-00001", "kc-0001")
        await _attach(live_client, a, "ex-00001", "SEN-1")

        r = await live_client.post(
            f"/admin/communities/{b}/members",
            json=_member("ex-00009", "kc-0009", meters={"m-9": "SEN-1"}),
        )

        detail = _refusal(r, 409, "sensor_held")
        assert "ex-00001" not in detail and "example-rec-a" not in detail

    async def test_a_pending_member_is_created_and_holds_nothing_yet(self, live_client):
        """@verifies REQ-0069"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        await _attach(live_client, c, "ex-00001", "SEN-1")

        r = await live_client.post(
            f"/admin/communities/{c}/members",
            json=_member("ex-00002", "kc-0002", status="pending", meters={"m-2": "SEN-1"}),
        )

        assert r.status_code == 201, r.text

    async def test_meters_created_with_a_member_are_stored_trimmed(self, live_client):
        """@verifies REQ-0069"""
        c = await _community(live_client)
        r = await live_client.post(
            f"/admin/communities/{c}/members",
            json=_member("ex-00001", "kc-0001", meters={"m-1": "  SEN-1 "}),
        )
        assert r.status_code == 201, r.text

        assert [a["sensor_id"] for a in await _assets(live_client, c)] == ["SEN-1"]


# =============================================================================
# Reactivation
# =============================================================================


@pytest.mark.integration
class TestReactivation:
    async def _taken_meanwhile(self, live_client) -> str:
        """ex-00001 held SEN-1, was suspended, and ex-00002 took it."""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        await _add(live_client, c, "ex-00002", "kc-0002")
        await _attach(live_client, c, "ex-00001", "SEN-1")
        r = await live_client.post(
            f"/admin/communities/{c}/members/ex-00001/status",
            json={"status": "suspended"},
        )
        assert r.status_code == 200, r.text
        taken = await _attach(live_client, c, "ex-00002", "SEN-1", key="m-2")
        assert taken.status_code == 200, taken.text
        return c

    async def _status(self, live_client, c: str, member: str) -> str:
        r = await live_client.get(f"/admin/communities/{c}/members/{member}")
        return r.json()["status"]

    async def test_the_status_route_refuses_and_leaves_the_status(self, live_client):
        """@verifies REQ-0069"""
        c = await self._taken_meanwhile(live_client)

        r = await live_client.post(
            f"/admin/communities/{c}/members/ex-00001/status",
            json={"status": "active", "reason": "back"},
        )

        _refusal(r, 409, "sensor_held")
        assert await self._status(live_client, c, "ex-00001") == "suspended"

    async def test_patch_refuses_the_whole_patch(self, live_client):
        """@verifies REQ-0069"""
        c = await self._taken_meanwhile(live_client)

        r = await live_client.patch(
            f"/admin/communities/{c}/members/ex-00001",
            json={"status": "active", "name": "Renamed"},
        )

        _refusal(r, 409, "sensor_held")
        member = await live_client.get(f"/admin/communities/{c}/members/ex-00001")
        assert member.json()["status"] == "suspended"
        assert member.json()["name"] == "Example Member"

    async def test_a_holder_in_another_community_blocks_it_unnamed(self, live_client):
        """@verifies REQ-0069"""
        a = await _community(live_client, "example-rec-a")
        b = await _community(live_client, "example-rec-b")
        await _add(live_client, a, "ex-00001", "kc-0001", status="inactive")
        await _attach(live_client, a, "ex-00001", "SEN-1")
        await _add(live_client, b, "ex-00009", "kc-0009")
        await _attach(live_client, b, "ex-00009", "SEN-1")

        r = await live_client.post(
            f"/admin/communities/{a}/members/ex-00001/status", json={"status": "active"}
        )

        detail = _refusal(r, 409, "sensor_held")
        assert "ex-00009" not in detail and "example-rec-b" not in detail

    async def test_reactivation_succeeds_once_the_sensor_is_free(self, live_client):
        """@verifies REQ-0069"""
        c = await self._taken_meanwhile(live_client)
        await live_client.delete(f"/admin/communities/{c}/members/ex-00002/assets/m-2")

        r = await live_client.post(
            f"/admin/communities/{c}/members/ex-00001/status", json={"status": "active"}
        )

        assert r.status_code == 200, r.text
        assert r.json()["status"] == "active"

    async def test_an_already_active_member_is_not_re_checked(self, live_client, pg_engine):
        """Only a move *to* active is a reactivation. Pre-existing duplicates
        (the report finds them) do not block unrelated writes.

        @verifies REQ-0069
        """
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        await _add(live_client, c, "ex-00002", "kc-0002", status="pending")
        await _attach(live_client, c, "ex-00001", "SEN-1")
        await _attach(live_client, c, "ex-00002", "SEN-1", key="m-2")
        async with pg_engine.begin() as conn:
            await conn.execute(text("update member set status = 'active'"))

        r = await live_client.patch(
            f"/admin/communities/{c}/members/ex-00001",
            json={"status": "active", "name": "Still here"},
        )

        assert r.status_code == 200, r.text


# =============================================================================
# The bundle import
# =============================================================================


def _holder(key: str, user_id: str, sensor_id: str, status: str = "active") -> dict:
    return {
        "user_id": user_id,
        "name": "Example Member",
        "role": "consumer",
        "area": "north",
        "status": status,
        "assets": {
            "meter": {
                f"meter-{key}": {
                    "name": "Meter",
                    "sensor_id": sensor_id,
                    "meter_type": "consumption",
                }
            }
        },
    }


@pytest.mark.integration
class TestTheImport:
    async def test_two_active_holders_in_one_bundle_are_refused(self, live_client):
        """Refused whole: nothing is written.

        @verifies REQ-0069
        """
        bundle = _bundle(
            "example-rec",
            {
                "ex-00001": _holder("ex-00001", "kc-0001", "SEN-1"),
                "ex-00002": _holder("ex-00002", "kc-0002", " SEN-1 "),
            },
        )

        r = await live_client.post("/admin/import", json={"bundle": bundle})

        detail = _refusal(r, 422, "sensor_held")
        assert "ex-00001" in detail and "ex-00002" in detail
        assert "SEN-1" not in detail
        assert (await live_client.get("/admin/communities/example-rec")).status_code == 404

    async def test_a_dry_run_reports_it_instead(self, live_client):
        """@verifies REQ-0069"""
        bundle = _bundle(
            "example-rec",
            {
                "ex-00001": _holder("ex-00001", "kc-0001", "SEN-1"),
                "ex-00002": _holder("ex-00002", "kc-0002", "SEN-1"),
            },
        )

        r = await live_client.post(
            "/admin/import", json={"bundle": bundle, "dry_run": True}
        )

        assert r.status_code == 200, r.text
        refusals = r.json()["refusals"]
        assert [x["code"] for x in refusals] == ["sensor_held"]
        assert (await live_client.get("/admin/communities/example-rec")).status_code == 404

    async def test_a_sensor_held_in_another_community_refuses_it_unnamed(
        self, live_client
    ):
        """@verifies REQ-0069"""
        other = await _community(live_client, "example-rec-a")
        await _add(live_client, other, "ex-00001", "kc-0001")
        await _attach(live_client, other, "ex-00001", "SEN-1")
        bundle = _bundle("example-rec-b", {"ex-00009": _holder("ex-00009", "kc-0009", "SEN-1")})

        r = await live_client.post("/admin/import", json={"bundle": bundle})
        dry = await live_client.post(
            "/admin/import", json={"bundle": bundle, "dry_run": True}
        )

        detail = _refusal(r, 422, "sensor_held")
        assert "ex-00009" in detail
        assert "ex-00001" not in detail and "example-rec-a" not in detail
        assert [x["code"] for x in dry.json()["refusals"]] == ["sensor_held"]
        assert "example-rec-a" not in dry.text

    async def test_the_replaced_communitys_own_rows_do_not_count(self, live_client):
        """The import deletes them, so re-importing a community holding a
        sensor is not a clash with itself.

        @verifies REQ-0069
        """
        members = {"ex-00001": _holder("ex-00001", "kc-0001", "SEN-1")}
        await _community(live_client, "example-rec", members)

        r = await live_client.post(
            "/admin/import",
            json={"bundle": _bundle("example-rec", members), "force": True},
        )

        assert r.status_code == 200, r.text

    async def test_an_inactive_holder_in_the_bundle_is_not_a_clash(self, live_client):
        """@verifies REQ-0069"""
        other = await _community(live_client, "example-rec-a")
        await _add(live_client, other, "ex-00001", "kc-0001")
        await _attach(live_client, other, "ex-00001", "SEN-1")
        bundle = _bundle(
            "example-rec-b",
            {
                "ex-00008": _holder("ex-00008", "kc-0008", "SEN-1", status="inactive"),
                "ex-00009": _holder("ex-00009", "kc-0009", "SEN-1", status="pending"),
            },
        )

        r = await live_client.post("/admin/import", json={"bundle": bundle})

        assert r.status_code == 200, r.text
        assert r.json()["refusals"] == []

    async def test_the_yaml_import_refuses_too(self, live_client):
        """@verifies REQ-0069"""
        bundle = _bundle(
            "example-rec",
            {
                "ex-00001": _holder("ex-00001", "kc-0001", "SEN-1"),
                "ex-00002": _holder("ex-00002", "kc-0002", "SEN-1"),
            },
        )
        body = yaml.safe_dump(bundle).encode()

        r = await live_client.post("/admin/import/yaml", content=body)
        dry = await live_client.post(
            "/admin/import/yaml", content=body, params={"dry_run": "true"}
        )

        _refusal(r, 422, "sensor_held")
        assert dry.status_code == 200, dry.text
        assert [x["code"] for x in dry.json()["reports"][0]["refusals"]] == [
            "sensor_held"
        ]

    async def test_imported_sensor_ids_are_stored_trimmed(self, live_client):
        """@verifies REQ-0069"""
        await _community(
            live_client,
            "example-rec",
            {"ex-00001": _holder("ex-00001", "kc-0001", "  SEN-1\t")},
        )

        assert [a["sensor_id"] for a in await _assets(live_client, "example-rec")] == [
            "SEN-1"
        ]

    async def test_a_sensor_id_blank_after_trimming_is_skipped_with_a_warning(
        self, live_client
    ):
        """@verifies REQ-0069"""
        r = await live_client.post(
            "/admin/import",
            json={
                "bundle": _bundle(
                    "example-rec", {"ex-00001": _holder("ex-00001", "kc-0001", "   ")}
                )
            },
        )

        assert r.status_code == 200, r.text
        assert any("meter-ex-00001" in w for w in r.json()["warnings"])
        assert await _assets(live_client, "example-rec") == []


# =============================================================================
# Two writers attaching one sensor at once
# =============================================================================


async def _wait_until_blocked(engine, holder_pid: int, *, timeout: float = 10.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    async with engine.connect() as conn:
        while loop.time() < deadline:
            waiting = await conn.scalar(
                text(
                    "select count(*) from pg_stat_activity "
                    "where :holder = any(pg_blocking_pids(pid))"
                ),
                {"holder": holder_pid},
            )
            if waiting:
                return
            await asyncio.sleep(0.01)
    raise AssertionError(
        f"no backend ever waited on pid {holder_pid}; the second attach did not "
        "reach the advisory lock, so this test would pass for the wrong reason"
    )


@pytest.mark.integration
class TestTwoAttachesAtOnce:
    """Neither writer can see the other's uncommitted asset, and no unique index
    can say "among active members" — the advisory lock is the only thing
    between two managers and two holders."""

    async def test_the_second_waits_for_the_first_and_is_sensor_held(
        self, live_client, pg_engine
    ):
        """Held open deliberately, as `TestTwoWritersAtOnce` does: a race that
        resolves the other way would prove nothing about the lock.

        @verifies REQ-0069
        """
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        await _add(live_client, c, "ex-00002", "kc-0002")

        maker = async_sessionmaker(pg_engine, expire_on_commit=False)
        async with maker() as holder:
            holder_pid = await holder.scalar(text("select pg_backend_pid()"))
            community = await member_service.resolve_community(holder, c)
            member = await member_service.resolve_member(holder, community, "ex-00001")
            await member_service.upsert_asset(
                holder,
                community=community,
                member=member,
                asset_key="meter-SEN-1",
                asset_type="meter",
                payload=MeterAssetIn(
                    name="Meter", sensor_id="SEN-1", meter_type="consumption"
                ),
            )
            # Flushed, not committed: invisible to the request below, which
            # would pass its check and insert if it did not wait on the lock.

            request = asyncio.create_task(_attach(live_client, c, "ex-00002", "SEN-1", "k2"))
            await _wait_until_blocked(pg_engine, holder_pid)
            await holder.commit()
            r = await request

        _refusal(r, 409, "sensor_held")
        assert [a["key"] for a in await _assets(live_client, "example-rec")] == [
            "meter-SEN-1"
        ]

    async def test_of_a_concurrent_pair_exactly_one_wins(self, live_client):
        """@verifies REQ-0069"""
        a = await _community(live_client, "example-rec-a")
        b = await _community(live_client, "example-rec-b")
        await _add(live_client, a, "ex-00001", "kc-0001")
        await _add(live_client, b, "ex-00009", "kc-0009")

        for round_ in range(5):
            sensor = f"SEN-RACE-{round_}"
            first, second = await asyncio.gather(
                _attach(live_client, a, "ex-00001", sensor),
                _attach(live_client, b, "ex-00009", sensor),
            )
            statuses = sorted([first.status_code, second.status_code])
            assert statuses == [200, 409], (first.text, second.text)
            loser = first if first.status_code == 409 else second
            assert loser.json()["code"] == "sensor_held"


# =============================================================================
# Codes (REQ-0073)
# =============================================================================


SPEC = Path(__file__).parent.parent / "docs" / "specifications" / "member-writes.md"


class TestTheCodeVocabulary:
    def test_the_codes_are_the_ones_the_requirement_lists(self):
        """The enum and the table in REQ-0073 are one list: a code in either and
        not the other is a code nobody reviewed, or one nobody implemented.

        @verifies REQ-0073
        """
        text_ = SPEC.read_text()
        section = text_.split("### REQ-0073", 1)[1].split("\n### ", 1)[0]
        table, _, _planned = section.partition("**Planned:**")
        listed = set(re.findall(r"^\| `([a-z_]+)` \|", table, re.M))
        assert listed == {c.value for c in ErrorCode}

    def test_a_code_carries_no_identifier(self):
        """@verifies REQ-0073"""
        for code in ErrorCode:
            assert re.fullmatch(r"[a-z]+(_[a-z]+)*", code.value), code


@pytest.mark.integration
class TestEveryRefusalCarriesItsCode:
    async def test_writes_to_an_unknown_community_or_member(self, live_client):
        """@verifies REQ-0073"""
        c = await _community(live_client)

        _refusal(
            await live_client.post(
                "/admin/communities/nowhere/members", json=_member("ex-1", "kc-1")
            ),
            404,
            "community_not_found",
        )
        _refusal(
            await live_client.patch(
                f"/admin/communities/{c}/members/nobody", json={"name": "x"}
            ),
            404,
            "member_not_found",
        )
        _refusal(await _attach(live_client, c, "nobody", "SEN-1"), 404, "member_not_found")

    async def test_member_key_user_id_and_did_clashes(self, live_client):
        """@verifies REQ-0073"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        await _add(live_client, c, "ex-00002", "kc-0002")
        did = "did:web:dataspace.example:ex-1"
        r = await live_client.patch(
            f"/admin/communities/{c}/members/ex-00001", json={"did": did}
        )
        assert r.status_code == 200, r.text

        _refusal(
            await live_client.post(
                f"/admin/communities/{c}/members", json=_member("ex-00001", "kc-0003")
            ),
            409,
            "member_key_taken",
        )
        _refusal(
            await live_client.post(
                f"/admin/communities/{c}/members", json=_member("ex-00003", "kc-0001")
            ),
            409,
            "user_id_taken",
        )
        _refusal(
            await live_client.patch(
                f"/admin/communities/{c}/members/ex-00002", json={"user_id": "kc-0001"}
            ),
            409,
            "user_id_taken",
        )
        _refusal(
            await live_client.patch(
                f"/admin/communities/{c}/members/ex-00002", json={"did": did}
            ),
            409,
            "did_taken",
        )

    async def test_asset_and_area_refusals(self, live_client):
        """@verifies REQ-0073"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        await _add(live_client, c, "ex-00002", "kc-0002")
        await _attach(live_client, c, "ex-00001", "SEN-1", key="shared")

        _refusal(
            await _attach(live_client, c, "ex-00002", "SEN-2", key="shared"),
            409,
            "asset_key_taken",
        )
        _refusal(
            await live_client.delete(f"/admin/communities/{c}/areas/north"),
            409,
            "area_in_use",
        )

    async def test_an_invalid_status(self, live_client):
        """@verifies REQ-0073"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")

        for r in (
            await live_client.post(
                f"/admin/communities/{c}/members",
                json=_member("ex-00002", "kc-0002", status="retired"),
            ),
            await live_client.patch(
                f"/admin/communities/{c}/members/ex-00001", json={"status": "retired"}
            ),
            await live_client.post(
                f"/admin/communities/{c}/members/ex-00001/status",
                json={"status": "retired"},
            ),
        ):
            _refusal(r, 422, "invalid_status")

    async def test_a_refusal_without_a_code_keeps_the_plain_body(self, live_client):
        """A body key that does not match the path is nobody's to act on
        programmatically yet: `{"detail"}` as before.

        @verifies REQ-0073
        """
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")

        r = await live_client.put(
            f"/admin/communities/{c}/members/ex-00001/assets/meter-SEN-1",
            json=_meter("SEN-1", key="something-else"),
        )

        assert r.status_code == 422
        assert set(r.json()) == {"detail"}


class TestTheOpenApiDocument:
    def test_the_coded_body_is_documented(self):
        """The SDK is generated from this document; a code that exists only at
        runtime is one no generated client can read.

        @verifies REQ-0073
        """
        from celine.rec_registry.main import create_app

        doc = create_app().openapi()
        schema = doc["components"]["schemas"]["ErrorResponse"]
        assert set(schema["properties"]) == {"detail", "code"}
        assert schema["properties"]["detail"]["type"] == "string"
        codes = doc["components"]["schemas"]["ErrorCode"]["enum"]
        assert set(codes) == {c.value for c in ErrorCode}

        put = doc["paths"][
            "/admin/communities/{community_key}/members/{member_key}/assets/{asset_key}"
        ]["put"]
        assert put["responses"]["409"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }
        imp = doc["paths"]["/admin/import"]["post"]
        assert "422" in imp["responses"]
        report = doc["components"]["schemas"]["ImportReport"]
        assert "refusals" in report["properties"]

    def test_the_app_renders_the_coded_body(self):
        """`create_app` installs the handler; without it the code would be lost.

        @verifies REQ-0073
        """
        from fastapi.testclient import TestClient

        from celine.rec_registry.core.errors import RegistryError
        from celine.rec_registry.main import create_app

        app = create_app()

        @app.get("/probe-coded-refusal")
        async def probe():
            raise RegistryError(409, "a sentence", ErrorCode.SENSOR_HELD)

        r = TestClient(app).get("/probe-coded-refusal")
        assert r.status_code == 409
        assert r.json() == {"detail": "a sentence", "code": "sensor_held"}


@pytest.mark.integration
class TestTheDuplicatesReportAgainstAnExport:
    async def test_it_finds_holders_written_before_the_check(self, live_client, pg_engine):
        """The check refuses the next write, not the past ones: rows that already
        break the rule are what the report exists to find.

        @verifies REQ-0076
        """
        from celine.rec_registry.cli.main import find_duplicate_sensors

        a = await _community(live_client, "example-rec-a")
        b = await _community(live_client, "example-rec-b")
        await _add(live_client, a, "ex-00001", "kc-0001")
        await _add(live_client, b, "ex-00009", "kc-0009", status="pending")
        await _attach(live_client, a, "ex-00001", "SEN-1")
        await _attach(live_client, b, "ex-00009", " SEN-1", key="meter-SEN-1")
        # As if written before the rule existed.
        async with pg_engine.begin() as conn:
            await conn.execute(text("update member set status = 'active'"))

        exported = await live_client.get("/admin/export")
        docs = [d for d in yaml.safe_load_all(exported.text) if d]

        assert find_duplicate_sensors(docs) == [
            ("SEN-1", [("example-rec-a", "ex-00001"), ("example-rec-b", "ex-00009")])
        ]


# =============================================================================
# One definition of "trimmed", in Python and in SQL
# =============================================================================


LEGACY_UNTRIMMED = ["\tSEN-1\n", " SEN-1 "]


@pytest.mark.integration
class TestLegacyIdsTrimmedLikePython:
    """A row written before ids were trimmed may carry any whitespace Python
    strips; Postgres's one-argument `btrim` strips only the space, so the SQL
    side passes the same character set Python strips."""

    @pytest.mark.parametrize("stored", LEGACY_UNTRIMMED, ids=["tab-newline", "nbsp"])
    async def test_a_stored_id_with_other_whitespace_still_counts(
        self, live_client, pg_engine, stored
    ):
        """@verifies REQ-0069"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        await _add(live_client, c, "ex-00002", "kc-0002")
        await _attach(live_client, c, "ex-00001", "SEN-1")
        async with pg_engine.begin() as conn:
            await conn.execute(
                text("update asset set sensor_id = :stored"), {"stored": stored}
            )

        r = await _attach(live_client, c, "ex-00002", "SEN-1")

        _refusal(r, 409, "sensor_held")

    @pytest.mark.parametrize("stored", LEGACY_UNTRIMMED, ids=["tab-newline", "nbsp"])
    async def test_reactivation_sees_it_too(self, live_client, pg_engine, stored):
        """@verifies REQ-0069"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001", status="suspended")
        await _add(live_client, c, "ex-00002", "kc-0002")
        await _attach(live_client, c, "ex-00001", "SEN-1")
        await _attach(live_client, c, "ex-00002", "SEN-2", key="m-2")
        async with pg_engine.begin() as conn:
            await conn.execute(
                text("update asset set sensor_id = :stored where key = 'm-2'"),
                {"stored": stored},
            )

        r = await live_client.post(
            f"/admin/communities/{c}/members/ex-00001/status", json={"status": "active"}
        )

        _refusal(r, 409, "sensor_held")

    @pytest.mark.parametrize("stored", LEGACY_UNTRIMMED, ids=["tab-newline", "nbsp"])
    async def test_the_duplicates_report_trims_the_same_way(
        self, live_client, pg_engine, stored
    ):
        """@verifies REQ-0076"""
        from celine.rec_registry.cli.main import find_duplicate_sensors

        a = await _community(live_client, "example-rec-a")
        b = await _community(live_client, "example-rec-b")
        await _add(live_client, a, "ex-00001", "kc-0001")
        await _add(live_client, b, "ex-00009", "kc-0009", status="pending")
        await _attach(live_client, a, "ex-00001", "SEN-1")
        await _attach(live_client, b, "ex-00009", "SEN-1")
        async with pg_engine.begin() as conn:
            await conn.execute(text("update member set status = 'active'"))
            await conn.execute(
                text(
                    "update asset set sensor_id = :stored where owner_id = "
                    "(select id from member where key = 'ex-00009')"
                ),
                {"stored": stored},
            )

        exported = await live_client.get("/admin/export")
        docs = [d for d in yaml.safe_load_all(exported.text) if d]

        assert find_duplicate_sensors(docs) == [
            ("SEN-1", [("example-rec-a", "ex-00001"), ("example-rec-b", "ex-00009")])
        ]


class TestTheDuplicatesReportTrimsLikeTheRegistry:
    def test_ids_differing_only_in_unicode_whitespace_are_one(self):
        """@verifies REQ-0076"""
        from celine.rec_registry.cli.main import find_duplicate_sensors

        def bundle(key, member, sensor_id):
            return {
                "community": {"id": key},
                "members": {
                    member: {
                        "status": "active",
                        "assets": {"meter": {"m": {"sensor_id": sensor_id}}},
                    }
                },
            }

        docs = [
            bundle("example-rec-a", "ex-00001", "SEN-1"),
            bundle("example-rec-b", "ex-00002", "\tSEN-1\n"),
            bundle("example-rec-c", "ex-00003", " SEN-1 "),
        ]

        assert find_duplicate_sensors(docs) == [
            (
                "SEN-1",
                [
                    ("example-rec-a", "ex-00001"),
                    ("example-rec-b", "ex-00002"),
                    ("example-rec-c", "ex-00003"),
                ],
            )
        ]


# =============================================================================
# An attach and a reactivation of one member at once
# =============================================================================


@pytest.mark.integration
class TestAttachAndReactivationAtOnce:
    """An attach to a member who is not active is not checked, and a
    reactivation checks the sensors the member holds. Run at the same moment,
    each would miss the other's uncommitted half; the member's row lock makes
    the second see the first. Held open deliberately, as
    `TestTwoAttachesAtOnce` does."""

    async def _setup(self, live_client) -> str:
        """ex-00002 is active holding SEN-1; ex-00001 is suspended, holding nothing."""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001", status="suspended")
        await _add(live_client, c, "ex-00002", "kc-0002")
        r = await _attach(live_client, c, "ex-00002", "SEN-1", key="m-2")
        assert r.status_code == 200, r.text
        return c

    async def _active_holders_of_sen_1(self, pg_engine) -> int:
        async with pg_engine.connect() as conn:
            return await conn.scalar(
                text(
                    "select count(*) from asset a join member m on m.id = a.owner_id "
                    "where a.sensor_id = 'SEN-1' and m.status = 'active'"
                )
            )

    async def test_a_reactivation_waits_for_an_attach_and_then_refuses(
        self, live_client, pg_engine
    ):
        """@verifies REQ-0069"""
        c = await self._setup(live_client)

        maker = async_sessionmaker(pg_engine, expire_on_commit=False)
        async with maker() as holder:
            holder_pid = await holder.scalar(text("select pg_backend_pid()"))
            community = await member_service.resolve_community(holder, c)
            member = await member_service.resolve_member(holder, community, "ex-00001")
            # Suspended, so not checked: the attach is allowed, uncommitted.
            await member_service.upsert_asset(
                holder,
                community=community,
                member=member,
                asset_key="meter-SEN-1",
                asset_type="meter",
                payload=MeterAssetIn(
                    name="Meter", sensor_id="SEN-1", meter_type="consumption"
                ),
            )

            request = asyncio.create_task(
                live_client.post(
                    f"/admin/communities/{c}/members/ex-00001/status",
                    json={"status": "active"},
                )
            )
            await _wait_until_blocked(pg_engine, holder_pid)
            await holder.commit()
            r = await request

        _refusal(r, 409, "sensor_held")
        assert await self._active_holders_of_sen_1(pg_engine) == 1

    async def test_an_attach_waits_for_a_reactivation_and_then_refuses(
        self, live_client, pg_engine
    ):
        """@verifies REQ-0069"""
        c = await self._setup(live_client)

        maker = async_sessionmaker(pg_engine, expire_on_commit=False)
        async with maker() as holder:
            holder_pid = await holder.scalar(text("select pg_backend_pid()"))
            community = await member_service.resolve_community(holder, c)
            member = await member_service.resolve_member(holder, community, "ex-00001")
            # Holds nothing, so the reactivation is allowed, uncommitted.
            await member_service.ensure_reactivation_allowed(
                holder, community, member, "active"
            )
            member.status = "active"
            await holder.flush()

            request = asyncio.create_task(_attach(live_client, c, "ex-00001", "SEN-1"))
            await _wait_until_blocked(pg_engine, holder_pid)
            await holder.commit()
            r = await request

        _refusal(r, 409, "sensor_held")
        assert await self._active_holders_of_sen_1(pg_engine) == 1


# =============================================================================
# Asset keys longer than the column
# =============================================================================


LONG_KEY = "k" * 129
LONGEST_KEY = "k" * 128


@pytest.mark.integration
class TestAssetKeyTooLong:
    """`asset.key` holds 128 characters; a longer key used to fail the insert
    and answer `500`."""

    async def test_the_asset_put_refuses_it_coded(self, live_client):
        """A coded refusal, whose sentence gives the length and not the key.

        @verifies REQ-0028
        @verifies REQ-0073
        """
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")

        r = await _attach(live_client, c, "ex-00001", "SEN-1", key=LONG_KEY)

        detail = _refusal(r, 422, "asset_key_too_long")
        assert LONG_KEY not in detail
        assert await _assets(live_client, c) == []

    async def test_a_key_of_exactly_128_is_stored(self, live_client):
        """@verifies REQ-0028"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")

        r = await _attach(live_client, c, "ex-00001", "SEN-1", key=LONGEST_KEY)

        assert r.status_code == 200, r.text
        assert r.json()["key"] == LONGEST_KEY

    async def test_a_long_sensor_id_at_the_meter_convention_is_refused(
        self, live_client
    ):
        """`meter-` plus a 123-character id is 129: the sensor id is not echoed.

        @verifies REQ-0071
        """
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        sensor = "S" * 123

        r = await _attach(live_client, c, "ex-00001", sensor)

        detail = _refusal(r, 422, "asset_key_too_long")
        assert sensor not in detail

    async def test_creating_a_member_with_one_refuses_it_coded(self, live_client):
        """@verifies REQ-0028"""
        c = await _community(live_client)

        r = await live_client.post(
            f"/admin/communities/{c}/members",
            json=_member("ex-00001", "kc-0001", meters={LONG_KEY: "SEN-1"}),
        )

        _refusal(r, 422, "asset_key_too_long")
        members = await live_client.get(f"/admin/communities/{c}/members")
        assert members.json()["items"] == []

    async def test_the_import_refuses_it_whole_and_a_dry_run_lists_it(
        self, live_client
    ):
        """An import refusal like `sensor_held`: before anything is deleted.

        @verifies REQ-0028
        """
        holder = _holder("ex-00001", "kc-0001", "SEN-1")
        meter = holder["assets"]["meter"].pop(next(iter(holder["assets"]["meter"])))
        holder["assets"]["meter"][LONG_KEY] = meter
        bundle = _bundle("example-rec", {"ex-00001": holder})

        r = await live_client.post("/admin/import", json={"bundle": bundle})

        detail = _refusal(r, 422, "asset_key_too_long")
        assert "ex-00001" in detail and LONG_KEY not in detail
        assert (await live_client.get("/admin/communities/example-rec")).status_code == 404

        dry = await live_client.post(
            "/admin/import", json={"bundle": bundle, "dry_run": True}
        )
        assert dry.status_code == 200, dry.text
        assert [x["code"] for x in dry.json()["refusals"]] == ["asset_key_too_long"]


# =============================================================================
# The OpenAPI document: both 422 bodies, and the asset PUT's type
# =============================================================================


class TestTheOpenApiDocumentsBoth422Bodies:
    ONE_OF = {
        "oneOf": [
            {"$ref": "#/components/schemas/ErrorResponse"},
            {"$ref": "#/components/schemas/HTTPValidationError"},
        ]
    }

    def _doc(self):
        from celine.rec_registry.main import create_app

        return create_app().openapi()

    def test_routes_with_a_coded_422_declare_either_body(self):
        """FastAPI's validation 422 (a list `detail`) arrives on these routes
        beside the coded one; a generated client must be able to read both.

        @verifies REQ-0073
        """
        doc = self._doc()
        components = doc["components"]["schemas"]
        assert "ErrorResponse" in components and "HTTPValidationError" in components

        member = "/admin/communities/{community_key}/members/{member_key}"
        for path, method in [
            ("/admin/import", "post"),
            ("/admin/import/yaml", "post"),
            ("/admin/communities/{community_key}/members", "post"),
            (member, "patch"),
            (member + "/status", "post"),
            (member + "/assets/{asset_key}", "put"),
        ]:
            response = doc["paths"][path][method]["responses"]["422"]
            schema = response["content"]["application/json"]["schema"]
            assert schema == self.ONE_OF, (path, method, schema)

    def test_the_asset_put_declares_the_stored_asset(self):
        """@verifies REQ-0028"""
        doc = self._doc()
        put = doc["paths"][
            "/admin/communities/{community_key}/members/{member_key}/assets/{asset_key}"
        ]["put"]
        schema = put["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/AssetDetail"}


@pytest.mark.integration
class TestTheAssetPutAnswersTheStoredAsset:
    async def test_it_answers_an_asset_detail(self, live_client):
        """@verifies REQ-0028"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")

        r = await _attach(live_client, c, "ex-00001", " SEN-1 ")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["key"] == "meter-SEN-1"
        assert body["sensor_id"] == "SEN-1"
        assert body["owner_key"] == "ex-00001"
        assert body["owner_user_id"] == "kc-0001"
        stored = await live_client.get(
            f"/admin/communities/{c}/assets/meter-SEN-1"
        )
        assert stored.status_code == 200, stored.text
        assert body == stored.json()
