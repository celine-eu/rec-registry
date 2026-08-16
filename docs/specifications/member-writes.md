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
that key's prefix and zero-padding preserved: `gl-00001`, `gl-00002` → `gl-00003`;
`ab-007` → `ab-008`. Keys that are not numbered are ignored when reading the pattern, and
a community with no members at all starts at `member-00001`.

A caller with no opinion should get the next key in the series rather than a UUID that
reads as foreign in an exported bundle — the bundle is a file people edit.

**A gap below the maximum is never reused.** `gl-00001`, `gl-00009` mints `gl-00010`, not
`gl-00002`: reusing a freed number would hand a new person the identity of one who left,
along with whatever history elsewhere in the platform still references that key.

The bound on that guarantee is honest and narrow — the *highest* number is the only state
consulted, so purging the highest-numbered member does let the next mint reuse their key.
See `.agents/knowledge/`. `member-00001` and its five-digit padding are arbitrary defaults
rather than chosen ones.

### REQ-0022 — creating refuses a duplicate key or a duplicate `user_id`

Either conflict answers `409`, naming the existing key or `user_id` so the caller can
switch to `PATCH`.

**Creating must not silently update.** A retry carrying a changed payload — the ordinary
shape of a client reconnecting — would otherwise rewrite the wrong person's row, and
`user_id` is the field that would attach one participant's identity to another's meters.

Both checks are **application-level, not database constraints**: `member` carries no
unique index on `key` or `user_id`, within a community or across the registry. Two
concurrent creates naming the same key can therefore both pass the check and both insert.
The window is small and the writers are few — `../onboarding` and an operator — but the
guarantee is "refused when observed", not "impossible".

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
`409`.

### REQ-0025 — a status change is its own route, and records why

`POST …/members/{mk}/status` moves a member through `pending`, `active`, `suspended`,
`inactive`, with an optional `reason` stored at `extra.status_reason`. An unrecognised
status answers `422`.

Separate from `PATCH` because a status change is the transition an operator reasons about,
and because it reads clearly in an audit log where a generic field update does not.

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

### REQ-0027 — supply points merge by identity, never by position

`PUT …/members/{mk}/delivery-points/{id}` adds or replaces exactly one point, keeping the
others; re-sending an existing id updates it rather than duplicating it; `DELETE` removes
one and keeps the rest. Removing an id the member does not have is `404`. The `id` in the
body must match the one in the path, or `422`.

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

`DELETE` on the same path answers `204`.

### REQ-0029 — patching a community keeps its areas, and upserting an area keeps the others

`PATCH /admin/communities/{ck}` updates `name`, `description`, `legal`, `links`, `contact`
and `settings`, merging `extra`. It does not touch `areas` or `topology`, which have their
own routes for the same reason delivery points do — they are collections with their own
identity, and a patch omitting one would read as emptying it.

`PUT …/areas/{key}` adds or replaces one area and returns the whole community, so the
caller can see the others are still there.

### REQ-0030 — an area still referenced by a member cannot be deleted

`DELETE …/areas/{key}` answers `409` naming how many members still reference it. An unused
area is removed and the community returned without it; an area that does not exist is
`404`.

An orphaned `Member.area` is a dangling reference nothing else in the system checks. It
would surface much later, and somewhere else, as a member belonging to an area that does
not exist — and area membership is what the incentive calculation is computed over.

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
