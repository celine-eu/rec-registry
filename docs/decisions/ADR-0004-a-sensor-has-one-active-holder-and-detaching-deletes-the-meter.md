# ADR-0004 — a sensor id has one active holder across the registry, and detaching a meter deletes it

**Date:** 2026-09-27
**Status:** accepted

## Context

A sensor id is how a reading finds its owner (REQ-0039). Nothing today stops two members
holding the same one — in one community, or in two — and every consumer that joins readings
to members would then count those readings twice. Asset keys are unique per community only,
and `sensor_id` carries a lookup index, not a uniqueness constraint.

Meters are about to be attached by community managers, by hand, as free text: a manager types
the id printed on the device. There is deliberately no list to pick from. A meter not yet
attached belongs to no community, so any candidate list would either show one community the
meters of another or assign a meter to the wrong one. The registry's answer to the attach is
the only feedback the manager gets, so that answer has to be right — including across
communities the manager cannot see.

## Decision

- **At most one active member in the whole registry holds a given sensor id.** A member whose
  status is not `active` holds nothing: deactivating a member releases its sensors, and
  reactivating one re-checks them — if another active member took one of its sensors
  meanwhile, the reactivation is refused with `sensor_held` and the member stays as it was.
- **The comparison is on the trimmed id**, and new writes store it trimmed, so ` SEN-1` and
  `SEN-1` are one sensor. Trimming strips every Unicode whitespace character, identically in
  Python and in the SQL that compares stored rows. An id that is blank after trimming counts as missing.
- **Every path that can make an active member hold a sensor checks it:** the asset `PUT`,
  creating a member with assets, a status change to `active` (the status route and `PATCH`),
  and the bundle import. A clash answers `409` with the code `sensor_held`.
- **Check and write happen under one transaction-scoped advisory lock keyed on the trimmed
  id**, so two managers attaching one sensor at once get one success and one `sensor_held`,
  never two successes. An attach and a reactivation of the same member also lock that
  member's row first, so an attach to a suspended member cannot slip past its concurrent
  reactivation.
- **`sensor_held` names nobody outside the community addressed.** Inside it, the answer may
  name the holding member's key, as the DID clash does (REQ-0060); in any other community it
  names neither member nor community.
- **An attached meter's asset key is `meter-<trimmed sensor id>`**, the convention the
  dashboard uses, so a re-attach of the same sensor to the same member is the idempotent
  upsert REQ-0028 already defines.
- **Detaching is a hard delete of the asset** (`DELETE …/assets/meter-<sensor id>`, `204`).

## Consequences

**Detaching loses the pointer from past readings to that member.** Readings are joined to
members without dates, so after a detach the sensor's whole history follows its next holder,
and the previous holder's share of it is attributed to nobody until then. That is accepted for
now; dated holdings — a meter held from one date to another — are the recorded follow-up, and
the reason this is a delete rather than a soft end-date that nothing would read yet.

**A meter cannot move within a community until the old asset is deleted.** The key
`meter-<sensor id>` is unique per community whatever its holder's status, so an inactive
member who still holds the asset blocks the attach with a key clash — a code distinct from
`sensor_held`, because the remedy differs: delete the old asset, then attach.

**Existing duplicates are not repaired by this.** A registry that already holds a sensor on
two active members keeps both rows until someone acts; the check refuses the next write, not
the past ones. A report of existing duplicates runs before the check is switched on.

**The temptation is to relax "any community" to "this community"** the first time a
cross-community clash surprises someone. The double count it prevents is invisible where it
happens and only shows up in settlement.
