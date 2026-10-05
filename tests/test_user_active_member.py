"""Self-service answers from an active member only, and never picks between two.

The `/user` routes used to resolve the caller's member on `user_id` alone and take
the first row. Two consequences, both live:

* **A released member kept their meters.** Release leaves the row `inactive`, so
  `GET /user/assets` still answered from it — and dataset-api builds its live
  `sensor_id IN (…)` row filter from that answer. Once the POD was given to a new
  occupant, the released member read the new occupant's readings.
* **Two rows, one username, an arbitrary answer.** `user_id` is unique per
  community only; with a row in each of two communities the answer was whichever
  the planner returned.

The DID half: `ix_member_did` was global, so a released row's DID blocked the
same DID from being held by an active member anywhere again.
"""

from __future__ import annotations

import pytest

from celine.sdk.auth import JwtUser
from celine.sdk.auth.jwt import Organization

from tests.conftest import identifies_as
from tests.substations import substation_graph

pytestmark = pytest.mark.asyncio

USER = "kc-mover"
OCCUPANT = "kc-occupant"
SENSOR = "sen-shared-01"
POD = "IT001E00000099"
DID = "did:web:dataspace.example:users:mover"

SELF_SERVICE_403 = [
    "/user/member",
    "/user/community",
    "/user/assets",
    "/user/assets/meter-mover",
    "/user/delivery-points",
]


def _member(user_id: str, *, status: str = "active", did: str | None = None) -> dict:
    member = {
        "user_id": user_id,
        "name": user_id,
        "role": "consumer",
        "area": "north",
        "status": status,
        "delivery_points": [{"id": POD, "type": "pod"}],
        "assets": {
            "meter": {
                "meter-mover": {
                    "name": "Meter",
                    "sensor_id": SENSOR,
                    "meter_type": "consumption",
                    "pod": POD,
                }
            }
        },
    }
    if did:
        member["did"] = did
    return member


async def _import(client, key: str, members: dict) -> None:
    bundle = {
        "version": "1.0",
        "schema_version": "0.5",
        "community": {
            "id": key,
            "name": key,
            "description": "A community",
            **substation_graph("north"),
            "settings": {"timezone": "Europe/Rome", "currency": "EUR"},
        },
        "members": members,
    }
    r = await client.post(
        "/admin/import", json={"bundle": bundle, "dry_run": False, "force": True}
    )
    assert r.status_code == 200, r.text


def _in_orgs(username: str, *aliases: str) -> JwtUser:
    """A token for `username` whose `organization` claim names these aliases."""
    user = identifies_as(username)
    user.organizations = [Organization(alias=a) for a in aliases]
    return user


async def _status(client, community: str, member: str, status: str):
    return await client.post(
        f"/admin/communities/{community}/members/{member}/status",
        json={"status": status},
    )


@pytest.mark.integration
class TestOnlyAnActiveMemberAnswers:
    @pytest.mark.parametrize("status", ["pending", "suspended", "inactive"])
    async def test_a_member_who_is_not_active_is_no_member(
        self, live_client, as_user, status
    ):
        """Every self-service route answers a non-active row as it answers a
        stranger: `GET /user` with no membership, the rest `403 not_a_member`.

        @verifies REQ-0094
        """
        await _import(live_client, "example-rec", {"ex-00001": _member(USER, status=status)})
        client = as_user(identifies_as(USER))

        me = await client.get("/user")
        assert me.status_code == 200, me.text
        assert me.json()["membership"] is None

        for path in SELF_SERVICE_403:
            r = await client.get(path)
            assert r.status_code == 403, (path, r.text)
            assert r.json()["code"] == "not_a_member", path

    async def test_a_released_member_stops_reading_the_meter_its_pod_now_feeds(
        self, live_client, as_user
    ):
        """The leak itself: released, then the POD and sensor given to a new
        occupant. The released member's `/user/assets` — dataset-api's row
        filter — no longer names the sensor; the occupant's does.

        @verifies REQ-0094
        """
        await _import(live_client, "example-rec", {"ex-00001": _member(USER)})
        mover = as_user(identifies_as(USER))
        before = await mover.get("/user/assets")
        assert [a["sensor_id"] for a in before.json()["items"]] == [SENSOR]

        r = await _status(live_client, "example-rec", "ex-00001", "inactive")
        assert r.status_code == 200, r.text
        occupant_in = _member(OCCUPANT)
        occupant_in["assets"]["meter"] = {
            "meter-occupant": occupant_in["assets"]["meter"]["meter-mover"]
        }
        r = await live_client.post(
            "/admin/communities/example-rec/members",
            json={**occupant_in, "key": "ex-00002", "type": "schema:Person"},
        )
        assert r.status_code == 201, r.text

        after = await mover.get("/user/assets")
        assert after.status_code == 403, after.text
        assert after.json()["code"] == "not_a_member"
        dps = await mover.get("/user/delivery-points")
        assert dps.status_code == 403, dps.text

        occupant = await as_user(identifies_as(OCCUPANT)).get("/user/assets")
        assert [a["sensor_id"] for a in occupant.json()["items"]] == [SENSOR]

    async def test_an_inactive_row_beside_an_active_one_does_not_count(
        self, live_client, as_user
    ):
        """Released at one community, active at another: the active row answers,
        with no organization in the token needed to choose.

        @verifies REQ-0094
        """
        await _import(live_client, "example-rec-a", {"ex-00001": _member(USER)})
        r = await _status(live_client, "example-rec-a", "ex-00001", "inactive")
        assert r.status_code == 200, r.text
        await _import(live_client, "example-rec-b", {"ex-00007": _member(USER)})

        client = as_user(identifies_as(USER))
        me = await client.get("/user")
        assert me.json()["membership"]["community"]["key"] == "example-rec-b"
        member = await client.get("/user/member")
        assert member.json()["key"] == "ex-00007"


@pytest.mark.integration
class TestTwoActiveRowsAreNeverPicked:
    async def _two_active(self, live_client):
        # Two communities, both holding the username active. The POD and sensor
        # differ, or the second would be refused as held (REQ-0069, REQ-0085).
        await _import(live_client, "example-rec-a", {"ex-00001": _member(USER)})
        other = _member(USER)
        other["delivery_points"] = [{"id": "IT001E00000098", "type": "pod"}]
        other["assets"]["meter"]["meter-mover"].update(
            sensor_id="sen-shared-02", pod="IT001E00000098"
        )
        await _import(live_client, "example-rec-b", {"ex-00001": other})

    async def test_with_no_organization_to_narrow_by_every_route_refuses(
        self, live_client, as_user, monkeypatch
    ):
        """Every route, `GET /user` included, and each refusal recorded.

        `audit_denied` is captured where the routes call it rather than read off
        the `celine.audit` logger, whose propagation other tests in the suite
        change.

        @verifies REQ-0095
        """
        import celine.rec_registry.api.user as user_api

        recorded: list[str] = []
        monkeypatch.setattr(
            user_api,
            "audit_denied",
            lambda action, *, reason, **_: recorded.append(f"{action}:{reason}"),
        )
        await self._two_active(live_client)
        client = as_user(identifies_as(USER))

        for path in ["/user", *SELF_SERVICE_403]:
            r = await client.get(path)
            assert r.status_code == 409, (path, r.text)
            assert r.json()["code"] == "ambiguous_member", path

        assert recorded == ["rec-registry.user.read:ambiguous_member"] * 6

    async def test_the_tokens_organization_names_which(self, live_client, as_user):
        """@verifies REQ-0095"""
        await self._two_active(live_client)

        a = await as_user(_in_orgs(USER, "example-rec-a")).get("/user/assets")
        b = await as_user(_in_orgs(USER, "example-rec-b")).get("/user/assets")

        assert [x["sensor_id"] for x in a.json()["items"]] == [SENSOR]
        assert [x["sensor_id"] for x in b.json()["items"]] == ["sen-shared-02"]

    async def test_a_token_naming_both_is_still_ambiguous(self, live_client, as_user):
        """@verifies REQ-0095"""
        await self._two_active(live_client)

        r = await as_user(
            _in_orgs(USER, "example-rec-a", "example-rec-b")
        ).get("/user/community")

        assert r.status_code == 409, r.text
        assert r.json()["code"] == "ambiguous_member"


@pytest.mark.integration
class TestADidIsUniqueAmongActiveMembersOnly:
    async def _released_at_a(self, live_client):
        await _import(live_client, "example-rec-a", {"ex-00001": _member(USER, did=DID)})
        r = await _status(live_client, "example-rec-a", "ex-00001", "inactive")
        assert r.status_code == 200, r.text

    async def test_a_released_rows_did_can_be_held_by_an_active_member_elsewhere(
        self, live_client
    ):
        """Created holding it, and patched onto an existing member: both succeed,
        and the released row keeps its DID.

        @verifies REQ-0096
        """
        await self._released_at_a(live_client)
        await _import(live_client, "example-rec-b", {})

        created = await live_client.post(
            "/admin/communities/example-rec-b/members",
            json={**_member(USER, did=DID), "key": "ex-00007", "type": "schema:Person"},
        )
        assert created.status_code == 201, created.text

        old = await live_client.get("/admin/communities/example-rec-a/members/ex-00001")
        assert old.json()["did"] == DID
        assert old.json()["status"] == "inactive"

    async def test_patch_writes_a_released_rows_did_onto_an_active_member(
        self, live_client
    ):
        """@verifies REQ-0096"""
        await self._released_at_a(live_client)
        other = _member("kc-other")
        other["delivery_points"] = [{"id": "IT001E00000097", "type": "pod"}]
        other["assets"] = {}
        await _import(live_client, "example-rec-b", {"ex-00007": other})

        r = await live_client.patch(
            "/admin/communities/example-rec-b/members/ex-00007", json={"did": DID}
        )
        assert r.status_code == 200, r.text
        assert r.json()["did"] == DID

    async def test_a_second_active_holder_is_still_refused(self, live_client):
        """@verifies REQ-0096"""
        await _import(live_client, "example-rec-a", {"ex-00001": _member(USER, did=DID)})
        other = _member("kc-other")
        other["delivery_points"] = [{"id": "IT001E00000097", "type": "pod"}]
        other["assets"] = {}
        await _import(live_client, "example-rec-b", {"ex-00007": other})

        r = await live_client.patch(
            "/admin/communities/example-rec-b/members/ex-00007", json={"did": DID}
        )
        assert r.status_code == 409, r.text
        assert r.json()["code"] == "did_taken"

    @pytest.mark.parametrize("route", ["status", "patch"])
    async def test_reactivating_a_row_whose_did_is_now_held_is_refused(
        self, live_client, route
    ):
        """The released row comes back while another active member holds its
        DID: `409 did_taken`, naming nobody, and the status stays `inactive`.

        @verifies REQ-0096
        """
        await self._released_at_a(live_client)
        other = _member("kc-other", did=DID)
        other["delivery_points"] = [{"id": "IT001E00000097", "type": "pod"}]
        other["assets"] = {}
        await _import(live_client, "example-rec-b", {"ex-00007": other})

        if route == "status":
            r = await _status(live_client, "example-rec-a", "ex-00001", "active")
        else:
            r = await live_client.patch(
                "/admin/communities/example-rec-a/members/ex-00001",
                json={"status": "active"},
            )
        assert r.status_code == 409, r.text
        assert r.json()["code"] == "did_taken"
        assert "ex-00007" not in r.json()["detail"]

        row = await live_client.get("/admin/communities/example-rec-a/members/ex-00001")
        assert row.json()["status"] == "inactive"
