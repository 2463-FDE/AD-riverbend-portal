---
name: implementation
description: Stage 4 of the delivery workflow (docs/workflow/README.md). Turn a gated code plan into merged code — branch, TDD slice loop, full-suite + baseline check, PR, codex review. Use when a work item's plan has passed the gate and the user says "start implementation", "impl stage", or invokes /implementation.
---

# Implementation

Input: `docs/workflow/<item>/plan.md` with `Status: GATED`. Refuse to start from a DRAFT
plan — the gate (plan/spec drift check) runs first, and starting early is how drift ships.
Output: a merged PR whose changes trace to the plan's scope map, with the spec untouched.

## Entry checklist

- Spec `Status: AGREED` (frozen), plan `Status: GATED`.
- Plan touches an approval-gated zone (`docs/landmines.md` §1 — auth, PHI columns,
  ROI/disclosure, migrations, secrets)? Confirm the human approval is recorded in the
  plan's Landmines section before writing code. No record → stop and ask.
- Branch off `main` per `CONTRIBUTING.md`. Never implement on `main`.

## Slice loop

Work the plan's scope map in order. Each slice runs the `tdd` skill's loop: one EARS
clause → failing test at the plan's seam → minimal code → green → next. Targeted test
file per cycle; the full suite waits for the end.

Slices with no behavioural seam — CI wiring, build config, tooling — skip the TDD loop;
the plan's Verification section covers them, and the PR body says which slices ran
test-first and which didn't.

Deviation handling, per the pipeline:

- **Plan fact wrong, fix trivial** (path moved, name changed): patch, record it in
  `docs/workflow/<item>/pr-body.md` (see end-of-implementation step 6), continue.
- **Plan design wrong** (seam doesn't hold, change fights a wall): stop. Back to stage 3;
  plan revised and re-gated; spec unchanged. Do not improvise structure mid-loop.

## End-of-implementation verification

1. Full suite: `make test-docker` (the claim-worthy gate) or
   `.venv/bin/python -m pytest -m "not integration" -q`.
2. Compare against the pinned baseline in `CLAUDE.md` §6. Passed count grows by exactly
   the tests this branch adds; **xfailed and deselected counts must not move**. A moved
   count is a finding to report, not a number to update.
3. `make eval` if anything under `eval/rag/` or the retrieval path changed.
4. Traceability: every SHALL clause in the plan's scope map has a test naming its SPEC id,
   or the plan records why not. This is the evidence trail the drift gate and review
   anchor to.
5. Run the plan's own Verification section end-to-end, including its negative
   (break-then-revert) checks.
6. Write the PR-body draft at `docs/workflow/<item>/pr-body.md`. It is a **working-tree
   artifact**, not committed on the code branch — workflow artifacts land on `main` once,
   via `noncode-merge`; cherry-picking them onto the code branch produces a conflicting
   second copy at merge. The gates read it from the working tree. It carries the delivery
   `Status:` header, created at `Status: DRAFT`, and must contain: the required "Risk &
   landmines" section (§1 zones touched or "none touched"); the accepted residuals copied
   from the plan's Landmines section; which slices ran test-first and which didn't; every
   plan deviation with its rationale; and any planned slice absent from the diff with why
   — an empty result ("discovery found nothing to fix") is still recorded. The impl gate
   checks this file (steps 2 and 7 of `.claude/skills/impl-gate/`); the branch is not
   gate-ready without it. Commit messages and session memory do not carry these
   disclosures — if it isn't in the draft, the gate and the next session don't know it.

## Landing

- Commits: format per `CONTRIBUTING.md`; no `Co-Authored-By` trailer
  (`CONTRIBUTING.md:53`).
- **Impl gate before push:** the finished branch is checked against plan and spec by
  `.claude/skills/impl-gate/` in a fresh session that did not write the code. Findings
  come back here as a round in `impl-findings.md`; the stamp on `pr-body.md`
  (`Status: IMPLEMENTED`) is what makes the branch push-ready. The plan header stays
  `GATED` — delivery state lives on `pr-body.md`.
- **Ask before pushing.** Push is human-gated.
- PR body: copy from `docs/workflow/<item>/pr-body.md` (end-of-implementation step 6);
  the draft is the durable record and lands on `main` via `noncode-merge` (not on the
  code branch — see step 6). The "Risk & landmines" section is required — a residual the
  plan accepted is disclosed in the PR, not rediscovered by review.
- **After push (an owned step, artifact-backed):** advance the `pr-body.md` `Status:`
  line to `PUSHED PR #<n> <date>`, then comment `@codex-review`. Log every review round in
  `docs/workflow/<item>/review-findings.md` (round log, created on the first finding;
  template and round-3 rule mirror `gate-findings.md` / `impl-findings.md`); answer each
  round with an `rN:` disposition comment (A/B/C labels); iterate until dry. Structural
  findings go back to stage 3 per the pipeline; trivial ones are patched and re-reviewed.
  On merge, advance `pr-body.md` `Status:` to `MERGED <sha> <date>`. No seventh skill —
  this skill owns the push→review→merge segment; the artifacts, not memory, carry its state.

## Review round log (`review-findings.md`)

Created on the first codex finding; rounds appended as review returns, dispositions filled
by this fix session. Round number is the last in the file plus one (1 for a new file).
Mirrors `gate-findings.md` / `impl-findings.md` exactly — header, round numbering,
disposition column, and the round-3 owner-escalation rule. Delivery status lives in
`pr-body.md`, not here. The review-stage state decode table is in `docs/workflow/README.md`
("State decode tables").

```markdown
# <item> codex review findings

> Round log for the @codex-review loop. Rounds appended as review returns; dispositions
> filled by the stage-4 fix session. Delivery status lives in pr-body.md.

## Round 1 — <date>

<n> findings.

| # | SPEC | Finding | Disposition (r1: A/B/C) |
|---|------|---------|-------------------------|
| 1 | <id or —> | <one line> | |
```

**Round-3 rule:** a third round with any open finding stops the loop. Report to the owner,
who decides per finding: accept as a named residual, overrule it, or send the item back to
stage 3 (plan revision, re-gated). Record each decision in the disposition cell; the next
round honors recorded owner decisions rather than re-raising them.
