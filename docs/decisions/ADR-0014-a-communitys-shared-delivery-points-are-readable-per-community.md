# ADR-0014 — a community's shared delivery points are readable over HTTP, per community, naming no one outside it

**Date:** 2026-10-01
**Status:** accepted

## Context

ADR-0013 gave operators a CLI report of delivery points held by more than one active member,
reading the whole registry through the export grant, and left an HTTP route for a console to
be decided when one was wanted. The operator console — onboarding — now wants it (plan
decision F8, the requester, 2026-10-01): an operator correcting a member's POD needs to see
which of the community's points the registry will refuse (`delivery_point_held`, ADR-0012)
before a write is refused.

The console holds `rec-registry.read`, not the export grant. Giving it the export grant would
hand it every community's members; reading the export and filtering in the console would do
the same with extra steps.

## Decision

- **A per-community read:** `GET /admin/communities/{ck}/delivery-points/duplicates`, in the
  community's delivery-point read family, deriving `read` like every other `GET` under
  `/admin`. No new action or scope.
- **For each point an active member of the community holds that another active member also
  holds:** the compared form, this community's holders by member key with the spelling each
  stored, a count of active holders in other communities, and the total.
- **Holders outside the community are a count, never a member key or a community** — the rule
  the `delivery_point_held` refusal already follows (ADR-0012), because which member of which
  other community holds a point is the enumeration disclosure the registry refuses
  everywhere. The CLI report (ADR-0013), behind the export grant, stays the cross-community
  view.
- **One definition of a duplicate:** the route feeds one query's rows — every active holder of
  every point the community's active members hold — to the CLI's finder,
  `find_duplicate_delivery_points`, moved beside the compared form in
  `core/delivery_point_id.py`. The read and the report cannot disagree.

## Consequences

**An operator can see that a point is held elsewhere and not by whom.** Resolving such a
clash still needs whoever holds the export grant to run the CLI report, or the member to be
asked, as the console's refusal message already says.

**`held_elsewhere` is a count, and a count is a little information** about other
communities: that some number of their active members hold this point. It is the least the
console needs to tell "two of ours" from "one of ours and someone else's", and it names
nobody.

**`duplicates` becomes a fixed segment under `…/delivery-points/`**: the access-log redaction
leaves this one path as it is, and the derivation tests carry it among the routes whose ids
are hostile. A future route under the same prefix has to do the same.
