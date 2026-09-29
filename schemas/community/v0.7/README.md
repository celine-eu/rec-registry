# CELINE REC Registry Schema v0.7

JSON Schema for Renewable Energy Community (REC) registry manifests in the CELINE ecosystem.

---

## Purpose

A registry manifest is a single YAML file that provides the authoritative description of a REC: its identity, grid topology, participants, and their assets. It is used at ingestion time to populate the rec-registry database and drive interoperability across CELINE services (dataset-api, celine-policies, celine-pipelines).

---

## Top-level Structure

| Field | Required | Description |
|---|---|---|
| `version` | yes | Manifest format version (currently `"1.0"`) |
| `schema_version` | yes | Schema this file conforms to (`"0.7"`) |
| `metadata` | no | Authoring metadata |
| `community` | yes | Community definition |
| `members` | yes | Member registry (keyed by member ID) |

---

## `metadata`

| Field | Description |
|---|---|
| `created` | Creation date (YYYY-MM-DD) |
| `updated` | Last update date (YYYY-MM-DD) |
| `updated_by` | Author or system that last updated the file |
| `description` | Free-text description |

---

## `community`

Required fields: `id`, `name`. `areas` is optional and may be empty, so an **administrative-only** bundle — the community's own data, with no areas, no topology and no members yet — is a valid v0.7 file; its areas are added later, by area writes or a later import.

| Field | Description |
|---|---|
| `id` | Stable lowercase identifier (`^[a-z0-9_-]+$`). Used as the Keycloak organization alias. |
| `name` | Human-readable community name |
| `description` | Free-text description |
| `legal` | Legal entity details (see below) |
| `links` | Public URLs (website, logo, privacy policy, terms, statute, regulations) |
| `contact` | Contact information (email, pec, phone, address) |
| `settings` | Operational settings (timezone, currency, energy\_unit, power\_unit) |
| `operators` | Grid operators active in the community (see below) |
| `areas` | Regulatory coverage areas (see below) |
| `topology` | CIM-aligned grid topology nodes (see below) |

### `community.legal`

| Field | Description |
|---|---|
| `name` | Official registered name |
| `vat` | VAT / tax ID |
| `fiscal_code` | Fiscal code (country-specific) |
| `legal_form` | e.g. APS, cooperativa, srl |
| `registration_number` | Business register number |
| `registered_office` | Registered office address |

### `community.operators`

Dict keyed by operator ID. The key **must** match an `id` entry in `owners.yaml` so that the KC org provisioning pipeline (`sync-orgs`) can resolve it. Referenced by topology nodes via their `operator_id` field (the registry's reads answer the same name).

```yaml
operators:
  example-dso:
    name: Example Distribution Network Operator
    country: IT       # ISO 3166-1 alpha-2
    contact: ""       # optional email or URL
```

### `community.areas`

Dict keyed by area ID. Areas represent **regulatory coverage zones** — in the Italian context these correspond to GSE *cabine primarie* service areas that define virtual self-consumption eligibility under Decreto 199/2021. They are **not** a CIM concept.

**An area is exactly one GSE primary substation.** It references one boundary, and lists exactly one topology node: a `primary_substation` node of `community.topology` whose `id` equals `boundary.id`. No two areas of one community reference the same `boundary.id`. The area key stays a hand-managed name; the boundary is what maps it to its substation.

An area key is letters, digits, `-` and `_`, starting with a letter or digit, at most 128 characters. The schema does not state it; the registry refuses any other key on the area write and on import (`invalid_area_key`).

| Field | Required | Description |
|---|---|---|
| `name` | yes | Area display name |
| `boundary` | yes | `{source, id}`: `source` is `gse_cabine_primarie`, `id` the substation code (`cod_ac`), at most 64 characters. A reference, never a shape |
| `topology` | yes | Exactly one topology node ID: `boundary.id`. The platform's pipelines read it as the primary substation of every member in the area |
| `location`, `geometry` | no | Accepted and unused |

```yaml
areas:
  northern:
    name: northern
    boundary:
      source: gse_cabine_primarie
      id: "AC000E00001"
    topology:
      - "AC000E00001"

topology:
  - id: "AC000E00001"
    type: primary_substation
    name: "Primary Substation northern"
    operator_id: example-dso
```

The equality of `topology[0]` and `boundary.id`, the node's type and the uniqueness across areas cannot be stated in JSON Schema. The registry holds them on the area write and on import, where a bundle breaking them is refused with `invalid_area_boundary` whatever `schema_version` it declares. The registry does not check `boundary.id` against the GSE dataset; it cannot read it.

### `community.topology`

List of electrical grid nodes. Required fields: `id`, `type`.

| Field | Description |
|---|---|
| `id` | Stable node identifier. Use the DSO's own node ID (e.g. the DSO mRID for the substation). |
| `type` | `primary_substation` \| `secondary_substation` \| `transformer` \| `feeder` |
| `name` | Human-readable name |
| `operator_id` | Operator ID — references a key in `community.operators` |
| `parent` | Parent node ID (for hierarchy, e.g. secondary substation → primary substation) |

Node types map to Italian electrical grid concepts:

| Type | Italian term | Voltage transformation |
|---|---|---|
| `primary_substation` | cabina primaria | AT/MT (HV → MV) |
| `secondary_substation` | cabina secondaria | MT/BT (MV → LV) |
| `transformer` | trasformatore | standalone |
| `feeder` | feeder / linea MT | MV distribution feeder |

```yaml
topology:
  - id: "AC000E00001"
    type: primary_substation
    name: "Primary Substation Example"
    operator_id: example-dso

  - id: "SS-example-001"
    type: secondary_substation
    name: "Secondary Substation Example"
    parent: "AC000E00001"
    operator_id: example-dso
```

---

## `members`

Dict keyed by a stable member ID (e.g. `ex-00001`). Required fields: `user_id`, `name`, `role`, `area`, `status`.

| Field | Description |
|---|---|
| `user_id` | Keycloak **username** the participant authenticates with (`preferred_username`) — not a subject UUID |
| `did` | Dataspace decentralised identifier. Optional, and unique across the whole registry |
| `name` | Display name |
| `type` | Participant entity type — schema.org CURIE (see below) |
| `role` | `consumer` \| `prosumer` \| `producer` \| `operator` \| `admin` |
| `area` | Reference to a key in `community.areas` |
| `status` | `pending` \| `active` \| `suspended` \| `inactive` |
| `delivery_points` | List of connection points (PODs, CUPS, etc.) |
| `assets` | Asset collection by type (see below) |

### `member.did` — dataspace identity

The identifier this member is known by in the dataspace, and the join key between the
connector's answer to *who consented* — stated in DIDs — and the registry's answer to *what
they hold*.

```yaml
members:
  ex-00001:
    user_id: alice
    did: "did:web:dataspace.example%3A30005:alice"
```

**Optional, and usually absent in a file.** The DID is minted one step *after* a member is
registered, so it is written by `PATCH` at runtime rather than authored here; it appears in
an export once it exists, and is omitted entirely — not written as `null` — when it does
not. A deployment with no dataspace never has one.

**Unique across the whole registry**, unlike `user_id` and the member key, which are unique
per community. That rests on a domain assumption stated as one: a person cannot be a member
of two RECs, because the same supply point settled twice is double billing.

### `member.type` — participant entity type

schema.org type CURIE. Aligns with Italian Decreto 199/2021 member categories:

| Value | Meaning |
|---|---|
| `schema:Person` | Private citizen / household |
| `schema:GovernmentOrganization` | Public administration |
| `schema:LocalBusiness` | SME, commercial entity |
| `schema:Organization` | Generic organization |

### `member.delivery_points`

| Field | Description |
|---|---|
| `id` | DSO-assigned identifier (POD IT221E…). In dev environments use an alias (IT000000000001). |
| `type` | `pod` \| `cups` \| `prm` \| `malo` \| `ean` \| `mpan` \| `other` |
| `description` | Free-text description |
| `active` | Boolean (default `true`) |

### `member.assets`

Assets are organized by type. Each type is a dict keyed by a stable asset ID.

#### `assets.meter` — required for metered members

| Field | Required | Description |
|---|---|---|
| `name` | yes | Display name |
| `sensor_id` | yes | CELINE data pipeline sensor identifier (e.g. `ex-sensor-0001`) |
| `meter_type` | yes | `consumption` \| `production` \| `bidirectional` \| `import` \| `export` |
| `pod` | no | Reference to delivery point `id` |
| `device` | no | Device specification (type, model, serial\_number, mac\_address) |
| `relationships.measures` | no | Asset IDs measured by this meter |

#### `assets.pv`

| Field | Description |
|---|---|
| `name` | Display name |
| `rated_power` | Peak power in kWp |
| `panel_type` | `monocrystalline` \| `polycrystalline` \| `thin_film` \| `bifacial` |
| `inverter_power` | Inverter output in kW |
| `orientation` | Azimuth in degrees (0=N, 180=S) |
| `tilt_angle` | Tilt from horizontal in degrees |
| `relationships.measures` | Meter asset IDs that measure this PV |

#### `assets.storage`

| Field | Description |
|---|---|
| `name` | Display name |
| `capacity` | Total capacity in kWh |
| `max_charge_power` | Maximum charge power in kW |
| `max_discharge_power` | Maximum discharge power in kW |
| `battery_type` | `lithium_ion` \| `lfp` \| `lead_acid` \| `flow_battery` \| `sodium_ion` \| `solid_state` \| `other` |
| `round_trip_efficiency` | Round-trip efficiency % |

#### `assets.ev_charger`

| Field | Description |
|---|---|
| `max_power` | Max charging power in kW |
| `charger_type` | `ac_level1` \| `ac_level2` \| `dc_fast` \| `dc_ultra_fast` |
| `connector_types` | List: `type2`, `ccs2`, `chademo`, etc. |
| `smart_charging` | Boolean |
| `bidirectional` | Boolean (V2G support) |

#### `assets.heat_pump`

| Field | Description |
|---|---|
| `thermal_power` | Nominal thermal output in kW |
| `electrical_power` | Nominal electrical input in kW |
| `cop` / `scop` | Coefficient of Performance / Seasonal COP |
| `eer` / `seer` | Energy Efficiency Ratio / Seasonal EER |
| `heat_pump_type` | `air_to_air` \| `air_to_water` \| `ground_source` \| `water_source` |

#### `assets.load`

| Field | Description |
|---|---|
| `load_type` | `hvac` \| `lighting` \| `appliance` \| `industrial` \| `process` \| `refrigeration` \| `pumping` \| `other` |
| `rated_power` | Nominal consumption in kW |
| `controllable` | Boolean — demand response eligible |
| `priority` | `critical` \| `high` \| `medium` \| `low` |
| `flexibility_kw` | Flexibility potential in kW |

---

## Changes from v0.6

| Change | Detail |
|---|---|
| `area.boundary` added, required | `{source: gse_cabine_primarie, id: <cod_ac>}`: the primary-substation boundary the area is |
| `area.topology` required, exactly one item | The one node is a `primary_substation` whose id equals `boundary.id` |
| One area per substation | No two areas of one community reference the same `boundary.id` |
| `community.areas` optional, may be empty | Required with at least one area since v0.5; an administrative-only bundle now validates. The importer never required it |

**A v0.6 file with areas is not a valid v0.7 file**: none of its areas carries a boundary, and an area may list several nodes. The import refuses it on content, whatever version it declares, and there is no compatibility branch: an old file is reshaped outside the product before it restores. A file with no areas — `areas` absent or `{}` — is a valid v0.7 one (it was never a valid v0.5 or v0.6 one, which required at least one area, though the importer accepted it). The v0.4 note below that removed the "exactly one primary substation" constraint is reversed here, per area rather than per community: a community may still span several substations, one area each.

## Changes from v0.5

| Change | Detail |
|---|---|
| `member.did` added | Dataspace decentralised identifier. Optional, nullable, unique registry-wide. Backed by a unique index on `member.did`, which permits any number of members holding none |
| `member.user_id` described correctly | The description said *"External identity system identifier (e.g., Keycloak UUID)"*, naming the one value the field cannot hold. It is a Keycloak **username**; a row written with a subject UUID exports cleanly and locks its owner out |

**A v0.5 file is a valid v0.6 file.** Nothing was removed or made required, so this is
additive — unlike v0.4 → v0.5, which dropped `area.location` and `topology[].dso`. Import
does not gate on the declared version in any case (it reports and proceeds), but the shape
is genuinely compatible in this direction.

## Changes from v0.4

| Change | Detail |
|---|---|
| `community.operators` added | Dict of grid operators keyed by ID, referenced by topology nodes and `owners.yaml` |
| `area.location` removed | Centroid coordinates dropped — areas are identified by topology node reference |
| `area.topology` added | List of topology node IDs bridging regulatory areas to the CIM grid layer |
| `topology[].operator` | Changed from free string to ID reference into `community.operators` |
| `topology[].dso` removed | Superseded by `operator` |
| `member.type` added | schema.org participant entity type (schema:Person, schema:GovernmentOrganization, schema:LocalBusiness, …) |
| Multi-PS communities | "Exactly one primary substation" constraint removed — communities may span multiple primary substation areas |
