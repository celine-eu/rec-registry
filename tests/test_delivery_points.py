"""A POD correction is one write, and a POD has one active holder (REQ-0084, REQ-0085).

`PUT …/delivery-points/{new}?replaces={old}` adds the new point, removes the old
and relinks the member's meters whose `pod` named it, in one transaction; a
point a meter still names cannot be deleted (`409 delivery_point_linked`). And
no two active members, in one community or two, hold the same delivery point:
`409 delivery_point_held` on every path that can make an active member hold
one — the delivery-point `PUT`, creating a member, a move to `active`, and the
import (`422` there, as `sensor_held`). The comparison is trimmed and
case-insensitive throughout.

Fixtures are generic: `example-rec`, `ex-0000n`, `IT001E…`, `SEN-…`.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from celine.rec_registry.schemas.bundle import DeliveryPointIn
from celine.rec_registry.services import delivery_points as dp_service
from celine.rec_registry.services import members as member_service
from tests.substations import substation_graph

pytestmark = pytest.mark.asyncio

C = "example-rec"
OLD = "IT001E00000001"
NEW = "IT001E00000002"


# =============================================================================
# Helpers
# =============================================================================


def _member(key: str, n: int, *, status: str = "active", pods=None) -> dict:
    return {
        "key": key,
        "user_id": f"kc-{n:04d}",
        "name": "Example Member",
        "role": "consumer",
        "area": "north",
        "status": status,
        "delivery_points": [
            {"id": p, "type": "pod"} for p in (pods if pods is not None else [])
        ],
    }


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


def _bundle_member(n: int, pods, *, status: str = "active") -> dict:
    m = _member("unused", n, status=status, pods=pods)
    m.pop("key")
    return m


async def _community(client, key: str = C) -> str:
    r = await client.post("/admin/import", json={"bundle": _bundle(key)})
    assert r.status_code == 200, r.text
    return key


async def _add(client, key: str, n: int, *, community: str = C, **kwargs):
    r = await client.post(
        f"/admin/communities/{community}/members", json=_member(key, n, **kwargs)
    )
    assert r.status_code == 201, r.text
    return key


def _path(member: str, point: str, community: str = C) -> str:
    return f"/admin/communities/{community}/members/{member}/delivery-points/{point}"


async def _put(client, member: str, point: str, *, community: str = C, replaces=None):
    params = {"replaces": replaces} if replaces is not None else None
    return await client.put(
        _path(member, point, community),
        json={"id": point, "type": "pod"},
        params=params,
    )


async def _meter(
    client, member: str, sensor: str, pod: str | None, *, community: str = C
):
    props = {"name": "Meter", "sensor_id": sensor, "meter_type": "consumption"}
    if pod is not None:
        props["pod"] = pod
    r = await client.put(
        f"/admin/communities/{community}/members/{member}/assets/meter-{sensor}",
        json={"key": f"meter-{sensor}", "asset_type": "meter", "properties": props},
    )
    assert r.status_code == 200, r.text


async def _points(client, member: str, community: str = C) -> list[str]:
    r = await client.get(f"/admin/communities/{community}/members/{member}")
    assert r.status_code == 200, r.text
    return [dp["id"] for dp in r.json()["delivery_points"]]


async def _pods(client, member: str, community: str = C) -> dict[str, str | None]:
    r = await client.get(
        f"/admin/communities/{community}/meters", params={"owner": member}
    )
    assert r.status_code == 200, r.text
    return {a["key"]: a["pod"] for a in r.json()["items"]}


async def _status(client, member: str, community: str = C) -> str:
    r = await client.get(f"/admin/communities/{community}/members/{member}")
    return r.json()["status"]


def _refusal(r, status: int, code: str) -> str:
    """The coded body `sensor_held` uses (REQ-0073)."""
    assert r.status_code == status, r.text
    body = r.json()
    assert set(body) == {"detail", "code"}, body
    assert body["code"] == code, body
    assert isinstance(body["detail"], str)
    return body["detail"]


# =============================================================================
# The compared form — pure
# =============================================================================


class TestTheComparedForm:
    @pytest.mark.parametrize(
        "raw,compared",
        [
            (OLD, OLD.lower()),
            (f"  {OLD} ", OLD.lower()),
            (f"\t{OLD.lower()}\n", OLD.lower()),
            (f" {OLD} ", OLD.lower()),
            ("", None),
            ("  \t", None),
            (None, None),
            (42, None),
        ],
    )
    def test_trimmed_as_a_sensor_id_and_case_folded(self, raw, compared):
        """@verifies REQ-0085"""
        assert dp_service.normalise_delivery_point_id(raw) == compared


# =============================================================================
# F5: a POD correction is one write (REQ-0084)
# =============================================================================


@pytest.mark.integration
class TestAPodCorrection:
    async def _setup(self, client) -> None:
        """ex-00001 holds OLD and a second POD; two meters name OLD (one with
        another spelling), one names the second; ex-00002 has a meter naming
        OLD too, which is not ex-00001's to relink."""
        await _community(client)
        await _add(client, "ex-00001", 1, pods=[OLD, "IT001E00000003"])
        await _add(client, "ex-00002", 2, pods=["IT001E00000004"])
        await _meter(client, "ex-00001", "SEN-1", OLD)
        await _meter(client, "ex-00001", "SEN-2", f" {OLD.lower()} ")
        await _meter(client, "ex-00001", "SEN-3", "IT001E00000003")
        await _meter(client, "ex-00001", "SEN-4", None)
        await _meter(client, "ex-00002", "SEN-5", OLD)

    async def test_adds_removes_and_relinks_in_one_write(self, live_client):
        """@verifies REQ-0084"""
        await self._setup(live_client)

        r = await _put(live_client, "ex-00001", NEW, replaces=OLD)

        assert r.status_code == 200, r.text
        assert [dp["id"] for dp in r.json()["delivery_points"]] == [
            "IT001E00000003",
            NEW,
        ]
        assert await _points(live_client, "ex-00001") == ["IT001E00000003", NEW]
        assert await _pods(live_client, "ex-00001") == {
            "meter-SEN-1": NEW,
            "meter-SEN-2": NEW,
            "meter-SEN-3": "IT001E00000003",
            "meter-SEN-4": None,
        }
        # Another member's meter is not this member's to relink.
        assert await _pods(live_client, "ex-00002") == {"meter-SEN-5": OLD}

    async def test_the_old_id_is_matched_trimmed_and_case_insensitively(
        self, live_client
    ):
        """@verifies REQ-0084"""
        await self._setup(live_client)

        r = await _put(live_client, "ex-00001", NEW, replaces=f" {OLD.lower()}")

        assert r.status_code == 200, r.text
        assert OLD not in await _points(live_client, "ex-00001")
        assert (await _pods(live_client, "ex-00001"))["meter-SEN-1"] == NEW

    async def test_the_new_id_is_stored_as_the_path_spells_it(self, live_client):
        """A case correction of the same POD is a correction too.

        @verifies REQ-0084
        """
        await self._setup(live_client)
        spelled = OLD.lower()

        r = await _put(live_client, "ex-00001", spelled, replaces=OLD)

        assert r.status_code == 200, r.text
        assert await _points(live_client, "ex-00001") == ["IT001E00000003", spelled]
        assert (await _pods(live_client, "ex-00001"))["meter-SEN-1"] == spelled

    async def test_an_old_id_that_is_not_the_members_is_404_and_changes_nothing(
        self, live_client
    ):
        """Another member's POD is not this member's to replace.

        @verifies REQ-0084
        """
        await self._setup(live_client)
        before = (
            await _points(live_client, "ex-00001"),
            await _pods(live_client, "ex-00001"),
        )

        for old in ("IT001E00000004", "IT001E09999999", "", "  "):
            r = await _put(live_client, "ex-00001", NEW, replaces=old)
            assert r.status_code == 404, (old, r.text)

        after = (
            await _points(live_client, "ex-00001"),
            await _pods(live_client, "ex-00001"),
        )
        assert after == before

    async def test_a_failure_leaves_both_points_and_every_link_as_they_were(
        self, live_client, monkeypatch
    ):
        """Fail after the points changed and the meters were relinked, before
        the commit: nothing of it is visible afterwards.

        @verifies REQ-0084
        """
        await self._setup(live_client)
        before = (
            await _points(live_client, "ex-00001"),
            await _pods(live_client, "ex-00001"),
        )
        relink = member_service.relink_meters
        relinked: list[int] = []

        async def relink_then_fail(session, member, old_id, new_id):
            relinked.append(await relink(session, member, old_id, new_id))
            raise RuntimeError("injected after the relink")

        monkeypatch.setattr(member_service, "relink_meters", relink_then_fail)

        with pytest.raises(RuntimeError, match="injected"):
            await _put(live_client, "ex-00001", NEW, replaces=OLD)

        assert relinked == [2], "the failure must come after real work"
        after = (
            await _points(live_client, "ex-00001"),
            await _pods(live_client, "ex-00001"),
        )
        assert after == before

    async def test_a_new_id_another_active_member_holds_is_refused_whole(
        self, live_client
    ):
        """@verifies REQ-0084
        @verifies REQ-0085"""
        await self._setup(live_client)
        before = (
            await _points(live_client, "ex-00001"),
            await _pods(live_client, "ex-00001"),
        )

        r = await _put(live_client, "ex-00001", "IT001E00000004", replaces=OLD)

        _refusal(r, 409, "delivery_point_held")
        after = (
            await _points(live_client, "ex-00001"),
            await _pods(live_client, "ex-00001"),
        )
        assert after == before

    async def test_without_replaces_the_put_merges_as_before(self, live_client):
        """@verifies REQ-0084
        @verifies REQ-0027"""
        await self._setup(live_client)

        r = await _put(live_client, "ex-00001", NEW)

        assert r.status_code == 200, r.text
        assert await _points(live_client, "ex-00001") == [OLD, "IT001E00000003", NEW]
        assert (await _pods(live_client, "ex-00001"))["meter-SEN-1"] == OLD


@pytest.mark.integration
class TestDeletingALinkedPoint:
    async def test_a_point_a_meter_names_is_delivery_point_linked(self, live_client):
        """Compared trimmed and case-insensitively, as the relink is.

        @verifies REQ-0084
        """
        await _community(live_client)
        await _add(live_client, "ex-00001", 1, pods=[OLD, NEW])
        await _meter(live_client, "ex-00001", "SEN-1", f" {OLD.lower()}")

        r = await live_client.delete(_path("ex-00001", OLD))

        detail = _refusal(r, 409, "delivery_point_linked")
        assert "SEN-1" not in detail
        assert await _points(live_client, "ex-00001") == [OLD, NEW]

    async def test_after_a_correction_or_a_detach_it_can_be_deleted(self, live_client):
        """@verifies REQ-0084"""
        await _community(live_client)
        await _add(live_client, "ex-00001", 1, pods=[OLD, NEW])
        await _meter(live_client, "ex-00001", "SEN-1", OLD)
        await _meter(live_client, "ex-00001", "SEN-2", NEW)

        r = await _put(live_client, "ex-00001", "IT001E00000005", replaces=OLD)
        assert r.status_code == 200, r.text
        r = await live_client.delete(
            f"/admin/communities/{C}/members/ex-00001/assets/meter-SEN-2"
        )
        assert r.status_code == 204, r.text

        r = await live_client.delete(_path("ex-00001", NEW))

        assert r.status_code == 200, r.text
        assert await _points(live_client, "ex-00001") == ["IT001E00000005"]

    async def test_a_point_nothing_names_is_deleted_and_an_unknown_one_is_404(
        self, live_client
    ):
        """@verifies REQ-0084
        @verifies REQ-0027"""
        await _community(live_client)
        await _add(live_client, "ex-00001", 1, pods=[OLD, NEW])
        await _meter(live_client, "ex-00001", "SEN-1", NEW)

        assert (await live_client.delete(_path("ex-00001", OLD))).status_code == 200
        r = await live_client.delete(_path("ex-00001", OLD))
        assert r.status_code == 404
        assert set(r.json()) == {"detail"}
        assert await _points(live_client, "ex-00001") == [NEW]


# =============================================================================
# F6: one active holder per delivery point (REQ-0085)
# =============================================================================


@pytest.mark.integration
class TestThePut:
    async def test_a_point_another_active_member_holds_is_refused_named(
        self, live_client
    ):
        """Inside the community the holder may be named (REQ-0060).

        @verifies REQ-0085
        """
        await _community(live_client)
        await _add(live_client, "ex-00001", 1, pods=[OLD])
        await _add(live_client, "ex-00002", 2)

        detail = _refusal(
            await _put(live_client, "ex-00002", OLD), 409, "delivery_point_held"
        )

        assert "ex-00001" in detail
        assert await _points(live_client, "ex-00002") == []

    async def test_a_holder_in_another_community_is_not_named(self, live_client):
        """@verifies REQ-0085"""
        await _community(live_client, "example-rec-a")
        await _community(live_client, "example-rec-b")
        await _add(live_client, "ex-00001", 1, community="example-rec-a", pods=[OLD])
        await _add(live_client, "ex-00009", 9, community="example-rec-b")

        r = await _put(live_client, "ex-00009", OLD, community="example-rec-b")

        detail = _refusal(r, 409, "delivery_point_held")
        assert "ex-00001" not in detail and "example-rec-a" not in detail

    @pytest.mark.parametrize("spelling", [OLD.lower(), "It001e00000001", f" {OLD} "])
    async def test_the_comparison_is_trimmed_and_case_insensitive(
        self, live_client, spelling
    ):
        """@verifies REQ-0085"""
        await _community(live_client)
        await _add(live_client, "ex-00001", 1, pods=[OLD])
        await _add(live_client, "ex-00002", 2)

        _refusal(
            await _put(live_client, "ex-00002", spelling), 409, "delivery_point_held"
        )
        assert await _points(live_client, "ex-00002") == []

    async def test_an_untrimmed_point_already_stored_still_counts(
        self, live_client, pg_engine
    ):
        """@verifies REQ-0085"""
        await _community(live_client)
        await _add(live_client, "ex-00001", 1, pods=[OLD])
        await _add(live_client, "ex-00002", 2)
        async with pg_engine.begin() as conn:
            await conn.execute(
                text(
                    "update member set delivery_points = "
                    "jsonb_build_array(jsonb_build_object('id', cast(:id as text), 'type', 'pod')) "
                    "where key = 'ex-00001'"
                ),
                {"id": f" {OLD.lower()}\t"},
            )

        _refusal(await _put(live_client, "ex-00002", OLD), 409, "delivery_point_held")

    @pytest.mark.parametrize("status", ["inactive", "suspended", "pending"])
    async def test_a_member_who_is_not_active_holds_nothing(self, live_client, status):
        """@verifies REQ-0085"""
        await _community(live_client)
        await _add(live_client, "ex-00001", 1, pods=[OLD], status=status)
        await _add(live_client, "ex-00002", 2)

        r = await _put(live_client, "ex-00002", OLD)

        assert r.status_code == 200, r.text

    async def test_a_member_who_is_not_active_is_not_checked(self, live_client):
        """Checked when it is reactivated instead.

        @verifies REQ-0085
        """
        await _community(live_client)
        await _add(live_client, "ex-00001", 1, pods=[OLD])
        await _add(live_client, "ex-00002", 2, status="suspended")

        assert (await _put(live_client, "ex-00002", OLD)).status_code == 200

    async def test_resending_the_members_own_point_is_not_a_clash(self, live_client):
        """@verifies REQ-0085"""
        await _community(live_client)
        await _add(live_client, "ex-00001", 1, pods=[OLD])

        assert (await _put(live_client, "ex-00001", OLD)).status_code == 200
        assert (
            await _put(live_client, "ex-00001", OLD.lower(), replaces=OLD)
        ).status_code == 200


@pytest.mark.integration
class TestCreatingAMember:
    async def test_an_active_member_with_a_held_point_is_refused(self, live_client):
        """@verifies REQ-0085"""
        await _community(live_client, "example-rec-a")
        await _community(live_client, "example-rec-b")
        await _add(live_client, "ex-00001", 1, community="example-rec-a", pods=[OLD])

        for community in ("example-rec-a", "example-rec-b"):
            r = await live_client.post(
                f"/admin/communities/{community}/members",
                json=_member("ex-00002", 2, pods=[f" {OLD.lower()} "]),
            )
            _refusal(r, 409, "delivery_point_held")
            r = await live_client.get(
                f"/admin/communities/{community}/members/ex-00002"
            )
            assert r.status_code == 404

    async def test_a_pending_member_is_created_and_holds_nothing_yet(self, live_client):
        """@verifies REQ-0085"""
        await _community(live_client)
        await _add(live_client, "ex-00001", 1, pods=[OLD])

        await _add(live_client, "ex-00002", 2, pods=[OLD], status="pending")


@pytest.mark.integration
class TestReactivation:
    async def _taken_meanwhile(self, client) -> None:
        """ex-00001 held OLD, was suspended, and ex-00002 took it."""
        await _community(client)
        await _add(client, "ex-00001", 1, pods=[OLD])
        await _add(client, "ex-00002", 2)
        r = await client.post(
            f"/admin/communities/{C}/members/ex-00001/status",
            json={"status": "suspended"},
        )
        assert r.status_code == 200, r.text
        assert (await _put(client, "ex-00002", OLD)).status_code == 200

    async def test_the_status_route_refuses_and_leaves_the_status(self, live_client):
        """@verifies REQ-0085"""
        await self._taken_meanwhile(live_client)

        r = await live_client.post(
            f"/admin/communities/{C}/members/ex-00001/status", json={"status": "active"}
        )

        _refusal(r, 409, "delivery_point_held")
        assert await _status(live_client, "ex-00001") == "suspended"

    async def test_patch_refuses_the_whole_patch(self, live_client):
        """@verifies REQ-0085"""
        await self._taken_meanwhile(live_client)

        r = await live_client.patch(
            f"/admin/communities/{C}/members/ex-00001",
            json={"status": "active", "name": "Changed"},
        )

        _refusal(r, 409, "delivery_point_held")
        r = await live_client.get(f"/admin/communities/{C}/members/ex-00001")
        assert (r.json()["status"], r.json()["name"]) == ("suspended", "Example Member")

    async def test_it_succeeds_once_the_point_is_free(self, live_client):
        """An inactive holder does not count either.

        @verifies REQ-0085
        """
        await self._taken_meanwhile(live_client)
        r = await live_client.delete(f"/admin/communities/{C}/members/ex-00002")
        assert r.status_code == 200, r.text  # soft: inactive

        r = await live_client.post(
            f"/admin/communities/{C}/members/ex-00001/status", json={"status": "active"}
        )

        assert r.status_code == 200, r.text


@pytest.mark.integration
class TestTheImport:
    async def test_two_active_holders_in_one_bundle_are_refused(self, live_client):
        """Refused whole, naming this bundle's members and never the POD.

        @verifies REQ-0085
        """
        bundle = _bundle(
            C,
            {
                "ex-00001": _bundle_member(1, [OLD]),
                "ex-00002": _bundle_member(2, [f" {OLD.lower()} "]),
            },
        )

        r = await live_client.post("/admin/import", json={"bundle": bundle})
        dry = await live_client.post(
            "/admin/import", json={"bundle": bundle, "dry_run": True}
        )

        detail = _refusal(r, 422, "delivery_point_held")
        assert "ex-00001" in detail and "ex-00002" in detail
        assert OLD not in detail and OLD.lower() not in detail
        assert (await live_client.get(f"/admin/communities/{C}")).status_code == 404
        assert dry.status_code == 200, dry.text
        assert [x["code"] for x in dry.json()["refusals"]] == ["delivery_point_held"]

    async def test_a_point_held_in_another_community_refuses_it_unnamed(
        self, live_client
    ):
        """@verifies REQ-0085"""
        await _community(live_client, "example-rec-a")
        await _add(live_client, "ex-00001", 1, community="example-rec-a", pods=[OLD])
        bundle = _bundle("example-rec-b", {"ex-00009": _bundle_member(9, [OLD])})

        r = await live_client.post("/admin/import", json={"bundle": bundle})

        detail = _refusal(r, 422, "delivery_point_held")
        assert "ex-00009" in detail
        assert "ex-00001" not in detail and "example-rec-a" not in detail
        assert OLD not in detail

    async def test_the_replaced_communitys_own_rows_do_not_count(self, live_client):
        """@verifies REQ-0085"""
        members = {"ex-00001": _bundle_member(1, [OLD])}
        r = await live_client.post(
            "/admin/import", json={"bundle": _bundle(C, members)}
        )
        assert r.status_code == 200, r.text

        r = await live_client.post(
            "/admin/import", json={"bundle": _bundle(C, members), "force": True}
        )

        assert r.status_code == 200, r.text

    async def test_an_inactive_holder_is_not_a_clash(self, live_client):
        """@verifies REQ-0085"""
        await _community(live_client, "example-rec-a")
        await _add(live_client, "ex-00001", 1, community="example-rec-a", pods=[OLD])
        bundle = _bundle(
            "example-rec-b",
            {
                "ex-00008": _bundle_member(8, [OLD], status="inactive"),
                "ex-00009": _bundle_member(9, [OLD], status="pending"),
            },
        )

        r = await live_client.post("/admin/import", json={"bundle": bundle})

        assert r.status_code == 200, r.text
        assert r.json()["refusals"] == []


# =============================================================================
# F7: the report of duplicates already stored (REQ-0086)
# =============================================================================


@pytest.mark.integration
class TestTheDuplicatesReportAgainstAnExport:
    async def test_it_finds_holders_written_before_the_check(
        self, live_client, pg_engine
    ):
        """The check refuses the next write, not the past ones: rows that
        already break the rule are what the report exists to find, across
        communities, compared trimmed and case-insensitively.

        @verifies REQ-0086
        """
        import yaml

        from celine.rec_registry.cli.main import find_duplicate_delivery_points

        await _community(live_client, "example-rec-a")
        await _community(live_client, "example-rec-b")
        await _add(live_client, "ex-00001", 1, community="example-rec-a", pods=[OLD])
        await _add(
            live_client,
            "ex-00009",
            9,
            community="example-rec-b",
            pods=[f" {OLD.lower()}"],
            status="pending",
        )
        await _add(
            live_client,
            "ex-00008",
            8,
            community="example-rec-b",
            pods=[OLD],
            status="inactive",
        )
        # As if written before the rule existed: ex-00009 becomes active
        # without the reactivation check; ex-00008 stays inactive.
        async with pg_engine.begin() as conn:
            await conn.execute(
                text("update member set status = 'active' where key = 'ex-00009'")
            )

        exported = await live_client.get("/admin/export")
        assert exported.status_code == 200, exported.text
        docs = [d for d in yaml.safe_load_all(exported.text) if d]

        assert find_duplicate_delivery_points(docs) == [
            (
                OLD.lower(),
                [("example-rec-a", "ex-00001"), ("example-rec-b", "ex-00009")],
            )
        ]
        # And the writes it warns about are the ones F6 now refuses.
        r = await live_client.post(
            "/admin/communities/example-rec-b/members/ex-00008/status",
            json={"status": "active"},
        )
        _refusal(r, 409, "delivery_point_held")


# =============================================================================
# Two writers at once
# =============================================================================


async def _wait_until_blocked(
    engine, holder_pid: int, *, timeout: float = 10.0
) -> None:
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
        f"no backend ever waited on pid {holder_pid}; the second write did not "
        "reach the advisory lock, so this test would pass for the wrong reason"
    )


@pytest.mark.integration
class TestTwoWritersAtOnce:
    """Neither writer can see the other's uncommitted list, and no unique index
    can say "among active members" — the advisory lock is what serialises them."""

    async def test_the_second_waits_for_the_first_and_is_delivery_point_held(
        self, live_client, pg_engine
    ):
        """Held open deliberately, as the sensor test is.

        @verifies REQ-0085
        """
        await _community(live_client, "example-rec-a")
        await _community(live_client, "example-rec-b")
        await _add(live_client, "ex-00001", 1, community="example-rec-a")
        await _add(live_client, "ex-00009", 9, community="example-rec-b")

        maker = async_sessionmaker(pg_engine, expire_on_commit=False)
        async with maker() as holder:
            holder_pid = await holder.scalar(text("select pg_backend_pid()"))
            community = await member_service.resolve_community(holder, "example-rec-a")
            member = await member_service.resolve_member(holder, community, "ex-00001")
            await member_service.put_delivery_point(
                holder, community, member, DeliveryPointIn(id=OLD, type="pod")
            )
            # Flushed, not committed: invisible to the request below.

            request = asyncio.create_task(
                _put(live_client, "ex-00009", OLD.lower(), community="example-rec-b")
            )
            await _wait_until_blocked(pg_engine, holder_pid)
            await holder.commit()
            r = await request

        _refusal(r, 409, "delivery_point_held")
        assert await _points(live_client, "ex-00009", "example-rec-b") == []

    async def test_of_a_concurrent_pair_exactly_one_wins(self, live_client):
        """@verifies REQ-0085"""
        await _community(live_client, "example-rec-a")
        await _community(live_client, "example-rec-b")
        await _add(live_client, "ex-00001", 1, community="example-rec-a")
        await _add(live_client, "ex-00009", 9, community="example-rec-b")

        for round_ in range(5):
            pod = f"IT001E1000000{round_}"
            first, second = await asyncio.gather(
                _put(live_client, "ex-00001", pod, community="example-rec-a"),
                _put(live_client, "ex-00009", pod, community="example-rec-b"),
            )
            statuses = sorted([first.status_code, second.status_code])
            assert statuses == [200, 409], (first.text, second.text)
            loser = first if first.status_code == 409 else second
            assert loser.json()["code"] == "delivery_point_held"

    async def test_a_concurrent_create_and_put_leave_one_holder(self, live_client):
        """The create path takes the same lock.

        @verifies REQ-0085
        """
        await _community(live_client, "example-rec-a")
        await _community(live_client, "example-rec-b")
        await _add(live_client, "ex-00001", 1, community="example-rec-a")

        for round_ in range(5):
            pod = f"IT001E2000000{round_}"
            put, create = await asyncio.gather(
                _put(live_client, "ex-00001", pod, community="example-rec-a"),
                live_client.post(
                    "/admin/communities/example-rec-b/members",
                    json=_member(f"ex-1000{round_}", 100 + round_, pods=[pod]),
                ),
            )
            assert sorted([put.status_code, create.status_code]) in (
                [200, 409],
                [201, 409],
            ), (put.text, create.text)
            loser = put if put.status_code == 409 else create
            assert loser.json()["code"] == "delivery_point_held"


# =============================================================================
# The OpenAPI document
# =============================================================================


class TestTheOpenApiDocument:
    def test_the_put_publishes_replaces_and_both_coded_refusals(self):
        """The SDK is generated from this document.

        @verifies REQ-0084
        @verifies REQ-0073
        """
        from celine.rec_registry.main import create_app

        doc = create_app().openapi()
        path = doc["paths"][
            "/admin/communities/{community_key}/members/{member_key}"
            "/delivery-points/{point_id}"
        ]
        params = {p["name"]: p for p in path["put"]["parameters"]}
        assert params["replaces"]["in"] == "query"
        assert params["replaces"]["required"] is False
        error = {"$ref": "#/components/schemas/ErrorResponse"}
        for method in ("put", "delete"):
            assert "replaces" not in {p["name"] for p in path["delete"]["parameters"]}
            body = path[method]["responses"]["409"]["content"]["application/json"]
            assert body["schema"] == error, method
        codes = doc["components"]["schemas"]["ErrorCode"]["enum"]
        assert {"delivery_point_held", "delivery_point_linked"} <= set(codes)
