"""The cross-community lookup API.

Every other admin route answers *"what is in this community"*. These answer the
question the rest of the platform actually asks — **"which community is this
in?"** — starting from a user id, a sensor id or a delivery point, none of which
the caller can map to a community on its own.

Two properties are worth more than the routes themselves, and both are security
properties wearing the clothes of ordinary behaviour:

* **both batch forms are bounded, by one shared constant** — a caller that can
  name ten thousand people in one request has a dump of the registry, not a
  lookup, and the sensor batch carried no bound at all until the two were made
  to read the same number;
* **it is not an enumeration oracle** — a user id that does not exist and a
  member who owns nothing are deliberately indistinguishable, so the endpoint
  cannot be used to discover who is registered.

Neither is visible from reading a route, and until this file existed nothing
checked either.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# =============================================================================
# Seeding
# =============================================================================


async def _seed(client, key: str = "lookup-rec") -> str:
    """A community with two members, each owning one meter.

    Built through the bundle importer rather than the write API: the lookups
    read columns the importer fills, and seeding this way keeps the fixture one
    request instead of six.
    """
    bundle = {
        "version": "1.0",
        "schema_version": "0.5",
        "community": {
            "id": key,
            "name": "Lookup Community",
            "areas": {"north": {"name": "north"}},
        },
        "members": {
            "lk-00001": {
                "user_id": "kc-alice",
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
                    }
                },
            },
            "lk-00002": {
                "user_id": "kc-bob",
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


# =============================================================================
# Single lookups
# =============================================================================


@pytest.mark.integration
class TestCommunityLookups:
    async def test_community_by_user_id(self, live_client):
        """@verifies REQ-0038"""
        key = await _seed(live_client)

        r = await live_client.get("/admin/lookup/community-by-user-id/kc-alice")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["community"]["key"] == key
        assert body["member"]["key"] == "lk-00001"
        assert body["member"]["role"] == "prosumer"

    async def test_unknown_user_id_is_404(self, live_client):
        """@verifies REQ-0038"""
        await _seed(live_client)

        r = await live_client.get("/admin/lookup/community-by-user-id/kc-nobody")

        assert r.status_code == 404

    async def test_community_by_sensor_id(self, live_client):
        """@verifies REQ-0039"""
        key = await _seed(live_client)

        r = await live_client.get("/admin/lookup/community-by-sensor-id/sen-bob")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["community"]["key"] == key
        # The whole point: a sensor id resolves to its owner, not just its
        # community. A reading arrives carrying nothing else.
        assert body["member"]["user_id"] == "kc-bob"
        assert body["asset"]["key"] == "meter-bob"

    async def test_unknown_sensor_id_is_404(self, live_client):
        """@verifies REQ-0039"""
        await _seed(live_client)

        r = await live_client.get("/admin/lookup/community-by-sensor-id/sen-nothing")

        assert r.status_code == 404

    async def test_community_by_delivery_point(self, live_client):
        """@verifies REQ-0040"""
        key = await _seed(live_client)

        r = await live_client.get(
            "/admin/lookup/community-by-delivery-point/IT-DP-ALICE"
        )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["community"]["key"] == key
        assert body["member"]["user_id"] == "kc-alice"
        assert body["delivery_point"]["id"] == "IT-DP-ALICE"

    async def test_unknown_delivery_point_is_404(self, live_client):
        """@verifies REQ-0040"""
        await _seed(live_client)

        r = await live_client.get("/admin/lookup/community-by-delivery-point/IT-NOPE")

        assert r.status_code == 404


@pytest.mark.integration
class TestGlobalLookups:
    async def test_member_by_user_id_carries_its_community(self, live_client):
        """@verifies REQ-0041"""
        key = await _seed(live_client)

        r = await live_client.get("/admin/lookup/member-by-user-id/kc-alice")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["key"] == "lk-00001"
        assert body["community_key"] == key
        assert [dp["id"] for dp in body["delivery_points"]] == ["IT-DP-ALICE"]

    async def test_unknown_member_is_404(self, live_client):
        """@verifies REQ-0041"""
        await _seed(live_client)

        r = await live_client.get("/admin/lookup/member-by-user-id/kc-nobody")

        assert r.status_code == 404

    async def test_asset_by_sensor_id_carries_its_owner(self, live_client):
        """@verifies REQ-0042"""
        key = await _seed(live_client)

        r = await live_client.get("/admin/lookup/asset-by-sensor-id/sen-alice")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["key"] == "meter-alice"
        assert body["owner_key"] == "lk-00001"
        assert body["owner_user_id"] == "kc-alice"
        assert body["community_key"] == key

    async def test_unknown_asset_is_404(self, live_client):
        """@verifies REQ-0042"""
        await _seed(live_client)

        r = await live_client.get("/admin/lookup/asset-by-sensor-id/sen-nothing")

        assert r.status_code == 404


# =============================================================================
# Batch lookups
# =============================================================================


@pytest.mark.integration
class TestAssetsBySensorIds:
    async def test_resolves_several_at_once(self, live_client):
        """@verifies REQ-0043"""
        await _seed(live_client)

        r = await live_client.post(
            "/admin/lookup/assets-by-sensor-ids",
            json={"sensor_ids": ["sen-alice", "sen-bob"]},
        )

        assert r.status_code == 200, r.text
        assert sorted(a["sensor_id"] for a in r.json()) == ["sen-alice", "sen-bob"]

    async def test_an_unknown_sensor_id_contributes_nothing(self, live_client):
        """A partial answer, not a 404: the caller asked about a set, and one
        missing member of it does not make the rest unanswerable.

        @verifies REQ-0043
        """
        await _seed(live_client)

        r = await live_client.post(
            "/admin/lookup/assets-by-sensor-ids",
            json={"sensor_ids": ["sen-alice", "sen-nothing"]},
        )

        assert r.status_code == 200
        assert [a["sensor_id"] for a in r.json()] == ["sen-alice"]

    async def test_an_empty_request_returns_an_empty_list(self, live_client):
        """@verifies REQ-0043"""
        await _seed(live_client)

        r = await live_client.post(
            "/admin/lookup/assets-by-sensor-ids", json={"sensor_ids": []}
        )

        assert r.status_code == 200
        assert r.json() == []

    async def test_the_request_is_bounded(self, live_client):
        """This route carried no bound at all while its sibling capped at 500,
        and both are reachable by anything holding `rec-registry.lookup`.

        Sensor ids are less guessable than usernames, so this was the weaker
        enumeration path — but not the weaker bulk-extraction one, which is what
        a bound is for.

        @verifies REQ-0043
        """
        await _seed(live_client)

        r = await live_client.post(
            "/admin/lookup/assets-by-sensor-ids",
            json={"sensor_ids": [f"sen-{n}" for n in range(501)]},
        )

        assert r.status_code == 422

    async def test_the_bound_itself_is_accepted(self, live_client):
        """500 inclusive, pinned so a refactor cannot quietly make it 499.

        @verifies REQ-0043
        """
        await _seed(live_client)

        r = await live_client.post(
            "/admin/lookup/assets-by-sensor-ids",
            json={"sensor_ids": [f"sen-{n}" for n in range(500)]},
        )

        assert r.status_code == 200



@pytest.mark.integration
class TestAssetsByUserIds:
    """The mirror of the sensor batch: that one starts from a device and finds
    its owner, this one starts from owners and finds their devices.

    It exists because a dataspace query is authorised for a *set of people* —
    the subjects who consented — and the self-service route can only ever answer
    "mine".
    """

    async def test_resolves_assets_for_several_members(self, live_client):
        """@verifies REQ-0044"""
        await _seed(live_client)

        r = await live_client.post(
            "/admin/lookup/assets-by-user-ids",
            json={"user_ids": ["kc-alice", "kc-bob"]},
        )

        assert r.status_code == 200, r.text
        assert sorted(a["key"] for a in r.json()) == ["meter-alice", "meter-bob"]

    async def test_every_row_names_the_member_it_belongs_to(self, live_client):
        """Without `owner_user_id` the caller cannot attribute a row back to the
        person it asked about, which is the entire purpose of a batch form.

        @verifies REQ-0044
        """
        await _seed(live_client)

        r = await live_client.post(
            "/admin/lookup/assets-by-user-ids", json={"user_ids": ["kc-alice"]}
        )

        assert [a["owner_user_id"] for a in r.json()] == ["kc-alice"]

    async def test_an_empty_request_returns_an_empty_list(self, live_client):
        """@verifies REQ-0044"""
        await _seed(live_client)

        r = await live_client.post(
            "/admin/lookup/assets-by-user-ids", json={"user_ids": []}
        )

        assert r.status_code == 200
        assert r.json() == []

    async def test_a_stranger_is_indistinguishable_from_someone_who_owns_nothing(
        self, live_client
    ):
        """The no-enumeration-oracle property, and the reason it is not a 404.

        The caller supplies the ids, so **any** difference between "no such
        member" and "that member owns nothing" would turn this endpoint into a
        way to discover who is registered — against a service whose rows are
        real people.

        @verifies REQ-0045
        """
        key = await _seed(live_client)
        # A real member of the community who happens to own no assets.
        created = await live_client.post(
            f"/admin/communities/{key}/members",
            json={
                "user_id": "kc-carol",
                "name": "Carol",
                "role": "consumer",
                "area": "north",
                "status": "active",
            },
        )
        assert created.status_code == 201, created.text

        stranger = await live_client.post(
            "/admin/lookup/assets-by-user-ids", json={"user_ids": ["kc-nobody"]}
        )
        owns_nothing = await live_client.post(
            "/admin/lookup/assets-by-user-ids", json={"user_ids": ["kc-carol"]}
        )

        assert stranger.status_code == owns_nothing.status_code == 200
        assert stranger.json() == owns_nothing.json() == []

    async def test_the_request_is_bounded(self, live_client):
        """A caller that can name ten thousand people in one request has a dump
        of the registry rather than a lookup, and the route is reachable by
        anything holding `rec-registry.lookup`.

        Raising this bound widens a data-exfiltration path; it is a security
        decision wearing the clothes of a validation constant.

        @verifies REQ-0045
        """
        await _seed(live_client)

        r = await live_client.post(
            "/admin/lookup/assets-by-user-ids",
            json={"user_ids": [f"kc-{n}" for n in range(501)]},
        )

        assert r.status_code == 422

    async def test_the_bound_itself_is_accepted(self, live_client):
        """The limit is 500 inclusive — pinned so that a refactor cannot quietly
        turn it into 499 or 501.

        @verifies REQ-0045
        """
        await _seed(live_client)

        r = await live_client.post(
            "/admin/lookup/assets-by-user-ids",
            json={"user_ids": [f"kc-{n}" for n in range(500)]},
        )

        assert r.status_code == 200


# =============================================================================
# The bound itself — no database, so it runs everywhere the suite does
# =============================================================================


class TestBothBatchesCarryTheSameBound:
    """The asymmetry this closed was accidental: the bound arrived with the
    newer endpoint and was not applied to the older one.

    Two literals would let that happen again, so both models read one constant.
    Deliberately outside the `integration` classes above — it needs no database,
    and a check against drift that only runs where a database is reachable is a
    check that is not running most of the time.
    """

    @staticmethod
    def _bound(model, field: str) -> int:
        (constraint,) = [
            m for m in model.model_fields[field].metadata if hasattr(m, "max_length")
        ]
        return constraint.max_length

    def test_the_two_batch_models_agree(self):
        """@verifies REQ-0043"""
        from celine.rec_registry.schemas.models import (
            SensorIdsBatchRequest,
            UserIdsBatchRequest,
        )

        assert self._bound(SensorIdsBatchRequest, "sensor_ids") == self._bound(
            UserIdsBatchRequest, "user_ids"
        )

    def test_both_read_the_shared_constant(self):
        """@verifies REQ-0043"""
        from celine.rec_registry.schemas.models import (
            MAX_BATCH_LOOKUP_IDS,
            SensorIdsBatchRequest,
        )

        assert self._bound(SensorIdsBatchRequest, "sensor_ids") == MAX_BATCH_LOOKUP_IDS
