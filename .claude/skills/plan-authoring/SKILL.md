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

**Fidelity: mechanism and test legs, not code.** A change row names what the mechanism
does; a test row names the legs that prove it. Neither spells how the code will be shaped —
no exception clauses (`try` / `except X`), no field list a fake or a record "carries", no
statement order inside a function, no branch structure. Those are stage-4 facts: a red test
proves or falsifies each in one run, and prose cannot be executed. Write "any parse or
comparison failure leaves the marker absent; legs: absent · malformed · offset-less · future",
not "`except ValueError` yields `None`". When a gate finding shows a code-level sentence
wrong, the disposition **demotes** it to mechanism level and adds the missing leg to the test
row — it does not correct the code-level sentence in place, because the corrected sentence
is the next round's finding (2026-09-03, eligibility-assistant `trace` r10 f1 / f2 / f5 and
`lifecycle` r10 f1: each anchored on a code-level clause the previous disposition had
written one round earlier).

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
   without a locator is not writable.** **A claim about behavior is a computed fact, and its
   locator is the run:** what a stdlib, SDK or package call returns, raises, accepts or
   serialises is read by executing it in the session's 3.12 venv (`.venv/bin/python -c …`)
   and recording the command and its output — reading the source is not running it, and a
   version pin is not an observation. **The probe is bounded:** pure, offline, non-mutating
   calls only — no network, no credentials read or sent, no file, repo, service or store
   write. A behavior that shows only under a side effect (a request sent, a row written, a
   key consumed) is observed through a test leg in the test row, never a live probe; a claim
   whose only evidence would be an out-of-bound probe is written at mechanism level with that
   leg, not as a computed fact. The gate agent runs the same probes under the same bound (its
   Bash is read-only; `.claude/agents/drift-gate-agent.md`), so a disposition that only read
   is behind it by one round (2026-09-03: `datetime.fromisoformat` of an offset-less stamp
   compared against an aware receipt raises `TypeError`, found by the gate running it after
   two dispositions had reasoned about the `except ValueError` shape). The gate reads the locator first and the claim
   second: a locator that does not say what the claim says is a wrong-fact finding, and a
   missing locator is a finding on its own. This is the plan-side twin of the gate agent's
   `checked:` trail — the 2026-08-27 lesson (eligibility-assistant `corpus` / `llm-seam`,
   three rounds each): every substantive finding across six rounds was a tree or package
   fact the plan asserted and the gate re-derived.
3. **Fill the spec's planned test names** where planning sharpens them; the check column
   is the test list — the plan does not restate it.
4. **Run the four checks** (below), then show the owner; the plan goes to the gate.
   After the gate stamps `GATED`, the files ride the ticket's branch — `implementation`
   cuts it at the stamp and, after owner push approval, pushes the first commit (README
   landing rule, 2026-08-28); no plan-only PR.

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
one (the drift-gate skill holds the matching round rule). A class is the same kind of
wrong **and** the same kind of site — the definition is the gate agent's
(`.claude/agents/drift-gate-agent.md`, origin tags); a finding on text the previous
disposition wrote is a regression of that disposition, tagged `new`, and owes the fix, not a
sweep.
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
  this class. **Scope:** the sweep runs over `git ls-files` **minus `docs/workflow/plans/`** —
  the item plan, its decision register and the ticket files. Those files quote the searched
  terms in every change row, disposition cell and finding cell, so an in-scope plan file grows
  the hit count on every re-run with no tree change (2026-09-03, eligibility-assistant `trace`
  r10 f3: the count grew between rounds, every delta a plan-file line). The
  plan's own internal consistency is the gate agent's cites-resolve check, not the sweep's.
  The contract `docs/workflow/<item>.md` stays in scope — it outlives the item.

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
