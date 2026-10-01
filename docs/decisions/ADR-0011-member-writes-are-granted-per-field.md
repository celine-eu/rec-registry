# ADR-0011 — a member's fields are written through per-field routes, each with its own grant

**Date:** 2026-10-01
**Status:** accepted

## Context

The registry's member writes were granted in two sizes: `members.write`, which creates members
and rewrites any field including `user_id`, `did` and status, and `members.profile.write`, a
one-off narrowing for role and area (ADR-0003). Each new caller needing less than
`members.write` produced another one-off. Two now did at once:

- the community dashboard's backend writes role and area, and will write nothing else of a
  member;
- onboarding corrects a member's name and delivery points after approval. It holds
  `members.write` only because creating members needs it, and the correction does not.

ADR-0003 already settled two things that constrain the answer. Authorisation is derived from
the route's fixed segments and the method, never the body: the middleware decides before
anything is parsed, and a body-driven check would make authorisation depend on parsing
untrusted input. And a narrower grant is a superset rule in the policy, not a change to the
shared scope matcher.

## Decision

- **One sub-route per field group, one action per route, one scope per action.**
  `PUT …/members/{mk}/name`, `…/role` and `…/area`, each taking exactly its one key, derive
  `members.name.write`, `members.role.write` and `members.area.write`; `PUT` and `DELETE`
  `…/members/{mk}/delivery-points/{id}` derive `members.delivery_points.write`. The scopes are
  `rec-registry.<action>`.
- **Naming keeps the existing order**, `<resource>.<field>.write`, as `members.profile.write`
  already does, so `rec-registry.admin` keeps covering every action through the shared
  matcher. Where the route segment is hyphenated (`delivery-points`) the action uses an
  underscore.
- **Each action's rule accepts the grants that already wrote that field**: `members.write`
  and `.admin` for all four, and `members.profile.write` also for role and area. No caller
  loses a write when a narrower route appears.
- **Identity stays coarse.** Creating a member, `user_id`, `did`, status and the general
  `PATCH` stay `members.write`: those bind a person to a member, and only onboarding holds
  them. There is no narrow route for an identity field, and a segment not in the list derives
  `admin`.
- **`PATCH …/profile` stays**, as the role-and-area alias of the two field routes, so no
  caller breaks.
- **The value checks are shared.** A field route calls the same check and the same write as the
  general `PATCH`; the narrow door is never a looser one.
- **The query is not read either.** `?replaces=` on the delivery-point `PUT` (ADR-0012) changes
  what the write does, not who may do it.
- **Extension is a segment, a rule and a scope.** A new field group is one entry in the
  middleware's `_MEMBER_FIELD_ROUTES`, one rule in `access.rego`, one scope declared in
  `../celine-policies`, and the route — plus its hostile-id cases and its place in
  `TestNoWriteReducesASibling`.

## Consequences

**The action set grows to fifteen**, and REQ-0010's set check with it; every rule carries
`.admin`, which a test reads.

**More routes, each a one-key body.** That is the cost of never reading a body for
authorisation, and it is paid in the SDK: each route is a wrapper. The general `PATCH` is not
removed, so a `members.write` holder may keep writing several fields at once.

**The grants are still registry-wide.** A holder of `rec-registry.members.area.write` can set
the area of any community's members; keeping a manager to their own community stays the
dashboard's policy.

**Granting moves to `../celine-policies`.** The registry declares the actions; which client
holds which scope is decided there. Until a client is moved to the narrow scope, it keeps
working through its superset.

**The temptation is to collapse the field routes into one `PATCH` with a body-derived
action** the next time a field is added. ADR-0003's reasons still hold; the extension recipe
above is the shape this service keeps.
