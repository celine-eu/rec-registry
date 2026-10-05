# Requirements

What this service must do, stated so that a test can name it.

These were **distilled from the code, not written before it** — see
[ADR-0001](../decisions/ADR-0001-requirements-are-read-out-of-the-code.md). Every one is
something the registry does today and something a reader would want to stay true; none is
an aspiration — **except those marked `planned`**, which
[ADR-0002](../decisions/ADR-0002-requirements-may-be-written-ahead-of-the-code-marked-planned.md)
allows to land ahead of the code, and which say so (below).

## Why this service in particular

**This is the platform's answer to "who is in this community".** It depends on almost
nothing and is read by eight other repositories, and **none of their suites runs against
it**. That asymmetry is the reason a written, traceable requirement is worth more here
than in a service with a user watching it: a wrong row here is wrong everywhere, and
nothing downstream can tell.

Two of those consumers make it concrete. `../onboarding` **writes** members on approval,
through the SDK's registry wrappers (`celine.sdk.rec_registry`). `../dataset-api` uses
membership to decide access — so a member wrongly deactivated here is a member who cannot
see their own data there, and the error surfaces three repositories away from its cause.

Two more write. The community dashboard's backend, `../celine-community`, attaches and
detaches meters and corrects a member's role and area (REQ-0063, REQ-0066,
REQ-0069 – REQ-0071; the per-field routes of REQ-0081 – REQ-0083 when it moves to them),
and `../onboarding` writes a community's areas and topology from its templates through the
area and topology node routes (REQ-0067, REQ-0072); the area rename route (REQ-0079) is the
one its sync moves an area with members to a new key through, and a POD correction
(REQ-0084) the one it corrects a member's declared supply point through.

## None of them describes a defect

For a while two did, and then one. They were written as behaviour anyway — a requirement
describing *intended* behaviour would be an unverified wish, and the trace matrix would
report it as covered — with tests asserting the **mismatch**, so that closing each one
turned its tests red deliberately rather than leaving them passing for the wrong reason.

All three are closed:

| | | |
|---|---|---|
| REQ-0043 | `assets-by-sensor-ids` carried no bound while its sibling capped at 500 | [#37](https://github.com/celine-eu/rec-registry/issues/37) |
| REQ-0018, REQ-0058 | version reporting was decorative — four places, three values, nothing reading the field | [#38](https://github.com/celine-eu/rec-registry/issues/38) |

Each now describes what the code does, and the mechanism is kept here rather than deleted:
**a requirement may describe a defect, provided it says so and its test asserts the defect
rather than the wish.** That is what made these three closable as visible three-part
changes — code, requirement, test — instead of silent ones.

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
same change — unless it is planned. The procedure is in the companion's testing playbook.

## Planned requirements

A requirement written ahead of the code carries, directly under its heading:

```markdown
**Status:** planned
```

It states the behaviour the code will have and names the decision record it comes from. **No
test declares it**, so the projection reads it as planned rather than unverified — and a
`@verifies` tag naming it is an error: either the status is stale or the tag is wrong. The
change that implements it adds its tests and removes the status line; an unmarked requirement
is implemented. An implemented requirement whose behaviour a planned one will change keeps
describing today, with a paragraph headed **Planned** pointing at the new one.

```bash
awk 'FNR==1{id=""} /^### REQ-/{id=$2} id && /^\*\*Status:\*\* planned/{print id; id=""}' docs/specifications/*.md | sort
```

Read against the two lists above: every requirement is either declared by a test or listed
here, and never both. The checker that owns the matrix does not know the status line yet and
reports planned requirements as unverified.

## The requirements

| | |
|---|---|
| REQ-0001 – REQ-0010, REQ-0063 – REQ-0065, REQ-0081 – REQ-0082, REQ-0088 – REQ-0091 | [identity and authorisation](identity-and-authorisation.md) — who the caller is and what they may do |
| REQ-0011 – REQ-0019, REQ-0059, REQ-0066 – REQ-0069, REQ-0085, REQ-0093, REQ-0096 | [the registry model](registry-model.md) — what a community, member and asset are |
| REQ-0020 – REQ-0031, REQ-0060, REQ-0062, REQ-0070 – REQ-0073, REQ-0079, REQ-0083 – REQ-0084 | [member and community writes](member-writes.md) — how a community changes at runtime |
| REQ-0032 – REQ-0037, REQ-0074 – REQ-0075 | [import and export](import-and-export.md) — the destructive path, and its guard |
| REQ-0038 – REQ-0045, REQ-0061, REQ-0097 – REQ-0099 | [cross-community lookup](lookup.md) — which community is this in |
| REQ-0046 – REQ-0053, REQ-0094 – REQ-0095 | [self-service](self-service.md) — what a participant may see about themselves |
| REQ-0054 – REQ-0058, REQ-0076 – REQ-0078, REQ-0080, REQ-0086 – REQ-0087, REQ-0092 | [operability](operability.md) — the CLI, health, version, the access log |

Each page's own block was full and contiguous when the dataspace DID arrived, so
REQ-0059 – REQ-0061 append to the end of the universe and are listed against the page they
belong to rather than renumbering three ranges to keep them tidy. Later additions append the
same way; REQ-0063 – REQ-0075, written planned, did, and so did REQ-0076 – REQ-0080,
REQ-0081 – REQ-0087, REQ-0088 – REQ-0089, REQ-0090 – REQ-0092, REQ-0093 and
REQ-0094 – REQ-0096 and REQ-0097 – REQ-0099.

## What is not covered

Unverified by any suite here, whatever this document says. Each area's own page repeats the
part that belongs to it.

- **The eight repositories that read this one.** `../digital-twin`, `../celine-webapp`,
  `../onboarding`, `../celine-ai-assistant`, `../flexibility-api`, `../dataset-api` and the
  community dashboard's backend `../celine-community` consume the registry through
  `celine.sdk.rec_registry`; `../celine-pipelines` mirrors it from `GET /admin/export` and
  reads each member's area topology. None of their suites runs against this service.
  `../celine-policies`' `keycloak sync-users` reads a REC definition out of band — a
  local-development path only; on a deployed realm members arrive through onboarding
  ([ADR-0009](../decisions/ADR-0009-a-community-is-retired-by-a-forced-empty-import.md)).
- **The middleware.** REQ-0001 – REQ-0008 pin `_get_admin_action`, a pure function, called
  directly. JWT parsing and verification, the decision cache, and the `401`/`403` a real
  request would receive are not exercised — the suite runs with `AUTH_ENABLED=false` and
  `POLICIES_ENABLED=false`, under `CELINE_ENV=dev` — the only signal
  that lets the app start with them (REQ-0088).
- **The migrations, beyond the shape they build.** `tests/test_migrations.py` runs
  `alembic upgrade head` into a throwaway schema and asserts it matches `Base.metadata`, so
  a model that drifts from `alembic/versions/` no longer passes. What that does not cover:
  `downgrade`, which drops the three tables and has never been run; and what a migration
  does to a database that already holds rows — the check builds an empty schema, so
  locking, backfill and anything a revision does to existing data are unexercised.
- **The Keycloak realm.** Operator authorisation depends on the client scopes that
  `../celine-policies` declares and syncs, and nothing here would notice a rename. No group
  and no realm role takes part (REQ-0090).
- **Read pagination.** `limit`, `cursor` and the filters on the community, member, asset
  and delivery-point listings are used incidentally by other tests and asserted by none.
  `MAX_PAGE_SIZE` is not exercised at all.
- **The exporter, directly.** It is covered only through the round trip (REQ-0037), which
  means its output is verified as *re-importable* and never as *correct*.
- **Concurrency, beyond member uniqueness.** Two writers racing on a member `key` or
  `user_id` are covered (REQ-0022) — constraint, translation and test. No other overlapping
  write is. `asset` carries the same unique index on `(community_id, key)` and nothing
  translates it, so two callers creating one asset key at once still answer `500`; two
  upserting one area key resolve by last-writer-wins. One sensor attached to
  two members at once is covered, serialised by an advisory lock (REQ-0069), and so is a
  member moved into an area while it is deleted, and two areas written onto one substation
  at once, both serialised on the community's row (REQ-0066, REQ-0067). One delivery point
given to two active members at once is covered the way the sensor is, by its own advisory
lock (REQ-0085).

## What is not here

- **Why** a choice was made — [`docs/decisions/`](../decisions/index.md).
- What the system *is* — [`docs/data-model.md`](../data-model.md) and
  [`docs/api-reference.md`](../api-reference.md).
- A trap that is true of the code and not obvious from reading it — the companion's knowledge.
- Anything broken — the issue tracker.
