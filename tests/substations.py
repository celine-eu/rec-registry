"""Areas that keep the one-substation rule (REQ-0067), for tests that need areas.

Every area a test builds is one primary substation: a boundary, and exactly one
topology node — a `primary_substation` whose id is the boundary's. The codes
are synthetic placeholders in the `AC000E` range and name no real substation.
"""

from __future__ import annotations

SOURCE = "gse_cabine_primarie"


def substation_code(n: int) -> str:
    """The placeholder substation code number ``n``: ``AC000E00001`` for 1."""
    return f"AC000E{n:05d}"


def substation_node(n: int) -> dict:
    """The `primary_substation` topology node for code number ``n``."""
    return {"id": substation_code(n), "type": "primary_substation"}


def substation_area(name: str, n: int) -> dict:
    """An area named ``name`` that is the substation with code number ``n``."""
    code = substation_code(n)
    return {"name": name, "boundary": {"source": SOURCE, "id": code}, "topology": [code]}


def substation_graph(*keys: str, spare: int = 0) -> dict:
    """``{"areas": …, "topology": …}`` for a community with one area per key.

    Area ``keys[i]`` is code number ``i + 1``. ``spare`` adds that many more
    `primary_substation` nodes, numbered after the areas', for a test that
    writes a new area onto a node the community already holds.
    """
    return {
        "areas": {k: substation_area(k, i + 1) for i, k in enumerate(keys)},
        "topology": [substation_node(n) for n in range(1, len(keys) + spare + 1)],
    }
