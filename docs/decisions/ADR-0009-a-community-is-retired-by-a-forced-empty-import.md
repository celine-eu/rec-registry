# ADR-0009 — a community is retired by a forced import with no members, and members arrive only through onboarding

**Date:** 2026-09-27
**Status:** accepted

## Context

A community seeded from a bundle can carry members that are not real: placeholder names and
accounts around a real meter. A deployment going live starts a **new** community instead —
managers first, then everyone through onboarding — and the old one has to stop holding its
meters, because a sensor has one active holder across the registry
([ADR-0004](ADR-0004-a-sensor-has-one-active-holder-and-detaching-deletes-the-meter.md)) and
the old placeholders would refuse every attach in the new community.

The registry has no community delete route and no "retired" status. REQ-0008 pins the action a
`DELETE /admin/communities/{key}` would derive, but no such route exists. Deactivating each
member one at a time would release the sensors but leave the rows, and nothing else would ever
read them.

## Decision

- **A community is retired by a forced import of a bundle naming the same community with no
  members.** The import replaces the graph (REQ-0032), so every member and asset of the old
  community is deleted and its sensors are released; the community row stays, with whatever
  metadata the bundle carries.
- **No new route and no new status.** Retirement is an operation, performed by a platform
  operator holding the import grant, outside the product.
- **On a deployed realm, members arrive only through onboarding.** A bundle carries the
  community's administrative data; loading members from a YAML file — the bundle's `members`
  or the policies tooling's `sync-users` — is for local development only.

## Consequences

**The import grant is purge-equivalent**, and always was: a forced import deletes every member
and asset of a community, which is more than `members.purge` can do to one member. REQ-0006's
separation of erasing from writing holds only for callers who do not hold `rec-registry.import`.

**A retired community looks like an empty one.** Nothing marks it retired, and a later import
could fill it again. That is acceptable while retirement is rare and deliberate; a status is
the follow-up if it stops being either.

**History is erased with the rows.** Readings keep their sensor ids and follow the sensors'
next holders; which placeholder held a sensor before is not kept here.

**The temptation is a `DELETE /admin/communities/{key}` "because the action already exists".**
A community delete cascades through every member and meter; it deserves its own decision, not
an inherited action name.
