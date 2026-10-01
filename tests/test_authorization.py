"""Admin authorization is derived from the path *and* the method.

While every admin route was a read, one action name (`admin`) was enough. Now
that a service account can create members it is not: reading every community and
rewriting its members are different permissions, and a service that does one
should not thereby be able to do the other.

`rec-registry.admin` still satisfies everything, through the shared matcher's
admin-override rule — so nothing that works today stops working.
"""

from __future__ import annotations

import pytest

from celine.rec_registry.core.middleware import PolicyMiddleware

# The method is unbound in these tests; the function uses no instance state.
action = PolicyMiddleware._get_admin_action


class TestActionDerivation:
    @pytest.mark.parametrize(
        "path",
        [
            "/admin/communities",
            "/admin/communities/rec-a",
            "/admin/communities/rec-a/members",
            "/admin/communities/rec-a/members/m1",
            "/admin/communities/rec-a/assets",
        ],
    )
    def test_reads_are_reads(self, path):
        """@verifies REQ-0001"""
        assert action(None, path, "GET") == "read"

    def test_creating_a_member_is_a_member_write(self):
        """@verifies REQ-0002"""
        assert action(None, "/admin/communities/rec-a/members", "POST") == "members.write"

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_every_mutating_method_on_members(self, method):
        """@verifies REQ-0002"""
        assert (
            action(None, "/admin/communities/rec-a/members/m1", method)
            == "members.write"
        )

    @pytest.mark.parametrize("method", ["PUT", "DELETE"])
    def test_delivery_points_are_their_own_member_write(self, method):
        """A delivery point sits under the member path and not under `/assets`,
        so managing one is a member field write, not an asset write — and,
        since REQ-0081, the delivery-point one rather than `members.write`.

        @verifies REQ-0002
        @verifies REQ-0081
        """
        assert (
            action(
                None,
                "/admin/communities/rec-a/members/m1/delivery-points/pod-1",
                method,
            )
            == "members.delivery_points.write"
        )

    def test_assets_are_distinguished_from_members(self):
        """An asset path contains "/members" too, so ordering matters — get it
        wrong and asset writes silently need the member grant.

        @verifies REQ-0003
        """
        assert (
            action(None, "/admin/communities/rec-a/members/m1/assets/a1", "PUT")
            == "assets.write"
        )

    def test_community_metadata_is_its_own_grant(self):
        """@verifies REQ-0004"""
        assert action(None, "/admin/communities/rec-a", "PATCH") == "community.write"
        assert (
            action(None, "/admin/communities/rec-a/areas/north", "PUT")
            == "community.write"
        )

    @pytest.mark.parametrize("method", ["PUT", "DELETE"])
    def test_a_topology_node_write_is_a_community_write(self, method):
        """A node is community structure, like an area (REQ-0072).

        @verifies REQ-0004
        """
        assert (
            action(None, "/admin/communities/rec-a/topology/AC000E00001", method)
            == "community.write"
        )

    def test_import_and_export_keep_their_own_actions(self):
        """@verifies REQ-0005"""
        assert action(None, "/admin/import", "POST") == "import"
        assert action(None, "/admin/import/yaml", "POST") == "import"
        assert action(None, "/admin/export", "GET") == "export"

    def test_lookup_keeps_its_own_action(self):
        """@verifies REQ-0005"""
        assert action(None, "/admin/lookup/user/u1", "GET") == "lookup"

    @pytest.mark.parametrize(
        "path",
        [
            "/admin/lookup/assets-by-user-ids",
            "/admin/lookup/members-by-dids",
        ],
    )
    def test_a_lookup_that_names_a_person_is_named_apart(self, path):
        """Both of these start from an identifier naming a *person* and answer
        what that person holds. The rest of `/admin/lookup/` answers which
        community a user, sensor or supply point sits in, which is a different
        disclosure.

        Same scope grants both today; the separate name is what lets a policy
        split them later without an API change.

        @verifies REQ-0005
        """
        assert action(None, path, "POST") == "assets.lookup"

    def test_any_other_lookup_falls_through_to_the_broad_action(self):
        """The special case is a list, not a pattern, so a new person-shaped
        batch route inherits `lookup` until somebody decides otherwise. That is
        the safe default — the broader action is the one every lookup caller
        already holds — and it is the reason adding a route means touching this
        function.

        @verifies REQ-0005
        """
        assert action(None, "/admin/lookup/members-by-something-else", "POST") == "lookup"


class TestPurgeIsSeparate:
    """Erasure is authorized apart from ordinary member writes.

    Deactivating somebody is recoverable; purging them takes their assets and is
    not. A service that manages members day to day should not be able to do it
    by adding a query parameter.
    """

    def test_delete_alone_is_an_ordinary_member_write(self):
        """@verifies REQ-0006"""
        assert (
            action(None, "/admin/communities/rec-a/members/m1", "DELETE")
            == "members.write"
        )

    @pytest.mark.parametrize("query", ["purge=true", "purge=1", "purge=yes", "purge=on"])
    def test_purge_asks_for_the_purge_grant(self, query):
        """@verifies REQ-0006"""
        assert (
            action(None, "/admin/communities/rec-a/members/m1", "DELETE", query)
            == "members.purge"
        )

    @pytest.mark.parametrize(
        "query", ["", "purge=false", "purge=0", "purge=", "purge=maybe", "other=true"]
    )
    def test_anything_not_clearly_truthy_is_a_soft_delete(self, query):
        """The safe reading of an ambiguous request is the recoverable one.

        @verifies REQ-0007
        """
        assert (
            action(None, "/admin/communities/rec-a/members/m1", "DELETE", query)
            == "members.write"
        )

    def test_purge_on_a_non_member_path_is_unaffected(self):
        """@verifies REQ-0008"""
        assert (
            action(None, "/admin/communities/rec-a", "DELETE", "purge=true")
            == "community.write"
        )


class TestScopeMatching:
    """The rego rules rest on the shared matcher, so pin what it promises."""

    def test_admin_covers_every_new_grant(self):
        """If this stops holding, every existing admin token loses access at once.

        @verifies REQ-0009
        """
        from pathlib import Path

        rego = Path("policies/celine/scopes.rego").read_text()
        # The admin-override rule is what makes the new fine-grained actions
        # backwards compatible; its absence would be silent until deployment.
        assert "Admin override" in rego
        assert 'endswith(have, ".admin")' in rego

    def test_every_action_has_a_rule(self):
        """Every action `_get_admin_action` can return, checked as a set.

        An action with no rule is denied by default — fail-closed, but it
        presents as an unexplained `403` in production rather than as anything a
        test catches.

        @verifies REQ-0010
        """
        from pathlib import Path

        rego = Path("policies/celine/rec_registry/access.rego").read_text()
        for name in (
            "read",
            "members.write",
            "members.purge",
            "assets.write",
            "community.write",
            "import",
            "export",
            "lookup",
            # Ninth, and the one that shows why the list is checked as a set:
            # it was added to the middleware and to the bundle together and left
            # out of this list, so the check passed while covering eight of nine.
            "assets.lookup",
            # Role and area only (REQ-0063, REQ-0064).
            "members.profile.write",
            # One per member field group (REQ-0081, REQ-0082).
            "members.name.write",
            "members.role.write",
            "members.area.write",
            "members.delivery_points.write",
            # What a path matching no route shape derives (REQ-0065): only the
            # admin grant satisfies it.
            "admin",
        ):
            assert f'input.action.name == "{name}"' in rego, f"no rule for {name}"


# =============================================================================
# Caller-supplied ids never choose the action (REQ-0065)
# =============================================================================
#
# Every id in an admin path is chosen by a caller: member keys, asset keys,
# delivery-point ids, area keys, community keys, and the ids a lookup resolves.
# An attached meter's asset key is `meter-<sensor id>`, and the sensor id is
# printed on a device — so the words below are exactly what an id can contain.
# The derivation used to search the whole path for `lookup`, `import` and
# `export` before it looked at the method, so `PUT …/assets/meter-lookup-01`
# derived `lookup`, and a lookup-only caller could write that asset.

HOSTILE_WORDS = [
    "lookup",
    "import",
    "export",
    "purge",
    "assets",
    "members",
    "profile",
    "status",
    "areas",
    "topology",
    "delivery-points",
    "communities",
    "admin",
    "yaml",
    "assets-by-user-ids",
    "members-by-dids",
    "rename",
    # The member field routes (REQ-0081): a member key spelling one must not
    # turn `…/members/{mk}` into a field write, nor a field write into another.
    "name",
    "role",
    "area",
    "delivery_points",
    "replaces",
]


def _hostile_ids(word: str) -> list[str]:
    return [word, f"meter-{word}", f"meter-{word}-01", f"x{word}x"]


# (method, path template, the action a plain id derives). Every admin route
# family, with each caller-supplied segment a placeholder.
ROUTES = [
    ("GET", "/admin/communities/{id}", "read"),
    ("GET", "/admin/communities/{id}/members/{id}", "read"),
    ("GET", "/admin/communities/{id}/assets/{id}", "read"),
    ("GET", "/admin/communities/{id}/assets/by-sensor-id/{id}", "read"),
    ("GET", "/admin/communities/{id}/members/by-user-id/{id}", "read"),
    ("GET", "/admin/communities/{id}/delivery-points/by-id/{id}", "read"),
    ("PATCH", "/admin/communities/{id}", "community.write"),
    ("PUT", "/admin/communities/{id}/areas/{id}", "community.write"),
    ("DELETE", "/admin/communities/{id}/areas/{id}", "community.write"),
    ("POST", "/admin/communities/{id}/areas/{id}/rename", "community.write"),
    ("PUT", "/admin/communities/{id}/topology/{id}", "community.write"),
    ("DELETE", "/admin/communities/{id}/topology/{id}", "community.write"),
    ("GET", "/admin/communities/{id}/topology", "read"),
    ("POST", "/admin/communities/{id}/members", "members.write"),
    ("PATCH", "/admin/communities/{id}/members/{id}", "members.write"),
    ("DELETE", "/admin/communities/{id}/members/{id}", "members.write"),
    ("POST", "/admin/communities/{id}/members/{id}/status", "members.write"),
    ("PATCH", "/admin/communities/{id}/members/{id}/profile", "members.profile.write"),
    ("PUT", "/admin/communities/{id}/members/{id}/name", "members.name.write"),
    ("PUT", "/admin/communities/{id}/members/{id}/role", "members.role.write"),
    ("PUT", "/admin/communities/{id}/members/{id}/area", "members.area.write"),
    (
        "PUT",
        "/admin/communities/{id}/members/{id}/delivery-points/{id}",
        "members.delivery_points.write",
    ),
    (
        "DELETE",
        "/admin/communities/{id}/members/{id}/delivery-points/{id}",
        "members.delivery_points.write",
    ),
    ("PUT", "/admin/communities/{id}/members/{id}/assets/{id}", "assets.write"),
    ("DELETE", "/admin/communities/{id}/members/{id}/assets/{id}", "assets.write"),
    ("GET", "/admin/lookup/community-by-user-id/{id}", "lookup"),
    ("GET", "/admin/lookup/community-by-sensor-id/{id}", "lookup"),
    ("GET", "/admin/lookup/community-by-delivery-point/{id}", "lookup"),
    ("GET", "/admin/lookup/member-by-user-id/{id}", "lookup"),
    ("GET", "/admin/lookup/asset-by-sensor-id/{id}", "lookup"),
]


class TestACallerSuppliedIdNeverChoosesTheAction:
    @pytest.mark.parametrize("method,template,expected", ROUTES)
    def test_a_plain_id_derives_the_routes_action(self, method, template, expected):
        """The baseline the hostile cases below are compared with.

        @verifies REQ-0065
        """
        assert action(None, template.replace("{id}", "plain-01"), method) == expected

    @pytest.mark.parametrize("word", HOSTILE_WORDS)
    @pytest.mark.parametrize("method,template,expected", ROUTES)
    def test_a_hostile_id_derives_the_same_action(
        self, method, template, expected, word
    ):
        """Each placeholder in turn, then all of them at once, holds the word.

        @verifies REQ-0065
        """
        slots = template.count("{id}")
        for hostile in _hostile_ids(word):
            for position in range(slots):
                ids = ["plain-01"] * slots
                ids[position] = hostile
                path = template.replace("{id}", "{}").format(*ids)
                assert action(None, path, method) == expected, path
            everywhere = template.replace("{id}", hostile)
            assert action(None, everywhere, method) == expected, everywhere

    @pytest.mark.parametrize("word", HOSTILE_WORDS)
    def test_a_hostile_id_cannot_reach_the_purge_grant_or_escape_it(self, word):
        """A member key naming an action changes neither the soft delete nor
        the purge.

        @verifies REQ-0065
        """
        for hostile in _hostile_ids(word):
            path = f"/admin/communities/{hostile}/members/{hostile}"
            assert action(None, path, "DELETE") == "members.write"
            assert action(None, path, "DELETE", "purge=true") == "members.purge"

    @pytest.mark.parametrize("word", ["lookup", "import", "export"])
    def test_the_example_the_defect_was_found_with(self, word):
        """`PUT …/assets/meter-export-01` is `assets.write`, not `export`.

        @verifies REQ-0065
        """
        path = f"/admin/communities/rec-a/members/m1/assets/meter-{word}-01"
        assert action(None, path, "PUT") == "assets.write"
        assert action(None, path, "DELETE") == "assets.write"

    def test_a_lookup_named_by_an_id_is_not_the_person_lookup(self):
        """`assets.lookup` is the route segment after `/admin/lookup/`, not a
        word anywhere in the path — an id spelling it stays on `lookup`.

        @verifies REQ-0065
        """
        assert (
            action(None, "/admin/lookup/community-by-user-id/assets-by-user-ids", "GET")
            == "lookup"
        )
        assert (
            action(None, "/admin/lookup/member-by-user-id/x/members-by-dids", "GET")
            == "lookup"
        )

    @pytest.mark.parametrize(
        "method,path",
        [
            ("DELETE", "/admin/import"),
            ("PUT", "/admin/import/yaml"),
            ("GET", "/admin/import"),
            ("POST", "/admin/export"),
            ("DELETE", "/admin/export"),
            ("PUT", "/admin/lookup/asset-by-sensor-id/s-1"),
            ("DELETE", "/admin/lookup/assets-by-user-ids"),
        ],
    )
    def test_the_method_is_honoured_on_the_fixed_routes(self, method, path):
        """Import is a POST and export a read. Any other method on those paths,
        or a write method on a lookup, is no route at all — and derives
        `admin` rather than the grant the path's name suggests.

        @verifies REQ-0065
        """
        assert action(None, path, method) == "admin"

    @pytest.mark.parametrize(
        "method,path",
        [
            ("PUT", "/admin/communities/rec-a/members/m1/assets"),
            ("PUT", "/admin/communities/rec-a/members/m1/assets/a/extra"),
            ("POST", "/admin/communities/rec-a/lookup"),
            ("PUT", "/admin/communities/rec-a/members/m1/export"),
            ("PUT", "/admin/communities/rec-a/topology"),
            ("POST", "/admin/communities/rec-a/topology"),
            ("PUT", "/admin/communities/rec-a/topology/n1/extra"),
            ("PUT", "/admin/communities/rec-a/areas/north/rename"),
            ("PATCH", "/admin/communities/rec-a/areas/north/rename"),
            ("DELETE", "/admin/communities/rec-a/areas/north/rename"),
            ("POST", "/admin/communities/rec-a/areas/north/rename/extra"),
            ("POST", "/admin/communities/rec-a/areas/north/other"),
            ("POST", "/admin/communities/rec-a/members/m1/rename"),
            ("POST", "/admin/communities/rec-a/topology/n1/rename"),
            ("POST", "/admin/somewhere-new"),
            ("PUT", "/admin"),
        ],
    )
    def test_a_write_matching_no_route_shape_needs_the_admin_grant(self, method, path):
        """Fail closed: a shape the derivation does not know falls through to
        `admin`, not to whichever narrower grant a word in it resembles.

        @verifies REQ-0065
        """
        assert action(None, path, method) == "admin"


class TestThroughTheMiddleware:
    """The derivation and the Rego bundle together, on a real request.

    The suite otherwise runs with `POLICIES_ENABLED=false`, so this turns the
    engine on for one app and gives the caller a token's scopes directly: token
    verification is not what is under test, the decision is.
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
            # Past the policy check. Stop here rather than touch a database.
            raise HTTPException(status_code=418, detail="reached the route")
            yield  # pragma: no cover

        app.dependency_overrides[get_session] = reached_the_route
        return TestClient(app)

    ASSET = "/admin/communities/rec-a/members/m1/assets/meter-lookup-01"
    BODY = {
        "key": "meter-lookup-01",
        "asset_type": "meter",
        "properties": {"name": "M", "sensor_id": "lookup-01", "meter_type": "consumption"},
    }

    def test_a_lookup_only_caller_cannot_put_an_asset_keyed_lookup(self, monkeypatch):
        """@verifies REQ-0065"""
        client = self._client(monkeypatch, "rec-registry.lookup")
        r = client.put(self.ASSET, json=self.BODY)
        assert r.status_code == 403, r.text

    def test_a_lookup_only_caller_cannot_delete_an_asset_keyed_lookup(self, monkeypatch):
        """@verifies REQ-0065"""
        client = self._client(monkeypatch, "rec-registry.lookup")
        r = client.delete(self.ASSET)
        assert r.status_code == 403, r.text

    @pytest.mark.parametrize("scope", ["rec-registry.import", "rec-registry.export"])
    def test_an_import_or_export_caller_cannot_write_such_an_asset(
        self, monkeypatch, scope
    ):
        """@verifies REQ-0065"""
        client = self._client(monkeypatch, scope)
        path = "/admin/communities/rec-a/members/m1/assets/meter-import-export-01"
        assert client.put(path, json={**self.BODY, "key": "meter-import-export-01"}).status_code == 403
        assert client.delete(path).status_code == 403

    def test_the_asset_grant_still_reaches_the_route(self, monkeypatch):
        """The contrast: the refusal above is the grant, not the path.

        @verifies REQ-0065
        """
        client = self._client(monkeypatch, "rec-registry.assets.write")
        r = client.put(self.ASSET, json=self.BODY)
        assert r.status_code == 418, r.text

    NODE = "/admin/communities/rec-a/topology/meter-lookup-01"
    NODE_BODY = {"id": "meter-lookup-01", "type": "primary_substation"}

    @pytest.mark.parametrize(
        "scope",
        [
            "rec-registry.lookup",
            "rec-registry.members.write",
            "rec-registry.assets.write",
            "rec-registry.read",
        ],
    )
    def test_only_the_community_grant_writes_a_topology_node(self, monkeypatch, scope):
        """A node id spelling `lookup` chooses nothing; neither the member,
        asset nor read grant reaches a node write (REQ-0072).

        @verifies REQ-0004
        """
        client = self._client(monkeypatch, scope)
        assert client.put(self.NODE, json=self.NODE_BODY).status_code == 403
        assert client.delete(self.NODE).status_code == 403

    def test_the_community_grant_reaches_the_node_routes(self, monkeypatch):
        """@verifies REQ-0004"""
        client = self._client(monkeypatch, "rec-registry.community.write")
        assert client.put(self.NODE, json=self.NODE_BODY).status_code == 418
        assert client.delete(self.NODE).status_code == 418

    RENAME = "/admin/communities/rec-a/areas/meter-lookup-01/rename"

    @pytest.mark.parametrize(
        "scope",
        [
            "rec-registry.lookup",
            "rec-registry.members.write",
            "rec-registry.members.profile.write",
            "rec-registry.assets.write",
            "rec-registry.read",
        ],
    )
    def test_only_the_community_grant_renames_an_area(self, monkeypatch, scope):
        """An area key spelling `lookup` chooses nothing; the member, profile,
        asset and read grants do not reach a rename, although it moves
        members' areas (REQ-0079).

        @verifies REQ-0004
        @verifies REQ-0079
        """
        client = self._client(monkeypatch, scope)
        assert client.post(self.RENAME, json={"new_key": "south"}).status_code == 403

    def test_the_community_grant_reaches_the_rename_route(self, monkeypatch):
        """@verifies REQ-0004
        @verifies REQ-0079"""
        client = self._client(monkeypatch, "rec-registry.community.write")
        assert client.post(self.RENAME, json={"new_key": "south"}).status_code == 418



# =============================================================================
# Member writes are granted per field (REQ-0081, REQ-0082)
# =============================================================================

M = "/admin/communities/rec-a/members/m1"

# (method, path, body, action): every member field write, by its narrow route.
FIELD_WRITES = {
    "name": ("PUT", f"{M}/name", {"name": "Example Member"}),
    "role": ("PUT", f"{M}/role", {"role": "prosumer"}),
    "area": ("PUT", f"{M}/area", {"area": "north"}),
    "dp_put": (
        "PUT",
        f"{M}/delivery-points/IT001E00000002",
        {"id": "IT001E00000002", "type": "pod"},
    ),
    "dp_replace": (
        "PUT",
        f"{M}/delivery-points/IT001E00000002?replaces=IT001E00000001",
        {"id": "IT001E00000002", "type": "pod"},
    ),
    "dp_delete": ("DELETE", f"{M}/delivery-points/IT001E00000001", None),
    "profile": ("PATCH", f"{M}/profile", {"area": "north"}),
    "patch": ("PATCH", M, {"name": "Example Member"}),
    "status": ("POST", f"{M}/status", {"status": "active"}),
    "create": ("POST", "/admin/communities/rec-a/members", {"user_id": "kc-0001"}),
}

# Which of FIELD_WRITES each scope reaches; everything else it is refused.
REACHES = {
    "rec-registry.members.name.write": {"name"},
    "rec-registry.members.role.write": {"role"},
    "rec-registry.members.area.write": {"area"},
    "rec-registry.members.delivery_points.write": {"dp_put", "dp_replace", "dp_delete"},
    "rec-registry.members.profile.write": {"role", "area", "profile"},
    "rec-registry.members.write": set(FIELD_WRITES),
    "rec-registry.admin": set(FIELD_WRITES),
    "rec-registry.assets.write": set(),
    "rec-registry.read": set(),
}


class TestPerFieldActions:
    @pytest.mark.parametrize(
        "segment,expected",
        [
            ("name", "members.name.write"),
            ("role", "members.role.write"),
            ("area", "members.area.write"),
        ],
    )
    def test_each_field_route_derives_its_own_action(self, segment, expected):
        """@verifies REQ-0081"""
        assert action(None, f"{M}/{segment}", "PUT") == expected

    @pytest.mark.parametrize("segment", ["name", "role", "area"])
    @pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
    def test_any_other_method_on_a_field_route_is_no_route(self, segment, method):
        """A field route is a `PUT`; anything else derives `admin`, and a read
        stays a read.

        @verifies REQ-0081
        """
        assert action(None, f"{M}/{segment}", method) == "admin"
        assert action(None, f"{M}/{segment}", "GET") == "read"

    @pytest.mark.parametrize("method", ["POST", "PATCH"])
    def test_only_put_and_delete_write_a_delivery_point(self, method):
        """@verifies REQ-0081"""
        assert action(None, f"{M}/delivery-points/pod-1", method) == "admin"

    @pytest.mark.parametrize(
        "query",
        [
            "replaces=pod-0",
            "replaces=",
            "replaces=purge",
            "purge=true",
            "replaces=pod-0&purge=true",
            "replaces=members.write",
        ],
    )
    @pytest.mark.parametrize("method", ["PUT", "DELETE"])
    def test_the_query_never_changes_a_delivery_point_action(self, query, method):
        """`?replaces=` is a correction, not a grant: the action is read from
        the route segments and the method only (F2), whatever the query says.

        @verifies REQ-0081
        """
        assert (
            action(None, f"{M}/delivery-points/pod-1", method, query)
            == "members.delivery_points.write"
        )

    @pytest.mark.parametrize("segment", ["profile", "status"])
    def test_the_existing_member_routes_keep_their_action(self, segment):
        """F3, F4: the profile alias and the identity routes are unchanged.

        @verifies REQ-0081
        """
        expected = "members.profile.write" if segment == "profile" else "members.write"
        method = "PATCH" if segment == "profile" else "POST"
        assert action(None, f"{M}/{segment}", method) == expected
        assert action(None, M, "PATCH") == "members.write"
        assert action(None, "/admin/communities/rec-a/members", "POST") == "members.write"

    @pytest.mark.parametrize("key", ["name", "role", "area", "delivery-points", "profile"])
    def test_a_member_keyed_like_a_field_route_derives_nothing_new(self, key):
        """A member whose key is `name` is a member, not a field route; its own
        field routes still derive by the segment after the key.

        @verifies REQ-0081
        @verifies REQ-0065
        """
        base = f"/admin/communities/rec-a/members/{key}"
        assert action(None, base, "PUT") == "members.write"
        assert action(None, base, "PATCH") == "members.write"
        assert action(None, base, "DELETE") == "members.write"
        assert action(None, f"{base}/name", "PUT") == "members.name.write"
        assert action(None, f"{base}/role", "PUT") == "members.role.write"
        assert action(None, f"{base}/area", "PUT") == "members.area.write"
        assert action(None, f"{base}/status", "POST") == "members.write"
        assert (
            action(None, f"{base}/delivery-points/{key}", "PUT")
            == "members.delivery_points.write"
        )
        # A delivery-point id spelling a field is still a delivery point.
        for dp in ("name", "role", "area", "profile"):
            assert (
                action(None, f"/admin/communities/rec-a/members/m1/delivery-points/{dp}", "DELETE")
                == "members.delivery_points.write"
            )

    @pytest.mark.parametrize(
        "method,path",
        [
            ("PUT", f"{M}/name/extra"),
            ("PUT", f"{M}/email"),
            ("PUT", f"{M}/did"),
            ("PUT", f"{M}/user_id"),
            ("PUT", f"{M}/delivery_points"),
            ("PUT", f"{M}/delivery-points"),
            ("PUT", f"{M}/delivery-points/pod-1/extra"),
        ],
    )
    def test_a_field_not_in_the_allow_list_needs_the_admin_grant(self, method, path):
        """Identity fields have no narrow route (F3): an invented one falls
        through to `admin`, never to a field action.

        @verifies REQ-0081
        """
        assert action(None, path, method) == "admin"


class TestPerFieldGrantsThroughTheMiddleware:
    """Each narrow scope reaches its own route and none of its neighbours'.

    Borrows `TestThroughTheMiddleware._client` (not its tests): the policy
    engine on, the caller's scopes given directly, and `418` meaning "past the
    policy check".
    """

    _client = TestThroughTheMiddleware._client

    def _send(self, client, write: str):
        method, path, body = FIELD_WRITES[write]
        return client.request(method, path, json=body)

    @pytest.mark.parametrize("scope", sorted(REACHES))
    @pytest.mark.parametrize("write", sorted(FIELD_WRITES))
    def test_a_scope_reaches_exactly_its_writes(self, monkeypatch, scope, write):
        """@verifies REQ-0082"""
        client = self._client(monkeypatch, scope)
        r = self._send(client, write)
        expected = 418 if write in REACHES[scope] else 403
        assert r.status_code == expected, (scope, write, r.status_code, r.text)

    def test_an_area_only_token_changes_an_area_and_nothing_else(self, monkeypatch):
        """The plan's acceptance case, spelled out: area yes; name, role and
        delivery points no.

        @verifies REQ-0082
        """
        client = self._client(monkeypatch, "rec-registry.members.area.write")
        assert self._send(client, "area").status_code == 418
        for neighbour in ("name", "role", "dp_put", "dp_replace", "dp_delete"):
            assert self._send(client, neighbour).status_code == 403, neighbour

    def test_the_admin_override_still_covers_every_field_action(self):
        """@verifies REQ-0009"""
        from pathlib import Path

        rego = Path("policies/celine/rec_registry/access.rego").read_text()
        for name in (
            "members.name.write",
            "members.role.write",
            "members.area.write",
            "members.delivery_points.write",
        ):
            block = rego.split(f'input.action.name == "{name}"', 1)[1].split("}", 1)[0]
            assert '"rec-registry.admin"' in block, name
