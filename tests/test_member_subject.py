"""The account subject: a member's Keycloak `sub`, in a column of its own.

`user_id` is the username the participant authenticates with (REQ-0053); the
subject is the account's own id, the UUID a token carries as `sub`. It is
optional, because a member can exist before its account, and it is written by
the create and `PATCH` routes and by the bundle import alike (REQ-0101).

It is read back by the full export, which is the backup and has to restore what
the write API wrote, and by nothing else: no member read, lookup, self-service
answer or member export carries it.

Synthetic values only: placeholder usernames, PODs and UUIDs.
"""

from __future__ import annotations

import pytest
import yaml
from sqlalchemy import select

from celine.rec_registry.db.models import Member
from tests.conftest import identifies_as
from tests.substations import substation_graph

pytestmark = pytest.mark.asyncio

SUBJECT = "0b6f6c3e-8d2a-4c41-9f0e-5a7d2c1b9e10"
OTHER_SUBJECT = "7c1d2e3f-4a5b-4c6d-8e9f-0a1b2c3d4e5f"


def _member(**overrides) -> dict:
    payload = {
        "user_id": "subject.one@example.org",
        "name": "Subject Member",
        "type": "schema:Person",
        "role": "consumer",
        "area": "north",
        "status": "active",
        "delivery_points": [{"id": "IT001E00000101", "type": "pod"}],
    }
    payload.update(overrides)
    return payload


async def _seed(client, key: str = "subject-rec", members: dict | None = None) -> str:
    bundle = {
        "version": "1.0",
        "schema_version": "0.7",
        "community": {"id": key, "name": "Subject Community", **substation_graph("north")},
        "members": members or {},
    }
    r = await client.post("/admin/import", json={"bundle": bundle, "dry_run": False})
    assert r.status_code == 200, r.text
    return key


async def _stored(pg_session, community_key: str, member_key: str) -> Member:
    from celine.rec_registry.db.models import Community

    pg_session.expire_all()
    return await pg_session.scalar(
        select(Member)
        .join(Community, Member.community_id == Community.id)
        .where(Community.key == community_key, Member.key == member_key)
    )


@pytest.mark.integration
class TestTheWriteRoutesTakeTheSubject:
    async def test_create_stores_it_in_its_own_column(self, live_client, pg_session):
        """@verifies REQ-0101"""
        key = await _seed(live_client)

        r = await live_client.post(
            f"/admin/communities/{key}/members",
            json=_member(key="ex-00001", subject=SUBJECT),
        )

        assert r.status_code == 201, r.text
        member = await _stored(pg_session, key, "ex-00001")
        assert member.subject == SUBJECT
        assert "subject" not in member.extra

    async def test_it_is_held_in_its_canonical_form(self, live_client, pg_session):
        """@verifies REQ-0101"""
        key = await _seed(live_client)

        r = await live_client.post(
            f"/admin/communities/{key}/members",
            json=_member(key="ex-00001", subject=SUBJECT.upper()),
        )

        assert r.status_code == 201, r.text
        assert (await _stored(pg_session, key, "ex-00001")).subject == SUBJECT

    async def test_a_member_can_exist_without_one(self, live_client, pg_session):
        """@verifies REQ-0101"""
        key = await _seed(live_client)

        r = await live_client.post(
            f"/admin/communities/{key}/members", json=_member(key="ex-00001")
        )

        assert r.status_code == 201, r.text
        assert (await _stored(pg_session, key, "ex-00001")).subject is None

    @pytest.mark.parametrize(
        "value", ["subject.one@example.org", "kc-0001", "not-a-uuid", ""]
    )
    async def test_a_value_that_is_not_a_uuid_is_refused(
        self, live_client, pg_session, value
    ):
        """A username in the subject is the mistake `user_id` invites the other
        way round (REQ-0053); it is refused before anything is written.

        @verifies REQ-0101
        """
        key = await _seed(live_client)

        r = await live_client.post(
            f"/admin/communities/{key}/members",
            json=_member(key="ex-00001", subject=value),
        )

        assert r.status_code == 422, r.text
        assert await _stored(pg_session, key, "ex-00001") is None

    async def test_patch_writes_it(self, live_client, pg_session):
        """@verifies REQ-0101"""
        key = await _seed(live_client)
        await live_client.post(f"/admin/communities/{key}/members", json=_member(key="ex-00001"))

        r = await live_client.patch(
            f"/admin/communities/{key}/members/ex-00001", json={"subject": SUBJECT}
        )

        assert r.status_code == 200, r.text
        assert (await _stored(pg_session, key, "ex-00001")).subject == SUBJECT

    async def test_a_patch_that_does_not_name_it_leaves_it(self, live_client, pg_session):
        """Absent never means empty, and neither does `null`.

        @verifies REQ-0101
        """
        key = await _seed(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members",
            json=_member(key="ex-00001", subject=SUBJECT),
        )

        r1 = await live_client.patch(
            f"/admin/communities/{key}/members/ex-00001", json={"name": "Renamed"}
        )
        r2 = await live_client.patch(
            f"/admin/communities/{key}/members/ex-00001", json={"subject": None}
        )

        assert r1.status_code == 200, r1.text
        assert r2.status_code == 200, r2.text
        assert (await _stored(pg_session, key, "ex-00001")).subject == SUBJECT

    async def test_patch_refuses_a_value_that_is_not_a_uuid(self, live_client, pg_session):
        """@verifies REQ-0101"""
        key = await _seed(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members",
            json=_member(key="ex-00001", subject=SUBJECT),
        )

        r = await live_client.patch(
            f"/admin/communities/{key}/members/ex-00001",
            json={"subject": "subject.one@example.org"},
        )

        assert r.status_code == 422, r.text
        assert (await _stored(pg_session, key, "ex-00001")).subject == SUBJECT


@pytest.mark.integration
class TestTheBundlePathCarriesItToo:
    async def test_a_bundle_member_stores_it_in_the_column(self, live_client, pg_session):
        """@verifies REQ-0101"""
        key = await _seed(
            live_client, members={"ex-00001": _member(subject=SUBJECT)}
        )

        member = await _stored(pg_session, key, "ex-00001")
        assert member.subject == SUBJECT
        assert "subject" not in member.extra

    async def test_a_bundle_carrying_a_value_that_is_not_a_uuid_is_refused(
        self, live_client
    ):
        """@verifies REQ-0101"""
        bundle = {
            "version": "1.0",
            "schema_version": "0.7",
            "community": {"id": "subject-rec", "name": "S", **substation_graph("north")},
            "members": {"ex-00001": _member(subject="subject.one@example.org")},
        }

        r = await live_client.post("/admin/import", json={"bundle": bundle, "dry_run": False})

        assert r.status_code == 422, r.text

    async def test_a_subject_written_through_the_api_survives_the_round_trip(
        self, live_client, pg_session
    ):
        """Create through the API → full export → re-import: the subject is still
        on the row. The full export is the backup; a restore that dropped the
        subject would unlink every member from its account.

        @verifies REQ-0101
        """
        key = await _seed(live_client)
        created = await live_client.post(
            f"/admin/communities/{key}/members",
            json=_member(key="ex-00001", subject=SUBJECT),
        )
        assert created.status_code == 201, created.text

        exported = await live_client.get(f"/admin/export?community_key={key}")
        assert exported.status_code == 200, exported.text
        bundle = yaml.safe_load(exported.text)
        assert bundle["members"]["ex-00001"]["subject"] == SUBJECT

        reimport = await live_client.post(
            "/admin/import", json={"bundle": bundle, "dry_run": False, "force": True}
        )
        assert reimport.status_code == 200, reimport.text

        member = await _stored(pg_session, key, "ex-00001")
        assert member.subject == SUBJECT
        assert "subject" not in member.extra

    async def test_a_member_without_one_exports_no_key(self, live_client):
        """@verifies REQ-0101"""
        key = await _seed(live_client, members={"ex-00001": _member()})

        exported = await live_client.get(f"/admin/export?community_key={key}")

        assert exported.status_code == 200, exported.text
        assert "subject" not in yaml.safe_load(exported.text)["members"]["ex-00001"]


@pytest.mark.integration
class TestNothingElseReadsIt:
    """Decision: only the mirrors read the subject. The full export is the
    backup; every other read answers without it."""

    async def _seeded(self, live_client) -> str:
        return await _seed(
            live_client,
            members={
                "ex-00001": _member(
                    subject=SUBJECT, did="did:web:dataspace.example:subject-1"
                )
            },
        )

    async def test_the_admin_member_reads_do_not_carry_it(self, live_client):
        """@verifies REQ-0101"""
        key = await self._seeded(live_client)

        reads = [
            await live_client.get(f"/admin/communities/{key}/members/ex-00001"),
            await live_client.get(f"/admin/communities/{key}/members"),
            await live_client.patch(
                f"/admin/communities/{key}/members/ex-00001", json={"subject": SUBJECT}
            ),
        ]

        for r in reads:
            assert r.status_code == 200, r.text
            assert SUBJECT not in r.text
            assert '"subject"' not in r.text

    async def test_a_create_answer_does_not_carry_it(self, live_client):
        """@verifies REQ-0101"""
        key = await _seed(live_client)

        r = await live_client.post(
            f"/admin/communities/{key}/members",
            json=_member(key="ex-00001", subject=OTHER_SUBJECT),
        )

        assert r.status_code == 201, r.text
        assert OTHER_SUBJECT not in r.text

    async def test_the_lookups_do_not_carry_it(self, live_client):
        """@verifies REQ-0101"""
        await self._seeded(live_client)

        reads = [
            await live_client.get(
                "/admin/lookup/member-by-user-id/subject.one@example.org"
            ),
            await live_client.get(
                "/admin/lookup/community-by-user-id/subject.one@example.org"
            ),
            await live_client.post(
                "/admin/lookup/members-by-dids",
                json={"dids": ["did:web:dataspace.example:subject-1"]},
            ),
        ]

        for r in reads:
            assert r.status_code == 200, r.text
            assert SUBJECT not in r.text

    async def test_the_member_export_does_not_carry_it(self, live_client):
        """@verifies REQ-0101"""
        await self._seeded(live_client)

        r = await live_client.get("/admin/export/members")

        assert r.status_code == 200, r.text
        assert SUBJECT not in r.text
        assert '"subject"' not in r.text

    async def test_self_service_does_not_carry_it(self, live_client, as_user):
        """@verifies REQ-0101"""
        await self._seeded(live_client)
        # Another `sub` on the token: `/user` echoes the caller's own profile, and
        # the point is what the registry adds from the row.
        client = as_user(identifies_as("subject.one@example.org"))

        for path in ("/user", "/user/member"):
            r = await client.get(path)

            assert r.status_code == 200, r.text
            assert SUBJECT not in r.text
