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

### REQ-0058 — version reporting is decorative

`GET /version` answers `api_version` and `schema_version`. Both are string literals in
`api/meta.py`, and neither is derived from anything:

- **`api_version` is `"1.0.0"`** while the package is on 1.5.0. It has not moved in five
  minor releases, so comparing it across two environments cannot tell you they differ.
- **`schema_version` is `"0.4"`**, which matches nothing that exists — the documents and
  the example bundle say `0.5`, the bundle model defaults to `1.0`, and the exporter emits
  `1.0` (REQ-0018).

So the one route whose job is to answer *"what is deployed?"* answers *"what was typed
into a file"*. This is a defect —
[#38](https://github.com/celine-eu/rec-registry/issues/38) — and it is described here as
it behaves. Its tests assert the **mismatch**, so closing it turns them red deliberately,
and fixing it means changing the code, this requirement and those tests together.

---

## What is not verified here

- **The CLI's other commands.** `list`, `tree`, `lookup-user` and `lookup-sensor` have no
  tests. So does `config`, and so does the authentication flow — every CLI test passes
  `--token` directly, so neither the client-credentials nor the password grant is
  exercised.
- **Startup.** `create_app` wiring, settings loading, and the policy engine's bundle load
  at boot. A service that starts with an unloadable Rego bundle is not something any test
  here would notice.
- **The migrations.** Alembic is not exercised by any test — the suite builds its schema
  from `Base.metadata` — so a model that has drifted from `alembic/versions/` passes
  everything and fails on deployment.
