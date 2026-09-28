# Operability

Running the service, and driving it from outside a browser: the CLI an operator seeds and
backs up communities with, and the two routes that answer questions about the process
itself.

---

### REQ-0054 — the CLI sends the file verbatim, to the YAML endpoint, with a bearer token

`celine-rec-registry import --file <path>` posts the file's **bytes** to
`/admin/import/yaml`, with `Authorization: Bearer <token>`. It does not parse the YAML and
re-serialise it.

Sending the file as given is the point: a multidocument file imports as several
communities in one request, and a round trip through a parser is an opportunity to change
what the operator is looking at in their editor. The report is printed per community, and
a dry run says so.

Authentication is by client-credentials or password grant, or by `--token` directly.

### REQ-0055 — the CLI states `force` on every import, and it defaults to off

`force` is sent explicitly as `"false"` rather than omitted, on every import request
including a dry run.

Omitting a parameter and sending it false are the same thing to the server today. They
stop being the same thing the moment the default changes on either side, and the
destructive default is the one worth pinning down at both ends — this is the flag standing
between an operator and REQ-0033.

### REQ-0056 — the CLI exports one, several or all communities, and fails loudly

`--community` may be given once, several times, or not at all — selecting one, several, or
every community. The result goes to stdout or to `-o <file>`.

**An HTTP error exits non-zero.** A CLI that printed an error and exited `0` would be
invisible to whatever ran it; export is the backup half of REQ-0037, and a backup that
silently did not happen is worse than one that visibly failed.

### REQ-0057 — health answers without a database

`GET /health` answers `{"status": "ok"}` and touches nothing else.

It is what an orchestrator restarts the pod on, so it must not depend on the database:
tying liveness to a dependency turns a database blip into a restart loop that cannot
recover because restarting was never the fix.

That independence is the requirement, and it is also the limitation — **this endpoint
becoming green says nothing about the service being able to serve a request.** There is no
readiness check that does.

### REQ-0058 — `/version` answers what is deployed

`GET /version` answers `api_version` and `schema_version`, and both are derived:

- **`api_version`** is the installed distribution's version, from `importlib.metadata`. It
  was the literal `"1.0.0"` while the package was on 1.5.0, so comparing it across two
  environments could not tell you they differed — which is the only thing the field is for.
  A distribution that cannot be found answers `0.0.0+unknown` rather than raising: this
  route is reached for when something is already wrong.
- **`schema_version`** is `CURRENT_SCHEMA_VERSION` from `core/versions.py`, the same
  constant the bundle model, the exporter and the importer read (REQ-0018). It was `"0.4"`,
  which matched nothing anywhere.

The route still answers with no database, for the same reason `/health` does.

**The OpenAPI document derives both too.** `create_app` sets `info.version` from
`api_version()` and names the bundle schema from `CURRENT_SCHEMA_VERSION`; they were the
literals `"1.0.0"` and `"v0.4 schema"`, which is the same defect in a fifth place. It
matters more here than in a docstring: `../celine-sdk` snapshots this API under
`openapi/rec-registry/v<info.version>/` and generates its client from that directory, so a
version that does not move while the document does overwrites a snapshot in place — and no
consumer of the generated client can tell the API changed.

### REQ-0076 — the CLI reports sensor ids held by more than one active member, and writes nothing

`celine-rec-registry duplicate-sensors` reads every community through `GET /admin/export` and
prints one line per holder of each trimmed sensor id — trimmed as the registry trims it
(REQ-0069), so an id exported with a tab or a no-break space around it is the same sensor —
that more than one **active** member holds, in any communities: the sensor id, the community key, the member key, and how many
active members hold it. A member holding one id under two asset keys is one holder. It exits
`0` when there are none, `1` when there are, and `2` when the registry cannot be read — so an
unreadable registry is never reported as clean.

The registry refuses the next write that would make a second active holder (REQ-0069) but
does not repair holders that already exist, and nothing else would find them: every write
path now refuses to create one. This is the report ADR-0004 asks to run before the check is
relied on. It issues one `GET` and no other request.

### REQ-0077 — the CLI reports members whose role, status or area is out of set, and writes nothing

`celine-rec-registry out-of-set-values` reads every community through `GET /admin/export` and
prints one line per offending field: the community key, the member key, the field (`role`,
`status` or `area`), and the value — `<missing>` when the export does not carry the field. A
role or status is out of set when it is not one of REQ-0066's values, compared exactly; an area
when it is not a key of **that member's own community's** `areas`. It exits `0` when there are
none, `1` when there are, and `2` when the registry cannot be read — so an unreadable registry
is never reported as clean. It prints no name, `user_id` or other personal field.

The writes refuse such values from REQ-0066 on, but rows written before it are not repaired,
and a re-import of their community is refused (REQ-0074). This is the report REQ-0066 asks to
run before the check is relied on; it judges with the same function the writes do, so the two
cannot disagree about what is out of set. It issues one `GET` and no other request.

### REQ-0078 — the CLI reports stored areas that break the one-substation rule, and writes nothing

`celine-rec-registry invalid-area-boundaries` reads every community through `GET /admin/export`
and prints one line per broken rule: the community key and the refusal sentence REQ-0067's
check produces, which names the area keys and the rule — never a boundary or node id. Every
area of each community is judged against that community's own `topology`, with the function
the area `PUT`, the topology node `PUT` and the import use (`area_boundary_refusals`), so the
report and the check cannot disagree. An area whose key is not an area key (REQ-0067) is listed
too, one line per key before the community's boundary lines, with the function the import uses
(`area_key_refusals`). It exits `0` when there are none, `1` when there are, and `2` when the
registry cannot be read. It issues one `GET` and no other request.

The writes refuse such areas from REQ-0067 on, but areas stored before it are not re-judged by
a write to a sibling, and a re-import of their community is refused (REQ-0074). This is the
report to run before a deployment relies on the rule — then an onboarding template sync, an
area rename (REQ-0079) for a key, or a reshaped bundle, corrects what it lists.

---

## What is not verified here

- **The CLI's other commands.** `list`, `tree`, `lookup-user` and `lookup-sensor` have no
  tests. So does `config`, and so does the authentication flow — every CLI test passes
  `--token` directly, so neither the client-credentials nor the password grant is
  exercised.
- **Startup.** `create_app` wiring, settings loading, and the policy engine's bundle load
  at boot. A service that starts with an unloadable Rego bundle is not something any test
  here would notice.
- **`downgrade`, and migrating a database that holds rows.**
  `tests/test_migrations.py` runs `alembic upgrade head` into a throwaway schema and
  compares it to `Base.metadata`, so a model that has drifted from `alembic/versions/` no
  longer passes. It builds an empty schema and never goes back down, so what a revision
  does to existing rows is still nobody's test.
