"""The admin lookups answer from the active member, and never pick between two.

The same leak as the `/user` routes (`test_user_active_member.py`), on the
service side. Every lookup that starts from a person or a device took the
first matching row whatever its status, so after a release and a reassignment:

* `assets-by-user-ids` — dataset-api's consent-gated row filter — still handed
  the released member's old meter, now the new occupant's;
* `member-by-user-id` / `community-by-user-id` answered the released row, or an
  arbitrary one of two;
* the sensor and delivery-point lookups attributed the new occupant's meter to
  whoever left, and `assets-by-sensor-ids` named both (the digital twin nudges
  every owner it returns).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.test_user_active_member import (
    OCCUPANT,
    POD,
    SENSOR,
    USER,
    _import,
    _member,
    _status,
)

pytestmark = pytest.mark.asyncio


async def _released_and_reassigned(client) -> None:
    """`USER` released at example-rec; `OCCUPANT` now holds the sensor and POD."""
    await _import(client, "example-rec", {"ex-00001": _member(USER)})
    r = await _status(client, "example-rec", "ex-00001", "inactive")
    assert r.status_code == 200, r.text
    occupant = _member(OCCUPANT)
    occupant["assets"]["meter"] = {
        "meter-occupant": occupant["assets"]["meter"]["meter-mover"]
    }
    r = await client.post(
        "/admin/communities/example-rec/members",
        json={**occupant, "key": "ex-00002", "type": "schema:Person"},
    )
    assert r.status_code == 201, r.text


async def _moved(client) -> None:
    """`USER` released at example-rec-a, then active at example-rec-b."""
    await _import(client, "example-rec-a", {"ex-00001": _member(USER)})
    r = await _status(client, "example-rec-a", "ex-00001", "inactive")
    assert r.status_code == 200, r.text
    other = _member(USER)
    other["delivery_points"] = [{"id": "IT001E00000098", "type": "pod"}]
    other["assets"]["meter"]["meter-mover"].update(
        sensor_id="sen-shared-02", pod="IT001E00000098"
    )
    await _import(client, "example-rec-b", {"ex-00007": other})


async def _two_active(client, pg_engine) -> None:
    """`USER` active at example-rec-a and example-rec-b at once.

    Reached by flipping the status in the database: every write path refuses a
    second active holder of the same sensor and POD, and the point here is what
    a lookup does when a registry holds two anyway (legacy rows, REQ-0069's
    "existing clashes are not repaired").
    """
    await _import(client, "example-rec-a", {"ex-00001": _member(USER)})
    await _import(client, "example-rec-b", {"ex-00007": _member(USER, status="inactive")})
    async with pg_engine.begin() as conn:
        await conn.execute(text("update member set status = 'active'"))


async def _assets_by_user_ids(client, *user_ids):
    return await client.post(
        "/admin/lookup/assets-by-user-ids", json={"user_ids": list(user_ids)}
    )


@pytest.mark.integration
class TestAssetsByUserIdsAnswersActiveOwnersOnly:
    async def test_a_released_member_contributes_no_rows(self, live_client):
        """Released, and the meter given on: the released id yields nothing,
        the same as an unknown id; the occupant's yields the sensor.

        @verifies REQ-0097
        """
        await _released_and_reassigned(live_client)

        released = await _assets_by_user_ids(live_client, USER)
        unknown = await _assets_by_user_ids(live_client, "kc-nobody")
        occupant = await _assets_by_user_ids(live_client, OCCUPANT)

        assert released.status_code == 200, released.text
        assert released.json() == [] == unknown.json()
        assert [a["sensor_id"] for a in occupant.json()] == [SENSOR]
        assert occupant.json()[0]["owner_user_id"] == OCCUPANT

    async def test_after_a_move_only_the_new_communitys_assets_answer(self, live_client):
        """@verifies REQ-0097"""
        await _moved(live_client)

        r = await _assets_by_user_ids(live_client, USER)

        assert r.status_code == 200, r.text
        assert [(a["community_key"], a["sensor_id"]) for a in r.json()] == [
            ("example-rec-b", "sen-shared-02")
        ]

    async def test_an_id_active_in_two_communities_is_refused(
        self, live_client, pg_engine
    ):
        """@verifies REQ-0097"""
        await _two_active(live_client, pg_engine)

        r = await _assets_by_user_ids(live_client, USER, "kc-nobody")

        assert r.status_code == 409, r.text
        assert r.json()["code"] == "ambiguous_member"
        assert USER not in r.json()["detail"]


@pytest.mark.integration
class TestTheUserIdLookupsAnswerTheActiveRow:
    @pytest.mark.parametrize(
        "route", ["member-by-user-id", "community-by-user-id"]
    )
    async def test_a_released_only_user_is_not_found(self, live_client, route):
        """@verifies REQ-0098"""
        await _released_and_reassigned(live_client)

        r = await live_client.get(f"/admin/lookup/{route}/{USER}")

        assert r.status_code == 404, r.text

    async def test_after_a_move_the_active_row_answers(self, live_client):
        """@verifies REQ-0098"""
        await _moved(live_client)

        member = await live_client.get(f"/admin/lookup/member-by-user-id/{USER}")
        community = await live_client.get(f"/admin/lookup/community-by-user-id/{USER}")

        assert member.status_code == 200, member.text
        assert (member.json()["community_key"], member.json()["key"]) == (
            "example-rec-b",
            "ex-00007",
        )
        assert member.json()["status"] == "active"
        assert community.json()["community"]["key"] == "example-rec-b"
        assert community.json()["member"]["key"] == "ex-00007"

    @pytest.mark.parametrize(
        "route", ["member-by-user-id", "community-by-user-id"]
    )
    async def test_two_active_rows_are_refused(self, live_client, pg_engine, route):
        """@verifies REQ-0098"""
        await _two_active(live_client, pg_engine)

        r = await live_client.get(f"/admin/lookup/{route}/{USER}")

        assert r.status_code == 409, r.text
        assert r.json()["code"] == "ambiguous_member"


@pytest.mark.integration
class TestTheDeviceLookupsAnswerTheActiveHolder:
    async def test_a_reassigned_sensor_resolves_to_its_occupant(self, live_client):
        """Single and batch sensor lookups, after the meter changed hands.

        @verifies REQ-0099
        """
        await _released_and_reassigned(live_client)

        community = await live_client.get(
            f"/admin/lookup/community-by-sensor-id/{SENSOR}"
        )
        asset = await live_client.get(f"/admin/lookup/asset-by-sensor-id/{SENSOR}")
        batch = await live_client.post(
            "/admin/lookup/assets-by-sensor-ids", json={"sensor_ids": [SENSOR]}
        )

        assert community.json()["member"]["user_id"] == OCCUPANT
        assert asset.json()["owner_user_id"] == OCCUPANT
        assert [a["owner_user_id"] for a in batch.json()] == [OCCUPANT]

    async def test_a_reassigned_pod_resolves_to_its_occupant(self, live_client):
        """The route scans members, so an unfiltered scan answers whichever row
        the scan meets first. Rewriting the released row moves it in the heap,
        which is the order that exposed the old scan.

        @verifies REQ-0099
        """
        await _released_and_reassigned(live_client)
        r = await live_client.patch(
            "/admin/communities/example-rec/members/ex-00001", json={"name": "Released"}
        )
        assert r.status_code == 200, r.text

        r = await live_client.get(f"/admin/lookup/community-by-delivery-point/{POD}")

        assert r.status_code == 200, r.text
        assert r.json()["member"]["user_id"] == OCCUPANT

    async def test_a_device_only_a_released_member_holds_is_not_found(
        self, live_client
    ):
        """@verifies REQ-0099"""
        await _import(live_client, "example-rec", {"ex-00001": _member(USER)})
        r = await _status(live_client, "example-rec", "ex-00001", "inactive")
        assert r.status_code == 200, r.text

        for path in (
            f"/admin/lookup/community-by-sensor-id/{SENSOR}",
            f"/admin/lookup/asset-by-sensor-id/{SENSOR}",
            f"/admin/lookup/community-by-delivery-point/{POD}",
        ):
            r = await live_client.get(path)
            assert r.status_code == 404, (path, r.text)
        batch = await live_client.post(
            "/admin/lookup/assets-by-sensor-ids", json={"sensor_ids": [SENSOR]}
        )
        assert batch.json() == []

    async def test_two_active_holders_are_refused(self, live_client, pg_engine):
        """@verifies REQ-0099"""
        await _two_active(live_client, pg_engine)

        for path in (
            f"/admin/lookup/community-by-sensor-id/{SENSOR}",
            f"/admin/lookup/asset-by-sensor-id/{SENSOR}",
            f"/admin/lookup/community-by-delivery-point/{POD}",
        ):
            r = await live_client.get(path)
            assert r.status_code == 409, (path, r.text)
            assert r.json()["code"] == "ambiguous_member", path
