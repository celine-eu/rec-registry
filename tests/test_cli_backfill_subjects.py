"""`backfill-subjects`: each member's account subject, looked up in Keycloak by username.

For every member the full export lists, the Keycloak user whose username is the
member's `user_id` is looked up; a member holding no subject is given that user's
id. Dry run unless `--apply`; a subject already held is never replaced, and one
that differs from Keycloak's is counted rather than written. Only counts are
printed (REQ-0102).

Keycloak and the registry are both mocked: `httpx.get` and `httpx.patch` are
patched where the CLI calls them. Synthetic values only.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import yaml
from typer.testing import CliRunner

from celine.rec_registry.cli.main import app, plan_subject_backfill

runner = CliRunner()

HTTPX_GET = "celine.rec_registry.cli.main.httpx.get"
HTTPX_PATCH = "celine.rec_registry.cli.main.httpx.patch"
HTTPX_POST = "celine.rec_registry.cli.main.httpx.post"

SUB_1 = "0b6f6c3e-8d2a-4c41-9f0e-5a7d2c1b9e10"
SUB_2 = "7c1d2e3f-4a5b-4c6d-8e9f-0a1b2c3d4e5f"
SUB_3 = "11111111-2222-4333-8444-555555555555"

AUTH_URL = "https://keycloak.example.org/realms/celine"
ADMIN_USERS = "https://keycloak.example.org/admin/realms/celine/users"


def _member(user_id: str, subject: str | None = None, status: str = "active") -> dict:
    member = {"user_id": user_id, "name": "N", "role": "consumer", "area": "a", "status": status}
    if subject is not None:
        member["subject"] = subject
    return member


def _doc(community: str, members: dict) -> dict:
    return {"community": {"id": community, "name": community}, "members": members}


def _lookup(accounts: dict[str, list[str]]):
    """A `find_subjects` over a fixed table, counting its calls."""
    calls: list[str] = []

    def find(username: str) -> list[str]:
        calls.append(username)
        return accounts.get(username, [])

    find.calls = calls  # type: ignore[attr-defined]
    return find


class TestPlanSubjectBackfill:
    def test_a_member_without_one_is_given_its_accounts_id(self):
        """@verifies REQ-0102"""
        plan = plan_subject_backfill(
            [_doc("rec-a", {"ex-00001": _member("one@example.org")})],
            _lookup({"one@example.org": [SUB_1]}),
        )

        assert plan.to_set == [("rec-a", "ex-00001", SUB_1)]
        assert plan.examined == 1

    def test_one_already_held_and_matching_is_left(self):
        """@verifies REQ-0102"""
        plan = plan_subject_backfill(
            [_doc("rec-a", {"ex-00001": _member("one@example.org", SUB_1.upper())})],
            _lookup({"one@example.org": [SUB_1]}),
        )

        assert plan.to_set == []
        assert plan.already_set == 1

    def test_one_already_held_and_different_is_counted_never_replaced(self):
        """@verifies REQ-0102"""
        plan = plan_subject_backfill(
            [_doc("rec-a", {"ex-00001": _member("one@example.org", SUB_2)})],
            _lookup({"one@example.org": [SUB_1]}),
        )

        assert plan.to_set == []
        assert plan.differs == 1

    def test_no_account_and_two_accounts_set_nothing(self):
        """A member can exist before its account; two answers are no answer.

        @verifies REQ-0102
        """
        plan = plan_subject_backfill(
            [
                _doc(
                    "rec-a",
                    {
                        "ex-00001": _member("none@example.org"),
                        "ex-00002": _member("two@example.org"),
                    },
                )
            ],
            _lookup({"two@example.org": [SUB_1, SUB_2]}),
        )

        assert plan.to_set == []
        assert plan.no_account == 1
        assert plan.ambiguous == 1

    def test_members_of_every_status_are_covered(self):
        """@verifies REQ-0102"""
        plan = plan_subject_backfill(
            [_doc("rec-a", {"ex-00001": _member("one@example.org", status="inactive")})],
            _lookup({"one@example.org": [SUB_1]}),
        )

        assert plan.to_set == [("rec-a", "ex-00001", SUB_1)]

    def test_one_username_is_looked_up_once(self):
        """@verifies REQ-0102"""
        find = _lookup({"one@example.org": [SUB_1]})

        plan = plan_subject_backfill(
            [
                _doc("rec-a", {"ex-00001": _member("one@example.org")}),
                _doc("rec-b", {"ex-00007": _member("one@example.org")}),
            ],
            find,
        )

        assert find.calls == ["one@example.org"]
        assert plan.to_set == [("rec-a", "ex-00001", SUB_1), ("rec-b", "ex-00007", SUB_1)]


class _Fake:
    """The registry export, Keycloak's user search and the member `PATCH`."""

    def __init__(self, docs: list[dict], accounts: dict[str, list[dict]], *, export_status=200,
                 keycloak_status=200, patch_status=200):
        self.docs = docs
        self.accounts = accounts
        self.export_status = export_status
        self.keycloak_status = keycloak_status
        self.patch_status = patch_status
        self.get = MagicMock(side_effect=self._get)
        self.patch = MagicMock(side_effect=self._patch)
        self.post = MagicMock()

    def _get(self, url, *, params=None, headers=None, timeout=None, **_):
        resp = MagicMock()
        if url.endswith("/admin/export"):
            resp.status_code = self.export_status
            resp.text = yaml.safe_dump_all(self.docs) if self.export_status < 400 else "{}"
            return resp
        assert url == ADMIN_USERS, url
        resp.status_code = self.keycloak_status
        body = self.accounts.get(params["username"], []) if self.keycloak_status < 400 else {}
        resp.json.return_value = body
        resp.text = json.dumps(body)
        return resp

    def _patch(self, url, *, json=None, headers=None, timeout=None, **_):
        resp = MagicMock()
        resp.status_code = self.patch_status
        resp.text = "{}"
        return resp

    def run(self, *args: str):
        with patch(HTTPX_GET, self.get), patch(HTTPX_PATCH, self.patch), patch(
            HTTPX_POST, self.post
        ):
            return runner.invoke(
                app,
                [
                    "backfill-subjects",
                    "--api",
                    "https://registry.example.org",
                    "--token",
                    "registry-jwt",
                    "--keycloak-token",
                    "keycloak-jwt",
                    "--auth-url",
                    AUTH_URL,
                    *args,
                ],
            )


def _kc(username: str, sub: str) -> dict:
    return {"id": sub, "username": username}


def _registry() -> list[dict]:
    return [
        _doc(
            "rec-a",
            {
                "ex-00001": _member("one@example.org"),
                "ex-00002": _member("two@example.org", SUB_2),
                "ex-00003": _member("three@example.org"),
            },
        )
    ]


ACCOUNTS = {
    "one@example.org": [_kc("one@example.org", SUB_1)],
    "two@example.org": [_kc("two@example.org", SUB_2)],
}


def _counts(output: str) -> dict[str, int]:
    counts = {}
    for line in output.splitlines():
        name, _, value = line.partition("\t")
        if value.strip().isdigit():
            counts[name] = int(value)
    return counts


class TestBackfillSubjectsCommand:
    def test_it_is_a_dry_run_unless_told_otherwise(self):
        """@verifies REQ-0102"""
        fake = _Fake(_registry(), ACCOUNTS)

        result = fake.run()

        assert result.exit_code == 0, result.output
        fake.patch.assert_not_called()
        fake.post.assert_not_called()
        assert _counts(result.output) == {
            "examined": 3,
            "would_set": 1,
            "already_set": 1,
            "no_account": 1,
            "ambiguous": 0,
            "differs": 0,
            "failed": 0,
        }

    def test_apply_writes_each_missing_subject_through_patch(self):
        """@verifies REQ-0102"""
        fake = _Fake(_registry(), ACCOUNTS)

        result = fake.run("--apply")

        assert result.exit_code == 0, result.output
        fake.patch.assert_called_once()
        call = fake.patch.call_args
        assert call.args[0] == "https://registry.example.org/admin/communities/rec-a/members/ex-00001"
        assert call.kwargs["json"] == {"subject": SUB_1}
        assert call.kwargs["headers"]["Authorization"] == "Bearer registry-jwt"
        assert _counts(result.output)["set"] == 1

    def test_keycloak_is_asked_for_the_exact_username_with_its_own_token(self):
        """@verifies REQ-0102"""
        fake = _Fake(_registry(), ACCOUNTS)

        fake.run()

        searches = [c for c in fake.get.call_args_list if c.args[0] == ADMIN_USERS]
        assert {c.kwargs["params"]["username"] for c in searches} == {
            "one@example.org",
            "two@example.org",
            "three@example.org",
        }
        for c in searches:
            assert c.kwargs["params"]["exact"] == "true"
            assert c.kwargs["headers"]["Authorization"] == "Bearer keycloak-jwt"

    def test_a_search_answer_for_another_username_is_not_a_match(self):
        """Keycloak's search can answer more than the exact name; only the
        account whose username is the member's `user_id` counts.

        @verifies REQ-0102
        """
        accounts = {"one@example.org": [_kc("one@example.org.other", SUB_3)]}
        fake = _Fake([_doc("rec-a", {"ex-00001": _member("one@example.org")})], accounts)

        result = fake.run("--apply")

        assert result.exit_code == 0, result.output
        fake.patch.assert_not_called()
        assert _counts(result.output)["no_account"] == 1

    def test_a_second_run_writes_nothing(self):
        """@verifies REQ-0102"""
        after = [
            _doc(
                "rec-a",
                {
                    "ex-00001": _member("one@example.org", SUB_1),
                    "ex-00002": _member("two@example.org", SUB_2),
                    "ex-00003": _member("three@example.org"),
                },
            )
        ]
        fake = _Fake(after, ACCOUNTS)

        result = fake.run("--apply")

        assert result.exit_code == 0, result.output
        fake.patch.assert_not_called()
        assert _counts(result.output)["already_set"] == 2

    def test_a_different_subject_is_reported_and_left_as_it_is(self):
        """@verifies REQ-0102"""
        docs = [_doc("rec-a", {"ex-00001": _member("one@example.org", SUB_2)})]
        fake = _Fake(docs, ACCOUNTS)

        result = fake.run("--apply")

        assert result.exit_code == 1, result.output
        fake.patch.assert_not_called()
        assert _counts(result.output)["differs"] == 1

    def test_it_prints_counts_and_nothing_that_names_a_member(self):
        """@verifies REQ-0102"""
        docs = [
            _doc(
                "rec-a",
                {
                    "ex-00001": _member("one@example.org"),
                    "ex-00002": _member("two@example.org", SUB_3),
                },
            )
        ]
        fake = _Fake(docs, ACCOUNTS)

        result = fake.run("--apply")

        for value in ("one@example.org", "two@example.org", "ex-0000", SUB_1, SUB_2, SUB_3):
            assert value not in result.output

    def test_an_unreadable_registry_writes_and_asks_nothing(self):
        """@verifies REQ-0102"""
        fake = _Fake(_registry(), ACCOUNTS, export_status=403)

        result = fake.run("--apply")

        assert result.exit_code == 2
        assert all(c.args[0].endswith("/admin/export") for c in fake.get.call_args_list)
        fake.patch.assert_not_called()

    def test_a_keycloak_refusal_writes_nothing_and_names_nobody(self):
        """Every lookup runs before the first write, so a refusal half-way
        leaves the registry as it was.

        @verifies REQ-0102
        """
        fake = _Fake(_registry(), ACCOUNTS, keycloak_status=403)

        result = fake.run("--apply")

        assert result.exit_code == 2
        fake.patch.assert_not_called()
        assert "@example.org" not in result.output

    def test_a_refused_write_is_counted_and_fails_the_run(self):
        """@verifies REQ-0102"""
        fake = _Fake(_registry(), ACCOUNTS, patch_status=409)

        result = fake.run("--apply")

        assert result.exit_code == 1, result.output
        counts = _counts(result.output)
        assert counts["set"] == 0
        assert counts["failed"] == 1

    def test_the_admin_url_is_derived_from_the_realm_url(self):
        """@verifies REQ-0102"""
        from celine.rec_registry.cli.main import keycloak_admin_url

        assert keycloak_admin_url(AUTH_URL) == "https://keycloak.example.org/admin/realms/celine"
        assert (
            keycloak_admin_url("http://localhost:8080/auth/realms/celine/")
            == "http://localhost:8080/auth/admin/realms/celine"
        )
