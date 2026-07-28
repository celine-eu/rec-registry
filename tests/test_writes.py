"""The admin write API.

Before this existed the registry could only be replaced wholesale: the entire
write surface was a replacement import that deletes a community and recreates
it. That was fine while a YAML file was the only source of members, and stopped
being fine the moment a manager could approve somebody at 14:32 on a Tuesday.

The rules these tests pin are the ones that are easy to lose:

* a write never reduces a sibling;
* deactivating a member is not the same as erasing one;
* JSONB collections merge by identity, not by position;
* a community exports the same whether its members arrived by API or by bundle.
"""

from __future__ import annotations

import pytest

from celine.rec_registry.schemas.bundle import DeliveryPointIn, MemberIn
from celine.rec_registry.services import members as member_service

pytestmark = pytest.mark.asyncio


# =============================================================================
# Key minting — pure, no database
# =============================================================================


class TestMemberKeyMinting:
    def test_follows_the_communitys_own_numbering(self):
        """A caller with no opinion should get the next key in the series, not a
        UUID that reads as foreign in an exported bundle."""
        assert member_service.next_member_key(["gl-00001", "gl-00002"]) == "gl-00003"

    def test_keeps_the_observed_zero_padding(self):
        assert member_service.next_member_key(["ab-007"]) == "ab-008"

    def test_starts_a_fresh_community_at_one(self):
        assert member_service.next_member_key([]) == "member-00001"

    def test_ignores_keys_that_are_not_numbered(self):
        assert member_service.next_member_key(["founder", "gl-00004"]) == "gl-00005"

    def test_gaps_do_not_reuse_a_key(self):
        """Reusing a freed number would hand a new person the identity of one who
        left — and their history elsewhere in the platform."""
        assert member_service.next_member_key(["gl-00001", "gl-00009"]) == "gl-00010"


# =============================================================================
# Delivery point merging — pure, no database
# =============================================================================


class TestDeliveryPointMerge:
    def _dp(self, id_: str, **kw):
        return DeliveryPointIn(id=id_, type="pod", **kw)

    def test_a_second_supply_point_does_not_replace_the_first(self):
        """The whole reason delivery points are a sub-resource: they live in one
        JSONB column, and a naive whole-field write drops the others."""
        existing = member_service.build_delivery_points([self._dp("IT001")])
        merged = member_service.merge_delivery_point(existing, self._dp("IT002"))

        assert [dp["id"] for dp in merged] == ["IT001", "IT002"]

    def test_resending_one_updates_rather_than_duplicates(self):
        existing = member_service.build_delivery_points(
            [self._dp("IT001", description="old")]
        )
        merged = member_service.merge_delivery_point(
            existing, self._dp("IT001", description="new")
        )

        assert len(merged) == 1
        assert merged[0]["description"] == "new"

    def test_removal_keeps_the_others(self):
        existing = member_service.build_delivery_points(
            [self._dp("IT001"), self._dp("IT002")]
        )
        assert [
            dp["id"] for dp in member_service.remove_delivery_point(existing, "IT001")
        ] == ["IT002"]

    def test_merge_does_not_mutate_the_input(self):
        existing = member_service.build_delivery_points([self._dp("IT001")])
        member_service.merge_delivery_point(existing, self._dp("IT002"))
        assert len(existing) == 1


# =============================================================================
# Live database
# =============================================================================


def _member_payload(**overrides) -> dict:
    payload = {
        "user_id": "kc-0001",
        "name": "Test Member",
        "type": "schema:Person",
        "role": "consumer",
        "area": "north",
        "status": "active",
        "delivery_points": [{"id": "IT001E00000001", "type": "pod"}],
    }
    payload.update(overrides)
    return payload


async def _seed_community(client, key: str = "test-rec", areas=("north", "south")):
    bundle = {
        "version": "1.0",
        "schema_version": "0.5",
        "community": {
            "id": key,
            "name": "Test Community",
            "areas": {a: {"name": a} for a in areas},
        },
        "members": {},
    }
    r = await client.post("/admin/import", json={"bundle": bundle, "dry_run": False})
    assert r.status_code == 200, r.text
    return key


@pytest.mark.integration
class TestMemberWrites:
    async def test_create_returns_the_member(self, live_client):
        key = await _seed_community(live_client)

        r = await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload()
        )

        assert r.status_code == 201, r.text
        body = r.json()
        assert body["user_id"] == "kc-0001"
        assert body["key"] == "member-00001"
        assert [dp["id"] for dp in body["delivery_points"]] == ["IT001E00000001"]

    async def test_supplied_key_is_honoured(self, live_client):
        key = await _seed_community(live_client)

        r = await live_client.post(
            f"/admin/communities/{key}/members",
            json=_member_payload(key="gl-00042"),
        )

        assert r.status_code == 201
        assert r.json()["key"] == "gl-00042"

    async def test_duplicate_key_is_refused(self, live_client):
        """Creating must not silently update: a retry with a changed payload
        would otherwise rewrite the wrong person."""
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="gl-00001")
        )

        r = await live_client.post(
            f"/admin/communities/{key}/members",
            json=_member_payload(key="gl-00001", user_id="kc-0002"),
        )

        assert r.status_code == 409
        assert "gl-00001" in r.json()["detail"]

    async def test_duplicate_user_id_is_refused(self, live_client):
        key = await _seed_community(live_client)
        await live_client.post(f"/admin/communities/{key}/members", json=_member_payload())

        r = await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="other")
        )

        assert r.status_code == 409
        assert "kc-0001" in r.json()["detail"]

    async def test_unknown_community_is_404(self, live_client):
        r = await live_client.post(
            "/admin/communities/nope/members", json=_member_payload()
        )
        assert r.status_code == 404

    async def test_patch_leaves_absent_fields_alone(self, live_client):
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="m1")
        )

        r = await live_client.patch(
            f"/admin/communities/{key}/members/m1", json={"name": "Renamed"}
        )

        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Renamed"
        assert body["role"] == "consumer"
        # The sharpest case: a patch that does not mention delivery points must
        # not read as "this member now has none".
        assert [dp["id"] for dp in body["delivery_points"]] == ["IT001E00000001"]

    async def test_patch_cannot_steal_another_members_user_id(self, live_client):
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="m1")
        )
        await live_client.post(
            f"/admin/communities/{key}/members",
            json=_member_payload(key="m2", user_id="kc-0002", delivery_points=[]),
        )

        r = await live_client.patch(
            f"/admin/communities/{key}/members/m2", json={"user_id": "kc-0001"}
        )

        assert r.status_code == 409

    async def test_status_transition(self, live_client):
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="m1")
        )

        r = await live_client.post(
            f"/admin/communities/{key}/members/m1/status",
            json={"status": "suspended", "reason": "non-payment"},
        )

        assert r.status_code == 200
        assert r.json()["status"] == "suspended"
        assert r.json()["extra"]["status_reason"] == "non-payment"

    async def test_unknown_status_is_refused(self, live_client):
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="m1")
        )

        r = await live_client.post(
            f"/admin/communities/{key}/members/m1/status", json={"status": "retired"}
        )

        assert r.status_code == 422


@pytest.mark.integration
class TestDeletion:
    async def test_delete_deactivates_by_default(self, live_client):
        """A member who leaves still has metering history, past consents and
        provenance elsewhere that reference them — and Asset cascades on a real
        delete, so it would silently take their meters too."""
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="m1")
        )

        r = await live_client.delete(f"/admin/communities/{key}/members/m1")

        assert r.status_code == 200
        assert r.json() == {
            "community_key": key,
            "member_key": "m1",
            "purged": False,
            "status": "inactive",
            "assets_removed": 0,
        }
        # Still there, still readable.
        again = await live_client.get(f"/admin/communities/{key}/members/m1")
        assert again.status_code == 200

    async def test_purge_removes_the_member(self, live_client):
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="m1")
        )

        r = await live_client.delete(f"/admin/communities/{key}/members/m1?purge=true")

        assert r.status_code == 200
        assert r.json()["purged"] is True
        gone = await live_client.get(f"/admin/communities/{key}/members/m1")
        assert gone.status_code == 404

    async def test_purge_reports_the_assets_it_took(self, live_client):
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="m1")
        )
        await live_client.put(
            f"/admin/communities/{key}/members/m1/assets/meter-1",
            json={
                "key": "meter-1",
                "asset_type": "meter",
                "properties": {
                    "name": "Meter 1",
                    "sensor_id": "s-1",
                    "meter_type": "consumption",
                },
            },
        )

        r = await live_client.delete(f"/admin/communities/{key}/members/m1?purge=true")

        assert r.json()["assets_removed"] == 1


@pytest.mark.integration
class TestDeliveryPointRoutes:
    async def test_adding_a_second_point_keeps_the_first(self, live_client):
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="m1")
        )

        r = await live_client.put(
            f"/admin/communities/{key}/members/m1/delivery-points/IT002",
            json={"id": "IT002", "type": "pod", "description": "Second"},
        )

        assert r.status_code == 200
        assert [dp["id"] for dp in r.json()["delivery_points"]] == [
            "IT001E00000001",
            "IT002",
        ]

    async def test_body_id_must_match_the_path(self, live_client):
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="m1")
        )

        r = await live_client.put(
            f"/admin/communities/{key}/members/m1/delivery-points/IT002",
            json={"id": "IT999", "type": "pod"},
        )

        assert r.status_code == 422

    async def test_removing_an_unknown_point_is_404(self, live_client):
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="m1")
        )

        r = await live_client.delete(
            f"/admin/communities/{key}/members/m1/delivery-points/IT999"
        )

        assert r.status_code == 404


@pytest.mark.integration
class TestAssetRoutes:
    def _meter(self, key="meter-1", sensor="s-1"):
        return {
            "key": key,
            "asset_type": "meter",
            "properties": {
                "name": "Meter",
                "sensor_id": sensor,
                "meter_type": "consumption",
            },
        }

    async def test_upsert_creates_then_replaces(self, live_client):
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="m1")
        )
        base = f"/admin/communities/{key}/members/m1/assets/meter-1"

        created = await live_client.put(base, json=self._meter())
        assert created.status_code == 200
        r = await live_client.put(base, json=self._meter(sensor="s-2"))

        assert r.status_code == 200
        assert r.json()["sensor_id"] == "s-2"

    async def test_a_second_asset_does_not_replace_the_first(self, live_client):
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="m1")
        )
        await live_client.put(
            f"/admin/communities/{key}/members/m1/assets/meter-1",
            json=self._meter("meter-1", "s-1"),
        )
        await live_client.put(
            f"/admin/communities/{key}/members/m1/assets/meter-2",
            json=self._meter("meter-2", "s-2"),
        )

        listing = await live_client.get(
            f"/admin/communities/{key}/assets", params={"owner": "m1"}
        )
        assert listing.status_code == 200
        assert len(listing.json()["items"]) == 2

    async def test_wrong_type_for_the_payload_is_refused(self, live_client):
        """An EV charger must not be storable carrying a heat pump's fields."""
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="m1")
        )

        r = await live_client.put(
            f"/admin/communities/{key}/members/m1/assets/ev-1",
            json={
                "key": "ev-1",
                "asset_type": "ev_charger",
                "properties": {"name": "Charger"},  # missing max_power/charger_type
            },
        )

        assert r.status_code == 422

    async def test_unknown_asset_type_names_the_valid_ones(self, live_client):
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="m1")
        )

        r = await live_client.put(
            f"/admin/communities/{key}/members/m1/assets/x",
            json={"key": "x", "asset_type": "reactor", "properties": {"name": "X"}},
        )

        assert r.status_code == 422
        assert "meter" in r.json()["detail"]


@pytest.mark.integration
class TestCommunityWrites:
    async def test_patch_metadata_keeps_areas(self, live_client):
        key = await _seed_community(live_client)

        r = await live_client.patch(
            f"/admin/communities/{key}", json={"description": "Updated"}
        )

        assert r.status_code == 200
        assert r.json()["description"] == "Updated"
        assert set(r.json()["areas"]) == {"north", "south"}

    async def test_upserting_an_area_keeps_the_others(self, live_client):
        key = await _seed_community(live_client)

        r = await live_client.put(
            f"/admin/communities/{key}/areas/east", json={"name": "East"}
        )

        assert r.status_code == 200
        assert set(r.json()["areas"]) == {"north", "south", "east"}

    async def test_area_in_use_cannot_be_deleted(self, live_client):
        """An orphaned Member.area is a dangling reference nothing else checks;
        it would surface much later as a member of an area that does not exist."""
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="m1")
        )

        r = await live_client.delete(f"/admin/communities/{key}/areas/north")

        assert r.status_code == 409
        assert "member" in r.json()["detail"]

    async def test_unused_area_can_be_deleted(self, live_client):
        key = await _seed_community(live_client)

        r = await live_client.delete(f"/admin/communities/{key}/areas/south")

        assert r.status_code == 200
        assert set(r.json()["areas"]) == {"north"}


@pytest.mark.integration
class TestNoWriteReducesASibling:
    """The invariant the whole module exists to protect.

    Every write is exercised against a community with two members, and the
    member count is checked afterwards. If any endpoint ever gains
    collection-replace semantics, this fails.
    """

    async def test_member_count_survives_every_write(self, live_client):
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="m1")
        )
        await live_client.post(
            f"/admin/communities/{key}/members",
            json=_member_payload(key="m2", user_id="kc-0002", delivery_points=[]),
        )

        async def count() -> int:
            listing = await live_client.get(f"/admin/communities/{key}/members")
            return len(listing.json()["items"])

        assert await count() == 2

        await live_client.patch(f"/admin/communities/{key}/members/m1", json={"name": "A"})
        await live_client.post(
            f"/admin/communities/{key}/members/m1/status", json={"status": "suspended"}
        )
        await live_client.put(
            f"/admin/communities/{key}/members/m1/delivery-points/IT777",
            json={"id": "IT777", "type": "pod"},
        )
        await live_client.put(
            f"/admin/communities/{key}/members/m1/assets/meter-1",
            json={
                "key": "meter-1",
                "asset_type": "meter",
                "properties": {
                    "name": "M",
                    "sensor_id": "s-9",
                    "meter_type": "consumption",
                },
            },
        )
        await live_client.patch(f"/admin/communities/{key}", json={"description": "d"})
        await live_client.put(f"/admin/communities/{key}/areas/west", json={"name": "West"})
        await live_client.delete(f"/admin/communities/{key}/members/m2")  # soft

        assert await count() == 2


@pytest.mark.integration
class TestRoundTrip:
    """A community must export the same whether its members arrived by API or
    by bundle — otherwise a `git`-driven re-import silently reverts weeks of
    approvals, and the two write paths have quietly diverged."""

    async def test_api_created_member_survives_export_and_reimport(self, live_client):
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members",
            json=_member_payload(key="gl-00001", name="Round Trip"),
        )
        await live_client.put(
            f"/admin/communities/{key}/members/gl-00001/assets/meter-1",
            json={
                "key": "meter-1",
                "asset_type": "meter",
                "properties": {
                    "name": "Meter 1",
                    "sensor_id": "sensor-rt",
                    "meter_type": "bidirectional",
                },
            },
        )

        exported = await live_client.get(f"/admin/export?community_key={key}")
        assert exported.status_code == 200, exported.text

        import yaml

        bundle = yaml.safe_load(exported.text)
        reimport = await live_client.post(
            "/admin/import", json={"bundle": bundle, "dry_run": False, "force": True}
        )
        assert reimport.status_code == 200, reimport.text

        member = await live_client.get(f"/admin/communities/{key}/members/gl-00001")
        assert member.status_code == 200, "the API-created member did not survive"
        assert member.json()["name"] == "Round Trip"
        assert [dp["id"] for dp in member.json()["delivery_points"]] == [
            "IT001E00000001"
        ]

        assets = await live_client.get(
            f"/admin/communities/{key}/assets", params={"owner": "gl-00001"}
        )
        assert [a["sensor_id"] for a in assets.json()["items"]] == ["sensor-rt"]


@pytest.mark.integration
class TestImportGuard:
    async def test_overwriting_a_live_community_is_refused(self, live_client):
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="m1")
        )

        bundle = {
            "version": "1.0",
            "schema_version": "0.5",
            "community": {"id": key, "name": "Replacement", "areas": {}},
            "members": {},
        }
        r = await live_client.post("/admin/import", json={"bundle": bundle, "dry_run": False})

        assert r.status_code == 409
        assert "1 member" in r.json()["detail"]
        # And the member is still there.
        again = await live_client.get(f"/admin/communities/{key}/members/m1")
        assert again.status_code == 200

    async def test_force_accepts_the_loss(self, live_client):
        key = await _seed_community(live_client)
        await live_client.post(
            f"/admin/communities/{key}/members", json=_member_payload(key="m1")
        )

        bundle = {
            "version": "1.0",
            "schema_version": "0.5",
            "community": {"id": key, "name": "Replacement", "areas": {}},
            "members": {},
        }
        r = await live_client.post(
            "/admin/import", json={"bundle": bundle, "dry_run": False, "force": True}
        )

        assert r.status_code == 200
        gone = await live_client.get(f"/admin/communities/{key}/members/m1")
        assert gone.status_code == 404
