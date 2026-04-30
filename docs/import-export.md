# Import & Export

## Bundle Format (v0.5)

The registry uses a YAML/JSON bundle format for import and export. A bundle encodes a full community graph:

```yaml
version: "1.0"
schema_version: "0.5"

community:
  id: example_rec
  name: Example REC
  description: A renewable energy community

  legal:
    name: "Example REC"
    vat: "IT0123456789"
    legal_form: "APS"

  links:
    website: "https://example.org"

  contact:
    email: "info@example.org"

  settings:
    timezone: "Europe/Rome"
    currency: "EUR"

  operators:
    example_dso:
      name: Example DSO
      country: IT

  areas:
    northern:
      name: northern
      topology:
        - "AC221E00020"

  topology:
    - id: "PS-001"
      type: primary_substation
      name: "Primary Substation"
      operator_id: example-dso

members:
  member-001:
    name: Alice Rossi
    role: prosumer
    area: northern
    status: active
    type: "schema:Person"
    delivery_points:
      - id: "IT001E00001234"
        type: withdrawal
        active: true
    assets:
      pv:
        - key: pv-001
          name: Rooftop PV
          capacity_kwp: 5.0
      meter:
        - key: meter-001
          name: Main Meter
          sensor_id: "SEN-001"
          meter_type: bidirectional
          pod: "IT001E00001234"
```

Key differences from v0.4:
- `members` is a dict keyed by member key (not a list)
- Assets are nested under members as typed dicts (`assets.pv`, `assets.meter`, `assets.storage`, etc.)
- Community has `areas`, `topology`, `legal`, `links`, `contact`, `settings`, `operators`
- Schema version is `"0.5"` with bundle version `"1.0"`

## Import

### JSON Import — `POST /admin/import`

Import a single community from a JSON request body. Full replace: deletes the existing community and all related entities, then recreates from the bundle. Atomic operation.

```bash
curl -X POST http://localhost:8004/admin/import \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d @community-bundle.json
```

### YAML Import — `POST /admin/import/yaml`

Import one or more communities from a YAML multidocument body. Each YAML document is a separate community bundle.

```bash
curl -X POST http://localhost:8004/admin/import/yaml \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: text/yaml" \
  --data-binary @communities.yaml
```

### CLI Import

```bash
celine-rec-registry import --file recs/rec-example.yaml
# or via taskfile:
task import:community -- --file recs/rec-example.yaml
```

The CLI authenticates via client credentials or password grant (configurable via flags).

## Export

### API Export — `GET /admin/export`

Exports all communities as a YAML multidocument.

```bash
curl "http://localhost:8004/admin/export" \
  -H "Authorization: Bearer <token>" \
  -o communities.yaml
```

### CLI Export

```bash
celine-rec-registry export --community example_rec -o export.yaml
```

## Replace Semantics

Import is a **full replace** operation:

1. The existing community graph (community + all members + all assets) is deleted.
2. The new graph from the bundle is created.
3. The operation is atomic — if any step fails, the entire import is rolled back.

Missing entities in the new bundle are deleted. Changed entities are recreated. New entities are added.

## Idempotency

Import is idempotent: importing the same bundle twice produces the same state. Use exports as authoritative backups and re-import to restore.
