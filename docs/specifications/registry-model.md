# The registry model

What a community, a member and an asset are — as the bundle schema defines them, because
**the bundle `*In` models are the contract**. Write requests reuse them rather than
declaring parallel shapes, so a member created through the API and one that arrived in a
YAML file are the same object validated by the same code.

The shape itself is described in [the data model](../data-model.md) and
[the bundle format](../import-export.md); this page states the parts a test can hold.

---

### REQ-0011 — a community carries its structure, its identity and its operators

`CommunityIn` accepts an `id`, a `name`, and five optional groups: `areas`, `topology`,
`legal`, `links`, `contact`, `settings` and `operators`.

- **`areas`** is a dict keyed by area key. Each area has a `name` and an optional
  `topology` — a list of node ids that place the area on the grid — plus optional
  `location` and `geometry`.
- **`topology`** is a list of grid nodes, each with an `id`, a `type` (such as
  `primary_substation` or `secondary_substation`), a `name` and an `operator_id`.
- **`operators`** is a dict of distribution network operators the topology refers to.

Areas are the load-bearing part: a member names one, and the incentive calculation the
platform performs depends on which primary-substation area a member sits in.

### REQ-0012 — a member belongs to exactly one community and states its role, area and status

`MemberIn` requires `user_id`, `name`, `role`, `area` and `status`. Members are keyed by
member key in a dict rather than held in a list, so the key is part of the document
structure and cannot be duplicated within a bundle.

`role` is one of `consumer`, `prosumer`, `producer`, `operator`, `admin`; `status` one of
`pending`, `active`, `suspended`, `inactive`.

**`user_id` holds a Keycloak *username*, not a subject UUID** — see REQ-0053, which is
where that becomes visible and costly.

### REQ-0013 — a member declares what kind of thing it is, as a schema.org CURIE

`type` carries `schema:Person`, `schema:GovernmentOrganization`, `schema:LocalBusiness`
or another CURIE, and is stored under `extra.type`.

A REC is not a registry of people alone: a municipality and a shop are members on the same
footing as a household, and downstream consumers distinguish them by this field rather
than by guessing from the name.

### REQ-0014 — assets are nested under their owning member, keyed by type

`assets` is a dict of typed collections — `assets.pv`, `assets.meter`, `assets.storage`,
`assets.ev_charger`, `assets.heat_pump`, `assets.load` — each a dict keyed by asset key.

The type is therefore structural rather than a field, which is what lets each type carry
its own validated properties (REQ-0028) instead of one permissive property bag.

### REQ-0015 — a meter carries the identifiers that connect it to measurements and to the grid

`sensor_id` is the identifier readings arrive under, and is promoted to its own column
because every cross-community lookup starts from it (REQ-0039, REQ-0042). `pod` names the
delivery point the meter sits on, and `meter_type` is `consumption`, `production` or
`bidirectional`.

A meter without a `sensor_id` is not stored — see REQ-0035.

### REQ-0016 — assets declare their relationships to each other

`relationships.measures` lists the asset keys an asset measures; `relationships.paired_with`
names one asset it is paired with.

This is how a PV array is connected to the meter that reads it. Nothing enforces that the
keys resolve, so a relationship naming an absent asset is stored as given.

### REQ-0017 — a member's supply points are part of the member

`delivery_points` is a list of objects carrying `id`, `type`, and optional `description`,
`address`, `tariff` and `active` (defaulting to true).

They live in one JSONB column on the member, which is the reason every write touching them
merges by identity rather than replacing the field (REQ-0027) — and the reason they are
absent from the patch model entirely.

### REQ-0018 — the schema version is read and reported, and never refuses

`schema_version` says which schema under `schemas/community/` a bundle conforms to;
`version` says the format of the envelope around it. They are different questions, and
conflating them is how `1.0` — an envelope version — came to sit in the `schema_version`
slot.

**One place holds the current value.** `core/versions.py` carries `MANIFEST_VERSION`,
`CURRENT_SCHEMA_VERSION` and `KNOWN_SCHEMA_VERSIONS`; `GET /version`, the bundle model's
defaults, the exporter and the importer all read it. They used to hold four literals, which
is how they came to hold three different opinions — a value nobody reads has nothing
holding its copies to each other.

**Import reports, and does not refuse.** A bundle declaring an older published version, an
unpublished one, or none at all is imported, and the caller is told in the `warnings` of
its `ImportReport`. The warning is produced before the `dry_run` return, so a dry run shows
it — that is where a caller looks to find out whether the file is the one they think it is.

This is deliberately **not** a compatibility gate: an incompatible bundle is still accepted
and partially applied. Refusing would break restoring a backup, and a backup is restored
when something has already gone wrong. What changed is that it is no longer silent.

**An export declares the version it emits**, not the version its rows arrived under. An
export is built from today's model, so it conforms to today's schema whatever it was
imported as; stamping the older number on a document written in the newer shape would be a
more convincing lie than the `1.0` it used to carry. A round trip of a current bundle
therefore comes back declaring exactly what it declared going in.

**The published schemas are not enforced.** `schemas/community/v0.4/community.schema.json`
and `v0.5/` are documentation: there is no `jsonschema` dependency and nothing in `src/`
reads them. `CURRENT_SCHEMA_VERSION` is written down rather than derived from that
directory, because `schemas/` does not ship in the Docker image — `tests/test_versions.py`
holds the constant to the directory in the repository instead.

### REQ-0019 — a bundle missing a required field is refused rather than defaulted

A bundle with no `community`, and a member with no `role` or no `area`, raise a validation
error at parse time.

The refusal happens before any database work, so a malformed bundle cannot partially
apply. That property matters more here than in most services because import is
destructive (REQ-0032): a bundle that parsed halfway and then failed would have already
deleted the community it was replacing.
