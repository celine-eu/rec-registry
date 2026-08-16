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

### REQ-0035 — a meter with no sensor id is skipped, with a warning naming it

The import continues and the report carries a warning naming the asset key and the missing
field. Everything else in the bundle is applied.

A meter is identified by its `sensor_id` throughout the platform — it is how a reading
finds its owner (REQ-0039). One stored without it is unreachable rather than merely
incomplete, so it is not stored; and one bad meter is not a reason to refuse a community
of two hundred members, so the import is not failed either.

### REQ-0036 — the report names what was deleted, what was inserted, and what was warned about

Every import answers an `ImportReport` carrying the community key, `deleted` and
`inserted` counts by entity type, and the list of warnings. The YAML route answers a
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
