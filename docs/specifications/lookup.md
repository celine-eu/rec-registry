# Cross-community lookup

Every other admin route answers *"what is in this community?"*. These answer the question
the rest of the platform actually asks — **"which community is this in?"** — starting from
a user id, a sensor id or a delivery point.

They exist because nothing else can answer it. A measurement arrives carrying a sensor id
and nothing else; a dataset request arrives carrying a user id. The caller cannot map
either to a community without asking, and six repositories ask.

Two of these requirements are security properties wearing the clothes of ordinary
behaviour: **both** batch forms are bounded, at one shared number (REQ-0043, REQ-0045), and
none of it is an **enumeration oracle** (REQ-0045). Both properties are easy to undo while
making the endpoint more useful, and one of them already was — `assets-by-sensor-ids`
carried no bound at all until the two were made to read the same constant.

---

### REQ-0038 — a user id resolves to its community and the member row within it

`GET /admin/lookup/community-by-user-id/{user_id}` answers the community reference and the
member — key, `user_id`, name, role, status. A user id belonging to no member is `404`.

The member comes back with the community because the caller almost always needs both, and
a second round trip to fetch the member would double the cost of the most-used lookup in
the platform.

### REQ-0039 — a sensor id resolves to its community, its owner and the asset

`GET /admin/lookup/community-by-sensor-id/{sensor_id}` answers all three. An unknown
sensor id is `404`.

The owner is the part that matters. A reading arrives carrying a sensor id and nothing
else; attributing it to a person is this lookup, and without the member in the response
every consumer would have to follow up with a second call.

### REQ-0040 — a delivery point id resolves to its community and member

`GET /admin/lookup/community-by-delivery-point/{dp_id}` answers the community, the member
and the matching delivery point. Unknown is `404`.

Delivery points live in a JSONB list rather than a table, so this lookup scans members and
matches in Python. It is correct and it does not scale the way the other two do — the cost
grows with the number of members in the whole registry, not with a lookup on an index.

### REQ-0041 — a user id resolves to a full member record, across all communities

`GET /admin/lookup/member-by-user-id/{user_id}` answers the member with its delivery
points, and names the community it belongs to. Unknown is `404`.

The wider sibling of REQ-0038: that one answers *where*, this one answers *what*.

### REQ-0042 — a sensor id resolves to a full asset record, with its owner

`GET /admin/lookup/asset-by-sensor-id/{sensor_id}` answers the asset with its properties,
device and relationships, plus `owner_key`, `owner_user_id` and the community. Unknown is
`404`.

### REQ-0043 — sensor ids can be resolved in a batch, and that batch is bounded

`POST /admin/lookup/assets-by-sensor-ids` resolves many sensor ids in one request,
answering one record per asset found. An empty list answers an empty list without querying.

A sensor id that matches nothing **contributes no row** rather than failing the request:
the caller asked about a set, and one absent member of it does not make the rest
unanswerable.

**Bounded:** at most 500 sensor ids in one request; 501 is `422` and 500 is accepted. The
same number as REQ-0045, from the same constant — `MAX_BATCH_LOOKUP_IDS`, which both
request models read. This route carried no bound at all while its sibling capped at 500,
and the asymmetry was accidental: the bound arrived with the newer endpoint and was not
applied to this one. Two literals would have let that happen again.

Sensor ids are less guessable than usernames, which made this the weaker *enumeration*
path — but not the weaker *bulk extraction* one, and extraction is what a bound is for: a
caller holding a list of sensor ids resolves every owner and community behind them in one
request.

**A bound on one request is not a bound on extraction.** Nothing rate-limits this route and
nothing counts what one caller has resolved over an hour, so a caller who wants the
registry can still page through it 500 at a time. What the bound removes is the single
request that takes all of it.

### REQ-0044 — assets can be resolved for a set of members, and every row names its owner

`POST /admin/lookup/assets-by-user-ids` is the mirror of REQ-0043: that one starts from a
device and finds its owner, this one starts from owners and finds their devices. An empty
list of ids answers an empty list without querying.

**Every row carries `owner_user_id`**, which is what lets the caller attribute a row back
to the member it asked about — the entire purpose of a batch form, and useless without it.

It exists because a dataspace query is authorised for a *set of people*: the subjects who
consented, not the caller. The self-service route (REQ-0050) can only ever answer "mine",
because it resolves the member from the caller's own token — and widening *that* endpoint
to accept a list of ids would turn a self-service route into a directory with no scope
check in front of it. So the batch form belongs here, behind the admin policy.

### REQ-0045 — the member batch is bounded, and answers nothing about who exists

**Bounded:** at most 500 user ids in one request; 501 is `422` and 500 is accepted. A
caller that can name ten thousand people in one request has a dump of the registry rather
than a lookup, and this route is reachable by anything holding `rec-registry.lookup`.
Raising the bound widens a data-exfiltration path — it is a security decision wearing the
clothes of a validation constant. The value 500 is arbitrary rather than derived; what is
load-bearing is that a bound exists.

**Not an oracle:** a user id that belongs to nobody and a member who owns no assets are
**deliberately indistinguishable** — both contribute no rows, and neither is a `404`.

The caller supplies the ids, so any difference between those two answers would make this a
way to discover who is registered. Against a service whose rows are real people in real
communities, membership is itself the disclosure — knowing that a given person is in an
energy community is information about them regardless of what they own.

The temptation to undo this is real and reasonable-sounding: *"tell the caller which ids
were not found, so they can clean their list."* That helpfulness is the oracle.

### REQ-0061 — a set of DIDs resolves to the members holding them, bounded and answering nothing about who exists

`POST /admin/lookup/members-by-dids` answers one member record per DID found — key,
`user_id`, `did`, name, role, area, status, **delivery points**, and the community.

**It answers members, not assets**, and that is the part it would be easy to get wrong. The
obvious move is to mirror REQ-0044 exactly and return assets, and it loses the supply point
in the common case: `../onboarding` writes the declared POD into `Member.delivery_points`
and registers **no assets**, because a meter's `sensor_id` is assigned at physical
installation, long after onboarding. An asset-shaped answer is empty for every participant
whose meter has not been commissioned. A commissioned meter stays reachable through the
`user_id` in the same row and REQ-0044.

**Every row carries its `did`**, which is what lets the caller attribute a row back to the
DID it asked about — the same job `owner_user_id` does in REQ-0044.

**Bounded:** at most 500 DIDs in one request; 501 is `422` and 500 is accepted. The same
number as REQ-0043 and REQ-0045, from the same `MAX_BATCH_LOOKUP_IDS`. A DID is the
identifier a consent record is written in, so the set a caller holds is a set of people who
consented — and this route turns that into the supply points they hold. The bound is the
same security decision it is on the other two.

**Not an oracle:** a DID belonging to nobody and a member holding no supply points are
deliberately indistinguishable — both contribute no rows, and neither is a `404`. An empty
list of DIDs answers an empty list without querying.

**It derives `assets.lookup`, not `lookup`** (REQ-0005). Resolving what a named person
holds is a different disclosure from resolving which community a sensor sits in, and this
route does the first.
