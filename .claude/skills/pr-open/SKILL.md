---
name: pr-open
description: Open a PR following this repo's conventions - branch naming, narrative body template, the security-review gate for auth/PHI/ROI diffs, squash-merge workflow. Use when creating a branch or opening a PR here.
---

# Open a PR (Riverbend conventions, per PR #1)

## Branch

`<type>/<ticket|noref>-<slug>` — e.g. `fix/RIV-141-eligibility-timeout`,
`feat/noref-ai-assistant-llm-wrapper`. Types: feat / fix / docs / chore.
Use `noref` when no RIV ticket applies. Branch from up-to-date `main`
(workflow preference: merge open PRs first when feasible; if stacking on an
open PR is unavoidable, base the new PR on that branch and note it).

## Gates before opening

1. **`/verify-stack`** — green suite, import smoke, compose config. On a
   prose-only diff (same test as the exemption below) the suite proves nothing
   about the change: skip it, and say so explicitly in the PR's Verification
   section instead of leaving an implied green. Replace it with checks that do
   bite — referenced paths resolve, no secret/PHI-shaped strings, IDs continuous.
2. **If the diff touches auth, PHI, redaction, logging of payloads, or ROI:**
   run `/security-review` (or an equivalent local adversarial pass) BEFORE
   opening. Both PR #2 leaks were caught post-push by the bot; pull that
   net earlier. Also confirm the §5 negative-test rule is satisfied.
3. **§6 check** — if any changed file is in a do-not-touch zone
   (auth/sessions, PHI columns, ROI logic, migrations, .env/secrets),
   confirm explicit human approval exists and cite it in the PR body.

## PR body (narrative template)

```
## What this PR is        — one paragraph, plain language
## Why                    — the client-facing problem / review finding / ticket
## Changes                — bullets, grouped by concern
## Out of scope           — what is deliberately NOT done here and where it is tracked
## Verification           — suite counts, smokes, regression-proofs, dynamic checks
```

Commits and PR prose are always normal English (never caveman). No
Co-Authored-By trailer.

**End the PR body with `@codex-review` on its own line** — it triggers the
adversarial bot round at creation time (user preference, PR #4; do not wait
to post it as a separate comment after opening).

### Exception: prose-only PRs skip the review round

**Omit the `@codex-review` trigger when the diff contains no code.** The bot
analyses code diffs; on prose about how we work it has nothing to analyse, and
the round costs a cycle for nothing. Precedents: #12, #16, #18 all merged
without a round, deliberately.

The test is the file contents, not the directory:

- **Exempt** — Markdown and prose only: `docs/**`, `adr/**`, `README`,
  `CLAUDE.md`, and `.claude/**/*.md` (skill and command instructions are prose
  even though they steer behaviour — that is why #16 qualified).
- **NOT exempt** — any executable or runtime-affecting file, even one line of
  it, even alongside a mountain of prose: `*.py`, `*.ts`, `*.tsx`, `*.sh`,
  `*.sql`, `Dockerfile*`, `Makefile`, `docker-compose.yml`, CI workflows,
  `config/*.yaml`. **#17 was NOT exempt** — it was mostly a skill and memory
  restructure, but it shipped `lint.sh`, so the standing rule was the full loop.
  It merged without one only on explicit user instruction, which is a different
  thing from this exemption.

A mixed PR takes the full loop. If that feels heavy, split the prose out into
its own PR — which §10.1 wants anyway.

## Single approval gate (2026-07-23, see [[workflow-preferences]])

After the gates above pass, present ONE approval message: overview (what the PR
does + how it addresses the spec/client need + verification results) plus the
proposed branch name and the full PR body verbatim. On a single "yes" →
create the branch (if needed), commit, push, and `gh pr create`. No separate
stage/commit/push/create steps. **Safety valve:** if verification was
ambiguous, the diff drifted from the overview, or a §6 zone is implicated,
re-pause and surface it instead of pushing through the "yes".

- Confirm the `@codex-review` trigger landed in the body; if it was missed,
  post it as a comment immediately. On a prose-only PR, confirm the opposite —
  that it is absent — and state the exemption in the approval gate so the user
  can override.
- Merge style: **squash**, delete branch after merge.
- Record PR number, tip SHA, and scope in the engagement-state memory.
- If items land in `docs/debt-log.md`, update statuses in the same PR.
