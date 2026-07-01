# Contributing — Riverbend Patient Portal

How changes land in this repo. This is a **brownfield, production, HIPAA** codebase — the
process is deliberately conservative. Read `CLAUDE.md` (esp. §6 landmines, §7 safety rules)
before opening a branch.

---

## 1. Branching model

Trunk-based. `main` is always deployable. No direct commits to `main` — everything lands via PR.

- Branch off the latest `main`.
- Keep branches **short-lived and small** (one ticket / one concern). Prefer several small PRs
  over one large one.
- Rebase on `main` before opening the PR; resolve conflicts locally.

### Branch naming

```
<type>/<ticket>-<short-slug>
```

- `<type>` — same set as commit types below (`feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `perf`, `ci`).
- `<ticket>` — the Jira key when one exists (`RIV-088`); use `noref` when there is no ticket.
- `<short-slug>` — 2–4 kebab words.

Examples:
```
fix/RIV-088-eligibility-timeout
feat/RIV-175-slot-unique-constraint
docs/noref-contributing-guide
```

---

## 2. Commit conventions

[Conventional Commits](https://www.conventionalcommits.org). Subject ≤ 50 chars, imperative mood.

```
<type>(<scope>): <subject>

<body — the WHY, wrap ~72 cols. Omit when the subject is self-explanatory.>

<footer — Refs: RIV-088, or BREAKING CHANGE: …>
```

- **Types:** `feat` `fix` `chore` `docs` `refactor` `test` `perf` `ci`.
- **Scope** (optional): the service or area — `gateway`, `intake`, `scheduling`, `records`,
  `roi`, `interop`, `eligibility`, `frontend`, `db`, `infra`.
- **Do NOT add a `Co-Authored-By` trailer** (workspace rule).
- Reference the ticket in the footer: `Refs: RIV-088`.

Example:
```
fix(intake): make payer eligibility call time-bounded

The inline 270/271 call had no timeout, so a payer outage froze the
whole intake screen (RIV-141), not just eligibility. Add a 3s timeout
and degrade to "eligibility unavailable" instead of blocking Save.

Refs: RIV-088, RIV-141
```

---

## 3. Pull request process

1. Open the PR against `main`. **Title** follows the commit convention:
   `type(scope): <RIV-### | W#-F#> short description`.
2. Fill in the PR body from `.github/pull_request_template.md`. The house style is
   **narrative-driven** (not checkboxes) — bold subsection headers, bullet detail, an
   endpoint table when relevant. Sections:
   - **Overview** — what & why; endpoint table if the API surface changes. `Refs:` line.
   - **Behavior** — bold-headed notes on each notable behavior / decision.
   - **Wiring** — gateway routing, compose/env, frontend proxy changes (omit if none).
   - **Risk & landmines** — **required.** Which `CLAUDE.md §6` landmines this touches
     (or "none touched"); blast radius + human sign-off request if any; confirm no PHI in
     logs/error bodies, and schema dual-update if the schema changed.
   - **Verification** — bold-prefixed, what you ran and the result; state anything skipped.
   - **Impact** — closing line: what this unblocks or follow-ups left open.
3. **Keep the diff scoped.** Do not refactor unrelated code in the same PR (`CLAUDE.md §7`).
4. CI must be green: frontend build, per-service import smoke, `pytest -m "not integration"`.
5. At least **one reviewer approval** before merge. Address review comments before adding new scope.
6. **Squash merge** into `main`. The squash commit subject follows the commit convention above;
   delete the branch after merge.

### Schema / migration changes
If a PR changes the DB schema it MUST update **both** `db/schema.sql` and add a new
`db/migrations/00N_*.sql` (they are hand-synced — `CLAUDE.md §4/§6`). Flag migrations in the PR.

---

## 4. Before you push — local checks

```bash
make test                     # unit tests (no infra)
pytest -m integration         # if you touched a DB/auth path (needs `make up`)
make config                   # if you touched docker-compose
cd frontend && npm run build  # if you touched the frontend
```

Report results in the PR. If tests fail or a step was skipped, say so — do not hide it.
