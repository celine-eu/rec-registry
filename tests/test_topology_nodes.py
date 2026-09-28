"""Topology nodes are written one at a time, merging by id (REQ-0072).

The routes an onboarding template sync writes a community's substations
through, before the areas that reference them. Held against the area rule
(REQ-0067): a node write never breaks an area that keeps it, and a node an
area references cannot be deleted. The substation codes are synthetic
placeholders (`tests/substations.py`).
"""

from __future__ import annotations

import asyncio

import pytest

from celine.rec_registry.core.area_boundary import (
    areas_referencing,
    child_nodes,
    node_write_refusals,
)
from celine.rec_registry.schemas.bundle import TopologyNodeIn
from celine.rec_registry.services.members import (
    merge_topology_node,
    remove_topology_node,
)
from tests.substations import (
    substation_area,
    substation_code,
    substation_graph,
    substation_node,
)

A1, A2, A3 = (substation_code(n) for n in (1, 2, 3))


# =============================================================================
# Merging — pure
# =============================================================================


class TestMergeById:
    def test_a_new_id_is_appended_and_the_others_kept(self):
        """@verifies REQ-0072"""
        existing = [substation_node(1), substation_node(2)]

        merged = merge_topology_node(
            existing, TopologyNodeIn(id=A3, type="primary_substation")
        )

        assert [n["id"] for n in merged] == [A1, A2, A3]
        assert merged[:2] == existing

    def test_resending_an_id_replaces_it_where_it_stands(self):
        """@verifies REQ-0072"""
        existing = [substation_node(1), substation_node(2), substation_node(3)]

        merged = merge_topology_node(
            existing, TopologyNodeIn(id=A2, type="primary_substation", name="Renamed")
        )

        assert [n["id"] for n in merged] == [A1, A2, A3]
        assert merged[1] == {"id": A2, "type": "primary_substation", "name": "Renamed"}

    def test_an_id_stored_twice_is_kept_once(self):
        """@verifies REQ-0072"""
        existing = [substation_node(1), substation_node(2), substation_node(1)]

        merged = merge_topology_node(
            existing, TopologyNodeIn(id=A1, type="primary_substation", name="One")
        )

        assert [n["id"] for n in merged] == [A1, A2]
        assert merged[0]["name"] == "One"

    def test_the_input_is_not_mutated(self):
        """@verifies REQ-0072"""
        existing = [substation_node(1)]
        snapshot = [dict(n) for n in existing]

        merge_topology_node(existing, TopologyNodeIn(id=A1, type="feeder"))
        remove_topology_node(existing, A1)

        assert existing == snapshot

    def test_removal_keeps_the_others_in_order(self):
        """@verifies REQ-0072"""
        existing = [substation_node(1), substation_node(2), substation_node(3)]

        assert [n["id"] for n in remove_topology_node(existing, A2)] == [A1, A3]

    def test_only_the_bundles_fields_are_stored(self):
        """@verifies REQ-0072"""
        node = TopologyNodeIn(
            id="SS-1",
            type="secondary_substation",
            name="Cabin",
            operator_id="example-dso",
            parent=A1,
            colour="red",
        )

        (stored,) = merge_topology_node([], node)

        assert stored == {
            "id": "SS-1",
            "type": "secondary_substation",
            "name": "Cabin",
            "operator_id": "example-dso",
            "parent": A1,
        }


class TestANodeWriteAgainstTheAreaRule:
    def _areas(self) -> dict:
        return substation_graph("north", "south")["areas"]

    def test_a_type_change_under_an_area_is_refused(self):
        """@verifies REQ-0072"""
        before = [substation_node(1), substation_node(2)]
        after = merge_topology_node(before, TopologyNodeIn(id=A1, type="feeder"))

        found = node_write_refusals(self._areas(), before, after, A1)

        assert len(found) == 1
        assert "'north'" in found[0] and "primary_substation" in found[0]
        assert A1 not in found[0]

    def test_a_node_no_area_lists_is_free(self):
        """@verifies REQ-0072"""
        before = [substation_node(1), substation_node(2), substation_node(3)]
        after = merge_topology_node(before, TopologyNodeIn(id=A3, type="feeder"))

        assert node_write_refusals(self._areas(), before, after, A3) == []

    def test_an_area_stored_before_the_rule_is_not_rejudged(self):
        """@verifies REQ-0072"""
        areas = {"old": {"name": "Old", "topology": ["x", "y"]}}
        before = [{"id": "x", "type": "primary_substation"}]
        after = merge_topology_node(before, TopologyNodeIn(id="x", type="feeder"))

        assert areas_referencing(areas, "x") == ["old"]
        assert node_write_refusals(areas, before, after, "x") == []


class TestChildNodes:
    def test_the_children_are_the_nodes_naming_it_as_parent_in_order(self):
        """@verifies REQ-0072"""
        topology = [
            substation_node(1),
            {"id": "T-2", "type": "transformer", "parent": A1},
            {"id": "T-1", "type": "transformer", "parent": A1},
            {"id": "T-3", "type": "transformer", "parent": A2},
            {"id": "T-4", "type": "transformer"},
        ]

        assert child_nodes(topology, A1) == ["T-2", "T-1"]
        assert child_nodes(topology, A2) == ["T-3"]
        assert child_nodes(topology, "T-4") == []

    def test_a_node_is_not_its_own_child(self):
        """@verifies REQ-0072"""
        assert child_nodes([{"id": "x", "type": "feeder", "parent": "x"}], "x") == []


# =============================================================================
# The routes — live
# =============================================================================


def _bundle(key: str) -> dict:
    graph = substation_graph("north", "south", spare=1)
    graph["topology"].append(
        {
            "id": "SS-1",
            "type": "secondary_substation",
            "name": "Cabin",
            "operator_id": "example-dso",
            "parent": A1,
        }
    )
    return {
        "version": "1.0",
        "schema_version": "0.7",
        "community": {
            "id": key,
            "name": "Topology Community",
            "operators": {"example-dso": {"name": "Example DSO"}},
            **graph,
        },
        "members": {},
    }


async def _seed(client, key: str = "topo-rec") -> str:
    r = await client.post("/admin/import", json={"bundle": _bundle(key)})
    assert r.status_code == 200, r.text
    return key


async def _ids(client, key: str) -> list[str]:
    r = await client.get(f"/admin/communities/{key}/topology")
    assert r.status_code == 200, r.text
    return [n["id"] for n in r.json()["topology"]]


def _node(node_id: str, type_: str = "primary_substation", **fields) -> dict:
    return {"id": node_id, "type": type_, **fields}


@pytest.mark.integration
class TestTheNodePut:
    async def test_a_new_node_is_added_and_the_others_kept(self, live_client):
        """@verifies REQ-0072"""
        c = await _seed(live_client)
        a4 = substation_code(4)

        r = await live_client.put(
            f"/admin/communities/{c}/topology/{a4}", json=_node(a4, name="Four")
        )

        assert r.status_code == 200, r.text
        assert [n["id"] for n in r.json()["topology"]] == [A1, A2, A3, "SS-1", a4]
        assert set(r.json()["areas"]) == {"north", "south"}
        assert await _ids(live_client, c) == [A1, A2, A3, "SS-1", a4]

    async def test_resending_an_id_replaces_it_rather_than_duplicating(self, live_client):
        """@verifies REQ-0072"""
        c = await _seed(live_client)

        for name in ("First", "Second"):
            r = await live_client.put(
                f"/admin/communities/{c}/topology/SS-1",
                json=_node("SS-1", "secondary_substation", name=name, parent=A2),
            )
            assert r.status_code == 200, r.text

        nodes = (await live_client.get(f"/admin/communities/{c}/topology")).json()["topology"]
        assert [n["id"] for n in nodes] == [A1, A2, A3, "SS-1"]
        assert nodes[3]["name"] == "Second"
        assert nodes[3]["parent"] == A2
        # Replaced, not merged field by field: the operator was not re-sent.
        assert nodes[3]["operator_id"] is None

    async def test_reads_answer_the_bundles_field_names(self, live_client):
        """`operator_id` and `parent`, as the bundle names them; `operator`, a
        v0.4 name nothing stores, is gone.

        @verifies REQ-0072
        """
        c = await _seed(live_client)

        for path in (f"/admin/communities/{c}", f"/admin/communities/{c}/topology"):
            nodes = (await live_client.get(path)).json()["topology"]
            ss = next(n for n in nodes if n["id"] == "SS-1")
            assert ss["operator_id"] == "example-dso"
            assert ss["parent"] == A1
            assert "operator" not in ss

    async def test_a_node_written_by_put_exports_and_reimports_unchanged(
        self, live_client
    ):
        """The route and the import build a node with one function.

        @verifies REQ-0072
        """
        import yaml

        c = await _seed(live_client)
        a4 = substation_code(4)
        await live_client.put(
            f"/admin/communities/{c}/topology/{a4}",
            json=_node(a4, name="Four", operator_id="example-dso", colour="red"),
        )
        before = (await live_client.get(f"/admin/communities/{c}/topology")).json()

        exported = await live_client.get("/admin/export", params={"community": c})
        assert exported.status_code == 200, exported.text
        (doc,) = [d for d in yaml.safe_load_all(exported.text) if d]
        stored = next(n for n in doc["community"]["topology"] if n["id"] == a4)
        assert "colour" not in stored
        r = await live_client.post(
            "/admin/import", json={"bundle": doc, "force": True}
        )
        assert r.status_code == 200, r.text

        after = (await live_client.get(f"/admin/communities/{c}/topology")).json()
        assert after == before

    async def test_the_body_id_must_match_the_path(self, live_client):
        """@verifies REQ-0072"""
        c = await _seed(live_client)

        r = await live_client.put(f"/admin/communities/{c}/topology/{A3}", json=_node(A2))

        assert r.status_code == 422, r.text
        assert "code" not in r.json()
        assert await _ids(live_client, c) == [A1, A2, A3, "SS-1"]

    async def test_an_unknown_community_is_404(self, live_client):
        """@verifies REQ-0072"""
        r = await live_client.put("/admin/communities/nowhere/topology/x", json=_node("x"))

        assert r.status_code == 404
        assert r.json()["code"] == "community_not_found"

    async def test_a_type_change_under_an_area_is_refused_and_changes_nothing(
        self, live_client
    ):
        """@verifies REQ-0072"""
        c = await _seed(live_client)
        before = (await live_client.get(f"/admin/communities/{c}")).json()

        r = await live_client.put(
            f"/admin/communities/{c}/topology/{A1}", json=_node(A1, "secondary_substation")
        )

        assert r.status_code == 422, r.text
        assert r.json()["code"] == "invalid_area_boundary"
        assert "'north'" in r.json()["detail"]
        after = (await live_client.get(f"/admin/communities/{c}")).json()
        assert after["topology"] == before["topology"]
        assert after["areas"] == before["areas"]

    async def test_renaming_a_node_under_an_area_is_accepted(self, live_client):
        """@verifies REQ-0072"""
        c = await _seed(live_client)

        r = await live_client.put(
            f"/admin/communities/{c}/topology/{A1}", json=_node(A1, name="North primary")
        )

        assert r.status_code == 200, r.text
        assert r.json()["topology"][0]["name"] == "North primary"

    async def test_a_node_no_area_lists_may_change_type(self, live_client):
        """@verifies REQ-0072"""
        c = await _seed(live_client)

        r = await live_client.put(
            f"/admin/communities/{c}/topology/{A3}", json=_node(A3, "feeder")
        )

        assert r.status_code == 200, r.text

    async def test_the_node_then_the_area_is_the_sync_order(self, live_client):
        """A template sync writes the substation, then the area onto it.

        @verifies REQ-0072
        """
        c = await _seed(live_client)
        a5 = substation_code(5)

        refused = await live_client.put(
            f"/admin/communities/{c}/areas/east", json=substation_area("East", 5)
        )
        assert refused.status_code == 422, refused.text

        r = await live_client.put(f"/admin/communities/{c}/topology/{a5}", json=_node(a5))
        assert r.status_code == 200, r.text
        r = await live_client.put(
            f"/admin/communities/{c}/areas/east", json=substation_area("East", 5)
        )
        assert r.status_code == 200, r.text
        assert r.json()["areas"]["east"]["topology"] == [a5]

    async def test_an_area_stored_before_the_rule_does_not_block_its_node(
        self, live_client, pg_session
    ):
        """@verifies REQ-0072"""
        from sqlalchemy import select

        from celine.rec_registry.db.models import Community

        c = await _seed(live_client)
        community = await pg_session.scalar(select(Community).where(Community.key == c))
        community.areas = {
            **community.areas,
            "old": {"name": "Old", "topology": [A3, "SS-1"]},
        }
        await pg_session.commit()

        r = await live_client.put(
            f"/admin/communities/{c}/topology/{A3}", json=_node(A3, "feeder")
        )

        assert r.status_code == 200, r.text


@pytest.mark.integration
class TestTheNodeDelete:
    async def test_an_unused_node_is_removed_and_the_others_kept(self, live_client):
        """@verifies REQ-0072"""
        c = await _seed(live_client)

        r = await live_client.delete(f"/admin/communities/{c}/topology/{A3}")

        assert r.status_code == 200, r.text
        assert [n["id"] for n in r.json()["topology"]] == [A1, A2, "SS-1"]
        assert set(r.json()["areas"]) == {"north", "south"}

    async def test_an_absent_node_is_404(self, live_client):
        """@verifies REQ-0072"""
        c = await _seed(live_client)

        r = await live_client.delete(f"/admin/communities/{c}/topology/nothing")

        assert r.status_code == 404
        assert await _ids(live_client, c) == [A1, A2, A3, "SS-1"]

    async def test_an_unknown_community_is_404(self, live_client):
        """@verifies REQ-0072"""
        r = await live_client.delete("/admin/communities/nowhere/topology/x")

        assert r.status_code == 404
        assert r.json()["code"] == "community_not_found"

    async def test_a_node_an_area_references_is_refused(self, live_client):
        """@verifies REQ-0072"""
        c = await _seed(live_client)

        r = await live_client.delete(f"/admin/communities/{c}/topology/{A2}")

        assert r.status_code == 409, r.text
        assert r.json()["code"] == "topology_node_in_use"
        assert "'south'" in r.json()["detail"]
        assert await _ids(live_client, c) == [A1, A2, A3, "SS-1"]

    async def test_an_area_stored_before_the_rule_holds_its_node_too(
        self, live_client, pg_session
    ):
        """@verifies REQ-0072"""
        from sqlalchemy import select

        from celine.rec_registry.db.models import Community

        c = await _seed(live_client)
        community = await pg_session.scalar(select(Community).where(Community.key == c))
        community.areas = {**community.areas, "old": {"name": "Old", "topology": ["SS-1"]}}
        await pg_session.commit()

        r = await live_client.delete(f"/admin/communities/{c}/topology/SS-1")

        assert r.status_code == 409, r.text
        assert r.json()["code"] == "topology_node_in_use"
        assert "'old'" in r.json()["detail"]

    async def test_a_node_another_node_names_as_parent_is_refused(self, live_client):
        """`SS-1` names `A1` as its parent: deleting `A1` would leave it
        pointing at nothing. The refusal names the child by node id.

        @verifies REQ-0072
        """
        c = await _seed(live_client)
        # Free A1 of its area, so the parent is the only thing holding it.
        assert (await live_client.delete(f"/admin/communities/{c}/areas/north")).status_code == 200

        r = await live_client.delete(f"/admin/communities/{c}/topology/{A1}")

        assert r.status_code == 409, r.text
        assert r.json()["code"] == "topology_node_in_use"
        assert "'SS-1'" in r.json()["detail"]
        assert await _ids(live_client, c) == [A1, A2, A3, "SS-1"]

    async def test_every_child_is_named_and_nothing_else(self, live_client):
        """@verifies REQ-0072"""
        c = await _seed(live_client)
        topo = f"/admin/communities/{c}/topology"
        r = await live_client.put(
            f"{topo}/T-1", json=_node("T-1", "transformer", parent=A3, name="Cabin")
        )
        assert r.status_code == 200, r.text
        r = await live_client.put(
            f"{topo}/T-2", json=_node("T-2", "transformer", parent=A3)
        )
        assert r.status_code == 200, r.text

        r = await live_client.delete(f"{topo}/{A3}")

        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert "'T-1'" in detail and "'T-2'" in detail
        assert "Cabin" not in detail
        assert A3 in await _ids(live_client, c)

    async def test_once_the_children_are_gone_the_parent_can_go(self, live_client):
        """Re-parenting the child (here: deleting it) is what frees the node.

        @verifies REQ-0072
        """
        c = await _seed(live_client)
        topo = f"/admin/communities/{c}/topology"
        assert (await live_client.delete(f"/admin/communities/{c}/areas/north")).status_code == 200
        r = await live_client.put(
            f"{topo}/SS-1", json=_node("SS-1", "secondary_substation", parent=A2)
        )
        assert r.status_code == 200, r.text

        r = await live_client.delete(f"{topo}/{A1}")

        assert r.status_code == 200, r.text
        assert [n["id"] for n in r.json()["topology"]] == [A2, A3, "SS-1"]

    async def test_a_node_naming_itself_as_parent_does_not_hold_itself(
        self, live_client
    ):
        """@verifies REQ-0072"""
        c = await _seed(live_client)
        topo = f"/admin/communities/{c}/topology"
        r = await live_client.put(f"{topo}/X-1", json=_node("X-1", "feeder", parent="X-1"))
        assert r.status_code == 200, r.text

        r = await live_client.delete(f"{topo}/X-1")

        assert r.status_code == 200, r.text

    async def test_once_the_area_is_gone_the_node_can_go(self, live_client):
        """@verifies REQ-0072"""
        c = await _seed(live_client)

        assert (await live_client.delete(f"/admin/communities/{c}/areas/south")).status_code == 200
        r = await live_client.delete(f"/admin/communities/{c}/topology/{A2}")

        assert r.status_code == 200, r.text
        assert A2 not in [n["id"] for n in r.json()["topology"]]

    async def test_an_area_put_racing_the_delete_never_orphans_the_area(
        self, live_client
    ):
        """Both take the community's row exclusively: either the area lands
        first and the delete is refused, or the node goes first and the area
        is refused. Never an area on a node that is gone.

        @verifies REQ-0072
        """
        c = await _seed(live_client)

        for round_ in range(4):
            n = 10 + round_
            code = substation_code(n)
            r = await live_client.put(
                f"/admin/communities/{c}/topology/{code}", json=_node(code)
            )
            assert r.status_code == 200, r.text

            area, delete = await asyncio.gather(
                live_client.put(
                    f"/admin/communities/{c}/areas/a{n}", json=substation_area("A", n)
                ),
                live_client.delete(f"/admin/communities/{c}/topology/{code}"),
            )

            assert sorted([area.status_code, delete.status_code]) in (
                [200, 409],
                [200, 422],
            ), (area.text, delete.text)
            community = (await live_client.get(f"/admin/communities/{c}")).json()
            node_ids = {n_["id"] for n_ in community["topology"]}
            if f"a{n}" in community["areas"]:
                assert code in node_ids
