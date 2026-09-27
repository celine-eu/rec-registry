# Import and export

The other way a community arrives: a YAML or JSON bundle, imported wholesale. This is how
a community is seeded and how it is restored from a backup, and it is **the only place in
the service where a write may delete what it was not given**.

The procedure and the file format are in [import & export](../import-export.md). What
follows is what the behaviour must be.

---

### REQ-0032 — an import is a full replace, and it is atomic

Importing a community deletes the existing community with every member and asset, then
recreates the whole graph from the bundle. Entities missing from the new bundle are gone;
changed ones are recreated; new ones are added.

The work is one transaction: if any step fails, nothing is applied. That is not a
convenience — a half-applied replacement is a community whose members have been deleted
and not recreated, and there is no state to roll back *to* except the transaction.

Rows are built by `src/celine/rec_registry/services/members.py`, **the same code the admin
write API uses**. Two implementations of "what a member row looks like" would drift on the
first schema change; REQ-0037 is what would notice.

### REQ-0033 — overwriting an existing community must be asked for

An import naming a community that already exists is **refused** unless `force` is set:
`409` over HTTP, and a non-zero exit from the CLI, in both cases **naming the members and
assets that would have been deleted**.

With `force`, the replacement proceeds and the loss is accepted. Creating a community that
does not exist yet needs no `force`.

This guard exists because the premise changed. Full replacement was safe while a YAML file
was the only source of members; now that members arrive at runtime through the write API,
**restoring a stale export is the likeliest way to lose weeks of approvals**. The counts
in the refusal are the point — they are how a caller judges whether forcing is warranted.

### REQ-0034 — a dry run reports and never writes, and is never blocked by the guard

`dry_run` returns the same report — what would be deleted, what would be inserted, with
what warnings — and performs no database work at all: nothing is added and nothing is
deleted.

A dry run against an existing community **reports instead of refusing**, even without
`force`. Seeing the counts is exactly how a caller decides whether forcing is warranted,
so the guard must not block the request that informs it.

It also lists, in the report's `refusals`, every `sensor_held` refusal the import would make
(REQ-0069), and every `invalid_role`, `invalid_status` and `unknown_area` refusal (REQ-0066,
REQ-0074). **Planned:** the area-boundary refusal too (REQ-0067).

### REQ-0035 — a meter with no sensor id is skipped, with a warning naming it

The import continues and the report carries a warning naming the asset key and the missing
field. Everything else in the bundle is applied.

A meter is identified by its `sensor_id` throughout the platform — it is how a reading
finds its owner (REQ-0039). One stored without it is unreachable rather than merely
incomplete, so it is not stored; and one bad meter is not a reason to refuse a community
of two hundred members, so the import is not failed either.

A `sensor_id` that is blank after trimming counts as missing and is skipped the same way
(REQ-0069).

### REQ-0036 — the report names what was deleted, what was inserted, and what was warned about

Every import answers an `ImportReport` carrying the community key, `deleted` and
`inserted` counts by entity type, the list of warnings, and — filled by a dry run only — the
`refusals` the import would make, each `{code, detail}` (REQ-0069). The YAML route answers a
`MultiImportReport`, one entry per document.

A malformed request — no `bundle` field, or a body that is not JSON — is `422` before any
of that.

The counts are what makes a destructive operation reviewable after the fact. `deleted`
being non-zero is the caller's evidence that a replacement rather than a creation
happened.

### REQ-0037 — a community exports the same whether its members arrived by API or by bundle

Create a member through the write API, export the community, re-import the export: the
member is still there, unchanged, with its delivery points and its assets.

This is the property the two write paths exist to preserve, and the one that is invisible
from reading either path alone. If it breaks, the symptom is **a community that exports
differently depending on how its members arrived** — which nobody notices until a restore
produces something subtly unlike the original, and by then the original is gone.

Practically: the file is a **seed**, `GET /admin/export` is a **backup**, and once members
arrive at runtime the database is the source of truth.

One field is knowingly excluded from this guarantee: the declared schema version does not
survive the round trip (REQ-0018).

**Planned:** the source of truth becomes per collection — areas come from onboarding
templates ([ADR-0006](../decisions/ADR-0006-onboarding-templates-are-the-source-of-truth-for-areas.md)),
members through onboarding, meters from a manager — and the database holds all three. The round
trip keeps holding for a community exported after schema v0.7; an export taken before it has
areas without a boundary, which REQ-0074 refuses, so it has to be reshaped before it restores.

### REQ-0074 — an import that breaks an invariant is refused whole, before any database work

**Status:** planned

A bundle is refused, and nothing is deleted or inserted, when:

- two of its active members hold the same trimmed sensor id, or one of them holds a sensor an
  active member of **another** community holds (REQ-0069) — the replaced community's own
  current rows do not count, since the import deletes them;
- an asset key is longer than the 128 characters `asset.key` holds — `asset_key_too_long`
  (REQ-0028), implemented with the sensor clause;
- a member's `role` or `status` is outside its set, or its `area` is not one of the bundle's
  areas (REQ-0066);
- an area breaks the one-substation rule (REQ-0067).

The refusal is `422` over HTTP and a non-zero exit from the CLI, with the code of the invariant
(REQ-0073) and a report naming the offending member, asset and area keys of **this** bundle; a
sensor held in another community is reported without naming that community or member. The
check runs after parsing (REQ-0019), and a dry run answers the report with every refusal it
would make rather than stopping at the first (REQ-0034).

The schema-version check stays the warning REQ-0018 describes; this refuses on content,
whatever version is declared. A bundle written before schema v0.7 that has areas is refused,
and there is no compatibility branch: a file is reshaped outside the product. The runtime
writes already refuse these rows, and an import that only warned would be the way to create
them anyway. Decided in
[ADR-0007](../decisions/ADR-0007-import-refuses-a-bundle-that-breaks-an-invariant.md).

The first three bullets are enforced, with this refusal's shape: the sensor clause as
REQ-0069 describes, the asset-key length with it, and the role, status and area clause as
REQ-0066 describes — each out-of-set field one refusal, `member '<key>': role 'x' is not one
of …`, and the area judged against the bundle's own `community.areas`. The last lands with
REQ-0067, and this requirement stays planned until it does.

### REQ-0075 — a community is retired by a forced import naming it with no members

**Status:** planned

A forced import of a bundle that names an existing community and carries no members deletes
every member and asset of that community and keeps the community, with the metadata the bundle
carries. The report counts what was deleted, as REQ-0036 says. Every sensor the old members
held is released, so a sensor can be attached in another community afterwards without
`sensor_held`.

There is no community delete route and no retired status: retirement is this import, performed
by an operator holding the import grant — the grant that is purge-equivalent for a whole
community (REQ-0006). On a deployed realm a bundle carries a community's administrative data
only, and members arrive through onboarding; members loaded from a file are for local
development. Decided in
[ADR-0009](../decisions/ADR-0009-a-community-is-retired-by-a-forced-empty-import.md).
