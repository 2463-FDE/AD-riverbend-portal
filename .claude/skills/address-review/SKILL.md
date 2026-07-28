---
name: address-review
description: Fetch the latest automated adversarial (@codex-review) round on a PR, cluster the findings by root cause, triage every cluster, stop at a design gate for any fix that is a decision rather than an edit, apply fixes with regression-proven tests, verify, push, reply with a finding ledger, and re-request review. Use when a new review lands on a PR or the user says "address the review on PR #N". Args - the PR number (defaults to the PR for the current branch).
---

# Address an adversarial review round

The repeated loop for this repo: reviewer bot posts a round → we **cluster** →
triage → **design-gate whatever is a decision rather than an edit** → fix →
verify → push → reply → `@codex-review` again. Follow these steps exactly.

The clustering and design-gate steps were added 2026-07-28 on measured evidence,
not taste: across PRs #2/#4/#5/#7/#11/#14, **58% of all reviewer findings (37 of
64) were defects in our own fix rounds** rather than in the code originally
pushed. The gate trades one stop for the rounds those cost. Evidence, method and
the running trend: `docs/review-loop-metrics.md`.

## 1. Fetch the latest round

```bash
gh pr view <N> --json comments --jq '[.comments[] | select(.author.login=="JesterCharles")] | last | .body'
```

The `<details>` block at the bottom holds the raw findings with severities and
file:line anchors — that is the authoritative list, not the prose summary.

## 2. Cluster the findings, then triage the clusters

Findings arrive as a flat list, but the list is not the unit of work. **Group them
by root cause first.** One cluster can span several findings, several files, and
several rounds; the cluster is what gets triaged, designed, fixed, and replied to.
Treating each finding as its own job is how a single defect ate five rounds on
PR #2 (r2 → r4 → r5 → r6 → r7: one budget-egress bug, four partial fixes).

Then put every cluster in exactly one bucket:

- **Fix now** — a real defect in this PR's diff that code on this branch can
  close, where the fix shape is obvious and introduces no new state. → step 4.
- **Needs design** — a real defect whose fix is a *decision*, not an edit. Trigger
  on **any** of:
  - the fix would introduce or alter **state** — a counter, TTL, lock, cache,
    breaker, budget, retry policy, or catalog;
  - more than one plausible fix shape exists;
  - the finding maps to no requirement ID in the week's spec (`docs/specs/wN.md`).

  → step 3. This bucket **always stops for a human call.**
- **Already-tracked debt** — matches an entry in `docs/debt-log.md` or a
  CLAUDE.md §6 documented gap (IDOR, ROI authz, sessions, history contamination…).
  Do NOT fix; it gets a scoping reply (step 6) citing the debt-log entry/runbook.
- **Approval-gated** — touches a §6 do-not-touch zone (auth, PHI columns,
  ROI logic, migrations, .env/secrets). STOP and ask the user before any change,
  even if the reviewer explicitly recommends it. Record the decision in memory.
  This bucket is about **permission**; *needs design* is about **direction**. A
  cluster can be both — take the design call and the approval in one gate.

If a finding is wrong, say so in the reply with evidence — do not silently skip.

### Label every finding as you triage it

One letter per finding, carried into the round's reply (step 6):

- **A** — defect in the code as originally pushed (what the reviewer is for).
- **B** — defect in code that an **earlier fix round wrote**.
- **C** — defect an earlier round already tried to fix and did not close.

B and C are the rounds this process exists to delete. The labels are the only
evidence of whether it works: if their share is not falling, step 3 and the class
sweep in step 4 are not earning their cost. Recording them costs one line per round.
The baseline they are measured against, the per-round history, and the method
live in `docs/review-loop-metrics.md` — read it before re-deriving any of this,
and append the round's line there.

## 3. Design gate — `needs-design` clusters

**STOP. Do not write code yet.**

Every B-class finding in the measured history came from *stateful machinery* —
quota counters, TTLs, locks, single-flight, breakers, member-ID catalogs —
invented mid-review with no design step. PR #7 is the standing example: one
legitimate finding ("paid AI endpoint has no aggregate abuse control") was
answered with a budget / refund / single-flight subsystem that grew
`services/gateway/security.py` from 67 to 364 lines, and rounds r7–r14 (eight
rounds, eleven findings) were spent stabilising *that*, not the original defect.
Across four of six PRs, review rounds wrote more code than the feature did.
One page of design ahead of a fix like that is worth those rounds.

Present at most one page per cluster, in one message:

1. **Problem** — the invariant that is actually broken, in our words, not the
   finding's wording.
2. **Options** — two or three, each with its blast radius: files touched, new
   state introduced, new failure modes created.
3. **Recommendation** — which one, and why the cheaper option was rejected.
4. **Requirement delta** — the spec requirement IDs this satisfies, or the new
   ones it needs (`W4-R12`). A fix that satisfies no requirement is either
   unjustified complexity or a spec gap — say which.
5. **ADR?** — yes or no, plus one line of reason (project rule: a non-trivial
   design decision gets an ADR, not just code).

Wait for the call. Then fix under step 4.

## 4. Fix-now items

- **Sweep the class, not the instance.** Before fixing, grep every call site of
  the same defect class — the same helper, the same field, the same code path in
  a sibling service — and fix them together, or state in the reply which ones you
  left and why. The entire C bucket is this step being skipped.
- **Cheapest fix first.** Name the smallest change that closes the cluster. If
  you ship something larger, one line on what the cheap version fails to cover.
- **Can it be closed by deleting?** Check whether removing code, a branch, or a
  flag closes the finding before adding anything.
- Match the surrounding service's layout — the fix should look like its neighbours.
- **Every redaction/authz/sanitization fix needs an adversarial test** — plant the
  bad input where the code does NOT expect it (CLAUDE.md §5 negative-test rule).
- **Regression-prove each new test**: stash the implementation change
  (`git stash push -- <impl files>`, keep the test), run the test, confirm it
  FAILS, `git stash pop`, confirm it passes. A new test that never failed
  proves nothing.

## 5. Verify before pushing

Run `/verify-stack` (unit suite in python:3.12 Docker + import smoke +
`make config` + regression-proof + the **`/verify-stack` step-6 adversarial diff review** that
front-loads what the bot would catch next round). Do not push on red or on
"probably fine". The adversarial pass is the lever that shrinks review rounds —
run it every round, not just the first.

Every round means the reviewer agent's cost is paid repeatedly, so brief it the
way `/verify-stack` §6 specifies: hand it the **briefing pack** (the inline
diff, the touched-file inventory, the `file:line` call-site map, what each
changed branch returns and what its callers do with that, and the tests already
covering the surface), forbid orientation greps, and cap the finding count
rather than the finding length. **Facts, not verdicts** — never include why the
fix was chosen or what was already checked, since inheriting this thread's
assumptions is exactly what destroys the pass's value. Round 2 onward, the pack
is nearly free to rebuild: it is a re-dump of context this thread already holds.

The same pack feeds `/security-review` when a round earns it — see `verify-stack`
§6 for the trigger rule (it is NOT every round) and for the commit-first gotcha
that silently narrows what that command reviews. Build the pack once per round
and use it for whichever lenses run.

## 6. Single approval gate, then commit + push + reply

STOP after verification. Present ONE gate (superseded the old three-checkpoint
flow, 2026-07-23 — see [[workflow-preferences]]) containing, in one message:

1. **Overview** — what was fixed and how it addresses each finding, plus the
   verification results (suite counts, regression-proof pass/fail, security-review
   outcome). Verification always runs BEFORE this gate — never ask approval on
   unverified or red work.
2. **Proposed commit message** (verbatim).
3. **Proposed PR reply** (verbatim) — ONE comment covering every finding: what
   was fixed (will cite the commit SHA), what is tracked-debt (link the debt-log
   entry/runbook), what is approval-gated (state the decision), ending with
   `@codex-review` to trigger the next round. Open it with the round's **finding
   ledger** — one line, the step-2 labels, e.g. `r7: 2 findings — 1 B, 1 C`. That line
   is the whole measurement; it is what tells a later session whether the design
   gate is reducing fix-induced rounds or just adding a stop.

On a single "yes" → stage → commit → push → post the reply. No separate
stage/commit/push/message steps.

**Safety valve (do NOT auto-push through a "yes" when something is off):** if
verification came back ambiguous/flaky, the final diff drifted from what the
overview described, an unexpected signal appeared (e.g. an xfail flipped to
XPASS — a §6 auth zone — a new warning), or a finding is only partially closed,
re-pause and surface the doubt instead of pushing. The single gate is the
default for the clean case, not a blind commit.

Then update the engagement-state memory: new tip SHA, findings disposition, and
the round's A/B/C tally so the per-PR trend survives the session.

## Gotchas learned the hard way

- The bot replies "No new commits since the last automated review" if you
  comment `@codex-review` without pushing first. Push, then comment.
- Findings about PHI-in-git-history and the tracked `.env` recur every round —
  they are history contamination, unfixable from a branch; always scoping-reply
  with a pointer to the remediation runbook in `docs/debt-log.md`.
