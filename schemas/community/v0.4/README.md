# CELINE REC Registry Manifest (v0.4)

This repository defines the **CELINE REC Registry Manifest Schema (v0.3)**, a JSON Schema intended to validate registry manifests for **Renewable Energy Communities (RECs)** in the CELINE ecosystem.

The schema is aligned with the semantic model defined in `celine.v0.3.ttl` and is designed to validate **YAML manifests after YAML → JSON parsing**.

---

## Purpose

The registry manifest provides a **single, authoritative description** of a REC, including:

- Community metadata
- Participants and memberships
- Energy assets, meters, and sites
- Datasets, catalogs, and distributions
- Network topology and substations
- Tariffs and tariff assignments

It is used for:
- Validation at ingestion time
- Interoperability between CELINE services
- Semantic alignment with DCAT, CIM, and PECO vocabularies

---

## Schema Metadata

- **Schema draft**: JSON Schema Draft 2020-12
- **Schema ID**: `https://celine-eu.github.io/ontologies/schema/rec-registry.v0.3.schema.json`
- **Kind discriminator**: `celine.rec.registry.v0.3`

---

## Top-Level Structure

A valid manifest **MUST** contain the following top-level fields:

| Field | Description |
|------|-------------|
| `version` | Manifest version string |
| `kind` | Fixed value: `celine.rec.registry.v0.3` |
| `context` | Base IRI and prefix mappings |
| `community` | Energy community definition |
| `participants` | One or more participants |
| `memberships` | One or more memberships |

Optional sections include catalogs, datasets, topology, assets, meters, tariffs, and others.

---

## Context

The `context` section defines the semantic namespace of the manifest.

Required fields:
- `base_iri`: Base IRI for all generated resources
- `prefixes`: CURIE prefix → IRI mappings

This enables compact identifiers and RDF interoperability.

---

## Core Concepts

### Community

Represents the Renewable Energy Community.

Key properties:
- `key`: Stable registry identifier
- `type`: `celine:EnergyCommunity`
- `name`: Human-readable name
- `operator_participant`: Reference to the operating participant

Optional links to areas, catalogs, and datasets are supported.

---

### Participants

Participants are legal or natural persons involved in the community.

Supported kinds:
- `organization`
- `individual`
- `public_body`
- `aggregator`
- `other`

Each participant includes an `auth_uri` used as the identity anchor for IAM/SSO.

---

### Memberships

Memberships link participants to the community.

They define:
- Role (preferably a PECO role, e.g. `peco:Prosumer`)
- Status (`active`, `inactive`, `pending`, `suspended`)
- Optional validity period

---

## Data & Metadata (DCAT-aligned)

The schema reuses DCAT concepts:

- **Catalogs** (`dcat:Catalog`)
- **Datasets** (`dcat:Dataset`)
- **Distributions** (`dcat:Distribution`)

Datasets reference distributions by key and may include semantic hints such as:
- `modeled_as` (e.g. `sosa:ObservationCollection`)
- `purpose` (routing hint for consumers)

---

## Physical & Network Model

### Sites and Areas
Logical or geographical locations where assets and meters are installed.

### Assets
Community or participant-owned energy assets:
- PV
- Storage
- EVSE
- Loads

Assets may declare nominal power, capacity, and linked datasets.

### Meters
Measurement devices associated with assets, sites, or substations.

---

## Topology (CIM-aligned)

The optional `topology` section models grid structure:

- One **primary** substation
- Zero or more **secondary** substations

Each substation references a CIM `mRID` and may link to datasets.

> Constraint note: “exactly one primary substation” is enforced by service logic, not JSON Schema.

---

## Tariffs

Tariffs and assignments model economic conditions:

- Currency must follow ISO 4217 (e.g. `EUR`)
- Assignments define direction (consumption/injection), component, and validity window
- Price data may be linked via datasets

---

## Identifier Rules

All registry keys:
- Must be stable
- Must match: `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`
- Are used for cross-referencing within the manifest

---

## Validation Notes

- `additionalProperties` is set to `false` almost everywhere
- Unknown fields are rejected
- Structural consistency (e.g. referenced keys existing) is expected to be checked by services

---

## Usage

Typical workflow:

1. Author manifest in **YAML**
2. Convert YAML → JSON
3. Validate against this schema
4. Ingest into CELINE services

---

## Versioning

- This schema is **v0.3**
- Backward compatibility is **not guaranteed**
- Breaking changes will increment the minor version

---

## License

Part of the CELINE project. Refer to the project repository for licensing and contribution terms.
