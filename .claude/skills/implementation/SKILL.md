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

- **Plan fact wrong, fix trivial** (path moved, name changed): patch, note it in the PR
  body, continue.
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

## Landing

- Commits: format per `CONTRIBUTING.md`; no `Co-Authored-By` trailer
  (`CONTRIBUTING.md:53`).
- **Impl gate before push:** the finished branch is checked against plan and spec by
  `.claude/skills/impl-gate/` in a fresh session that did not write the code. Findings
  come back here as a round in `impl-findings.md`; the stamp
  (`Status: IMPLEMENTED`) is what makes the branch push-ready.
- **Ask before pushing.** Push is human-gated.
- PR body: "Risk & landmines" section is required — name the §1 zones touched or "none
  touched". Copy the accepted residuals from the plan's Landmines section; a residual the
  plan accepted is disclosed in the PR, not rediscovered by review.
- After push: comment `@codex-review`; answer each round with an `rN:` disposition
  comment (A/B/C labels); iterate until dry. Structural findings go back to stage 3 per
  the pipeline; trivial ones are patched and re-reviewed.
