"""An area is one GSE primary substation: one boundary, one node, the same id (REQ-0067).

Held on the two writes that can change an area — the area `PUT` and the bundle
import — and published as bundle schema v0.7 (REQ-0068). The substation codes
here are synthetic placeholders (`tests/substations.py`).
"""

from __future__ import annotations

import asyncio
import json
import pathlib

import pytest
import yaml

from celine.rec_registry.core.area_boundary import (
    area_boundary_refusals,
    area_key_refusals,
    is_area_key,
)
from celine.rec_registry.core.versions import CURRENT_SCHEMA_VERSION, KNOWN_SCHEMA_VERSIONS
from tests.substations import (
    SOURCE,
    substation_area,
    substation_code,
    substation_graph,
    substation_node,
)

CODE = "invalid_area_boundary"
SCHEMAS = pathlib.Path(__file__).parent.parent / "schemas" / "community"


def _without_descriptions(node):
    """The schema with every `description` string dropped — the shape alone.

    Only a string value is wording; a property *named* `description` holds a
    schema and is kept.
    """
    if isinstance(node, dict):
        return {
            k: _without_descriptions(v)
            for k, v in node.items()
            if not (k == "description" and isinstance(v, str))
        }
    if isinstance(node, list):
        return [_without_descriptions(v) for v in node]
    return node


def _refusal(r, status: int = 422, code: str = CODE) -> str:
    assert r.status_code == status, r.text
    body = r.json()
    assert body["code"] == code, body
    assert isinstance(body["detail"], str)
    return body["detail"]


# The four ways the plan names an area breaking the rule, as area bodies over a
# community holding nodes 1..5 as primary substations, with areas on 1 and 2.
def _two_boundaries() -> dict:
    area = substation_area("East", 3)
    area["boundary"] = [area["boundary"], {"source": SOURCE, "id": substation_code(4)}]
    return area


def _two_nodes() -> dict:
    area = substation_area("East", 3)
    area["topology"] = [substation_code(3), substation_code(4)]
    return area


def _node_is_not_the_boundary() -> dict:
    area = substation_area("East", 3)
    area["topology"] = [substation_code(4)]
    return area


def _on_a_siblings_substation() -> dict:
    return substation_area("East", 1)


BROKEN = {
    "two boundaries": _two_boundaries,
    "two nodes": _two_nodes,
    "a node id differing from the boundary id": _node_is_not_the_boundary,
    "two areas on one cod_ac": _on_a_siblings_substation,
}


# =============================================================================
# The rule — pure
# =============================================================================


class TestTheRule:
    def _refusals(self, areas: dict, topology: list | None = None, **kw) -> list[str]:
        if topology is None:
            topology = [substation_node(n) for n in range(1, 6)]
        return area_boundary_refusals(areas, topology, **kw)

    def test_one_boundary_one_node_the_same_id_is_accepted(self):
        """@verifies REQ-0067"""
        graph = substation_graph("north", "south")
        assert area_boundary_refusals(graph["areas"], graph["topology"]) == []

    @pytest.mark.parametrize("case", sorted(BROKEN))
    def test_each_named_breach_is_refused(self, case):
        """@verifies REQ-0067"""
        areas = {**substation_graph("north", "south")["areas"], "east": BROKEN[case]()}

        found = self._refusals(areas)

        assert found, case
        assert any("'east'" in f for f in found), found

    def test_an_area_with_no_boundary_is_refused(self):
        """@verifies REQ-0067"""
        area = substation_area("East", 3)
        del area["boundary"]

        assert "carries no boundary" in self._refusals({"east": area})[0]

    @pytest.mark.parametrize(
        "boundary",
        [
            {"source": SOURCE},
            {"source": SOURCE, "id": 7},
            {"source": SOURCE, "id": "AC000E00003", "shape": {}},
            "AC000E00003",
        ],
    )
    def test_a_malformed_boundary_is_refused(self, boundary):
        """@verifies REQ-0067"""
        area = substation_area("East", 3)
        area["boundary"] = boundary

        assert any("not an object" in f for f in self._refusals({"east": area}))

    def test_another_source_is_refused(self):
        """@verifies REQ-0067"""
        area = substation_area("East", 3)
        area["boundary"]["source"] = "nuts"

        assert any("source 'nuts'" in f for f in self._refusals({"east": area}))

    @pytest.mark.parametrize("blank", ["", "  "])
    def test_a_blank_boundary_id_is_refused(self, blank):
        """@verifies REQ-0067"""
        area = {"name": "East", "boundary": {"source": SOURCE, "id": blank}, "topology": [blank]}

        assert any("missing or blank" in f for f in self._refusals({"east": area}))

    def test_a_boundary_id_over_64_characters_is_refused(self):
        """@verifies REQ-0067"""
        long_id, at_cap = "A" * 65, "A" * 64
        topology = [
            {"id": long_id, "type": "primary_substation"},
            {"id": at_cap, "type": "primary_substation"},
        ]

        def area(code: str) -> dict:
            return {"name": "East", "boundary": {"source": SOURCE, "id": code}, "topology": [code]}

        found = self._refusals({"east": area(long_id)}, topology)
        assert any("65 characters; at most 64" in f for f in found)
        assert not any(long_id in f for f in found)
        assert self._refusals({"east": area(at_cap)}, topology) == []

    def test_no_node_is_refused(self):
        """@verifies REQ-0067"""
        area = substation_area("East", 3)
        area["topology"] = []

        assert any("lists 0 topology nodes" in f for f in self._refusals({"east": area}))

    def test_a_node_the_topology_does_not_hold_is_refused(self):
        """@verifies REQ-0067"""
        found = self._refusals({"east": substation_area("East", 9)})

        assert any("not a node of the community's topology" in f for f in found)

    def test_a_node_that_is_not_a_primary_substation_is_refused(self):
        """@verifies REQ-0067"""
        topology = [{"id": substation_code(3), "type": "secondary_substation"}]

        found = self._refusals({"east": substation_area("East", 3)}, topology)

        assert any("'secondary_substation'" in f for f in found)

    def test_two_nodes_sharing_the_id_are_refused(self):
        """Exactly one topology node carries the area's id.

        @verifies REQ-0067"""
        topology = [substation_node(3), substation_node(3)]

        found = self._refusals({"east": substation_area("East", 3)}, topology)

        assert any("holds 2 nodes" in f for f in found)

    def test_the_comparison_is_exact(self):
        """@verifies REQ-0067"""
        area = substation_area("East", 3)
        area["topology"] = [substation_code(3).lower()]

        assert any("not its boundary id" in f for f in self._refusals({"east": area}))

    def test_a_refusal_names_the_area_and_not_the_code(self):
        """@verifies REQ-0067"""
        found = self._refusals(
            {"a": substation_area("A", 1), "b": substation_area("B", 1)}
        )

        assert len(found) == 1
        assert "'a'" in found[0] and "'b'" in found[0]
        assert substation_code(1) not in found[0]

    def test_only_judges_the_written_area_but_uniqueness_against_all(self):
        """An area stored before the rule is not re-judged by a write to
        another; its boundary id still counts against the written one.

        @verifies REQ-0067"""
        legacy = {"name": "Old", "topology": ["x", "y"]}
        areas = {"old": legacy, "north": substation_area("North", 1)}

        assert self._refusals(areas, only=["north"]) == []
        areas["east"] = substation_area("East", 1)
        assert self._refusals(areas, only=["east"])
        assert self._refusals(areas)  # judged whole, the legacy area is refused


# =============================================================================
# The area PUT
# =============================================================================


def _bundle(key: str, *areas: str, spare: int = 3, version: str = CURRENT_SCHEMA_VERSION) -> dict:
    graph = substation_graph(*areas, spare=spare)
    graph["topology"].append(
        {"id": "SS-1", "type": "secondary_substation", "parent": substation_code(1)}
    )
    return {
        "version": "1.0",
        "schema_version": version,
        "community": {"id": key, "name": "Area Community", **graph},
        "members": {},
    }


async def _seed(client, key: str = "area-rec") -> str:
    r = await client.post("/admin/import", json={"bundle": _bundle(key, "north", "south")})
    assert r.status_code == 200, r.text
    return key


@pytest.mark.integration
class TestTheAreaPut:
    async def test_it_stores_and_returns_the_boundary_and_the_node(self, live_client):
        """@verifies REQ-0067"""
        c = await _seed(live_client)

        r = await live_client.put(
            f"/admin/communities/{c}/areas/east", json=substation_area("East", 3)
        )

        assert r.status_code == 200, r.text
        east = r.json()["areas"]["east"]
        assert east["boundary"] == {"source": SOURCE, "id": substation_code(3)}
        assert east["topology"] == [substation_code(3)]
        again = (await live_client.get(f"/admin/communities/{c}")).json()
        assert again["areas"]["east"] == east
        assert again["areas"]["north"]["topology"] == [substation_code(1)]

    async def test_replacing_an_area_on_its_own_substation_is_accepted(self, live_client):
        """@verifies REQ-0067"""
        c = await _seed(live_client)

        r = await live_client.put(
            f"/admin/communities/{c}/areas/north", json=substation_area("Renamed", 1)
        )

        assert r.status_code == 200, r.text
        assert r.json()["areas"]["north"]["name"] == "Renamed"

    async def test_moving_an_area_to_a_free_substation_is_accepted(self, live_client):
        """@verifies REQ-0067"""
        c = await _seed(live_client)

        r = await live_client.put(
            f"/admin/communities/{c}/areas/north", json=substation_area("North", 4)
        )

        assert r.status_code == 200, r.text
        # Its old substation is free again.
        r = await live_client.put(
            f"/admin/communities/{c}/areas/east", json=substation_area("East", 1)
        )
        assert r.status_code == 200, r.text

    @pytest.mark.parametrize("case", sorted(BROKEN))
    async def test_each_named_breach_is_refused_and_changes_nothing(self, live_client, case):
        """@verifies REQ-0067"""
        c = await _seed(live_client)
        before = (await live_client.get(f"/admin/communities/{c}")).json()

        r = await live_client.put(f"/admin/communities/{c}/areas/east", json=BROKEN[case]())

        detail = _refusal(r)
        assert "'east'" in detail
        after = (await live_client.get(f"/admin/communities/{c}")).json()
        assert after["areas"] == before["areas"]

    @pytest.mark.parametrize(
        "body",
        [
            {"name": "East"},
            {"name": "East", "boundary": None, "topology": ["AC000E00003"]},
            {"name": "East", "boundary": {"source": SOURCE}, "topology": ["AC000E00003"]},
        ],
        ids=["no boundary", "null boundary", "boundary without id"],
    )
    async def test_a_missing_or_malformed_boundary_is_refused_with_the_code(
        self, live_client, body
    ):
        """A coded refusal, not FastAPI's validation body (REQ-0073).

        @verifies REQ-0067"""
        c = await _seed(live_client)

        _refusal(await live_client.put(f"/admin/communities/{c}/areas/east", json=body))

    async def test_a_node_the_topology_does_not_hold_yet_is_refused(self, live_client):
        """The node is written first; until then the area cannot reference it.

        @verifies REQ-0067"""
        c = await _seed(live_client)

        detail = _refusal(
            await live_client.put(
                f"/admin/communities/{c}/areas/east", json=substation_area("East", 9)
            )
        )

        assert "not a node of the community's topology" in detail

    async def test_a_node_that_is_not_a_primary_substation_is_refused(self, live_client):
        """@verifies REQ-0067"""
        c = await _seed(live_client)
        body = {"name": "East", "boundary": {"source": SOURCE, "id": "SS-1"}, "topology": ["SS-1"]}

        detail = _refusal(await live_client.put(f"/admin/communities/{c}/areas/east", json=body))

        assert "'secondary_substation'" in detail

    async def test_a_boundary_id_over_64_characters_is_refused_with_the_code(
        self, live_client
    ):
        """`AreaBoundaryIn` publishes `maxLength: 64`, and a longer id still
        answers the code rather than FastAPI's validation body.

        @verifies REQ-0067
        """
        c = await _seed(live_client)
        long_id = "A" * 65

        r = await live_client.put(
            f"/admin/communities/{c}/topology/{long_id}",
            json={"id": long_id, "type": "primary_substation"},
        )
        assert r.status_code == 200, r.text
        r = await live_client.put(
            f"/admin/communities/{c}/areas/east",
            json={"name": "East", "boundary": {"source": SOURCE, "id": long_id}, "topology": [long_id]},
        )

        assert "at most 64" in _refusal(r)
        areas = (await live_client.get(f"/admin/communities/{c}")).json()["areas"]
        assert "east" not in areas

    async def test_an_unknown_community_is_404(self, live_client):
        """@verifies REQ-0067"""
        r = await live_client.put(
            "/admin/communities/nowhere/areas/east", json=substation_area("East", 3)
        )

        assert r.status_code == 404
        assert r.json()["code"] == "community_not_found"

    async def test_two_writers_onto_one_substation_get_one_success(self, live_client):
        """Two concurrent writers onto one substation end with one area on it.
        `asyncio.gather` over the ASGI transport does not reliably interleave
        the two requests, so this does not show the lock is needed; that is
        `test_a_put_waits_for_an_uncommitted_area_on_its_substation`.

        @verifies REQ-0067"""
        c = await _seed(live_client)

        results = await asyncio.gather(
            *(
                live_client.put(
                    f"/admin/communities/{c}/areas/{k}", json=substation_area(k, 3)
                )
                for k in ("east", "west")
            )
        )

        assert sorted(r.status_code for r in results) == [200, 422], [
            r.text for r in results
        ]
        areas = (await live_client.get(f"/admin/communities/{c}")).json()["areas"]
        on_three = [k for k, a in areas.items() if a["topology"] == [substation_code(3)]]
        assert len(on_three) == 1

    async def test_a_put_waits_for_an_uncommitted_area_on_its_substation(
        self, live_client, pg_engine
    ):
        """A writer holds the community row with an uncommitted area on a
        substation; a `PUT` onto the same substation waits for it and is then
        refused. Without the lock the `PUT` reads the areas before the first
        writer commits, passes, and overwrites it. `asyncio.gather` over the
        ASGI transport does not reliably interleave two requests, so the first
        writer is held open deliberately, as in `TestAnAreaDeletedMeanwhile`.

        @verifies REQ-0067"""
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from celine.rec_registry.services import members as member_service
        from tests.test_member_values import _wait_until_blocked

        c = await _seed(live_client)
        maker = async_sessionmaker(pg_engine, expire_on_commit=False)

        async with maker() as holder:
            holder_pid = await holder.scalar(text("select pg_backend_pid()"))
            community = await member_service.resolve_community(holder, c)
            await member_service.lock_community(holder, community, share=False)
            community.areas = {**community.areas, "east": substation_area("East", 3)}
            await holder.flush()

            request = asyncio.create_task(
                live_client.put(
                    f"/admin/communities/{c}/areas/west", json=substation_area("West", 3)
                )
            )
            await _wait_until_blocked(pg_engine, holder_pid)
            await holder.commit()

        r = await request
        _refusal(r)
        areas = (await live_client.get(f"/admin/communities/{c}")).json()["areas"]
        assert "east" in areas and "west" not in areas

    async def test_an_area_stored_before_the_rule_is_read_and_not_rejudged(
        self, live_client, pg_session
    ):
        """@verifies REQ-0067"""
        from sqlalchemy import select

        from celine.rec_registry.db.models import Community

        c = await _seed(live_client)
        community = await pg_session.scalar(select(Community).where(Community.key == c))
        community.areas = {
            **community.areas,
            "old": {"name": "Old", "topology": ["x", "y"], "boundary": "not-one"},
        }
        await pg_session.commit()

        read = await live_client.get(f"/admin/communities/{c}")
        assert read.status_code == 200, read.text
        assert read.json()["areas"]["old"]["boundary"] is None
        assert read.json()["areas"]["old"]["topology"] == ["x", "y"]

        r = await live_client.put(
            f"/admin/communities/{c}/areas/east", json=substation_area("East", 3)
        )
        assert r.status_code == 200, r.text
        assert "old" in r.json()["areas"]


# =============================================================================
# The import
# =============================================================================


@pytest.mark.integration
class TestTheImport:
    @pytest.mark.parametrize("case", sorted(BROKEN))
    async def test_each_named_breach_refuses_the_bundle_whole(self, live_client, case):
        """@verifies REQ-0067
        @verifies REQ-0074"""
        bundle = _bundle("area-rec", "north", "south")
        bundle["community"]["areas"]["east"] = BROKEN[case]()

        r = await live_client.post("/admin/import", json={"bundle": bundle})

        assert "'east'" in _refusal(r)
        assert (await live_client.get("/admin/communities/area-rec")).status_code == 404

    async def test_a_dry_run_lists_every_refusal(self, live_client):
        """@verifies REQ-0034
        @verifies REQ-0074"""
        bundle = _bundle("area-rec", "north", "south")
        areas = bundle["community"]["areas"]
        areas["east"] = _two_nodes()
        areas["west"] = substation_area("West", 1)

        r = await live_client.post("/admin/import", json={"bundle": bundle, "dry_run": True})

        assert r.status_code == 200, r.text
        refusals = r.json()["refusals"]
        assert [x["code"] for x in refusals] == [CODE, CODE]
        details = " ".join(x["detail"] for x in refusals)
        assert "'east'" in details and "'west'" in details and "'north'" in details
        assert (await live_client.get("/admin/communities/area-rec")).status_code == 404

    async def test_the_yaml_route_refuses_too(self, live_client):
        """@verifies REQ-0074"""
        bundle = _bundle("area-rec", "north")
        bundle["community"]["areas"]["east"] = _node_is_not_the_boundary()

        r = await live_client.post(
            "/admin/import/yaml",
            content=yaml.safe_dump(bundle),
            headers={"content-type": "application/yaml"},
        )

        _refusal(r)
        assert (await live_client.get("/admin/communities/area-rec")).status_code == 404

    async def test_a_forced_reimport_that_breaks_the_rule_keeps_the_community(
        self, live_client
    ):
        """Refused before anything is deleted.

        @verifies REQ-0074"""
        c = await _seed(live_client)
        bundle = _bundle(c, "north", "south")
        bundle["community"]["name"] = "Replacement"
        bundle["community"]["areas"]["south"] = substation_area("South", 1)

        r = await live_client.post("/admin/import", json={"bundle": bundle, "force": True})

        _refusal(r)
        kept = (await live_client.get(f"/admin/communities/{c}")).json()
        assert kept["name"] == "Area Community"

    async def test_a_v06_bundle_with_areas_and_no_boundary_is_refused(self, live_client):
        """No compatibility branch: an old backup is reshaped before it restores.

        @verifies REQ-0074
        @verifies REQ-0068"""
        bundle = {
            "version": "1.0",
            "schema_version": "0.6",
            "community": {
                "id": "old-rec",
                "name": "Old",
                "areas": {"north": {"name": "north", "topology": ["PS-1", "PS-2"]}},
                "topology": [
                    {"id": "PS-1", "type": "primary_substation"},
                    {"id": "PS-2", "type": "primary_substation"},
                ],
            },
            "members": {},
        }

        r = await live_client.post("/admin/import", json={"bundle": bundle})
        dry = await live_client.post("/admin/import", json={"bundle": bundle, "dry_run": True})

        _refusal(r)
        assert (await live_client.get("/admin/communities/old-rec")).status_code == 404
        assert [x["code"] for x in dry.json()["refusals"]] == [CODE, CODE]
        assert any("0.6" in w for w in dry.json()["warnings"])

    async def test_a_v06_bundle_that_keeps_the_rule_is_imported(self, live_client):
        """The version is a warning; the content is what refuses (REQ-0018).

        @verifies REQ-0074
        @verifies REQ-0068"""
        r = await live_client.post(
            "/admin/import", json={"bundle": _bundle("v06-rec", "north", version="0.6")}
        )

        assert r.status_code == 200, r.text
        assert any("0.6" in w for w in r.json()["warnings"])

    async def test_a_v06_bundle_with_no_areas_is_imported(self, live_client):
        """@verifies REQ-0068"""
        bundle = {
            "version": "1.0",
            "schema_version": "0.6",
            "community": {"id": "bare-rec", "name": "Bare"},
            "members": {},
        }

        r = await live_client.post("/admin/import", json={"bundle": bundle})

        assert r.status_code == 200, r.text


# =============================================================================
# The area key — the rule the rename holds a new key to, on every write (REQ-0067)
# =============================================================================

KEY_CODE = "invalid_area_key"
NOT_AREA_KEYS = ["north zone", "south.2", "-nord", "_nord", "nörd", "a" * 129]


class TestTheAreaKeyRule:
    @pytest.mark.parametrize("key", ["north", "N", "0", "north_2-b", "a" * 128])
    def test_an_area_key_is_accepted(self, key):
        """@verifies REQ-0067"""
        assert is_area_key(key)
        assert area_key_refusals({key: {}}) == []

    @pytest.mark.parametrize("key", [*NOT_AREA_KEYS, "", "a/b", None, 1])
    def test_anything_else_is_not_an_area_key(self, key):
        """@verifies REQ-0067"""
        assert not is_area_key(key)

    def test_one_refusal_per_key_naming_it_and_the_rule(self):
        """@verifies REQ-0067"""
        found = area_key_refusals({"north": {}, "south.2": {}, "north zone": {}})

        assert found == [
            "area 'north zone': the key is not an area key (letters, digits, '-' "
            "and '_', starting with a letter or digit, at most 128 characters)",
            "area 'south.2': the key is not an area key (letters, digits, '-' "
            "and '_', starting with a letter or digit, at most 128 characters)",
        ]


@pytest.mark.integration
class TestTheAreaPutChecksTheKey:
    @pytest.mark.parametrize("key", NOT_AREA_KEYS)
    async def test_a_key_that_is_not_an_area_key_is_refused_and_changes_nothing(
        self, live_client, key
    ):
        """@verifies REQ-0067"""
        c = await _seed(live_client)
        before = (await live_client.get(f"/admin/communities/{c}")).json()

        r = await live_client.put(
            f"/admin/communities/{c}/areas/{key}", json=substation_area("East", 3)
        )

        detail = _refusal(r, 422, KEY_CODE)
        assert key not in detail
        after = (await live_client.get(f"/admin/communities/{c}")).json()
        assert after["areas"] == before["areas"]

    async def test_the_key_is_judged_before_the_body(self, live_client):
        """A bad key and a bad boundary: the key's code, which names what to fix
        first.

        @verifies REQ-0067"""
        c = await _seed(live_client)

        r = await live_client.put(
            f"/admin/communities/{c}/areas/south.2", json={"name": "East"}
        )

        _refusal(r, 422, KEY_CODE)

    async def test_the_longest_key_is_accepted(self, live_client):
        """@verifies REQ-0067"""
        c = await _seed(live_client)
        key = "E" + "a" * 126 + "_"

        r = await live_client.put(
            f"/admin/communities/{c}/areas/{key}", json=substation_area("East", 3)
        )

        assert r.status_code == 200, r.text
        assert key in r.json()["areas"]

    async def test_an_unknown_community_is_404_before_the_key(self, live_client):
        """@verifies REQ-0067"""
        r = await live_client.put(
            "/admin/communities/nowhere/areas/south.2", json=substation_area("East", 3)
        )

        _refusal(r, 404, "community_not_found")

    async def test_a_key_stored_before_the_rule_is_read_and_renamed_onto_one(
        self, live_client, pg_session
    ):
        """Not re-judged by a sibling's write; the rename is the way out, and
        takes its members along (REQ-0079).

        @verifies REQ-0067"""
        from sqlalchemy import select

        from celine.rec_registry.db.models import Community

        c = await _seed(live_client)
        community = await pg_session.scalar(select(Community).where(Community.key == c))
        areas = dict(community.areas)
        areas["north zone"] = areas.pop("north")
        community.areas = areas
        await pg_session.commit()

        read = await live_client.get(f"/admin/communities/{c}")
        assert "north zone" in read.json()["areas"]
        r = await live_client.put(
            f"/admin/communities/{c}/areas/east", json=substation_area("East", 3)
        )
        assert r.status_code == 200, r.text
        _refusal(
            await live_client.put(
                f"/admin/communities/{c}/areas/north zone", json=substation_area("North", 1)
            ),
            422,
            KEY_CODE,
        )

        r = await live_client.post(
            f"/admin/communities/{c}/areas/north zone/rename", json={"new_key": "north"}
        )

        assert r.status_code == 200, r.text
        assert "north" in r.json()["community"]["areas"]
        assert "north zone" not in r.json()["community"]["areas"]


@pytest.mark.integration
class TestTheImportChecksTheKey:
    async def test_a_key_that_is_not_an_area_key_refuses_the_bundle_whole(
        self, live_client
    ):
        """@verifies REQ-0067
        @verifies REQ-0074"""
        bundle = _bundle("area-rec", "north", "south.2")

        r = await live_client.post("/admin/import", json={"bundle": bundle})

        assert "'south.2'" in _refusal(r, 422, KEY_CODE)
        assert (await live_client.get("/admin/communities/area-rec")).status_code == 404

    async def test_a_member_in_that_area_is_not_refused_for_it(self, live_client):
        """The area is what is wrong; its members name a key the bundle holds.

        @verifies REQ-0074"""
        bundle = _bundle("area-rec", "north zone")
        bundle["members"]["ex-00001"] = {
            "user_id": "kc-0001",
            "name": "One",
            "role": "consumer",
            "area": "north zone",
            "status": "active",
        }

        r = await live_client.post("/admin/import", json={"bundle": bundle, "dry_run": True})

        assert r.status_code == 200, r.text
        assert [x["code"] for x in r.json()["refusals"]] == [KEY_CODE]

    async def test_the_yaml_route_refuses_too(self, live_client):
        """@verifies REQ-0074"""
        bundle = _bundle("area-rec", "north", "north zone")

        r = await live_client.post(
            "/admin/import/yaml",
            content=yaml.safe_dump(bundle),
            headers={"content-type": "application/yaml"},
        )

        _refusal(r, 422, KEY_CODE)
        assert (await live_client.get("/admin/communities/area-rec")).status_code == 404


# =============================================================================
# The published schema, v0.7 (REQ-0068)
# =============================================================================


class TestTheSchemaIsPublishedAsV07:
    def _schema(self) -> dict:
        return json.loads((SCHEMAS / "v0.7" / "community.schema.json").read_text())

    def test_the_current_version_is_v07(self):
        """@verifies REQ-0068"""
        assert CURRENT_SCHEMA_VERSION == "0.7"
        assert "0.7" in KNOWN_SCHEMA_VERSIONS
        assert self._schema()["version"] == "0.7"

    def test_an_area_requires_one_boundary_and_one_node(self):
        """@verifies REQ-0068"""
        area = self._schema()["definitions"]["Area"]

        assert set(area["required"]) == {"name", "boundary", "topology"}
        boundary = area["properties"]["boundary"]
        assert boundary["required"] == ["source", "id"]
        assert boundary["properties"]["id"]["maxLength"] == 64
        assert boundary["additionalProperties"] is False
        assert boundary["properties"]["source"]["enum"] == [SOURCE]
        topology = area["properties"]["topology"]
        assert (topology["minItems"], topology["maxItems"]) == (1, 1)

    def test_nothing_else_changed_from_v06(self):
        """Only the area, and wording, changed: `description` strings are
        ignored, so a description corrected in v0.7 (the operators map names
        the node field `operator_id`) is not a change of shape.

        @verifies REQ-0068"""
        old = json.loads((SCHEMAS / "v0.6" / "community.schema.json").read_text())
        new = self._schema()
        for doc in (old, new):
            for key in ("$id", "title", "version"):
                doc.pop(key)
            doc["definitions"].pop("Area")

        assert _without_descriptions(new) == _without_descriptions(old)

    def test_the_operators_map_names_the_node_field_operator_id(self):
        """@verifies REQ-0068"""
        operators = self._schema()["definitions"]["Community"]["properties"]["operators"]

        assert "'operator_id' field" in operators["description"]
        assert "'operator' field" not in operators["description"]

    def test_version_and_openapi_name_it(self):
        """@verifies REQ-0068"""
        from celine.rec_registry.main import create_app

        doc = create_app().openapi()

        assert "bundle schema v0.7" in doc["info"]["description"]
        assert "AreaBoundaryIn" in doc["components"]["schemas"]
        boundary_id = doc["components"]["schemas"]["AreaBoundaryIn"]["properties"]["id"]
        assert boundary_id["maxLength"] == 64

    async def test_version_answers_it(self):
        """@verifies REQ-0068"""
        from celine.rec_registry.api.meta import version

        assert (await version())["schema_version"] == "0.7"
