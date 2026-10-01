# ADR-0012 — a delivery point has one active holder across the registry, and is corrected in one write

**Date:** 2026-10-01
**Status:** accepted; amended by ADR-0013

## Context

A member's delivery point (a POD) is declared by the member at onboarding, typed by hand, and
is what consent and settlement use to find the member's supply. Nothing stopped two members
holding the same one, in one community or in two. The case that matters is not a deliberate
share but a mistyped POD that happens to be somebody else's: the registry would then attribute
one supply point to two people, and nothing downstream can tell.

Correcting a wrong POD was also three calls: add the new point, relink every meter whose
`properties.pod` named the old one (an asset write, needing `assets.write`), and remove the old
point. A failure between them left a member with both points, or a meter naming a point the
member no longer has, and the caller doing the correction — onboarding — needed an asset grant
for a member-data change.

ADR-0004 had already settled the same question for sensor ids, and its mechanism — only active
members hold, compare trimmed, check every path under an advisory lock, name nobody outside the
addressed community — fits delivery points unchanged.

## Decision

- **At most one active member in the whole registry holds a given delivery point.** A member
  whose status is not `active` holds nothing; reactivating one re-checks its points. A point's
  own `active` flag is not read: an active member holds every point it lists.
- **Compared trimmed and case-insensitively.** Trimmed by the character set ADR-0004's sensor
  ids use, in Python and in SQL alike; lower-cased on both sides. The id is stored as the
  caller spelled it — the registry has no canonical form for a POD and does not invent one.
- **Every path that can make an active member hold a point checks it**: the delivery-point
  `PUT` (with or without `replaces`), creating a member, a status change to `active`, and the
  bundle import. A clash is `409 delivery_point_held` (`422` on an import, where the bundle is
  what is wrong), in `sensor_held`'s body, naming a holder only inside the addressed community.
- **Under a transaction-scoped advisory lock keyed on the compared id**, in a namespace apart
  from the sensors', taken after the member's row lock and after any sensor locks: community
  row, member rows, sensor locks, delivery-point locks.
- **A POD correction is one write:** `PUT …/delivery-points/{new}?replaces={old}` adds `new`,
  removes `old` and relinks this member's meters whose `pod` named `old` to `new`, in one
  transaction under the member's row lock. `404` if `old` is not this member's. It derives the
  delivery-point action (ADR-0011): the relink is part of correcting the member's own data, and
  the caller needs no asset grant.
- **A point a meter of the member still names cannot be deleted** (`409
  delivery_point_linked`): the remedy is a correction with `replaces`, or detaching the meter.

## Consequences

**Existing duplicates are not repaired.** A registry already holding a POD on two active
members keeps both until someone acts, and each of them is refused the next write that touches
the point — including a re-import of either community. Unlike the sensors (ADR-0004), no
report of existing duplicates exists yet; one should run against a deployed registry before
this ships to it.

**The meter link is a string, not a reference.** A meter's `pod` is free text compared the
same way; nothing stops a meter naming a point its member does not list. This decision keeps
the two consistent on the writes it controls — the correction and the delete — and does not
validate the meter `PUT`.

**Re-sending the same POD with another spelling to the same member adds a second entry**,
because the merge of REQ-0027 is by exact id; a correction with `replaces` is the way to change
a spelling.

**The temptation is to relax "any community" to "this community"**, as for sensors, the first
time a cross-community clash surprises someone. The misattribution it prevents is invisible
where it happens.
