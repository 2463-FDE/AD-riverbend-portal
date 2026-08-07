---
name: spec-authoring
description: Stage 2 of the delivery workflow (docs/workflow/README.md). Turn an AGREED requirements document into an EARS spec at docs/workflow/wN/spec.md — the frozen contract the drift gate and review anchor against. Use when a week's requirements are agreed and the user says "start spec", "spec stage", or invokes /spec-authoring.
---

# Spec authoring (EARS)

Input: `docs/workflow/wN/requirements.md` with `Status: AGREED`. Refuse to start from a
DRAFT — requirements change through their own stage, not here.
Output: `docs/workflow/wN/spec.md`, agreed with the owner, then **frozen**. It changes only
by explicit human decision (`docs/workflow/README.md`). This stage produces **behavior
contracts, not design** — no file paths, no module names, no implementation choices (that
is the plan stage).

## Process

1. **Read the agreed requirements.** Every `WN-REQ-n` must be covered; nothing outside
   them may be specified. Scope grows only by going back to stage 1.
2. **Write EARS statements** (`WN-SPEC-n`, allocated once, never renumbered). One
   requirement usually yields several statements: the normal path, the unwanted-behavior
   paths, and any state-dependent behavior.
3. **Build the traceability table** — both directions must close: every REQ maps to ≥1
   SPEC; every SPEC maps to exactly one REQ.
4. **Carry gates forward.** A `⚠ human-gate` on a requirement marks every SPEC derived
   from it. PHI/authz/sanitization behavior inherits the `docs/landmines.md` §3
   negative-test rule — say so in the statement's Notes, don't restate the rule.
5. **Ask the owner the open questions**, fold answers in, and stop at agreement. Owner
   marks AGREED; the spec is then the frozen contract and the plan stage may start.

## EARS patterns

Use the smallest pattern that fits; name the system element precisely.

- **Ubiquitous:** The `<element>` shall `<response>`.
- **Event-driven:** When `<trigger>`, the `<element>` shall `<response>`.
- **State-driven:** While `<state>`, the `<element>` shall `<response>`.
- **Unwanted behavior:** If `<condition>`, then the `<element>` shall `<response>`.
- **Optional feature:** Where `<feature>`, the `<element>` shall `<response>`.

Rules: one behavior per statement; every statement independently verifiable; configured
values named as configuration (`a configured <thing>`), not as numbers — numbers are plan
or implementation detail unless the requirement itself fixed one.

## Template

```markdown
# W<N> Spec (EARS)

> Status: DRAFT | AGREED <date> (frozen)
> Source: docs/workflow/w<N>/requirements.md (AGREED <date>)

## 1. Statements

### W<N>-REQ-<n> — <requirement short name>

| ID | Statement | Notes |
|----|-----------|-------|
| W<N>-SPEC-<n> | <EARS statement> | <⚠ human-gate / negative-test note if inherited> |

## 2. Traceability

| REQ | SPECs |
|-----|-------|
| W<N>-REQ-1 | W<N>-SPEC-1, W<N>-SPEC-2 |

## 3. Open questions

<numbered; delete section when empty at agreement>
```
