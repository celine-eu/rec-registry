"""An area is one GSE primary substation: one boundary, one node, the same id (REQ-0067).

An area carries ``boundary: {source, id}`` and its ``topology`` lists exactly
one node id: a node of the community's ``topology`` whose ``type`` is
``primary_substation`` and whose ``id`` equals ``boundary.id``. No two areas of
one community carry the same ``boundary.id``. The pipelines take an area's
first node as its members' primary substation; this makes it the only one.

Both paths that write areas ask ``area_boundary_refusals`` — the area ``PUT``
and the bundle import — so an area is judged the same way whichever way it
arrives (``the-two-write-paths``). The community ``PATCH`` never touches areas
or topology (REQ-0029), so it does not ask.

The registry does not check ``boundary.id`` against the GSE dataset, which it
cannot read; onboarding's template import does (ADR-0005). The comparison is
exact: no case folding, no trimming.

A refusal names the area key and the rule broken. It does not repeat the
boundary or node id: the key is enough to find the area, and the detail stays
the same whatever the caller typed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

#: The boundary sources an area may reference. One today; another country's
#: scheme is a new value here, not a new field (ADR-0005).
BOUNDARY_SOURCES: tuple[str, ...] = ("gse_cabine_primarie",)

#: The topology node type an area's one node must have.
PRIMARY_SUBSTATION = "primary_substation"

#: The longest ``boundary.id`` an area may carry (D53). A substation code is
#: eleven characters; the cap leaves room for another scheme and refuses a blob.
BOUNDARY_ID_MAX_LENGTH = 64

#: What an area key may look like (REQ-0067, REQ-0079): letters, digits, ``-``
#: and ``_``, starting with a letter or digit, at most 128 characters — what
#: ``member.area`` holds, and the rule onboarding's template import holds a
#: template's area keys to, so a key onboarding writes is always one this
#: accepts. Every write that stores a key checks it: the area ``PUT``, the
#: rename's new key and the bundle import. A key stored before the rule is read
#: back as stored and can be renamed onto one that keeps it.
AREA_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")

#: The rule, as a refusal states it.
AREA_KEY_RULE = (
    "letters, digits, '-' and '_', starting with a letter or digit, "
    "at most 128 characters"
)


def is_area_key(value: Any) -> bool:
    """Whether ``value`` is an area key a write may store (REQ-0067, REQ-0079)."""
    return isinstance(value, str) and AREA_KEY.fullmatch(value) is not None


def area_key_refusals(areas: Iterable[Any]) -> list[str]:
    """One refusal sentence per key of ``areas`` that is not an area key, sorted.

    The import and the stored-areas report ask this (REQ-0067, REQ-0078). Like
    every area refusal it names the area by its key — the key is what the
    bundle author has to find and change.
    """
    return [
        f"area {key!r}: the key is not an area key ({AREA_KEY_RULE})"
        for key in sorted(areas, key=str)
        if not is_area_key(key)
    ]


def _get(obj: Any, name: str) -> Any:
    """``obj.name`` or ``obj[name]``: areas and nodes arrive as models or dicts."""
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def boundary_id(area: Any) -> str | None:
    """The ``boundary.id`` an area carries, or ``None``."""
    boundary = _get(area, "boundary")
    if boundary is None or isinstance(boundary, (list, str)):
        return None
    value = _get(boundary, "id")
    return value if isinstance(value, str) and value.strip() else None


def area_refusals(
    area_key: str, area: Any, topology: Iterable[Any]
) -> list[str]:
    """What is wrong with one area on its own, against the community's topology.

    Every rule the area breaks, in the order a reader would fix them. The
    uniqueness of ``boundary.id`` across areas is ``area_boundary_refusals``'s.
    """
    found: list[str] = []
    boundary = _get(area, "boundary")
    nodes = _get(area, "topology") or []
    nodes = list(nodes) if isinstance(nodes, (list, tuple)) else [nodes]
    prefix = f"area {area_key!r}"

    if hasattr(boundary, "model_dump"):
        boundary = boundary.model_dump()
    bid = None
    if boundary is None:
        found.append(
            f"{prefix} carries no boundary; an area references one primary-"
            "substation boundary, {source, id}"
        )
    elif isinstance(boundary, list):
        found.append(
            f"{prefix} carries {len(boundary)} boundaries; an area references "
            "exactly one"
        )
    elif not (
        isinstance(boundary, Mapping)
        and set(boundary) == {"source", "id"}
        and all(isinstance(boundary[k], str) for k in ("source", "id"))
    ):
        found.append(f"{prefix}: its boundary is not an object {{source, id}} of strings")
    else:
        source = _get(boundary, "source")
        if source not in BOUNDARY_SOURCES:
            found.append(
                f"{prefix}: boundary source {source!r} is not one of "
                f"{', '.join(BOUNDARY_SOURCES)}"
            )
        bid = boundary_id(area)
        if bid is None:
            found.append(f"{prefix}: boundary id is missing or blank")
        elif len(bid) > BOUNDARY_ID_MAX_LENGTH:
            found.append(
                f"{prefix}: boundary id is {len(bid)} characters; at most "
                f"{BOUNDARY_ID_MAX_LENGTH} are allowed"
            )

    if len(nodes) != 1:
        found.append(
            f"{prefix} lists {len(nodes)} topology nodes; an area lists exactly "
            "one, its primary substation"
        )
        return found

    if bid is not None and nodes[0] != bid:
        found.append(f"{prefix}: its topology node is not its boundary id")
        return found

    matching = [n for n in topology if _get(n, "id") == nodes[0]]
    if not matching:
        found.append(
            f"{prefix}: its topology node is not a node of the community's topology"
        )
    elif len(matching) > 1:
        found.append(
            f"{prefix}: the community's topology holds {len(matching)} nodes with "
            "its node's id; exactly one is allowed"
        )
    elif _get(matching[0], "type") != PRIMARY_SUBSTATION:
        found.append(
            f"{prefix}: its topology node is of type "
            f"{_get(matching[0], 'type')!r}, not {PRIMARY_SUBSTATION!r}"
        )
    return found


def area_boundary_refusals(
    areas: Mapping[str, Any],
    topology: Iterable[Any],
    *,
    only: Iterable[str] | None = None,
) -> list[str]:
    """Every REQ-0067 refusal among ``areas``, as detail sentences.

    ``only`` limits the per-area checks to those keys — the area ``PUT`` judges
    the area it writes, not siblings stored before the rule existed — while
    uniqueness is still judged against every area that carries a boundary id.
    """
    topology = list(topology)
    judged = sorted(areas) if only is None else sorted(set(only))
    found: list[str] = []
    for key in judged:
        found.extend(area_refusals(key, areas[key], topology))

    by_id: dict[str, list[str]] = {}
    for key in sorted(areas):
        bid = boundary_id(areas[key])
        if bid is not None:
            by_id.setdefault(bid, []).append(key)
    for keys in by_id.values():
        if len(keys) > 1 and set(keys) & set(judged):
            named = ", ".join(repr(k) for k in keys)
            found.append(
                f"areas {named} reference one boundary; no two areas of a "
                "community reference the same primary substation"
            )
    return found


def areas_referencing(areas: Mapping[str, Any], node_id: str) -> list[str]:
    """The keys of every area whose ``topology`` lists ``node_id``, sorted.

    Every area, including one stored before the rule: a node an area names is
    in use whether or not that area keeps the rule (REQ-0072).
    """
    found = []
    for key in sorted(areas or {}):
        nodes = _get(areas[key], "topology") or []
        nodes = list(nodes) if isinstance(nodes, (list, tuple)) else [nodes]
        if node_id in nodes:
            found.append(key)
    return found


def node_write_refusals(
    areas: Mapping[str, Any],
    before: Iterable[Any],
    after: Iterable[Any],
    node_id: str,
) -> list[str]:
    """What a topology node write would break, as detail sentences (REQ-0072).

    Judges only the areas that list ``node_id``, and among them only those that
    keep the rule with the topology as it is (``before``): a node write never
    breaks an area that keeps it — changing the ``type`` of an area's node away
    from ``primary_substation`` is refused — while an area stored before the
    rule is not re-judged by a write to one of its nodes, as REQ-0067 leaves a
    sibling alone on the area ``PUT``.
    """
    before, after = list(before), list(after)
    found: list[str] = []
    for key in areas_referencing(areas, node_id):
        if area_refusals(key, areas[key], before):
            continue
        found.extend(area_refusals(key, areas[key], after))
    return found


def child_nodes(topology: Iterable[Any], node_id: str) -> list[str]:
    """The ids of every other node naming ``node_id`` as its ``parent``, in order.

    A node such a child names cannot be deleted (REQ-0072): the child
    would be left pointing at a node that does not exist.
    """
    return [
        _get(n, "id")
        for n in topology
        if _get(n, "parent") == node_id and _get(n, "id") != node_id
    ]
