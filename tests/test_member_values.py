"""A member's role and area: the profile route, its action, and the sets every
write path holds role, status and area to.

A community manager corrects a member's role and area from a dashboard: the role
decides whether a meter's production counts, the area decides its substation.
The dashboard is given `members.profile.write` and nothing more, so the route it
writes through accepts `{role?, area?}` and no other key (ADR-0003), and every
path that writes a member — create, both `PATCH` routes, the status route and
the bundle import — refuses a role or status outside its set and an area that is
not one of the community's, with a code (REQ-0066, REQ-0073).

Fixtures are generic: `example-rec`, `ex-0000n`, `SEN-…`.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from typer.testing import CliRunner

from celine.rec_registry.core.member_values import (
    MEMBER_ROLES,
    MEMBER_STATUSES,
    member_value_refusals,
)
from celine.rec_registry.core.middleware import PolicyMiddleware
from celine.rec_registry.services import members as member_service
from celine.rec_registry.core.versions import CURRENT_SCHEMA_VERSION
from tests.substations import substation_graph

action = PolicyMiddleware._get_admin_action

PROFILE = "/admin/communities/{c}/members/{m}/profile"


# =============================================================================
# Helpers
# =============================================================================


def _member(key: str, user_id: str, **overrides) -> dict:
    payload = {
        "key": key,
        "user_id": user_id,
        "name": "Example Member",
        "role": "consumer",
        "area": "north",
        "status": "active",
    }
    payload.update(overrides)
    return payload


def _bundle(key: str, members: dict | None = None, areas=("north", "south")) -> dict:
    return {
        "version": "1.0",
        "schema_version": "0.6",
        "community": {
            "id": key,
            "name": "Example Community",
            **substation_graph(*areas, spare=1),
        },
        "members": members or {},
    }


def _bundle_member(user_id: str, **overrides) -> dict:
    member = _member("unused", user_id, **overrides)
    member.pop("key")
    return member


async def _community(client, key: str = "example-rec", members: dict | None = None):
    r = await client.post("/admin/import", json={"bundle": _bundle(key, members)})
    assert r.status_code == 200, r.text
    return key


async def _add(client, community: str, key: str, user_id: str, **overrides):
    r = await client.post(
        f"/admin/communities/{community}/members",
        json=_member(key, user_id, **overrides),
    )
    assert r.status_code == 201, r.text
    return key


async def _get(client, community: str, member: str) -> dict:
    r = await client.get(f"/admin/communities/{community}/members/{member}")
    assert r.status_code == 200, r.text
    return r.json()


def _refusal(r, status: int, code: str) -> str:
    """Assert the coded body of REQ-0073 and hand back the sentence."""
    assert r.status_code == status, r.text
    body = r.json()
    assert body["code"] == code, body
    assert isinstance(body["detail"], str), "detail must stay a string"
    return body["detail"]


# =============================================================================
# The sets — pure
# =============================================================================


SCHEMA = (
    Path(__file__).parent.parent
    / "schemas"
    / "community"
    / f"v{CURRENT_SCHEMA_VERSION}"
    / "community.schema.json"
)


def _schema_enum(field: str) -> list[str]:
    doc = json.loads(SCHEMA.read_text())

    def walk(node):
        if isinstance(node, dict):
            props = node.get("properties")
            if isinstance(props, dict) and field in props and "enum" in props[field]:
                if {"user_id", "role", "area"} <= set(props):
                    return props[field]["enum"]
            for value in node.values():
                found = walk(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = walk(value)
                if found is not None:
                    return found
        return None

    found = walk(doc)
    assert found is not None, f"no member {field} enum in the schema"
    return found


class TestTheSets:
    def test_they_are_the_published_schemas(self):
        """The registry enforces what the JSON Schema already declares, and
        nothing else — a set that drifted from the schema would refuse a valid
        bundle or accept an invalid one.

        @verifies REQ-0066
        """
        assert list(MEMBER_ROLES) == _schema_enum("role")
        assert list(MEMBER_STATUSES) == _schema_enum("status")

    def test_every_value_in_set_passes(self):
        """@verifies REQ-0066"""
        for role in MEMBER_ROLES:
            for status in MEMBER_STATUSES:
                assert (
                    member_value_refusals(
                        role=role, status=status, area="north", areas=["north"]
                    )
                    == []
                )

    def test_each_field_has_its_code_and_names_the_valid_values(self):
        """@verifies REQ-0066"""
        found = member_value_refusals(
            role="owner", status="retired", area="east", areas=["south", "north"]
        )
        assert [(f.field, f.code.value) for f in found] == [
            ("role", "invalid_role"),
            ("status", "invalid_status"),
            ("area", "unknown_area"),
        ]
        assert "consumer, prosumer, producer, operator, admin" in found[0].detail
        assert "pending, active, suspended, inactive" in found[1].detail
        assert "north, south" in found[2].detail

    def test_a_community_with_no_areas_has_no_valid_area(self):
        """@verifies REQ-0066"""
        assert [f.code.value for f in member_value_refusals(area="north", areas=[])] == [
            "unknown_area"
        ]

    def test_a_field_not_given_is_not_checked(self):
        """A patch checks only what it names.

        @verifies REQ-0066
        """
        assert member_value_refusals(role="prosumer") == []
        assert member_value_refusals() == []

    @pytest.mark.parametrize("role", ["Consumer", " consumer", "", None])
    def test_the_comparison_is_exact(self, role):
        """No case folding and no trimming: the stored value is what readers
        compare against, so an almost-right value is a wrong one.

        @verifies REQ-0066
        """
        assert [f.code.value for f in member_value_refusals(role=role)] == [
            "invalid_role"
        ]


# =============================================================================
# The action (REQ-0063) and the policy (REQ-0064)
# =============================================================================


class TestTheProfileAction:
    def test_the_profile_route_derives_its_own_action(self):
        """@verifies REQ-0063"""
        path = "/admin/communities/rec-a/members/m1/profile"
        assert action(None, path, "PATCH") == "members.profile.write"

    def test_no_other_member_route_derives_it(self):
        """The general PATCH still accepts role and area, and still derives
        `members.write`.

        @verifies REQ-0063
        """
        base = "/admin/communities/rec-a/members"
        assert action(None, f"{base}/m1", "PATCH") == "members.write"
        assert action(None, base, "POST") == "members.write"
        assert action(None, f"{base}/m1/status", "POST") == "members.write"
        assert action(None, f"{base}/m1", "DELETE", "purge=true") == "members.purge"

    @pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
    def test_another_method_on_the_profile_path_is_no_route(self, method):
        """Fail closed: only a PATCH is the profile write.

        @verifies REQ-0063
        """
        path = "/admin/communities/rec-a/members/m1/profile"
        assert action(None, path, method) == "admin"

    def test_reading_it_is_a_read(self):
        """@verifies REQ-0063"""
        path = "/admin/communities/rec-a/members/m1/profile"
        assert action(None, path, "GET") == "read"

    @pytest.mark.parametrize(
        "path",
        [
            # A member keyed `profile` is an ordinary member.
            "/admin/communities/rec-a/members/profile",
            # A community keyed `profile`, too.
            "/admin/communities/profile/members/m1",
        ],
    )
    def test_an_id_spelling_profile_is_not_the_profile_route(self, path):
        """@verifies REQ-0063"""
        assert action(None, path, "PATCH") == "members.write"

    def test_a_member_key_spelling_a_route_word_still_reaches_the_profile_action(
        self,
    ):
        """@verifies REQ-0063"""
        for word in ("profile", "status", "assets", "lookup", "import", "export"):
            path = f"/admin/communities/{word}/members/{word}/profile"
            assert action(None, path, "PATCH") == "members.profile.write", path

    def test_the_rule_names_its_three_scopes(self):
        """The superset is in the rule, not in the shared matcher.

        @verifies REQ-0064
        """
        rego = Path("policies/celine/rec_registry/access.rego").read_text()
        rule = rego.split('input.action.name == "members.profile.write"', 1)[1]
        rule = rule.split("}", 1)[0]
        for scope in (
            "rec-registry.members.profile.write",
            "rec-registry.members.write",
            "rec-registry.admin",
        ):
            assert f'"{scope}"' in rule, scope
        scopes = Path("policies/celine/scopes.rego").read_text()
        assert "members" not in scopes


class TestThroughThePolicy:
    """The derivation and the Rego bundle together, on a real request.

    As in `test_authorization.TestThroughTheMiddleware`: the engine is on for
    one app and the caller's scopes are given directly. A request that passes
    the policy reaches a session dependency that answers `418`.
    """

    def _client(self, monkeypatch, scopes: str):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient
        from celine.sdk.auth import JwtUser

        from celine.rec_registry.api.admin.writes import router as writes_router
        from celine.rec_registry.core import middleware as mw
        from celine.rec_registry.db.session import get_session

        monkeypatch.setattr(mw.settings, "policies_enabled", True)
        monkeypatch.setattr(mw.settings, "policies_cache_enabled", False)

        async def as_caller(self, request):
            return JwtUser(sub="svc-example", claims={"scope": scopes})

        monkeypatch.setattr(mw.PolicyMiddleware, "_extract_user", as_caller)

        app = FastAPI()
        app.add_middleware(mw.PolicyMiddleware)
        app.include_router(writes_router, prefix="/admin")

        async def reached_the_route():
            raise HTTPException(status_code=418, detail="reached the route")
            yield  # pragma: no cover

        app.dependency_overrides[get_session] = reached_the_route
        return TestClient(app)

    BASE = "/admin/communities/example-rec/members/ex-00001"

    @pytest.mark.parametrize(
        "scope",
        [
            "rec-registry.members.profile.write",
            "rec-registry.members.write",
            "rec-registry.admin",
        ],
    )
    def test_each_of_the_three_scopes_reaches_the_profile_route(
        self, monkeypatch, scope
    ):
        """@verifies REQ-0064"""
        client = self._client(monkeypatch, scope)
        r = client.patch(f"{self.BASE}/profile", json={"role": "prosumer"})
        assert r.status_code == 418, r.text

    @pytest.mark.parametrize(
        "scope",
        [
            "rec-registry.read",
            "rec-registry.assets.write",
            "rec-registry.community.write",
            "rec-registry.members.purge",
            "rec-registry.lookup",
            "rec-registry.import",
            "rec-registry.export",
        ],
    )
    def test_no_other_scope_does(self, monkeypatch, scope):
        """@verifies REQ-0064"""
        client = self._client(monkeypatch, scope)
        r = client.patch(f"{self.BASE}/profile", json={"role": "prosumer"})
        assert r.status_code == 403, r.text

    def test_the_profile_scope_alone_reaches_no_other_write(self, monkeypatch):
        """The narrower grant is narrower in fact: not the general PATCH — which
        could rewrite `user_id`, `did` and status — and no other member, asset,
        area or community write.

        @verifies REQ-0064
        """
        client = self._client(monkeypatch, "rec-registry.members.profile.write")
        meter = {
            "key": "meter-SEN-1",
            "asset_type": "meter",
            "properties": {"name": "M", "sensor_id": "SEN-1", "meter_type": "consumption"},
        }
        refused = [
            client.patch(self.BASE, json={"role": "prosumer"}),
            client.patch(self.BASE, json={"user_id": "kc-9"}),
            client.post(
                "/admin/communities/example-rec/members",
                json=_member("ex-00002", "kc-0002"),
            ),
            client.post(f"{self.BASE}/status", json={"status": "active"}),
            client.delete(self.BASE),
            client.delete(self.BASE, params={"purge": "true"}),
            client.put(
                f"{self.BASE}/delivery-points/IT001",
                json={"id": "IT001", "type": "pod"},
            ),
            client.put(f"{self.BASE}/assets/meter-SEN-1", json=meter),
            client.delete(f"{self.BASE}/assets/meter-SEN-1"),
            client.patch("/admin/communities/example-rec", json={"name": "x"}),
            client.put(
                "/admin/communities/example-rec/areas/east", json={"name": "East"}
            ),
            client.get(self.BASE),
        ]
        assert [r.status_code for r in refused] == [403] * len(refused)

    def test_a_hostile_member_key_does_not_widen_the_profile_scope(self, monkeypatch):
        """@verifies REQ-0064"""
        client = self._client(monkeypatch, "rec-registry.members.profile.write")
        for word in ("profile", "status", "assets"):
            path = f"/admin/communities/example-rec/members/{word}"
            assert client.patch(path, json={"role": "prosumer"}).status_code == 403
            assert (
                client.patch(f"{path}/profile", json={"role": "prosumer"}).status_code
                == 418
            )


# =============================================================================
# The profile route (REQ-0070)
# =============================================================================


@pytest.mark.integration
class TestTheProfileRoute:
    async def test_it_writes_role_and_area(self, live_client):
        """@verifies REQ-0070"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")

        r = await live_client.patch(
            PROFILE.format(c=c, m="ex-00001"), json={"role": "prosumer", "area": "south"}
        )

        assert r.status_code == 200, r.text
        assert (r.json()["role"], r.json()["area"]) == ("prosumer", "south")
        stored = await _get(live_client, c, "ex-00001")
        assert (stored["role"], stored["area"]) == ("prosumer", "south")

    async def test_an_absent_field_is_left_alone(self, live_client):
        """@verifies REQ-0070"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        before = await _get(live_client, c, "ex-00001")

        r = await live_client.patch(PROFILE.format(c=c, m="ex-00001"), json={"area": "south"})
        assert r.status_code == 200, r.text
        r = await live_client.patch(
            PROFILE.format(c=c, m="ex-00001"), json={"role": "producer"}
        )
        assert r.status_code == 200, r.text

        after = await _get(live_client, c, "ex-00001")
        assert (after["role"], after["area"]) == ("producer", "south")
        for field in ("user_id", "did", "name", "status", "delivery_points", "extra"):
            assert after[field] == before[field], field

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"user_id": "kc-9"},
            {"did": "did:web:example.org:x"},
            {"status": "inactive"},
            {"name": "Someone Else"},
            {"extra": {"k": "v"}},
            {"type": "schema:Organization"},
            {"role": "prosumer", "user_id": "kc-9"},
            {"area": "south", "status": "inactive"},
            {"role": None},
            {"area": None},
            {"role": "prosumer", "unknown": 1},
        ],
    )
    async def test_it_accepts_nothing_else(self, live_client, body):
        """An empty body, a key the general PATCH accepts, an unknown key or a
        null is `422`, and the member is unchanged.

        @verifies REQ-0070
        """
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        before = await _get(live_client, c, "ex-00001")

        r = await live_client.patch(PROFILE.format(c=c, m="ex-00001"), json=body)

        assert r.status_code == 422, r.text
        assert isinstance(r.json()["detail"], list), "a validation error, not a code"
        after = await _get(live_client, c, "ex-00001")
        assert {k: v for k, v in after.items() if k != "updated_at"} == {
            k: v for k, v in before.items() if k != "updated_at"
        }

    async def test_a_role_outside_the_set_is_invalid_role(self, live_client):
        """@verifies REQ-0066"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")

        detail = _refusal(
            await live_client.patch(
                PROFILE.format(c=c, m="ex-00001"), json={"role": "owner", "area": "south"}
            ),
            422,
            "invalid_role",
        )

        assert "consumer, prosumer, producer, operator, admin" in detail
        stored = await _get(live_client, c, "ex-00001")
        assert (stored["role"], stored["area"]) == ("consumer", "north")

    async def test_an_area_the_community_lacks_is_unknown_area(self, live_client):
        """@verifies REQ-0066"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")

        detail = _refusal(
            await live_client.patch(
                PROFILE.format(c=c, m="ex-00001"), json={"role": "prosumer", "area": "east"}
            ),
            422,
            "unknown_area",
        )

        assert "north, south" in detail
        stored = await _get(live_client, c, "ex-00001")
        assert (stored["role"], stored["area"]) == ("consumer", "north")

    async def test_an_area_of_another_community_is_unknown_here(self, live_client):
        """@verifies REQ-0066"""
        c = await _community(live_client)
        other = _bundle("example-rec-b", areas=("east",))
        r = await live_client.post("/admin/import", json={"bundle": other})
        assert r.status_code == 200, r.text
        await _add(live_client, c, "ex-00001", "kc-0001")

        _refusal(
            await live_client.patch(PROFILE.format(c=c, m="ex-00001"), json={"area": "east"}),
            422,
            "unknown_area",
        )

    async def test_an_unknown_member_or_community_is_404(self, live_client):
        """@verifies REQ-0070"""
        c = await _community(live_client)

        _refusal(
            await live_client.patch(PROFILE.format(c=c, m="nobody"), json={"role": "prosumer"}),
            404,
            "member_not_found",
        )
        _refusal(
            await live_client.patch(
                PROFILE.format(c="nowhere", m="ex-00001"), json={"role": "prosumer"}
            ),
            404,
            "community_not_found",
        )

    async def test_a_role_change_keeps_the_members_assets(self, live_client):
        """A prosumer becoming a consumer keeps their meter: what the role
        changes is how its readings are settled, not what they hold.

        @verifies REQ-0070
        """
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001", role="prosumer")
        body = {
            "key": "meter-SEN-1",
            "asset_type": "meter",
            "properties": {"name": "M", "sensor_id": "SEN-1", "meter_type": "bidirectional"},
        }
        r = await live_client.put(
            f"/admin/communities/{c}/members/ex-00001/assets/meter-SEN-1", json=body
        )
        assert r.status_code == 200, r.text
        before = await live_client.get(f"/admin/communities/{c}/assets/meter-SEN-1")
        assert before.status_code == 200, before.text

        for change in ({"role": "consumer"}, {"area": "south"}, {"role": "producer"}):
            r = await live_client.patch(PROFILE.format(c=c, m="ex-00001"), json=change)
            assert r.status_code == 200, r.text

        after = await live_client.get(f"/admin/communities/{c}/assets/meter-SEN-1")
        assert after.status_code == 200, after.text
        assert {k: v for k, v in after.json().items() if k != "updated_at"} == {
            k: v for k, v in before.json().items() if k != "updated_at"
        }

    async def test_it_writes_a_member_who_is_not_active(self, live_client):
        """The route does not look at status; which members a dashboard offers
        the action for is its own policy.

        @verifies REQ-0070
        """
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001", status="suspended")

        r = await live_client.patch(PROFILE.format(c=c, m="ex-00001"), json={"area": "south"})

        assert r.status_code == 200, r.text
        assert r.json()["status"] == "suspended"


# =============================================================================
# The other write paths (REQ-0066)
# =============================================================================


@pytest.mark.integration
class TestTheOtherWritePaths:
    async def test_the_general_patch_keeps_role_and_area_with_the_same_checks(
        self, live_client
    ):
        """@verifies REQ-0066"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        path = f"/admin/communities/{c}/members/ex-00001"

        r = await live_client.patch(path, json={"role": "prosumer", "area": "south"})
        assert r.status_code == 200, r.text
        assert (r.json()["role"], r.json()["area"]) == ("prosumer", "south")

        _refusal(await live_client.patch(path, json={"role": "owner"}), 422, "invalid_role")
        _refusal(await live_client.patch(path, json={"area": "east"}), 422, "unknown_area")
        _refusal(
            await live_client.patch(path, json={"status": "retired"}), 422, "invalid_status"
        )

        stored = await _get(live_client, c, "ex-00001")
        assert (stored["role"], stored["area"], stored["status"]) == (
            "prosumer",
            "south",
            "active",
        )

    async def test_a_refused_general_patch_changes_nothing(self, live_client):
        """A patch carrying a valid name and an invalid role writes neither.

        @verifies REQ-0066
        """
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")

        _refusal(
            await live_client.patch(
                f"/admin/communities/{c}/members/ex-00001",
                json={"name": "Renamed", "area": "east"},
            ),
            422,
            "unknown_area",
        )

        assert (await _get(live_client, c, "ex-00001"))["name"] == "Example Member"

    async def test_a_patch_naming_neither_is_not_checked_against_them(self, live_client):
        """A member whose stored area predates the check can still be renamed:
        a patch checks only what it names.

        @verifies REQ-0066
        """
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")

        r = await live_client.patch(
            f"/admin/communities/{c}/members/ex-00001", json={"name": "Renamed"}
        )

        assert r.status_code == 200, r.text

    @pytest.mark.parametrize(
        "overrides,code",
        [
            ({"role": "owner"}, "invalid_role"),
            ({"role": "Consumer"}, "invalid_role"),
            ({"status": "retired"}, "invalid_status"),
            ({"area": "east"}, "unknown_area"),
        ],
    )
    async def test_create_is_held_to_the_sets(self, live_client, overrides, code):
        """@verifies REQ-0066"""
        c = await _community(live_client)

        _refusal(
            await live_client.post(
                f"/admin/communities/{c}/members",
                json=_member("ex-00001", "kc-0001", **overrides),
            ),
            422,
            code,
        )

        r = await live_client.get(f"/admin/communities/{c}/members/ex-00001")
        assert r.status_code == 404

    @pytest.mark.parametrize("role", MEMBER_ROLES)
    async def test_create_accepts_every_role(self, live_client, role):
        """@verifies REQ-0066"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001", role=role)

    async def test_a_community_with_no_areas_takes_no_member(self, live_client):
        """@verifies REQ-0066"""
        r = await live_client.post(
            "/admin/import", json={"bundle": _bundle("example-rec", areas=())}
        )
        assert r.status_code == 200, r.text

        _refusal(
            await live_client.post(
                "/admin/communities/example-rec/members", json=_member("ex-00001", "kc-0001")
            ),
            422,
            "unknown_area",
        )

    async def test_the_status_route_is_held_to_its_set(self, live_client):
        """@verifies REQ-0066"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")

        _refusal(
            await live_client.post(
                f"/admin/communities/{c}/members/ex-00001/status",
                json={"status": "retired"},
            ),
            422,
            "invalid_status",
        )


# =============================================================================
# An area deleted while a member is moved into it (REQ-0066)
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
    raise AssertionError(f"no backend ever waited on pid {holder_pid}")


@pytest.mark.integration
class TestAnAreaDeletedMeanwhile:
    """Deleting an area refuses while a member references it (REQ-0030); a
    member write names an area that exists (REQ-0066). Each is checked against
    rows the other has not committed yet, so without the community row lock
    both would pass and leave a member in an area that does not exist.

    The first writer is held open deliberately, as in `TestTwoWritersAtOnce`.
    """

    async def test_a_delete_waits_for_a_member_moving_in_and_then_refuses(
        self, live_client, pg_engine
    ):
        """@verifies REQ-0066"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        maker = async_sessionmaker(pg_engine, expire_on_commit=False)

        async with maker() as holder:
            holder_pid = await holder.scalar(text("select pg_backend_pid()"))
            community = await member_service.resolve_community(holder, c)
            await member_service.lock_community(holder, community, share=True)
            member = await member_service.resolve_member(holder, community, "ex-00001")
            member.area = "south"
            await holder.flush()

            request = asyncio.create_task(
                live_client.delete(f"/admin/communities/{c}/areas/south")
            )
            await _wait_until_blocked(pg_engine, holder_pid)
            await holder.commit()
            r = await request

        _refusal(r, 409, "area_in_use")
        assert (await _get(live_client, c, "ex-00001"))["area"] == "south"

    async def test_a_member_write_waits_for_a_delete_and_then_refuses(
        self, live_client, pg_engine
    ):
        """@verifies REQ-0066"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        maker = async_sessionmaker(pg_engine, expire_on_commit=False)

        async with maker() as holder:
            holder_pid = await holder.scalar(text("select pg_backend_pid()"))
            community = await member_service.resolve_community(holder, c)
            await member_service.lock_community(holder, community, share=False)
            community.areas = {
                k: v for k, v in (community.areas or {}).items() if k != "south"
            }
            await holder.flush()

            request = asyncio.create_task(
                live_client.patch(
                    PROFILE.format(c=c, m="ex-00001"), json={"area": "south"}
                )
            )
            await _wait_until_blocked(pg_engine, holder_pid)
            await holder.commit()
            r = await request

        _refusal(r, 422, "unknown_area")
        assert (await _get(live_client, c, "ex-00001"))["area"] == "north"


# =============================================================================
# The bundle import refuses (REQ-0066, REQ-0074)
# =============================================================================


@pytest.mark.integration
class TestTheImportRefuses:
    @pytest.mark.parametrize(
        "overrides,code",
        [
            ({"role": "owner"}, "invalid_role"),
            ({"status": "retired"}, "invalid_status"),
            ({"area": "east"}, "unknown_area"),
        ],
    )
    async def test_an_out_of_set_member_refuses_the_whole_bundle(
        self, live_client, overrides, code
    ):
        """Nothing is written: not the community, not the valid member beside
        the invalid one.

        @verifies REQ-0066
        """
        bundle = _bundle(
            "example-rec",
            {
                "ex-00001": _bundle_member("kc-0001"),
                "ex-00002": _bundle_member("kc-0002", **overrides),
            },
        )

        detail = _refusal(
            await live_client.post("/admin/import", json={"bundle": bundle}), 422, code
        )

        assert "'ex-00002'" in detail
        r = await live_client.get("/admin/communities/example-rec")
        assert r.status_code == 404

    async def test_a_refused_reimport_leaves_the_live_community_alone(self, live_client):
        """@verifies REQ-0066"""
        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        bundle = _bundle(c, {"ex-00001": _bundle_member("kc-0001", area="east")})

        _refusal(
            await live_client.post("/admin/import", json={"bundle": bundle, "force": True}),
            422,
            "unknown_area",
        )

        assert (await _get(live_client, c, "ex-00001"))["area"] == "north"

    async def test_the_area_must_be_one_of_the_bundles_own(self, live_client):
        """The bundle replaces the community, so its own areas are the ones
        that count — not the ones the registry holds now.

        @verifies REQ-0066
        """
        c = await _community(live_client)
        bundle = _bundle(c, {"ex-00001": _bundle_member("kc-0001", area="north")}, areas=("south",))

        _refusal(
            await live_client.post("/admin/import", json={"bundle": bundle, "force": True}),
            422,
            "unknown_area",
        )

    async def test_the_yaml_route_refuses_the_same_way(self, live_client):
        """@verifies REQ-0066"""
        bundle = _bundle("example-rec", {"ex-00001": _bundle_member("kc-0001", role="owner")})

        r = await live_client.post(
            "/admin/import/yaml",
            content=yaml.safe_dump(bundle),
            headers={"content-type": "application/yaml"},
        )

        _refusal(r, 422, "invalid_role")
        assert (await live_client.get("/admin/communities/example-rec")).status_code == 404

    async def test_a_dry_run_lists_every_refusal(self, live_client):
        """@verifies REQ-0034"""
        bundle = _bundle(
            "example-rec",
            {
                "ex-00001": _bundle_member("kc-0001", role="owner", area="east"),
                "ex-00002": _bundle_member("kc-0002", status="retired"),
                "ex-00003": _bundle_member("kc-0003"),
            },
        )

        r = await live_client.post("/admin/import", json={"bundle": bundle, "dry_run": True})

        assert r.status_code == 200, r.text
        refusals = [(x["code"], x["detail"].split(":")[0]) for x in r.json()["refusals"]]
        assert refusals == [
            ("invalid_role", "member 'ex-00001'"),
            ("unknown_area", "member 'ex-00001'"),
            ("invalid_status", "member 'ex-00002'"),
        ]
        assert (await live_client.get("/admin/communities/example-rec")).status_code == 404

    async def test_a_valid_bundle_with_every_role_and_status_imports(self, live_client):
        """@verifies REQ-0066"""
        members = {
            f"ex-{i:05d}": _bundle_member(
                f"kc-{i:04d}",
                role=MEMBER_ROLES[i % len(MEMBER_ROLES)],
                status=MEMBER_STATUSES[i % len(MEMBER_STATUSES)],
                area=("north", "south")[i % 2],
            )
            for i in range(1, 11)
        }

        r = await live_client.post("/admin/import", json={"bundle": _bundle("example-rec", members)})

        assert r.status_code == 200, r.text
        assert r.json()["inserted"]["member"] == 10


# =============================================================================
# The OpenAPI document
# =============================================================================


class TestTheOpenApiDocument:
    def test_the_profile_route_is_documented(self):
        """The SDK is generated from this document.

        @verifies REQ-0070
        """
        from celine.rec_registry.main import create_app

        doc = create_app().openapi()
        op = doc["paths"][
            "/admin/communities/{community_key}/members/{member_key}/profile"
        ]["patch"]

        ref = op["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        body = doc["components"]["schemas"][ref.rsplit("/", 1)[1]]
        assert set(body["properties"]) == {"role", "area"}
        assert body["additionalProperties"] is False
        assert body["minProperties"] == 1

        assert op["responses"]["200"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/MemberDetail"
        }
        assert op["responses"]["404"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }
        assert op["responses"]["422"]["content"]["application/json"]["schema"] == {
            "oneOf": [
                {"$ref": "#/components/schemas/ErrorResponse"},
                {"$ref": "#/components/schemas/HTTPValidationError"},
            ]
        }

    def test_the_profile_body_does_not_advertise_null(self):
        """Both fields are optional, but the route refuses `null` with a `422`,
        so the published schema must not offer `null` to a generated client.

        @verifies REQ-0070
        """
        from celine.rec_registry.main import create_app

        doc = create_app().openapi()
        body = doc["components"]["schemas"]["MemberProfilePatch"]
        assert body.get("required", []) == []
        for name in ("role", "area"):
            prop = body["properties"][name]
            assert "anyOf" not in prop, prop
            assert prop["type"] == "string"
            assert "default" not in prop

    def test_the_new_codes_are_in_the_enum(self):
        """@verifies REQ-0073"""
        from celine.rec_registry.main import create_app

        codes = create_app().openapi()["components"]["schemas"]["ErrorCode"]["enum"]
        assert {"invalid_role", "invalid_status", "unknown_area"} <= set(codes)


# =============================================================================
# The report of values already out of set (REQ-0077)
# =============================================================================


def _export_doc(community: str, areas, members: dict) -> dict:
    return {
        "community": {
            "id": community,
            "name": community,
            "areas": {a: {"name": a} for a in areas},
        },
        "members": members,
    }


def _exported_member(**overrides) -> dict:
    member = {"user_id": "kc-x", "name": "N", "role": "consumer", "area": "north", "status": "active"}
    member.update(overrides)
    return member


class TestFindOutOfSetValues:
    def test_each_field_is_one_line(self):
        """@verifies REQ-0077"""
        from celine.rec_registry.cli.main import find_out_of_set_values

        docs = [
            _export_doc(
                "example-rec-a",
                ["north"],
                {
                    "ex-00001": _exported_member(),
                    "ex-00002": _exported_member(role="owner", area="east"),
                },
            ),
            _export_doc(
                "example-rec-b",
                ["south"],
                {"ex-00009": _exported_member(status="retired", area="south")},
            ),
        ]

        assert find_out_of_set_values(docs) == [
            ("example-rec-a", "ex-00002", "area", "east"),
            ("example-rec-a", "ex-00002", "role", "owner"),
            ("example-rec-b", "ex-00009", "status", "retired"),
        ]

    def test_an_area_is_judged_against_its_own_community(self):
        """@verifies REQ-0077"""
        from celine.rec_registry.cli.main import find_out_of_set_values

        docs = [
            _export_doc("example-rec-a", ["north"], {}),
            _export_doc("example-rec-b", ["south"], {"ex-00001": _exported_member()}),
        ]

        assert find_out_of_set_values(docs) == [
            ("example-rec-b", "ex-00001", "area", "north")
        ]

    def test_a_missing_field_is_reported_as_missing(self):
        """@verifies REQ-0077"""
        from celine.rec_registry.cli.main import find_out_of_set_values

        member = _exported_member()
        del member["role"]
        docs = [_export_doc("example-rec", ["north"], {"ex-00001": member})]

        assert find_out_of_set_values(docs) == [
            ("example-rec", "ex-00001", "role", "<missing>")
        ]

    def test_a_clean_export_reports_nothing(self):
        """@verifies REQ-0077"""
        from celine.rec_registry.cli.main import find_out_of_set_values

        docs = [
            _export_doc(
                "example-rec",
                ["north", "south"],
                {
                    f"ex-{i:05d}": _exported_member(role=role, status=status, area="south")
                    for i, (role, status) in enumerate(zip(MEMBER_ROLES, MEMBER_STATUSES * 2))
                },
            )
        ]

        assert find_out_of_set_values(docs) == []


HTTPX_POST = "celine.rec_registry.cli.main.httpx.post"
HTTPX_GET = "celine.rec_registry.cli.main.httpx.get"


class TestOutOfSetValuesCommand:
    def _run(self, body: str, status: int = 200):
        from celine.rec_registry.cli.main import app

        resp = MagicMock()
        resp.status_code = status
        resp.text = body
        get = MagicMock(return_value=resp)
        post = MagicMock()
        with patch(HTTPX_GET, get), patch(HTTPX_POST, post):
            result = CliRunner().invoke(app, ["out-of-set-values", "--token", "fake-jwt-token"])
        return result, get, post

    def test_a_clean_registry_exits_zero(self):
        """@verifies REQ-0077"""
        body = yaml.safe_dump(
            _export_doc("example-rec", ["north"], {"ex-00001": _exported_member()})
        )
        result, _, _ = self._run(body)

        assert result.exit_code == 0, result.output
        assert "in set" in result.output

    def test_out_of_set_values_are_listed_and_exit_non_zero(self):
        """@verifies REQ-0077"""
        body = yaml.safe_dump_all(
            [
                _export_doc("example-rec-a", ["north"], {"ex-00001": _exported_member(role="owner")}),
                _export_doc("example-rec-b", ["north"], {"ex-00009": _exported_member(area="east")}),
            ]
        )
        result, _, _ = self._run(body)

        assert result.exit_code == 1, result.output
        assert "community\tmember\tfield\tvalue" in result.output
        assert "example-rec-a\tex-00001\trole\towner" in result.output
        assert "example-rec-b\tex-00009\tarea\teast" in result.output

    def test_it_prints_no_name_or_user_id(self):
        """Only keys and the offending vocabulary: the report is pasted into
        tickets.

        @verifies REQ-0077
        """
        member = _exported_member(role="owner", name="Somebody Named", user_id="kc-someone")
        body = yaml.safe_dump(_export_doc("example-rec", ["north"], {"ex-00001": member}))
        result, _, _ = self._run(body)

        assert result.exit_code == 1
        assert "Somebody Named" not in result.output
        assert "kc-someone" not in result.output

    def test_it_only_reads_the_export(self):
        """One GET of `/admin/export`, no other request.

        @verifies REQ-0077
        """
        result, get, post = self._run("")

        assert result.exit_code == 0, result.output
        get.assert_called_once()
        assert get.call_args.args[0].endswith("/admin/export")
        assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer fake-jwt-token"
        post.assert_not_called()

    def test_an_unreadable_registry_is_not_reported_as_clean(self):
        """@verifies REQ-0077"""
        result, _, _ = self._run('{"detail": "Forbidden"}', status=403)

        assert result.exit_code == 2


@pytest.mark.integration
class TestTheReportAgainstAnExport:
    async def test_a_live_export_of_valid_members_is_clean(self, live_client):
        """The report reads what `GET /admin/export` really answers.

        @verifies REQ-0077
        """
        from celine.rec_registry.cli.main import find_out_of_set_values

        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001", role="prosumer", area="south")

        exported = await live_client.get("/admin/export", params={"community": c})
        assert exported.status_code == 200, exported.text

        assert find_out_of_set_values(list(yaml.safe_load_all(exported.text))) == []

    async def test_a_row_written_before_the_check_is_found(self, live_client, pg_engine):
        """@verifies REQ-0077"""
        from celine.rec_registry.cli.main import find_out_of_set_values

        c = await _community(live_client)
        await _add(live_client, c, "ex-00001", "kc-0001")
        async with pg_engine.begin() as conn:
            await conn.execute(
                text("update member set role = 'owner', area = 'east' where key = 'ex-00001'")
            )

        exported = await live_client.get("/admin/export", params={"community": c})

        assert find_out_of_set_values(list(yaml.safe_load_all(exported.text))) == [
            (c, "ex-00001", "area", "east"),
            (c, "ex-00001", "role", "owner"),
        ]
