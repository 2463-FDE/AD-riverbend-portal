# E1 Requirements — frontend test harness + healthcheck

> Status: AGREED 2026-08-06
> Source: internal (engagement team), 2026-08-06 — not a client ask. Unblocks W3 planning.

## 1. Raw ask (verbatim)

> Our own. Frontend has no test harness and no healthcheck. We need one so that we can
> atleast write tests for new UI components.

## 2. Context

- `docs/todo.md` TODO-45: `frontend` has never had a compose healthcheck in any commit, and
  no CI step has ever started the container — a build-clean, boot-broken UI ships green.
  TODO-45 records the fix shape: health route + compose `healthcheck` + a CI step that
  starts the image and curls it.
- `frontend/package.json`: zero test dependencies; scripts are `dev`/`build`/`start`/`lint`
  only. The `lint` script exists but nothing runs it in CI.
- `.github/workflows/ci.yml:22`: "There is no JavaScript gate" — the `frontend` job runs
  `next build` and nothing else.
- `docker-compose.yml:247`: `frontend` service has no `healthcheck`; `make ps` reports it
  up the moment the container starts.
- This item gates W3 planning (W3 is parked at spec-DRAFT pending frontend testability).
- Classification decision 2026-08-06: internal enablers get an `eN` track alongside `wN`,
  same pipeline (`docs/workflow/README.md`).

## 3. Requirements

| ID | Requirement | Notes |
|----|-------------|-------|
| E1-REQ-1 | A developer can run the frontend UI-component test suite locally with one documented command. | Harness choice is spec/plan-stage work, not a requirement. |
| E1-REQ-2 | CI runs the frontend test suite on every PR; a failing test blocks merge. | |
| E1-REQ-3 | CI type-checks the frontend on every PR; a type error blocks merge. | |
| E1-REQ-4 | CI lints the frontend on every PR; a lint failure blocks merge. | Wires up the existing `lint` script. |
| E1-REQ-5 | The frontend answers a health request with success only when the app is actually serving. | |
| E1-REQ-6 | `make ps` (compose) reports the frontend healthy only when it is actually serving, not merely started. | |
| E1-REQ-7 | CI starts the built frontend image and fails if the health request does not succeed — a boot-broken image cannot ship green. | Closes TODO-45. |
| E1-REQ-8 | At least one real UI-component test exists and passes, proving the harness works end to end. | Seed test; must not touch deliberate defects (see §4). |

No requirement touches a `docs/landmines.md` §1 approval-gated zone (auth, PHI columns,
ROI/disclosure, migrations, secrets).

## 4. Assumptions

- Component-level testing satisfies "tests for new UI components"; no browser/E2E
  infrastructure is required.
- New tests characterize new components only. Deliberately planted frontend defects —
  above all the broken-registration success path (TODO-1) — are teaching artifacts; the
  harness must not be used to "fix" them, and the seed test must not assert around them.
- The Python baseline (`821 passed, 1 xfailed, 5 deselected`) is untouched by this item.
- Lint/type-check gating on the *existing* code may require making current code pass
  first; how much cleanup that implies is discovered at spec/plan stage.

## 5. Open questions

None — scope questions resolved with owner 2026-08-06 (CI gate blocking; full TODO-45
boot-check shape; gate covers tests + tsc + lint).

## 6. Out of scope

- **Browser E2E suite** — component tests satisfy the stated need; E2E is a separate,
  larger investment.
- **Backfilling tests for existing UI components** — the need is tests for *new*
  components; backfill would collide with deliberate defects.
- **Fixing the registration break (TODO-1)** — deliberate, human-gated, tracked elsewhere.
- **No client-facing UI surface** — this is internal infrastructure; nothing here is
  something the client expects to see (recorded per the TODO-44 lesson).
- **Topology changes** — no new host-published ports (ADR 0016); healthcheck runs inside
  the compose network.
