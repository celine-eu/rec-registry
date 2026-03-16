# Import & Export

## Bundle Format (v0.4)

The registry uses a YAML bundle format for import and export. A bundle encodes a full community graph:

```yaml
version: "0.4"
community:
  key: COMM1
  name: Community One
  metadata:
    gse_zone: IT-North

members:
  - id: member-001
    name: Alice Rossi
    role: prosumer
    metadata: {}
    sites:
      - id: site-001
        address: "Via Roma 1, Milano"
        assets:
          - id: asset-001
            asset_type: pv
            metadata:
              capacity_kw: 5.0
          - id: asset-002
            asset_type: meter
```

## POST /admin/import — Replace Semantics

Importing a bundle is a **full replace** operation:

1. The existing community graph (community + all members, sites, assets) is deleted.
2. The new graph from the YAML bundle is created.
3. The operation is atomic — if any step fails, the entire import is rolled back.

This means:
- Missing entities in the new bundle are deleted.
- Changed entities are recreated with the new data.
- New entities are added.

**There is no partial or delta import.**

## GET /admin/export

Exports the full community graph as a YAML bundle in v0.4 format.

```bash
curl "http://localhost:8000/admin/export?community=COMM1" \
  -H "Authorization: Bearer <token>" \
  -o community-comm1.yaml
```

## Idempotency

Import is idempotent: importing the same bundle twice produces the same state. Use exports as authoritative backups and re-import to restore.

## Validation

Before applying, use `GET /admin/import` to validate a bundle without modifying the database:

```bash
curl -X GET http://localhost:8000/admin/import \
  -F "file=@community-comm1.yaml"
```

Returns `200` with validation details, or `422` with field-level errors.
