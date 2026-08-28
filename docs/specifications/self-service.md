# Self-service

What a participant may see about themselves, under `/user`. Six routes, and one rule
holding all of them: **the caller's own member row is resolved first, and everything else
is scoped to it.**

There is no policy question here. `/admin` asks *may this caller do this?*; `/user` never
asks, because nothing a participant can request is anything but their own. That makes the
scoping the whole of the security, and it is enforced not by a rule in a policy bundle but
by a `WHERE owner_id = <the member we resolved>` repeated in each route — **a seventh
route added without it would look exactly like the others.**

---

### REQ-0046 — the profile answers who the caller is and where they belong

`GET /user` answers the caller's JWT profile — `sub`, email, name, `preferred_username` —
together with their membership: the member summary, the community summary, how many
delivery points they have, and their assets counted by type.

The member summary carries `did` (REQ-0059), `null` for a member who holds none. This is
the route an application loads first and it is shaped to make a second request unnecessary
for the common case, so the caller's dataspace identity belongs in it.

The counts are of the caller's own assets.

### REQ-0047 — a caller who is a member of nothing is answered, not refused

`GET /user` answers `200` with `membership: null`. The other five routes answer `403`.

The asymmetry is deliberate. `GET /user` is the route an onboarding application calls *to
find out* whether somebody is a member yet, so it must be answerable before the answer is
yes. The rest have nothing to return, and `403` says why rather than pretending an empty
result.

### REQ-0048 — the member detail is the caller's own, omits what they already know, and carries what they do not

`GET /user/member` answers key, name, role, area, status, `did`, delivery points, `extra`
and timestamps — and **not `user_id`**.

Every field not returned is a field that cannot leak. The caller already knows their own
identifier, so returning it buys nothing and puts an identity into one more response body.

**`did` is returned, and the difference from `user_id` is the point.** A participant knows
the username they authenticated with; they do not know the dataspace DID, because an
onboarding service minted it on their behalf a step after registration — and it is the
identifier their consent records are written in. Withholding it would mean a participant
cannot see, in the one place that is theirs, which dataspace identity acts for them.

It is `null` for a member who holds none, which is every member of a deployment with no
dataspace and every member between registration and minting.

### REQ-0049 — the community detail carries the caller's place in it, and not its member list

`GET /user/community` answers the community — name, description, legal, links, contact,
settings, areas and topology — plus `your_area` and `your_role`.

Community-level detail is shared by everyone in it and is not scoped. **The member list is
not part of it:** knowing your community must not mean enumerating everybody in it. That
is `/admin`, behind the `read` grant.

### REQ-0050 — a participant lists their own assets, and only their own

`GET /user/assets` answers the caller's assets, sorted by key, with a total. The
`asset_type` filter narrows within them and never widens beyond them.

The response omits owner information — the caller knows whose they are.

### REQ-0051 — another member's asset is *not found*, not *forbidden*

`GET /user/assets/{key}` naming an asset owned by somebody else answers `404`, with the
same body as an asset key that does not exist anywhere.

The distinction is the requirement. A `403` would confirm that the key names something
real, turning the route into a way to test whether a guessed asset key exists — and asset
keys are guessable, being `meter-<member key>` in every bundle this service ships with.

### REQ-0052 — a participant lists their own delivery points, and only their own

`GET /user/delivery-points` answers the caller's supply points with a total.

### REQ-0053 — the caller is identified by username, not by subject

Every route here resolves its member with `JwtUser.get_username()`, which returns
`preferred_username` — **not `sub`**. So `Member.user_id` holds a Keycloak *username*, and
a token whose subject happens to be somebody else's username still resolves to the member
matching its `preferred_username`.

A token carrying **no** `preferred_username` matches nobody: `get_username()` falls back to
the string `user-<sub>`, which is not a form any `user_id` in the registry takes. The
fallback is therefore not a fallback but a guaranteed miss, and the caller — who may be a
perfectly good member — is told they belong to nothing.

This is the failure worth stating loudest, because it is silently wrong rather than loud:
the operator reading that `403` investigates the registry, and the fault is in the token.

---

## What is not verified here

- **The `401`.** `require_user` raises when no user is on the request, but the suite
  overrides that dependency to choose an identity, so the unauthenticated path is not
  exercised. Nothing here proves a caller with no token is refused — that is the
  middleware's job, and the middleware is not covered either
  ([identity and authorisation](identity-and-authorisation.md)).
- **Cross-community membership.** Every route resolves the member with a query on
  `user_id` alone, taking the first match, with no community filter. The data model allows
  one person to be a member of two communities; what these routes would answer if they
  were is not specified and not tested.
