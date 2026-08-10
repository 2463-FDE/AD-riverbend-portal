# e1 findings

> Round log for this item's three gated stages: the drift gate
> (`.claude/skills/drift-gate/`), the impl gate (`.claude/skills/impl-gate/`), and the
> `@codex-review` loop (owned by `.claude/skills/implementation/`). Each stage appends
> rounds under its own heading, created on that stage's first finding; the next-stage
> session fills the dispositions. Findings only — plan maturity lives in `plan.md`,
> delivery status in `pr-body.md`.

## Impl gate

### Round 1 — 2026-08-07

1 finding, no stamp.

| # | SPEC | Finding | Disposition (stage 4) |
|---|------|---------|-----------------------|
| 1 | — | No PR-body draft exists: the planned "existing `frontend/**` lint/type fixes" slice is absent from the diff with nothing recording why (gate re-ran `npm run typecheck` and `npm run lint` — both exit 0 untouched, so the list is empty; plan step 5 says "noted in PR body"), and the required disclosures (test-first vs non-TDD slice split, `vite ^5` pin deviation, plan's accepted SPEC-11 residual, Risk & landmines section) are recorded nowhere durable. Write the PR-body draft; commit-message notes alone don't carry it. | **Fixed** 2026-08-07 — PR-body draft written to `docs/workflow/e1/pr-body.md`. Records: the empty step-5 cleanup list and why (typecheck/lint both exit 0 on untouched inherited source; one pre-existing non-failing `jsx-a11y` warning left alone), the test-first/non-TDD slice split (only the seed test has a behavioral seam; `/healthz` has no automated test, covered by the `frontend-boot` job), the `vite ^5` pin deviation, the plan's accepted SPEC-11 residual, a "none touched" Risk & landmines section, and the SPEC-15 verification caveat. No code, plan, or spec changed. |

Gate evidence (all reproduced fresh this session, branch `feat/noref-e1-frontend-js-gates` @ `0c5ad6a`):

- `npm test` → 2 passed, exit 0; throwaway failing test → exit 1, test named (SPEC-1..3,18).
- `npm run typecheck` exit 0 (test file included via tsconfig `**/*.tsx`); `npm run lint` exit 0,
  one pre-existing non-failing `jsx-a11y` warning in `DateField.tsx` (SPEC-6..9).
- Production build + `next start`: `/healthz` → `200 {"status":"ok"}`, no session, fixed body;
  server killed → connection refused (SPEC-10..12). Caveat: ports 3070/3071 are held by running
  docker containers whose stale images answer differently — verify on a free port.
- `docker build` of `frontend/` boots healthy in ~4 s; compose probe command exits 0 in-container
  against the live app and 1 against a dead port; `docker compose config -q` clean (SPEC-13..17).
  SPEC-15 verified at probe level, not by live compose flip: killing node inside the container
  kills PID-1 `npm` and exits the container, so the as-written plan verification item 4 negative
  ("stop the next server process inside the container") is not executable as described.
- `make test-docker`: `821 passed, 5 deselected, 1 xfailed` — pinned baseline exact (no Python touched).
- No `Co-Authored-By` trailer; no `docs/landmines.md` §1 zone touched; no existing frontend
  source modified, registration/TODO-1 defect intact; TODO-45 closure is the item's sanctioned scope.

### Round 2 — 2026-08-07

1 finding, no stamp. Round-1 finding 1 confirmed closed (`docs/workflow/e1/pr-body.md` exists and
carries every disclosure it names). Full re-run, fresh session, branch `feat/noref-e1-frontend-js-gates`
@ `0c5ad6a`.

| # | SPEC | Finding | Disposition (stage 4) |
|---|------|---------|-----------------------|
| 1 | — | Unplanned, undisclosed scope that leaves a registry stale: `docs/runbook.md` "CI" dropped `secret-scan` from "There is no secret-scan, dependency-vuln-scan, or image-scan step". That exact claim is a **registered** drift item — `docs/todo.md` TODO-52 names it verbatim ("its CI section says there is no secret scan, which has run since PR #2") and still reads "measured 2026-08-06, none fixed". The plan's scope for `docs/runbook.md` is "document `npm test` one-command"; the PR body's Wiring section lists only the one-command edit. TODO-52 also says explicitly "**Do not fix by deleting** — record what changed and when", and the diff deletes. Either revert the `secret-scan` clause (leaving TODO-52 to own the whole sweep) or keep the correction and record it in TODO-52; either way disclose in the PR body. | **Fixed** 2026-08-07 — option A: `secret-scan` clause reverted in `docs/runbook.md` (commit amended); runbook again carries the registered-stale claim and TODO-52 owns the whole sweep with its no-delete rule intact. PR body Wiring section now discloses the deliberate non-correction and the round-2 revert. Also synced the PR body's SPEC-15 paragraph to round 2's live verification (stale round-1 caveat replaced). No other file changed. |

Gate evidence (all reproduced fresh this session; nothing accepted on the prior round's record):

- `npm test` → 2 passed, exit 0. Throwaway failing test → exit **1**, failing test named with file and
  line (SPEC-1,3,18). Same suite run from the **image's** node_modules (clean `npm install` off
  `package.json` + lock during `docker build`) → 2 passed, proving no undocumented setup (SPEC-2).
- `npm run typecheck` → exit 0. Injected `const bad: number = "not a number"` → exit **2**; reverted
  (SPEC-6,7). `npm run lint` → exit 0, one pre-existing non-failing `jsx-a11y` warning in
  `DateField.tsx` (SPEC-8,9). Working tree clean after both negatives.
- `docker build ./frontend` (same Dockerfile `build: ./frontend` uses) → run → CI poll loop went green
  on try 2; try 1 got `curl: (52) Empty reply from server`, i.e. no success response while not yet
  serving (SPEC-16,17 and SPEC-11). `curl -i /healthz` → `200`, `content-type: application/json`,
  body `{"status":"ok"}`, no `Set-Cookie`, no session required, no PHI or secret (SPEC-10,12).
  Container removed → `curl: (7) Connection refused` (SPEC-11 negative).
- **SPEC-15 verified live this round, closing the residual round 1 recorded as non-executable.**
  Container run with the compose healthcheck values verbatim (`interval 10s / timeout 3s / retries 5 /
  start_period 20s`) and PID 1 held by `sh`: `running/starting` → `running/healthy` at t+15s
  (SPEC-13,14) → `next-server` killed at t+45s → `running/unhealthy` at t+95s, container still up
  (SPEC-15). Round 1's caveat holds only for the default `CMD` (killing node there kills PID-1 `npm`);
  the probe itself discriminates correctly and docker acts on it. `docker compose config -q` clean.
- `make test-docker` → `821 passed, 5 deselected, 1 xfailed` — pinned CLAUDE.md §6 baseline, exact and
  unmoved. No Python touched.
- Scope map closed both ways: all 14 changed files trace to a scope-map slice; the one planned slice
  absent from the diff (legacy `frontend/**` lint/type cleanup) is recorded as empty-with-reason in the
  PR body, and this round independently confirms typecheck and lint exit 0 against untouched inherited
  source. Only the `docs/runbook.md` secret-scan hunk fails the trace — finding 1.
- Planted defects intact: no inherited `frontend/**` source modified at all; `StatusBadge` is pure
  presentational (no fetch, no state) and sits on no defective flow; nothing near registration/TODO-1.
- Idiom/rule sweep: no gateway route touched, no `_post`/`_get` added, no `str(e)` or PHI-bearing field
  in any log, no `Co-Authored-By` trailer on `0c5ad6a`, no `docs/landmines.md` §1 zone touched (compose
  edit is additive — `healthcheck` only, `ports`/`build` untouched, so no `expose`-only allowlist
  question arises).

### Round 3 — 2026-08-07

Clean — stamped. Full re-run, fresh session, branch `feat/noref-e1-frontend-js-gates` @ `0dc7ef5`.
Round-2 finding 1 confirmed closed: the only delta from round-2's gated commit `0c5ad6a` is the
1-line `docs/runbook.md` `secret-scan` revert (`git diff 0c5ad6a..0dc7ef5` = one file, one line) —
the runbook again carries the registered-stale claim TODO-52 owns, no-delete rule intact. Round-1
finding 1 (PR-body draft) remains closed: `pr-body.md` carries every required disclosure (TDD vs
non-TDD split, `vite ^5` deviation, empty cleanup slice, SPEC-11 residual, SPEC-15 live-verify,
secret-scan non-correction, "none touched" Risk & landmines).

Gate evidence (reproduced fresh this session):

- All 14 changed files trace to a scope-map slice both ways; the one planned-absent slice (legacy
  `frontend/**` lint/type cleanup) recorded empty-with-reason in the PR body and re-confirmed here
  (typecheck + lint exit 0 against untouched inherited source).
- `npm test` → 2 passed, exit 0. SPEC-3 negative (broke one assertion) → exit **1**, failing test
  named with file; reverted, tracked tree clean.
- `npm run typecheck` → exit 0; `npm run lint` → exit 0, one pre-existing non-failing `jsx-a11y`
  warning in `DateField.tsx` (SPEC-6..9).
- `docker compose config -q` clean (SPEC-13..15 file validity). Seed test targets real pure-
  presentational `StatusBadge` (no fetch/state, no defective flow) — SPEC-18,19 intact.
- `make test-docker` → `821 passed, 5 deselected, 1 xfailed` — CLAUDE.md §6 baseline, exact and
  unmoved (branch adds Vitest tests, not pytest). No Python touched.
- Idiom/rule sweep: no gateway route, no `_post`/`_get`, no `str(e)`/PHI log, no `Co-Authored-By`
  trailer on `0dc7ef5`, no `docs/landmines.md` §1 zone touched. Planted defects intact — no
  inherited `frontend/**` source modified, registration/TODO-1 untouched.

Delivery stamped `Status: IMPLEMENTED 2026-08-07` — on `pr-body.md` since the 2026-08-07
state-split; the plan header stays `GATED`. **The item was pushed after this gate:** PR #49
is open with codex round 1 pending. Current delivery state and the codex loop live in
`pr-body.md` and the Review section below. (This line was corrected from its original
"Push-ready; push stays human-gated", which predated the push — recorded, not deleted, per
TODO-52's convention.)

## Review

> PR #49, `@codex-review` by JesterCharles.

### Round 1 — 2026-08-07

1 finding. Disposition: **A, fixed**.

| # | SPEC | Finding | Disposition (A/B/C) |
|---|------|---------|---------------------|
| 1 | — | [medium] Dev/test deps shipped in the production frontend image: `frontend/package.json` adds Vitest, Vite, jsdom, Testing Library, ESLint as devDependencies, but the frontend Dockerfile still builds the runtime image with plain `npm install` and never prunes dev packages — larger image + wider CVE/SBOM surface for a provider-facing portal. Fix: multi-stage Dockerfile — full install in the build stage, `npm ci --omit=dev` for the runtime stage; keep CI on the full install. Optional invariant: a CI `npm ls --omit=dev` (or image-inspect) step so a devDependency can't leak back in. | **A** — genuine defect in the original push. Fixed: `frontend/Dockerfile` split into `build` (full `npm install` + `next build`) and `runtime` (`npm ci --omit=dev`, copies `.next` + `next.config.mjs` only) stages. Regression guard added to the `frontend-boot` CI job: inspects the built image and fails if `node_modules/vitest` is present. No state introduced (no counter/TTL/lock/breaker/budget/cache) → trivial patch on branch, no re-gate. Runtime-verified: image builds, vitest absent + next/react present, serves `/healthz` 200. |

### Round 2 — 2026-08-07

1 finding. Disposition: **A, fixed**.

| # | SPEC | Finding | Disposition (A/B/C/E) |
|---|------|---------|-----------------------|
| 1 | E1-SPEC-17 | [medium] `frontend-boot` is not part of the terminal CI dependency chain (`.github/workflows/ci.yml:130-132`): the new job carries `needs: frontend`, but the `docker-build` fan-in job still depends only on `frontend, services, tests, secret-scan, eval`. Anything reading `docker-build` as the terminal signal (branch protection, merge queue, deploy automation) can go green while the boot probe fails — the exact failure this PR set out to close. Fix: add `frontend-boot` to `docker-build.needs`. Also: the runbook/TODO closure claims are only true once the gate is wired. | **A** — genuine wiring gap, and a spec-conformance miss: E1-SPEC-17 says the pipeline shall report an **overall failure**, and a job outside the terminal fan-in only fails itself. Both the drift gate and the impl gate read "job exists and polls `/healthz`" as satisfying it and neither checked the fan-in edge (noted in the metrics ledger). Fixed: `frontend-boot` added to `docker-build.needs`. `docker-build`'s stale NOTE comment ("Nothing here would notice a service that builds and then crashes on boot") corrected — it is now true of the domain services only, not the frontend. Closure claims made precise in `docs/runbook.md` (CI section names the fan-in) and `docs/todo.md` TODO-45 (names the `needs` wiring). No state introduced (no counter/TTL/lock/breaker/budget/cache) → trivial patch on branch, no re-gate. Verified: `ci.yml` parses, `docker-build.needs` = `[frontend, frontend-boot, services, tests, secret-scan, eval]` with no dangling job name and no cycle; Python suite re-run at the pinned baseline `821 passed, 5 deselected, 1 xfailed`. |

### Round 3 — 2026-08-07 (dry)

0 findings. Verdict: **approve** — "No defensible ship-blocking issue found in the branch diff.
No material findings." Loop closed; PR squash-merged as `efe6f32`.

Reviewer explicitly confirmed both prior fixes held: the fan-in includes `frontend-boot`, and the
pruned runtime image still ships every file the app needs (the over-prune failure mode the r1 fix
could have introduced). Non-blocking suggestion carried forward, not actioned in this PR: grow
Vitest coverage from `StatusBadge.test.tsx` as each frontend component is next touched.
