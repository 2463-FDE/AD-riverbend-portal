---
name: noncode-merge
description: Streamlined path for landing non-code changes (docs, ADRs, .claude/ tooling, workflow artifacts) on main — branch, commit, gated push, PR, squash merge, ff local main. Use when the user says "merge the docs", "land this on main", "ship the tooling", or invokes /noncode-merge, and the pending changes contain no runtime code.
---

# Non-code merge

Fast path to `main` for changes that cannot alter runtime behavior: `docs/**`, `adr/**`,
any `*.md`, and `.claude/**` tooling. Everything else in `CONTRIBUTING.md` still binds
(branch naming, Conventional Commits, PR body sections, squash merge); this skill only
streamlines the sequence and drops the review round that non-code changes skip.

## Scope guard (run first)

Inspect the full pending diff (staged + unstaged + untracked). Every path must match:

- `docs/**`, `adr/**`, `*.md` anywhere, `.claude/**`

If ANY other path appears — `services/`, `frontend/` (non-md), `db/`, `tests/`, `config/`,
`Makefile`, `.github/`, compose files, anything `.env*` or secret-like — **stop and say
so**. That change takes the normal PR process, not this skill. Never split a mixed diff
silently; ask which part to land.

`.github/workflows/` counts as code: CI changes gate merges and get real review.

## Sequence

0. **Survey open PRs** before branching: `gh pr list --state open`. Every open PR branch
   goes stale the moment this lands. Note them now — step 8 refreshes them, and one case
   needs a decision *before* you merge (see "Ordering against an open code PR").
1. **Branch** off latest `main`: `docs/noref-<slug>` for docs/ADRs, `chore/noref-<slug>`
   for `.claude/` tooling or mixed non-code (use the real ticket key instead of `noref`
   when one exists).
2. **Commit** per Conventional Commits (`docs:` / `chore:` type, subject ≤ 50 chars,
   imperative, body = why, **no `Co-Authored-By` trailer**). One concern per commit is
   ideal; a small bundle of related non-code files in one commit is fine.
3. **GATE — ask the owner before pushing.** Show branch name, commit subject(s), and file
   list; push only on explicit approval. This gate always stands.
4. **Push and open the PR** against `main`. Title follows the commit convention. Body uses
   the house narrative sections; **Risk & landmines is required** — for a clean non-code
   diff write "none touched — non-code only (docs/tooling), no runtime paths". State in
   Verification that no code paths changed.
5. **Review fork:**
   - Default: non-code PRs skip the `@codex-review` loop (standing protocol).
   - If the owner said this one needs **human eyes**: stop here. Leave the PR open, report
     the URL, do not merge until the owner says so.
6. **Merge** once CI is green: `gh pr merge --squash --delete-branch`. Squash subject
   follows the commit convention.
7. **Sync local:** `git checkout main && git pull --ff-only`, confirm local `main` is at
   the squash commit, and confirm the working tree is clean. Report PR number, squash SHA,
   and files landed.
8. **Refresh stale branches** (below). Do not report the merge as done until every open PR
   branch from step 0 is either refreshed or explicitly deferred by the owner.

## Refreshing stale branches (step 8)

A squash merge rewrites `main`'s history, so every branch cut before it is now behind and
its PR shows "out of date". Non-code merges are frequent here, so this is the normal state
after landing, not an exception. For each open PR branch from step 0:

1. **Classify the drift.** `git diff --name-only <branch>...main` (files main gained) and
   `git log --oneline <branch>..main`. No overlap with the branch's own changed files
   (`git diff --name-only main...<branch>`) means a clean rebase; overlap means expect
   conflicts and slow down.
2. **Rebase, don't merge.** `git rebase main <branch>`. Keep branch history linear —
   `main` merge commits into a feature branch make the eventual squash diff unreadable.
   On conflict, resolve only the conflicting hunks; never take a side wholesale on a file
   in a `docs/landmines.md` §1 zone.
3. **GATE — ask before force-pushing.** A rebased branch needs
   `git push --force-with-lease`, which rewrites published history. Show branch, commits
   moved, and conflict count; push only on explicit approval. Never plain `--force`.
   If the branch was never pushed, no gate is needed — just rebase.
4. **Re-verify code branches.** Rebasing a code branch onto a new `main` invalidates the
   verification behind it. Re-run the suite (`make test-docker`) and confirm the baseline
   count still holds. If the item's `pr-body.md` carries an `IMPLEMENTED` stamp from
   `/impl-gate` (the stamp lives on `pr-body.md`, not the branch), it covered the
   pre-rebase tree — say so, and re-run `/impl-gate` if `main` gained anything that
   touches the branch's surface.
5. **Report** per branch: rebased / conflicted / deferred, new head SHA, suite result.

Non-code branches (docs, `.claude/`) need steps 1–3 only.

## Ordering against an open code PR

The trap this repo hits: workflow artifacts for a work item (`docs/workflow/<item>/plan.md`,
`findings.md` — the round log for all three gated stages — and `pr-body.md`, which carries
the delivery `Status:`) are non-code and qualify for this fast path, so they land on `main`
while the item's code PR is still open. Result: `main` documents an
implementation that has not merged, and the code branch does not contain its own
paperwork.

That is acceptable — the stages are decoupled on purpose — but state it explicitly rather
than letting it happen silently:

- Say, before step 6, which open code PR the artifacts describe and that `main` will
  briefly claim work that is not yet merged.
- Do **not** cherry-pick the artifacts onto the code branch; they belong to `main` once,
  and duplicating them produces a conflicting second copy at that branch's merge.
- If the artifacts would contradict a still-changing branch (a stamp for a plan whose
  implementation is still being revised), hold them and land them after the code PR.

## Never

- Never push or merge without the step-3 approval, or force-push a rebased branch without
  the step-8.3 approval.
- Never merge `main` into a feature branch to clear the out-of-date banner — rebase.
- Never bypass CI or merge red.
- Never use this path for anything in a `docs/landmines.md` §1 approval-gated zone, even
  when the file is technically "docs" (e.g. editing the README compliance claim is
  TODO-12, human-gated).
- Never edit `docs/specs-deprecated/**` — archive, frozen.
