# API Reference

## Authorization

`/admin` routes need a JWT and an OPA decision. The action is derived from the
path **and** the HTTP method, so reads and writes are separate grants. Only the
route's fixed segments are read, each at its position: a member key, asset key or
any other id containing `lookup`, `import`, `export`, `profile`, `name`, `role`, `area` or
`delivery-points` never changes the action, nor does the body or the query,
and a path matching no route derives `admin`, which only `rec-registry.admin`
satisfies (REQ-0065).

| Action | Reached by | Scope |
|---|---|---|
| `read` | any `GET` under `/admin` | `rec-registry.read` |
| `members.write` | create, the general `PATCH`, `…/status` and `DELETE` on `…/members…` | `rec-registry.members.write` |
| `members.profile.write` | `PATCH …/members/{key}/profile` (role and area only) | `rec-registry.members.profile.write`, or `rec-registry.members.write` |
| `members.name.write` | `PUT …/members/{key}/name` | `rec-registry.members.name.write`, or `rec-registry.members.write` |
| `members.role.write` | `PUT …/members/{key}/role` | `rec-registry.members.role.write`, `rec-registry.members.profile.write`, or `rec-registry.members.write` |
| `members.area.write` | `PUT …/members/{key}/area` | `rec-registry.members.area.write`, `rec-registry.members.profile.write`, or `rec-registry.members.write` |
| `members.delivery_points.write` | `PUT` and `DELETE …/members/{key}/delivery-points/{id}`, `?replaces=` included | `rec-registry.members.delivery_points.write`, or `rec-registry.members.write` |
| `members.purge` | `DELETE …/members/{key}?purge=true` | `rec-registry.members.purge` |
| `assets.write` | write methods on `…/assets…` | `rec-registry.assets.write` |
| `community.write` | write methods on a community, its areas (the area rename included) or its topology nodes | `rec-registry.community.write` |
| `import` / `export` | `/admin/import*`, `/admin/export` | `rec-registry.import` / `.export` |
| `lookup` | `/admin/lookup/*` | `rec-registry.lookup` |
| `assets.lookup` | `/admin/lookup/assets-by-user-ids`, `/admin/lookup/members-by-dids` | `rec-registry.lookup` |

`rec-registry.admin` satisfies all of them (the shared matcher treats
`{service}.admin` as covering `{service}.*`), so existing tokens keep working —
but **do not give it to a service account**. Grant the actions it calls: a
service that registers approved participants needs `members.write`, one that
attaches meters needs `assets.write`, one that corrects a member's area needs
`members.area.write` — which reaches that one route and nothing else (ADR-0011) — and none
has any business importing, exporting or purging. A member field is granted alone; identity
(`user_id`, `did`, status, creating a member) is `members.write` only.

Interactive OpenAPI docs are available at `http://localhost:8004/docs` under `CELINE_ENV=dev`,
or with `CELINE_PUBLIC_DOCS=true` (REQ-0092).

## Refusal codes

A refusal a caller is expected to act on answers

```json
{"detail": "This sensor is already held by another active member", "code": "sensor_held"}
```

`detail` is a sentence for people and stays a string; branch on `code`, never on
the wording (REQ-0073). The OpenAPI document names the body `ErrorResponse` and the
codes `ErrorCode`.

| Code | Status | Refusal |
|---|---|---|
| `community_not_found` | `404` | a write naming an unknown community |
| `member_not_found` | `404` | a write naming a member the community does not have |
| `asset_not_found` | `404` | deleting an asset the member does not hold |
| `member_key_taken` | `409` | the member key is taken in the community |
| `user_id_taken` | `409` | the `user_id` is taken in the community |
| `did_taken` | `409` | the DID is held by another active member anywhere (REQ-0096) |
| `asset_key_taken` | `409` | the asset key is held by another member of the community |
| `asset_key_too_long` | `422` | the asset key is longer than 128 characters (asset `PUT`, member create, import) |
| `sensor_held` | `409` (`422` on an import) | another active member, in any community, holds the sensor |
| `area_in_use` | `409` | deleting an area members still reference |
| `invalid_status` | `422` | a status outside `pending`, `active`, `suspended`, `inactive` (every member write, import) |
| `invalid_role` | `422` | a role outside `consumer`, `prosumer`, `producer`, `operator`, `admin` (every member write, import) |
| `unknown_area` | `422` | an area that is not a key of the community's `areas` (every member write; on an import, the bundle's own areas) |
| `invalid_area_boundary` | `422` | an area that is not one primary substation: one boundary, one `primary_substation` node with its id, no two areas on one boundary id (area `PUT`, topology node `PUT`, import) |
| `topology_node_in_use` | `409` | deleting a topology node an area still references, or another node names as its `parent` |
| `area_not_found` | `404` | renaming an area the community does not have |
| `area_key_taken` | `409` | renaming an area onto a key the community already has |
| `invalid_area_key` | `422` | an area key that is not letters, digits, `-` and `_`, starting with a letter or digit, at most 128 characters (area `PUT`, rename's `new_key`, import) |
| `not_a_member` | `403` | a `/user` route other than `GET /user`, for a caller whose username names no active member |
| `ambiguous_member` | `409` | a `/user` route, for a caller active in more than one community whose token's organizations do not narrow it to one; a lookup that more than one active member would answer (REQ-0097 – REQ-0099) |
| `delivery_point_held` | `409` (`422` on an import) | another active member, in any community, holds the delivery point (trimmed, case-insensitive) — as a point, or as a meter's `pod` (REQ-0093) |
| `delivery_point_linked` | `409` | deleting a delivery point one of the member's meters still names as its `pod` |

Other refusals — FastAPI's validation errors, a body id or key that does not match
the path, the import's `force` guard, a `404` for an unknown delivery point (on its
`DELETE`, or as the `replaces` of a correction), topology node, or area on its `DELETE` — keep the plain `{"detail": ...}` body. A route
that answers a coded `422` documents its `422` as `oneOf` `ErrorResponse` and
`HTTPValidationError` (whose `detail` is a list): both arrive with that status.

## The access log

A meter's asset key is `meter-<sensor_id>`, three routes take a sensor id in
the path, three a user id and three a delivery-point id, so the access line uvicorn writes
is rewritten before it is logged (REQ-0080): method, route shape and status stay, the
identifiers do not.

| Request | Logged as |
|---|---|
| `PUT /admin/communities/example-rec/members/ex-00001/assets/meter-SEN-1` | `PUT /admin/communities/example-rec/members/ex-00001/assets/{asset_key}` |
| `GET /admin/lookup/asset-by-sensor-id/SEN-1` | `GET /admin/lookup/asset-by-sensor-id/{sensor_id}` |
| `GET /admin/lookup/member-by-user-id/user-1` | `GET /admin/lookup/member-by-user-id/{user_id}` |
| `GET /admin/lookup/community-by-delivery-point/DP-1` | `GET /admin/lookup/community-by-delivery-point/{dp_id}` |
| `GET /admin/communities/example-rec/meters?limit=50&cursor=meter-SEN-1` | `GET /admin/communities/example-rec/meters?limit=50&cursor={redacted}` |

Every asset key is replaced, on every `/assets/{asset_key}` route; so is everything after
`by-sensor-id/`, `by-user-id/`, `/delivery-points/by-id/` and
`community-by-delivery-point/`, the delivery-point id on the member delivery-point `PUT`
and `DELETE`, the `cursor` of the asset, meter and delivery-point listings, and any
`sensor_id(s)`, `user_id(s)`, `dp_id(s)` or `delivery_point_id(s)` query value. The markers
are fixed rather than a hash of the id. Only uvicorn's own line is covered: a proxy in front
of the service that logs the URL logs the identifiers.

---

## User Routes

Self-service endpoints scoped to the authenticated user's membership. Prefix: `/user`.

Only an **active** member answers (REQ-0094): a `pending`, `suspended` or `inactive` row
counts as no row. A caller whose username names no active member gets `GET /user` with
`membership: null`; every other route answers `403` with
`{"detail": "You are not a member of any community", "code": "not_a_member"}`
(REQ-0047). Branch on the code, not the sentence. A caller active in more than one
community is answered from the one their token's `organization` aliases name; when those
do not name exactly one, every route answers `409 ambiguous_member` (REQ-0095).

### `GET /user`

Profile summary: user info, community membership, asset counts by type.

### `GET /user/member`

Own member detail (key, name, role, area, status, delivery points).

### `GET /user/community`

Detail of the community the user belongs to.

### `GET /user/assets`

List own assets.

**Query params:**
- `asset_type` — filter by asset type (`pv`, `meter`, `storage`, `ev_charger`, `heat_pump`, `load`)

### `GET /user/assets/{asset_key}`

Detail of a specific owned asset.

### `GET /user/delivery-points`

List own delivery points.

---

## Admin Routes — Communities

Community browsing and detail endpoints. Prefix: `/admin`.

### `GET /admin/communities`

Paginated list of communities.

**Query params:**
- `key` — filter by community key
- `limit` — page size (default 50, max 500)
- `cursor` — pagination cursor

### `GET /admin/communities/{community_key}`

Community detail including areas, topology, legal, contact, settings.

### `GET /admin/communities/{community_key}/topology`

Grid topology nodes for a community, each `{id, type, name, operator_id, parent,
area}` — the bundle's names. (Before 1.6.0 reads answered `operator`, always
`null`, and never the stored `operator_id`.)

### `GET /admin/communities/{community_key}/members`

Paginated list of members.

**Query params:**
- `role` — filter by role (`consumer`, `prosumer`, `producer`, `operator`, `admin`)
- `status` — filter by status (`pending`, `active`, `suspended`, `inactive`)
- `area` — filter by area key
- `limit`, `cursor` — pagination

### `GET /admin/communities/{community_key}/members/{member_key}`

Member detail.

### `GET /admin/communities/{community_key}/members/by-user-id/{user_id}`

Lookup member by user ID within a community.

### `GET /admin/communities/{community_key}/members/{member_key}/delivery-points`

Delivery points for a specific member.

### `GET /admin/communities/{community_key}/delivery-points`

Paginated list of all delivery points in a community.

**Query params:**
- `type` — filter by delivery point type
- `active` — filter by active status
- `limit`, `cursor` — pagination

### `GET /admin/communities/{community_key}/delivery-points/duplicates`

The community's delivery points that more than one **active** member holds — the
per-community view of `celine-rec-registry duplicate-delivery-points`, for an operator console.
A read (`rec-registry.read`). Not paginated.

```json
{
  "community_key": "example-rec",
  "items": [
    {
      "delivery_point": "it001e00000001",
      "holders": [
        {"member_key": "ex-00001", "id": "IT001E00000001"},
        {"member_key": "ex-00002", "id": "it001e00000001"}
      ],
      "held_elsewhere": 1,
      "active_holders": 3
    }
  ]
}
```

`delivery_point` is the compared form (trimmed, lower-cased); `holders` are this community's
active holders with the spelling each stored; `held_elsewhere` counts active holders in other
communities, which are never named, nor their communities. A point shared only between other
communities is not listed. Unknown community: `404`.

### `GET /admin/communities/{community_key}/delivery-points/by-id/{dp_id}`

Lookup a specific delivery point by its ID.

### `GET /admin/communities/{community_key}/assets`

Paginated list of community assets.

**Query params:**
- `asset_type` — filter by type
- `owner` — filter by member key
- `limit`, `cursor` — pagination

### `GET /admin/communities/{community_key}/assets/{asset_key}`

Asset detail.

### `GET /admin/communities/{community_key}/assets/by-sensor-id/{sensor_id}`

Lookup asset by sensor ID within a community.

### `GET /admin/communities/{community_key}/meters`

Convenience endpoint listing meter-type assets with POD and meter type info.

**Query params:**
- `owner` — filter by member key
- `limit`, `cursor` — pagination

---

## Admin Routes — Lookup

Cross-community lookups. Prefix: `/admin/lookup`.

Every lookup below except `members-by-dids` answers from **active** members only
(REQ-0097 – REQ-0099): a released (`inactive`), `pending` or `suspended` member is not
found, the same as an unknown id, and contributes no rows to a batch. Where more than one
active member would answer a single lookup, it is `409 ambiguous_member`, naming nobody,
rather than whichever row came first.

### `GET /admin/lookup/community-by-user-id/{user_id}`

Find which community a user belongs to.

### `GET /admin/lookup/community-by-sensor-id/{sensor_id}`

Find which community owns a given sensor.

### `GET /admin/lookup/community-by-delivery-point/{dp_id}`

Find which community a delivery point belongs to.

### `GET /admin/lookup/member-by-user-id/{user_id}`

Lookup member details by user ID across communities.

### `GET /admin/lookup/asset-by-sensor-id/{sensor_id}`

Lookup asset details by sensor ID across communities.

### `POST /admin/lookup/assets-by-sensor-ids`

Batch lookup: resolve multiple sensor IDs to assets in a single request.

**Request body:** `{sensor_ids: [...]}`, at most 500.

### `POST /admin/lookup/assets-by-user-ids`

Batch lookup: resolve the assets owned by a set of members, across communities.
Every row carries `owner_user_id`, so the caller can attribute it back to the
member it asked about. A user id that is an active member of more than one
community refuses the whole batch with `409 ambiguous_member` (REQ-0097).

**Request body:** `{user_ids: [...]}`, at most 500.

### `POST /admin/lookup/members-by-dids`

Batch lookup: resolve the members holding a set of dataspace DIDs, across
communities. Every row carries its `did`, plus the member's `user_id`, delivery
points and community.

**Members, not assets** — deliberately. A participant is registered with a
declared supply point and no asset at all, because a meter's `sensor_id` is
assigned at physical installation. An asset-shaped answer would be empty for
everyone whose meter is not commissioned yet; a commissioned meter stays
reachable through `assets-by-user-ids` and the `user_id` in the same row.

**Request body:** `{dids: [...]}`, at most 500.

All three batch routes share one bound, and none of them is an enumeration
oracle: an identifier matching nothing contributes no row and is never a `404`.

---

## Admin Routes — Management

Import/export operations. Prefix: `/admin`.

### `POST /admin/import`

Import a community from a JSON bundle. Full replace: deletes existing community graph and recreates from bundle. Atomic operation.

**Destructive.** Overwriting a community that already exists requires `force: true` and otherwise answers `409`, naming the members and assets that would have been deleted. See [Import & Export](import-export.md#the-force-guard).

**Request body:** `{bundle, dry_run, force}` (see [Import & Export](import-export.md)).

**Response:** `ImportReport` with created counts. A dry run also lists in
`refusals` (`[{code, detail}]`) every invariant refusal the import would make.

**Refused whole**, before anything is deleted, with `422` and the invariant's
`code`, when the bundle breaks an invariant the runtime writes keep — today
`sensor_held`: one trimmed sensor id held by two active members of the bundle, or
by one of them and an active member of another community (that community and
member are not named); `asset_key_too_long`: an asset key over 128 characters;
`invalid_role`, `invalid_status`, `unknown_area`: a member whose role or status
is outside its set, or whose area is not a key of the bundle's `community.areas`;
`invalid_area_key`: an area whose key is not an area key (below, under the area
`PUT`); `invalid_area_boundary`: an area that is not one primary substation (below, under
the area `PUT`), judged against the bundle's own `community.topology` — so a
bundle written before schema v0.7 that has areas is refused, whatever
`schema_version` it declares. The replaced community's own current rows do not
count.

### `POST /admin/import/yaml`

Import one or more communities from a YAML multidocument body. Each document is a separate community bundle.

**Request body:** `text/yaml` — multidocument YAML. Query: `dry_run`, `force`.

**Response:** `MultiImportReport` with per-community results. A bundle breaking an
invariant refuses the whole request as `POST /admin/import` does.

### `GET /admin/export`

Export communities as YAML multidocument.

**Response:** `text/plain` — YAML bundle(s).

---

## Admin Routes — Writes

Runtime changes to a community. Prefix: `/admin`.

Every route here keeps one rule: **no write reduces a sibling.** `PUT` on a
member replaces that member, not the member list; patching a member does not
clear its delivery points; upserting an area does not drop the others. The only
endpoint that deletes what it was not given is the bundle import above.

### `POST /admin/communities/{community_key}/members`

Create one member, with its delivery points and assets.

`key` is optional — when omitted it is minted from the community's own
numbering (`ex-00001` → `ex-00002`), so a caller with no opinion still gets a key
that reads correctly in an exported bundle.

`did` is optional and unique across the whole registry, unlike `key` and
`user_id`, which are unique per community. It is usually written afterwards
rather than here — see `PATCH` below.

`extra` is optional, and its keys are merged into the member's `extra` at the
top level — the same place `PATCH` puts them. Other body keys that are not member
fields are kept in `extra` too.

**Responses:** `201` with the member; `409` when the key or `user_id` is already
taken (`member_key_taken`, `user_id_taken`), naming the existing key so the caller
can switch to `PATCH`, or when an `active` member is created with a `did` another
active member holds anywhere in the registry (`did_taken`, REQ-0096); `409 sensor_held` when an `active` member
is created with a meter whose sensor another active member holds, and `409
delivery_point_held` with a delivery point, or a meter `pod`, another active member
holds; `404
community_not_found`; `422 invalid_role`, `invalid_status` or `unknown_area` when
`role`, `status` or `area` is out of set (the area must be a key of the
community's `areas`).

### `PATCH /admin/communities/{community_key}/members/{member_key}`

Partial update. Absent fields are left alone, never cleared.

`delivery_points` is deliberately not accepted here — it is a JSONB list, and a
patch that happened to omit it would read as "this member now has none". Use the
delivery-point routes.

**This is how a member's dataspace `did` is written**, because the identity is
minted a step after the member is registered. Re-sending a member the DID it
already holds is a `200` that changes nothing, so the write is safe to retry.

**Responses:** `200`; `409 user_id_taken` if the new `user_id` belongs to another
member of the community, or `409 did_taken` if the new `did` belongs to any other
active member in the registry and this member is active after the patch (REQ-0096). A DID clash inside the addressed community names the
holding member; one in another community does not, because which member of which
other community holds a DID is not the caller's question. `status: active` on a
member that was not active re-checks its sensors and delivery points: `409
sensor_held` / `409 delivery_point_held`, and nothing in the patch is applied, when
another active member holds one.

`role` and `area` are still accepted here, with the checks of the profile route
below; `status` too. Out of set: `422 invalid_role`, `invalid_status`,
`unknown_area`, and nothing in the patch is applied. Only the fields a patch names
are checked.

### `PATCH /admin/communities/{community_key}/members/{member_key}/profile`

A member's role and area, and nothing else — the route a community dashboard
holding only `rec-registry.members.profile.write` writes through
(`rec-registry.members.write` and `.admin` reach it too).

```json
{"role": "prosumer", "area": "south"}
```

At least one of the two, and no other key. Absent fields are left alone; the
member's status is not looked at and its assets are left as they are.

| Outcome | Answer |
|---|---|
| written | `200` with the member (`MemberDetail`) |
| an empty body, an unknown key, a `null`, or any other member field (`user_id`, `did`, `status`, `name`, `type`, `extra`) | `422`, FastAPI's validation body; nothing changes |
| `role` outside `consumer`, `prosumer`, `producer`, `operator`, `admin` | `422 invalid_role` |
| `area` not a key of the community's `areas` | `422 unknown_area` |
| unknown community / member | `404 community_not_found` / `member_not_found` |

### `PUT /admin/communities/{community_key}/members/{member_key}/name|role|area`

One field of a member, and nothing else: `{"name": "…"}`, `{"role": "…"}`,
`{"area": "…"}`. Each derives its own action (`members.name.write`,
`members.role.write`, `members.area.write`), so a service can be granted one field
alone; the supersets are in the table at the top.

| Outcome | Answer |
|---|---|
| written | `200` with the member (`MemberDetail`) |
| the key absent or `null`, or any other key beside it | `422`, FastAPI's validation body; nothing changes |
| `role` out of set / `area` not one of the community's | `422 invalid_role` / `unknown_area` — the same answer the general `PATCH` gives |
| unknown community / member | `404 community_not_found` / `member_not_found` |

### `POST /admin/communities/{community_key}/members/{member_key}/status`

Move a member through `pending → active → suspended → inactive`, with an optional
`reason` recorded on the member.

A move to `active` re-checks the member's sensors and delivery points — only an
active member holds one — and answers `409 sensor_held` / `409 delivery_point_held`,
leaving the status unchanged, when another active member took one meanwhile; and
`409 did_taken`, naming nobody, when another active member holds its `did`
(REQ-0096). An unknown status is `422 invalid_status`.

### `DELETE /admin/communities/{community_key}/members/{member_key}`

**Deactivates** the member (`status = inactive`). A member who leaves still has
metering history, past consents and provenance elsewhere that reference them, and
assets cascade on a real delete. The row keeps its `user_id` and `did`; it no longer
answers `/user` (REQ-0094) and no longer blocks its DID (REQ-0096).

`?purge=true` erases the member and its assets permanently. It requires the
separate `rec-registry.members.purge` grant, so a service that manages members
day to day cannot perform one.

**Response:** `DeletionReport` — `purged` tells the caller which happened.

### `PUT|DELETE /admin/communities/{ck}/members/{mk}/delivery-points/{point_id}`

Add, replace or remove one supply point, keeping the others. The body `id` must
match the path (`422` otherwise). Derives `members.delivery_points.write`.

**One active holder per delivery point** across the registry, compared trimmed and
case-insensitively: a `PUT` giving an active member a point another active member
holds is `409 delivery_point_held` (the holder named by key only inside this
community). A member that is not active is checked when it is reactivated.

**Correcting a POD** is one write:
`PUT …/delivery-points/{new}?replaces={old}` with the new point as body. In one
transaction it adds `new`, removes `old` and relinks the member's meters whose
`pod` named `old` to `new` (as the path spells it); a failure changes nothing.

| Outcome | Answer |
|---|---|
| corrected | `200`, `{"delivery_points": [...]}` — the member's points after the write |
| `old` is not one of this member's points | `404` (plain `{"detail"}`) |
| `new` is held by another active member | `409 delivery_point_held` |

`DELETE` of a point one of the member's meters still names is `409
delivery_point_linked`: correct it with `replaces`, or detach the meter, first. An
unknown point is `404`.

**Duplicates already stored** are not repaired by the check; an operator lists them with
`celine-rec-registry duplicate-delivery-points` — a read-only CLI report over
`GET /admin/export` (the export grant), one tab-separated line per active holder:
`delivery_point  community  member  active_holders`, the point trimmed and lower-cased; exit
`0` none, `1` some, `2` unreadable. One community's share of the same list is
`GET /admin/communities/{community_key}/delivery-points/duplicates` (a read; holders in other
communities counted, not named).

### `PUT|DELETE /admin/communities/{ck}/members/{mk}/assets/{asset_key}`

Create, replace or remove one asset. `properties` is validated against the model
for `asset_type` (`pv`, `storage`, `meter`, `ev_charger`, `heat_pump`, `load`),
so an EV charger cannot be stored carrying a heat pump's fields.

**Attaching a meter** is a `PUT` at `meter-<sensor id>`, the id trimmed:

```json
{"key": "meter-SEN-1", "asset_type": "meter",
 "properties": {"name": "Meter", "sensor_id": "SEN-1", "meter_type": "consumption"}}
```

| Outcome | Answer |
|---|---|
| attached | `200` with the stored asset (`AssetDetail`) |
| already attached to this member | `200`, nothing changes |
| another active member, in any community, holds the sensor | `409 sensor_held` — the holder is named by key only inside this community |
| the meter's `pod` is not one of the member's delivery points, and another active member, in any community, holds it as a delivery point or through a meter | `409 delivery_point_held` — named as for the sensor (REQ-0093) |
| another member of this community holds the key (with the convention: an inactive member still holding the asset) | `409 asset_key_taken` |
| the sensor id is blank after trimming | `422` |
| the asset key is longer than 128 characters | `422 asset_key_too_long` |

Sensor ids are compared and stored trimmed (of any Unicode whitespace); only an `active` member holds one, so
a write to a member that is not active is checked when it is reactivated.

**Detaching** is `DELETE` on the same path: a hard delete, `204`, after which the
sensor may be attached elsewhere. An asset the member does not hold is `404
asset_not_found`; an unknown member `404 member_not_found`.

### `PATCH /admin/communities/{community_key}`

Update community metadata. It does not touch areas or topology, for the same
reason the member patch does not touch delivery points: both have their own
routes, below.

### `PUT|DELETE /admin/communities/{community_key}/areas/{area_key}`

Add, replace or remove one area; both answer the whole community. Deleting is
refused with `409 area_in_use` while members still reference it — an orphaned
`Member.area` is a dangling reference nothing else checks. A member write moving
somebody into the area at the same moment is counted, not orphaned: both
serialise on the community's row.

**An area is one GSE primary substation** (REQ-0067). The `PUT` body (`AreaUpsert`):

```json
{
  "name": "northern",
  "boundary": {"source": "gse_cabine_primarie", "id": "AC000E00000"},
  "topology": ["AC000E00000"]
}
```

`location` and `geometry` are accepted and unused; other keys are dropped. The
area is stored and returned with `boundary` and `topology` — every read of a
community carries both on each area (`Area.boundary` is `null` on an area stored
before schema v0.7 without one).

| Refused `422 invalid_area_boundary`, nothing changed | |
|---|---|
| no `boundary`, `null`, a list, or not exactly `{source, id}` of strings | coded, not FastAPI's validation body |
| `source` other than `gse_cabine_primarie`, a blank `id`, or an `id` over 64 characters | |
| `topology` of zero or several ids, or one that is not `boundary.id` (exact) | |
| the node is not in the community's `topology`, is there twice, or is not a `primary_substation` | write the node first (`PUT …/topology/{node_id}`) |
| another area of the community carries the same `boundary.id` | two writers at once: one succeeds |

**The key is an area key**: letters, digits, `-` and `_`, starting with a letter
or digit, at most 128 characters — what a rename accepts as `new_key` and
onboarding's template import holds a template's keys to. Any other `area_key` is
`422 invalid_area_key`, judged before the body, and nothing changes. An area stored
under another key before the rule is read as stored; the rename, below, moves it
onto a key that keeps the rule.

An unknown community is `404 community_not_found`, before the key is judged. The
`PUT` judges the area it writes: areas stored before the rule are not re-judged,
but the written area may not share a boundary id with them. The registry never
checks the code against the GSE dataset.

### `POST /admin/communities/{community_key}/areas/{area_key}/rename`

Move an area to a new key, with its members (REQ-0079); derives `community.write`.
Body `{"new_key": "nord"}` and nothing else. In one transaction under the
community's row lock the area — name, boundary, topology, as stored — is written
under `new_key`, every member of the community whose `area` is `area_key` (any
status) is moved to it, and `area_key` is removed. Nothing else changes: not the
other areas, the topology, the members' other fields or their assets.

```json
{"old_key": "north", "new_key": "nord", "members_moved": 2, "community": {"key": "example-rec", "areas": {"nord": {}}}}
```

`community` is the whole community after the rename (abridged above).

| Refused, nothing changed | |
|---|---|
| `new_key` is not letters, digits, `-` and `_`, starting with a letter or digit, at most 128 characters | `422 invalid_area_key` |
| the community has no area `area_key` | `404 area_not_found` |
| the community already has `new_key` (`area_key` itself included) | `409 area_key_taken` |
| an unknown community | `404 community_not_found` |
| a body with another key, or none | `422`, FastAPI's validation body |

This is the write for a template sync that renames an area with members: an area
`PUT` under the new key is refused (one area per boundary) and the old key's
`DELETE` is refused while members hold it. A member write naming an area at the
same moment serialises with the rename on the community's row.

### `PUT|DELETE /admin/communities/{community_key}/topology/{node_id}`

Add, replace or remove one topology node (REQ-0072); both answer the whole
community and derive `community.write`. The `PUT` body is the bundle's node
(`TopologyNodeIn`), and its `id` must match the path (`422` otherwise, plain body):

```json
{"id": "AC000E00000", "type": "primary_substation", "name": "Northern primary", "operator_id": "example-dso"}
```

`name`, `operator_id`, `parent` and `area` are optional; other keys are dropped.
Nodes merge by `id`: re-sending one replaces it where it stands (the whole node,
not field by field), a new one is appended, and every other node is kept.

| Refused | |
|---|---|
| `PUT` changing the `type` of a node an area lists away from `primary_substation` | `422 invalid_area_boundary`, nothing changed; an area stored before the rule is not re-judged |
| `DELETE` of a node any area lists | `409 topology_node_in_use`, naming the areas: change or delete them first |
| `DELETE` of a node another node names as its `parent` | `409 topology_node_in_use`, naming those nodes by id: re-parent or delete them first |
| `DELETE` of a node the community does not have | `404`, plain body |
| an unknown community | `404 community_not_found` |

The order a template sync writes in: the node, then the area onto it. Both routes
serialise with the area routes on the community's row. No node is left naming a
deleted node as its `parent`; a node naming itself does not hold itself.

---

## Meta Routes

### `GET /health`

Health check. Returns `{"status": "ok"}`.

### `GET /version`

Service version information.
