---
name: impl-gate
description: Pre-push gate of the delivery workflow (docs/workflow/README.md) — fresh-context adversarial check of an implementation branch against its GATED plan and frozen EARS spec in docs/workflow/<item>.md, before push and codex review. Stamps delivery IMPLEMENTED (the plan stamp is untouched) or returns findings to stage 4. Use when implementation is complete and the user says "run the impl gate", "pre-push review", or invokes /impl-gate.
---

# Implementation gate (pre-push)

Input: `docs/workflow/<item>.md` with `## Spec` `FROZEN` and `## Plan` `GATED`, and a
completed implementation branch (unpushed, or pushed but pre-review) carrying the
artifact.
Output: either the header stamped `delivery IMPLEMENTED <date>` (the plan stamp is not
touched), or an `### Impl gate — round N, <date>` round appended to `## Findings` and
the branch back to stage 4 (spec and plan unchanged). The round log — not chat history
or session memory — carries findings between sessions.

This gate covers what codex review cannot: codex sees the diff but never the spec, the
plan, or the repo's landmine rules. The impl gate anchors the diff to those artifacts.
The fresh context is the mechanism, not a nicety — the authoring session cannot see its
own drift (same lesson as `.claude/skills/drift-gate/`).

## Two hard rules

1. **The gate never runs in the session that wrote or amended the implementation.** If
   this session wrote any of the branch's code, stop and tell the owner to invoke the
   gate in a new session.
2. **The gate session never edits code or the Requirements/Spec/Plan/Delivery content.**
   It writes exactly two things: Impl-gate rounds in `## Findings`, and — on a clean
   run — the `delivery IMPLEMENTED` header stamp plus its short gate record. Fixes happen
   in stage 4; the fixed branch gets a full fresh gate run.

## Process

**Mechanical half** (each check is a command or lookup, scriptable later; skill-run, so
advisory by construction — `CLAUDE.md` §11 — until the owner moves one into CI or the
Makefile):

1. **Pinned-test diff (owned here).** Diff the frozen spec table's `test:` cells against
   the branch: every cell filled with a real test id, and **no pinned test renamed,
   removed, or behaviourally rewritten without a matching owner decision ID in the
   register**. A changed pinned test with no decision is a red finding — the executable
   half of the contract moves only the way the prose half does.
2. **Size budget (owned here).** `wc -l docs/workflow/<item>.md` — over the **400-line
   default budget** is a red finding unless a stage-tagged decision in the item's own
   register raises the budget and says why. The cap is a backstop against prose regrowth,
   not a target; the authoring rules (deltas only, evidence by reference, ≤5-line notes)
   do the real work and this catches what slips.
3. **`cmd:` checks.** Run every `cmd:` cell in the spec table; expected output must
   match.
4. **`gate:` checks.** Execute every `gate:` cell (hand-run assertions, click-ops state
   reads); the observation is recorded — quote it in the round or, on a clean run, note
   it for `## Delivery` via the stage-4 session. A `gate:` row with no recordable
   observation is a finding.

**Judgment half:**

5. **Read the Spec section first, alone** — expected behaviour per SPEC id — then the
   plan's change list and Landmines block. Expectations from the contract, then the diff
   tested against them.
6. **Close the diff against the change list both ways:** `git diff main...HEAD --stat`,
   then the full diff. Every changed file traces to a planned change; every planned
   change appears in the diff or `## Delivery` records why not. A missing Delivery
   section is itself a finding. An untraceable file is a finding — unplanned scope,
   however helpful-looking, goes back to stage 4.
7. **Planted-defect check.** For any hunk near known defects (`docs/debt-log.md`,
   `docs/landmines.md` §1, the phi-logging register), confirm the change does not
   silently repair or disturb a teaching artifact. A "helpful" fix of a planted defect is
   a finding, always.
8. **Baseline.** Full-suite result against the header's `Baseline at branch:`: passed
   grows by exactly the tests the branch adds; xfailed and deselected must not move.
   Prefer re-running (`make test-docker` or the 3.12 venv); accept recorded counts only
   if re-running is impossible, and say so in the record.
9. **Idiom and rule sweep over the diff only:** gateway routes not on
   `_get_checked`/`_post_checked` (CLAUDE.md §4); exception logging with `str(e)` or
   PHI-bearing fields on touched paths (`docs/phi-logging-policy.md`); `Co-Authored-By`
   trailers (`CONTRIBUTING.md:53`); §1 zones in the diff without a recorded approval in
   the Landmines block.
10. **Delivery evidence.** The plan's Verification ran end-to-end including negatives,
    recorded per the stage-4 evidence rule (references and ≤5-line notes, isolation
    clause present for landmine-adjacent live runs); deviations and test-first
    disclosures present; residuals are registry IDs only.

## Outcome

- **Any finding → no stamp.** Append `### Impl gate — round N, <date>` to `## Findings`
  (README owns the round format), SPEC-cited where applicable, one line each, disposition
  column empty for stage 4. Branch returns to stage 4; re-gate is a full re-run, fresh
  session.
- **Clean → stamp.** Set the header to `delivery IMPLEMENTED <date>` and append a short
  gate record in `## Delivery`: date, "impl-gated fresh-context", branch and HEAD commit,
  baseline observed, `gate:` observations, residuals accepted here. The plan stamp stays
  exactly as the drift gate set it. Close with a dry `checked:` round line. The stamp
  means push-ready; **push itself stays human-gated** per
  `.claude/skills/implementation/`.

Round numbers count this stage's rounds only. **Round-3 rule:** a third round with any
open finding stops the loop; the owner accepts as a named residual, overrules, or sends
the item back to stage 3, per finding, recorded in the disposition cell; the next gate
run honors recorded decisions rather than re-flagging them.

## Never

- Never gate a branch this session helped write.
- Never edit code or the artifact's other sections — Impl-gate rounds and the clean-run
  stamp + gate record are the only writes.
- Never stamp with an open finding, however minor — minor goes back to stage 4 cheaply.
- Never fix a finding in-line "while you're there" — analyze-and-amend in one motion
  leaves the final state never checked as a whole.
- Never hand findings off through chat or memory alone — if it isn't in the round log,
  the next session doesn't know it.
