# E5 Code Plan — the gateway/portal error contract, and registration idempotency

> Status: GATED 2026-08-11
> Gate record: gated fresh-context 2026-08-11, round 4 (`findings.md` §Gate) — full re-run
> against the amended spec; rounds 1–3 dispositions verified in place, round-3 owner
> overrules honored. Residual-named SPECs, accepted and carried into implementation:
> E5-SPEC-30/31 (a replay re-verifies eligibility — one extra payer hop, D-14),
> E5-SPEC-33 (the bounded-wait expiry answers imprecisely, D-11; `lock_timeout` must be
> proven at verification step 12, with the `statement_timeout` fallback recorded as a
> decision if taken), E5-SPEC-34 (submission identifiers retained forever, D-7),
> E5-SPEC-40 (a portal-bug rejection renders in the correctable-at-the-desk branch, D-10).
> Plan maturity only. The plan header never carries delivery state (IMPLEMENTED, pushed,
> merged) — that lives in `docs/workflow/e5/pr-body.md`. The impl gate does not touch
> this header.
> Workflow stage 3 (code plan). Anchors to the frozen spec `docs/workflow/e5/spec.md`
> (E5-SPEC-1..40, AGREED 2026-08-11; amended 2026-08-11 and re-frozen — E5-SPEC-8 only).
> Requirements: `docs/workflow/e5/requirements.md` (AGREED 2026-08-10, amended 2026-08-11).
> Revised 2026-08-11 after gate round 1 (`findings.md` §Gate): the zero-caller search
> scoped to the gateway helpers, the portal measurements corrected at source, the patient
> chart read added per amended E5-SPEC-8, and the plan's decision ids renumbered
> (D-12..D-17 → D-13..D-17) because the spec amendment allocated D-12; the spec is frozen
> and this plan is DRAFT, so the plan yields the id.
> Revised 2026-08-11 after gate round 2: the owner approval for the whole thirteen-route
> gateway conversion — recorded at requirements/spec stage — is now carried in Context and
> Landmines, per the e4 precedent; previously only the ROI subset and the chunk-2 migration
> named their gate.
> Revised 2026-08-11 after gate round 3 (both findings owner-overruled as blockers, corrected
> anyway): two scope-map cites fixed — E5-SPEC-38/39's negative tests are §13 not §12, and
> E5-SPEC-19's carrier is the Landmines PR-body bullet plus verification step 9, not §5.

## Context

e4 converted **one** gateway route (`proxy_intake`) off the inherited error-swallowing proxy
helpers and froze the error contract that conversion produces. Thirteen call sites remain, and
they are the rest of D4's open half: eight `_get` (`services/gateway/app.py:264, 307, 312, 319,
335, 347, 354, 377`) and five `_post` (`:359, 366, 382, 389, 1239`), spanning eligibility,
records, scheduling, ROI and interop. `_post`/`_get` (`app.py:1249-1264`) collapse every
downstream and transport failure into a **200 OK** `{"error": str(e)}` body and log `str(e)`.

The conversion targets already exist and are in production use: `_get_checked` (`:1267`) and
`_post_checked` (`:1299`) relay downstream status, map transport failures to typed 502/504, and
log the exception **class** only. Four routes are already on them. **This is repointing, not
design.**

The portal half is not optional. Six inherited `apiFetch` call sites check no response status
and coerce any non-list body to an empty result — `frontend/app/roi/page.tsx:50-52`,
`frontend/app/appointments/page.tsx:31-33` and `:42-45`, `frontend/app/page.tsx:39-42` and
`:44-51` (`d.items ?? []`), and `frontend/app/records/page.tsx:78-83` (the chart read,
`json.encounters ?? []` then "No records found for this patient."). A converted gateway sends
`{"detail": …}`, which is as non-list as `{"error": …}`, so without the portal change an outage
still renders as "you have none". The in-tree pattern to imitate is
`frontend/app/records/page.tsx:96-113` (`!res.ok` → shape guard → explicit failed state) — the
sibling function twenty lines below the unchecked chart read; 10 of 17 non-test `apiFetch` call
sites already check status (the seventh unchecked site is the logout write, out of scope per
requirements §6).

Chunk 2 closes the *residual on the residual* recorded at `docs/debt-log.md:143-146` and in the
`intake-service` module docstring (`services/intake-service/app.py:36-38`): `POST /intake`
commits the registration and then evaluates the match key and verifies eligibility on the same
request thread (`app.py:132-144`), so a lost response leaves a committed chart while the portal
correctly tells the operator nothing was saved (E4-SPEC-7). The operator retries; there is no
idempotency key and no uniqueness guard, so a second chart is created with its own coverage and
consent rows. This is an inherited defect e4 made *reachable*, not e4's breakage.

**What this must not touch:** e4's frozen response contract and its four portal result branches
(E4-SPEC-6, E4-SPEC-7); D11 (four converted routes sit in its exposure set); D5 and D5b; the
`ConsentKind` closed enum; ADR 0010's pinned budgets.

**Approval-gated zones deliberately touched, owner-approved before this stage and carried here**
(the e4 precedent — its plan carried the gateway-zone approval from requirements stage,
`docs/workflow/e4/plan.md:41-43`): **gateway error handling, the whole thirteen-route
conversion** — not only its ROI subset — is the touch `docs/landmines.md` §1 gates ("migrating
them is approval-gated and scheduled as `e5`", the intake-registration bullet, `:87`). The
recorded approval is the chain of owner acts whose sole subject is this migration: e4
requirements D-3 (owner, the estate conversion deferred to the named item `e5`), e5 requirements
AGREED 2026-08-10 carrying E5-REQ-1 as ⚠ human-gate with owner decisions D-2, D-3 and D-4 fixing
its mechanism (`proxy_hl7` stays in, the helpers are deleted, the bound is uniform), and the spec
AGREED 2026-08-11 freezing E5-SPEC-1..4 as ⚠ human-gate statements. Branch A implements only what
those recorded decisions state; a departure from them is drift, not a re-approval question. The
ROI subset and chunk 2's migration zone are named in Landmines below; no other §1 zone is entered.

**Decisions carried into this plan** (plan-stage, owner-confirmed 2026-08-11; numbered on from
the spec's decisions. Renumbered 2026-08-11: the spec amendment allocated D-12, so this plan's
former D-12..D-16 are now D-13..D-17 — the spec is frozen and this plan is DRAFT, so the plan
yields the id. The former plan D-17 — the slot picker counts as part of the appointments
surface, closing the gap between D-8's five call sites and the spec's four-surface enumeration —
is retired, superseded by spec D-12: amended E5-SPEC-8 states universality and names all six
surfaces itself, so no interpretive decision remains to record):

- **D-13 — e5 lands as two branches, chunk 1 first.** Branch A is E5-SPEC-1..23 (gateway
  conversion, portal read surfaces, helper deletion, registry upkeep); branch B is
  E5-SPEC-24..40 (registration idempotency). Requirements D-1 permits this explicitly; the
  chunks share no code and no seam. Chunk 1 is repointing against a known contract, chunk 2 is
  new persisted state in an approval-gated zone — separate PRs keep each review honest.
- **D-14 — a replayed registration re-verifies eligibility.** The original verdict is not
  persisted (D4 residual 3), so it cannot be read back. The replay calls the same bounded,
  breaker-guarded hop the original did and returns its verdict. It writes no record, so
  E5-SPEC-30's "create no further record" holds, and the replay stays indistinguishable from the
  original success, which is D-5's whole point. Cost: one more payer hop, bounded by the
  existing budget.
- **D-15 — the bounded wait is Postgres `lock_timeout` on the registration transaction**, from a
  new `REGISTRATION_LOCK_WAIT_SECONDS` knob (default 5s). The winner's submission row is
  invisible until it commits, so the loser's INSERT blocks on the unique index; a unique
  violation means the winner committed (re-read and replay, E5-SPEC-32), a lock timeout means
  the bound expired (503 into e4's system-failure branch, E5-SPEC-33). No polling.
- **D-16 — `tests/test_gateway_review_queue.py::test_queue_routes_never_use_the_swallowing_helpers`
  is deleted and its claim re-homed.** Deleting the helpers makes it fail at `monkeypatch.setattr`
  and makes its assertion vacuous. Its intent lands as a repo-wide structural check in the new
  e5 gateway test. The baseline moves by −1 plus e5's additions, and the move is stated in the
  PR body rather than absorbed.
- **D-17 — the submission identifier is a client-generated UUIDv4 carried as a required root
  field `submission_id`** on the `POST /intake` request payload, stored as `TEXT` (the estate
  stores everything as `TEXT`). Minted with `crypto.randomUUID()` where available and from
  `crypto.getRandomValues` otherwise — `randomUUID` is secure-context-only, and the portal is
  not guaranteed to be served over https.

## Scope map (spec → change)

| SPEC | Change |
|------|--------|
| E5-SPEC-1, E5-SPEC-2, E5-SPEC-3 | §1 — thirteen call sites repointed to `_get_checked`/`_post_checked`; §6 test asserts relay/502/504/no-`error`-key per route |
| E5-SPEC-4 | §1 — the route set is enumerated in the test, and §2's structural check proves no unconverted route can exist |
| E5-SPEC-5, E5-SPEC-6, E5-SPEC-7 | §4 — six portal call sites get the `records/page.tsx:96-113` tri-state: failed / empty / loaded |
| E5-SPEC-8 | §4 — all six surfaces the amended statement names (spec D-12): ROI queue, appointments list, bookable-slots panel, dashboard appointments, dashboard records, patient chart |
| E5-SPEC-9, E5-SPEC-10 | §1 — the checked helpers already log class-only and never echo URL/query/exception text; §6 pins it per converted route |
| E5-SPEC-11, E5-SPEC-12 | §3 — `PROXY_TIMEOUT_SECONDS = 30.0`, and a new invariant pinning it above eligibility-service's worst-case payer budget |
| E5-SPEC-13, E5-SPEC-14 | §6 — characterization tests first: success status/body relayed unchanged, and the captured downstream call (service, path, params, payload) is identical pre/post |
| E5-SPEC-15, E5-SPEC-16, E5-SPEC-17 | §1 — no `Depends` changes; `tests/test_gateway_authz.py` route→capability pin is untouched and must stay green |
| E5-SPEC-18, E5-SPEC-19 | §1 — `proxy_hl7` → `_post_checked`; the PR body names the outward-facing change (Landmines "PR-body lines required", verification step 9) |
| E5-SPEC-20, E5-SPEC-21 | §2 — `_post`/`_get` deleted after a zero-caller search; structural test pins their absence |
| E5-SPEC-22, E5-SPEC-23 | §5 — registry upkeep across CLAUDE.md, landmines, debt-log, phi-logging-policy, the `_get_checked` docstring |
| E5-SPEC-24, E5-SPEC-25 | §11 — the replay path creates no patient, coverage or consent row |
| E5-SPEC-26, E5-SPEC-35 | §9 — the identifier is minted once per page mount and reused for every re-submission of that attempt |
| E5-SPEC-27 | §8 — `contracts/intake-registration.json` gains `submission_id` on the request side, asserted from both suites |
| E5-SPEC-28 | §10 — `proxy_intake` forwards the body verbatim; test pins id-in == id-out and no minting |
| E5-SPEC-29, E5-SPEC-34 | §7 — `registration_submissions` (UNIQUE `submission_id`, FK `patient_id`), written in `_create_registration`'s transaction; no expiry, no pruning |
| E5-SPEC-30, E5-SPEC-31 | §11 — replay answers 201 with the recorded `patient_id`, same response model, no replay marker (D-14 supplies `eligibility`) |
| E5-SPEC-32, E5-SPEC-33 | §11 — unique violation → re-read and replay; `lock_timeout` expiry → 503 (D-15) |
| E5-SPEC-36, E5-SPEC-37 | §11 — an unrecorded identifier always creates a new chart; `_evaluate_match_key` is unchanged, so the pair is still queued and still not merged |
| E5-SPEC-38, E5-SPEC-39 | §9 — random UUIDv4, derived from no submitted value; §13 negative tests over payload, log line and stored row |
| E5-SPEC-40 | §11 — a missing or malformed identifier is a pydantic rejection (422), so it lands in e4's correctable-at-the-desk branch |
| registry upkeep | §5 — `docs/todo.md` TODO-1's deferral line, TODO-62 for the accepted residual (id re-checked at landing per the collision rule) |

## Implementation

### Branch A — chunk 1: the gateway/portal error contract

#### 1. Repoint the thirteen call sites (E5-SPEC-1..4, 9, 10, 13..18)

`services/gateway/app.py`. Each edit is one line plus the timeout argument. `_get_checked` takes
`(service, path, timeout, params=None)`; `_post_checked` takes
`(service, path, payload, timeout, headers=None)`.

| Line | Route | Becomes |
|------|-------|---------|
| 264 | `proxy_eligibility` | `_get_checked("eligibility", "/eligibility", PROXY_TIMEOUT_SECONDS, params={...})` |
| 307 | `proxy_patients` | `_get_checked("records", "/patients", PROXY_TIMEOUT_SECONDS, params={...})` |
| 312 | `proxy_patient` | `_get_checked("records", f"/patients/{patient_id}", PROXY_TIMEOUT_SECONDS)` |
| 319 | `proxy_records` | `_get_checked("records", f"/patients/{patient_id}/records", PROXY_TIMEOUT_SECONDS)` |
| 335 | `proxy_search` | `_get_checked("records", "/records/search", PROXY_TIMEOUT_SECONDS, params={"q": q})` |
| 347 | `proxy_slots` | `_get_checked("scheduling", "/slots", PROXY_TIMEOUT_SECONDS, params={...})` |
| 354 | `proxy_list_appointments` | `_get_checked("scheduling", "/appointments", PROXY_TIMEOUT_SECONDS, params={...})` |
| 377 | `proxy_roi_list` | `_get_checked("roi", "/roi/requests", PROXY_TIMEOUT_SECONDS, params={...})` |
| 359 | `proxy_book` | `_post_checked("scheduling", "/appointments", payload, PROXY_TIMEOUT_SECONDS)` |
| 366 | `proxy_cancel` | `_post_checked("scheduling", f"/appointments/{appointment_id}/cancel", {}, PROXY_TIMEOUT_SECONDS)` |
| 382 | `proxy_roi_create` | `_post_checked("roi", "/roi/requests", payload, PROXY_TIMEOUT_SECONDS)` |
| 389 | `proxy_roi_fulfill` | `_post_checked("roi", f"/roi/requests/{request_id}/fulfill", {}, PROXY_TIMEOUT_SECONDS)` |
| 1239 | `proxy_hl7` | `_post_checked("interop", "/hl7/ingest", payload, PROXY_TIMEOUT_SECONDS)` |

Nothing else in these route bodies changes: same `Depends(require_capability(...))`, same
service, same path, same params, same payload (E5-SPEC-14, E5-SPEC-15, E5-SPEC-16). The IDOR
comment at `:317-318` and the D11-related comment at `:326-329` stay — they document a
deliberate gap that this change neither closes nor widens (E5-SPEC-17).

`proxy_hl7` gets a short comment naming the outward-facing consequence (E5-SPEC-18, D-9): the
interop service already answers a bad message with 422/413 (`services/interop-service/app.py:44,
47, 55`), and relaying that status is the change — no HL7 ACK/NAK message is constructed.

#### 2. Delete `_post` and `_get` (E5-SPEC-20, E5-SPEC-21)

Order matters, and requirements D-3 makes the search a gate item (`docs/landmines.md` §2's
don't-delete-unused rule). A repo-wide bare-name match is unsatisfiable —
`tests/test_ai_visit_chat.py:172` defines an unrelated module-local `_post(` with ~30 call sites
that match forever — so the search is scoped to the ways the gateway helpers can actually be
reached: a call in the gateway's own source, or an attribute/string reference to the module
object elsewhere. The deletion lands only once **both** return nothing:

- `rg -n '\b_post\(|\b_get\(' services/gateway/ | rg -v 'def _'` — no call site left in the
  gateway source (the two `def` lines are what the deletion removes);
- `rg -n '\._post\b|\._get\b|"_post"|"_get"|'\''_post'\''|'\''_get'\''' services/ frontend/ tests/ eval/`
  — no attribute access and no string-keyed reference (the `monkeypatch.setattr(gw, "_post", …)`
  shape) anywhere else. Measured this session: the only matches are the six monkeypatch lines
  removed below.

`_clean` stays — `_get_checked` calls it.

Three test sites monkeypatch the helpers and would fail at setup with `AttributeError` once they
are gone:

- `tests/test_gateway_authz.py:189-190` (`_forbid_fanout`) — drop the two legacy lines; the two
  `_checked` lines already cover every route after §1.
- `tests/test_gateway_authz.py:290-291` (`test_granted_role_reaches_the_downstream_proxy`) — same.
- `tests/test_gateway_review_queue.py:155-170` — deleted per D-16.

The re-homed claim lands in the new gateway test as a source scan over
`services/gateway/app.py`: no `def _post(` / `def _get(` definition, and no call matching
`\b_get\(|\b_post\(`. The scan is safe against the checked helpers because `_post_checked(`
does not match `_post\(` and `\b_post\b` finds no boundary before `_checked` — pinned by a
positive-control assertion in the same test so the regex cannot silently stop matching.

#### 3. The bound, and what it may not preempt (E5-SPEC-11, E5-SPEC-12)

Requirements D-4 fixes a uniform `timeout=30.0`, following W2's three converted routes rather
than e4's settings-backed shape. Introduce one module constant in `services/gateway/app.py`
beside the transport helpers:

```python
# The uniform bound on a proxied call (e5, requirements D-4). Not a config
# surface: one value, thirteen call sites, and the same 30s the inherited
# _post/_get hardcoded, so no route's bound moves. It is PINNED — it must never
# fall below a downstream service's own configured budget for the call, or the
# gateway converts a slow success into a fabricated outage
# (tests/test_eligibility_budget_alignment.py). The registration path keeps its
# own configured bound (settings.intake_timeout_seconds, E4-SPEC-17).
PROXY_TIMEOUT_SECONDS = 30.0
```

Only one converted route reaches a service with a configured budget of its own:
`GET /eligibility` → eligibility-service, whose worst-case payer budget is
`(connect 1 + read 2) × (max_retries 1 + 1) = 6s` (`services/eligibility-service/config.py:24-26`,
`.env.example:30-32`). Add an invariant to `tests/test_eligibility_budget_alignment.py`, in the
file's existing both-sources style, asserting `PROXY_TIMEOUT_SECONDS >= payer worst case +
MARGIN_SECONDS` against the code defaults and `.env.example`. Every other converted route reaches
a service that makes no outbound call at all (verified: no `httpx.`/`requests.` call exists in
records-, scheduling-, roi- or interop-service), so its budget is a single DB round trip and 30s
does not preempt it.

#### 4. The portal read surfaces (E5-SPEC-5, E5-SPEC-6, E5-SPEC-7, E5-SPEC-8)

Six call sites — every surface amended E5-SPEC-8 names (spec D-12) — one pattern, copied from
`frontend/app/records/page.tsx:96-113`. Each surface gains a `…Failed` boolean beside its
existing `null | T[]` state, so three states are distinguishable: `null` = loading, `Failed` =
could not load, `[]` = genuinely empty.

```ts
// frontend/app/roi/page.tsx — the shape all six call sites take
const load = useCallback(async () => {
  setRequests(null);
  setFailed(false);
  try {
    const r = await apiFetch(`/api/roi/requests?patient_id=${encodeURIComponent(patientId)}`);
    if (!r.ok) { setFailed(true); return; }           // E5-SPEC-5
    const d: unknown = await r.json();
    const items = Array.isArray(d) ? d : (d as { items?: unknown }).items;
    if (!Array.isArray(items)) { setFailed(true); return; }   // E5-SPEC-6
    setRequests(items as RoiRequest[]);
  } catch {
    setFailed(true);                                   // never setRequests([])
  }
}, [patientId]);
```

Render: when `failed`, an `rb-alert rb-alert--err` with `role="status"` carrying a fixed,
client-authored, non-PHI sentence naming the panel and saying the list could not be loaded and is
not a statement that there is nothing. The existing `rb-empty` copy stays exactly as it is and
keeps its meaning (E5-SPEC-7) — both states must remain reachable and distinct. Per surface:

| File | Call site | Surface | Empty copy kept |
|------|-----------|---------|-----------------|
| `frontend/app/roi/page.tsx` | `:50` | ROI queue | "No release requests on file for this patient." |
| `frontend/app/appointments/page.tsx` | `:31` | Appointment list | existing |
| `frontend/app/appointments/page.tsx` | `:42` | Bookable-slots panel | existing |
| `frontend/app/page.tsx` | `:39` | Dashboard — appointments | "No upcoming appointments." |
| `frontend/app/page.tsx` | `:44` | Dashboard — records | "No recent lab results on file." |
| `frontend/app/records/page.tsx` | `:78` | Patient chart (spec D-12) | "No records found for this patient." |

The dashboard's two `.then()` chains become the same guarded shape; the records reads (dashboard
and chart) keep the `encounters` shape guard rather than `items`. The chart read's conversion
mirrors the sibling `loadRelevant` twenty lines below it: a `chartFailed` state, `!res.ok` →
failed, `Array.isArray(json.encounters)` shape guard → else failed; the existing `catch` branch
stops echoing `e.message` into the status line and sets the same failed state with the fixed
client-authored copy — exception text is not a user-facing sentence, and the failed state must
be one state, not two spellings. The empty copy and its trigger (`encounters.length === 0`) are
unchanged (E5-SPEC-7). Write surfaces (`appointments/page.tsx:59`, `:84`, `roi/page.tsx:67`,
`:96`) are untouched — requirements §6.

#### 5. Registry upkeep (E5-SPEC-22, E5-SPEC-23)

Every durable statement of the count, corrected to "none remain":

| File | What changes |
|------|--------------|
| `CLAUDE.md` §4 (`:100-103`) | The "Do NOT imitate" bullet: the helpers are gone, so the rule is structural. "Do not add a fifteenth" retired with the thing it guarded |
| `CLAUDE.md` §5 (`:126-129`) | The trailing "other thirteen … scheduled as `e5`" sentence, replaced by what now holds it closed |
| `docs/landmines.md` §1 (`:86-88`) | "The other thirteen `_post`/`_get` proxy routes are unchanged" → delivered, with the date |
| `docs/debt-log.md` D4 (`:114-118`) | The follow-up line: the estate conversion is delivered; register-first and the unpersisted verdict stay open |
| `docs/debt-log.md` (`:359`) | The "Intake contract break" four-layer narrative reads present-tense ("is the open half of D4"); dated in place, not rewritten — it is the record of the defect |
| `docs/phi-logging-policy.md` row 94 | OPEN → FIXED, dated, naming the new test file; the register is checked before anyone reports a "new" gateway leak |
| `services/gateway/app.py:1273-1276` | `_get_checked`'s docstring still says the fourteen inherited routes are deliberately not migrated |
| `docs/todo.md` | TODO-1's closed record names the thirteen routes as deferred to `e5`; annotate rather than rewrite |

`ARCHITECTURE.md` §7 needs no edit — it never claimed anything about the proxy helpers.

#### 6. Chunk 1 tests

**New: `tests/test_gateway_proxy_error_contract.py`.** Harness copied from
`tests/test_gateway_intake_proxy.py` (module pinning, `require_session` override, `httpx` faked
at the gateway seam, no Redis or DB I/O). A single table drives everything — one row per
converted route: method, path, capability-holding role, downstream service, expected downstream
path, and the params/payload the route must issue. Parametrized cases:

1. **Characterization first** (`docs/landmines.md` §3): a 2xx downstream response is relayed with
   the same status and the identical body (E5-SPEC-13), and the captured outbound call matches
   the expected service, path, params and payload (E5-SPEC-14). These are written and run
   **before** the §1 edits, against the current helpers, so the diff moves only the error path.
2. Downstream 4xx and 5xx are relayed, not flattened to 200 (E5-SPEC-1).
3. `httpx.TimeoutException` → 504; `httpx.ConnectError` → 502 (E5-SPEC-2), and the two are
   distinguishable from a relayed 4xx by status class.
4. No response body on any failure carries an `error` key (E5-SPEC-3).
5. A poisoned exception message (`http://records-service:8073/records/search?q=Quentin+Gonzalez`)
   reaches neither the response nor any log record; the log carries the exception class only
   (E5-SPEC-9, E5-SPEC-10) — the landmines §3 adversarial case for this path.
6. The route set is closed: the parametrization is asserted equal to every `APIRoute` on
   `gw.app` that fans out downstream, so a route added later without conversion fails here
   (E5-SPEC-4). The non-proxy routes are a closed, named exclusion list — `/healthz`, `/login`,
   `/logout`, `/me` — as are the four routes already converted (`/intake`, `/review-queue`,
   `/review-queue/{pair_id}/disposition`, `/patients/{patient_id}/relevant-records`) and the two
   `/ai` routes, which carry their own contract tests. An exclusion list rather than a "routes
   that call a checked helper" predicate: the latter would pass vacuously the moment a route
   called neither.
7. The structural scan of §2 (E5-SPEC-20, E5-SPEC-21), with its positive control.
8. `proxy_hl7` specifically: interop's 422 on an unparseable message arrives at the sender as a
   422, not as a 200 acknowledgement (E5-SPEC-18).

**Extended:** `tests/test_eligibility_budget_alignment.py` gains the `PROXY_TIMEOUT_SECONDS`
invariant (§3). **Edited:** `tests/test_gateway_authz.py` (two `_forbid_fanout`-style helpers).
**Deleted:** one test per D-16. `tests/test_gateway_authz.py`'s route→capability pin and 403
cases must stay green untouched — that is the evidence for E5-SPEC-15 and E5-SPEC-16.

**Frontend:** one test file per changed page — new files for `roi`, `appointments` and the
dashboard, imitating `frontend/app/records/page.test.tsx`; the chart read's cases extend that
existing file. For each of the six call sites: a 503 renders the failed state and never the
empty copy (E5-SPEC-5); a 200 carrying `{"detail": …}` renders the failed state (E5-SPEC-6); a
200 carrying the genuinely-empty shape (`{"items": []}`, or `{"encounters": []}` on the records
reads) renders the empty copy and not the failure (E5-SPEC-7). Each new test file
imports `describe`/`it`/`expect`/`vi` from `vitest` explicitly — `vitest.config.ts` sets no
`globals: true`, and `tsconfig.json` type-checks `**/*.tsx`, so a test file relying on ambient
globals reddens `typecheck` and `next build` rather than the test run (e1's lesson, in the
opposite direction).

### Branch B — chunk 2: registration idempotency

#### 7. Schema and migration (E5-SPEC-29, E5-SPEC-34) — ⚠ approval-gated

`db/schema.sql` and a new `db/migrations/010_registration_submissions.sql`, hand-synced per
`docs/landmines.md` §2. **Recorded human approval before any code is written** — this is the
migrations zone.

```sql
-- ---------------------------------------------------------------------------
-- Registration submission idempotency (e5, E5-SPEC-29/34)
-- ---------------------------------------------------------------------------
-- One row per completed registration submission, written in the SAME
-- transaction as the patient/coverage/consent rows: a record written outside
-- that transaction reopens the window it exists to close. The UNIQUE index is
-- the mechanism, not an optimization — it decides a concurrent collision and
-- makes replay lookup cheap as the table grows (D-7). No PHI: an opaque
-- client-generated identifier, a patient id and a timestamp.
-- Rows are kept FOREVER. No expiry, no pruning (requirements D-7): a retention
-- horizon is a date past which a late retry silently creates the duplicate this
-- table exists to prevent. The unbounded growth is accepted and recorded.
CREATE TABLE IF NOT EXISTS registration_submissions (
    id             SERIAL PRIMARY KEY,
    submission_id  TEXT NOT NULL UNIQUE,
    patient_id     INTEGER NOT NULL REFERENCES patients(id),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`services/intake-service/models.py` gains the matching `RegistrationSubmission` model. No other
service gets it — no other service reads registrations. D8 (the schema has zero indexes) is
untouched: the UNIQUE index is on the new table only, and no existing table gains one.

#### 8. The request contract (E5-SPEC-27)

`contracts/intake-registration.json`: `request_fields.root` gains `"submission_id"`, and
`sample_request` gains a synthetic UUID. Additive on the request side only — nothing is renamed,
retyped or removed, and the response side is untouched (requirements §6). Both suites already
assert `request_fields.root` against their own end (`tests/test_intake_payload_contract.py`,
`frontend/app/intake/payload.contract.test.ts`), so the declaration is the only place the field
is introduced and either side drifting reddens its own CI job.

#### 9. The portal mints and reuses the identifier (E5-SPEC-26, E5-SPEC-35, E5-SPEC-38, E5-SPEC-39)

`frontend/app/intake/payload.ts`:

```ts
/**
 * A submission-attempt identifier: random, and derived from nothing the operator
 * typed (E5-SPEC-38). A key hashed from SSN/DOB/name would put PHI in a log, a
 * response and a stored column, and two genuine registrations for one person
 * would collide — which is E5-SPEC-36, i.e. an accidental master patient index.
 * crypto.randomUUID is secure-context-only, so the portal cannot rely on it
 * over plain http; getRandomValues is available either way.
 */
export function newSubmissionId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;                        // version 4
  b[8] = (b[8] & 0x3f) | 0x80;                        // variant 10x
  const hex = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
```

`buildIntakePayload` takes the identifier as a fourth argument and emits it as a root key.
`frontend/app/intake/page.tsx` mints it once per mount —
`const [submissionId] = useState(newSubmissionId)` — so every re-submission of the same attempt
carries the same value (E5-SPEC-26) and a genuinely new registration, which reaches the form by a
fresh mount, gets a new one (E5-SPEC-35). The confirmation screen replaces the form entirely
(`page.tsx:159-231`) and offers no "register another", so a success cannot be re-submitted from
the same mount.

Reusing the identifier across a *correctable rejection* retry is deliberate and safe: a rejected
submission recorded nothing, so the retry with corrected values creates the registration rather
than replaying.

#### 10. The gateway forwards it unchanged (E5-SPEC-28)

No code change. `proxy_intake` takes `payload: dict` and hands it to `_post_checked` verbatim
(`services/gateway/app.py:251-257`), and `frontend/app/api/intake/route.ts` proxies the parsed
body through. The requirement is that the gateway neither mints, substitutes nor drops one — a
gateway-minted identifier would differ on the retry and close nothing — so this lands as a test
(§13) pinning id-in == id-out over the existing route, not as an edit.

#### 11. The intake service (E5-SPEC-24, 25, 29..33, 36, 37, 40)

`services/intake-service/schemas.py` — `IntakeRequest` gains a required field:

```python
    submission_id: str

    @field_validator("submission_id")
    @classmethod
    def submission_id_well_formed(cls, v: str) -> str:
        # Required, per requirements D-10: no path retains the non-idempotent
        # behaviour, so the guarantee is not conditional on the caller. A
        # rejection here is a pydantic 422 — a rejection by the submitted
        # values, which is e4's correctable-at-the-desk branch (E4-SPEC-6).
        try:
            return str(UUID(v))
        except (ValueError, AttributeError, TypeError):
            raise ValueError("submission_id must be a UUID")
```

Canonicalizing through `UUID` normalizes case and rejects anything else, so two spellings of the
same identifier cannot both claim a row (E5-SPEC-40).

`log_metadata` gains `"submission_id"`. It is the correlation key that makes a lost-confirmation
retry traceable at all, and E5-SPEC-39 anticipates exactly this: the identifier discloses nothing
about the patient, which is the property that makes logging it safe. Every other value in that
projection stays a boolean presence flag. The projection's two tests
(`tests/test_intake_schemas.py:108, 130`) assert an all-PHI scan and named keys, not an exact key
set, so the addition is additive — and the PHI scan then covers the identifier for free, which is
one of the three surfaces E5-SPEC-39 names.

`services/intake-service/app.py` — `create_intake` gains a replay fast path and a collision path:

```python
def create_intake(req, db):
    started = time.time()
    log.info('POST /intake meta=%s', json.dumps(log_metadata(req)))

    replayed = _find_registration(db, req.submission_id)          # E5-SPEC-30
    if replayed is None:
        try:
            patient_id = _create_registration(db, req)            # one transaction
        except _SubmissionAlreadyRecorded:                        # E5-SPEC-32
            patient_id = _require_registration(db, req.submission_id)
        else:
            _evaluate_match_key(db, patient_id, req.demographics) # E5-SPEC-37, unchanged
    else:
        patient_id = replayed

    eligibility = _verify_eligibility_guarded(req.insurance)      # D-14, both paths
    ...
    return IntakeResponse(patient_id=patient_id, elapsed_seconds=elapsed, eligibility=eligibility)
```

- **The record is written inside the existing transaction** (E5-SPEC-29). `_create_registration`
  adds `RegistrationSubmission(submission_id=…, patient_id=patient_id)` after `db.flush()`
  assigns the PK and before the single `db.commit()`. Nothing about the patient/coverage/consent
  writes changes, so E4-SPEC-4's atomicity is inherited rather than re-made.
- **The bounded wait** (D-15, E5-SPEC-32, E5-SPEC-33). Before the insert, on the PostgreSQL
  dialect only, `_create_registration` issues
  `SET LOCAL lock_timeout = '<n>ms'` with `n` an `int()`-coerced settings value — `SET` takes no
  bind parameters, so the value is interpolated after integer coercion and reaches the statement
  from config, never from a request. The dialect guard exists because the endpoint tests run on
  in-memory SQLite (`tests/test_intake_endpoint.py`), which serializes writers anyway; a unit
  test pins that the statement *is* issued on the Postgres path, so the guard cannot silently
  become "never".
- **Unique violation → replay** (E5-SPEC-32): `IntegrityError` on `uq`/`registration_submissions`
  is caught *before* the existing `SQLAlchemyError` → 503 branch, rolled back, and re-read. The
  winner has committed by definition — that is what released the lock — so a single re-read
  suffices and no polling is needed. `_require_registration` raising means the row vanished, which
  is the 503 branch.
- **Lock-timeout expiry → 503** (E5-SPEC-33): Postgres `55P03` (`lock_not_available`) surfaces as
  `OperationalError`; it is mapped to the existing `HTTPException(503, "registration store
  unavailable")`, so the portal's existing system-failure branch renders it (D-11) and no fifth
  result branch is added. No second registration is created — the transaction aborted before any
  write committed.
- **A fresh identifier always creates** (E5-SPEC-36): nothing in this path consults demographics.
  A patient with identical identifying values and a new `submission_id` takes the ordinary create
  path, and `_evaluate_match_key` then queues the candidate pair exactly as it does today
  (E5-SPEC-37) — idempotency must not become an MPI.
- **The replay creates nothing** (E5-SPEC-24, E5-SPEC-25): the fast path skips
  `_create_registration` *and* `_evaluate_match_key`, so no patient, coverage, consent or queue
  row is written. It answers 201 with the recorded `patient_id` through the unchanged
  `IntakeResponse` — no replay marker, no new status (E5-SPEC-30, E5-SPEC-31).

The module docstring's D4 bullet (`app.py:36-38`) is corrected: the idempotency key it names as
"still open" is what this branch lands.

#### 12. The new bound, and what it may not preempt

`services/intake-service/config.py` gains
`registration_lock_wait_seconds = float(os.getenv("REGISTRATION_LOCK_WAIT_SECONDS", "5"))`, with
`.env.example` carrying the value and the invariant comment in the style of its neighbours.

This widens intake's own worst case on the registration path from `ELIGIBILITY_TIMEOUT_SECONDS`
(8s) to `REGISTRATION_LOCK_WAIT_SECONDS + ELIGIBILITY_TIMEOUT_SECONDS` (13s), so
`tests/test_eligibility_budget_alignment.py::test_the_gateway_registration_bound_never_preempts_intake`
must assert against the new sum — otherwise the test keeps passing while no longer describing
what it claims to guard (E5-SPEC-11, E5-SPEC-12 applied to the registration path). The gateway's
30s default clears 13s + 1s margin with room.

`tests/test_compose_topology.py`'s two registration-bound guards (`:387`, `:397`) are
parametrized over both keys, for the reason the existing comment already gives: a per-service
`environment:` entry or a scoped env template can set a value neither source-of-truth check can
see. No compose edit is needed — intake-service loads the shared `.env`.

#### 13. Chunk 2 tests

**New: `tests/test_intake_idempotency.py`** — TestClient over intake-service on in-memory SQLite,
harness copied from `tests/test_intake_endpoint.py`: the same submission twice yields one patient
row, one coverage row, one consent set and the same `patient_id` (E5-SPEC-24, E5-SPEC-25,
E5-SPEC-30); the second response is byte-identical in shape and status to the first
(E5-SPEC-31); two different identifiers with identical demographics create two charts and leave
the duplicate pair queued (E5-SPEC-36, E5-SPEC-37); a missing identifier and a malformed one are
each 422 with nothing written (E5-SPEC-40); the collision path is driven by faking the insert to
raise `IntegrityError` and asserting a replay rather than a second write (E5-SPEC-32), and by
faking `lock_not_available` and asserting 503 with no second registration (E5-SPEC-33); the
`SET LOCAL lock_timeout` statement is issued on the Postgres dialect and skipped elsewhere.

**PHI negative tests** (`docs/landmines.md` §3, E5-SPEC-38, E5-SPEC-39): a submission whose
demographics carry an adversarial name/SSN/DOB produces an identifier containing none of them;
the identifier as stored, as logged and as it appears anywhere in the response is scanned for
every submitted value.

**Extended:** `tests/test_gateway_intake_proxy.py` — the identifier arrives downstream unchanged
and the gateway mints none (E5-SPEC-28). `tests/test_intake_payload_contract.py` needs no edit;
it reads the declaration.

**Every existing `IntakeRequest(...)` construction gains the field**, or it fails validation:
`tests/test_intake_schemas.py` (9 sites), `tests/test_redaction.py:85, 137`,
`tests/test_intake_match_key.py:133`, `tests/test_intake_db_error_phi.py:128`,
`tests/test_intake_endpoint.py`'s `VALID_REQUEST`. `tests/test_gateway_intake_proxy.py`'s
`PAYLOAD` is a plain dict through a `payload: dict` route and validates nowhere, but gains the
field so the fixture stays honest about what a real request looks like.

**Frontend:** `payload.contract.test.ts` gains the root-key assertion by construction (it
compares against the declaration); `page.test.tsx` gains cases for a stable identifier across two
submissions from one mount (E5-SPEC-26) and for an identifier that appears in the posted body and
matches no submitted value (E5-SPEC-38).

## Files touched

| File | Change |
|------|--------|
| **Branch A** | |
| `services/gateway/app.py` | 13 call sites repointed; `PROXY_TIMEOUT_SECONDS` added; `_post`/`_get` deleted; `_get_checked` docstring corrected |
| `frontend/app/roi/page.tsx` | Failed state on the requests read (`:50`) |
| `frontend/app/appointments/page.tsx` | Failed state on the appointment list (`:31`) and slot picker (`:42`) |
| `frontend/app/page.tsx` | Failed state on both dashboard panels (`:39`, `:44`) |
| `frontend/app/records/page.tsx` | Failed state on the chart read (`:78`), mirroring its sibling `loadRelevant` |
| `tests/test_gateway_proxy_error_contract.py` | **New** — the per-route error contract, the route-set closure, the structural scan |
| `tests/test_gateway_authz.py` | Two helper bodies drop the deleted helpers |
| `tests/test_gateway_review_queue.py` | One vacated test deleted (D-16) |
| `tests/test_eligibility_budget_alignment.py` | New `PROXY_TIMEOUT_SECONDS` invariant |
| `frontend/app/roi/page.test.tsx`, `frontend/app/appointments/page.test.tsx`, `frontend/app/page.test.tsx` | **New** — failed / empty / loaded per surface |
| `frontend/app/records/page.test.tsx` | Extended — the chart read's failed / empty / loaded cases |
| `CLAUDE.md`, `docs/landmines.md`, `docs/debt-log.md`, `docs/phi-logging-policy.md`, `docs/todo.md` | Registry upkeep (§5) |
| **Branch B** | |
| `db/schema.sql`, `db/migrations/010_registration_submissions.sql` | ⚠ New table, hand-synced |
| `contracts/intake-registration.json` | `submission_id` on the request side; sample updated |
| `services/intake-service/models.py` | `RegistrationSubmission` |
| `services/intake-service/schemas.py` | Required validated `submission_id`; `log_metadata` gains it |
| `services/intake-service/app.py` | Replay fast path, in-transaction record, collision handling, docstring correction |
| `services/intake-service/config.py`, `.env.example` | `REGISTRATION_LOCK_WAIT_SECONDS` |
| `frontend/app/intake/payload.ts` | `newSubmissionId()`; builder takes and emits the identifier |
| `frontend/app/intake/page.tsx` | Mints once per mount, passes to the builder |
| `tests/test_intake_idempotency.py` | **New** — replay, collision, fresh-create, rejection, PHI negatives |
| `tests/test_intake_schemas.py`, `test_redaction.py`, `test_intake_match_key.py`, `test_intake_db_error_phi.py`, `test_intake_endpoint.py`, `test_gateway_intake_proxy.py` | Fixtures gain the field; gateway forwarding pinned |
| `tests/test_eligibility_budget_alignment.py`, `tests/test_compose_topology.py` | Registration bound covers the new knob |
| `frontend/app/intake/page.test.tsx` | Identifier stability and non-derivation |
| `docs/debt-log.md`, `docs/todo.md` | D4's idempotency follow-up closed; TODO-62 for the accepted residual |

## Out of scope (from requirements §6)

- **The registration path's error contract** — e4's chunk. e5 must not re-open what e4 froze:
  no field in `contracts/intake-registration.json` is renamed, retyped or removed, the gateway's
  registration error mapping is untouched, and the portal's four result branches keep their
  meanings (E4-SPEC-6, E4-SPEC-7). Chunk 2 **adds** a field to that contract and adds a replay
  path to `POST /intake`; that is the one registration change e5 carries, and it is additive.
  *(Narrowed 2026-08-10 by the second ask. Before then this line excluded the registration path
  entirely.)*
- **Fixing D11 / IDOR and the unbounded `%` search** — e5 touches four routes in the D11 exposure
  set and is required not to widen them (E5-REQ-6), but the fix is sized against the whole set on
  its own item.
- **The booking race** (`scheduling-service/book.py`, RIV-175) and **D5b** — `proxy_book` and
  `proxy_cancel` are converted here; the double-booking defect behind them is untouched.
- **Register-first / async eligibility re-verification** — D4's other remaining follow-up, an
  architecture change rather than a contract fix. It attacks the same lost-confirmation class that
  chunk 2 closes, from the other side (shrink the window rather than make the retry safe), and it
  needs the job/result store ADR 0010 defers. Chunk 2 does not depend on it and does not preclude
  it.
- **D5 / the master patient index** — chunk 2 makes one *submission* idempotent, not one *person*.
  Two genuinely separate submissions for the same patient still fork two charts, still get queued
  as a candidate pair, and still get merged by nobody. E5-REQ-12 exists to keep that true.
- **HL7 AL1/RXA mapping** — `proxy_hl7`'s error contract is in scope; what interop does with a
  well-formed message is not.
- **The portal's *write* surfaces** — booking, cancel, ROI-create and ROI-fulfill
  (`appointments/page.tsx:59`, `:84`, `roi/page.tsx:67`, `:96`), plus logout
  (`components/AppShell.tsx:112`). E5-REQ-2 is a read-surface requirement and D-8 kept it that
  way; covering the writes would need new ids, and the gateway routes behind them are converted
  here either way. *(Corrected 2026-08-11: this bullet called those four writes "unchecked". They
  are not — all four check `!r.ok` and set an explicit error message, crudely but correctly, at
  `appointments/page.tsx:69` and `:85` and `roi/page.tsx:79` and `:97`. The one genuinely
  unchecked write is logout, and it has no result surface to mis-render. Nothing about the scope
  boundary changes; the phantom does.)*
- **Retention or pruning of submission identifiers** — D-7 keeps them forever deliberately. No
  scheduled job, no horizon. The unbounded growth is accepted and recorded, not deferred to a
  future item.
- **CI check routing** — `e3`'s chunk.
- **Correcting the README compliance claim** — TODO-12, human-gated by scenario design.

## Verification (end-to-end)

Fast tier is `make test-docker` (python:3.12, mirrors CI); the frontend gate is
`cd frontend && npm install && npm test` plus `npm run build`, `typecheck`, `lint`.

1. **Characterization before conversion** (E5-SPEC-13, E5-SPEC-14, `docs/landmines.md` §3).
   Land the success-path half of `tests/test_gateway_proxy_error_contract.py` against the
   *unconverted* gateway and confirm it is green. Only then make the §1 edits. If any success
   case reddens, the conversion changed something it is forbidden to change.
2. **Per-route error contract** (E5-SPEC-1, E5-SPEC-2, E5-SPEC-3). Full suite green with the new
   parametrization over all 13 routes. **Negative:** revert one route to the old helper — the
   route's relay and no-`error`-key cases go red, and so does the route-set closure case. Revert
   the revert.
3. **Universality** (E5-SPEC-4). Add a throwaway gateway route calling a downstream service
   without conversion; the closure case goes red. Delete it.
4. **The helpers cannot come back** (E5-SPEC-20, E5-SPEC-21). Both §2 searches return nothing
   before the deletion lands: no call site in `services/gateway/` outside the two `def` lines,
   and no attribute or string-keyed reference (`._post`/`._get`/`"_post"`/`"_get"`) anywhere in
   `services/`, `frontend/`, `tests/` or `eval/`. **Negative:** re-add `def _get(...)` — the
   structural scan goes red; and confirm the scan's positive control still passes with
   `_get_checked`/`_post_checked` present, so it is matching the right thing.
5. **PHI on the failure path** (E5-SPEC-9, E5-SPEC-10). The poisoned-URL case over every
   converted route. **Negative:** change one `type(e).__name__` to `e` in a checked helper — the
   scan goes red on every route. Revert.
6. **Authorization unchanged** (E5-SPEC-15, E5-SPEC-16, E5-SPEC-17). `tests/test_gateway_authz.py`
   green with its route→capability pin and 403-before-fan-out cases *unedited* except for the two
   deleted monkeypatch lines. `config/roles.yaml` and `services/gateway/authz.py` untouched.
7. **The bound does not preempt** (E5-SPEC-11, E5-SPEC-12).
   `tests/test_eligibility_budget_alignment.py` green with the new invariant. **Negative:** set
   `PROXY_TIMEOUT_SECONDS = 5.0` — below eligibility-service's 6s worst case — and watch it go
   red. Revert.
8. **The portal shows an outage as an outage** (E5-SPEC-5, E5-SPEC-6, E5-SPEC-7, E5-SPEC-8).
   Vitest green over all six call sites. Then live: `make up`, log in, `docker compose stop
   roi-service scheduling-service records-service`, and load `/roi`, `/appointments`, `/` and
   `/records`. Each panel — the chart included — must read as failed, never as empty and never
   as "No records found for this patient.". Restart the services; each panel must recover, and
   a patient with genuinely no rows must still read as empty.
9. **The HL7 sender sees a rejection** (E5-SPEC-18, E5-SPEC-19). With the stack up, `docker
   compose exec gateway` POST an unparseable message to `/hl7/ingest` with a session holding
   `hl7.ingest`: the answer is interop's own 422, not a 200 acknowledgement. Confirm the PR body
   names this as outward-facing and identifies external senders as the affected callers.
10. **Registries** (E5-SPEC-22, E5-SPEC-23). `rg -n 'thirteen|fourteen|fifteenth'` over the
    tracked tree returns only historical records that are dated as such — no live statement of an
    outstanding count survives.
11. **Idempotency, the operator's outcome** (E5-SPEC-24, E5-SPEC-25, E5-SPEC-30, E5-SPEC-31).
    `make up`, register a patient through `/intake`, then re-post the identical body (same
    `submission_id`) through the gateway. Second answer: 201, same `patient_id`, no replay marker.
    Then `SELECT count(*) FROM patients WHERE ssn = …` and the same over `insurance_coverages`
    and `consents` — one of each.
12. **The concurrent collision** (E5-SPEC-32, E5-SPEC-33) — the case the unit tests fake, proven
    once against real Postgres. Fire two simultaneous registrations carrying one `submission_id`;
    exactly one chart exists afterwards and both callers get the same `patient_id`. Then set
    `REGISTRATION_LOCK_WAIT_SECONDS=1` and hold a conflicting transaction open past it: the second
    caller gets a 503 the portal renders in its existing system-failure branch, and no second
    registration exists. **This step also proves `lock_timeout` actually bounds a wait on a
    duplicate-key insert** — see the risk below.
13. **A fresh registration is never a replay** (E5-SPEC-36, E5-SPEC-37). Register the same person
    twice with two identifiers: two charts, and
    `SELECT * FROM duplicate_review_queue WHERE status='pending'` still shows the pair. D5 is
    still open.
14. **Rejection** (E5-SPEC-40). POST without `submission_id`, and with `"not-a-uuid"`: both 422,
    both leave `patients` unchanged, and the portal renders the correctable-at-the-desk branch.
15. **PHI** (E5-SPEC-38, E5-SPEC-39). The negative tests green; then read
    `logs/intake-service.log` from the live run above and confirm the identifier appears with no
    submitted value near it.
16. **Baseline and gaps.** Full `make test-docker`, and the resulting `passed / xfailed /
    deselected` recorded in `pr-body.md` against the 2026-08-10 baseline of
    `969 passed, 1 xfailed, 5 deselected`. The xfail and deselected counts must not move —
    `docs/landmines.md` §3's list of deliberate gaps is unchanged by e5. The passed count moves by
    e5's additions **minus one** (D-16), and the −1 is stated explicitly.
17. **`make eval`** green. The drift gate hashes `db/seed/seed.sql` and the eval corpus only
    (`eval/rag/check_drift.py:151-161`), and neither the schema change nor the migration touches
    them.

## Landmines / risk

**`docs/landmines.md` §1 zones touched:**

- ⚠️ **Gateway error handling — the whole conversion, all thirteen routes.** `docs/landmines.md`
  §1 approval-gates the migration itself, not only its ROI subset ("migrating them is
  approval-gated and scheduled as `e5`", `:87`). Owner approval is on record and carried here
  rather than re-secured — the chain is in Context: e4 requirements D-3 scheduled the migration
  as this item; e5 requirements (AGREED 2026-08-10) carry E5-REQ-1 as ⚠ human-gate with the
  owner's D-2..D-4 fixing its mechanism; the spec (AGREED 2026-08-11) freezes E5-SPEC-1..4 as
  ⚠ human-gate statements. Precedent: e4's plan carried its gateway-zone approval from
  requirements-stage decision D-1 the same way.
- ⚠️ **ROI / disclosure logic** — three converted routes (`proxy_roi_list`, `proxy_roi_create`,
  `proxy_roi_fulfill`). Error path only: no disclosure logic, no authorization behaviour, no
  stored row changes. The zone is entered, so the change is human-gated; the approval above
  covers it — the three routes are inside the approved thirteen, and the requirements name the
  zone crossing explicitly (§2, "Zones this crosses", owner-AGREED).
- ⚠️ **Migrations and the schema** (chunk 2) — one new table, hand-synced across `db/schema.sql`
  and `db/migrations/010_*.sql`. Recorded human approval before code. No existing table, column
  or PHI column is altered.
- ⚠️ **ADR 0010 budget pinning** — `PROXY_TIMEOUT_SECONDS` on the eligibility-reaching route and
  `REGISTRATION_LOCK_WAIT_SECONDS` inside intake's own budget. Both land as new assertions in
  `tests/test_eligibility_budget_alignment.py`; neither existing value is widened or loosened.
- ⚠️ **Auth / sessions** — not edited. No `Depends`, no capability, no `config/roles.yaml` or
  `authz.py` change; E5-SPEC-15/16 are verified by leaving `tests/test_gateway_authz.py`'s pins
  untouched.
- ⚠️ **IDOR / D11** — `proxy_patients`, `proxy_search`, `proxy_records` and `proxy_roi_list` are
  converted. They return the same rows on success; only the failure representation changes. D11
  is neither fixed nor widened.

**Deliberate defects preserved, not fixed:** D11 and the `?q=%25` corpus dump; D5 (no MPI —
E5-SPEC-36/37 exist to prove chunk 2 did not close it); D5b and RIV-175 (`proxy_book`/`proxy_cancel`
convert, the booking race is untouched); D8 (the new UNIQUE index is on the new table only — no
existing table gains one); the HL7 AL1/RXA `xfail`; D2 (`audit_logs` still has no writers).
`proxy_search` gets the uniform 30s exactly as `_get` hardcoded, so its unbounded scan is
unchanged — that is D11's problem, out of scope (requirements §6).

**Accepted residuals:**

- **E5-SPEC-33's answer is imprecise.** A bounded-wait expiry answers "not saved" while the
  winning request may have saved the registration. Accepted deliberately at spec stage (D-11):
  the operator's next retry carries the same identifier and replays into the real confirmation.
- **E5-SPEC-40 lands a non-correctable rejection in the correctable branch.** A missing or
  malformed `submission_id` is a portal bug, not something the operator can fix at the desk, but
  it is a rejection by the submitted values so it renders as E4-SPEC-6. Accepted rather than
  adding a fifth result branch (D-10, D-11). The portal is the only caller today.
- **`lock_timeout` must be proven, not assumed.** The design rests on Postgres applying
  `lock_timeout` to the transaction-id wait a duplicate-key insert performs. Verification step 12
  proves it against real Postgres before the branch is claimed. If it does not fire there, the
  fallback is `statement_timeout` scoped to the same statement — same bound, wider blast radius
  (it would also abort a legitimately slow insert), and it would be recorded as a decision rather
  than swapped in silently.
- **The replay costs a second eligibility hop** (D-14), bounded by the existing 8s budget and the
  intake-side breaker. Accepted as the price of a replay the operator cannot distinguish from the
  original.
- **Submission identifiers grow without bound** (D-7). Recorded here and in the schema comment,
  not deferred to a future item.
- **The verdict still reaches no column.** D4 residual 3 is untouched — it is why the replay must
  re-verify rather than read back.

**PR-body lines required:**

- Branch A: **the HL7 ingest response is an outward-facing contract change** (E5-SPEC-19). Every
  ingest is answered 200 today; after this, a message interop rejects is answered with interop's
  rejection status. The affected callers are external interop senders, and this route has no
  portal surface, so the delivery record is the only place a reader meets it.
- Both branches: the "Risk & landmines" section names the zones above, and the baseline move
  (including D-16's −1) is stated rather than absorbed.

**Gate interaction.** `next build` type-checks and, with an eslint config present, lints — so a
portal type or lint error reddens the build step before the dedicated `typecheck`/`lint` steps
and gets attributed there. Both contract-test jobs (pytest and vitest) already gate
`docker-build`, so the chunk-2 contract extension cannot land half-applied. `tests` and
`frontend` are separate CI jobs: a chunk-1 branch that converts the gateway without the portal
half would be green in `frontend` and still ship the defect, which is why E5-SPEC-8 is in the
same branch as E5-SPEC-1.

**TODO id.** TODO-62 is the next free id (max allocated is TODO-61). Per the collision rule it is
re-checked at landing; a later entry taking it first means this one renumbers.
