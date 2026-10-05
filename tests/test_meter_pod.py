"""A meter's ``pod`` is one of its owner's delivery points, or held by nobody else.

A meter names the supply it reads in ``properties.pod``. Without a rule, a
meter could name a POD another active member holds as a delivery point, and
every consumer joining supply to members would attribute one supply to two
people — the case REQ-0085 closed for delivery points, reopened through the
meter. So the POD a meter names is a holding (REQ-0093): it is one of its
owner's own delivery points, or no other active member holds it — as a
delivery point or through a meter of its own. A clash is
``409 delivery_point_held`` (``422`` on an import), as for a delivery point.

Integration tests against PostgreSQL; skipped when none is reachable.
"""

from __future__ import annotations

import pytest

from tests.substations import substation_graph

pytestmark = pytest.mark.asyncio

C = "example-rec"
POD = "IT001E00000001"
OTHER_POD = "IT001E00000002"


def _member(key: str, n: int, *, status: str = "active", pods=(), meters=None) -> dict:
    body = {
        "key": key,
        "user_id": f"kc-{n:04d}",
        "name": "Example Member",
        "role": "consumer",
        "area": "north",
        "status": status,
        "delivery_points": [{"id": p, "type": "pod"} for p in pods],
    }
    if meters:
        body["assets"] = {"meter": meters}
    return body


def _meter_in(sensor: str, pod: str | None) -> dict:
    meter = {"name": "Meter", "sensor_id": sensor, "meter_type": "consumption"}
    if pod is not None:
        meter["pod"] = pod
    return meter


def _bundle(key: str, members: dict | None = None) -> dict:
    return {
        "version": "1.0",
        "schema_version": "0.7",
        "community": {
            "id": key,
            "name": "Example Community",
            **substation_graph("north", "south"),
        },
        "members": members or {},
    }


def _bundle_member(n: int, *, pods=(), meters=None, status: str = "active") -> dict:
    body = _member("unused", n, status=status, pods=pods, meters=meters)
    body.pop("key")
    return body


async def _community(client, key: str = C) -> None:
    r = await client.post("/admin/import", json={"bundle": _bundle(key)})
    assert r.status_code == 200, r.text


async def _add(client, key: str, n: int, *, community: str = C, **kwargs) -> None:
    r = await client.post(
        f"/admin/communities/{community}/members", json=_member(key, n, **kwargs)
    )
    assert r.status_code == 201, r.text


async def _attach(client, member: str, sensor: str, pod: str | None, *, community: str = C):
    return await client.put(
        f"/admin/communities/{community}/members/{member}/assets/meter-{sensor}",
        json={
            "key": f"meter-{sensor}",
            "asset_type": "meter",
            "properties": _meter_in(sensor, pod),
        },
    )


async def _meters(client, member: str, community: str = C) -> dict[str, str | None]:
    r = await client.get(
        f"/admin/communities/{community}/meters", params={"owner": member}
    )
    assert r.status_code == 200, r.text
    return {a["key"]: a["pod"] for a in r.json()["items"]}


async def _set_status(client, member: str, status: str, *, community: str = C):
    return await client.post(
        f"/admin/communities/{community}/members/{member}/status",
        json={"status": status},
    )


def _refusal(r, status: int, code: str) -> str:
    assert r.status_code == status, r.text
    body = r.json()
    assert set(body) == {"detail", "code"}, body
    assert body["code"] == code, body
    return body["detail"]


@pytest.mark.integration
class TestTheAttach:
    async def test_a_meter_may_name_its_owners_own_point_in_any_spelling(
        self, live_client
    ):
        """@verifies REQ-0093"""
        await _community(live_client)
        await _add(live_client, "ex-00001", 1, pods=[POD])

        r = await _attach(live_client, "ex-00001", "SEN-1", f" {POD.lower()} ")

        assert r.status_code == 200, r.text

    async def test_a_point_another_active_member_holds_is_refused(self, live_client):
        """Named inside the community, as REQ-0085 names a holder; nothing stored.

        @verifies REQ-0093
        """
        await _community(live_client)
        await _add(live_client, "ex-00001", 1, pods=[POD])
        await _add(live_client, "ex-00002", 2, pods=[OTHER_POD])

        r = await _attach(live_client, "ex-00002", "SEN-2", POD.lower())

        detail = _refusal(r, 409, "delivery_point_held")
        assert "ex-00001" in detail
        assert POD not in detail and POD.lower() not in detail
        assert await _meters(live_client, "ex-00002") == {}

    async def test_a_point_held_in_another_community_is_refused_unnamed(
        self, live_client
    ):
        """@verifies REQ-0093"""
        await _community(live_client, "example-rec-a")
        await _community(live_client, "example-rec-b")
        await _add(live_client, "ex-00001", 1, community="example-rec-a", pods=[POD])
        await _add(live_client, "ex-00009", 9, community="example-rec-b")

        r = await _attach(
            live_client, "ex-00009", "SEN-9", POD, community="example-rec-b"
        )

        detail = _refusal(r, 409, "delivery_point_held")
        assert "ex-00001" not in detail and "example-rec-a" not in detail

    async def test_a_pod_nobody_holds_may_be_named_and_is_then_held(self, live_client):
        """A meter naming a POD outside its owner's points makes its owner the
        holder: a second meter elsewhere, or a delivery point elsewhere, is refused.

        @verifies REQ-0093
        """
        await _community(live_client)
        await _add(live_client, "ex-00001", 1)
        await _add(live_client, "ex-00002", 2)

        assert (await _attach(live_client, "ex-00001", "SEN-1", POD)).status_code == 200
        # The same member's second meter on it is no clash.
        assert (await _attach(live_client, "ex-00001", "SEN-3", POD)).status_code == 200

        _refusal(
            await _attach(live_client, "ex-00002", "SEN-2", POD),
            409,
            "delivery_point_held",
        )
        r = await live_client.put(
            f"/admin/communities/{C}/members/ex-00002/delivery-points/{POD}",
            json={"id": POD, "type": "pod"},
        )
        _refusal(r, 409, "delivery_point_held")
        # The holder itself may still declare it.
        r = await live_client.put(
            f"/admin/communities/{C}/members/ex-00001/delivery-points/{POD}",
            json={"id": POD, "type": "pod"},
        )
        assert r.status_code == 200, r.text

    async def test_a_meter_without_a_pod_is_not_checked(self, live_client):
        """@verifies REQ-0093"""
        await _community(live_client)
        await _add(live_client, "ex-00001", 1, pods=[POD])
        await _add(live_client, "ex-00002", 2)

        assert (await _attach(live_client, "ex-00002", "SEN-2", None)).status_code == 200

    async def test_deactivating_the_holder_releases_the_pod(self, live_client):
        """@verifies REQ-0093"""
        await _community(live_client)
        await _add(live_client, "ex-00001", 1, pods=[POD])
        await _add(live_client, "ex-00002", 2)
        r = await _set_status(live_client, "ex-00001", "inactive")
        assert r.status_code == 200, r.text

        assert (await _attach(live_client, "ex-00002", "SEN-2", POD)).status_code == 200


@pytest.mark.integration
class TestTheOtherPaths:
    async def test_an_inactive_member_may_name_it_and_its_reactivation_is_refused(
        self, live_client
    ):
        """@verifies REQ-0093"""
        await _community(live_client)
        await _add(live_client, "ex-00001", 1, pods=[POD])
        await _add(live_client, "ex-00002", 2, status="suspended")

        assert (await _attach(live_client, "ex-00002", "SEN-2", POD)).status_code == 200

        r = await _set_status(live_client, "ex-00002", "active")
        _refusal(r, 409, "delivery_point_held")
        r = await live_client.get(f"/admin/communities/{C}/members/ex-00002")
        assert r.json()["status"] == "suspended"

    async def test_creating_a_member_with_a_meter_on_a_held_pod_is_refused(
        self, live_client
    ):
        """@verifies REQ-0093"""
        await _community(live_client)
        await _add(live_client, "ex-00001", 1, pods=[POD])

        r = await live_client.post(
            f"/admin/communities/{C}/members",
            json=_member("ex-00002", 2, meters={"meter-SEN-2": _meter_in("SEN-2", POD)}),
        )

        _refusal(r, 409, "delivery_point_held")
        assert (
            await live_client.get(f"/admin/communities/{C}/members/ex-00002")
        ).status_code == 404

    async def test_creating_a_member_whose_meter_names_its_own_point_succeeds(
        self, live_client
    ):
        """@verifies REQ-0093"""
        await _community(live_client)

        r = await live_client.post(
            f"/admin/communities/{C}/members",
            json=_member(
                "ex-00001",
                1,
                pods=[POD],
                meters={"meter-SEN-1": _meter_in("SEN-1", POD.lower())},
            ),
        )

        assert r.status_code == 201, r.text


@pytest.mark.integration
class TestTheImport:
    async def test_a_meter_on_another_members_point_in_the_bundle_is_refused(
        self, live_client
    ):
        """@verifies REQ-0093"""
        bundle = _bundle(
            C,
            {
                "ex-00001": _bundle_member(1, pods=[POD]),
                "ex-00002": _bundle_member(
                    2, meters={"meter-SEN-2": _meter_in("SEN-2", POD)}
                ),
            },
        )

        r = await live_client.post("/admin/import", json={"bundle": bundle})

        detail = _refusal(r, 422, "delivery_point_held")
        assert "ex-00001" in detail and "ex-00002" in detail
        assert POD not in detail

    async def test_a_meter_on_a_point_held_in_another_community_is_refused(
        self, live_client
    ):
        """@verifies REQ-0093"""
        await _community(live_client, "example-rec-a")
        await _add(live_client, "ex-00001", 1, community="example-rec-a", pods=[POD])
        bundle = _bundle(
            "example-rec-b",
            {"ex-00009": _bundle_member(9, meters={"meter-SEN-9": _meter_in("SEN-9", POD)})},
        )

        r = await live_client.post("/admin/import", json={"bundle": bundle})

        detail = _refusal(r, 422, "delivery_point_held")
        assert "ex-00009" in detail and "example-rec-a" not in detail

    async def test_meters_on_their_owners_points_import(self, live_client):
        """@verifies REQ-0093"""
        bundle = _bundle(
            C,
            {
                "ex-00001": _bundle_member(
                    1,
                    pods=[POD],
                    meters={
                        "meter-SEN-1": _meter_in("SEN-1", POD),
                        "meter-SEN-3": _meter_in("SEN-3", f" {POD.lower()}"),
                    },
                ),
                "ex-00002": _bundle_member(
                    2,
                    pods=[OTHER_POD],
                    meters={"meter-SEN-2": _meter_in("SEN-2", OTHER_POD)},
                ),
            },
        )

        r = await live_client.post("/admin/import", json={"bundle": bundle})

        assert r.status_code == 200, r.text
