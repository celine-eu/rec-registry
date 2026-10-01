# Member and community writes

How a community changes at runtime — one member at a time, as a manager approves somebody
at 14:32 on a Tuesday.

Everything on this page rests on one rule, stated last because everything else is an
instance of it: **no write reduces a sibling** (REQ-0031). Before these routes existed the
entire write surface was a replacement import, and every one of these requirements exists
to stop a piece of that wholesale behaviour leaking into a route that should touch one row.

---

### REQ-0020 — creating a member returns the member, with everything it arrived with

`POST /admin/communities/{ck}/members` answers `201` with the member: its key, `user_id`,
role, area, status and delivery points. A supplied `key` is honoured as given.

### REQ-0021 — an omitted key is minted from the community's own numbering

`key` is optional. When absent it is taken from the highest-numbered existing key, with
that key's prefix and zero-padding preserved: `ex-00001`, `ex-00002` → `ex-00003`;
`ab-007` → `ab-008`. Keys that are not numbered are ignored when reading the pattern, and
a community with no members at all starts at `member-00001`.

A caller with no opinion should get the next key in the series rather than a UUID that
reads as foreign in an exported bundle — the bundle is a file people edit.

**A gap below the maximum is never reused.** `ex-00001`, `ex-00009` mints `ex-00010`, not
`ex-00002`: reusing a freed number would hand a new person the identity of one who left,
along with whatever history elsewhere in the platform still references that key.

The bound on that guarantee is honest and narrow — the *highest* number is the only state
consulted, so purging the highest-numbered member does let the next mint reuse their key.
See the companion's knowledge. `member-00001` and its five-digit padding are arbitrary defaults
rather than chosen ones.

### REQ-0022 — creating refuses a duplicate key or a duplicate `user_id`

Either conflict answers `409`, naming the existing key or `user_id` so the caller can
switch to `PATCH`.

**Creating must not silently update.** A retry carrying a changed payload — the ordinary
shape of a client reconnecting — would otherwise rewrite the wrong person's row, and
`user_id` is the field that would attach one participant's identity to another's meters.

**Two writers at once get the same answer.** The check is application-level and the
message is its work, but `member` carries unique indexes on `(community_id, key)` and
`(community_id, user_id)`, so a create that passes the check because the clashing row was
not committed yet is refused by the index instead — and that refusal is translated back
into the same `409`. A caller cannot tell a race from an ordinary duplicate, and the loser
leaves no row behind.

The same holds for `PATCH` reassigning a `user_id` (REQ-0024): its clash check is equally
blind to an uncommitted row, and equally backed.

The guarantee is per community, not registry-wide — one person may hold the same `user_id`
in two communities, which is what makes membership of several possible.

### REQ-0023 — a write naming an unknown community is `404`

Rather than creating the community implicitly. A community is seeded deliberately; a
member arriving for one that does not exist is a caller with a stale key, not an
instruction to invent it.

### REQ-0024 — a patch leaves absent fields alone, and cannot steal an identity

`PATCH …/members/{mk}` updates only the fields it names. `extra` merges rather than
replaces, because it accumulates fields from several sources and a caller that knows about
one must not erase the rest.

**`delivery_points` is deliberately not accepted here.** It is a JSONB list, and a partial
update that happened to omit it would read as *"this member now has none"*. It has its own
sub-resource (REQ-0027). Adding the field to the patch model is a data-loss bug, not a
convenience — the absence is load-bearing.

A patch moving `user_id` to one already held by another member of the community answers
`409` — including when the holder's row was written concurrently and the clash check could
not see it yet, which the unique index behind REQ-0022 is what catches.

A patch setting `status: active` on a member that was not active re-checks its sensors, and
the whole patch answers `409` `sensor_held` — changing nothing — when another active member
holds one (REQ-0069).

`role` is held to its set and `area` to the community's areas (REQ-0066), as on the narrower
route role and area also have (REQ-0070).

### REQ-0025 — a status change is its own route, and records why

`POST …/members/{mk}/status` moves a member through `pending`, `active`, `suspended`,
`inactive`, with an optional `reason` stored at `extra.status_reason`. An unrecognised
status answers `422`.

Separate from `PATCH` because a status change is the transition an operator reasons about,
and because it reads clearly in an audit log where a generic field update does not.

A change to `active` re-checks the member's sensors, and answers `409` `sensor_held` rather
than reactivating a member whose meter another active member now holds; the status is left as
it was (REQ-0069). An unrecognised status carries the code `invalid_status` (REQ-0073).

### REQ-0026 — deleting deactivates; erasing is a different request and reports what it took

`DELETE …/members/{mk}` sets `status = inactive` and answers a `DeletionReport` with
`purged: false`. The member remains readable.

`?purge=true` erases the member permanently, answering `purged: true` and `assets_removed`
counting the assets that went with them. It needs the separate `members.purge` grant
(REQ-0006).

Deactivation is the default because a member who leaves still has metering history, past
consents and provenance elsewhere in the platform that reference them — and because
`Asset` cascades on member delete, so a real delete looks like it affected one row and
silently takes the member's measurement history with it.

`assets_removed` is in the report for that reason: it is the number the caller did not ask
about and needs to see.

Deactivating releases the member's sensors, since only an active member holds one
(REQ-0069). It does not release the asset keys: an inactive member's `meter-<sensor id>`
still occupies that key in the community until the asset is deleted (REQ-0071).

### REQ-0027 — supply points merge by identity, never by position

`PUT …/members/{mk}/delivery-points/{id}` adds or replaces exactly one point, keeping the
others; re-sending an existing id updates it rather than duplicating it; `DELETE` removes
one and keeps the rest. Removing an id the member does not have is `404`. The `id` in the
body must match the one in the path, or `422`. A `PUT` with `?replaces=` corrects a point
(REQ-0084); a `DELETE` of a point one of the member's meters names is refused (REQ-0084); an
active member taking a point another active member holds is refused (REQ-0085). Both routes
derive `members.delivery_points.write` (REQ-0081).

The merge is by point id, not by list index, and it does not mutate the list it was given.
Positional replacement silently drops entries, and a member gaining a second supply point
must not lose the first.

### REQ-0028 — an asset upsert replaces that asset only, and validates its properties by type

`PUT …/members/{mk}/assets/{ak}` creates the asset or replaces it in place, leaving the
member's other assets untouched.

`properties` is validated against the model for the declared `asset_type`, so an EV
charger cannot be stored carrying a heat pump's fields, and an incomplete one answers
`422`. An `asset_type` that is not one of the six answers `422` **naming the valid ones**
— the caller's next request depends on knowing them, and a bare rejection makes them read
the source.

**An asset key is unique per community, not per member.** The lookup behind the upsert
filters by owner as well, so a key that looks free to this member may already be another
member's — and the two outcomes behind that are different:

- **The key is already this member's**, including when a concurrent writer created it a
  moment ago. The upsert is applied to that row and answers `200`. A create-or-replace is
  idempotent by definition, so a race means only that two writers arrived in an order
  neither cared about; reporting a conflict the caller cannot act on would push retry logic
  into six consuming repositories for nothing.
- **The key is another member's.** `409`. Applying the upsert would move somebody else's
  meter onto this member, which is not what *replace my asset* asked for — and this is not
  only a race: two members using one key in sequence takes exactly the same path.

`DELETE` on the same path answers `204`; an asset the member does not hold is `404`.

A meter attached by a manager is keyed `meter-<sensor id>` and detached by this `DELETE`
(REQ-0071); the upsert refuses a sensor another active member holds (REQ-0069), checked before
the key; the key clash above carries the code `asset_key_taken`, distinct from `sensor_held`,
and the `404` carries `asset_not_found` (REQ-0073).

**An asset key longer than 128 characters — what `asset.key` holds — is refused `422`
`asset_key_too_long`** before anything is written, on every path that writes assets: this
upsert, creating a member with assets (REQ-0020), and the bundle import (REQ-0074), where it
is an import refusal like `sensor_held`. It used to fail the insert and answer `500`. With the
meter convention (REQ-0071) a sensor id longer than 122 characters reaches it. A coded refusal
rather than a validation error, because the caller — a manager typing the id printed on a
device — needs to tell it from the other outcomes of an attach by `code`. The `detail` gives
the key's length and the limit, not the key, which can embed a sensor id.

The upsert answers the stored asset, as `AssetDetail` (the body of the asset `GET`), so a
generated client has its type.

### REQ-0029 — patching a community keeps its areas, and upserting an area keeps the others

`PATCH /admin/communities/{ck}` updates `name`, `description`, `legal`, `links`, `contact`
and `settings`, merging `extra`. It does not touch `areas` or `topology`, for the same reason
delivery points are absent from the member patch — they are collections with their own
identity, and a patch omitting one would read as emptying it. Areas have their own route,
below, and topology its node routes (REQ-0072). The community `PATCH` stays outside the area
invariant of REQ-0067, because it never touches either collection.

`PUT …/areas/{key}` adds or replaces one area and returns the whole community, so the
caller can see the others are still there. The area it writes is one primary substation, or
the write is refused `422` `invalid_area_boundary`, and its key is an area key, or the write is
refused `422` `invalid_area_key` (REQ-0067).

### REQ-0030 — an area still referenced by a member cannot be deleted

`DELETE …/areas/{key}` answers `409` naming how many members still reference it. An unused
area is removed and the community returned without it; an area that does not exist is
`404`.

An orphaned `Member.area` is a dangling reference nothing else in the system checks. It
would surface much later, and somewhere else, as a member belonging to an area that does
not exist — and area membership is what the incentive calculation is computed over.

The count is taken under an exclusive lock on the community's row, which a member write
naming an area holds shared until it commits, so a member moved into the area at the same
moment is counted rather than orphaned (REQ-0066).

The refusal carries the code `area_in_use` (REQ-0073). It is the answer an onboarding
template sync meets when it prunes an area that still has members, and the count in the
message is what tells its operator how many to move first.

### REQ-0031 — no write reduces a sibling

The invariant the whole write API exists to keep:

> `PUT` on a member replaces **that member**, not the member list. Patching a member does
> not clear its delivery points. Upserting an area does not drop the others.

**There is no collection-level replace outside the bundle import**, which is the only
place wholesale replacement is allowed and which announces itself (REQ-0033).

This is verified by exercising **every** write against a two-member community and checking
the member count afterwards — `tests/test_writes.py::TestNoWriteReducesASibling`. That test
is a **registry of writes, not a sample of them**: a new write endpoint must be added to
it, and one that is missing from it is a write nobody has checked for the single thing the
write API guarantees.

Attaching and detaching a meter (REQ-0071), a refused `sensor_held` attach, a
reactivation, the profile route (REQ-0070) — accepted and refused — the area `PUT`,
accepted and refused `invalid_area_boundary` and `invalid_area_key` (REQ-0067), and the topology node `PUT` and
`DELETE` (REQ-0072) — a new node, a replaced one, a refused type change and a refused
`topology_node_in_use` delete — of a node an area lists, and of a node another node names as
its `parent` — and accepted deletes — are in it, and so is the area rename (REQ-0079),
accepted and refused `area_key_taken`, `area_not_found` and `invalid_area_key`. For the
topology writes the test also counts the community's nodes: a node write keeps every other
node; for the renames it compares the areas: a rename changes one key and nothing else.
The field routes (REQ-0083), accepted and refused, are in it, and so are the delivery-point
writes: a `PUT` and a `DELETE`, a correction with `replaces` (REQ-0084), refused `404` and
`delivery_point_held` (REQ-0085), and a `DELETE` refused `delivery_point_linked`; for these it
also compares both members' delivery points, which every write but the one addressed leaves
as they were.

### REQ-0060 — the dataspace DID is written by `PATCH`, and a clash names its holder only within the community

`PATCH …/members/{mk}` accepts `did` alongside the fields of REQ-0024. There is **no
dedicated route**: the DID is minted a step after the member is registered, so it arrives
as an update to a row that already exists, and a write endpoint of its own would earn
nothing `PATCH` already does while adding one more entry to REQ-0031's registry of writes.

**Re-sending a member the DID it already holds is a `200` that changes nothing.**
`../onboarding` writes it from a retriable step, so the same write arriving twice must not
be a conflict — the member itself is excluded from the clash check, by row id rather than
by member key, because keys repeat across communities and the check does not filter by one.

**A DID another member already holds is `409`, and what the message says depends on where
that member is:**

- **Inside the community the caller addressed** — the response names the holding member's
  key, as the `user_id` clash does, so the caller can act on it.
- **In any other community** — the response says the DID belongs to another member and
  names nobody. Which member of which community holds a DID is a question about people the
  caller was not addressing, and answering it is the enumeration disclosure REQ-0045
  exists to refuse.

**Two writers at once get the same answer**, by the mechanism of REQ-0022: the check cannot
see an uncommitted row, `ix_member_did` refuses the loser, and that refusal is translated
into the same `409`. The translated message is the community-blind one — by then there is
no holder in hand to name, which is the honest answer rather than a degraded one.

Creating a member that carries an already-held DID answers `409` the same way. It has no
application-level check of its own: the two checks in `create_member` read a list of the
community's own members, and DID uniqueness is registry-wide, so a check would be a second
query answering exactly what the index answers.

### REQ-0062 — a member's `extra` is stored at the same level on create as on patch

`POST …/members` accepts `extra` as `PATCH` does (REQ-0024), and merges its keys into the
member's `extra` at the top level. Body keys that are neither columns nor `extra` are still
copied into `extra` as they always were; where one clashes with a key of `extra`, `extra`
wins, as it does over `type` on a patch. So a client sending one body to either route gets
one stored shape — before, create stored it one level down, at `extra.extra`.

**A bundle member is not affected.** The bundle model does not declare `extra`: a bundle
member's unknown keys already are the top level of `extra`, and the exporter writes them
back there, so a literal `extra:` key in a bundle is kept as it arrived. An API-created
member therefore exports with those keys flat and re-imports unchanged (REQ-0037).

**Rows written before this are not rewritten.** A member created with `extra` earlier —
`../onboarding`'s `declared_at_onboarding` among them — still holds it at `extra.extra`.

### REQ-0070 — a member's role and area are written through a route that accepts nothing else

`PATCH /admin/communities/{ck}/members/{mk}/profile` accepts a body of `{role?, area?}`: at
least one of the two, and no other key. An empty body, an unknown key, a `null`, or a key the
general `PATCH` accepts — `user_id`, `did`, `status`, `name`, `type`, `extra` — answers `422`
with FastAPI's validation body and changes nothing. `role` and `area` are checked as REQ-0066
says (`422 invalid_role`, `422 unknown_area`); an unknown community or member is `404`
`community_not_found` / `member_not_found`. A valid request answers `200` with the member, and
absent fields are left alone as REQ-0024 leaves them. The member's status is not looked at,
and its assets are left as they are.

It derives `members.profile.write` (REQ-0063). Accepting nothing else is what makes that
action narrower than `members.write` in fact and not only in name: a body that could carry a
`user_id` would hand the narrower grant the identity rewrite REQ-0022 exists to stop. Decided
in [ADR-0003](../decisions/ADR-0003-role-and-area-have-their-own-route-and-action.md).

### REQ-0071 — a meter is attached at `meter-<sensor id>`, and detaching it deletes it

A community manager attaches a meter with the asset `PUT` of REQ-0028 at
`…/members/{mk}/assets/meter-<sensor id>`, the sensor id trimmed, `asset_type: meter`. The
outcomes a caller must tell apart:

- **attached** — `200`;
- **already attached to this member** — `200`, the idempotent replace of REQ-0028;
- **the sensor is held by another active member, in any community** — `409` `sensor_held`
  (REQ-0069);
- **the key is held by another member of this community** — which, with this convention, means
  an inactive member still holds the asset — `409` `asset_key_taken`, not `sensor_held`,
  because the remedy is different: delete that asset, then attach.

The sensor check runs before the key check, so a key another *active* member holds for the
same sensor answers `sensor_held`. A sensor id blank after trimming is `422`, and one long
enough to make the key exceed 128 characters is `422` `asset_key_too_long` (REQ-0028). The registry does
not enforce the key convention — it is the convention the dashboard uses, and an asset `PUT`
at any other key is still the upsert of REQ-0028, still checked by REQ-0069.

**Detaching is `DELETE` on the same path, and it is a hard delete** (`204`; `404`
`asset_not_found` when the member holds no such asset, including one another member holds). Readings are joined to members without dates, so after a detach
the sensor's whole history follows its next holder; keeping the previous holder's share is the
job of dated holdings, a recorded follow-up and not this requirement. Decided in
[ADR-0004](../decisions/ADR-0004-a-sensor-has-one-active-holder-and-detaching-deletes-the-meter.md).

### REQ-0072 — topology nodes are written one at a time, merging by id

`PUT /admin/communities/{ck}/topology/{node_id}` adds or replaces exactly one node, keeping the
others; re-sending an existing id replaces that node where it stands rather than duplicating
it, and a new id is appended. The `id` in the body must match the one in the path, or `422`.
`DELETE` removes one node and keeps the rest; a node the community does not have is `404`; a
node an area still references — any area, whether or not it keeps REQ-0067 — is refused with
`409` `topology_node_in_use`, naming the areas; so is a node another node names as its
`parent`, naming those nodes by id only, so they are re-parented or deleted first (a node
naming itself does not hold itself). Both derive `community.write` (REQ-0004) and
answer the whole community, as the area routes do.

**The body is the bundle's topology node** (`TopologyNodeIn`): `id`, `type`, and optionally
`name`, `operator_id`, `parent`, `area`. Every read answers a node under those same names
(`TopologyNode`): before 1.6.0 reads answered `operator`, a schema v0.4 name nothing had stored
since v0.5, so it was always `null` and the stored `operator_id` was never returned. Keys beyond
these are accepted and not stored, as on the import, which builds a node with the same function.
No node is left naming a deleted node as its `parent`.

**A node write never breaks an area that keeps REQ-0067:** a `PUT` changing the `type` of a node
such an area references away from `primary_substation` answers `422` `invalid_area_boundary` and
changes nothing. An area stored before the rule is not re-judged by a write to its node, as the
area `PUT` leaves such a sibling alone. A community stored holding one id twice keeps one after a
`PUT` of that id: the first, replaced. Both routes take the community's row exclusively before
reading the areas, as the area routes do, so an area write and a node write on one community are
serialised.

Topology is a collection with its own identity, like delivery points (REQ-0027), and the
merge-by-id rule is theirs for the same reason. It is the route an onboarding template sync
writes a community's substations through. Decided in
[ADR-0006](../decisions/ADR-0006-onboarding-templates-are-the-source-of-truth-for-areas.md).

### REQ-0073 — a refusal a caller acts on carries a code from a closed list

The body of such a refusal is `{"detail": "<sentence>", "code": "<code>"}`. `detail` stays a
string with its current meaning; the code sits beside it, never inside it. Clients — the SDK
among them — branch on `code`, never on the wording of `detail`. The codes, and the requirement
each comes from:

| Code | Status | Refusal |
|---|---|---|
| `community_not_found` | `404` | a write naming an unknown community (REQ-0023) |
| `member_not_found` | `404` | a write naming a member the community does not have (REQ-0024 – REQ-0028) |
| `asset_not_found` | `404` | deleting an asset the member does not hold (REQ-0028, REQ-0071) |
| `member_key_taken` | `409` | a member key already held in the community (REQ-0022) |
| `user_id_taken` | `409` | a `user_id` already held in the community (REQ-0022, REQ-0024) |
| `did_taken` | `409` | a DID held by another member anywhere (REQ-0060) |
| `asset_key_taken` | `409` | an asset key held by another member of the community (REQ-0028, REQ-0071) |
| `asset_key_too_long` | `422` | an asset key longer than the 128 characters `asset.key` holds, on every path that writes assets (REQ-0028) |
| `sensor_held` | `409` | a sensor id held by another active member anywhere (REQ-0069) |
| `area_in_use` | `409` | deleting an area members still reference (REQ-0030) |
| `invalid_status` | `422` | a status outside the set, on every write path (REQ-0025, REQ-0066) |
| `invalid_role` | `422` | a role outside the set, on every write path (REQ-0066) |
| `unknown_area` | `422` | an area that is not a key of the community's areas, on every write path (REQ-0066) |
| `invalid_area_boundary` | `422` | an area that is not one primary substation — one boundary, one `primary_substation` node with its id, no two areas on one boundary id — on the area `PUT`, the topology node `PUT` and the import (REQ-0067, REQ-0072) |
| `topology_node_in_use` | `409` | deleting a topology node an area still references, or another node names as its `parent` (REQ-0072) |
| `area_not_found` | `404` | renaming an area the community does not have (REQ-0079) |
| `area_key_taken` | `409` | renaming an area onto a key the community already has (REQ-0079) |
| `invalid_area_key` | `422` | an area key that is not letters, digits, `-` and `_`, starting with a letter or digit, at most 128 characters — on the area `PUT`, the rename's `new_key` and the import (REQ-0067, REQ-0079) |
| `not_a_member` | `403` | a self-service read by a caller whose username names no member (REQ-0047) |
| `delivery_point_held` | `409` | a delivery point held by another active member anywhere, on the delivery-point `PUT`, a create, a move to `active` and the import (REQ-0085) |
| `delivery_point_linked` | `409` | deleting a delivery point one of the member's meters still names as its `pod` (REQ-0084) |

`sensor_held` and `delivery_point_held` are `422` on an import, where the bundle is what is
wrong (REQ-0069, REQ-0074, REQ-0085).
A route that answers a coded `422` declares its `422` in the OpenAPI document as either body —
`oneOf` `ErrorResponse` and FastAPI's `HTTPValidationError`, whose `detail` is a list — since
both arrive with that status: the member create, both `PATCH` routes (REQ-0070), the role and area
`PUT` routes (REQ-0083) and the status route, the asset `PUT`, the area `PUT`, the area rename, the topology node `PUT`, and both
import routes.
The two `404` codes let a caller detaching a meter tell *"that member is gone"* from *"that
meter is already detached"*. Every write route documents the body in the OpenAPI document as
`ErrorResponse`, with the codes as the `ErrorCode` enum, and so does every self-service route
that answers `403 not_a_member`.

A code names the rule, never the entity: it carries no key or id, and what the `detail` may name
follows the rule already governing it (REQ-0060, REQ-0069). A code is added here by the
requirement that introduces its refusal. An import refusal (REQ-0074) carries the code of the
invariant it breaks. Refusals no requirement has given a code keep the plain
`{"detail": "<sentence>"}` body — FastAPI's own validation errors, a body id or key that does
not match the path, an unknown asset type, the import's `force` guard (REQ-0033), and the `404`
for an unknown delivery point — on its `DELETE` and as the `replaces` of a correction
(REQ-0084) — topology node, or area on its `DELETE` (the rename's is coded).
Decided in
[ADR-0008](../decisions/ADR-0008-a-refusal-carries-a-machine-readable-code.md).

### REQ-0079 — an area's key is renamed in one write, with its members

`POST /admin/communities/{ck}/areas/{area_key}/rename` with body `{"new_key": "<key>"}` moves
an area to a new key. In **one transaction, under the community's row taken exclusively**, the
area as stored — `name`, `boundary`, `topology`, and whatever else it carries — is written
under `new_key`, every member of the community whose `area` is `area_key` is moved to
`new_key`, **whatever their status**, and `area_key` is removed. It answers `{old_key, new_key,
members_moved, community}`, the whole community after the rename. It derives
`community.write` (REQ-0004).

**Nothing else changes** (REQ-0031): not the other areas, not the topology, not a member's
other fields, not a member's assets, not a member of another community whose `area` has the
same key. The area is moved as stored, not re-judged against REQ-0067, and the set of
boundary ids never changes — so no reader ever sees two areas on one boundary, both keys, or a
member in an area that does not exist.

**Refused, changing nothing:**

- a `new_key` that is not an area key — letters, digits, `-` and `_`, starting with a letter
  or digit, at most 128 characters (what `member.area` holds, and what onboarding's template
  import accepts; the rule every write of a key holds, REQ-0067) — `422` `invalid_area_key`;
- an `area_key` the community does not have — `404` `area_not_found`;
- a `new_key` the community already has, `area_key` itself included — `409`
  `area_key_taken`;
- an unknown community — `404` `community_not_found`; a body other than `{new_key}` — `422`
  (FastAPI's validation body).

**Concurrency** follows the order every write takes its locks in: community row, then member
rows (REQ-0066). A member write naming an area holds the row shared, so a rename waits for it
and then moves that member too; a member write naming an area during a rename waits, then
finds `area_key` gone (`422 unknown_area`) or `new_key` there. A write that names no area
takes no community lock, waits on the member row the rename updated, and leaves the moved area
as it is. Two renames of one area at once: one succeeds, the other finds it gone.

This is how an onboarding template sync renames an area that has members: an area `PUT` under
the new key is refused (`invalid_area_boundary`, one area per boundary) and a `DELETE` of the
old key is refused (`area_in_use`) while members hold it. Decided in
[ADR-0010](../decisions/ADR-0010-an-area-is-renamed-with-its-members-in-one-write.md).

### REQ-0083 — a member's name, role and area each have a route that writes that field and nothing else

`PUT /admin/communities/{ck}/members/{mk}/name` with `{"name": "<name>"}`, `PUT …/role` with
`{"role": "<role>"}` and `PUT …/area` with `{"area": "<area key>"}` each write one field and
answer `200` with the member. The body is exactly that one key: absent, `null`, or beside any
other key — `user_id`, `did`, `status`, another field — it is `422` with FastAPI's validation
body, and nothing changes. An unknown community or member is `404` `community_not_found` /
`member_not_found`.

**The value checks are the general `PATCH`'s** (REQ-0066), the same function on the same
values: a role outside its set is `422 invalid_role`, an area that is not a key of the
community's areas `422 unknown_area` — the same status, code and sentence as the general
`PATCH` gives for that value — and a name is held to no set, as on the `PATCH`. The area is
checked under the community's row (REQ-0066). The member's other fields, its status, its
delivery points and its assets are left as they are.

Each derives its own action (REQ-0081) so that a service can be granted one field
(REQ-0082). `PATCH …/profile` (REQ-0070) stays as the role-and-area alias, and the general
`PATCH` keeps accepting all three for `members.write` holders (REQ-0024). A member whose key is
`name`, `role`, `area` or `delivery-points` is addressed like any other. Decided in
[ADR-0011](../decisions/ADR-0011-member-writes-are-granted-per-field.md).

### REQ-0084 — a delivery point is corrected in one write, and one a meter names cannot be deleted

`PUT /admin/communities/{ck}/members/{mk}/delivery-points/{new}?replaces={old}` corrects a
member's delivery point. In **one transaction**, under the member's row lock:

- `new` is added (the body is the point, its `id` equal to `new`, as REQ-0027);
- every point of the member whose id is `old`, compared trimmed and case-insensitively as
  REQ-0085 compares, is removed;
- every meter of **this member** whose `properties.pod`, compared the same way, names `old` is
  relinked: its `pod` becomes `new`, spelled as the path spells it. Nothing else of the meter
  changes, and another member's meter naming `old` is not touched.

It answers `200` with the member's delivery points, as the `PUT` without `replaces` does. A
failure at any step leaves both points and every link as they were. `old` that is not one of
this member's points — another member's, an unknown one, a blank one — is `404` (plain
`{"detail"}` body, as for the `DELETE` of an unknown point) and changes nothing. An active
member's `new` that another active member holds is `409 delivery_point_held` (REQ-0085),
checked before anything changes; the member's own `old` is not a clash, so a correction of
spelling alone (`it001…` → `IT001…`) is accepted. Without `replaces` the `PUT` is REQ-0027's,
plus REQ-0085. `replaces` never changes the action (REQ-0081).

**`DELETE …/delivery-points/{id}` of a point one of the member's meters still names** as its
`pod` — trimmed, case-insensitive — is `409 delivery_point_linked`, and nothing changes: the
meter would otherwise name a supply the member no longer has. The sentence names the point
and how many meters name it, not the meters. Correct the point with `replaces`, or detach the
meter (REQ-0071), first. The check and the removal hold the member's row, which a meter
attach takes too.

The query parameter carries a POD, so the access log redacts it (REQ-0080). This is the call
onboarding's POD correction makes: one write, no asset grant. Decided in
[ADR-0012](../decisions/ADR-0012-a-delivery-point-has-one-active-holder-and-is-corrected-in-one-write.md).
