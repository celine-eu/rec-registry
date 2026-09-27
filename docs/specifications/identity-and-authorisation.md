# Identity and authorisation

Who the caller is, and what they may do. Two mechanisms, and they are not the same one:

- **`/admin`** — a JWT plus an OPA decision, where the action asked about is derived from
  the request itself. That derivation is the subject of most of this page.
- **`/user`** — a JWT, and no policy question at all. Every self-service route is scoped
  by resolving the caller's own member row; see [self-service](self-service.md).

The distinction that matters: `/admin` asks *may this caller do this?*, while `/user`
never asks, because there is nothing a participant can request there that is not already
their own.

---

### REQ-0001 — the admin action is derived from the path **and** the method

`PolicyMiddleware._get_admin_action` maps a request to one action name, which is then the
subject of the policy question. Any `GET` under `/admin` is `read`, whatever it reads —
communities, members, assets, a single meter.

Reads and writes are therefore separate grants. While every admin route was a read, one
action name was enough; the moment a service account could create a member it stopped
being enough, because reading every community and rewriting its members are not the same
permission and a service that does one has no business doing the other.

### REQ-0002 — every mutating method on a member path is `members.write`

`POST`, `PUT`, `PATCH` and `DELETE` on `…/members` or `…/members/{key}` all derive
`members.write`. The method set is closed deliberately: a new verb that fell through the
match would be authorised as a read.

### REQ-0003 — an asset path is an asset write, even though it contains `/members`

`/admin/communities/{ck}/members/{mk}/assets/{ak}` derives `assets.write`, not
`members.write`.

**Ordering in the matcher is load-bearing**, because an asset path contains `/members` as
a proper substring. Get the order wrong and asset writes silently require the member
grant — silently, because everything still works for any caller holding both, which is
every caller during development.

### REQ-0004 — community metadata and areas are one grant of their own

`PATCH /admin/communities/{ck}` and any write on `…/areas/{key}` derive `community.write`.
Areas are community structure rather than membership, so they are authorised with the
community and not with the members who reference them.

**Planned:** the topology node routes of REQ-0072 derive `community.write` too, for the same
reason — a node is community structure.

### REQ-0005 — import, export and lookup keep their own actions, and one lookup is named apart

`/admin/import` and `/admin/import/yaml` derive `import`; `/admin/export` derives
`export`; anything under `/admin/lookup/` derives `lookup`.

**With two exceptions, and they are the same exception twice.**
`/admin/lookup/assets-by-user-ids` and `/admin/lookup/members-by-dids` derive
**`assets.lookup`**. Both start from an identifier that names a *person* and answer what
that person holds; the rest answer which community a user, a sensor or a supply point sits
in. That is a different disclosure, so it gets a different name.

Both are granted by `rec-registry.lookup` today and nothing changes for a caller — naming
them apart is what lets a policy separate them later without an API change. Anything else
under `/admin/lookup/` falls through to `lookup`, so a new person-shaped batch route has to
be added here deliberately rather than inheriting the broader action by default.

These are separable because they are the ones a service account most often should
*not* have. A service account is granted the actions it calls and no others: one that
registers approved participants needs `members.write`, one that attaches meters needs
`assets.write`, and neither has any business importing, exporting or purging.

### REQ-0006 — erasing a member is authorised apart from writing one

`DELETE …/members/{key}` alone derives `members.write`. The same request with a truthy
`purge` query parameter derives **`members.purge`**, a separate grant.

Deactivating somebody is recoverable and erasing them is not — `Asset` cascades, so a
purge takes their meters with them. A service that manages members day to day must not be
able to cross that line by adding a query parameter to a request it is already allowed to
make.

**The import grant is the exception to that line.** A forced import replaces a community's
whole graph (REQ-0032), deleting every member and asset in it, so a holder of
`rec-registry.import` can do to a community what `members.purge` cannot do to one member.
The separation above holds only for callers who do not hold the import grant.

### REQ-0007 — an ambiguous purge parameter reads as the recoverable action

`purge=true`, `purge=1`, `purge=yes` and `purge=on` ask for the purge grant. Everything
else — absent, empty, `false`, `0`, `maybe`, or a different parameter entirely — derives
the ordinary `members.write`.

The rule is that **the safe reading of an ambiguous request is the recoverable one**. An
unrecognised value must never be read as consent to erase.

### REQ-0008 — `purge` outside a member path changes nothing

`DELETE /admin/communities/{ck}?purge=true` derives `community.write`. The parameter is
only meaningful where a purge is possible, so it does not leak the purge action onto paths
that have no such operation.

No community `DELETE` route exists; the requirement pins what the derivation would answer,
so that adding one cannot inherit the purge action by accident.

### REQ-0009 — `{service}.admin` satisfies every action

The shared scope matcher in `../celine-sdk` treats a held scope ending `.admin` as
covering every action of that service, so `rec-registry.admin` satisfies `read`,
`members.write`, `members.profile.write`, `members.purge`, `assets.write`, `community.write`,
`import`, `export`, `lookup` and `assets.lookup`.

This is what made the fine-grained actions backwards compatible: every token that worked
before they existed still works. The property is pinned by reading
`policies/celine/scopes.rego` directly, because its absence would be silent until
deployment — and would then revoke access for every existing admin token at once.

**It is compatibility, not a recommendation.** Do not grant `rec-registry.admin` to a
service account; grant the actions it calls.

### REQ-0010 — every action name has a rule in the Rego bundle

`policies/celine/rec_registry/access.rego` carries a rule for each of the eleven action
names `_get_admin_action` can return: the ten grants, and `admin`, which a path matching no
route derives (REQ-0065) and only `rec-registry.admin` satisfies. An action derived by the middleware with no
corresponding rule would be denied by default — a fail-closed outcome, but one that
presents as an unexplained `403` in production rather than as anything a test would catch.

So the bundle is read and checked for all eleven, rather than the actions being exercised
one at a time. `assets.lookup` is the one that shows why this is checked as a set: it was
added to the middleware and to the bundle together but left out of the list being checked,
so for a while the check passed while covering eight of nine.

`members.profile.write` (REQ-0063, REQ-0064) joined the set in the same change as the
middleware and the bundle, as every addition must.

### REQ-0063 — the member profile route derives `members.profile.write`, and no other member route does

`PATCH /admin/communities/{ck}/members/{mk}/profile` derives **`members.profile.write`**.
Every other mutating request on a member path keeps deriving `members.write` (REQ-0002), or
`members.purge` (REQ-0006), exactly as today — including the general `PATCH …/members/{mk}`,
which still accepts `role` and `area`. Any other method on the profile path matches no route
and derives `admin` (REQ-0065); a read of it is a read (REQ-0001).

The route exists so that a service correcting a member's role and area — a community
dashboard — can be given that and nothing more. The action is named by the route and the
method, never by the body, because the middleware decides before the body is read. Decided in
[ADR-0003](../decisions/ADR-0003-role-and-area-have-their-own-route-and-action.md).

### REQ-0064 — `members.profile.write` is satisfied by its own scope, by `members.write` and by `admin`

`policies/celine/rec_registry/access.rego` allows `members.profile.write` for a caller holding
`rec-registry.members.profile.write`, `rec-registry.members.write` or `rec-registry.admin`. A
caller holding only `rec-registry.members.profile.write` is refused `members.write` — the
general `PATCH` among it — and every other action: pinned by requests through the middleware
with the policy engine on.

The superset lives in the policy rule, not in the shared matcher in
`policies/celine/scopes.rego`, which stays exact-or-`.admin`-or-`.*`: `members.write` does not
match `members.profile.write` by any of those rules, so without the rule listing it a service
that already writes members — onboarding — would be refused the narrower write it could
always perform through the general `PATCH`.

### REQ-0065 — a caller-supplied id never changes the action a request derives

The action depends only on the fixed segments of the route a request matches, each read at its
position, and on the method. A member key, asset key, delivery-point id, area key, community
key or lookup id that contains `lookup`, `import`, `export`, `assets`, `members`, `profile` or
any other route word derives the same action as the same request with a plain id:
`PUT …/members/{mk}/assets/meter-export-01` is `assets.write`, not `export`, and a holder of
`rec-registry.lookup` alone is refused a `PUT` or `DELETE` of an asset keyed
`meter-lookup-01`.

The method is honoured on the fixed routes too: import is a `POST` and export a read, and a
lookup is a read or a batch `POST`. **A request matching no route shape derives `admin`**, which
only `rec-registry.admin` satisfies — such a request answers `404` or `405` anyway, and an
unknown shape must not fall through to whichever narrower grant a word in it resembles.

The derivation used to match by substring over the whole path, before it looked at the method,
so such an id derived the action of whatever word it contained — and a holder of that action's
grant reached a write it was never given. Asset keys become `meter-<sensor id>` (REQ-0071), so
the content of an id is no longer under the registry's operators' control at all. Pinned by
hostile-id tests over every admin route family, and by requests through the middleware with the
policy engine on.

It was the first change of the set, landed before REQ-0071 wrote caller-supplied
`meter-<sensor id>` keys. Decided in
[ADR-0003](../decisions/ADR-0003-role-and-area-have-their-own-route-and-action.md).

---

## What is not verified here

- **The middleware itself.** These requirements pin `_get_admin_action`, a pure function,
  called directly. Nothing exercises the surrounding request path: JWT parsing and
  verification, the policy engine's decision cache, or the `401` that an unauthenticated
  caller should receive. The suite runs with `AUTH_ENABLED=false` and
  `POLICIES_ENABLED=false`.
- **Which community a write reaches.** Every grant is registry-wide: a holder of
  `rec-registry.assets.write` can write any community's assets, and a holder of
  `rec-registry.members.profile.write` (REQ-0063) any community's members. Keeping a manager
  to their own community is the calling dashboard's policy, and nothing here checks it.
- **The Keycloak realm.** Operators are authorised by organization and group against state
  `../celine-policies` owns and syncs. There is no import to grep for and nothing here
  would notice a rename.
