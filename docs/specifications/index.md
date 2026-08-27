# Requirements

What this service must do, stated so that a test can name it.

These were **distilled from the code, not written before it** — see
[ADR-0001](../decisions/ADR-0001-requirements-are-read-out-of-the-code.md). Every one is
something the registry does today and something a reader would want to stay true; none is
an aspiration.

## Why this service in particular

**This is the platform's answer to "who is in this community".** It depends on almost
nothing and is read by six other repositories, and **none of their suites runs against
it**. That asymmetry is the reason a written, traceable requirement is worth more here
than in a service with a user watching it: a wrong row here is wrong everywhere, and
nothing downstream can tell.

Two of those consumers make it concrete. `../onboarding` **writes** members on approval,
through SDK wrappers that are not in a published release yet. `../dataset-api` uses
membership to decide access — so a member wrongly deactivated here is a member who cannot
see their own data there, and the error surfaces three repositories away from its cause.

## One of them describes a defect

It is written as behaviour anyway. A requirement describing the *intended* behaviour would
be an unverified wish, and the trace matrix would report it as covered. It names its issue,
and fixing it means changing the code, the requirement and its test in the same change.

| | | |
|---|---|---|
| REQ-0043 | `assets-by-sensor-ids` carries no bound, while its sibling caps at 500 | [#37](https://github.com/celine-eu/rec-registry/issues/37) |

Its tests assert the **mismatch**, not the intended value, so closing the defect turns them
red deliberately rather than leaving a test that passes for the wrong reason.

REQ-0018 and REQ-0058 were the second entry here — version reporting, four places holding
three values with nothing reading the field
([#38](https://github.com/celine-eu/rec-registry/issues/38)). Closed: both now describe
what the code does rather than what it fails to do, and their tests went red on the way, as
this section says they would.

## How a requirement is verified

A test declares what it covers with a `@verifies REQ-####` tag in its docstring:

```python
async def test_a_stranger_is_indistinguishable_from_someone_who_owns_nothing(live_client):
    """@verifies REQ-0045"""
```

The mapping is a projection of the two and is never written by hand. the harness profile
names `provider = "harness"`, so the checker owns it; until that checker is available in
this checkout the projection is a grep — `--include='*.py'` because `__pycache__` matches
otherwise:

```bash
grep -rho --include='*.py' "@verifies REQ-[0-9]\{4\}" tests/ | sort | uniq -c
grep -rhoE '^### (REQ-[0-9]{4})' docs/specifications/*.md | sort
```

It has to be read **both ways**: a requirement no test declares is unverified, and a tag
naming a requirement that does not exist is a typo — and a typo in a trace tag is
indistinguishable from coverage until someone reads the matrix.

Adding a requirement means adding a `REQ-####` here **and** a test declaring it, in the
same change. The procedure is in the companion's testing playbook.

## The requirements

| | |
|---|---|
| REQ-0001 – REQ-0010 | [identity and authorisation](identity-and-authorisation.md) — who the caller is and what they may do |
| REQ-0011 – REQ-0019 | [the registry model](registry-model.md) — what a community, member and asset are |
| REQ-0020 – REQ-0031 | [member and community writes](member-writes.md) — how a community changes at runtime |
| REQ-0032 – REQ-0037 | [import and export](import-and-export.md) — the destructive path, and its guard |
| REQ-0038 – REQ-0045 | [cross-community lookup](lookup.md) — which community is this in |
| REQ-0046 – REQ-0053 | [self-service](self-service.md) — what a participant may see about themselves |
| REQ-0054 – REQ-0058 | [operability](operability.md) — the CLI, health, version |

## What is not covered

Unverified by any suite here, whatever this document says. Each area's own page repeats the
part that belongs to it.

- **The six repositories that read this one.** `../digital-twin`, `../celine-webapp`,
  `../onboarding`, `../celine-ai-assistant`, `../flexibility-api` and `../dataset-api` all
  consume the registry through `celine.sdk.rec_registry`, and none of their suites runs
  against this service. `../celine-policies`' `keycloak sync-users` reads a REC definition
  from here out of band.
- **The middleware.** REQ-0001 – REQ-0008 pin `_get_admin_action`, a pure function, called
  directly. JWT parsing and verification, the decision cache, and the `401`/`403` a real
  request would receive are not exercised — the suite runs with `AUTH_ENABLED=false` and
  `POLICIES_ENABLED=false`.
- **The migrations, beyond the shape they build.** `tests/test_migrations.py` runs
  `alembic upgrade head` into a throwaway schema and asserts it matches `Base.metadata`, so
  a model that drifts from `alembic/versions/` no longer passes. What that does not cover:
  `downgrade`, which drops the three tables and has never been run; and what a migration
  does to a database that already holds rows — the check builds an empty schema, so
  locking, backfill and anything a revision does to existing data are unexercised.
- **The Keycloak realm.** Operator authorisation depends on organizations and groups that
  `../celine-policies` syncs, and nothing here would notice a rename.
- **Read pagination.** `limit`, `cursor` and the filters on the community, member, asset
  and delivery-point listings are used incidentally by other tests and asserted by none.
  `MAX_PAGE_SIZE` is not exercised at all.
- **The exporter, directly.** It is covered only through the round trip (REQ-0037), which
  means its output is verified as *re-importable* and never as *correct*.
- **Concurrency, beyond member uniqueness.** Two writers racing on a member `key` or
  `user_id` are covered (REQ-0022) — constraint, translation and test. No other overlapping
  write is. `asset` carries the same unique index on `(community_id, key)` and nothing
  translates it, so two callers creating one asset key at once still answer `500`; two
  upserting an area resolve by last-writer-wins, unchecked.

## What is not here

- **Why** a choice was made — [`docs/decisions/`](../decisions/index.md).
- What the system *is* — [`docs/data-model.md`](../data-model.md) and
  [`docs/api-reference.md`](../api-reference.md).
- A trap that is true of the code and not obvious from reading it — the companion's knowledge.
- Anything broken — the issue tracker.
