# ADR-0006 — onboarding templates are the source of truth for areas, written through the area and topology routes

**Date:** 2026-09-27
**Status:** accepted

## Context

Areas and topology have been authored in the bundle a community is seeded from, and changed
afterwards by hand if at all. Once an area is one primary substation
([ADR-0005](ADR-0005-an-area-is-one-gse-primary-substation.md)), the list of a community's
areas is the list of substations it covers — and the place that already decides coverage is
onboarding, whose per-community template says who is eligible and which area a new member
lands in. Two places declaring the same list drift.

The registry can write one area at a time (`PUT …/areas/{key}`), but **topology has no write
route**: it is a collection with its own identity, deliberately absent from the community
`PATCH`, and today only a bundle import writes it.

## Decision

- **The onboarding template declares a community's areas** — hand-managed names, each with its
  `cod_ac` — and onboarding writes them to the registry in an explicit, admin-driven sync,
  never on template reload.
- **Topology gains node routes:** `PUT` and `DELETE /admin/communities/{community_key}/topology/{node_id}`,
  one node at a time, merging by id and leaving sibling nodes untouched, under
  `community.write`. `DELETE` is refused while an area references the node.
- **The sync uses the public routes and nothing else**: an area `PUT` and a topology node `PUT`
  per area; removal is an area `DELETE`, which is refused while members reference the area
  (REQ-0030), and then a node `DELETE`. There is no bulk areas endpoint.
- **onboarding's service account holds `rec-registry.community.write`** for this. Like every
  registry grant it is registry-wide; onboarding confines itself to the communities its
  templates bind.

## Consequences

**The database stops being the source of truth for areas**, while it stays one for members and
meters: members arrive through onboarding, meters through a manager, areas from the template.
A bundle import can still write areas; onboarding's drift check is what makes that visible.

**Two more writes for `TestNoWriteReducesASibling`**, and a merge-by-id requirement for
topology that mirrors the one for delivery points (REQ-0027).

**The registry cannot tell the sync from any other caller.** It enforces the area invariant on
every write; it does not know, and does not check, that the template was the origin.

**The temptation is a "replace all areas" endpoint** because the sync would be one call. That
is a collection-level replace outside the import, which REQ-0031 exists to forbid.
