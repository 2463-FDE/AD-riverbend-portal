# W3 PR body — eligibility assistant portal surface

> Status: MERGED PR #58 2026-08-07 (squash `f69a554`)
>   DRAFT -> IMPLEMENTED 2026-08-07 -> PUSHED PR #58 2026-08-07 -> MERGED 2026-08-07
>
> **Review record — PR #58, 4 rounds, closed dry.** r1 2 findings, r2 1, r3 1 — all
> **A, fixed** on branch (`7b5d7d2`, `997a042`, `700fa5c`); r4 dry, verdict `approve`.
> Squash-merged to `main` as `f69a554`, branch deleted. Round log:
> `docs/workflow/w3/findings.md` §Review; ledger lines in `docs/review-loop-metrics.md` §4.
> No fix this loop introduced state, so none went back to stage 3 — spec stays AGREED,
> plan stays GATED, both unamended by the review. Residuals below are unchanged by it.
>
> **Impl-gate record — 2026-08-07, impl-gated fresh-context.** Branch
> `feat/noref-w3-assistant-surface` @ `dc92fc5`. Re-run this gate session:
> `make test-docker` → `821 passed, 1 xfailed, 5 deselected` (exact pinned baseline,
> no count moved); frontend `npm test` → 20 passed, `typecheck`/`lint`/`build` green,
> `/assistant` and `/api/ai/visit-chat` both in the route manifest. Scope map closed
> both ways (types.ts = Deviation 1, additive-only confirmed); planted defects intact;
> no landmines §1 zone in the diff; no `Co-Authored-By` trailer. Residuals accepted at
> this gate: the plan's named set unchanged (SPEC-10/11/12/13/17 partials, nav visible
> to unauthorized roles, unpinned `maxLength` mirror) plus Deviations 1–4 as recorded —
> nothing new. Live-run evidence (Bedrock happy path, 403, 503, tones, PHI log grep)
> accepted from the implementation session's record; not re-run.
>
> Delivery state for W3 lives on this header (spec stays AGREED, plan stays GATED).
> Draft written by the stage-4 implementation session; the impl gate reads it from the
> working tree. Landed on `main` via `noncode-merge`, never cherry-picked onto the code
> branch.
>
> Branch: `feat/noref-w3-assistant-surface`

---

## Overview

W3's eligibility assistant has been running behind `POST /ai/visit-chat` since the prior
engagement with no way for the front desk to reach it — TODO-44, and the only code W3's
plan builds. This adds the surface: a `/assistant` chat screen, its proxy route, and a
sixth nav entry. Everything else in W3 is backfill of record, verified against `main` on
2026-08-07 and filed as findings in PR #57 (noncode); nothing in this PR re-litigates it.

| Method | Path | Returns |
|--------|------|---------|
| POST | `/api/ai/visit-chat` (portal) | relays gateway `POST /ai/visit-chat` verbatim — status and body untouched |

No backend change. No new gateway route, no schema, no compose, no CI change.

Refs: W3-SPEC-17, 18, 20, 21, 22 · TODO-44 · `docs/workflow/w3/plan.md`

## Behavior

**The chat surface (W3-SPEC-20).** `frontend/app/assistant/page.tsx` is a client component,
like every page in this portal, because the token lives in `localStorage` and `gateway.ts`
authenticates by forwarding the browser's header. It holds `visit_id` and a render-only
transcript: the gateway persists metadata only (ADR 0011 §3) and never the prose, so a
refresh legitimately starts a blank screen on a visit the gateway still remembers. The
returned `visit_id` is echoed on every later turn; a `null` one (`visit_memory:
"unavailable"`) is dropped so the next message opens a fresh visit rather than 404-ing.

**A separate verdict badge, not the shared one (W3-SPEC-18).** `StatusBadge`'s map renders
`unknown`/`unverified`/`inactive` as `neutral` while `denied` is `bad` — an unverified
outcome reads *quieter* than a denial, the exact inversion this spec forbids. `VerdictBadge`
gets its own map (`active`→ok, `inactive`→bad, `unknown`/`pending`→warn) and an unrecognised
status renders nothing rather than guessing a tone. Extending the shared map instead would
have restyled the four pages already using it. Both components stay; the new tests say why.

**Degraded is a successful turn, not an error (W3-SPEC-17).** `assistant: "degraded"` and
`visit_memory: "stale"` ride a real answer, so they render as `rb-alert--info` notices under
the reply, never as `rb-alert--err`. Rendering them as failures would train the desk to
ignore the surface on the days it matters most.

**Deterministic fallback, and the upstream body is never read (W3-SPEC-22).** On any non-2xx
the page switches on the status code alone — it does not parse or touch the response body —
so there is no route by which a payer host, an internal URL, or the clerk's own text comes
back through an error. 401 clears the session and returns to `/login`; 403 states the
refusal and disables the input; 404 drops the visit id; 429 names the retry; everything else
(422/502/503/network/bad shape) gets one fixed non-PHI string.

**No role list in the frontend (W3-SPEC-21).** `ai.use` is enforced at the gateway only
(`config/roles.yaml`, pinned equal to `authz.py` by
`tests/test_gateway_authz.py::test_roles_yaml_matches_enforced_map:66`). The portal adds no
copy of it — an unpinned mirror of the role map is the stale-copy failure. The nav entry is
therefore visible to every signed-in role, and an unauthorized one is told so by the 403
handler (owner-ruled residual, below).

## Wiring

`frontend/app/api/ai/visit-chat/route.ts` is byte-for-byte the shape of the existing
`app/api/ai/intake-instructions/route.ts`: `proxy()` forwards the caller's `Authorization`
header and relays the upstream status verbatim, so gateway 401/403/404/422/429/502/503 reach
the client untouched. One `NAV` entry added in `AppShell.tsx`, reusing `IconMessages`; the
disabled Messages/Billing stubs are untouched.

## Risk & landmines

**No `docs/landmines.md` §1 zone edited.** Auth untouched — W3-SPEC-21 is the existing
gateway capability gate, owner-ruled as gateway-only enforcement. PHI columns, ROI/disclosure
logic, migrations, and secrets untouched. No schema change, so no `db/migrations/` entry is
due.

The surface is **adjacent** to the `/ai/*` vendor-egress human-gate (D13/D14): it feeds an
existing gated path and moves no boundary. Clerk text still terminates at ai-assistant and
never reaches the vendor — `tests/test_visit_chat_phi.py:239` pins the prompt byte-identity
that makes that true, and it is green here.

**No PHI added to logs, error bodies, or fixtures.** The page logs nothing. The fixed
fallback strings are client-authored and carry no patient data. Two tests assert the
*absence* of server-supplied text after a 503 and after a network failure — the leak class,
not just the happy path. Live log spot-check during the runs below: gateway and ai-assistant
printed metadata only (`{"intent": "check_eligibility", "eligibility_status": "unknown",
"turn_count": 0}`) — no message text, no member id.

**Deliberate defects preserved.** TODO-1 (registration 422→200→false success) is untouched;
no file on the intake path was edited. `tests/test_compose_topology.py` green.

### Accepted residuals (carried from the plan's Landmines section, disclosed not rediscovered)

- **W3-SPEC-10 partial** — timeouts bound each network *phase*, not total wall time; a
  trickling payer can exceed the 6s design budget (ADR 0010 says so itself).
- **W3-SPEC-11 partial** — eligibility never *rejects* a registration, but an unexpected
  exception escapes `_verify_eligibility` → 500 after the patient commit, before consents.
  Pinned as intended by `tests/test_intake_breaker.py:469`.
- **W3-SPEC-12 residuals** — `unverified` is response-only (nothing writes
  `insurance_coverages.status`); no test drives `POST /intake` end-to-end (TODO-55).
- **W3-SPEC-13 partial** — RIV-141 is bounded, not eliminated (`workers × 3` slow calls).
- **W3-SPEC-17 partial** — this PR closes the chat-surface half only; the intake wizard still
  discards the eligibility verdict (TODO-56). Out of W3 scope by the plan.
- **Nav visible to unauthorized roles** — enforcement is server-side; hiding the entry would
  need a duplicated role→capability map or a backend capability field that does not exist
  (TODO-54). Owner-ruled.
- **`maxLength={1000}` is an unpinned mirror** of `AI_VISIT_MAX_MESSAGE_CHARS`
  (`services/gateway/config.py:153`). Drift costs a handled 422 rendered as the fallback, not
  a broken surface.

All six backfill findings were filed in the registries by PR #57 before this branch, per the
plan's decision to keep them off the code PR.

## Verification

**`make test-docker`**: `821 passed, 1 xfailed, 5 deselected` — exactly the `CLAUDE.md` §6
pinned baseline. No count moved; this branch adds no Python test and touches no Python.

**`npm test`** (frontend/): `20 passed` (was 2). +18 from this branch — 7 in
`VerdictBadge.test.tsx`, 11 in `assistant/page.test.tsx`. **`npm run typecheck`**: clean.
**`npm run lint`**: clean (one pre-existing `DateField.tsx` a11y warning, untouched).
**`npm run build`**: green; `/assistant` and `/api/ai/visit-chat` both in the route manifest.

**`make eval`**: not run — nothing under `eval/rag/` or the retrieval path changed.

**Negative harness, break-then-revert** (plan Verification 3), both confirmed:
- Inverted `VerdictBadge`'s `unknown` mapping to `neutral` → 2 tests red, including the
  W3-SPEC-18 invariant. Reverted.
- Pointed the page's non-2xx path at the server's `detail` string → 5 tests red, including
  both W3-SPEC-22 absence assertions. Reverted.

**Live, against the full stack — production frontend image on the published port 3070**, not
a dev server. `docker compose build frontend` from this branch, container healthy, `/healthz`
200 and `/assistant` 200 (the same path CI's `frontend-boot` job polls). Browser-driven.

- **W3-SPEC-20, happy path (plan Verification 4)**: signed in as seeded `frontdesk`, sent a
  message naming seeded member `BCBS4471` → real `200` through gateway → ai-assistant → a
  real Bedrock call (`llm call model=claude-sonnet-4-6 in_tokens=666 cost=$0.0023`). Reply,
  disclaimer and verdict badge all rendered. Follow-up "Is it still active?" → the browser
  echoed `visit_id` `5bcc80f1…` on turn 2 and the second answer came back from visit context.
  ai-assistant's own metadata log proves both spec claims underneath it:
  `{"intent": "ask_status", "eligibility_status": "unknown", "turn_count": 2,
  "checked": false}` — turn count grew (W3-SPEC-3, visit context in use) and the turn issued
  **no** second payer check (W3-SPEC-2, at most one check per turn).
- **W3-SPEC-17/18 tone, live (plan Verification 7)**: the verdict came back `unknown` and
  rendered as the amber "UNVERIFIED — NOT A DENIAL" badge, with the assistant's own prose
  saying "This is a failed check, not a denial." Repeated with
  `docker compose stop eligibility-service`: still a `200`, still the warn tone, still not an
  error — then restarted, stack healthy.
- **W3-SPEC-21 negative**: signed in as a `clinician` (`drnguyen` — see Deviation 3), sent a
  message → real gateway `403` → "Your role isn't authorized for eligibility work.",
  `textarea disabled: true`, `send disabled: true`, and the second turn could not be issued at
  all (Playwright times out against a disabled control — the retry genuinely cannot fire).
  The gateway's own words never rendered: asserted absent in the page text.
- **W3-SPEC-22**: verified earlier in the session against a real `503` — before the
  environment was repaired, ai-assistant answered 503 on every turn, and the surface showed
  the fixed fallback string with no raw error body.
- **PHI spot check (plan Verification 8)**: across every run, gateway and ai-assistant logged
  metadata only — `{"intent": …, "eligibility_status": …, "turn_count": …, "checked": …}`.
  Grepped both services' logs for the message text and the member id: no hits.
- **Nav**: "Assistant" renders as the sixth primary entry and marks active on `/assistant`.

**One tone pair is not live-verifiable on this repo, by design.** `PAYER_API_URL` is
`https://edi.example.com/v1/eligibility` — a fictional host — so every real eligibility check
fails to `unknown`. `active` and `inactive` verdicts cannot be produced against the real
payer path here at all; this is a property of the training repo, not a credential or config
gap, and no amount of environment repair changes it. Those two tones are covered by
`VerdictBadge.test.tsx` and by a scratch stub upstream (outside the repo) driven through the
real proxy route and the real page over HTTP: `active` → green "Coverage active", `inactive`
→ red "No active coverage (payer-confirmed)", visibly distinct from the amber unverified
treatment, which is the W3-SPEC-18 claim.

**Environment repair performed during verification, recorded because it changed the stack.**
The live checks first failed for reasons unrelated to this branch, and fixing them touched
running infrastructure but no tracked file:
1. `AWS_BEARER_TOKEN_BEDROCK` was expired; the owner supplied a fresh one directly in `.env`.
2. `.env.ai-proxy` and `.env.redis` both held **empty** secrets on disk while the containers
   ran on values loaded days earlier, so the first container recreate fail-closed
   (`REDIS_PASSWORD is unset or a placeholder — refusing to use an unauthenticated Redis`,
   D3b). Both regenerated; `.env.redis` via the Makefile's own rule after moving the empty
   file aside. Sessions and visit memory were dropped; no patient data involved.
3. The `ai-assistant` and `frontend` images were stale. The running ai-assistant predated the
   `assistant` health field, which is why every turn reported `assistant: "unknown"` — correct
   version-skew behaviour from `_assistant_health`, not a defect. The running frontend
   predated e1's `/healthz`, so its healthcheck was failing (404) before this branch existed.
   Both rebuilt; after the rebuild ai-assistant reports `assistant: "ok"` and the frontend
   container is healthy.

None of the above is a repo change and none of it is in this diff. One follow-up worth
filing separately (**not** on this branch, per the plan's scope map): `make up` regenerates
`.env.redis` only when the file is *absent*, so an existing-but-empty file leaves the stack
fail-closed with no self-repair, and the documented recovery lives in a comment inside the
very file that gets overwritten.

## Slices, test-first or not

- **`VerdictBadge` + tests** — test-first (red on the missing module, then per-invariant).
- **`/assistant` page + tests** — test-first (11 tests written and red before the page).
- **Proxy route** — not test-first. No behavioural seam: it is a six-line mirror of an
  existing route that every gate already covers, and the plan's §4 lists no test for it.
- **Nav entry** — not test-first. One-line config array; covered by the live nav check above.
- **`docs/todo.md` TODO-44 close** — registry upkeep, no test.

## Deviations from the plan

1. **`frontend/app/lib/types.ts` edited — a file the plan's "Files touched" table does not
   list.** `EligibilityVerdict` and `VisitChatResponse` were added there rather than declared
   inline, matching that file's stated role ("shared types mirroring the Riverbend gateway
   API contract") and how every other portal response shape is declared. Additive only; no
   existing type changed. Plan-fact gap, fix trivial.
2. **Tests call `cleanup()` explicitly.** RTL registers auto-cleanup only under Vitest
   globals, and this project deliberately runs without them (e1: tests import their own
   `describe`/`it`/`expect`). Without it, renders accumulate across cases and a role query
   matches the previous test's node — which is how it was found. Both new test files declare
   `afterEach(cleanup)`; the shared `vitest.setup.ts` was left alone so the change stays
   inside files the plan lists. Worth folding into the setup file if a third test file lands.
3. **The live 403 check used `drnguyen`, not the plan's `drpatel`.** The plan cited
   `db/seed/generate_seed.py:85`, which is correct for a *fresh* volume; this machine's
   Postgres volume predates ADR 0017's role assignment, so `drpatel` is still `staff` there
   (and `staff` holds `ai.use`, hence a 503 rather than a 403). `drnguyen` is `clinician` in
   the live volume. The seed file itself says only a fresh volume picks the values up — a
   plan fact that is right about the file and wrong about this machine.
4. **Plan Verification 4's `active` verdict was not obtainable and never will be here.** The
   step assumed a seeded member id yields a verdict line; the seeded ids exist, but
   `PAYER_API_URL` points at the fictional `edi.example.com`, so every check resolves to
   `unknown`. The step ran and passed on everything else it asserts (round trip, badge,
   follow-up on the same `visit_id`); only the verdict *value* differs from what the plan
   pictured. See the Verification section.

## Planned scope absent from the diff

None. Every row of the plan's scope map with a change is in the diff. The rows marked "none —
backfill verified" produce no code by design, and their findings landed in PR #57.

## Impact

Closes TODO-44 — both AI features now have a portal surface, and W3's client ask ("a little
chat assistant for the front desk") is on screen. Leaves open, all filed: the intake wizard's
discarded verdict (TODO-56), the two backend-exposure candidates the mockup wanted (TODO-54),
the missing `POST /intake` endpoint test (TODO-55), and a happy-path run against a live payer
once a working Bedrock credential is available.
