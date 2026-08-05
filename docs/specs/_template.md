# Spec template

> Copy to `docs/specs/<name>.md`. Delete the guidance blockquotes.
>
> **Why requirement IDs exist.** `address-review`'s design gate stops when a proposed fix
> "maps to no spec requirement ID." Without stable IDs, every review round re-argues whether
> a fix is in scope. IDs make that a lookup instead of a debate. They are also the traceability
> spine: requirement → debt ID (`docs/debt-log.md`) → the test that proves it.

---

## 0. ID scheme

`<PREFIX>-R<n>`, allocated once and **never renumbered or reused.** A withdrawn requirement
stays in the table marked `WITHDRAWN` with a one-line reason; a changed requirement keeps its
ID and records the change. Prefix is short and spec-scoped (`W4`, `FE`, …).

## 1. Context / client ask

> Verbatim client ask if there is one (`docs/handover/jira-tickets.md`), else who asked and why.
> No solutioning here.

## 2. Scope

**In scope:** …
**Out of scope:** … (name the adjacent thing someone will try to pull in, and why it is out)

## 3. Definitions

> Only terms whose ambiguity would change the work. Domain terms (BFF, ROI, HL7/ADT/ORU/PID/PV1,
> MPI, PHI, 45 CFR 164.508, X12 270/271) are defined where they are used — `ARCHITECTURE.md` and
> `docs/landmines.md` carry the load-bearing ones.

## 4. Deliverables

> Artifacts that must exist for "Done". Files, ADRs, docs — things reviewable in a PR.

## 5. Requirements (EARS)

> **EARS** — Easy Approach to Requirements Syntax. One requirement per row, one behaviour each,
> written so a reader can say whether it holds. Use the narrowest pattern that fits:
>
> | Pattern | Form |
> |---|---|
> | Ubiquitous | The `<system>` shall `<response>`. |
> | Event-driven | **WHEN** `<trigger>`, the `<system>` shall `<response>`. |
> | State-driven | **WHILE** `<state>`, the `<system>` shall `<response>`. |
> | Unwanted behaviour | **IF** `<trigger>`, **THEN** the `<system>` shall `<response>`. |
> | Optional feature | **WHERE** `<feature is included>`, the `<system>` shall `<response>`. |
>
> Rules that earn their keep here:
> - **"Shall", never "should"/"may".** A requirement is not a preference.
> - **One behaviour per ID.** Two `shall`s joined by "and" is two requirements, and a review
>   round will only half-satisfy it.
> - **No solution nouns** unless the solution *is* the requirement. Say what must be true.
> - **Safety requirements use the IF/THEN pattern.** The unwanted-behaviour form is the one that
>   catches fail-open defects, which is where this repo's regressions live
>   (`docs/landmines.md` §3).
> - **Every requirement names its verification.** A requirement no test or documented repro can
>   settle is a wish. "Reviewed by inspection" is allowed, but say so explicitly.

| ID | Requirement | Verification | Debt | Gate |
|---|---|---|---|---|
| `X-R1` | WHEN …, the portal shall … | `tests/test_….py::…` | D4 | G1 |

## 6. Checkpoints / gates

> A gate is a named stop with an **artifact**, a **verification method**, and a **who signs**.
> Phases without a gate silently merge into each other. Mark which gates block a merge
> (`docs/landmines.md` §1 approval-gated changes always do).

| Gate | Blocks | Artifact | Verified how | Signed by |
|---|---|---|---|---|

## 7. Relevant landmines

> Copy the applicable `docs/landmines.md` §1 entries. Do not paraphrase them into something
> softer.

## 8. Open decisions

> Decisions this spec deliberately does NOT make, each with what unblocks it. An open decision
> recorded here is in scope to *decide*; an unrecorded one becomes a mid-PR scope fight.

| # | Decision | Blocks | Unblocked by |
|---|---|---|---|

## 9. Traceability

> requirement → debt ID → test. Where a requirement maps to no debt ID, say why (new scope,
> not a documented gap).
