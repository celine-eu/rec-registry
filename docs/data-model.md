# Data Model

## Core Entities

### Community

A Renewable Energy Community (REC) is the top-level entity. It groups members, sites, and assets under a shared energy boundary.

| Field | Type | Description |
|---|---|---|
| `key` | `str` | Unique community identifier (e.g., `COMM1`) |
| `name` | `str` | Human-readable display name |
| `description` | `str` | Optional free-text description |
| `metadata` | `JSONB` | Extensible properties (GSE zone, regulatory context, etc.) |
| `created_at` | `datetime` | Record creation timestamp |

### Member

A participant belonging to a community. Members can be producers, consumers, or prosumers.

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Unique member identifier |
| `community_key` | `str` | Foreign key to Community |
| `name` | `str` | Display name |
| `role` | `str` | `producer`, `consumer`, or `prosumer` |
| `metadata` | `JSONB` | Additional properties |

### Asset

A physical or virtual energy asset (meter, panel, battery, etc.) associated with a member.

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Unique asset identifier |
| `member_id` | `str` | Foreign key to Member |
| `asset_type` | `str` | Type classification (e.g., `pv`, `meter`, `battery`) |
| `metadata` | `JSONB` | Asset-specific properties |

### Site

A physical location grouping assets. Optional intermediate layer between Member and Asset.

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Unique site identifier |
| `member_id` | `str` | Owning member |
| `address` | `str` | Physical address |
| `coordinates` | `JSONB` | Optional GeoJSON point |

## JSONB Fields

JSONB fields provide flexible extensibility without schema migrations. They are surfaced verbatim in API responses and stored as validated JSON. Common patterns:

- `metadata.gse_zone` — GSE regulatory zone (Italian deployments)
| - `metadata.boundary` — participant ID list for consumption boundaries
- `metadata.capacity_kw` — installed capacity in kilowatts

## Relationships

```
Community
  └── Member (many)
        └── Site (many, optional)
              └── Asset (many)
```

Assets without a site are attached directly to a Member.

## IRI Convention

All entities are represented as expanded IRIs in JSON-LD responses using the CELINE ontology:

```
https://celine-eu.github.io/ontologies/celine#Community
https://data.celine.eu/communities/COMM1
```

No CURIE output is produced. The `@context` always references the remote context document.
