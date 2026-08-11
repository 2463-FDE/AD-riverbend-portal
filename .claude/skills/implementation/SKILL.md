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
  come back here as a round in `findings.md` §Impl gate; the stamp on `pr-body.md`
  (`Status: IMPLEMENTED`) is what makes the branch push-ready. The plan header stays
  `GATED` — delivery state lives on `pr-body.md`.
- **Ask before pushing.** Push is human-gated.
- PR body: copy from `docs/workflow/<item>/pr-body.md` (end-of-implementation step 6);
  the draft is the durable record and lands on `main` via `noncode-merge` (not on the
  code branch — see step 6). The "Risk & landmines" section is required. Know what the
  disclosure does and does not buy: it informs human readers and gives the fix session an
  anchored record to cite — it does **not** prevent rediscovery, because **the reviewer
  reads the diff, not the PR prose** (measured on e4, `docs/review-loop-metrics.md` §4).
  Expect roughly one round per accepted residual per PR; the only thing that reduces that
  count is accepting fewer residuals.
- **After push (an owned step, artifact-backed):** advance the `pr-body.md` `Status:`
  line to `PUSHED PR #<n> <date>`, then comment `@codex-review`. Each round is worked by
  the fix-session procedure below; iterate until dry. On merge, advance `pr-body.md`
  `Status:` to `MERGED <sha> <date>`. No seventh skill — this skill owns the
  push→review→merge segment; the artifacts, not memory, carry its state.

## Addressing a round (the fix session)

The procedure for responding to a codex round. The label definitions and the measured
reasoning behind these steps live in `docs/review-loop-metrics.md` (§1 labels, §3 the
baseline analysis) — that file is the why, this section is the how.

1. Append the round to `findings.md` §Review (template below), one row per finding.
2. **Label** each finding A/B/C/E per `docs/review-loop-metrics.md` §1. A finding
   believed wrong is refuted with runtime evidence (build it, run it, hit the endpoint —
   never inference from static config) and closed with an anchored comment, no code
   change.
   **A finding that restates an accepted residual or a recorded owner decision is
   answered from the record, not re-litigated:** no code change; close it with an
   anchored comment pointing at the recorded acceptance (the pr-body residuals section,
   the plan's Landmines section, or the findings-round disposition that accepted it).
   This is expected, not a surprise — the reviewer reads the diff, not the prose, so
   every accepted residual visible in the diff will come back as a finding. Reopening an
   accepted residual is the owner's call only; the fix session neither re-accepts nor
   silently fixes it.
3. **Cluster** findings that share one root cause; fix causes, not instances.
4. **Route** each cluster:
   - The fix would introduce or alter state (counter, TTL, lock, breaker, budget,
     cache) → structural. Back to stage 3; plan revised and re-gated; spec unchanged.
     Every B round in the baseline came from improvising exactly this mid-review.
   - Labelled **C** (an earlier fix didn't close it) → the instance fix already failed
     once; fix the class and add the guard or regression test that proves the class is
     closed, not another instance patch.
   - Otherwise trivial: patch on the branch. PHI, authz, and sanitization paths take
     the negative test (`docs/landmines.md` §3).
5. Re-verify: full suite plus the pinned-baseline count check (end-of-implementation
   steps 1–2).
6. Close the round: fill the round-log dispositions, reply with the `rN:` disposition
   comment carrying the labels, append one ledger line to
   `docs/review-loop-metrics.md` §4, re-tag `@codex-review`.

## Review round log (`findings.md` §Review)

One `findings.md` per item holds all three stages' rounds, one `## ` section each; this
skill owns `## Review` and writes nothing else in the file. The section is created on the
first codex finding; rounds are appended as review returns, dispositions filled by this
fix session. Round number is the last **in this section** plus one (1 for a new section) —
never count a gate round. Mirrors `## Gate` / `## Impl gate` exactly — round numbering,
disposition column, and the round-3 owner-escalation rule. Delivery status lives in
`pr-body.md`, not here. The review-stage state decode table is in `docs/workflow/README.md`
("State decode tables").

File template, used only when `findings.md` does not exist yet (rare at this stage — the
two gates usually create it first):

```markdown
# <item> findings

> Round log for this item's three gated stages: the drift gate
> (`.claude/skills/drift-gate/`), the impl gate (`.claude/skills/impl-gate/`), and the
> `@codex-review` loop (owned by `.claude/skills/implementation/`). Each stage appends
> rounds under its own heading, created on that stage's first finding; the next-stage
> session fills the dispositions. Findings only — plan maturity lives in `plan.md`,
> delivery status in `pr-body.md`.
```

Section template, appended on the first codex finding. Sections stay in pipeline order —
`## Gate`, `## Impl gate`, `## Review`. The PR number and reviewer go on the section's
lead line once, not on every round:

```markdown
## Review

> PR #<n>, `@codex-review` by <reviewer>.

### Round 1 — <date>

<n> findings.

| # | SPEC | Finding | Disposition (A/B/C/E) |
|---|------|---------|-----------------------|
| 1 | <id or —> | <one line> | |
```

**Round-3 rule:** a third round with any open finding stops the loop. Report to the owner,
who decides per finding: accept as a named residual, overrule it, or send the item back to
stage 3 (plan revision, re-gated). Record each decision in the disposition cell; the next
round honors recorded owner decisions rather than re-raising them.
