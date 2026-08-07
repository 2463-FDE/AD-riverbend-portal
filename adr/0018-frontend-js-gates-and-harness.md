# ADR 0018 — JS gates on the inherited Next portal: Vitest + RTL + jsdom harness; CI test/typecheck/lint steps; boot check against the production image

**Status:** Accepted — e1 implementation landed
**Date:** 2026-08-06
**Author:** Riverbend engagement team
**Debt:** none directly — new scope, internal enabler `e1` (`docs/workflow/e1/`). Closes TODO-45
(boot-broken frontend ships green). The gap it is written against is the one ADR 0013's
supersession note left open: "there is no JavaScript test harness in this repository… and now has
nothing scheduled against it." Adjacent to the intake contract break (`docs/debt-log.md`) — this
harness makes contract tests *writable*, it does not write them (TODO-1 stays live, deliberately).

## Context

ADR 0013's supersession note instructs: "A future JS gate should re-read §2's measurement before
re-deciding." Re-measured 2026-08-06; every fact holds on `main`: `frontend/package.json` declares
four scripts (`dev`, `build`, `start`, `lint`) and no test script; devDependencies are `@types/*`
plus `typescript`; the CI `frontend` job is `npm install` then `npm run build`; nothing starts the
frontend container in CI and the compose `frontend` service has no `healthcheck`. CLAUDE.md §3
records the consequence: "a build-clean, boot-broken UI ships green (TODO-45)."

What changed since 0013 is the target. 0013 chose a harness for the SvelteKit rebuild; that
rebuild is descoped (ADR 0012, Superseded) and its harness left `main` with it. The engagement
decision of 2026-08-06 (CLAUDE.md §11) is that tooling is built from scratch — the
`alt/sveltekit-portal` branch is a historical record, not a source. The inherited Next 15 portal
is now the permanent and only frontend, W3 is parked pending frontend testability, and `e1`
(requirements AGREED, spec frozen at E1-SPEC-1..19) is the enabler that unparks it.

One constraint 0013 named still binds: the host runs Node 26 while CI and the runtime image pin
22 — a gate proven only on the host is proven on a version nothing deploys. And this repo's
standing hazard binds every cleanup step: the frontend carries deliberately planted defects
(above all the registration success path, TODO-1) that a gate rollout must not "fix."

## Decision

### 1. Harness: Vitest + React Testing Library + jsdom, single project

`vitest` with `@vitejs/plugin-react`, `jsdom` environment, `@testing-library/react` +
`@testing-library/jest-dom` (setup imports the `/vitest` entry). One project, one command:
`npm test` = `vitest run`. No `globals: true` — test files import `describe`/`it`/`expect`
from `vitest` explicitly.

**Invariant: the gate's own artifacts pass the gate.** Test files fall under the same
`tsc --noEmit` this ADR adds, so nothing in the harness may rely on ambient types the type
gate cannot see. This is what rules out vitest globals, not style.

**Invariant: a passing component test asserted real rendered output** — rendered DOM, roles,
accessible names — never a trivial always-pass (E1-SPEC-18). Seed test: `StatusBadge`.

### 2. CI gates: three separate steps on the existing frontend job

`npm run typecheck` (`tsc --noEmit`), `npm run lint` (`next lint`, `eslint-config-next`,
`next/core-web-vitals`), `npm test` — each its own step so a failure is attributable
(E1-SPEC-5/7/9). `next build` overlaps both once an eslint config exists; the dedicated steps
stay for attribution, and the overlap means legacy cleanup must land with the gates.

**Invariant: gate cleanup never alters a deliberate defect's behavior.** A violation sitting on
a planted defect gets a narrowly-scoped inline suppression citing the landmine/TODO
(`// eslint-disable-next-line <rule> — deliberate defect, see TODO-N`), never a fix. This is the
standing policy for every future gate expansion, first applied here.

### 3. Boot check: run the production image, poll a truthful health endpoint

New `frontend/app/healthz/route.ts` — status-only, no auth, no upstream dependency, no PHI or
secrets in the body (E1-SPEC-10..12). Compose `frontend` service gains a `healthcheck` (`node -e`
HTTP probe — the image has no curl) with a `start_period` so boot reads `starting`, not
unhealthy. New CI job builds `./frontend` — the same Dockerfile, same context, no build args
that `docker-compose.yml` builds — runs it standalone, and polls `/healthz`; no 200 inside the
window is a red check (E1-SPEC-16/17). A boot-broken image can no longer ship green.

## Alternatives considered

- **Real-browser component tests (0013's choice).** Rejected at e1's scope using 0013's own
  accounting: it found eleven of its twelve requirements "would be served correctly by a DOM
  shim" and bought the browser for one — native `<input type="date">` semantics (`FE-R7`) —
  plus one combobox. e1's entire load is the shim-served class (presence-and-text assertions).
  The Next portal has the same exposure waiting (`DateField.tsx` / `react-day-picker`, the
  ADR 0008 lineage): **the first test that must verify real date-entry behavior reopens this**,
  by adding a browser-mode project — 0013 §1 is the design to re-read, not re-derive.
- **Jest.** No criterion favors it: 0013 already evaluated Vitest for this repo and its harness
  shipped (PR #25, since removed with the rebuild), and the spec names no tool — the choice was
  put to the owner and confirmed at plan stage 2026-08-06 (`docs/workflow/e1/plan.md`).
- **Compose-based boot check.** Rejected — it would drag postgres, the gateway, and six domain
  services into CI to prove a route that deliberately has no upstream dependency. The standalone
  image is the same build the compose environment runs, which is what E1-SPEC-16 requires.
- **E2E suite.** Still deferred; out of e1 scope (requirements §6). 0013 §2's reason was a
  PHI-boundary reason (patient-shaped data in CI artifacts) and nothing about it has changed;
  adopting E2E as a side effect of a gate rollout is the specific move 0013 warns against.

## Accepted tradeoffs / deferred gaps

1. **jsdom cannot verify native widget semantics.** Date-entry behavior in
   `DateField`/`react-day-picker` is untestable here — jsdom treats `<input type="date">` as
   text and reports green on nothing (0013's measured finding). Acceptable now: no e1 test
   touches it. Closes: browser-mode project when the first such test is required (trigger in
   Alternatives).
2. **`/healthz` is process-level, not page-level.** If the Next process serves but a page breaks
   at runtime (layout crash, missing chunk), healthz still answers 200. Bounded: the probe covers
   the TODO-45 threat model — boot-broken and process-dead. Closes: a page-level probe or E2E,
   each a decision of its own.
3. **No contract tests.** The intake contract break stays live as class and instance — it is a
   teaching artifact (TODO-1), and the seed test deliberately avoids defective flows
   (E1-SPEC-19). The harness makes 0013 §3's fixture design implementable when the exercise
   calls for it.
4. **No backfill.** One seed test; existing components gain tests only as they are touched
   (requirements §6). The gate's value at day one is that new UI work *can* be tested and typed,
   not that the inherited surface is covered.
5. **`next lint` is deprecated from Next 15.3.** Works at the pinned 15.1.3; migrating to the
   eslint CLI is recorded churn for whenever Next is bumped, not silent debt.
6. **Merge-blocking is a host-side required-checks setting**, outside this repo. The spec's
   observable is the red check (E1-SPEC-5 note); the branch-protection toggle is an engagement-
   owner action.

## Consequences

- New: `frontend/vitest.config.ts`, `vitest.setup.ts`, `.eslintrc.json`,
  `app/healthz/route.ts`, `app/components/StatusBadge.test.tsx`; test/typecheck/lint steps and
  a `frontend-boot` job in `ci.yml`; a `healthcheck` block on the compose `frontend` service
  (`ports`/`build` untouched — `tests/test_compose_topology.py` stays green unmodified).
- A frontend PR now goes red on a failing test, a type error, a lint failure, or an image that
  does not boot. Legacy type/lint violations must be cleaned (non-behavioral) or suppressed-
  with-citation in the same change that lands the gates.
- CLAUDE.md §3's "There is no JavaScript gate" and the matching `ci.yml` comment become false —
  corrected in the landing PR; TODO-45 closes.
- Fresh clone: `cd frontend && npm install && npm test` — the whole setup (E1-SPEC-2).
- Holding the line: the seed test proves the harness end-to-end; the boot job proves the image;
  the compose healthcheck makes `make ps` truthful. Full change design:
  `docs/workflow/e1/plan.md`.
