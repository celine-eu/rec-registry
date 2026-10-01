"""A member's name, role and area each have their own route (REQ-0083).

`PUT …/members/{mk}/name|role|area` with a one-key body, each deriving its own
action (REQ-0081) so that a service can be granted one field and nothing more
(REQ-0082). The values are held to the same checks as on the general `PATCH`
(REQ-0066): the narrow door is not a looser one.

Fixtures are generic: `example-rec`, `ex-0000n`, `IT001E…`.
"""

from __future__ import annotations

import pytest

from tests.substations import substation_graph

pytestmark = pytest.mark.asyncio

C = "example-rec"


def _bundle(key: str = C) -> dict:
    return {
        "version": "1.0",
        "schema_version": "0.7",
        "community": {
            "id": key,
            "name": "Example Community",
            **substation_graph("north", "south"),
        },
        "members": {},
    }


async def _community(client, key: str = C) -> str:
    r = await client.post("/admin/import", json={"bundle": _bundle(key)})
    assert r.status_code == 200, r.text
    return key


async def _add(client, key: str, n: int, community: str = C) -> dict:
    r = await client.post(
        f"/admin/communities/{community}/members",
        json={
            "key": key,
            "user_id": f"kc-{n:04d}",
            "name": "Example Member",
            "role": "consumer",
            "area": "north",
            "status": "active",
            "delivery_points": [{"id": f"IT001E{n:08d}", "type": "pod"}],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _get(client, key: str, community: str = C) -> dict:
    r = await client.get(f"/admin/communities/{community}/members/{key}")
    assert r.status_code == 200, r.text
    return r.json()


def _stable(member: dict) -> dict:
    return {k: v for k, v in member.items() if k not in ("updated_at",)}


@pytest.mark.integration
class TestEachFieldHasItsRoute:
    @pytest.mark.parametrize(
        "field,value",
        [("name", "Another Name"), ("role", "prosumer"), ("area", "south")],
    )
    async def test_the_route_writes_its_field_and_nothing_else(
        self, live_client, field, value
    ):
        """@verifies REQ-0083"""
        await _community(live_client)
        before = await _add(live_client, "ex-00001", 1)
        sibling = await _add(live_client, "ex-00002", 2)

        r = await live_client.put(
            f"/admin/communities/{C}/members/ex-00001/{field}", json={field: value}
        )

        assert r.status_code == 200, r.text
        after = r.json()
        assert after[field] == value
        expected = {**_stable(before), field: value}
        assert _stable(after) == expected
        assert _stable(await _get(live_client, "ex-00002")) == _stable(sibling)

    @pytest.mark.parametrize(
        "field,body",
        [
            ("name", {}),
            ("name", {"name": None}),
            ("name", {"name": "x", "user_id": "kc-9999"}),
            ("role", {"role": "prosumer", "area": "south"}),
            ("role", {"did": "did:web:example.org:ex-1"}),
            ("area", {"area": "south", "status": "inactive"}),
            ("area", {"area": None}),
        ],
    )
    async def test_a_body_naming_anything_else_is_refused_and_changes_nothing(
        self, live_client, field, body
    ):
        """One key, not `null`, and no other: a field grant cannot carry an
        identity rewrite (F3).

        @verifies REQ-0083
        """
        await _community(live_client)
        before = await _add(live_client, "ex-00001", 1)

        r = await live_client.put(
            f"/admin/communities/{C}/members/ex-00001/{field}", json=body
        )

        assert r.status_code == 422, r.text
        assert isinstance(r.json()["detail"], list), "FastAPI's validation body"
        assert _stable(await _get(live_client, "ex-00001")) == _stable(before)

    @pytest.mark.parametrize("field", ["name", "role", "area"])
    async def test_an_unknown_member_or_community_is_coded(self, live_client, field):
        """@verifies REQ-0083"""
        await _community(live_client)
        value = {"name": "x", "role": "consumer", "area": "north"}[field]

        r = await live_client.put(
            f"/admin/communities/{C}/members/nobody/{field}", json={field: value}
        )
        assert r.status_code == 404 and r.json()["code"] == "member_not_found"
        r = await live_client.put(
            f"/admin/communities/nowhere/members/ex-00001/{field}", json={field: value}
        )
        assert r.status_code == 404 and r.json()["code"] == "community_not_found"


@pytest.mark.integration
class TestTheValueChecksAreThePatchs:
    @pytest.mark.parametrize(
        "field,value,code",
        [
            ("role", "landlord", "invalid_role"),
            ("role", "Consumer", "invalid_role"),
            ("area", "nowhere", "unknown_area"),
            ("area", " north", "unknown_area"),
        ],
    )
    async def test_the_field_route_refuses_what_the_general_patch_refuses(
        self, live_client, field, value, code
    ):
        """Same status, same code, same sentence, and nothing changes — on the
        field route and on the general `PATCH` alike (REQ-0066).

        @verifies REQ-0083
        @verifies REQ-0066
        """
        await _community(live_client)
        before = await _add(live_client, "ex-00001", 1)

        narrow = await live_client.put(
            f"/admin/communities/{C}/members/ex-00001/{field}", json={field: value}
        )
        general = await live_client.patch(
            f"/admin/communities/{C}/members/ex-00001", json={field: value}
        )

        assert narrow.status_code == general.status_code == 422, narrow.text
        assert narrow.json() == general.json()
        assert narrow.json()["code"] == code
        assert _stable(await _get(live_client, "ex-00001")) == _stable(before)

    async def test_any_name_the_patch_accepts_the_route_accepts(self, live_client):
        """The general `PATCH` holds a name to no set, so neither does the route.

        @verifies REQ-0083
        """
        await _community(live_client)
        await _add(live_client, "ex-00001", 1)
        for name in ("", "  Spaced  ", "Ünïcødé – Name"):
            r = await live_client.put(
                f"/admin/communities/{C}/members/ex-00001/name", json={"name": name}
            )
            assert r.status_code == 200, r.text
            assert (await _get(live_client, "ex-00001"))["name"] == name


@pytest.mark.integration
class TestHostileMemberKeys:
    """A member keyed like a field route is a member: its key is read at the
    member position and never as the field."""

    @pytest.mark.parametrize(
        "key", ["name", "role", "area", "delivery-points", "profile"]
    )
    async def test_a_member_keyed_like_a_route_is_written_as_itself(
        self, live_client, key
    ):
        """@verifies REQ-0083
        @verifies REQ-0065"""
        await _community(live_client)
        await _add(live_client, key, 1)
        bystander = await _add(live_client, "ex-00002", 2)

        base = f"/admin/communities/{C}/members/{key}"
        assert (
            await live_client.put(f"{base}/name", json={"name": "N"})
        ).status_code == 200
        assert (
            await live_client.put(f"{base}/role", json={"role": "producer"})
        ).status_code == 200
        assert (
            await live_client.put(f"{base}/area", json={"area": "south"})
        ).status_code == 200

        member = await _get(live_client, key)
        assert (member["name"], member["role"], member["area"]) == (
            "N",
            "producer",
            "south",
        )
        assert _stable(await _get(live_client, "ex-00002")) == _stable(bystander)


class TestTheOpenApiDocument:
    def _doc(self):
        from celine.rec_registry.main import create_app

        return create_app().openapi()

    @pytest.mark.parametrize(
        "field,schema",
        [
            ("name", "MemberNamePut"),
            ("role", "MemberRolePut"),
            ("area", "MemberAreaPut"),
        ],
    )
    def test_each_field_route_is_published_with_its_body(self, field, schema):
        """The SDK is generated from this document (REQ-0083).

        @verifies REQ-0083
        """
        doc = self._doc()
        put = doc["paths"][
            f"/admin/communities/{{community_key}}/members/{{member_key}}/{field}"
        ]["put"]
        body = put["requestBody"]["content"]["application/json"]["schema"]
        assert body == {"$ref": f"#/components/schemas/{schema}"}
        component = doc["components"]["schemas"][schema]
        assert component["required"] == [field]
        assert component["additionalProperties"] is False
        ok = put["responses"]["200"]["content"]["application/json"]["schema"]
        assert ok == {"$ref": "#/components/schemas/MemberDetail"}
