# ADR-0002 — requirements may be written ahead of the code, marked `planned`

**Date:** 2026-09-27
**Status:** accepted

Amends [ADR-0001](ADR-0001-requirements-are-read-out-of-the-code.md), whose first rule —
"every `REQ-####` in `docs/specifications/` is something the service does today" — no longer
holds without exception. The rest of ADR-0001 stands.

## Context

ADR-0001 was written for a repository that had behaviour and no statement of it, and it
closed with the case this record handles: *"when the product conversation happens, the
requirements it settles supersede these"*.

That conversation has happened. A manager attaching meters and correcting a member's role
and area needs the registry to refuse a sensor already held elsewhere, to name a narrower
action for the profile write, to hold areas to one primary substation each, and to refuse an
import that breaks any of that. Several other repositories build on those answers at the
same time — a dashboard, onboarding, the SDK — and each needs the registry's contract written
down before the registry's code exists, so that all of them build against one statement
rather than against each other's guesses.

Under ADR-0001 alone there are two ways to do that and both are wrong: write the contract
somewhere other than the requirements, where no test can name it; or write it as ordinary
requirements, which the projection would then report as *unverified* — indistinguishable
from a requirement whose test was lost.

## Decision

A requirement may land before the code that satisfies it, provided it says so.

- It carries the line `**Status:** planned` directly under its heading.
- It states the behaviour the code **will** have, as precisely as an implemented one, and
  names the decision record it comes from.
- **No test declares it yet.** A `@verifies` tag naming a planned requirement is an error
  either way round: the status is stale, or the tag is wrong.
- **The change that makes it pass removes the status line** in the same change as the code
  and the tests that declare it. An unmarked requirement is one the code does today, exactly
  as ADR-0001 defines it.
- **An implemented requirement is never rewritten to describe a planned change.** Where a
  planned change alters existing behaviour, the existing requirement keeps describing today
  and gains a paragraph headed **Planned** pointing at the new requirement; that paragraph
  goes when the new requirement is implemented.

## Consequences

**The projection has three answers now, not two.** A requirement is verified, unverified, or
planned; `docs/specifications/index.md` gives the grep for the third. The checker that owns
the matrix does not know the status line yet, so until it does, it will report planned
requirements as unverified, and a reader has to subtract them by hand.

**A planned requirement is a promise, and promises rot.** One that sits planned for months is
the aspiration ADR-0001 refused to write. The remedy is the same as for any stale document:
delete it, or implement it — not leave it.

**The temptation is to write the planned version into the implemented requirement** because
the diff is smaller. That makes a requirement describe behaviour the code lacks while its old
tests still pass — the exact matrix-lies-to-the-reviewer outcome ADR-0001 exists to prevent.
