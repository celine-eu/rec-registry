# ADR-0008 — a refusal carries a machine-readable code beside its message

**Date:** 2026-09-27
**Status:** accepted

## Context

Every `4xx` the registry writes is `{"detail": "<a sentence>"}`. That was enough while the only
readers were people at a terminal. It is not enough for a dashboard that has to tell a manager
*"this meter is already attached to another member"* in three languages, or for onboarding,
which has to tell *"that area is still in use"* apart from *"that area does not exist"* to decide
what to do next. Parsing the sentence would make its wording an API, which no one would know
they were changing.

## Decision

- **A refusal a caller is expected to act on carries a `code`** beside the existing `detail`:
  `{"detail": "<human-readable sentence>", "code": "<code>"}`. `detail` stays a string with its
  current meaning — never an object carrying the code — so a client that reads only `detail`
  is unaffected.
- **The codes are a closed vocabulary, listed in the requirements** (REQ-0073). A code is added
  by the requirement that introduces the refusal, never ad hoc in a handler.
- **A code names the rule broken, not the entity or the person**, and carries no identifier of
  its own. What the message may name follows the rule that already governs it — within the
  addressed community, never outside it (REQ-0060).
- **Codes are `snake_case` and stable.** Renaming one is a breaking change of the API, and the
  SDK regenerates on it.

## Consequences

**The SDK reads `code`, not the sentence**, and surfaces it so consumers branch on it; the
sentence stays for people.

**Refusals without a code remain** — the framework's own validation errors, and every refusal
nobody has had to act on programmatically yet. Those gain a code when a requirement needs one.

**The temptation is to put data in the code** (`sensor_held:<key>`). Data belongs in the
message, under the disclosure rule the message already follows; a code is only a name.
