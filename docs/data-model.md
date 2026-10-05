# Data Model

## Core Entities

### Community

Top-level entity representing a Renewable Energy Community.

| Field | Type | Description |
|---|---|---|
| `key` | `str` | Unique community identifier (e.g., `example_rec`) |
| `name` | `str` | Human-readable display name |
| `description` | `str` | Optional free-text description |
| `areas` | `JSONB` | Named areas; each is one GSE primary substation: `name`, `boundary` (`{source: gse_cabine_primarie, id: <cod_ac>}`), `topology` (exactly one node ID, equal to `boundary.id`, a `primary_substation` node of `topology`), optional `location`/`geometry` (unused). `boundary.id` is at most 64 characters. No two areas share a `boundary.id`; enforced on the area `PUT`, the topology node `PUT` and on import. An area key is letters, digits, `-` and `_`, starting with a letter or digit, at most 128 characters; enforced on the area `PUT`, the rename's new key and on import. Areas stored before schema v0.7 may lack a boundary, or carry another key, and are read back as stored. An area's key changes only through `POST …/areas/{key}/rename`, which moves its members' `area` with it (REQ-0079) |
| `topology` | `JSONB` | Grid topology as a list of nodes (`id`, `type`, `name`, `operator_id`, `parent`, optional `area` geometry), the bundle's names, which reads answer too. Written one node at a time by `PUT`/`DELETE …/topology/{node_id}`, merging by `id` (REQ-0072); a node an area lists, or another node names as its `parent`, cannot be deleted |
| `legal` | `JSONB` | Legal info: `name`, `vat`, `legal_form` |
| `links` | `JSONB` | Public URLs: `website`, `logo`, `privacy_policy`, `terms` |
| `contact` | `JSONB` | Contact info: `email`, `pec`, `phone` |
| `settings` | `JSONB` | Operational settings: `timezone`, `currency` |
| `extra` | `JSONB` | Extensible properties; `extra.operators` holds operator definitions |

### Member

A participant belonging to a community.

| Field | Type | Description |
|---|---|---|
| `key` | `str` | Unique member identifier within the community |
| `user_id` | `str` | Keycloak **username** the participant authenticates with — not a subject UUID |
| `did` | `str?` | Dataspace decentralised identifier. Optional, unique among active members across the whole registry (REQ-0096) |
| `name` | `str` | Display name |
| `role` | `str` | `consumer`, `prosumer`, `producer`, `operator`, or `admin` — enforced on every write path |
| `area` | `str` | A key of the community's `areas` — enforced on every write path; rewritten by an area rename (REQ-0079) |
| `status` | `str` | `pending`, `active`, `suspended`, or `inactive` — enforced on every write path |
| `delivery_points` | `JSONB` | List of delivery point objects (`id`, `type`, `description`, `address`, `tariff`, `active`) |
| `extra` | `JSONB` | Extensible properties; `extra.type` holds a schema.org CURIE |

A member carries three identifiers and each answers a different question: `key` is what
this community calls them, `user_id` is who they authenticate as, and `did` is who they are
in the dataspace. `user_id` matches `preferred_username` in the token — a row written with
a subject UUID exports cleanly and locks its owner out. `did` arrives after registration
(the identity is minted a step later) and is absent entirely in a deployment with no
dataspace.

### Asset

A physical or virtual energy asset associated with a member and community.

| Field | Type | Description |
|---|---|---|
| `key` | `str` | Unique asset identifier within the community, at most 128 characters; a meter attached at runtime is keyed `meter-<sensor_id>` |
| `asset_type` | `str` | `pv`, `storage`, `meter`, `ev_charger`, `heat_pump`, or `load` |
| `name` | `str` | Display name |
| `sensor_id` | `str?` | Optional sensor/meter identifier (promoted column for lookups); stored trimmed, and held by at most one `active` member across the registry (REQ-0069) |
| `properties` | `JSONB` | Type-specific properties (e.g., `capacity_kwp` for PV, `meter_type`/`pod` for meters) |
| `device` | `JSONB` | SAREF-inspired device specification: `manufacturer`, `model`, `serial_number`, `firmware_version`, `type` |
| `relationships` | `JSONB` | Asset relationships: `measures` (list of asset keys), `paired_with` (asset key) |
| `extra` | `JSONB` | Extensible properties |
| `community_id` | `FK` | Foreign key to Community |
| `owner_id` | `FK` | Foreign key to Member |

## Relationships

```
Community
  +-- Member (many)
  |     +-- Asset (many, via owner_id)
  +-- Asset (many, via community_id)
```

Assets belong to both a community and an owning member. There is no `Site` entity; assets attach directly to members.

## JSONB Conventions

JSONB fields provide flexible extensibility without schema migrations. They are stored as validated JSON and surfaced verbatim in API responses. Type-specific asset properties vary by `asset_type`:

- **pv**: `capacity_kwp`, `orientation`, `tilt`, `installation_date`
- **storage**: `capacity_kwh`, `max_power_kw`, `chemistry`
- **meter**: `meter_type`, `pod`, `direction`
- **ev_charger**: `max_power_kw`, `connector_type`, `num_connectors`, `smart_charging`
- **heat_pump**: `thermal_power_kw`, `cop`, `heat_source`, `reversible`
- **load**: `rated_power_kw`, `load_type`, `controllable`, `priority`
