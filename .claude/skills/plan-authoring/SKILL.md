---
name: plan-authoring
description: Stage 3 of the delivery workflow (docs/workflow/README.md). Turn a frozen EARS spec into a code plan at docs/workflow/wN/plan.md — the design the drift gate checks against the spec and the implementation follows. Use when a week's spec is frozen and the user says "start plan", "plan stage", enters plan mode for a workflow item, or invokes /plan-authoring.
---

# Code plan authoring

Input: `docs/workflow/wN/spec.md` with `Status: AGREED` (frozen). Refuse to start from a
DRAFT — the spec changes only through stage 2 by explicit owner decision.
Output: `docs/workflow/wN/plan.md`, `Status: DRAFT`, ready for the drift gate. This stage
produces **design, not code** — which files change, what each change is, and why; code
snippets only where the exact content is load-bearing (a probe command, a config block,
a route body short enough to be the spec of itself).

## Process

1. **Read the spec and the requirements** — especially the requirements' **out-of-scope
   section**: it is carried into the plan verbatim, not rediscovered. Find that section by
   its heading, never by a section number: `.claude/skills/requirement-synthesis/` owns the
   requirements document's numbering and it moves per item (an item that adds a deferrals
   or decisions section pushes out-of-scope down — it is §7 in `docs/workflow/e4/`, §6 in
   `w1`–`w3`, `e1` and `e2`). Cite the number you actually found in the heading below.
2. **Verify every factual claim in-repo before writing it.** Every file path, line
   reference, exported symbol, port, version, and config value in the plan is read from
   the working tree this session — never from memory or convention. A plan whose facts
   are wrong fails at the gate or, worse, at implementation.
3. **Record plan-stage decisions at the top**, each owner-confirmed and dated. The plan is
   where implementation choices land (tool, path, naming); the spec stays free of them.
4. **Draft per the template**, then run the three checks below before showing the owner.
5. **Owner reviews; plan goes to the gate.** Structural review findings during
   implementation come back to this stage (spec unchanged) per the pipeline.

## Optional input: spec-anchored mockup

Where the item's spec names the portal as a system element, a static mockup
(`.claude/skills/mockup/`) may inform this stage. The mockup is evidence, not contract —
it stays scratch (untracked), and what it teaches lands here as text: plan-stage
decisions and per-SPEC changes. Items with no UI surface skip this entirely.

## Revision after a gate round

When the gate returns the plan, the findings are the latest round in the `## Gate`
section of `docs/workflow/wN/findings.md` (other sections belong to other stages — do not
count their rounds) — the round log is the handoff, not chat history or
session memory. Address every finding and fill its disposition cell (what changed, or
the recorded owner decision where one overruled a finding or accepted it as residual),
re-run the three checks, and leave the plan at `Status: DRAFT` for a full fresh-session
re-gate. The round-3 escalation rule lives in `.claude/skills/drift-gate/`.

## Three checks (lessons of e1)

Run these against the finished draft; each has caught a real gap.

- **Self-consistency:** the plan's own new artifacts must pass the plan's own new gates.
  Walk every proposed check over every file the plan adds. (e1: the seed test would have
  failed the new `tsc --noEmit` gate — vitest globals had no types.)
- **Gate interaction:** existing pipeline steps may already partially enforce a new gate.
  Name the interaction and its ordering/attribution consequences. (e1: `next build`
  type-checks, and lints once an eslint config exists — legacy violations would redden
  the build step before the dedicated gate steps.)
- **Residual honesty:** where a change satisfies a SPEC only partially, name the accepted
  residual in Landmines/risk — never let a scope map row imply full coverage it doesn't
  have. (e1: a status-only `/healthz` can answer 200 while pages break at runtime;
  SPEC-11 residual, accepted and written down.)

## Plan rules

- **Scope map closes both ways:** every SPEC id appears in the map; every change traces
  to a SPEC or is named registry upkeep (CLAUDE.md self-correction, TODO status).
- **Verification is numbered, end-to-end, SPEC-cited**, and includes negative checks —
  break the thing, watch the gate go red, revert.
- **Landmines section is required:** name the `docs/landmines.md` §1 zones touched or
  "none touched"; deliberate defects are preserved — suppress-with-citation, never fix.
- **Version caveats noted:** a tool deprecated beyond the pinned version is future churn
  to record, not silent debt.
- Exemplar: `docs/workflow/e1/plan.md`.

## Template

```markdown
# W<N> Code Plan — <short name>

> Status: DRAFT | GATED <date>
> Plan maturity only. The plan header never carries delivery state (IMPLEMENTED, pushed,
> merged) — that lives in `docs/workflow/w<N>/pr-body.md`. The impl gate does not touch
> this header.
> Workflow stage 3 (code plan). Anchors to the frozen spec `docs/workflow/w<N>/spec.md`
> (W<N>-SPEC-1..<n>). Requirements: `docs/workflow/w<N>/requirements.md` (AGREED <date>).

## Context

<why this change, what gap it closes, what it must not touch. Cite debt IDs/TODOs.>

**Decisions carried into this plan** (plan-stage, owner-confirmed <date>):
- <decision — one line each>

## Scope map (spec → change)

| SPEC | Change |
|------|--------|
| W<N>-SPEC-1..2 | <change> |

## Implementation

### <n>. <change name> (W<N>-REQ-x / SPEC-y..z)

<design; load-bearing snippets only>

## Files touched

| File | Change |
|------|--------|

## Out of scope (from requirements §<n>)

<carried verbatim. §<n> is the number the out-of-scope heading actually carries in THIS
item's requirements — read it, do not assume 6.>

## Verification (end-to-end)

1. <step, cites SPEC ids, includes break-then-revert negative checks>

## Landmines / risk

- <§1 zones touched or "none touched"; defects preserved; accepted residuals; PR-body line>
```
