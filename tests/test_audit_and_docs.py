"""Refusals leave a record naming the caller; the API documentation is a dev convenience.

The refusals are read back off the `celine.audit` logger the way a log pipeline would
select them: one JSON object per line. Token verification is not under test — the
caller is handed to the middleware directly, as `test_authorization.py` does.
"""

from __future__ import annotations

import json
import logging

import pytest
from celine.sdk.auth import JwtUser
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

# Imported for its side effect too: `main` names the service on every audit record.
from celine.rec_registry import main as main_module
from celine.rec_registry.core import middleware as mw
from celine.rec_registry.db.session import get_session

EMAIL = "manager@example.org"
NAME = "Example Manager"
CALLER = JwtUser(
    sub="ex-00001-sub",
    email=EMAIL,
    name=NAME,
    preferred_username="ex-00001",
    claims={
        "sub": "ex-00001-sub",
        "azp": "svc-example",
        "email": EMAIL,
        "name": NAME,
        "preferred_username": "ex-00001",
        "scope": "rec-registry.lookup",
    },
)
ASSET = "/admin/communities/example-rec/members/m1/assets/meter-sensor-01"
BODY = {
    "key": "meter-sensor-01",
    "asset_type": "meter",
    "properties": {"name": "M", "sensor_id": "sensor-01", "meter_type": "consumption"},
}


def denials(caplog) -> list[dict]:
    return [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name == "celine.audit" and r.levelno == logging.WARNING
    ]


def assert_no_personal_data(caplog) -> None:
    text = "\n".join(r.getMessage() for r in caplog.records if r.name == "celine.audit")
    for value in (EMAIL, NAME, "m1", "sensor-01"):
        assert value not in text


def _admin_client(monkeypatch, caller: JwtUser | None) -> TestClient:
    from celine.rec_registry.api.admin.writes import router as writes_router

    monkeypatch.setattr(mw.settings, "policies_enabled", True)
    monkeypatch.setattr(mw.settings, "policies_cache_enabled", False)

    async def as_caller(self, request):
        return caller

    monkeypatch.setattr(mw.PolicyMiddleware, "_extract_user", as_caller)

    app = FastAPI()
    app.add_middleware(mw.PolicyMiddleware)
    app.include_router(writes_router, prefix="/admin")

    async def reached_the_route():
        raise HTTPException(status_code=418, detail="reached the route")
        yield  # pragma: no cover

    app.dependency_overrides[get_session] = reached_the_route
    return TestClient(app)


class TestRefusalsAreRecorded:
    def test_an_admin_refusal_names_the_caller_and_the_community(self, monkeypatch, caplog):
        """@verifies REQ-0091"""
        client = _admin_client(monkeypatch, CALLER)

        with caplog.at_level(logging.INFO, logger="celine.audit"):
            r = client.put(ASSET, json=BODY)

        assert r.status_code == 403
        [record] = denials(caplog)
        assert record["event"] == "denied"
        assert record["outcome"] == "denied"
        assert record["service"] == "rec-registry"
        assert record["action"] == "rec-registry.assets.write"
        assert record["sub"] == "ex-00001-sub"
        assert record["client_id"] == "svc-example"
        assert record["method"] == "PUT"
        assert record["resource"] == "example-rec"
        assert record["reason"] == "missing required scope"
        assert_no_personal_data(caplog)

    def test_an_admitted_admin_request_records_no_refusal(self, monkeypatch, caplog):
        """@verifies REQ-0091"""
        granted = JwtUser(sub="svc", claims={"sub": "svc", "scope": "rec-registry.assets.write"})
        client = _admin_client(monkeypatch, granted)

        with caplog.at_level(logging.INFO, logger="celine.audit"):
            r = client.put(ASSET, json=BODY)

        assert r.status_code == 418
        assert denials(caplog) == []

    @pytest.mark.parametrize("path", [ASSET, "/user/member"])
    def test_a_presented_token_that_does_not_verify_is_recorded_without_a_caller(
        self, monkeypatch, caplog, path
    ):
        """@verifies REQ-0091"""
        client = _admin_client(monkeypatch, None)

        with caplog.at_level(logging.INFO, logger="celine.audit"):
            r = client.put(path, json=BODY, headers={"authorization": "Bearer not-a-jwt"})

        assert r.status_code == 401
        [record] = denials(caplog)
        assert record["sub"] is None
        assert record["client_id"] is None
        assert record["reason"] == "token_rejected"
        expected = "rec-registry.assets.write" if path == ASSET else "rec-registry.user"
        assert record["action"] == expected

    def test_an_admin_refusal_names_the_route_template_not_the_path(self, monkeypatch, caplog):
        """@verifies REQ-0091"""
        client = _admin_client(monkeypatch, CALLER)

        with caplog.at_level(logging.INFO, logger="celine.audit"):
            r = client.put(ASSET, json=BODY)

        assert r.status_code == 403
        [record] = denials(caplog)
        assert record["route"] == (
            "/admin/communities/{community_key}/members/{member_key}/assets/{asset_key}"
        )
        assert_no_personal_data(caplog)

    @pytest.mark.parametrize(
        ("method", "path", "route"),
        [
            (
                "PUT",
                ASSET,
                "/admin/communities/{community_key}/members/{member_key}/assets/{asset_key}",
            ),
            ("GET", "/user/assets/meter-sensor-01", "/user/assets/{asset_key}"),
            # Served for GET only: the router answers 405, the record still names it.
            ("PUT", "/user/member", "/user/member"),
            # No route serves it: no template to name, and never the raw path.
            ("GET", "/user/ex-00001", None),
            ("PUT", "/admin/communities/example-rec/ex-00001", None),
        ],
    )
    def test_a_rejected_token_names_the_route_template(
        self, monkeypatch, caplog, method, path, route
    ):
        """@verifies REQ-0091"""
        from celine.rec_registry.api.user import router as user_router

        client = _admin_client(monkeypatch, None)
        client.app.include_router(user_router)

        with caplog.at_level(logging.INFO, logger="celine.audit"):
            r = client.request(
                method, path, json=BODY, headers={"authorization": "Bearer not-a-jwt"}
            )

        assert r.status_code == 401
        [record] = denials(caplog)
        assert record["method"] == method
        assert record["route"] == route
        assert "ex-00001" not in json.dumps(record)
        assert_no_personal_data(caplog)

    @pytest.mark.parametrize(
        ("path", "resource"), [(ASSET, "example-rec"), ("/user/member", None)]
    )
    def test_a_rejected_token_names_the_community_of_the_path(
        self, monkeypatch, caplog, path, resource
    ):
        """@verifies REQ-0091"""
        client = _admin_client(monkeypatch, None)

        with caplog.at_level(logging.INFO, logger="celine.audit"):
            r = client.put(path, json=BODY, headers={"authorization": "Bearer not-a-jwt"})

        assert r.status_code == 401
        [record] = denials(caplog)
        assert record["resource"] == resource
        assert_no_personal_data(caplog)

    def test_no_token_at_all_records_nothing(self, monkeypatch, caplog):
        """@verifies REQ-0091"""
        client = _admin_client(monkeypatch, None)

        with caplog.at_level(logging.INFO, logger="celine.audit"):
            r = client.put(ASSET, json=BODY)

        assert r.status_code == 401
        assert denials(caplog) == []

    @pytest.mark.parametrize(
        ("path", "route"),
        [
            ("/user/member", "/user/member"),
            ("/user/community", "/user/community"),
            ("/user/assets", "/user/assets"),
            ("/user/assets/meter-sensor-01", "/user/assets/{asset_key}"),
            ("/user/delivery-points", "/user/delivery-points"),
        ],
    )
    def test_not_a_member_is_recorded_with_the_caller(
        self, mock_session, caplog, path, route
    ):
        """@verifies REQ-0091"""
        # `/user/community` reads a joined row; no row is what a non-member gets.
        mock_session.execute.return_value.first.return_value = None
        from celine.rec_registry.api.user import router as user_router
        from celine.rec_registry.core.errors import install_error_handlers
        from celine.rec_registry.core.middleware import require_user

        app = FastAPI()
        install_error_handlers(app)
        app.include_router(user_router)

        async def override_session():
            yield mock_session

        async def override_user():
            return CALLER

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[require_user] = override_user

        with caplog.at_level(logging.INFO, logger="celine.audit"):
            r = TestClient(app).get(path)

        assert r.status_code == 403
        assert r.json()["code"] == "not_a_member"
        [record] = denials(caplog)
        assert record["action"] == "rec-registry.user.read"
        assert record["sub"] == "ex-00001-sub"
        assert record["route"] == route
        assert record["reason"] == "not_a_member"
        assert_no_personal_data(caplog)


DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


def _statuses() -> dict[str, int]:
    client = TestClient(main_module.create_app())
    return {path: client.get(path).status_code for path in (*DOC_PATHS, "/health")}


class TestDocumentation:
    def test_outside_dev_the_documentation_is_not_mounted(self, monkeypatch):
        """@verifies REQ-0092"""
        # Outside dev the startup guard refuses the suite's dev switches; it is not
        # what is under test here.
        monkeypatch.setattr(main_module, "enforce_posture", lambda settings: None)
        monkeypatch.setenv("CELINE_ENV", "staging")
        monkeypatch.delenv("CELINE_PUBLIC_DOCS", raising=False)

        statuses = _statuses()

        assert {p: statuses[p] for p in DOC_PATHS} == {p: 404 for p in DOC_PATHS}
        assert statuses["/health"] == 200

    def test_outside_dev_the_documentation_can_be_published_on_purpose(self, monkeypatch):
        """@verifies REQ-0092"""
        monkeypatch.setattr(main_module, "enforce_posture", lambda settings: None)
        monkeypatch.setenv("CELINE_ENV", "staging")
        monkeypatch.setenv("CELINE_PUBLIC_DOCS", "true")

        assert all(_statuses()[p] == 200 for p in DOC_PATHS)

    def test_in_dev_the_documentation_is_served(self, monkeypatch):
        """@verifies REQ-0092"""
        monkeypatch.setenv("CELINE_ENV", "dev")
        monkeypatch.delenv("CELINE_PUBLIC_DOCS", raising=False)

        assert all(_statuses()[p] == 200 for p in DOC_PATHS)

    def test_the_schema_is_still_generated_outside_dev(self, monkeypatch):
        """`../celine-sdk` and the schema tests read `app.openapi()`, not the route.

        @verifies REQ-0092
        """
        monkeypatch.setattr(main_module, "enforce_posture", lambda settings: None)
        monkeypatch.setenv("CELINE_ENV", "staging")
        monkeypatch.delenv("CELINE_PUBLIC_DOCS", raising=False)

        assert "/user/member" in main_module.create_app().openapi()["paths"]
