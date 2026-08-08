# W3 Code Plan — eligibility assistant portal surface + backfill record

> Status: GATED 2026-08-07
> Plan maturity only. Delivery state (implemented, pushed, merged) lives in
> `docs/workflow/w3/pr-body.md`; the impl gate does not touch this header.
> Workflow stage 3 (code plan). Anchors to the frozen spec `docs/workflow/w3/spec.md`
> (W3-SPEC-1..24, AGREED 2026-08-07). Requirements: `docs/workflow/w3/requirements.md`
> (AGREED 2026-08-06).
>
> **Gate record — 2026-08-07, gated fresh-context (round 2).** All 24 SPEC ids carry a
> verdict; scope map closes both ways; plan facts re-read from the working tree this
> session. Round-1 findings confirmed fixed (D14 defined in `docs/specs-deprecated/w8.md:7`;
> authz parity pin at `tests/test_gateway_authz.py::test_roles_yaml_matches_enforced_map`
> `:66`).
> **Residual-named SPECs inherited by implementation and review:** W3-SPEC-10 (phase, not
> total, wall-time bound), W3-SPEC-11 (an unexpected exception escapes `_verify_eligibility`
> → 500 post-commit), W3-SPEC-12 (`unverified` is response-only; no end-to-end `POST /intake`
> test), W3-SPEC-13 (RIV-141 bounded, not eliminated), W3-SPEC-17 (chat-surface half only;
> the intake wizard still discards the eligibility field). Plus two accepted
> implementation residuals: the nav entry is visible to roles the gateway will 403, and
> `maxLength=1000` is an unpinned mirror of `AI_VISIT_MAX_MESSAGE_CHARS`.

## Context

W3 is a backfill-of-record item with one new build. The assistant, its visit memory, the
bounded payer path, and the vendor PHI boundary all shipped in the prior engagement
(ADR 0010 / ADR 0011; gateway `POST /ai/visit-chat` at `services/gateway/app.py:990`,
ai-assistant `POST /visit-chat` at `services/ai-assistant/app.py:802`). The one piece never
delivered is a portal screen for it — TODO-44 (`docs/todo.md:67`), W3-REQ-9, the only code
this plan builds. Everything else was verified against `main` on 2026-08-07 (backfill
verification, all 21 backfill SPECs checked with pinning tests); results and findings are
summarized in **Backfill record** below.

**Decisions carried into this plan** (plan-stage, owner-confirmed 2026-08-07):

- **SPEC-21 enforcement is gateway-only.** The gateway already gates `/ai/visit-chat` with
  `require_capability("ai.use")` (`services/gateway/app.py:651,990`; granted to
  `front_desk`/`admin`/deprecated `staff`, denied to `clinician`/`roi_clerk` —
  `config/roles.yaml`, pinned equal to `authz.py` by
  `tests/test_gateway_authz.py::test_roles_yaml_matches_enforced_map` at `:66`). The
  frontend adds **no role list** (an unpinned mirror of `roles.yaml` is the stale-copy
  failure). It handles 401 → login redirect and 403 → explicit fixed "not authorized" state;
  the nav entry is visible to all logged-in roles.
- **Nav: new sixth "Assistant" entry**, route `/assistant`, reusing `IconMessages`
  (`frontend/app/components/icons.tsx:61`). The disabled Messages/Billing stubs
  (`AppShell.tsx:35-38`) stay untouched.
- **Backfill findings land in a separate noncode PR before the feature branch** (owner chose
  over riding the code PR). Scope in **Backfill record**.
- **Verdict presentation is a new dedicated component** (`VerdictBadge`), not `StatusBadge`.
  Forced by the spec's SPEC-18 carry-over note: `StatusBadge.tsx:5-35` maps `unknown`/
  `unverified`/`inactive` → `neutral` while `denied` → `bad` — the exact inversion SPEC-18
  forbids. Extending the shared map instead would silently restyle status rendering on the
  four existing pages that use it.

## Backfill record (verified against `main`, 2026-08-07)

Statements verified with their pinning tests; per the requirements run shape, mismatches are
findings, never spec changes and never code fixes.

**Satisfied:** SPEC-1..9 (chat path, one check per turn, visit context, isolation, sliding
inactivity TTL, grounded verdicts, unknown≠denial, `(connect, read)` bound, typed timeout),
SPEC-12, SPEC-14..16 (breakers, immediate degraded answer, recovery), SPEC-18 (backend:
three independent never-a-denial layers), SPEC-19 (ADR 0010 Accepted, with "Honest limits"
and follow-ups), SPEC-23/24 (closed-vocabulary vendor boundary; `tests/test_visit_chat_phi.py`
adversarial suite incl. the prompt byte-identity test at `:239`).

**Findings** (to file in the noncode PR, after checking each against the registries —
several are already ADR/debt-log-documented and need at most a pointer, not a new row):

1. **SPEC-10 partial** — timeouts bound each network *phase*, not total wall time; a
   trickling payer can exceed the 6s design budget. ADR 0010 says so itself
   (`adr/0010-eligibility-resilience.md:246-251`).
2. **SPEC-11 partial** — eligibility never *rejects* a registration, but an unexpected
   exception escapes `_verify_eligibility` (`services/intake-service/app.py:205-213`,
   `try/finally` with no `except`) → 500 after the patient commit, before consents.
   Pinned as intended by `tests/test_intake_breaker.py:469` — report, do not fix.
3. **SPEC-13 partial** — RIV-141 is bounded, not eliminated (`workers × 3` slow calls
   possible); already self-documented (`adr/0010:320-326`, `docs/debt-log.md:100-108`).
4. **SPEC-12 residuals** — "unverified" is response-only (nothing writes
   `insurance_coverages.status`, `adr/0010:153-157`); no test drives `POST /intake`
   end-to-end (all call `_verify_eligibility` directly).
5. **SPEC-17 partial** — backend surfaces comply; no front-desk surface renders any of it.
   The chat surface (this plan) closes the REQ-9 half; the intake wizard still discards the
   eligibility field (`frontend/app/intake/page.tsx:108-114`) — residual, not W3 scope.
6. **Traceability** — D13/D14 gate the whole vendor-egress path yet have no
   `docs/debt-log.md` rows. D14 *is* defined — fake de-identification,
   `docs/specs-deprecated/w8.md:7` (also `:20`, `:48`, `w10.md:46`) — but only in the
   deprecated spec archive; ADR 0011 cites a stale "CLAUDE.md §9". File D13 and D14 rows
   (D14 definition sourced from the archive); stale citations go to TODO-52.

## Scope map (spec → change)

| SPEC | Change |
|------|--------|
| W3-SPEC-1..10, 12..16, 19, 23, 24 | none — backfill verified; findings 1-4, 6 → noncode PR |
| W3-SPEC-11 | none — verified (reworded statement holds); finding 2 → noncode PR |
| W3-SPEC-17 | chat surface renders explicit unverified/pending verdict tones (residual: intake wizard, finding 5) |
| W3-SPEC-18 | `VerdictBadge` with its own tone map + negative test; `StatusBadge` untouched |
| W3-SPEC-20 | `/assistant` page + `/api/ai/visit-chat` proxy route + nav entry |
| W3-SPEC-21 | gateway capability gate (exists, verified); frontend 401/403 handling + negative test |
| W3-SPEC-22 | deterministic fixed-string fallback driven by response tri-states and error statuses + negative test |
| — | registry upkeep in code PR: close TODO-44 |

## Implementation

### 1. Proxy route (W3-REQ-9 / SPEC-20)

New `frontend/app/api/ai/visit-chat/route.ts` — byte-for-byte the shape of
`app/api/ai/intake-instructions/route.ts`:

```ts
import { NextRequest } from "next/server";
import { proxy } from "@/app/lib/gateway";

export async function POST(req: NextRequest) {
  const body = await req.json();
  return proxy(req, "/ai/visit-chat", { method: "POST", body });
}
```

`proxy` forwards the caller's `Authorization` header (`app/lib/gateway.ts:15-16`) and relays
upstream status codes verbatim, so gateway 401/403/404/422/429/502/503 reach the client
untouched.

### 2. Chat page (W3-REQ-9 / SPEC-20..22, SPEC-17/18 surface half)

New `frontend/app/assistant/page.tsx`, `'use client'`, following the codebase's only
pattern (every page is a client component because the token lives in `localStorage` and
`gateway.ts` authenticates by forwarding the browser's header — a server component cannot
reach the gateway). Prior art: `intake/page.tsx:128-163` (`fetchInstructions`) for the
fetch/validate/fixed-string triple, `login/page.tsx:31` for the form submit pattern.

- **State:** `visitId: string | null`, `turns: {role, text, verdict?}[]` (local render
  only — the server holds no transcript and neither do we beyond the session), `input`,
  `busy`, `notice`.
- **Submit:** `apiFetch("/api/ai/visit-chat", …)` with `{ message, ...(visitId && { visit_id: visitId }) }`.
  Echo the returned `visit_id` on every later turn; when it comes back `null`
  (`visit_memory: "unavailable"`), drop it and let the next turn start a fresh visit.
  Textarea `maxLength={1000}` with a comment citing `AI_VISIT_MAX_MESSAGE_CHARS` — an
  unpinned mirror, accepted: drift costs a handled 422, not a broken surface.
- **200 handling:** validate shape (`typeof data.reply === "string"`); render `reply` and
  `disclaimer`; render `eligibility` (object | null) through `VerdictBadge` (§3).
  `assistant: "degraded"` and `visit_memory: "stale"` are **successful turns**, not errors —
  render the reply plus an `rb-alert--info` notice ("assistant is degraded" / "context may
  not have saved"), never `rb-alert--err`.
- **Fallback (SPEC-22):** every non-200 and every network/shape failure produces a fixed,
  client-authored, non-PHI string per the established convention (`intake/page.tsx:154,159`
  — never render the server's message):
  - 401 → `clearSession()` + redirect `/login` (AppShell's existing unauthenticated
    behavior, `AppShell.tsx:81-88`).
  - 403 → "Your role isn't authorized for eligibility work." — chat input stays disabled
    thereafter (SPEC-21).
  - 404 → drop `visitId`, "That conversation has expired — starting a new one."
  - 429 → "The assistant is busy — try again in a moment."
  - 422 / 502 / 503 / network / bad shape → "The assistant is unavailable right now.
    Coverage can still be checked directly with the payer." (deterministic, no PHI, no raw
    error text).
- **Nav:** add `{ href: "/assistant", label: "Assistant", icon: <IconMessages … /> }` to
  `NAV` (`AppShell.tsx:27-33`).

### 3. VerdictBadge (W3-REQ-7 carry-over / SPEC-17, 18)

New `frontend/app/components/VerdictBadge.tsx`: maps `eligibility.status` to the existing
`rb-badge--*` classes (no CSS change) with its own labels — the map is the point:

| status | variant | label |
|--------|---------|-------|
| `active` | ok | Coverage active |
| `inactive` | bad | No active coverage (payer-confirmed) |
| `unknown` | warn | Unverified — not a denial |
| `pending` | warn | Pending verification — not a denial |
| anything else / null | render nothing | |

Invariants (each a test): `unknown`/`pending` never map to the `bad` variant and never to
`neutral` (SPEC-18 — unverified is neither a denial nor quieter than one); only `inactive`
may render `bad`; an unrecognized status renders nothing rather than guessing. The
authoritative prose (with its `checked_at` stamp) is the server-rendered `reply`; the badge
is a tone signal, not a second source of truth.

### 4. Tests (SPEC-18, 20..22; landmines §3 negative-test rule on the authz/PHI-adjacent path)

Colocated Vitest + RTL, spec IDs in `it()` titles (e1 convention,
`StatusBadge.test.tsx` as exemplar; the default glob picks them up, no config change).

- `VerdictBadge.test.tsx` — the table above, plus the negative invariants.
- `assistant/page.test.tsx` — mock `apiFetch` (module-mock `@/app/lib/session`):
  happy path renders reply + disclaimer + badge; `visit_id` echoed on turn 2; `null`
  `visit_id` resets; **403 → fixed not-authorized string, input disabled, no retry fires
  (SPEC-21 negative)**; **network reject and 503 → the fixed fallback string, and the
  server-supplied error text is asserted absent (SPEC-22 negative)**; degraded 200 renders
  the reply, not an error.

## Files touched

| File | Change |
|------|--------|
| `frontend/app/api/ai/visit-chat/route.ts` | new — proxy |
| `frontend/app/assistant/page.tsx` | new — chat surface |
| `frontend/app/assistant/page.test.tsx` | new — surface tests incl. negatives |
| `frontend/app/components/VerdictBadge.tsx` (+ `.test.tsx`) | new — verdict tone map |
| `frontend/app/components/AppShell.tsx` | one `NAV` entry |
| `docs/todo.md` | TODO-44 → closed (registry upkeep, code PR) |
| *(separate noncode PR, before the branch)* | backfill findings 1-6 per **Backfill record** |

No Python, no schema, no compose, no CI change (the `frontend` job already runs
build/typecheck/lint/test on these paths; `frontend-boot` unaffected).

## Out of scope (from requirements §6)

Last-known-good eligibility cache (owner cut 2026-08-06); register-first async
re-verification (stays ADR 0010's recorded follow-up); fixing the intake contract break
(TODO-1); Redis hardening (D3b); BAA / Safe-Harbor scrub (W8); gateway `proxy_intake`
migration off `_post`; additional agent tools or multi-agent shapes; widening pinned
timeout/breaker values.

## Verification (end-to-end)

1. **Backfill re-run:** `make test-docker` green at the baseline
   `821 passed, 1 xfailed, 5 deselected` (counts are load-bearing; a moved count is a
   finding). Covers every pinning test cited in the Backfill record (SPEC-1..19, 23, 24).
2. **Frontend gates:** `cd frontend && npm install && npm test` green;
   `npm run typecheck && npm run lint && npm run build` green (SPEC-20 artifacts pass the
   e1 gates).
3. **Negative, harness:** invert `VerdictBadge`'s `unknown` mapping to `neutral` → the
   SPEC-18 invariant test goes red; revert. Point the page's fallback at the server's error
   text → the SPEC-22 absence assertion goes red; revert.
4. **Live happy path:** `make up`; login as seed `frontdesk` (role `front_desk`,
   `db/seed/generate_seed.py:82`); open `/assistant`; send a message with a seeded member
   id → verdict line + badge render; follow-up "is it still active?" → answered from visit
   context, same `visit_id` (SPEC-1, 3, 20).
5. **Live 403 (SPEC-21 negative):** login as seed `drpatel` (role `clinician`,
   `generate_seed.py:85`); `/assistant` send → fixed not-authorized string, no chat.
6. **Live fallback (SPEC-22):** `docker compose stop ai-assistant`; send → deterministic
   fixed fallback, no raw error body rendered; restart.
7. **Live degraded tones (SPEC-17/18):** `docker compose stop eligibility-service`; send a
   member-id message → `unknown`/`pending` renders the warn "not a denial" treatment,
   visibly distinct from the `inactive` denial treatment.
8. **PHI spot check:** during 4-7, gateway and ai-assistant logs show metadata-only lines
   (class-name idiom), no message text, no member id (SPEC-23 adjacency; the boundary
   itself is backend-verified).
9. **Defects intact:** registration still 422→200→false-success (TODO-1 untouched);
   `tests/test_compose_topology.py` green.

## Landmines / risk

- **§1 zones: none edited.** Auth untouched (SPEC-21 is the existing gateway gate,
  owner-ruled); PHI columns, ROI, migrations, secrets untouched. The surface is
  *adjacent* to the `/ai/*` vendor-egress human-gate (D13/D14): it feeds an existing gated
  path and moves no boundary — clerk text still terminates at ai-assistant, never the
  vendor (`tests/test_visit_chat_phi.py:239` pins it).
- **Accepted residuals:** SPEC-10/11/12/13 partials + SPEC-17's intake-wizard half —
  filed as findings (noncode PR), never fixed here; deliberate defects preserved.
  SPEC-21's nav entry is visible to unauthorized roles (enforcement is server-side;
  owner-ruled). `maxLength=1000` is an unpinned mirror of `AI_VISIT_MAX_MESSAGE_CHARS`
  (drift → handled 422).
- **Version caveat:** none new; `next lint` deprecation churn already recorded in e1.
- **PR body "Risk & landmines" line:** "No §1 zone edited; surface is D13/D14-adjacent
  (existing gated path, boundary unmoved); deliberate defects incl. TODO-1 preserved;
  backfill residuals filed via noncode PR."

## Three checks (run 2026-08-07)

- **Self-consistency:** all new files are `.tsx`/`.ts` under the e1 gates — tests import
  `describe`/`it`/`expect` explicitly (no globals, per e1 decision), colocated names match
  Vitest's default glob, `VerdictBadge` reuses existing `rb-badge--*` classes so no CSS
  gate or drift, the page is a client component so `next build` has no server-data path to
  break, and the proxy route mirrors a file already passing every gate.
- **Gate interaction:** `next build` type-checks and lints the new files before the
  dedicated `typecheck`/`lint` CI steps — a violation reddens the build step first (known
  e1 attribution note, no new consequence). `frontend-boot` polls `/healthz` only.
- **Residual honesty:** the scope-map rows for SPEC-10..17 do not claim coverage the code
  lacks — partials are named findings; SPEC-17's row claims only the chat-surface half.
