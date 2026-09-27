# ADR-0003 — role and area are written through their own route and action, and no caller-supplied id can change an action

**Date:** 2026-09-27
**Status:** accepted

## Context

A community manager needs to correct a member's `role` and `area`: onboarding sets the first
from a self-declared answer and the second from a municipality list, and both decide how the
member's meter readings are settled. The dashboard that does this must not be able to do
more — `members.write` would let it rewrite a member's `user_id`, `did` and status, which is
how one participant's identity ends up on another's meters.

The first design narrowed the existing `PATCH …/members/{key}` by its body: a patch naming
only `role` and `area` would derive a narrower action. The middleware cannot do that. It
derives the action from the path and the method (REQ-0001); `_get_admin_action` never sees
the body, and reading it there would put JSON parsing, and the question of what an empty or
malformed body means, in front of every admin request.

Reviewing the derivation turned up a second problem. It matches by **substring over the whole
path**: anything containing `lookup`, `import` or `export` derives those actions before the
method is even considered, and `/assets` is tested before `/members`. Member keys, asset keys
and, soon, topology node ids are chosen by the caller — an asset keyed `meter-<sensor id>`
carries whatever the sensor id carries. An id containing one of those words derives an action
the route never meant, and a holder of the matching grant reaches a write it was never given.

## Decision

- **A dedicated route:** `PATCH /admin/communities/{community_key}/members/{member_key}/profile`,
  accepting `{role?, area?}` — at least one key, and no other. It derives the new action
  **`members.profile.write`**, granted by the scope `rec-registry.members.profile.write`.
- **A superset in the policy, not in the matcher:** the rule for `members.profile.write` in
  `access.rego` also accepts `rec-registry.members.write` and `rec-registry.admin`. The shared
  scope matcher stays as it is (exact, `.admin`, `.*`), so a service that already writes
  members keeps being able to write their role and area without a new grant.
- **The general member `PATCH` keeps accepting `role` and `area`** for `members.write`
  holders. The new route is the narrow door, not a replacement. The value checks are the same
  on both routes: `role` must be one of the closed set and `area` a key of the community's
  areas (REQ-0066), whichever route writes them.
- **Actions are derived from the route's fixed segments.** Which action a request derives
  depends on the literal segments of the route it matches, by position, and never on the
  content of a segment the caller supplies. Hostile ids — keys and node ids containing
  `lookup`, `import`, `export`, `assets`, `members` or `profile` — are pinned by tests.
- **The derivation fix lands first**, as the first change of this set and before any
  caller-supplied `meter-<sensor id>` asset key is written (ADR-0004). It corrects a defect
  in the current code, not only a risk of the new route, so it does not wait for the rest.

## Consequences

**The action list grows to ten**, and REQ-0010's set check grows with it — the check exists
because an action added to the middleware and not to the bundle presents as an unexplained
`403`.

**One more write for `TestNoWriteReducesASibling`.** A route that writes two fields of one
member is exactly the kind of write that registry exists to catch.

**The grant is registry-wide**, like every registry grant: a holder of
`rec-registry.members.profile.write` can correct any community's members. Keeping a manager to
their own community is the dashboard's policy, not this service's.

**The temptation is to "just read the body"** the next time a narrower grant is wanted on an
existing route. That makes authorisation depend on parsing untrusted input before deciding
whether to parse it at all; a route per grant is the shape this service keeps.
