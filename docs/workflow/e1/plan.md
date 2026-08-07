# E1 Code Plan — frontend test harness + healthcheck

> Status: IMPLEMENTED 2026-08-07
> Gate record: gated fresh-context 2026-08-07, round 1 clean (no findings; no round log
> created). Residual-named SPECs: E1-SPEC-11 (route-level probe answers 200 while a page
> may break at runtime — accepted, see Landmines / risk).
> Impl-gate record: impl-gated fresh-context 2026-08-07, round 3 clean — branch
> `feat/noref-e1-frontend-js-gates` @ `0dc7ef5`. Rounds 1 (PR-body draft absent) and 2
> (runbook `secret-scan` clause dropped, colliding with TODO-52) both fixed and re-verified.
> Baseline observed: `821 passed, 5 deselected, 1 xfailed` (make test-docker, exact/unmoved);
> `npm test` 2 passed + SPEC-3 negative exit 1; typecheck/lint exit 0. Residuals accepted:
> E1-SPEC-11 (page-level runtime health out of scope); `vite ^5` pin deviation (disclosed,
> keeps `@types/node` pin); SPEC-15 verified at gate round 2 not stage 4 (plan Verification
> item 4 negative not executable under default CMD — disclosed in PR body). Push stays
> human-gated.
> Workflow stage 3 (code plan). Anchors to the frozen spec `docs/workflow/e1/spec.md`
> (E1-SPEC-1..19). Requirements: `docs/workflow/e1/requirements.md` (AGREED 2026-08-06).

## Context

The frontend has **no JavaScript gate at all**: `frontend/package.json` has zero test deps,
CI (`.github/workflows/ci.yml`) runs only `next build`, and the `frontend` compose service has
no `healthcheck` — so a build-clean but boot-broken UI ships green (TODO-45), and there is no
way to write or run tests for new UI components. E1 closes that gap with three pieces
(harness + gates + truthful health) without touching the deliberately planted defects.

This item is an internal enabler (source: engagement team, not client) and **gates W3 planning**,
which is parked pending frontend testability. No requirement touches a `docs/landmines.md` §1
approval-gated zone (auth, PHI, ROI, migrations, secrets).

**Decisions carried into this plan** (plan-stage, owner-confirmed 2026-08-06; decision record:
`adr/0018-frontend-js-gates-and-harness.md`, Proposed until this lands):
- Test harness: **Vitest + React Testing Library + jsdom** (matches the descoped rebuild's
  choice noted in `ci.yml`).
- Legacy lint/tsc violations: **fix non-behavioral only** — never alter a deliberate defect's
  behavior; if a defect trips a rule, disable that rule *inline* with a comment citing the
  landmine/TODO, do not "fix" it.
- CI boot check: **`docker run` the built image standalone** (health route needs no gateway).
- Health endpoint path: **`/healthz`** (matches every backend service's convention).

## Scope map (spec → change)

| SPEC | Change |
|------|--------|
| E1-SPEC-1..3 | Vitest harness + `test` script; non-zero exit + failing-test id on failure (Vitest default) |
| E1-SPEC-4,5 | CI step runs the suite on every PR; failure = red check |
| E1-SPEC-6,7 | CI step `tsc --noEmit`; type error = red check |
| E1-SPEC-8,9 | CI step `next lint` (config + deps added); lint failure = red check |
| E1-SPEC-10..12 | `/healthz` route: status-only, no auth, no PHI/secrets |
| E1-SPEC-13..15 | compose `healthcheck` on `frontend` service |
| E1-SPEC-16,17 | CI job: build same image, run it, poll `/healthz`, fail if not healthy in window |
| E1-SPEC-18,19 | Seed component test on `StatusBadge` (real render + assert), avoids defective flows |

## Implementation

### 1. Health route (E1-REQ-5 / SPEC-10..12)

New file `frontend/app/healthz/route.ts` — App Router route handler, mirrors the existing
`route.ts` idiom (`app/api/me/route.ts`) but does **not** use `proxy`/gateway (status-only,
no upstream dependency):

```ts
import { NextResponse } from "next/server";
export const dynamic = "force-dynamic"; // never statically cached
export function GET() {
  return NextResponse.json({ status: "ok" }, { status: 200 });
}
```

Serving pages ⇒ Next serves this route ⇒ 200. If the app is not serving, the request gets no
success response (SPEC-11 satisfied by non-response). Body is a fixed literal — no PHI, no
secrets, no session read (SPEC-12).

### 2. Compose healthcheck (E1-REQ-6 / SPEC-13..15)

Add a `healthcheck:` block to the `frontend` service in `docker-compose.yml` (lines 247-254).
**Do not touch `ports` or `build`** — `tests/test_compose_topology.py::test_the_frontend_stays_published`
pins `"3070"` published and `build: ./frontend`. `node:22-slim` has no curl/wget, so use a
`node -e` HTTP probe — the language-native analogue of the gateway's `python -c urllib` probe:

```yaml
    healthcheck:
      test: ["CMD-SHELL", "node -e \"require('http').get('http://localhost:3070/healthz', r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))\""]
      interval: 10s
      timeout: 3s
      retries: 5
      start_period: 20s
```

`start_period` (new to this repo, but valid) covers `next start` boot so the container reports
`starting`→`healthy` rather than flapping unhealthy during boot; docker shows `health: starting`
during `start_period`, which satisfies SPEC-13's "not healthy" before the first successful probe
(SPEC-13/14). Container-up but
app-dead ⇒ probe fails ⇒ `unhealthy` within interval×retries (SPEC-15). Visible via `make ps`
(`docker compose ps` shows the health column). Validate with `make config` (`docker compose config -q`).

### 3. Test harness (E1-REQ-1 / SPEC-1..3)

`frontend/package.json` — add devDeps and scripts:
- devDeps: `vitest`, `@vitejs/plugin-react`, `jsdom`, `@testing-library/react`,
  `@testing-library/jest-dom`, `@testing-library/dom`.
- scripts: `"test": "vitest run"`, `"typecheck": "tsc --noEmit"`.

New `frontend/vitest.config.ts`:
```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  test: { environment: "jsdom", setupFiles: ["./vitest.setup.ts"] },
  resolve: { alias: { "@": new URL("./", import.meta.url).pathname } }, // mirror tsconfig "@/*"
});
```
New `frontend/vitest.setup.ts`: `import "@testing-library/jest-dom/vitest";` — the
vitest-specific entry, which gives both the runtime `expect` extension and the correct
type augmentation for vitest's `expect`.

**No `globals: true`** — tsconfig's `include: **/*.tsx` puts test files under `tsc --noEmit`
(SPEC-6), so bare `describe`/`it`/`expect` would type-error the gate on its own seed test.
Test files import explicitly (`import { describe, it, expect } from "vitest";`). Chosen over
adding `"types": ["vitest/globals"]` to tsconfig, because setting `types` stops the automatic
inclusion of `@types/node`/`@types/react` unless every package is enumerated.

`vitest run` exits non-zero and names the failing test on failure (SPEC-3), needs no undocumented
setup after `npm install` (SPEC-2). Document the one command in `README.md`/`docs/runbook.md`:
`cd frontend && npm install && npm test`. Regenerate `frontend/package-lock.json` (`npm install`).

### 4. Seed component test (E1-REQ-8 / SPEC-18,19)

New `frontend/app/components/StatusBadge.test.tsx`, importing `describe`/`it`/`expect`
explicitly from `vitest` (see step 3 — no globals). Target `StatusBadge` — pure presentational,
no fetch/state, exports the pure helper `statusVariant` and renders a `<span role="status">`.
Assert on real rendered output: given `status="confirmed"`, the node has `role="status"`,
`aria-label="Status: confirmed"`, text `confirmed`, and class `rb-badge--ok`; a couple
`statusVariant` cases (`"pending"→warn`, unknown→`neutral`). This proves the harness end-to-end
(SPEC-18) and touches **no** deliberate defect — nothing about registration/TODO-1 (SPEC-19).

### 5. Lint config + legacy cleanup (E1-REQ-4 + E1-REQ-3 / SPEC-6..9)

`next lint` has no config and eslint is not installed — it would prompt interactively and fail in
CI. Add:
- devDeps `eslint`, `eslint-config-next` (pin to Next 15.1.3 line).
- `frontend/.eslintrc.json`: `{ "extends": "next/core-web-vitals" }`.

**Discovery-then-fix within the "non-behavioral only" rule:** run `npm run typecheck` and
`npm run lint` locally, collect violations. Fix only mechanical/type/style issues (unused vars,
missing types, import order). If a violation sits on a **deliberate defect** (e.g. the
registration success-path, `app/intake/page.tsx`, or anything cross-referenced in
`docs/debt-log.md` / `docs/todo.md` TODO-1), do **not** change behavior — add a narrowly-scoped
`// eslint-disable-next-line <rule> — deliberate defect, see TODO-N` or a typed suppression with
the same citation. Read `docs/landmines.md` §1 before editing any file that looks wrong.
Expected surface is small (few components, `app/lib/`); actual list is produced in this step and
noted in the PR body.

Note: `next lint` is deprecated from Next 15.3+; at the pinned 15.1.3 it works. Migrating to the
eslint CLI is expected future churn, not E1 scope.

### 6. CI wiring (E1-REQ-2,3,4,7 / SPEC-4..9,16,17)

Edit `.github/workflows/ci.yml`. Extend the existing `frontend` job (keeps `working-directory:
frontend`, node 22, `npm install`) with steps after build, each a separate step so a failure is
attributable and reports overall failure (SPEC-5/7/9):
```yaml
      - run: npm run typecheck   # SPEC-6,7
      - run: npm run lint        # SPEC-8,9
      - run: npm test            # SPEC-4,5
```
Interaction to know: `next build` already type-checks, and once `.eslintrc.json` exists it runs
lint during build too — so legacy violations would redden the **build** step before the dedicated
steps, muddying per-step attribution (SPEC-5/7/9). Consequence: step-5 discovery/cleanup lands in
the same PR before these gates can go green; the dedicated steps stay for attributability.
Remove/replace the stale "There is no JavaScript gate" comment block (ci.yml:22-25) — it becomes
false. Update the CLAUDE.md §3 line and `docs/todo.md` TODO-45 status in the same PR (CLAUDE.md
self-correction rule).

New **boot-check job** (E1-REQ-7 / SPEC-16,17), standalone `docker run` of the same Dockerfile
image, no gateway needed:
```yaml
  frontend-boot:
    runs-on: ubuntu-latest
    needs: frontend
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t frontend-boot ./frontend        # same Dockerfile the compose image builds
      - run: docker run -d --name fe -p 3070:3070 frontend-boot
      - name: Poll /healthz (fail if not healthy in window)
        run: |
          for i in $(seq 1 30); do
            if curl -fsS http://localhost:3070/healthz; then echo "healthy"; exit 0; fi
            sleep 2
          done
          echo "frontend did not become healthy"; docker logs fe; exit 1
```
A boot-broken image never answers 200 → job red → cannot ship green (SPEC-17, closes TODO-45).

## Files touched

| File | Change |
|------|--------|
| `frontend/app/healthz/route.ts` | new — status-only health route |
| `docker-compose.yml` | add `healthcheck` to `frontend` (only) |
| `frontend/package.json` | test/typecheck scripts + devDeps |
| `frontend/package-lock.json` | regenerated |
| `frontend/vitest.config.ts`, `frontend/vitest.setup.ts` | new — harness |
| `frontend/app/components/StatusBadge.test.tsx` | new — seed test |
| `frontend/.eslintrc.json` | new — lint config |
| existing `frontend/**` files | narrow non-behavioral lint/type fixes (list from step 5) |
| `.github/workflows/ci.yml` | typecheck/lint/test steps + `frontend-boot` job; drop stale comment |
| `README.md` / `docs/runbook.md` | document `npm test` one-command |
| `CLAUDE.md` §3, `docs/todo.md` TODO-45 | correct the "no JS gate" / TODO-45 claims |
| `adr/0018-frontend-js-gates-and-harness.md` | flip Status: Proposed → Accepted when this lands |

## Out of scope (from requirements §6)

Browser/E2E suite; backfilling tests for existing components; fixing registration (TODO-1);
new host-published ports (ADR 0016 — healthcheck runs inside the compose network); any client
UI surface. Python baseline `821 passed, 1 xfailed, 5 deselected` is untouched.

## Verification (end-to-end)

1. **Harness local**: fresh `cd frontend && npm install && npm test` → seed test passes, exit 0
   (SPEC-1,2,18). Temporarily break the assertion → `npm test` exits non-zero and names the test
   (SPEC-3); revert.
2. **Typecheck/lint**: `npm run typecheck` and `npm run lint` both exit 0 after step-5 cleanup
   (SPEC-6..9). Introduce a type error → typecheck exits non-zero; revert.
3. **Health route**: `cd frontend && npm run build && npm start`, then
   `curl -i localhost:3070/healthz` → `200 {"status":"ok"}`, no session/PHI/secret in body
   (SPEC-10,12). Stop the server → curl fails (SPEC-11).
4. **Compose health**: `make up`; `make ps` shows `frontend` `starting`→`healthy` (SPEC-13,14).
   Stop the next server process inside the container → `make ps` flips `unhealthy`
   within interval×retries (SPEC-15). `make config` validates the file.
5. **CI boot check** (locally mimic): `docker build -t fe ./frontend && docker run -d -p 3070:3070 fe`,
   poll `curl -fsS localhost:3070/healthz` → healthy (SPEC-16). Build an image with a broken
   start and confirm the poll loop fails (SPEC-17).
6. **Defects intact**: registration still reports false success; no deliberate-defect behavior
   changed (SPEC-19). Python suite counts unchanged; `tests/test_compose_topology.py` green.

## Landmines / risk

- **Accepted residual on SPEC-11:** `/healthz` is a route-handler-level probe. If the Next
  process is up but a page breaks at runtime (layout crash, missing chunk), healthz still answers
  200 while pages fail. The probe covers the TODO-45 threat model (boot-broken, process-dead);
  page-level runtime health is out of E1 scope.
- Touches **no** §1 approval-gated zone. Compose edit is additive (`healthcheck` only); leaves
  `ports`/`build` untouched so topology tests stay green.
- Deliberate defects (esp. registration/TODO-1) are preserved: seed test avoids them, legacy
  cleanup suppresses-with-citation rather than fixes on any defect path. Read `docs/landmines.md`
  §1 before editing any inherited file.
- PR body "Risk & landmines" section: "none of the §1 zones touched; deliberate frontend defects
  preserved (seed test + suppress-not-fix on defect paths)."
- Follows CONTRIBUTING.md: no `Co-Authored-By` trailer; no schema change (no migration needed).
