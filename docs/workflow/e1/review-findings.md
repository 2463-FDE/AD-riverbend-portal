# e1 codex review findings

> Round log for the @codex-review loop. Rounds appended as review returns; dispositions
> filled by the stage-4 fix session. Delivery status lives in pr-body.md.

## Round 1 — 2026-08-07

1 finding (PR #49, `@codex-review` by JesterCharles). Disposition: **A, fixed**.

| # | SPEC | Finding | Disposition (r1: A/B/C) |
|---|------|---------|-------------------------|
| 1 | — | [medium] Dev/test deps shipped in the production frontend image: `frontend/package.json` adds Vitest, Vite, jsdom, Testing Library, ESLint as devDependencies, but the frontend Dockerfile still builds the runtime image with plain `npm install` and never prunes dev packages — larger image + wider CVE/SBOM surface for a provider-facing portal. Fix: multi-stage Dockerfile — full install in the build stage, `npm ci --omit=dev` for the runtime stage; keep CI on the full install. Optional invariant: a CI `npm ls --omit=dev` (or image-inspect) step so a devDependency can't leak back in. | **A** — genuine defect in the original push. Fixed: `frontend/Dockerfile` split into `build` (full `npm install` + `next build`) and `runtime` (`npm ci --omit=dev`, copies `.next` + `next.config.mjs` only) stages. Regression guard added to the `frontend-boot` CI job: inspects the built image and fails if `node_modules/vitest` is present. No state introduced (no counter/TTL/lock/breaker/budget/cache) → trivial patch on branch, no re-gate. Runtime-verified: image builds, vitest absent + next/react present, serves `/healthz` 200. |

## Round 2 — 2026-08-07

1 finding (PR #49, `@codex-review` by JesterCharles). Disposition: **A, fixed**.

| # | SPEC | Finding | Disposition (r2: A/B/C/E) |
|---|------|---------|---------------------------|
| 1 | E1-SPEC-17 | [medium] `frontend-boot` is not part of the terminal CI dependency chain (`.github/workflows/ci.yml:130-132`): the new job carries `needs: frontend`, but the `docker-build` fan-in job still depends only on `frontend, services, tests, secret-scan, eval`. Anything reading `docker-build` as the terminal signal (branch protection, merge queue, deploy automation) can go green while the boot probe fails — the exact failure this PR set out to close. Fix: add `frontend-boot` to `docker-build.needs`. Also: the runbook/TODO closure claims are only true once the gate is wired. | **A** — genuine wiring gap, and a spec-conformance miss: E1-SPEC-17 says the pipeline shall report an **overall failure**, and a job outside the terminal fan-in only fails itself. Both the drift gate and the impl gate read "job exists and polls `/healthz`" as satisfying it and neither checked the fan-in edge (noted in the metrics ledger). Fixed: `frontend-boot` added to `docker-build.needs`. `docker-build`'s stale NOTE comment ("Nothing here would notice a service that builds and then crashes on boot") corrected — it is now true of the domain services only, not the frontend. Closure claims made precise in `docs/runbook.md` (CI section names the fan-in) and `docs/todo.md` TODO-45 (names the `needs` wiring). No state introduced (no counter/TTL/lock/breaker/budget/cache) → trivial patch on branch, no re-gate. Verified: `ci.yml` parses, `docker-build.needs` = `[frontend, frontend-boot, services, tests, secret-scan, eval]` with no dangling job name and no cycle; Python suite re-run at the pinned baseline `821 passed, 5 deselected, 1 xfailed`. |

## Round 3 — 2026-08-07 (dry)

0 findings (PR #49, `@codex-review` by JesterCharles). Verdict: **approve** — "No defensible
ship-blocking issue found in the branch diff. No material findings." Loop closed; PR squash-merged
as `efe6f32`.

Reviewer explicitly confirmed both prior fixes held: the fan-in includes `frontend-boot`, and the
pruned runtime image still ships every file the app needs (the over-prune failure mode the r1 fix
could have introduced). Non-blocking suggestion carried forward, not actioned in this PR: grow
Vitest coverage from `StatusBadge.test.tsx` as each frontend component is next touched.
