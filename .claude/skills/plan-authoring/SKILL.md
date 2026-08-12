---
name: plan-authoring
description: Stage 3 of the delivery workflow (docs/workflow/README.md). Turn a frozen EARS spec into the Plan section of docs/workflow/<item>.md — the design the drift gate checks against the spec and the implementation follows. Use when an item's spec is frozen and the user says "start plan", "plan stage", enters plan mode for a workflow item, or invokes /plan-authoring.
---

# Code plan authoring

Input: `docs/workflow/<item>.md` with `## Spec` at `Status: FROZEN`. Refuse to start from
a DRAFT — the spec changes only through stage 2 by explicit owner decision.
Output: the `## Plan` section at `Status: DRAFT`, ready for the drift gate.

**The plan is deltas only — nothing the diff will show.** Its contents, in full:

- plan-stage decisions, entered `plan`-tagged in the item's `## Decisions` register and
  cited by ID from here — one line each, owner-confirmed, dated;
- a file-level change list (`Changes:` — file, one clause on what changes and which
  SPEC/REQ it serves);
- **Verification as runnable commands with expected output**, numbered, SPEC-cited,
  including negative (break-then-revert) checks;
- the **Landmines block** (below).

No narrative, no quoted code, no embedded DDL — the diff is the DDL. A code snippet is
justified only where the exact content is load-bearing and nothing else can carry it (a
probe command, a config block that is the spec of itself).

## The Landmines block — verbatim, never compressed

The one deliberate exception to deltas-only: the landmine-approval block is written as
full prose and is never compressed, summarized, or replaced by a citation. It names each
`docs/landmines.md` §1 zone the change enters (or states "none touched"), which owner act
approved the entry (cited by decision ID and date), that deliberate defects in reach are
preserved, and any accepted residuals. This is the graded surface; the gates check it and
the PR body's "Risk & landmines" section is drafted from it.

## Process

1. **Read the spec and requirements sections** — same file, including out-of-scope, which
   the plan respects and cites but does not copy.
2. **Verify every factual claim in-repo before writing it.** Every file path, line
   reference, exported symbol, port, version, and config value is read from the working
   tree this session — never from memory or convention. A plan whose facts are wrong
   fails at the gate or, worse, at implementation.
3. **Fill the spec's planned test names** where planning sharpens them; the check column
   is the test list — the plan does not restate it.
4. **Run the three checks** (below), then show the owner; the plan goes to the gate.

## Optional input: spec-anchored mockup

Where the spec names the portal as a system element, a static mockup
(`.claude/skills/mockup/`) may inform this stage. The mockup is evidence, not contract —
it stays scratch (untracked); what it teaches lands as `plan`-tagged decisions.

## Revision after a gate round

Findings arrive as the latest `### Gate — round N` in `## Findings` — the round log is
the handoff, not chat history. Address every finding, fill its disposition cell citing
the decision register where a decision resolves it (never re-argue in the cell), re-run
the three checks, and leave the plan at `Status: DRAFT` for a full fresh-session re-gate.
The round-3 escalation rule lives in `.claude/skills/drift-gate/`.

## Three checks (lessons of e1)

- **Self-consistency:** the plan's own new artifacts must pass the plan's own new gates.
  Walk every proposed check over every file the plan adds.
- **Gate interaction:** existing pipeline steps may already partially enforce a new gate.
  Name the interaction and its ordering/attribution consequences.
- **Residual honesty:** where a change satisfies a SPEC only partially, the residual is
  named in the Landmines block — never let a change row imply full coverage it doesn't
  have.

## Template (the section)

```markdown
## Plan

Status: DRAFT | GATED <date>

Changes (file level):
- `<path>` — <what and why, one clause> (<item>-SPEC-n / <item>-D-n)

Landmine approvals (verbatim, never compressed):
- <full prose per the rule above, or "none touched">

Verification (runnable, expected output stated):
1. `<command>` → <expected> (<item>-SPEC-n)
2. break-then-revert: <break> → <check red>; revert → green
```
