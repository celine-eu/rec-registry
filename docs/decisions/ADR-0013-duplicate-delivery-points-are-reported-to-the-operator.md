# ADR-0013 — delivery points already held twice are reported to the operator

**Date:** 2026-10-01
**Status:** accepted

## Context

ADR-0012 made the registry refuse every write that would give a delivery point a second
active holder, and left the duplicates already stored in place: each of them blocks the next
write that touches the point — a re-send of either holder's point, a reactivation of either,
a re-import of either community. ADR-0012 noted that no report of them existed, unlike the
sensors, whose `duplicate-sensors` report (ADR-0004, REQ-0076) is run before that check is
relied on.

A clash across communities is the one no community's manager can see, and the registry's
refusal names nobody outside the addressed community. Without a report, an operator learns of
a stored duplicate only when a write is refused, and then cannot see the other holder.

## Decision

- **Report them, the way `duplicate-sensors` reports sensors** (plan decision F7, the
  requester, 2026-10-01: operator-facing, so operators can act on them):
  `celine-rec-registry duplicate-delivery-points`.
- **Same shape, same reach.** A read-only CLI command that reads every community through
  `GET /admin/export` — the export grant, which sees every community — issues no other
  request, and prints one tab-separated line per active holder of each point held by more than
  one active member: `delivery_point`, `community`, `member`, `active_holders`. Exit `0` when
  there are none, `1` when there are, `2` when the registry cannot be read.
- **The registry's own comparison.** Points are compared and printed trimmed and lower-cased,
  by the one definition the writes use (`core/delivery_point_id.py`); only active members
  hold; a member listing a point twice is one holder.
- **No HTTP route**, as there is none for `duplicate-sensors`: the export already answers
  everything the report needs, under a grant that already means "may read every community".

## Consequences

**An operator resolves each line by hand** — a correction of one holder's POD with
`replaces`, or a deactivation of one holder — and the report is how they find the other
holder the refusal would not name.

**The point is printed in its compared form**, lower-cased, not as either holder stored it.
That is the form the registry compares; looking a point up in the registry is
case-sensitive on the read routes, so an operator searching for it uses the member keys the
report prints, not the printed id.

**A console needs the export grant to show the same thing.** If an operator console is to
show this list, it either holds `rec-registry.export` or a dedicated read route is decided
then; this ADR adds neither.
