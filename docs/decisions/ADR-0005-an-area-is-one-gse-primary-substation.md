# ADR-0005 — an area is one GSE primary substation, referenced by id and never stored as a shape

**Date:** 2026-09-27
**Status:** accepted

## Context

A member names an `area`; the area lists `topology` node ids; the platform's pipelines copy
that list onto each member and take its **first** entry as the member's primary substation.
Shared energy is settled per primary substation. Nothing in the registry holds the list to
that reading: an area may list any number of nodes, a node id need not exist in the
community's topology, and several areas may point at the same substation. So an area listing
three substations settles all of its members under the first, whether or not they sit there,
and two areas naming one substation are indistinguishable downstream.

Areas exist to model the GSE incentive, and nothing else depends on them. The authoritative
boundaries are the GSE conventional primary-substation areas, one per substation code
(`cod_ac`), already loaded as a gold dataset and reachable through the Digital Twin. The
registry already carries an optional `geometry` per area and per topology node; nothing reads
either.

## Decision

- **An area references exactly one boundary:** `boundary: {source: "gse_cabine_primarie",
  id: "<cod_ac>"}`.
- **It lists exactly one topology node, of type `primary_substation`, whose id equals
  `boundary.id`**, and that node exists in the community's `topology`. The first node is the
  substation because it is the only one.
- **No two areas of one community reference the same `cod_ac`.**
- **Area keys stay hand-managed names**, mapped to their substation by the boundary reference;
  the key is not the code.
- **No geometry is stored or read.** The registry keeps a reference; the shape is resolved
  through the Digital Twin by whoever needs it. `geometry` and topology `area` stay in the
  schema for compatibility and stay unused. The registry does not check the id against the
  GSE dataset — it has no access to it; the template import in onboarding does.
- **Enforced on every write that can change an area or the topology:** the area `PUT`, the
  topology node routes, and the bundle import, each answering `422` with the code
  `invalid_area_boundary`. The community `PATCH` is not an enforcement point, because it never
  touches areas or topology (REQ-0029).
- **Published as bundle schema v0.7**, with `Area.boundary` and the cardinality above;
  `CURRENT_SCHEMA_VERSION` and the OpenAPI `info.version` move with it.

## Consequences

**Every bundle written before v0.7 is refused** if it has areas: none of them carries a
boundary. Old backups have to be reshaped before they restore — see
[ADR-0007](ADR-0007-import-refuses-a-bundle-that-breaks-an-invariant.md).

**A member's substation is one chain with no choice in it:** member → area → `boundary.id` →
the pipelines' substation. A manager changing a member's area changes that member's
substation, which is the point of letting them.

**When GSE revises a perimeter, nothing here moves.** The registry holds a code, and a
member's area does not change because a boundary did; a manager moves the member.

**A country with another boundary scheme is a new `source` value**, not a new field — which
is the reason the reference names its source rather than assuming GSE.

**The temptation is to copy the shape in** "so the registry is self-contained". The copy would
drift from GSE's revisions with nothing to notice, and the registry would become the second
source of a dataset it does not own.
