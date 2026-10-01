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

- **`areas`** is a dict keyed by area key. Each area has a `name`, a `boundary` — the
  primary-substation boundary it is, `{source, id}` — and a `topology` listing that
  substation's node id, plus optional `location` and `geometry`, accepted and unused.
- **`topology`** is a list of grid nodes, each with an `id`, a `type` (such as
  `primary_substation` or `secondary_substation`), a `name` and an `operator_id`.
- **`operators`** is a dict of distribution network operators the topology refers to.

Areas are the load-bearing part: a member names one, and the incentive calculation the
platform performs depends on which primary-substation area a member sits in.

An area is held to that reading on the writes that can change it: one boundary, one
`primary_substation` node with the boundary's id, no two areas on one substation (REQ-0067),
published as schema v0.7 (REQ-0068).

### REQ-0012 — a member belongs to exactly one community and states its role, area and status

`MemberIn` requires `user_id`, `name`, `role`, `area` and `status`. Members are keyed by
member key in a dict rather than held in a list, so the key is part of the document
structure and cannot be duplicated within a bundle.

`role` is one of `consumer`, `prosumer`, `producer`, `operator`, `admin`, `status` one of
`pending`, `active`, `suspended`, `inactive`, and `area` a key of the community's `areas` —
held on every write path, the bundle import among them (REQ-0066). The models type the three
as plain strings on purpose, so that a value outside its set is refused with a code rather
than as a validation error (REQ-0073).

**`user_id` holds a Keycloak *username*, not a subject UUID** — see REQ-0053, which is
where that becomes visible and costly.

A member carries three identifiers and each answers a different question: `key` is what
this community calls them, `user_id` is who they authenticate as, and `did` (REQ-0059) is
who they are in the dataspace. Two of the three are wrong for any given use, which is why
they are documented together at the column.

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

The column carries a lookup index, not a uniqueness constraint: at most one **active** holder
per trimmed sensor id across the registry is kept by the writes (REQ-0069), and new writes
store the id trimmed. Rows written before that are kept as they were.

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
absent from the patch model entirely. An active member holds each of its points alone
(REQ-0085).

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

A bundle holding one sensor on two active members is refused whatever version it declares
(REQ-0069), and so is one whose members break REQ-0066 or whose areas break REQ-0067
(REQ-0074) — so a backup written before schema v0.7 that has areas has to be reshaped before
it restores. A v0.6 bundle whose areas keep REQ-0067 imports, with the version warning.

**An export declares the version it emits**, not the version its rows arrived under. An
export is built from today's model, so it conforms to today's schema whatever it was
imported as; stamping the older number on a document written in the newer shape would be a
more convincing lie than the `1.0` it used to carry. A round trip of a current bundle
therefore comes back declaring exactly what it declared going in.

**The published schemas are not enforced.** `schemas/community/v0.4/`, `v0.5/`, `v0.6/` and
`v0.7/community.schema.json` are documentation: there is no `jsonschema` dependency and nothing in `src/`
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

A member whose `area` is not a key of the bundle's `community.areas`, or whose `role` or
`status` is outside its set, is refused before any database work too — by the import's
invariant check rather than at parse time, so that the refusal carries its code (REQ-0066,
REQ-0074). A bundle carrying members carries their areas.

### REQ-0059 — a member may hold one dataspace DID, and no two members hold the same one

`did` is optional on `MemberIn` and stored in its **own column** beside `user_id`, not
under `extra`. It is the identifier the member is known by in the dataspace, and the join
key between the connector's answer to *who consents* — which is stated in DIDs — and this
registry's answer to *what they hold*.

Its own column because it is a join key, resolved by an `IN` over a set of DIDs on every
consent-gated export. Burying an identifier in JSONB makes it look like a declaration, and
`MemberIn` is `extra="allow"`, so a `did` the row-building code did not know about would
validate, import, and land in `extra` while the column stayed `NULL` — one member holding
two records of its DID that disagree.

**Optional.** The DID is minted a step *after* the member is registered — `../onboarding`
registers at `rec_registry_member` and mints the identity at `dataspace_identity` — and a
deployment with no dataspace never populates it at all. A bundle written before this field
existed still parses, and exports omit the field entirely rather than writing `did: null`.

**Unique registry-wide, not per community**, unlike `key` and `user_id`. `ix_member_did` is
a unique index on `did` alone, and because Postgres treats NULLs as distinct it permits any
number of members holding none while refusing a second holder of one.

The global scope rests on a domain assumption, stated here as one: a person cannot be a
member of two RECs, because the same supply point settled twice is double billing. If
multi-REC membership ever arrives, this constraint is the first thing that has to be
revisited.

**Both write paths carry it.** A member created through the admin API and one that arrived
in a YAML bundle hold the DID in the same column, and a community exports the same either
way — the property REQ-0037 pins.

It is published as **schema v0.6**, which adds this field and changes nothing else — so a
v0.5 file is a valid v0.6 one. Like every schema under `schemas/community/`, that document
is documentation and is not enforced (REQ-0018).

### REQ-0066 — role and status are closed sets on every write path, and a member's area is one of its community's

`role` must be one of `consumer`, `prosumer`, `producer`, `operator`, `admin`, and `status` one
of `pending`, `active`, `suspended`, `inactive` — on creating a member, on both member
`PATCH` routes — the general one, which keeps accepting `role` and `area` for
`members.write` holders (REQ-0024), and the profile route (REQ-0070) — on the role and area
`PUT` routes (REQ-0083), on the status route,
and in a bundle. `area` must be a key of the community's `areas` — in a bundle, of the
bundle's own `community.areas`, since the import replaces the community. A value outside the
set answers `422` with the code of REQ-0073 — `invalid_role`, `invalid_status` or
`unknown_area` — naming the value and the valid ones, and changes nothing; in a bundle it
refuses the import (REQ-0074). The comparison is exact: no case folding, no trimming. A
`PATCH` checks only the fields it names, so a member stored before the check can still be
renamed. A role change leaves the member's assets as they are.

A member write naming an area and an area delete (REQ-0030) are serialised on the
community's row: the write holds it shared from its check to its commit, the delete takes it
exclusively before counting the members that reference the area. Without that, each could
pass against the other's uncommitted half and leave a member in an area that does not exist.

These are the sets the published JSON Schemas (v0.4–v0.7) and the platform ontology already
declare, held to the schema by a test; the registry was the last place still accepting
anything. A manager correcting a member's role and area is the reason they matter now: the
role decides whether a meter's production counts, and the area decides its substation. The
report of rows already outside the sets is `out-of-set-values` (REQ-0077). Decided in
[ADR-0003](../decisions/ADR-0003-role-and-area-have-their-own-route-and-action.md) and
[ADR-0007](../decisions/ADR-0007-import-refuses-a-bundle-that-breaks-an-invariant.md).

### REQ-0067 — an area is one GSE primary substation: one boundary, one node, the same id

Every area carries `boundary: {source, id}`, where `source` is `gse_cabine_primarie` and `id`
is the substation code (`cod_ac`), and its `topology` lists **exactly one** node id — a node of
the community's `topology` whose `type` is `primary_substation` and whose `id` equals
`boundary.id`; the community's `topology` holds exactly one node with that id. No two areas of
one community carry the same `boundary.id`, including when two writers race.

A write that would break this answers `422` with the code `invalid_area_boundary` (REQ-0073)
and changes nothing: the area `PUT`, the topology node `PUT` (REQ-0072) and the bundle import
(REQ-0074). Each refusal names the
area keys and the rule, not the boundary or node id. What is refused:

- no boundary, a `null` one, a list of boundaries, or one that is not exactly `{source, id}` of
  strings — refused with the code, not as FastAPI's validation body, so that a caller branches
  on `code` alone;
- a `source` other than `gse_cabine_primarie`, an `id` blank after trimming, or an `id` longer
  than 64 characters (the bundle schema and `AreaBoundaryIn` publish `maxLength: 64`; a longer
  one is still refused with the code, not as a validation body);
- a `topology` of zero or several node ids, or one that is not `boundary.id` — compared
  exactly, no case folding or trimming;
- a node the community's `topology` does not hold, holds twice, or holds with another `type`;
- a `boundary.id` another area of the community already carries.

**The node is written before the area that references it.** An area `PUT` naming a node the
community's `topology` does not hold is refused; the node arrives through the topology node
routes (REQ-0072) or a bundle import. A node `PUT` never breaks an area that keeps this rule —
changing the `type` of its node away from `primary_substation` is refused — and a node an area
references cannot be deleted (`409 topology_node_in_use`). The community `PATCH` is not an enforcement point because it never touches
areas or topology (REQ-0029).

**The area `PUT` judges the area it writes.** Areas stored before this rule are not re-judged
by a write to a sibling, and are read back as stored — an area with no valid boundary answers
`boundary: null` — except that the written area may not carry a boundary id one of them
already carries. The import judges every area of the bundle. **Two writers** putting two areas
onto one substation at once are serialised on the community's row, which the area `PUT` takes
exclusively before reading the siblings; one succeeds and the other is refused.
An area rename (REQ-0079) moves an area to a new key as stored, without re-judging it, and
never changes the set of boundary ids, so it cannot put two areas on one substation.

**An area's key is an area key**: letters, digits, `-` and `_`, starting with a letter or
digit, at most 128 characters — what `member.area` holds, and the rule onboarding's template
import holds a template's area keys to. Every write that stores a key holds it to this: the
area `PUT`, judged on its `area_key` after the community is found and before the body, the
rename's `new_key` (REQ-0079) and the bundle import (REQ-0074), each refusing `422` with the
code `invalid_area_key` and changing nothing. On an import the refusal names the key, one per
key; a member naming such an area is not refused `unknown_area` for it. An area stored under
another key before this rule is read back as stored, is not re-judged by a write to a sibling,
cannot be replaced by a `PUT` under its key, and is moved onto a key that keeps the rule by a
rename, whose `area_key` may be any stored key. The stored-areas report (REQ-0078) lists such
keys.

The area `PUT` stores `boundary` and `topology` and returns them, as every read of a community
does (`Area.boundary`, `Area.topology`). `geometry` and `location` stay accepted and unused;
other keys of the `PUT` body are dropped, as before. The registry does not check `boundary.id`
against the GSE dataset, which it cannot read.

The pipelines already take an area's first node as its members' primary substation; this
makes it the only one, so the reading is right rather than lucky. Decided in
[ADR-0005](../decisions/ADR-0005-an-area-is-one-gse-primary-substation.md).

### REQ-0068 — the bundle schema is published as v0.7

`schemas/community/v0.7/community.schema.json` adds `Area.boundary` — required, `{source, id}`,
`source` one of `gse_cabine_primarie`, no other key — and makes `Area.topology` required with
exactly one item, makes `community.areas` optional and allows it empty — so an
administrative-only bundle (the community's own data, no areas) validates, as the importer
already accepted it — and changes nothing else. The equality of the topology item with `boundary.id`, the
node's type and uniqueness across areas are not expressible in JSON Schema; REQ-0067 enforces
them. `CURRENT_SCHEMA_VERSION` is `0.7`, `KNOWN_SCHEMA_VERSIONS` gains it, and so do `/version`,
an export's `schema_version` and the bundle schema named in the OpenAPI description. The
package version is 1.6.0, the one this delivery moved to from the last release (1.5.0), so the
SDK's snapshot of this API named after `info.version` (REQ-0058) is a new one rather than an
overwrite of a released one.

A file with no areas (`areas` absent or `{}`) is a valid v0.7 one, and the import accepts it
whatever version it declares; a v0.6 file with areas is not, since none of
its areas carries a boundary — the import refuses it on content whatever it declares, and
imports a v0.6 file whose areas keep REQ-0067 with the version warning (REQ-0018, REQ-0074).
Like every published schema it is documentation, not enforced (REQ-0018). Decided in
[ADR-0005](../decisions/ADR-0005-an-area-is-one-gse-primary-substation.md).

### REQ-0069 — a sensor id has at most one active holder across the whole registry

No two members whose status is `active` hold a meter with the same sensor id, in one community
or in two. The comparison is on the **trimmed** id, and new writes store it trimmed; an id
that is blank after trimming is missing (REQ-0035). **Trimmed has one definition**: every
character Python's `str.isspace()` accepts — tab, newline, no-break space and the other
Unicode spaces as well as the ASCII space — stripped from both ends, spelled out once
(`core/sensor_id.py`) and used alike by the writes, by the SQL comparing rows already stored
(`btrim` with that character set, not its one-argument form, which strips only the space) and
by the duplicates report (REQ-0076). A member whose status is not `active`
holds nothing, so deactivating a member releases its sensors (REQ-0026).

Checked on every path that can make an active member hold a sensor: the asset `PUT` (REQ-0028,
REQ-0071), creating a member with assets (REQ-0020), a status change to `active` through the
status route or `PATCH` (REQ-0024, REQ-0025), and the bundle import (REQ-0074). A clash answers
`409` with the code **`sensor_held`** (REQ-0073). **Reactivation re-checks:** a member whose
sensor was taken by another active member while it was not `active` is refused `sensor_held`
on the status change, and its status is left unchanged.

**Check and write run under one transaction-scoped advisory lock keyed on the trimmed id**, so
two writers attaching one sensor to two members at once get one success and one `sensor_held`.

**A write that can make a member hold a sensor locks that member's row first** (`SELECT … FOR
UPDATE`), and reads its status and sensor ids after the lock: the asset `PUT` and every move
to `active`. An attach to a member who is not active is not checked, and a reactivation
checks the sensors the member holds — so, without the row lock, an attach to a suspended
member running at the same moment as its reactivation would each miss the other's
uncommitted half and leave two active holders. With it, whichever runs second sees the
first's result and checks. The import locks the replaced community's member rows before its
advisory locks, the same order, so no two writers wait on each other in a cycle.

**The answer names nobody outside the community addressed.** A holder inside it may be named
by member key, as the DID clash names its holder (REQ-0060); a holder in any other community is
not named, and neither is its community — which member of which other community holds a
sensor is the enumeration disclosure REQ-0045 refuses.

On the import the refusal is `422` `sensor_held` — the bundle is what is wrong — naming this
bundle's member and asset keys, before anything is deleted; a dry run lists it in the report's
`refusals` and answers `200`. The replaced community's own current rows do not count, since the
import deletes them. The comparison with rows already stored is trimmed too, so an untrimmed id
written earlier — with spaces, a tab, a newline or a no-break space around it — still counts. A member already `active` is not re-checked by a patch that
leaves it active.

**Existing duplicates are not repaired, and do not block unrelated writes.** The check refuses
the next write, not the past ones; `celine-rec-registry duplicate-sensors` lists them
(REQ-0076).

Two holders double-count every reading of the sensor in every consumer that joins readings to
members, and nothing downstream can tell. Decided in
[ADR-0004](../decisions/ADR-0004-a-sensor-has-one-active-holder-and-detaching-deletes-the-meter.md).

### REQ-0085 — a delivery point has at most one active holder across the whole registry

No two members whose status is `active` list a delivery point with the same id, in one
community or in two. The comparison is on the id **trimmed and lower-cased**: trimmed by the
one character set REQ-0069 defines (`core/sensor_id.py`), in Python and in the SQL that
compares rows already stored alike, and lower-cased by Python's `str.lower` and Postgres
`lower`. The id is stored as the caller spelled it. A member whose status is not `active`
holds nothing, so deactivating a member releases its points; a point's own `active` flag is
not read — an active member holds every point it lists.

Checked on every path that can make an active member hold a point: the delivery-point `PUT`,
with or without `replaces` (REQ-0027, REQ-0084); creating a member with delivery points
(REQ-0020); a status change to `active` through the status route or `PATCH` (REQ-0024,
REQ-0025); and the bundle import (REQ-0074). A clash answers `409` with the code
**`delivery_point_held`** (REQ-0073), in the body `sensor_held` uses, and changes nothing;
reactivation leaves the status as it was. A `PUT` to a member who is not active is not
checked — its reactivation is. Re-sending a member's own point is not a clash.

**Check and write run under one transaction-scoped advisory lock keyed on the compared id**
(a namespace of its own, apart from the sensors'), after the member's row lock and after any
sensor locks the same write takes: community row, member rows, sensor locks, delivery-point
locks — the order every write takes them in. Two writers giving one point to two active
members at once get one success and one `delivery_point_held`.

**The answer names nobody outside the community addressed**, as REQ-0069's: a holder inside
it may be named by member key, a holder in another community is named neither by member nor
by community. On the import the refusal is `422` `delivery_point_held`, naming this bundle's
member keys and never the point's id; the replaced community's own rows do not count; a dry
run lists it in `refusals`.

**Existing duplicates are not repaired, and do not block unrelated writes.** The check
refuses the next write that would make one, not the past ones; a duplicate already stored
blocks re-sending either holder's point, reactivating either holder, and re-importing either
community, until it is resolved. `celine-rec-registry duplicate-delivery-points` lists them
(REQ-0086), and `GET …/communities/{ck}/delivery-points/duplicates` lists one community's
(REQ-0087).

A mistyped POD that happens to be somebody else's is the case this catches: two holders would
attribute one supply to two people in every consumer that joins supply to members. Decided
in [ADR-0012](../decisions/ADR-0012-a-delivery-point-has-one-active-holder-and-is-corrected-in-one-write.md).
