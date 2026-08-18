---
name: requirement-synthesis
description: Stage 1 of the delivery workflow (docs/workflow/README.md). Turn the engagement owner's raw ask into an agreed Requirements section in the item's contract file at docs/workflow/<item>.md, creating its plan file docs/workflow/plans/<item>.md alongside. Use when the user provides a new weekly ask, says "start week N", or invokes /requirement-synthesis.
---

# Requirement synthesis

Input: an item number and the engagement owner's raw ask, given fresh in conversation.
Output: **both item files created** (the split shape — section order, header, decision
register, and landing rule are `docs/workflow/README.md` §Layout's): the contract file
`docs/workflow/<item>.md` with its `## Requirements` section agreed with the owner, and
the plan file `docs/workflow/plans/<item>.md` holding the `## Decisions` register (and
any req-review rounds). This stage produces **requirements, not solutions** — no design,
no file lists, no EARS phrasing (that is the spec stage).

Both files are working-tree only at this stage (README landing rule); nothing is
committed.

## Process

1. **Capture the ask verbatim, redacted.** Quote it exactly — never paraphrase — but
   **redact-then-quote**: the artifact is itself on the PHI documentation surface, and
   this stage's verbatim quoting of log lines, payloads, and exports is the structural
   path by which PHI enters a tracked file. SSN-shaped strings and the
   `docs/phi-logging-policy.md` rule-2 identifiers (name, DOB, member id, …) are replaced
   with a bracketed placeholder before the quote is written; keep referential identity
   (`[SSN-REDACTED-1]` twice if the same value appears twice). Exactness of the *ask* is
   preserved; the identifier is the only loss, and it is deliberate.
2. **Interrogate the repo before the owner.** Check `docs/debt-log.md`, `docs/todo.md`,
   `docs/landmines.md` §1, and the relevant code for context the ask touches. Do not read
   `docs/specs-deprecated/` — it is archive, not input.
3. **Draft the section** per the template below. Requirement IDs are `<item>-REQ-n`,
   allocated once, never renumbered — withdrawn rows are struck through, not deleted, and
   a revised row takes a prime (`REQ-4′`), so the revision trail stays visible in place.
   Owner decisions taken at this stage go in the item's `## Decisions` register
   (`docs/workflow/plans/<item>.md`), `req`-tagged; a requirement whose rationale
   outgrows its table cell cites its decision ID instead of carrying the argument.
4. **Ask the owner the open questions** (structured multi-choice where possible), fold
   answers in as `req`-tagged decisions, and delete resolved questions.
5. **Owner review runs as Findings rounds.** When the owner reviews a draft and returns
   defects, append a `### Req-review — round N, <date>` round to the plan file's
   `## Findings` (same
   table-and-disposition machinery as every other stage's rounds; the README owns the
   round format). No bespoke "what changed from the first draft" section — the round log
   plus the never-renumber idiom *is* the revision trail.
6. **Stop at agreement.** The owner marks the section `Status: AGREED <date>` (and the
   header `Status:` line advances); only then does the spec stage start.

## Requirement rules

- Each requirement is one testable statement of need — what must be true, not how.
- Name the actor (front desk, patient, clinician, system) and the observable outcome.
- Flag any requirement touching a `docs/landmines.md` §1 approval-gated zone (auth, PHI
  columns, ROI/disclosure, migrations, secrets) with `⚠ human-gate`.
- A requirement deferred to a later item is a table row marked `DEFERRED → <item>` — the
  spec stage excludes it from the freeze (`.claude/skills/spec-authoring/` owns that
  rule); never a silent deletion.
- **Out-of-scope is as load-bearing as in-scope, and compresses by citation:** one clause
  per entry when the reason is already recorded somewhere citable (a decision ID, a
  registry entry, a debt ID); a full sentence only when the reason lives nowhere else.
- If the ask names something the client expects to *see*, a UI surface requirement must
  appear in the requirements table or its exclusion in out-of-scope (lesson of TODO-44).
- Measurements taken at this stage that have no durable ref (live API state, CI timings,
  click-ops config) are recorded once as a dated `E-n` block per the README's evidence
  rule and cited by ID from the table.

## Template (the two files, as stage 1 leaves them)

Contract file — `docs/workflow/<item>.md`:

```markdown
# <item> — <short name>

Status: requirements DRAFT
Item: <one line — what this item is>
Baseline at branch: not yet cut

## Requirements

Status: DRAFT
Source: engagement owner ask, <date>

> <ask, quoted verbatim, redacted per the rule above>

| ID | Requirement | Notes |
|----|-------------|-------|
| <item>-REQ-1 | <actor + observable outcome> | <⚠ human-gate / decision cite / DEFERRED → eM> |

Out of scope: <entry (cite)> · <entry (cite)> · <entry — full sentence, reason lives
nowhere else>.

Open: <questions for the owner; delete when resolved — answers become req decisions>
```

Plan file — `docs/workflow/plans/<item>.md`:

```markdown
# <item> — plan file (deleted at delivery; contract: docs/workflow/<item>.md)

## Decisions

| ID | Stage | Decision | Why (one sentence) |
|---|---|---|---|
| <item>-D-1 | req | <decision> (owner <date>) | <why> |
```

`## Spec` and `## Delivery` are appended to the contract file, `## Plan` and
`## Findings` to the plan file, by their stages — not scaffolded empty here. Each is
created by its first writing stage (README shape rule) — a req-review round in step 5
writes the `## Findings` heading with its first round.
