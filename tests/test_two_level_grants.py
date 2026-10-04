"""No group and no realm role decides an `/admin` request (REQ-0090).

The platform has two levels of grant: the realm role `platform-admin`, the only
platform-wide one, and an organisation's own groups, valid only inside that
organisation. This service reads neither: `access.rego` decides on scopes, and the
subject the middleware builds carries no group. Before celine-sdk 2.0.0 it carried
`extract_groups`' merge of the realm's groups with every organisation's, so any rule
reading `input.subject.groups` would have let one community's group act as a platform
group, or as the same group in another community.

Two layers here:

- **hand-built claims** in every shape a token can take — the retired realm group in
  both its forms, an organisation's `admins`, the `platform-admin` role, a group named
  like a grant — through the middleware with the policy engine on;
- **real tokens** from the local Keycloak (`keycloak` marker), verified by the
  middleware itself, not patched. They skip when no local Keycloak answers; say which
  of the two ran.

`418` means "past the policy check": the route's session dependency is replaced so
nothing touches a database.
"""

from __future__ import annotations

import os

import httpx
import pytest

# The retired realm-group token, as the old `oauth2_proxy` issued it: both forms of
# the group (realm `groups` scope mapper and client-level mapper), the realm role the
# old `/admins` group mapped onto, and an organisation's `admins` beside it.
LEGACY_REALM_ADMIN = {
    "azp": "oauth2_proxy",
    "preferred_username": "legacy-admin",
    "groups": ["/admins", "admins"],
    "realm_access": {"roles": ["admin"]},
    "organization": {"example-rec": {"type": ["rec"], "groups": ["/admins"]}},
}
# A platform administrator: the realm role, and no registry scope.
PLATFORM_ADMIN = {
    "azp": "oauth2_proxy",
    "preferred_username": "admin",
    "realm_access": {"roles": ["platform-admin"]},
    "organization": {"example_rec": {"type": ["rec"], "groups": ["/admins"]}},
}
# An organisation's `admins` member who is not a platform administrator.
ORG_ADMIN = {
    "azp": "oauth2_proxy",
    "preferred_username": "org-admin",
    "realm_access": {
        "roles": ["default-roles-celine", "offline_access", "uma_authorization"]
    },
    "organization": {"example_rec": {"type": ["rec"], "groups": ["/admins"]}},
}
# Groups named like this service's grants, at each level. The merge would have put
# both into `input.subject.groups`.
ORG_GROUP_NAMED_LIKE_A_GRANT = {
    "preferred_username": "org-operator",
    "organization": {
        "example-rec": {"type": ["rec"], "groups": ["/rec-registry.admin"]}
    },
}
REALM_GROUP_NAMED_LIKE_A_GRANT = {
    "preferred_username": "realm-operator",
    "groups": ["/rec-registry.admin", "rec-registry.admin"],
    "realm_access": {"roles": ["rec-registry.admin"]},
}

SHAPES = {
    "legacy realm /admins": LEGACY_REALM_ADMIN,
    "platform-admin role": PLATFORM_ADMIN,
    "organisation admins": ORG_ADMIN,
    "organisation group named rec-registry.admin": ORG_GROUP_NAMED_LIKE_A_GRANT,
    "realm group and role named rec-registry.admin": REALM_GROUP_NAMED_LIKE_A_GRANT,
}

READ = ("GET", "/admin/communities", None)
ASSET_WRITE = (
    "PUT",
    "/admin/communities/rec-a/members/m1/assets/meter-01",
    {
        "key": "meter-01",
        "asset_type": "meter",
        "properties": {"name": "M", "sensor_id": "01", "meter_type": "consumption"},
    },
)
PURGE = ("DELETE", "/admin/communities/rec-a/members/m1?purge=true", None)
IMPORT = ("POST", "/admin/import", {})
EVERY = {"read": READ, "asset write": ASSET_WRITE, "purge": PURGE, "import": IMPORT}


def _client(monkeypatch, claims: dict | None = None):
    """An app with the policy engine on, recording every subject it asks about.

    With `claims`, the caller is a token with those claims (verification is not
    under test). Without, the middleware verifies the bearer token itself.
    """
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from celine.sdk.auth import JwtUser

    from celine.rec_registry.api.admin.communities import router as communities_router
    from celine.rec_registry.api.admin.management import router as management_router
    from celine.rec_registry.api.admin.writes import router as writes_router
    from celine.rec_registry.core import middleware as mw
    from celine.rec_registry.db.session import get_session

    monkeypatch.setattr(mw.settings, "policies_enabled", True)
    monkeypatch.setattr(mw.settings, "policies_cache_enabled", False)

    if claims is not None:

        async def as_caller(self, request):
            return JwtUser(
                sub="sub-unused",
                preferred_username=claims.get("preferred_username"),
                claims=claims,
            )

        monkeypatch.setattr(mw.PolicyMiddleware, "_extract_user", as_caller)

    seen: list = []
    real_input = mw.PolicyInput

    def recording_input(*args, **kwargs):
        built = real_input(*args, **kwargs)
        seen.append(built)
        return built

    monkeypatch.setattr(mw, "PolicyInput", recording_input)

    app = FastAPI()
    app.add_middleware(mw.PolicyMiddleware)
    app.include_router(communities_router, prefix="/admin")
    app.include_router(writes_router, prefix="/admin")
    app.include_router(management_router, prefix="/admin")

    async def reached_the_route():
        raise HTTPException(status_code=418, detail="reached the route")
        yield  # pragma: no cover

    app.dependency_overrides[get_session] = reached_the_route
    return TestClient(app), seen


def _send(client, request, headers=None):
    method, path, body = request
    return client.request(method, path, json=body, headers=headers)


# =============================================================================
# Hand-built claims
# =============================================================================


class TestNoGroupReachesTheDecision:
    @pytest.mark.parametrize("shape", sorted(SHAPES))
    @pytest.mark.parametrize("name", sorted(EVERY))
    def test_without_a_scope_every_shape_is_refused(self, monkeypatch, shape, name):
        """A group or a realm role, at any level and with any name, grants nothing.

        @verifies REQ-0090
        """
        client, seen = _client(monkeypatch, SHAPES[shape])
        r = _send(client, EVERY[name])
        assert r.status_code == 403, (shape, name, r.status_code, r.text)
        assert len(seen) == 1

    @pytest.mark.parametrize("shape", sorted(SHAPES))
    def test_the_subject_carries_no_group(self, monkeypatch, shape):
        """@verifies REQ-0090"""
        client, seen = _client(monkeypatch, SHAPES[shape])
        _send(client, READ)
        (policy_input,) = seen
        assert policy_input.subject.groups == []

    @pytest.mark.parametrize("shape", sorted(SHAPES))
    def test_a_scope_reaches_exactly_what_it_reached_before(self, monkeypatch, shape):
        """The same claims plus `rec-registry.read`: reads pass, nothing else does.

        @verifies REQ-0090
        """
        claims = {**SHAPES[shape], "scope": "openid rec-registry.read"}
        client, seen = _client(monkeypatch, claims)
        assert _send(client, READ).status_code == 418
        for name in ("asset write", "purge", "import"):
            r = _send(client, EVERY[name])
            assert r.status_code == 403, (shape, name, r.status_code)
        assert all(p.subject.groups == [] for p in seen)

    def test_the_sdk_tells_the_two_levels_apart_and_nothing_here_reads_either(self):
        """The fixtures are what they claim to be, by the SDK's own reading.

        @verifies REQ-0090
        """
        from celine.sdk.auth import Grants, is_platform_admin

        assert is_platform_admin(PLATFORM_ADMIN)
        assert not is_platform_admin(ORG_ADMIN)
        assert not is_platform_admin(LEGACY_REALM_ADMIN)
        assert Grants.from_claims(ORG_ADMIN).in_org("example_rec") == {"admins"}
        assert Grants.from_claims(LEGACY_REALM_ADMIN).platform == {"admin"}


# =============================================================================
# Real tokens from the local Keycloak
# =============================================================================

KEYCLOAK = os.environ.get("REC_REGISTRY_TEST_KEYCLOAK_URL", "http://keycloak.celine.localhost")
REALM = os.environ.get("REC_REGISTRY_TEST_KEYCLOAK_REALM", "celine")
# The local realm's user-token client and its development secret (celine-policies
# clients.yaml default). Never point this at a shared realm.
USER_CLIENT = os.environ.get("REC_REGISTRY_TEST_USER_CLIENT", "oauth2_proxy")
USER_CLIENT_SECRET = os.environ.get("REC_REGISTRY_TEST_USER_CLIENT_SECRET", "oauth2_proxy")
TOKEN_URL = f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/token"


def _token(**form) -> str:
    try:
        r = httpx.post(TOKEN_URL, data=form, timeout=10)
    except httpx.HTTPError as e:
        pytest.skip(f"no local Keycloak at {KEYCLOAK}: {e}")
    if r.status_code != 200:
        pytest.skip(f"local Keycloak refused a token for {form.get('username') or form.get('client_id')}: {r.text}")
    return r.json()["access_token"]


def _user_token(username: str) -> str:
    """A dev user's access token (password = username), as oauth2-proxy asks for it."""
    return _token(
        grant_type="password",
        client_id=USER_CLIENT,
        client_secret=USER_CLIENT_SECRET,
        username=username,
        password=username,
        scope="openid email profile organization:*",
    )


def _service_token(client_id: str) -> str:
    return _token(
        grant_type="client_credentials", client_id=client_id, client_secret=client_id
    )


def _verified(token: str):
    from celine.sdk.auth import JwtUser

    from celine.rec_registry.core.settings import settings

    return JwtUser.from_token(token, oidc=settings.oidc)


@pytest.mark.keycloak
class TestRealTokens:
    """The middleware verifies these itself; nothing is patched but the session."""

    def _refused_everything(self, monkeypatch, token: str):
        client, seen = _client(monkeypatch)
        headers = {"Authorization": f"Bearer {token}"}
        for name, request in EVERY.items():
            r = _send(client, request, headers)
            # 403, not 401: the token verified, and the policy said no.
            assert r.status_code == 403, (name, r.status_code, r.text)
        assert len(seen) == len(EVERY)
        assert all(p.subject.groups == [] for p in seen)

    def test_an_organisation_admin_is_not_a_platform_admin(self, monkeypatch):
        """@verifies REQ-0090"""
        token = _user_token("org-admin")
        user = _verified(token)
        assert not user.is_platform_admin
        assert "admins" in user.grants.in_org("example_rec")
        self._refused_everything(monkeypatch, token)

    def test_a_platform_admin_is_one_and_holds_no_registry_grant(self, monkeypatch):
        """`platform-admin` is the platform-wide grant; this service grants on scopes.

        @verifies REQ-0090
        """
        token = _user_token("admin")
        user = _verified(token)
        assert user.is_platform_admin
        self._refused_everything(monkeypatch, token)

    def test_a_realm_group_still_in_a_token_grants_nothing(self, monkeypatch):
        """A real token minted with the retired realm group `/admins`.

        The local realm no longer emits one, so it is supplied from outside: the
        token kit's fixture script mints it on a throwaway client and tears the
        old state down again.

        @verifies REQ-0090
        """
        token = os.environ.get("REC_REGISTRY_TEST_LEGACY_GROUP_TOKEN")
        if not token:
            pytest.skip("REC_REGISTRY_TEST_LEGACY_GROUP_TOKEN not set")
        user = _verified(token)
        assert "/admins" in (user.claims.get("groups") or [])
        assert not user.is_platform_admin
        self._refused_everything(monkeypatch, token)

    def test_a_scoped_service_token_still_reaches_exactly_its_scope(self, monkeypatch):
        """The control: real verification lets a scoped token through.

        @verifies REQ-0090
        """
        token = _service_token("svc-community")
        assert "rec-registry.read" in _verified(token).claims.get("scope", "").split()
        client, seen = _client(monkeypatch)
        headers = {"Authorization": f"Bearer {token}"}
        assert _send(client, READ, headers).status_code == 418
        assert _send(client, ASSET_WRITE, headers).status_code == 403
        assert all(p.subject.groups == [] for p in seen)
