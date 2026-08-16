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

    def test_import_and_export_keep_their_own_actions(self):
        """@verifies REQ-0005"""
        assert action(None, "/admin/import", "POST") == "import"
        assert action(None, "/admin/import/yaml", "POST") == "import"
        assert action(None, "/admin/export", "GET") == "export"

    def test_lookup_keeps_its_own_action(self):
        """@verifies REQ-0005"""
        assert action(None, "/admin/lookup/user/u1", "GET") == "lookup"


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
        """@verifies REQ-0010"""
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
        ):
            assert f'input.action.name == "{name}"' in rego, f"no rule for {name}"
