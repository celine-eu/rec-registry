# Decisions

Architecture decision records: **why a technical choice was made here**, when the reason
is not derivable from the code and would otherwise be re-litigated.

One file per decision, named `ADR-####-short-slug.md`, with this shape:

```markdown
# ADR-0001 — <the decision, as a statement>

**Date:** <ISO-8601>
**Status:** accepted | superseded by ADR-#### | accepted; amended by ADR-####

## Context
<what forced a choice. The constraint, and what had already been tried.>

## Decision
<what was decided, in the imperative.>

## Consequences
<what this costs, what it forecloses, and what will tempt someone to undo it.>
```

## What is not an ADR

- **A requirement.** What the product must do belongs with the requirements, where it can
  be traced to a test. An ADR is measured by nothing.
- **A rule with a referent that something already measures.** If a statement could carry
  an identifier and a test that names it, put it where that measurement happens. Deciding
  it here hides it from the report.
- **A procedure.** That is a playbook, and playbooks live in the companion.
- **A fact about the code.** That is knowledge, and knowledge lives in the companion.

An ADR is immutable once accepted. It is superseded by a later ADR that names it, never
edited to say something else.

## The records

| | |
|---|---|
| [ADR-0001](ADR-0001-requirements-are-read-out-of-the-code.md) | the requirements are read out of the code, and say what it does today |
| [ADR-0002](ADR-0002-requirements-may-be-written-ahead-of-the-code-marked-planned.md) | requirements may be written ahead of the code, marked `planned` |
| [ADR-0003](ADR-0003-role-and-area-have-their-own-route-and-action.md) | role and area are written through their own route and action, and no caller-supplied id can change an action |
| [ADR-0004](ADR-0004-a-sensor-has-one-active-holder-and-detaching-deletes-the-meter.md) | a sensor id has one active holder across the registry, and detaching a meter deletes it |
| [ADR-0005](ADR-0005-an-area-is-one-gse-primary-substation.md) | an area is one GSE primary substation, referenced by id and never stored as a shape |
| [ADR-0006](ADR-0006-onboarding-templates-are-the-source-of-truth-for-areas.md) | onboarding templates are the source of truth for areas, written through the area and topology routes |
| [ADR-0007](ADR-0007-import-refuses-a-bundle-that-breaks-an-invariant.md) | import refuses a bundle that breaks an invariant, and old backups are reshaped rather than tolerated |
| [ADR-0008](ADR-0008-a-refusal-carries-a-machine-readable-code.md) | a refusal carries a machine-readable code beside its message |
| [ADR-0009](ADR-0009-a-community-is-retired-by-a-forced-empty-import.md) | a community is retired by a forced import with no members, and members arrive only through onboarding |
| [ADR-0010](ADR-0010-an-area-is-renamed-with-its-members-in-one-write.md) | an area is renamed with its members in one write, under the community's lock |
| [ADR-0011](ADR-0011-member-writes-are-granted-per-field.md) | a member's fields are written through per-field routes, each with its own grant |
| [ADR-0012](ADR-0012-a-delivery-point-has-one-active-holder-and-is-corrected-in-one-write.md) | a delivery point has one active holder across the registry, and is corrected in one write |
| [ADR-0013](ADR-0013-duplicate-delivery-points-are-reported-to-the-operator.md) | delivery points already held twice are reported to the operator, as sensors are |
