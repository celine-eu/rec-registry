"""The self-service API — what a participant may see about themselves.

The module it tests opens with the claim *"Security: Does NOT expose information
about other users"*, and until this file existed nothing checked it. That is the
wrong claim to leave unverified: it is the only thing standing between one
participant and another's meters, and it is enforced not by a policy rule but by
a `WHERE owner_id = <the member we resolved>` in each of five routes. A sixth
route added without it would look exactly like the others.

So every test here is written as a **pair or a contrast**: what the caller sees,
and what the caller does not.

## The identity trap

These routes resolve their member with `JwtUser.get_username()`, which is
`preferred_username` — **not** `sub`. So `Member.user_id` holds a Keycloak
*username*, and a token carrying only a subject matches no member at all,
answering `403` to somebody who is a perfectly good member. The last class here
pins that, because it is the failure an operator would misread as a data problem.
"""

from __future__ import annotations

import pytest

from tests.conftest import identifies_as

pytestmark = pytest.mark.asyncio


ALICE = "kc-alice"
BOB = "kc-bob"


async def _seed(client, key: str = "user-rec") -> str:
    """Two members of one community, each with a meter and a supply point.

    Two, always: a test that shows a participant their own data proves nothing
    unless somebody else's data is also present to have been excluded.
    """
    bundle = {
        "version": "1.0",
        "schema_version": "0.5",
        "community": {
            "id": key,
            "name": "Self Service Community",
            "description": "A community",
            "areas": {"north": {"name": "north"}},
            "settings": {"timezone": "Europe/Rome", "currency": "EUR"},
        },
        "members": {
            "us-00001": {
                "user_id": ALICE,
                "name": "Alice",
                "role": "prosumer",
                "area": "north",
                "status": "active",
                "delivery_points": [{"id": "IT-DP-ALICE", "type": "pod"}],
                "assets": {
                    "meter": {
                        "meter-alice": {
                            "name": "Alice Meter",
                            "sensor_id": "sen-alice",
                            "meter_type": "bidirectional",
                        }
                    },
                    "pv": {
                        "pv-alice": {"name": "Alice PV", "capacity_kwp": 4.5},
                    },
                },
            },
            "us-00002": {
                "user_id": BOB,
                "name": "Bob",
                "role": "consumer",
                "area": "north",
                "status": "active",
                "delivery_points": [{"id": "IT-DP-BOB", "type": "pod"}],
                "assets": {
                    "meter": {
                        "meter-bob": {
                            "name": "Bob Meter",
                            "sensor_id": "sen-bob",
                            "meter_type": "consumption",
                        }
                    }
                },
            },
        },
    }
    r = await client.post(
        "/admin/import", json={"bundle": bundle, "dry_run": False, "force": True}
    )
    assert r.status_code == 200, r.text
    return key


@pytest.mark.integration
class TestProfile:
    async def test_a_member_sees_their_membership(self, live_client, as_user):
        """@verifies REQ-0046"""
        await _seed(live_client)

        r = await as_user(identifies_as(ALICE)).get("/user")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["profile"]["preferred_username"] == ALICE
        assert body["membership"]["member"]["key"] == "us-00001"
        assert body["membership"]["community"]["key"] == "user-rec"

    async def test_asset_counts_are_by_type_and_own_only(self, live_client, as_user):
        """Alice has one meter and one PV; Bob's meter is not hers to count.

        @verifies REQ-0046
        """
        await _seed(live_client)

        r = await as_user(identifies_as(ALICE)).get("/user")

        assert r.json()["membership"]["assets_count"] == {"meter": 1, "pv": 1}
        assert r.json()["membership"]["delivery_points_count"] == 1

    async def test_a_stranger_gets_a_profile_with_no_membership(
        self, live_client, as_user
    ):
        """Not a 403. The caller holds a valid token and is simply not a member
        of anything — which is what an onboarding app asks this route to find
        out, and it must be able to ask before the answer is yes.

        @verifies REQ-0047
        """
        await _seed(live_client)

        r = await as_user(identifies_as("kc-stranger")).get("/user")

        assert r.status_code == 200
        assert r.json()["membership"] is None
        assert r.json()["profile"]["preferred_username"] == "kc-stranger"


@pytest.mark.integration
class TestMemberAndCommunity:
    async def test_member_detail_is_the_callers_own(self, live_client, as_user):
        """@verifies REQ-0048"""
        await _seed(live_client)

        r = await as_user(identifies_as(BOB)).get("/user/member")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["key"] == "us-00002"
        assert [dp["id"] for dp in body["delivery_points"]] == ["IT-DP-BOB"]
        # The route deliberately omits user_id — the caller already knows it, and
        # every field not returned is a field that cannot leak.
        assert "user_id" not in body

    async def test_community_detail_carries_the_callers_place_in_it(
        self, live_client, as_user
    ):
        """@verifies REQ-0049"""
        await _seed(live_client)

        r = await as_user(identifies_as(ALICE)).get("/user/community")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["key"] == "user-rec"
        assert body["your_area"] == "north"
        assert body["your_role"] == "prosumer"
        # Community-level detail is shared by every member, so it is not scoped.
        assert set(body["areas"]) == {"north"}
        # But the member list is not part of it: knowing your community must not
        # mean enumerating everybody in it.
        assert "members" not in body

    @pytest.mark.parametrize("route", ["/user/member", "/user/community"])
    async def test_a_stranger_is_refused(self, live_client, as_user, route):
        """@verifies REQ-0047"""
        await _seed(live_client)

        r = await as_user(identifies_as("kc-stranger")).get(route)

        assert r.status_code == 403


@pytest.mark.integration
class TestAssets:
    async def test_only_the_callers_own_assets_are_listed(self, live_client, as_user):
        """@verifies REQ-0050"""
        await _seed(live_client)

        r = await as_user(identifies_as(ALICE)).get("/user/assets")

        assert r.status_code == 200, r.text
        keys = [a["key"] for a in r.json()["items"]]
        assert keys == ["meter-alice", "pv-alice"]
        assert "meter-bob" not in keys
        assert r.json()["total"] == 2

    async def test_the_type_filter_narrows_within_the_callers_own(
        self, live_client, as_user
    ):
        """@verifies REQ-0050"""
        await _seed(live_client)

        r = await as_user(identifies_as(ALICE)).get(
            "/user/assets", params={"asset_type": "meter"}
        )

        assert [a["key"] for a in r.json()["items"]] == ["meter-alice"]

    async def test_another_members_asset_is_not_found_rather_than_forbidden(
        self, live_client, as_user
    ):
        """Bob's meter exists, and to Alice it must be indistinguishable from a
        meter that does not — a `403` would confirm the key names something real.

        @verifies REQ-0051
        """
        await _seed(live_client)
        alice = as_user(identifies_as(ALICE))

        theirs = await alice.get("/user/assets/meter-bob")
        imaginary = await alice.get("/user/assets/meter-does-not-exist")

        assert theirs.status_code == 404
        assert imaginary.status_code == 404
        assert theirs.json() == imaginary.json()

    async def test_the_callers_own_asset_is_returned_in_full(
        self, live_client, as_user
    ):
        """@verifies REQ-0051"""
        await _seed(live_client)

        r = await as_user(identifies_as(ALICE)).get("/user/assets/meter-alice")

        assert r.status_code == 200, r.text
        assert r.json()["sensor_id"] == "sen-alice"


@pytest.mark.integration
class TestDeliveryPoints:
    async def test_only_the_callers_own_are_listed(self, live_client, as_user):
        """@verifies REQ-0052"""
        await _seed(live_client)

        r = await as_user(identifies_as(BOB)).get("/user/delivery-points")

        assert r.status_code == 200, r.text
        assert [dp["id"] for dp in r.json()["items"]] == ["IT-DP-BOB"]
        assert r.json()["total"] == 1


@pytest.mark.integration
class TestIdentityIsTheUsernameNotTheSubject:
    """`Member.user_id` holds a Keycloak *username*, not a subject UUID.

    Worth its own class because the failure is silently wrong rather than loud:
    a member with a correct row is told they belong to nothing, and the operator
    reading that `403` looks at the registry rather than at the token.
    """

    async def test_the_member_is_resolved_by_preferred_username(
        self, live_client, as_user
    ):
        """@verifies REQ-0053"""
        await _seed(live_client)
        from celine.sdk.auth import JwtUser

        # A token whose subject is somebody else's username entirely: if `sub`
        # were what these routes matched on, this would come back as Bob.
        token = JwtUser(sub=BOB, preferred_username=ALICE)

        r = await as_user(token).get("/user/member")

        assert r.status_code == 200
        assert r.json()["key"] == "us-00001"

    async def test_a_token_with_no_username_matches_nobody(self, live_client, as_user):
        """`get_username()` falls back to `user-<sub>`, which matches no member
        — so the fallback is not a fallback, it is a guaranteed miss.

        @verifies REQ-0053
        """
        await _seed(live_client)
        from celine.sdk.auth import JwtUser

        r = await as_user(JwtUser(sub=ALICE)).get("/user/member")

        assert r.status_code == 403
