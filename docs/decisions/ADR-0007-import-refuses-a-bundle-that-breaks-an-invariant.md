# ADR-0007 — import refuses a bundle that breaks an invariant, and old backups are reshaped rather than tolerated

**Date:** 2026-09-27
**Status:** accepted

## Context

The import has been lenient on purpose. A bundle declaring an unknown or older schema version
is imported with a warning (REQ-0018), a meter with no sensor id is skipped with a warning
(REQ-0035), and REQ-0018 gives the reason: refusing would break restoring a backup, and a
backup is restored when something has already gone wrong.

The invariants now being added — one active holder per sensor id
([ADR-0004](ADR-0004-a-sensor-has-one-active-holder-and-detaching-deletes-the-meter.md)),
closed role and status sets and an area that exists, one substation per area
([ADR-0005](ADR-0005-an-area-is-one-gse-primary-substation.md)) — are enforced on every
runtime write. If the import only warned about them, a bundle would be the way to create
exactly the rows the write API refuses, and every reader downstream would have to handle a
state the registry claims cannot exist.

## Decision

- **Import refuses a bundle that breaks any of those invariants**, as a whole, before any
  database work: `422` with the invariant's code, and a report naming the offending keys. A dry
  run reports every refusal it would make instead of stopping at the first.
- **The schema-version check stays a warning.** A version mismatch is not an invariant; an
  invariant breach is refused whatever version the bundle declares.
- **Bundles written before v0.7 are reshaped, not accommodated.** An area without a boundary,
  or with several topology nodes, is refused; there is no compatibility branch in the
  importer. A one-off reshape of an existing file is an operation performed outside the
  product.
- **What is merely incomplete keeps its warning.** A meter with no sensor id — including one
  that is blank after trimming — is still skipped and named, not refused.

## Consequences

**An old export no longer restores as it is.** That is the cost REQ-0018 named, now accepted:
a restore of a pre-v0.7 backup needs the reshape first. The compensation is that a restored
community satisfies the same invariants as a live one.

**The round trip still holds for anything written today** — an export of a v0.7 community
re-imports unchanged (REQ-0037) — because an export is built from rows that already passed
the checks.

**A sensor held in another community refuses the import of this one.** The clash is
registry-wide, so a bundle can be refused because of a community it does not name; the report
says so without naming that community.

**The temptation is to make the refusals warnings "just for restores"**. That reintroduces the
second door ADR-0004 and ADR-0005 exist to close.
