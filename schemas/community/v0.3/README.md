# CELINE REC Registry Manifest (v0.3) — Field Guide

This document explains the example YAML manifest aligned to `celine.v0.3.ttl`.
The registry is a *manifest* (identities + references), not a data lake.

## Top-level fields

- `version`: manifest version (string).
- `kind`: document kind. For this profile: `celine.rec.registry.v0.3`.
- `context.base_iri`: used to mint URIs when missing.
- `context.prefixes`: CURIE prefix mapping used for human-friendly references.

## DCAT blocks (datasets)

- `catalogs[]` (`dcat:Catalog`): groups datasets; referenced from `community.catalogs`.
- `datasets[]` (`dcat:Dataset`):
  - `identifier` (required): stable dataset ID known by Dataset API.
  - `distributions` (required): one or more `dcat:Distribution` keys.
  - `modeled_as`: semantic hint IRI (e.g., `sosa:ObservationCollection`, `peco:Timeseries`).
  - `purpose`: lightweight routing tag (weather_observation, forecast, measurement, flex_constraints, etc.).
- `distributions[]` (`dcat:Distribution`):
  - `access_url` (required): API endpoint (or access URL).
  - `media_type`: content-type hint, optional.

## Community and governance

- `community` (`celine:EnergyCommunity`):
  - `key`, `uri`, `name`, `description`, `website`
  - `operator_participant`: participant key responsible for ops/representation
  - `areas[]`: coarse coverage areas
  - `catalogs[]`: keys referencing `catalogs`
  - `datasets[]`: keys referencing shared/community datasets
- `participants[]` (`celine:Participant`):
  - `auth_uri`: identity anchor in IAM/SSO (preferred over PII)
  - `external_ids`: reconciliation IDs (optional)
- `memberships[]` (`celine:Membership`):
  - `community`, `participant`
  - `role`: PECO role term (do not infer from assets)
  - `valid_from`, `valid_to`, `status`

## Sites, assets, meters

- `sites[]` (`celine:Site`): optional physical grouping.
- `assets[]` (`celine:Asset`):
  - `owner.kind` = participant | community; `owner.ref` is the key
  - `external_asset_uri`: pointer to authoritative asset service record
  - `datasets[]`: keys referencing `dcat:Dataset` used/produced by the asset
- `meters[]` (`celine:Meter`):
  - `pod`: the POD code (optional but common)
  - `sensor_id`: pipeline anchor for ingestion/time-series
  - `supplied_by_substation`: substation key
  - `datasets[]`: meter datasets (DCAT)

## Topology anchors (CIM)

- `topology.substations[]`:
  - `kind`: primary (mandatory) or secondary (optional)
  - `cim_ref.mrid`: CIM IdentifiedObject.mRID
  - `cim_ref.uri`: resolvable CIM resource URL (optional)
  - `datasets[]`: dataset keys relevant to that anchor (constraints/historical)

## Tariffs

- `tariffs[]` (`celine:Tariff`): tariff definitions (no tariff calculus here).
- `tariff_assignments[]` (`celine:TariffAssignment`):
  - `applies_to`: participant key(s) and/or meter key(s)
  - `tariff`: tariff key
  - `direction`: consumption | injection
  - `component`: retail_energy | network | incentive | other
  - `valid_from`, `valid_to`: contract validity windows
