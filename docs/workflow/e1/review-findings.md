# e1 codex review findings

> Round log for the @codex-review loop. Rounds appended as review returns; dispositions
> filled by the stage-4 fix session. Delivery status lives in pr-body.md.

## Round 1 — 2026-08-07

1 finding (PR #49, `@codex-review` by JesterCharles). Dispositions pending.

| # | SPEC | Finding | Disposition (r1: A/B/C) |
|---|------|---------|-------------------------|
| 1 | — | [medium] Dev/test deps shipped in the production frontend image: `frontend/package.json` adds Vitest, Vite, jsdom, Testing Library, ESLint as devDependencies, but the frontend Dockerfile still builds the runtime image with plain `npm install` and never prunes dev packages — larger image + wider CVE/SBOM surface for a provider-facing portal. Fix: multi-stage Dockerfile — full install in the build stage, `npm ci --omit=dev` for the runtime stage; keep CI on the full install. Optional invariant: a CI `npm ls --omit=dev` (or image-inspect) step so a devDependency can't leak back in. | |
