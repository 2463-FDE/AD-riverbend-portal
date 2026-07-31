# Frontend rebuild — verification state

> **This file records only whether a human has verified something. It never restates a
> requirement.** The requirement text, its verification method, its debt link and its gate all
> live in `docs/specs/frontend-rebuild.md` §5/§6/§8 and are read from there (CLAUDE.md §10.1 —
> one instruction, one file). Consumed by `make status`.
>
> **Why this file has to exist:** most `FE-R*` requirements are verified by inspection, driven
> repro, ADR review or a copy checklist — there is nothing a script can resolve. If the dashboard
> only reported machine-checkable state it would read 1/26 forever and you would stop trusting it.
> So the human verdicts are recorded here, in the smallest possible surface, with who and when.

## Rules

- `state` — `open` · `in_progress` · `met` · `withdrawn`. Blocked-ness is **derived** from the
  gate order and is not a state you set here.
- `by` / `on` — who checked and when (`YYYY-MM-DD`). Required for `met`. An undated `met` is
  reported as unattributed.
- `test` — a `path::node` when a mechanical check exists. The generator resolves it. If the test
  is missing or the node cannot be found while `state: met`, the dashboard reports a **conflict**
  rather than letting the hand-set verdict quietly win.
- Never delete a row. Withdraw it.
- A gate row is the user's signature on that gate (`docs/specs/frontend-rebuild.md` §6, "Signed by").

## Requirement verdicts

| ID | State | By | On | Test | Note |
|---|---|---|---|---|---|
| FE-R1 | open | — | — | — | — |
| FE-R2 | open | — | — | — | frontend-side `detail`-body guard is satisfiable without the gateway half (spec §7) |
| FE-R3 | open | — | — | — | — |
| FE-R4 | open | — | — | — | — |
| FE-R5 | open | — | — | — | — |
| FE-R6 | open | — | — | — | `GET /patients?q=` already exists; no backend work needed |
| FE-R7 | open | — | — | — | — |
| FE-R8 | open | — | — | — | not satisfiable frontend-side alone — see spec §8 #9 (seed stores wrong instants) |
| FE-R9 | open | — | — | — | — |
| FE-R10 | open | — | — | — | — |
| FE-R11 | open | — | — | — | — |
| FE-R12 | open | — | — | — | — |
| FE-R13 | open | — | — | — | — |
| FE-R14 | open | — | — | — | G4, auth-approval gated |
| FE-R15 | open | — | — | — | — |
| FE-R16 | open | — | — | — | — |
| FE-R17 | open | — | — | — | — |
| FE-R18 | met | user | 2026-07-28 | — | `docs/design/01-operators-and-tasks.md` — six operator archetypes, evidence graded; reviewed and merged as PR #18 |
| FE-R19 | met | user | 2026-07-30 | — | `adr/0012-frontend-framework-sveltekit.md`; G1 signed same date. Stack also approved by the trainer in the client role, closing ADR 0012 gap #2 |
| FE-R20 | open | — | — | — | — |
| FE-R21 | open | — | — | — | — |
| FE-R22 | open | — | — | — | existing test must be re-proven to discriminate after the enum is widened |
| FE-R23 | open | — | — | — | — |
| FE-R24 | open | — | — | — | — |
| FE-R25 | open | — | — | — | — |
| FE-R26 | open | — | — | — | — |

## Gate signatures

| Gate | State | By | On | Note |
|---|---|---|---|---|
| G0 | met | user | 2026-07-30 | P0.1–P0.4 merged in PR #18; P0.5 tokens (direction F, `05-design-tokens.md`) written 2026-07-30. Signed with density and three other poll questions still unanswered (tokens §7, TODO-15) — the design set is accepted, those four are carried forward, not resolved |
| G1 | met | user | 2026-07-30, re-affirmed 2026-07-31 | `adr/0012-frontend-framework-sveltekit.md` — SvelteKit. Next.js scored as a genuine option and lost on `FE-R17` + form ergonomics, won continuity. Stack separately approved by the trainer in the client role, 2026-07-30. **Re-affirmed by the user 2026-07-31** after the audit-round amendment narrowed `FE-R17` from "interactive element" to "button or link" (`svelte-check` is silent on form-control names and defeated by spread attributes) and corrected the Alternatives row scoring it — so the original signature's `FE-R17` rationale above is narrower than written, and the decision stands on rules-on-by-default vs opt-in, form ergonomics across five forms, and continuity as one criterion against several. ADR stays `Proposed` until code lands |
| G2 | open | — | — | — |
| G3 | open | — | — | — |
| G4 | open | — | — | requires explicit human approval for an auth change (CLAUDE.md §6) |
| G5 | open | — | — | — |

## Phase artifacts

Resolved by file existence — do not hand-set these. `Gate` is the gate the step closes.

| Step | Gate | Artifact | Label |
|---|---|---|---|
| P0.1 | G0 | docs/design/01-operators-and-tasks.md | Operators and tasks |
| P0.2 | G0 | docs/design/02-information-architecture.md | Information architecture |
| P0.3 | G0 | docs/design/03-key-flows.md | Key flows |
| P0.4 | G0 | docs/design/04-wireframes.md | Wireframes |
| P0.5 | G0 | docs/design/05-design-tokens.md | Design tokens |
| P1 | G1 | adr/0012-frontend-framework-sveltekit.md | Framework ADR |
| P1b | G1 | adr/0013-frontend-test-harness.md | Test-harness ADR (written after the framework ADR) |
