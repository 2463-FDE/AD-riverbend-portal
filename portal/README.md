# portal — Riverbend staff portal (SvelteKit)

The staff-facing rebuild. It coexists with the legacy Next.js app in `frontend/` until `FE-R1`–`FE-R3`
pass here (`FE-R15`), so both are runnable and both are built by CI. Requirements live in
`docs/specs/frontend-rebuild.md`; the decisions behind this directory are ADR 0012 (SvelteKit),
0013 (test harness), 0014 (session handling) and 0015 (origin).

Scaffolded from `npx sv@0.17.0 create --template minimal --types ts`, then: `adapter-auto` swapped
for `adapter-node`, the Vitest two-project harness added, and eslint wired up.

## Commands

| Task | Command |
|------|---------|
| Dev server (3071) | `make portal-dev` — or `npm run dev -- --port 3071` |
| The whole JS gate | `make test-frontend` (repo root) |
| Type + a11y check | `npm run check` |
| Lint | `npm run lint` |
| Tests, both projects | `npm test` |
| Tests, Node project only | `npm run test:unit` |
| Production build | `npm run build` |

The browser project needs Chromium once: `npx playwright install chromium`.

## What is load-bearing here

- **`vitest` and `@vitest/browser-playwright` are pinned exactly, not caret-ranged.** The provider
  peers `vitest` at an exact version (ADR 0013 §5), so bumping one alone breaks the install. Bump
  them together, and re-check `vitest-browser-svelte`'s peer range at the same time.
- **The `.svelte.test.ts` suffix decides which project a test runs in.** `src/**/*.svelte.test.ts`
  is the Chromium project; everything else matching `src/**/*.test.ts` or `tests/**/*.test.ts` is
  the Node project. Misname a component test and it silently loses its browser.
- **`TZ=America/Chicago` on the `test` script is a control, not a preference** — ADR 0013 §4, and
  `tests/ambient-timezone.test.ts` is what stops it being deleted as noise.
- **`--fail-on-warnings` on `svelte-check` is the whole of the `FE-R17` gate.** Without the flag it
  exits 0 on every accessibility warning. eslint does not widen it: `eslint-plugin-svelte` ships no
  a11y rules. See ADR 0013 gap #9 for what is still uncovered — measured, not assumed.
- **Nothing is read from the environment at build time.** `GATEWAY_URL` (ADR 0012 §4) and `ORIGIN`
  (ADR 0015 §3) are request-time values; `$env/static/private` would bake them into the artifact and
  reproduce the scar the Next.js image still carries.

## Not here yet

Login, the session module and the gateway proxy layer (ADR 0014), and the intake contract path.
`GET /healthz` currently reports liveness only — ADR 0014 requires it to fail when the cookie
encryption key is missing, and that lands with the session module.
