"""The mirror export: the member export plus the account subject, for the member mirrors.

`GET /admin/export/mirror` answers what `GET /admin/export/members` answers and, per
member, its account `subject` (REQ-0101) — nothing else that names a member. An
intermediate environment's mirror job reads it from prod to recreate each member's
account under the same `sub` (REQ-0103). It has an action and a scope of its own,
`mirror` and `rec-registry.mirror`: the pipelines hold `rec-registry.export` and must
not reach the subject through it, and the mirror job must not reach the full export.

Synthetic values only: placeholder e-mails, PODs and substation codes.
"""

from __future__ import annotations

import pytest

from celine.rec_registry.core.middleware import PolicyMiddleware
from tests.test_member_export import PERSONAL, _seed

action = PolicyMiddleware._get_admin_action

ROUTE = "/admin/export/mirror"
SUBJECT = "0b6f6c3e-8d2a-4c41-9f0e-5a7d2c1b9e10"


class TestTheRouteHasItsOwnAction:
    def test_reading_it_is_the_mirror_action(self):
        """@verifies REQ-0103"""
        assert action(None, ROUTE, "GET") == "mirror"

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_any_other_method_derives_admin(self, method):
        """@verifies REQ-0103"""
        assert action(None, ROUTE, method) == "admin"

    @pytest.mark.parametrize("word", ["members", "mirror", "export", "x"])
    def test_a_longer_path_derives_admin(self, word):
        """@verifies REQ-0103"""
        assert action(None, f"{ROUTE}/{word}", "GET") == "admin"

    def test_the_member_export_keeps_the_export_action(self):
        """@verifies REQ-0103"""
        assert action(None, "/admin/export/members", "GET") == "export.members"

    def test_the_policy_has_a_rule_for_it(self):
        """@verifies REQ-0103"""
        from pathlib import Path

        rego = Path("policies/celine/rec_registry/access.rego").read_text()
        assert 'input.action.name == "mirror"' in rego


class TestOnlyTheMirrorGrantReachesIt:
    """Through the middleware and the real policy bundle, with the session
    replaced by a dependency that answers 418 once the route is reached."""

    def _client(self, monkeypatch, scopes: str):
        from celine.sdk.auth import JwtUser
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient

        from celine.rec_registry.api.admin.management import router
        from celine.rec_registry.core import middleware as mw
        from celine.rec_registry.db.session import get_session

        monkeypatch.setattr(mw.settings, "policies_enabled", True)
        monkeypatch.setattr(mw.settings.policies, "policies_cache_enabled", False)

        async def as_caller(self, request):
            return JwtUser(sub="svc-example", claims={"scope": scopes})

        monkeypatch.setattr(mw.PolicyMiddleware, "_extract_user", as_caller)

        app = FastAPI()
        app.add_middleware(mw.PolicyMiddleware)
        app.include_router(router, prefix="/admin")

        async def reached_the_route():
            raise HTTPException(status_code=418, detail="reached the route")
            yield  # pragma: no cover

        app.dependency_overrides[get_session] = reached_the_route
        return TestClient(app)

    @pytest.mark.parametrize("scope", ["rec-registry.mirror", "rec-registry.admin"])
    def test_the_mirror_scope_reaches_it(self, monkeypatch, scope):
        """@verifies REQ-0103"""
        r = self._client(monkeypatch, scope).get(ROUTE)
        assert r.status_code == 418, r.text

    @pytest.mark.parametrize(
        "scope",
        [
            "rec-registry.export",
            "rec-registry.read",
            "rec-registry.lookup",
            "rec-registry.import",
            "rec-registry.members.write",
        ],
    )
    def test_no_other_scope_does(self, monkeypatch, scope):
        """The pipelines' `rec-registry.export` in particular.

        @verifies REQ-0103
        """
        r = self._client(monkeypatch, scope).get(ROUTE)
        assert r.status_code == 403, r.text

    @pytest.mark.parametrize("route", ["/admin/export", "/admin/export/members"])
    def test_the_mirror_scope_reaches_no_other_export(self, monkeypatch, route):
        """@verifies REQ-0103"""
        r = self._client(monkeypatch, "rec-registry.mirror").get(route)
        assert r.status_code == 403, r.text


@pytest.mark.integration
class TestTheMirrorExport:
    async def test_it_is_the_member_export_plus_the_subject(self, live_client):
        """@verifies REQ-0103"""
        key = await _seed(live_client)

        members = (await live_client.get("/admin/export/members")).json()
        r = await live_client.get(ROUTE)

        assert r.status_code == 200, r.text
        expected = members["communities"][0]
        expected["members"][0]["subject"] = SUBJECT
        expected["members"][1]["subject"] = None
        assert r.json() == {"communities": [expected]}
        assert expected["community"] == key

    async def test_no_personal_value_but_the_subject_reaches_it(self, live_client):
        """@verifies REQ-0103"""
        await _seed(live_client)

        r = await live_client.get(ROUTE)

        assert r.status_code == 200, r.text
        assert [v for v in PERSONAL if v in r.text] == [SUBJECT]

    async def test_a_community_can_be_named_and_an_unknown_one_is_404(self, live_client):
        """@verifies REQ-0103"""
        await _seed(live_client, "export-rec")
        await _seed(live_client, "other-rec", members=False)

        r = await live_client.get(ROUTE, params={"community": "other-rec"})
        assert r.status_code == 200, r.text
        assert [c["community"] for c in r.json()["communities"]] == ["other-rec"]

        r = await live_client.get(ROUTE, params={"community": "no-such-rec"})
        assert r.status_code == 404
