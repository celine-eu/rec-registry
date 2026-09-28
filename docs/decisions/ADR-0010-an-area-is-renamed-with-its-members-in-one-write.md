# ADR-0010 — an area is renamed with its members in one write

**Date:** 2026-09-28
**Status:** accepted

## Context

Onboarding templates are the source of truth for a community's areas
([ADR-0006](ADR-0006-onboarding-templates-are-the-source-of-truth-for-areas.md)), and an area
is one primary substation, with no two areas of a community on one boundary
([ADR-0005](ADR-0005-an-area-is-one-gse-primary-substation.md)). A template that renames an area
— same substation, new key — could not be synced once the area had members: the area `PUT`
under the new key is refused, because the old key still holds that boundary; the `DELETE` of
the old key is refused, because members still reference it; and a member cannot be moved to the
new key, because it does not exist. Every order of the existing writes breaks one rule or
another, and relaxing either rule for the length of a sync would let a reader see a community
that breaks it.

## Decision

- **A rename is its own write**: `POST …/areas/{area_key}/rename` with `{new_key}` (REQ-0079).
  In one transaction, under the community's row taken exclusively, the area as stored is
  written under the new key, every member of the community whose `area` is the old key —
  whatever their status — is moved to it, and the old key is removed.
- **It is a community write** (`community.write`), like the other area routes, although it
  moves members' `area`: it changes community structure, and the members follow it.
- **It changes nothing but the key and the members' `area`.** The area is not re-judged, and the
  set of boundary ids is the same before and after.
- **It refuses rather than merges**: a new key the community has is `409 area_key_taken`, an
  absent old key `404 area_not_found`, a new key that is not an area key `422
  invalid_area_key`.

## Consequences

**Onboarding's sync is to use it** when a template area names a substation a registry area holds
under another key, instead of reporting the old area for a prune that members would block.

**The lock order is the one every write already takes**, community row before member rows, so a
rename and a member write never wait on each other in a cycle.

**The temptation is to make the area `PUT` do this** when it meets its own boundary under
another key. That would turn a replace-one-area write into one that silently moves members, and
a typo in a key would move a whole area's members without anyone having asked for a rename.
