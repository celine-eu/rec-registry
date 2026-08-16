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

### REQ-0018 — the schema version is carried, never checked, and disagreed about

`version` and `schema_version` are accepted on a bundle, defaulted to `"1.0"` when absent,
and **read by nothing**. A bundle declaring `0.4`, `0.5` or `not-a-version` imports
identically.

Four places hold three opinions about what the current version is:

| Place | Says |
|---|---|
| `GET /version` | `0.4` |
| `recs/rec-example.yaml`, and every document under `docs/` | `0.5` |
| `RegistryBundleIn`'s default | `1.0` |
| what `src/celine/rec_registry/services/exporter.py` emits | `1.0` |

They drifted freely *because* nothing reads the field. One consequence is worth stating
separately: **an export does not preserve the version its import declared** — a `0.5`
bundle exports as `1.0` — so an export is not a faithful backup in the one field whose job
is to describe the shape of the rest.

This is a defect — [#38](https://github.com/celine-eu/rec-registry/issues/38) — and it is
stated here as behaviour rather than as the intended version gate, because the gate does
not exist and a requirement describing it would report coverage for something nobody
verified. Fixing it means changing the code, this requirement and its tests together.

### REQ-0019 — a bundle missing a required field is refused rather than defaulted

A bundle with no `community`, and a member with no `role` or no `area`, raise a validation
error at parse time.

The refusal happens before any database work, so a malformed bundle cannot partially
apply. That property matters more here than in most services because import is
destructive (REQ-0032): a bundle that parsed halfway and then failed would have already
deleted the community it was replacing.
