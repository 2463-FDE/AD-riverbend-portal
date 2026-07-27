---
name: address-review
description: Fetch the latest automated adversarial (@codex-review) round on a PR, triage every finding, apply fixes with regression-proven tests, verify, push, reply, and re-request review. Use when a new review lands on a PR or the user says "address the review on PR #N". Args - the PR number (defaults to the PR for the current branch).
---

# Address an adversarial review round

The repeated loop for this repo: reviewer bot posts a round → we triage → fix →
verify → push → reply → `@codex-review` again. Follow these steps exactly.

## 1. Fetch the latest round

```bash
gh pr view <N> --json comments --jq '[.comments[] | select(.author.login=="JesterCharles")] | last | .body'
```

The `<details>` block at the bottom holds the raw findings with severities and
file:line anchors — that is the authoritative list, not the prose summary.

## 2. Triage every finding into exactly one bucket

- **Fix now** — a real defect in this PR's diff that code on this branch can close.
- **Already-tracked debt** — matches an entry in `docs/debt-log.md` or a
  CLAUDE.md §6 documented gap (IDOR, ROI authz, sessions, history contamination…).
  Do NOT fix; it gets a scoping reply (step 5) citing the debt-log entry/runbook.
- **Approval-gated** — touches a §6 do-not-touch zone (auth, PHI columns,
  ROI logic, migrations, .env/secrets). STOP and ask the user before any change,
  even if the reviewer explicitly recommends it. Record the decision in memory.

If a finding is wrong, say so in the reply with evidence — do not silently skip.

## 3. Fix-now items

- Smallest change that closes the finding; match the surrounding service's layout.
- **Every redaction/authz/sanitization fix needs an adversarial test** — plant the
  bad input where the code does NOT expect it (CLAUDE.md §5 negative-test rule).
- **Regression-prove each new test**: stash the implementation change
  (`git stash push -- <impl files>`, keep the test), run the test, confirm it
  FAILS, `git stash pop`, confirm it passes. A new test that never failed
  proves nothing.

## 4. Verify before pushing

Run `/verify-stack` (unit suite in python:3.12 Docker + import smoke +
`make config` + regression-proof + the **step-6 adversarial diff review** that
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

The same pack feeds `/security-review` when a round touches auth/PHI/ROI. Build
it once per round, use it for both lenses.

## 5. Single approval gate, then commit + push + reply

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
   `@codex-review` to trigger the next round.

On a single "yes" → stage → commit → push → post the reply. No separate
stage/commit/push/message steps.

**Safety valve (do NOT auto-push through a "yes" when something is off):** if
verification came back ambiguous/flaky, the final diff drifted from what the
overview described, an unexpected signal appeared (e.g. an xfail flipped to
XPASS — a §6 auth zone — a new warning), or a finding is only partially closed,
re-pause and surface the doubt instead of pushing. The single gate is the
default for the clean case, not a blind commit.

Then update the engagement-state memory: new tip SHA, findings disposition.

## Gotchas learned the hard way

- The bot replies "No new commits since the last automated review" if you
  comment `@codex-review` without pushing first. Push, then comment.
- Findings about PHI-in-git-history and the tracked `.env` recur every round —
  they are history contamination, unfixable from a branch; always scoping-reply
  with a pointer to the remediation runbook in `docs/debt-log.md`.
