# CELINE REC Registry Schema v0.6

JSON Schema for Renewable Energy Community (REC) registry manifests in the CELINE ecosystem.

---

## Purpose

A registry manifest is a single YAML file that provides the authoritative description of a REC: its identity, grid topology, participants, and their assets. It is used at ingestion time to populate the rec-registry database and drive interoperability across CELINE services (dataset-api, celine-policies, celine-pipelines).

---

## Top-level Structure

| Field | Required | Description |
|---|---|---|
| `version` | yes | Manifest format version (currently `"1.0"`) |
| `schema_version` | yes | Schema this file conforms to (`"0.6"`) |
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

Required fields: `id`, `name`, `areas`.

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

Dict keyed by operator ID. The key **must** match an `id` entry in `owners.yaml` so that the KC org provisioning pipeline (`sync-orgs`) can resolve it. Referenced by topology nodes via their `operator` field.

```yaml
operators:
  example-dso:
    name: Example Distribution Network Operator
    country: IT       # ISO 3166-1 alpha-2
    contact: ""       # optional email or URL
```

### `community.areas`

Dict keyed by area ID. Areas represent **regulatory coverage zones** — in the Italian context these correspond to GSE *cabine primarie* service areas that define virtual self-consumption eligibility under Decreto 199/2021. They are **not** a CIM concept.

| Field | Description |
|---|---|
| `name` | Area display name |
| `topology` | List of topology node IDs (from `community.topology`) that serve this area. Bridges the regulatory layer to the CIM grid layer. |

```yaml
areas:
  northern:
    name: northern
    topology:
      - "PS-example-001"
```

> A community may span multiple primary substation areas. There is no "exactly one primary substation" constraint.

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
  - id: "PS-example-001"
    type: primary_substation
    name: "Primary Substation Example"
    operator_id: example-dso

  - id: "SS-example-001"
    type: secondary_substation
    name: "Secondary Substation Example"
    parent: "PS-example-001"
    operator_id: example-dso
```

---

## `members`

Dict keyed by a stable member ID (e.g. `gl-00001`). Required fields: `user_id`, `name`, `role`, `area`, `status`.

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
  gl-00001:
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
| `sensor_id` | yes | CELINE data pipeline sensor identifier (e.g. `c2g-57CFBC3F0`) |
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
