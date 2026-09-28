"""An area's key is renamed in one write, with its members (REQ-0079).

The route an onboarding template sync renames an area through when the
template holds a substation the registry already has under another key: an
area `PUT` under the new key is refused (one area per boundary, REQ-0067), and
the old key cannot be deleted while members hold it (REQ-0030). The rename
moves the area and its members at once, under the community's row lock. The
substation codes are synthetic placeholders (`tests/substations.py`).
"""

from __future__ import annotations

import asyncio

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from celine.rec_registry.core.area_boundary import is_area_key
from celine.rec_registry.services import members as member_service
from tests.substations import substation_area, substation_code, substation_graph

A1, A2, A3 = (substation_code(n) for n in (1, 2, 3))

RENAME = "/admin/communities/{c}/areas/{a}/rename"
PROFILE = "/admin/communities/{c}/members/{m}/profile"


# =============================================================================
# Helpers
# =============================================================================


def _bundle(key: str) -> dict:
    graph = substation_graph("north", "south", "east")
    graph["areas"]["north"]["name"] = "North Area"
    graph["topology"].append(
        {"id": "SS-1", "type": "secondary_substation", "parent": A1}
    )
    return {
        "version": "1.0",
        "schema_version": "0.7",
        "community": {"id": key, "name": "Rename Community", **graph},
        "members": {},
    }


async def _community(client, key: str = "example-rec") -> str:
    r = await client.post("/admin/import", json={"bundle": _bundle(key)})
    assert r.status_code == 200, r.text
    return key


async def _add(client, c: str, key: str, user_id: str, **fields) -> str:
    payload = {
        "key": key,
        "user_id": user_id,
        "name": "Example Member",
        "role": "consumer",
        "area": "north",
        "status": "active",
        "delivery_points": [{"id": f"IT001E0000000{key[-1]}", "type": "pod"}],
        **fields,
    }
    r = await client.post(f"/admin/communities/{c}/members", json=payload)
    assert r.status_code == 201, r.text
    return key


async def _member(client, c: str, key: str) -> dict:
    r = await client.get(f"/admin/communities/{c}/members/{key}")
    assert r.status_code == 200, r.text
    return r.json()


async def _community_detail(client, c: str) -> dict:
    r = await client.get(f"/admin/communities/{c}")
    assert r.status_code == 200, r.text
    return r.json()


def _refusal(r, status: int, code: str) -> str:
    assert r.status_code == status, r.text
    body = r.json()
    assert body["code"] == code, body
    assert isinstance(body["detail"], str)
    return body["detail"]


def _without_timestamps(member: dict) -> dict:
    return {k: v for k, v in member.items() if k not in ("updated_at", "area")}


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
    raise AssertionError(f"no backend ever waited on pid {holder_pid}")


# =============================================================================
# The key rule — pure
# =============================================================================


class TestTheAreaKey:
    @pytest.mark.parametrize(
        "key", ["north", "N", "7", "area_2", "north-2", "a" * 128, "A1-b_c"]
    )
    def test_letters_digits_dash_and_underscore_are_a_key(self, key):
        """@verifies REQ-0079"""
        assert is_area_key(key)

    @pytest.mark.parametrize(
        "key",
        ["", " ", "-north", "_north", "north ", "a b", "a/b", "a.b", "nörd", "a" * 129, None, 7],
    )
    def test_anything_else_is_not(self, key):
        """@verifies REQ-0079"""
        assert not is_area_key(key)


# =============================================================================
# The route — live
# =============================================================================


@pytest.mark.integration
class TestTheRename:
    async def test_the_area_moves_to_the_new_key_as_it_was(self, live_client):
        """Name, boundary and topology unchanged, under the new key; the old
        key is gone.

        @verifies REQ-0079
        """
        c = await _community(live_client)
        before = (await _community_detail(live_client, c))["areas"]

        r = await live_client.post(RENAME.format(c=c, a="north"), json={"new_key": "nord"})

        assert r.status_code == 200, r.text
        body = r.json()
        assert (body["old_key"], body["new_key"], body["members_moved"]) == ("north", "nord", 0)
        areas = body["community"]["areas"]
        assert set(areas) == {"nord", "south", "east"}
        assert areas["nord"] == before["north"]
        assert areas["nord"]["name"] == "North Area"
        assert areas["nord"]["boundary"] == {"source": "gse_cabine_primarie", "id": A1}
        assert areas["nord"]["topology"] == [A1]
        assert (await _community_detail(live_client, c))["areas"] == areas

    async def test_every_member_of_the_area_moves_whatever_their_status(
        self, live_client
    ):
        """@verifies REQ-0079"""
        c = await _community(live_client)
        for n, status in enumerate(("active", "pending", "suspended", "inactive"), 1):
            await _add(live_client, c, f"ex-0000{n}", f"kc-000{n}", status=status)
        await _add(live_client, c, "ex-00005", "kc-0005", area="south")

        r = await live_client.post(RENAME.format(c=c, a="north"), json={"new_key": "nord"})

        assert r.status_code == 200, r.text
        assert r.json()["members_moved"] == 4
        for n in range(1, 5):
            assert (await _member(live_client, c, f"ex-0000{n}"))["area"] == "nord"
        assert (await _member(live_client, c, "ex-00005"))["area"] == "south"
        listing = await live_client.get(f"/admin/communities/{c}/members?area=north")
        assert listing.json()["items"] == []

    async def test_another_communitys_area_of_the_same_key_is_not_touched(
        self, live_client
    ):
        """@verifies REQ-0079"""
        c = await _community(live_client)
        other = await _community(live_client, "example-rec-2")
        await _add(live_client, c, "ex-00001", "kc-0001")
        await _add(live_client, other, "ex-00001", "kc-0001")

        r = await live_client.post(RENAME.format(c=c, a="north"), json={"new_key": "nord"})

        assert r.status_code == 200, r.text
        assert (await _member(live_client, other, "ex-00001"))["area"] == "north"
        assert "north" in (await _community_detail(live_client, other))["areas"]

    async def test_the_renamed_area_keeps_the_one_boundary_rule(self, live_client):
        """The boundary goes with the key: the old key cannot be re-created on
        it, and the new one cannot be written onto another area's boundary.

        @verifies REQ-0079
        @verifies REQ-0067
        """
        c = await _community(live_client)
        r = await live_client.post(RENAME.format(c=c, a="north"), json={"new_key": "nord"})
        assert r.status_code == 200, r.text

        r = await live_client.put(
            f"/admin/communities/{c}/areas/north", json=substation_area("North", 1)
        )
        _refusal(r, 422, "invalid_area_boundary")
        r = await live_client.put(
            f"/admin/communities/{c}/areas/nord", json=substation_area("Nord", 1)
        )
        assert r.status_code == 200, r.text
        assert r.json()["areas"]["nord"]["name"] == "Nord"

    async def test_member_writes_follow_the_new_key(self, live_client):
        """@verifies REQ-0079"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001", area="south")
        assert (
            await live_client.post(RENAME.format(c=c, a="north"), json={"new_key": "nord"})
        ).status_code == 200

        r = await live_client.patch(PROFILE.format(c=c, m="ex-00001"), json={"area": "north"})
        _refusal(r, 422, "unknown_area")
        r = await live_client.patch(PROFILE.format(c=c, m="ex-00001"), json={"area": "nord"})
        assert r.status_code == 200, r.text
        assert r.json()["area"] == "nord"

    async def test_the_export_carries_the_new_key(self, live_client):
        """@verifies REQ-0079"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        assert (
            await live_client.post(RENAME.format(c=c, a="north"), json={"new_key": "nord"})
        ).status_code == 200

        r = await live_client.get(f"/admin/export?community={c}")
        assert r.status_code == 200, r.text
        (bundle,) = [d for d in yaml.safe_load_all(r.text) if d]
        areas = bundle["community"]["areas"]
        assert "nord" in areas and "north" not in areas
        assert [m["area"] for m in bundle["members"].values()] == ["nord"]


@pytest.mark.integration
class TestARenamedArea:
    """What an onboarding template sync meets when a template renames an area
    that has members: the create is refused, the delete is refused, the
    rename moves it, and the sync's own area `PUT` is then a replace.
    """

    async def test_a_renamed_area_with_members_is_moved_not_recreated(self, live_client):
        """@verifies REQ-0079"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        await _add(live_client, c, "ex-00002", "kc-0002", status="suspended")
        areas = f"/admin/communities/{c}/areas"

        _refusal(
            await live_client.put(f"{areas}/nord", json=substation_area("Nord", 1)),
            422,
            "invalid_area_boundary",
        )
        _refusal(await live_client.delete(f"{areas}/north"), 409, "area_in_use")

        r = await live_client.post(RENAME.format(c=c, a="north"), json={"new_key": "nord"})
        assert r.status_code == 200, r.text
        assert r.json()["members_moved"] == 2

        r = await live_client.put(f"{areas}/nord", json=substation_area("Nord", 1))
        assert r.status_code == 200, r.text
        assert set(r.json()["areas"]) == {"nord", "south", "east"}
        for m in ("ex-00001", "ex-00002"):
            assert (await _member(live_client, c, m))["area"] == "nord"


@pytest.mark.integration
class TestTheRenameRefuses:
    async def _unchanged(self, client, c: str, before: dict) -> None:
        assert await _community_detail(client, c) == before
        assert (await _member(client, c, "ex-00001"))["area"] == "north"

    async def test_a_new_key_the_community_has_is_409(self, live_client):
        """@verifies REQ-0079"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        before = await _community_detail(live_client, c)

        r = await live_client.post(RENAME.format(c=c, a="north"), json={"new_key": "south"})

        detail = _refusal(r, 409, "area_key_taken")
        assert "'south'" in detail
        await self._unchanged(live_client, c, before)

    async def test_renaming_to_itself_is_409(self, live_client):
        """@verifies REQ-0079"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        before = await _community_detail(live_client, c)

        r = await live_client.post(RENAME.format(c=c, a="north"), json={"new_key": "north"})

        _refusal(r, 409, "area_key_taken")
        await self._unchanged(live_client, c, before)

    async def test_an_absent_area_is_404(self, live_client):
        """@verifies REQ-0079"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        before = await _community_detail(live_client, c)

        r = await live_client.post(RENAME.format(c=c, a="nowhere"), json={"new_key": "x"})

        _refusal(r, 404, "area_not_found")
        await self._unchanged(live_client, c, before)

    async def test_an_unknown_community_is_404(self, live_client):
        """@verifies REQ-0079"""
        r = await live_client.post(RENAME.format(c="nowhere", a="north"), json={"new_key": "x"})

        _refusal(r, 404, "community_not_found")

    @pytest.mark.parametrize("new_key", ["", "-nord", "no rd", "nörd", "a" * 129, "a/b"])
    async def test_a_new_key_that_is_not_an_area_key_is_422(self, live_client, new_key):
        """@verifies REQ-0079"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        before = await _community_detail(live_client, c)

        r = await live_client.post(RENAME.format(c=c, a="north"), json={"new_key": new_key})

        detail = _refusal(r, 422, "invalid_area_key")
        assert new_key not in detail or new_key == ""
        await self._unchanged(live_client, c, before)

    @pytest.mark.parametrize(
        "body", [{}, {"new_key": "nord", "name": "x"}, {"new_key": None}, {"key": "nord"}]
    )
    async def test_a_body_other_than_new_key_is_422(self, live_client, body):
        """@verifies REQ-0079"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        before = await _community_detail(live_client, c)

        r = await live_client.post(RENAME.format(c=c, a="north"), json=body)

        assert r.status_code == 422, r.text
        await self._unchanged(live_client, c, before)


@pytest.mark.integration
class TestARenameReducesNoSibling:
    """The rename touches the area's key and its members' `area`, and nothing
    else: not the other areas, not the topology, not the members' other
    fields, not their assets (REQ-0031)."""

    async def test_everything_but_the_key_and_the_members_area_is_as_it_was(
        self, live_client
    ):
        """@verifies REQ-0079
        @verifies REQ-0031"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001", role="prosumer", extra={"note": "n"})
        await _add(live_client, c, "ex-00002", "kc-0002", area="south")
        r = await live_client.patch(
            f"/admin/communities/{c}/members/ex-00001",
            json={"did": "did:web:dataspace.example:ex-1"},
        )
        assert r.status_code == 200, r.text
        r = await live_client.put(
            f"/admin/communities/{c}/members/ex-00001/assets/meter-SEN-1",
            json={
                "key": "meter-SEN-1",
                "asset_type": "meter",
                "properties": {"name": "M", "sensor_id": "SEN-1", "meter_type": "consumption"},
            },
        )
        assert r.status_code == 200, r.text

        community_before = await _community_detail(live_client, c)
        moved_before = await _member(live_client, c, "ex-00001")
        other_before = await _member(live_client, c, "ex-00002")
        assets_before = (await live_client.get(f"/admin/communities/{c}/assets")).json()

        r = await live_client.post(RENAME.format(c=c, a="north"), json={"new_key": "nord"})
        assert r.status_code == 200, r.text

        community_after = await _community_detail(live_client, c)
        for field in ("topology", "name", "legal", "links", "contact", "settings", "extra"):
            assert community_after[field] == community_before[field], field
        assert {k: v for k, v in community_after["areas"].items() if k != "nord"} == {
            k: v for k, v in community_before["areas"].items() if k != "north"
        }
        moved_after = await _member(live_client, c, "ex-00001")
        assert moved_after["area"] == "nord"
        assert _without_timestamps(moved_after) == _without_timestamps(moved_before)
        assert await _member(live_client, c, "ex-00002") == other_before
        assets_after = (await live_client.get(f"/admin/communities/{c}/assets")).json()
        assert assets_after == assets_before
        listing = await live_client.get(f"/admin/communities/{c}/members")
        assert len(listing.json()["items"]) == 2


# =============================================================================
# Concurrency with member writes (community row before member rows)
# =============================================================================


@pytest.mark.integration
class TestARenameAndAMemberWriteAtOnce:
    """A member write naming an area holds the community's row shared; the
    rename takes it exclusively, then updates member rows — the order every
    write takes them in. Each case holds the first writer open deliberately.
    """

    async def test_a_rename_waits_for_a_member_moving_in_and_moves_them_too(
        self, live_client, pg_engine
    ):
        """@verifies REQ-0079"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001", area="south")
        maker = async_sessionmaker(pg_engine, expire_on_commit=False)

        async with maker() as holder:
            pid = await holder.scalar(text("select pg_backend_pid()"))
            community = await member_service.resolve_community(holder, c)
            await member_service.lock_community(holder, community, share=True)
            member = await member_service.resolve_member(holder, community, "ex-00001")
            member.area = "north"
            await holder.flush()

            request = asyncio.create_task(
                live_client.post(RENAME.format(c=c, a="north"), json={"new_key": "nord"})
            )
            await _wait_until_blocked(pg_engine, pid)
            await holder.commit()
            r = await request

        assert r.status_code == 200, r.text
        assert r.json()["members_moved"] == 1
        assert (await _member(live_client, c, "ex-00001"))["area"] == "nord"

    async def test_a_member_moving_in_during_a_rename_waits_and_finds_it_gone(
        self, live_client, pg_engine
    ):
        """@verifies REQ-0079"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001", area="south")
        maker = async_sessionmaker(pg_engine, expire_on_commit=False)

        async with maker() as holder:
            pid = await holder.scalar(text("select pg_backend_pid()"))
            community = await member_service.resolve_community(holder, c)
            assert await member_service.rename_area(holder, community, "north", "nord") == 0
            await holder.flush()

            request = asyncio.create_task(
                live_client.patch(PROFILE.format(c=c, m="ex-00001"), json={"area": "north"})
            )
            await _wait_until_blocked(pg_engine, pid)
            await holder.commit()
            r = await request

        _refusal(r, 422, "unknown_area")
        assert (await _member(live_client, c, "ex-00001"))["area"] == "south"

    async def test_a_member_moving_to_the_new_key_during_a_rename_lands_there(
        self, live_client, pg_engine
    ):
        """@verifies REQ-0079"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001", area="south")
        maker = async_sessionmaker(pg_engine, expire_on_commit=False)

        async with maker() as holder:
            pid = await holder.scalar(text("select pg_backend_pid()"))
            community = await member_service.resolve_community(holder, c)
            await member_service.rename_area(holder, community, "north", "nord")
            await holder.flush()

            request = asyncio.create_task(
                live_client.patch(PROFILE.format(c=c, m="ex-00001"), json={"area": "nord"})
            )
            await _wait_until_blocked(pg_engine, pid)
            await holder.commit()
            r = await request

        assert r.status_code == 200, r.text
        assert (await _member(live_client, c, "ex-00001"))["area"] == "nord"

    async def test_a_role_change_during_a_rename_keeps_the_moved_area(
        self, live_client, pg_engine
    ):
        """A role-only write takes no community lock; it waits on the member
        row the rename updated, and writes the role alone — the area the
        rename set survives.

        @verifies REQ-0079
        """
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        maker = async_sessionmaker(pg_engine, expire_on_commit=False)

        async with maker() as holder:
            pid = await holder.scalar(text("select pg_backend_pid()"))
            community = await member_service.resolve_community(holder, c)
            assert await member_service.rename_area(holder, community, "north", "nord") == 1
            await holder.flush()

            request = asyncio.create_task(
                live_client.patch(
                    PROFILE.format(c=c, m="ex-00001"), json={"role": "prosumer"}
                )
            )
            await _wait_until_blocked(pg_engine, pid)
            await holder.commit()
            r = await request

        assert r.status_code == 200, r.text
        member = await _member(live_client, c, "ex-00001")
        assert (member["role"], member["area"]) == ("prosumer", "nord")

    async def test_two_renames_of_one_area_at_once_one_wins(self, live_client):
        """@verifies REQ-0079"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")

        first, second = await asyncio.gather(
            live_client.post(RENAME.format(c=c, a="north"), json={"new_key": "nord"}),
            live_client.post(RENAME.format(c=c, a="north"), json={"new_key": "norte"}),
        )

        statuses = sorted([first.status_code, second.status_code])
        assert statuses == [200, 404], (first.text, second.text)
        winner = first if first.status_code == 200 else second
        new_key = winner.json()["new_key"]
        assert (await _member(live_client, c, "ex-00001"))["area"] == new_key
        areas = (await _community_detail(live_client, c))["areas"]
        assert set(areas) == {new_key, "south", "east"}
