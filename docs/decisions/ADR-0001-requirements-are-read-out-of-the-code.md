# ADR-0001 — the requirements are read out of the code, and say what it does today

**Date:** 2026-08-15
**Status:** accepted

## Context

This repository had 114 tests and five documents describing what the service *is* — the
data model, the endpoint list, the bundle format — and **no statement of what it must
do**. Nothing carried an identifier, so no test could name anything, so nothing anywhere
answered *"is this behaviour verified?"*.

The gap mattered more here than it would in most of the workspace. Six repositories read
this registry and none of their suites runs against it, so a wrong row here is wrong
everywhere and nothing downstream can tell. The invariants that keep the rows right — no
write reduces a sibling, absent never means empty, deactivating is not erasing — were held
by convention, by prose in `.agents/knowledge/`, and by two named test classes an author
had to already know to look for.

Writing requirements needs something to state. The only statement of intent available was
the code: the people who could say what was *intended* are not the ones reading it, and
several of the values in question — the 500-id batch bound, the default member key
`member-00001` and its five-digit padding — look chosen by whoever typed them rather than
decided.

Waiting for that conversation would have left the situation as it was, which is the one
thing that was already known to be inadequate.

## Decision

Distil the requirements from the code, and state **what it does**, not what it should do.

- Every `REQ-####` in `docs/specifications/` is something the service does today.
- Where the behaviour is a defect, the requirement still describes the behaviour, names
  the issue, and says it is a defect. It does not describe the fix, and its test asserts
  the **mismatch** so that closing the defect turns the test red deliberately.
- Where the current value is arbitrary rather than chosen — the batch bound, the default
  key format — the requirement says so, so that changing it later is a decision rather
  than a regression.
- Where a surface is unverified, it is named as unverified in
  `docs/specifications/index.md` rather than given a requirement nothing checks.

Requirements that would need a product answer are not invented. The identifier scheme is
the harness default, `REQ-####`, with no repository prefix.

## Consequences

**A requirement can be wrong in a way a test cannot catch.** The suite proves the service
does what the document says; nothing proves the document says what anyone wanted. A reader
must not take REQ-0045's bound of 500 as evidence that 500 was chosen.

**Two requirements describe defects** — REQ-0043 and the pair REQ-0018/REQ-0058. Each is a
place where a passing suite is *not* an argument that the behaviour is right.

**The temptation is to quietly "fix" the requirement** when the behaviour is embarrassing —
to write what the code was obviously meant to do. That produces a document that reads well
and a matrix reporting coverage for something nobody verified, which is worse than having
neither, because the matrix is what a reviewer trusts instead of reading the code.

**Distilling found things.** Three defects' worth of drift, and several traps now recorded
in `.agents/knowledge/`, surfaced only because writing a requirement forces a claim to be
either true or false. That is an argument for doing this earlier elsewhere, not an argument
that this repository was unusually bad.

When the product conversation happens, the requirements it settles supersede these, and the
change is visible as a diff against a statement of what the code used to do.
