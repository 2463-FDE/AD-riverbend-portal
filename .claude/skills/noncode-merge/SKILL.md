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

## Never

- Never push or merge without the step-3 approval.
- Never bypass CI or merge red.
- Never use this path for anything in a `docs/landmines.md` §1 approval-gated zone, even
  when the file is technically "docs" (e.g. editing the README compliance claim is
  TODO-12, human-gated).
- Never edit `docs/specs-deprecated/**` — archive, frozen.
