---
name: plan-authoring
description: Stage 3 of the delivery workflow (docs/workflow/README.md). Turn a frozen EARS spec into the Plan section of the item's plan file docs/workflow/plans/<item>.md — or, for a ticketed item, one ticket plan file docs/workflow/plans/<item>/<ticket>.md per ticket — the design the drift gate checks against the spec and the implementation follows. Use when an item's spec is frozen and the user says "start plan", "plan stage", enters plan mode for a workflow item, or invokes /plan-authoring.
---

# Code plan authoring

Input: the contract file `docs/workflow/<item>.md` with `## Spec` at `Status: FROZEN`.
Refuse to start from a DRAFT — the spec changes only through stage 2 by explicit owner
decision.
Output: the `## Plan` section of the plan file `docs/workflow/plans/<item>.md` at
`Status: DRAFT` (contract header `Status:` advanced in the same edit — ticketed: the
ticket file's `Status:` line and the `plan` cell of its ticket row instead, README),
ready for the drift gate. **Ticketed item** (README Tickets rule): this stage decides the split as a
`plan`-tagged decision, creates one ticket file `docs/workflow/plans/<item>/<ticket>.md`
per ticket (template below) and the ticket table in the contract's `## Delivery`; each
ticket's `## Plan` goes to its own gate, and the ticket's `Status:` line + ticket row
(columns and legal values: README, Tickets rule) take the place of the contract header
for the plan and delivery axes. Every frozen SPEC
row lands in exactly one ticket's `Scope:` line (a ticket whose rows are not yet frozen
is a table row, not a file).

**The plan is deltas only — nothing the diff will show.** Its contents, in full:

- plan-stage decisions, entered `plan`-tagged in the item's `## Decisions` register
  (same file) and cited by ID from here — one line each, owner-confirmed, dated;
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

1. **Read the spec and requirements sections** — in the contract file, including
   out-of-scope, which the plan respects and cites but does not copy.
2. **Verify every factual claim before writing it, and write the locator with it (the
   fact trail).** Every file path, line reference, exported symbol, port, version, config
   value, count, size, split and enum membership is read from the working tree or the
   client package this session — never from memory or convention — and the sentence that
   states it carries where it was read: `path:line` for a tree fact, the command and its
   output for a computed fact, the package path for a client-package fact. **A claim
   without a locator is not writable.** The gate reads the locator first and the claim
   second: a locator that does not say what the claim says is a wrong-fact finding, and a
   missing locator is a finding on its own. This is the plan-side twin of the gate agent's
   `checked:` trail — the 2026-08-27 lesson (eligibility-assistant `corpus` / `llm-seam`,
   three rounds each): every substantive finding across six rounds was a tree or package
   fact the plan asserted and the gate re-derived.
3. **Fill the spec's planned test names** where planning sharpens them; the check column
   is the test list — the plan does not restate it.
4. **Run the four checks** (below), then show the owner; the plan goes to the gate.
   After the gate stamps `GATED`, the files land via `noncode-merge` (README landing
   rule).

## Optional input: spec-anchored mockup

Where the spec names the portal as a system element, a static mockup
(`.claude/skills/mockup/`) may inform this stage. The mockup is evidence, not contract —
it stays scratch (untracked); what it teaches lands as `plan`-tagged decisions.

## Revision after a gate round

Findings arrive as the latest `### Gate — round N` in the plan file's `## Findings`
(the ticket file's, for a ticketed item) — the round log is
the handoff, not chat history. Address every finding, fill its disposition cell citing
the decision register where a decision resolves it (never re-argue in the cell), re-run
the four checks, and leave the plan at `Status: DRAFT` for a full fresh-session re-gate.
**A disposition is a plan.** One that adds or changes a mechanism — a test, a cap, a pin,
a constant, a change row — is written under the fact-trail rule (step 2) and walks the
four checks over the fix before the plan goes back, the self-consistency check first: the
plan's own new artifact must do what the disposition says it does (2026-08-27 lesson — the
round-2 fixes on both eligibility-assistant tickets were the round-3 substantive findings).
**Every disposition cell that changes text ends in a `Sites changed:` list** — file and
row / section / decision ID for each edit the disposition made, including edits to sibling
ticket files and the decision register. This list, with the plan-text hash the gate
records in its `checked:` line, is the durable basis the next gate derives its origin
tags from (`.claude/agents/drift-gate-agent.md`); a disposition without it makes every
finding of the next round `new` by rule.
When a finding repeats a class an earlier round already dispositioned, close the class,
not the instance: run the sweep for further sites of the same class and **enumerate the
sites checked in the disposition cell** — file and row, each with its outcome — never a
scope phrase ("every clause of every row"); a scope phrase is a declared sweep, not a run
one (the drift-gate skill holds the matching round rule).
The round-3 escalation rule lives in `.claude/skills/drift-gate/`.

## Four checks (lessons of e1 and e6)

- **Self-consistency:** the plan's own new artifacts must pass the plan's own new gates.
  Walk every proposed check over every file the plan adds.
- **Gate interaction:** existing pipeline steps may already partially enforce a new gate.
  Name the interaction and its ordering/attribution consequences.
- **Residual honesty:** where a change satisfies a SPEC only partially, the residual is
  named in the Landmines block — never let a change row imply full coverage it doesn't
  have.
- **Falsified-claims sweep:** for every behavior the plan changes, grep the claim
  registries for statements the diff will falsify: `docs/landmines.md`,
  `docs/debt-log.md`, the `docs/phi-logging-policy.md` register, `docs/todo.md`,
  `CLAUDE.md`, `ARCHITECTURE.md` §7, `docs/runbook.md`, and in-code debt markers on or
  near the edited lines. Search by file path, route, and behavior name — stale line
  cites count. Every hit gets a change row scoped to the falsified clause (surviving
  claims stay verbatim, per the fix-wrong-claims rule in the `CLAUDE.md` preamble) or an
  explicit out-of-scope entry. The one exemption is `README.md` itself — its false
  claims are human-gated (TODO-12); the TODO-12 row in `docs/todo.md` is swept like any
  other. This check exists because e6 gate rounds 2–4 each found one missed registry of
  this class.

## Template (the section; a ticket file carries the three header lines first)

```markdown
# <item>/<ticket> — ticket plan file (deleted at its merge; contract: docs/workflow/<item>.md)

Scope: <item>-SPEC-n, <item>-SPEC-m, … (every row exactly one ticket)
Status: plan DRAFT

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
