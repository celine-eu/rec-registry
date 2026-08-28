# Data Model

## Core Entities

### Community

Top-level entity representing a Renewable Energy Community.

| Field | Type | Description |
|---|---|---|
| `key` | `str` | Unique community identifier (e.g., `example_rec`) |
| `name` | `str` | Human-readable display name |
| `description` | `str` | Optional free-text description |
| `areas` | `JSONB` | Named areas, each with `name`, `topology` (list of node IDs), optional `location`/`geometry` |
| `topology` | `JSONB` | Grid topology as a list of nodes (`id`, `type`, `name`, `operator_id`, children) |
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
| `did` | `str?` | Dataspace decentralised identifier. Optional, unique across the whole registry |
| `name` | `str` | Display name |
| `role` | `str` | `consumer`, `prosumer`, `producer`, `operator`, or `admin` |
| `area` | `str` | Reference to a community area key |
| `status` | `str` | `pending`, `active`, `suspended`, or `inactive` |
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
| `key` | `str` | Unique asset identifier within the community |
| `asset_type` | `str` | `pv`, `storage`, `meter`, `ev_charger`, `heat_pump`, or `load` |
| `name` | `str` | Display name |
| `sensor_id` | `str?` | Optional sensor/meter identifier (promoted column for lookups) |
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
