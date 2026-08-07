# e1 PR body (draft)

> Stage-4 artifact for branch `feat/noref-e1-frontend-js-gates`. Paste the content below the
> rule into the PR body at open time. Round-1 impl-gate finding 1 is closed by this file.
> Title: `feat(frontend): add JS gates, Vitest harness, truthful /healthz`

---

## Overview

The inherited Next portal had no JavaScript gate at all: CI ran `next build` and nothing else,
`frontend/package.json` carried zero test dependencies, and the `frontend` compose service had no
`healthcheck` — so a build-clean but boot-broken UI shipped green (TODO-45) and there was no way to
write or run a UI test. E1 closes that gap with three pieces — harness, CI gates, truthful health —
without touching any deliberately planted defect.

| Method | Path | Returns |
|--------|------|---------|
| GET | `/healthz` (frontend, 3070) | `200 {"status":"ok"}` — status-only, no session, no upstream call |

Refs: e1 (`docs/workflow/e1/` — requirements AGREED, spec AGREED/frozen, plan GATED)

## Behavior

**Vitest + RTL + jsdom harness** (ADR 0018, Proposed → Accepted here): one documented command,
`cd frontend && npm install && npm test`. `vitest run` exits non-zero and names the failing test.
No `globals: true` — tsconfig's `include: **/*.tsx` puts test files under `tsc --noEmit`, so bare
`describe`/`it`/`expect` would type-error the gate on its own seed test; test files import from
`vitest` explicitly instead.

**Seed component test** on `StatusBadge` — a real render with assertions on `role`, `aria-label`,
text and class, plus `statusVariant` mapping cases. `StatusBadge` is pure presentational and sits
on no defective flow, so the harness is proven end-to-end without asserting on registration/TODO-1
(E1-SPEC-18,19).

**Truthful `/healthz`**: an App Router route handler with a fixed literal body — no gateway call,
no session read, no PHI, no secret. Serving pages ⇒ 200; not serving ⇒ no success response.

**Compose healthcheck on `frontend`**: `node:22-slim` ships no curl or wget, so the probe is a
`node -e` HTTP GET — the language-native analogue of the gateway's `python -c urllib` probe.
`start_period: 20s` covers `next start` boot so the container reports `starting` → `healthy` rather
than flapping. Additive only: `ports` and `build` are untouched, so
`tests/test_compose_topology.py` stays green.

**No behavior change to any existing frontend source**: not one inherited file under `frontend/app/`
was modified. Registration still 422s at intake-service and still reports false success (TODO-1).

**Deviation from the plan — `vite` pinned to `^5`**: the plan named `vitest` and
`@vitejs/plugin-react` only. `@vitejs/plugin-react`'s vite peer otherwise resolves to `vite@7`,
which demands a newer `@types/node` than the repo's pinned `22.10.2`. Pinning `vite: ^5.4.11`
directly keeps the existing type pins intact. Trivial-fact deviation, patched and disclosed per the
implementation skill; no plan revision needed.

**Deviation from the plan — the legacy lint/type cleanup slice is empty**: plan step 5 said to run
`npm run typecheck` and `npm run lint`, collect violations, and fix the non-behavioral ones. Both
commands exit 0 against the untouched inherited source once `eslint`/`eslint-config-next`/
`.eslintrc.json` are in place, so the violation list is empty and no existing file needed a fix or
an inline suppression. `next lint` reports one pre-existing non-failing `jsx-a11y` warning in
`app/components/DateField.tsx`; warnings do not fail the gate and it was left alone.

## Wiring

- `.github/workflows/ci.yml`: three steps appended to the existing `frontend` job —
  `npm run typecheck` (SPEC-6,7), `npm run lint` (SPEC-8,9), `npm test` (SPEC-4,5) — kept as
  separate steps so a failure is attributable per gate. New `frontend-boot` job (`needs: frontend`)
  builds the same Dockerfile the compose image builds, `docker run`s it standalone (the health
  route needs no gateway), and polls `/healthz` for up to 60s, dumping `docker logs` on failure.
  The stale "There is no JavaScript gate" comment block is removed — it is now false.
- `docker-compose.yml`: `healthcheck` block on the `frontend` service only.
- Docs corrected in the same PR per the CLAUDE.md self-correction rule: CLAUDE.md §3, `README.md`,
  `docs/runbook.md` (the one-command local run and the healthcheck/CI descriptions), `docs/todo.md`
  TODO-45 closed, `adr/0018-frontend-js-gates-and-harness.md` flipped to Accepted.
- Deliberately **not** corrected: the runbook CI section's "no secret-scan" claim. It is stale (a
  secret-scan has run since PR #2), but that exact drift is registered in `docs/todo.md` TODO-52,
  which owns the sweep and says not to fix by deleting. An earlier draft of this branch deleted the
  clause; impl-gate round 2 caught it as unplanned scope and it was reverted, leaving TODO-52 to
  record the correction with its history.

## Risk & landmines

**None of the `docs/landmines.md` §1 approval-gated zones are touched** — no auth or session code,
no PHI column, no ROI/disclosure logic, no migration, no `.env` or secret file. No schema change,
so no `db/schema.sql` + `db/migrations/00N_*.sql` pair is due.

**Deliberate defects preserved.** No existing `frontend/**` source file is modified at all; the
seed test targets a pure presentational component and asserts nothing about registration or any
other defective flow (E1-SPEC-19). The cleanup slice ended up empty (see Behavior), so there was no
occasion to suppress-with-citation on a defect path.

**No PHI added anywhere.** The `/healthz` body is a fixed literal `{"status":"ok"}`; nothing new is
logged, and no error body carries an exception string.

**Accepted residual, carried from the plan (E1-SPEC-11).** `/healthz` is a route-handler-level
probe. If the Next process is up but a page breaks at runtime (layout crash, missing chunk),
`/healthz` still answers 200 while pages fail. The probe covers the TODO-45 threat model
(boot-broken image, dead process); page-level runtime health is out of E1 scope.

**Known future churn, not E1 scope.** `next lint` is deprecated from Next 15.3+; at the pinned
15.1.3 it works. Migrating to the eslint CLI comes with the next Next upgrade.

## Verification

**Test-first vs not.** Only the seed component test slice (E1-SPEC-18,19) has a behavioral seam and
ran the TDD loop. The harness config, lint config, `/healthz` route, compose healthcheck and CI
wiring have no behavioral seam and were verified against the plan's Verification section instead of
via a failing test first — the split the implementation skill requires be disclosed here. Note the
consequence: `/healthz` has no automated test; its evidence is the manual run below plus the
`frontend-boot` CI job, which exercises it on every PR.

**`npm test`**: 2 passed, exit 0. Negative check: a throwaway failing test made it exit 1 and named
the failing test; reverted.

**`npm run typecheck`**: exit 0 (test files are included via tsconfig `**/*.tsx`).
**`npm run lint`**: exit 0, with the one pre-existing `jsx-a11y` warning noted above.

**Health route live**: production build + `next start`, `curl -i /healthz` → `200
{"status":"ok"}`, no session cookie required, fixed body. Negative check: server killed →
connection refused (SPEC-11 by non-response).

**Container + compose**: `docker build` of `frontend/` boots healthy in ~4s; the compose probe
command exits 0 in-container against the live app and 1 against a dead port; `docker compose
config -q` clean.

**SPEC-15 verified live at impl-gate round 2.** Stage 4 originally verified it only at probe level:
the plan's Verification item 4 negative ("stop the next server process inside the container") is not
executable under the default `CMD` (killing node kills PID-1 `npm`, exiting the container). Gate
round 2 re-ran it with the container's PID 1 held by `sh` and the compose healthcheck values
verbatim: `starting` → `healthy` at t+15s, `next-server` killed → `unhealthy` at t+95s with the
container still up. The probe's own discrimination (exit 0 live app, exit 1 dead port) was verified
both rounds.

**Python suite**: `make test-docker` → `821 passed, 5 deselected, 1 xfailed` — the pinned CLAUDE.md
§6 baseline, exact and unmoved. No Python was touched.

**Conventions**: no `Co-Authored-By` trailer on the branch's commits.

## Impact

Closes TODO-45: a boot-broken frontend image now goes red in CI instead of green. Unblocks W3
planning, which was parked pending frontend testability — there is now a harness to write UI tests
in and three CI gates to keep them honest. Leaves open: no test covers `/healthz` itself (the
`frontend-boot` job does), page-level runtime health remains outside the probe (SPEC-11 residual),
and the eslint-CLI migration comes with the next Next upgrade.
