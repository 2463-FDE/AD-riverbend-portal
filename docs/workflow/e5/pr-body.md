# e5 branch A — the gateway/portal error contract

> Status: MERGED 762f614 2026-08-11
> Impl-gate record: impl-gated fresh-context 2026-08-11, clean — no findings
> (`findings.md` has no §Impl gate section; nothing was ever filed against this
> branch). Branch `fix/e5-gateway-error-contract`, HEAD `14f0af1`. Baseline
> re-run by the gate session (3.12 venv, full suite minus integration):
> **1247 passed, 1 xfailed, 5 deselected** — matches this document's
> `make test-docker` record against the 969/1/5 baseline; frontend re-run:
> 100 passed. The one verification gap this document disclosed — plan step 8's
> browser half — was **reproduced clean by the gate session**: headless-Chromium
> render checks as the full-capability `staff` user, 19/19 — with
> roi/scheduling/records stopped, all six read surfaces render their failed
> state and never the empty copy; after restart all six recover, and a rowless
> patient still renders the distinct empty copy. Step 8 is now fully verified;
> no residual remains there. Residual accepted at this gate: the pre-existing
> httpx INFO request-URL logging finding stays owner-routed (the section below
> plus the register row 94 note) with no register row or TODO id of its own —
> placement is the owner's call, as this document states.
> Chunk 1 of e5 (plan D-13): E5-SPEC-1 … E5-SPEC-23. Branch B (registration
> idempotency, E5-SPEC-24 … E5-SPEC-40) is a separate PR and is not in this diff.
> Spec: `docs/workflow/e5/spec.md` (AGREED 2026-08-11, frozen).
> Plan: `docs/workflow/e5/plan.md` (GATED 2026-08-11, round 4).
> Branch: `fix/e5-gateway-error-contract`.

## What this changes

e4 converted **one** gateway route off the inherited error-swallowing proxy
helpers. This converts the remaining **thirteen** and deletes the helpers, then
fixes the portal half without which the conversion is invisible.

`_post`/`_get` collapsed every downstream and transport failure into a **200 OK**
`{"error": str(e)}` body and logged `str(e)`. So an outage reached the portal as
a success, and the portal — which checked no status and coerced any non-list
body to `[]` — rendered it as *"you have none"*. On the chart read that sentence
was **"No records found for this patient."**

Three things had to move together, which is why they are one PR:

1. **Thirteen call sites** → `_get_checked`/`_post_checked` (eligibility,
   records ×4, scheduling ×4, ROI ×3, interop). Downstream status and body
   relayed; transport failures typed 502/504; exception **class** only in logs.
2. **Both helpers deleted.** Deletion, not disuse — while they exist, "don't use
   them" is advice a new route can ignore by copying a neighbour.
3. **Six portal read surfaces** given a third state. `null` = loading,
   `failed` = could not load, `[]` = genuinely empty. The existing empty copy is
   untouched and both states stay reachable and distinct.

The bound is one module constant, `PROXY_TIMEOUT_SECONDS = 30.0` — the same 30s
the inherited helpers hardcoded, so **no route's bound moves** — newly pinned
above eligibility-service's worst-case payer budget.

## Risk & landmines

`docs/landmines.md` §1 zones **entered**:

- ⚠️ **Gateway error handling — the whole conversion, all thirteen routes.**
  §1 approval-gates the migration itself (`:87`, "migrating them is
  approval-gated and scheduled as `e5`"). **Owner approval is on record** and is
  carried by the plan rather than re-secured: e4 requirements D-3 deferred the
  estate conversion to this named item; e5 requirements (AGREED 2026-08-10)
  carry E5-REQ-1 as ⚠ human-gate with owner decisions D-2…D-4 fixing its
  mechanism; the spec (AGREED 2026-08-11) freezes E5-SPEC-1…4 as ⚠ human-gate
  statements. Same shape as e4's precedent (`docs/workflow/e4/plan.md:41-43`).
- ⚠️ **ROI / disclosure logic** — `proxy_roi_list`, `proxy_roi_create`,
  `proxy_roi_fulfill`. **Error path only**: no disclosure logic, no
  authorization behaviour, no stored row changes. Covered by the approval above.
- ⚠️ **ADR 0010 budget pinning** — `PROXY_TIMEOUT_SECONDS` on the
  eligibility-reaching route. New assertion in
  `tests/test_eligibility_budget_alignment.py`; no existing value widened or
  loosened.
- ⚠️ **IDOR / D11** — `proxy_patients`, `proxy_search`, `proxy_records`,
  `proxy_roi_list` are in D11's exposure set. They relay the same body byte for
  byte on success, so the same rows and the same fields are disclosed. **D11 is
  neither fixed nor widened**; the IDOR comments at `app.py:317-318` and
  `:326-329` are untouched.

Zones **not entered**: auth/sessions (no `Depends`, no capability, no
`config/roles.yaml`, no `authz.py`), PHI columns, migrations, secrets.

**Deliberate defects preserved, not fixed:** D11 and the `?q=%25` corpus dump
(`proxy_search` gets the same 30s `_get` hardcoded, so its unbounded scan is
unchanged); D5 / no MPI; D5b and RIV-175 (`proxy_book`/`proxy_cancel` convert,
the booking race is untouched); D8 (no table gains an index); the HL7 AL1/RXA
`xfail`; D2 (`audit_logs` still has no writers).

## ⚠️ Outward-facing contract change (E5-SPEC-19)

**`POST /hl7/ingest` now answers a rejected message with a rejection status.**
Today every ingest is answered **200**. interop-service already rejects an
unparseable or oversized message with 422/413; the inherited `_post` swallowed
that into a 200 acknowledgement, so a sending system saw every message as
accepted. Relaying interop's own status **is** the change — no HL7 ACK/NAK
message is constructed (owner decision D-9).

**Affected callers are external interop senders.** This route has no portal
surface, so this PR body is the only place a reader meets the change. Verified
live against the running stack: whitespace-only → 422, oversized → 413.

## Accepted residuals

- **`proxy_search`'s unbounded scan is unchanged.** Out of scope (requirements
  §6); it belongs to the D11 item, sized against the whole exposure set.
- **The eligibility verdict still reaches no column** (D4 residual 3) —
  untouched.
- **Register-first / async re-verification** (D4's other follow-up) is not in
  this branch and is not precluded by it.

## 🔎 Finding for the owner to route — NOT fixed here

**httpx logs every outbound request URL, query string included, at INFO, into
the gateway's own log.** Confirmed at runtime, not inferred — with the stack up:

```
INFO [gateway] HTTP Request: GET http://eligibility-service:8072/eligibility?insurance_id=BCBS4471 "HTTP/1.1 200 OK"
INFO [gateway] HTTP Request: GET http://records-service:8073/records/search?q=gonzalez "HTTP/1.1 200 OK"
```

That is a member id and a patient surname in a log line — the same leak *class*
`docs/phi-logging-policy.md` row 94 describes, at a **different log site**: the
httpx library, not the gateway's own `log.error`. It is **pre-existing and
estate-wide** — true on every route including the four e4/W2 already converted,
and true before this branch — and it is not in the register. e5 does not
introduce it, does not widen it, and E5-SPEC-9/E5-SPEC-10 govern *the gateway's
own* log entry and response, which are class-only and clean (pinned by a
poisoned-URL case over all thirteen routes).

It is **not fixed here** because silencing a logger is a PHI-policy decision, not
an error-contract fix, and `docs/landmines.md` §1 puts that call with the owner.
Recorded in the register row so the next reader meets it; **no TODO id was
allocated** — that is the owner's to place.

## Slices, and which ran test-first

| Slice | Test-first? | Notes |
|-------|-------------|-------|
| Characterization floor | **Yes — first** | 39 success-path cases written and run **green against the unconverted gateway** before any call site moved (`docs/landmines.md` §3, verification step 1) |
| Thirteen call sites | Yes | Error-path cases red → conversion → green |
| `PROXY_TIMEOUT_SECONDS` + budget invariant | Yes | Negative check run: at 5.0 the invariant reddens |
| Helper deletion | Yes | Structural scan red pre-deletion, green after |
| Six portal surfaces | Yes | 25 vitest cases red → conversion → green |
| Registry upkeep (§5) | n/a — no behavioural seam | Covered by verification step 10's sweep |

## Deviations from the plan

1. **The PHI scan is scoped to gateway-emitted log records.** The plan's case 5
   said "reaches neither the response nor any log record". As written that
   fails on a **harness artifact**: `caplog` also captures httpx's own INFO line
   for the TestClient's *inbound* request to the app under test, which carries
   the test's own URL — a leak the gateway did not commit. The assertion now
   filters `rec.name == "gateway"`, with the reason in a comment. The
   product-side observation this exposed is the finding above.
2. **Added: per-route authorization cases** (`test_a_denied_role_is_rejected_before_any_fan_out`,
   `test_no_converted_route_answers_without_a_session`). The plan's evidence for
   E5-SPEC-15/16 was "leave `test_gateway_authz.py` green untouched", and it is
   green untouched. This is an addition, not a substitution: the failure mode —
   an error path answering before the session dependency — is specific to the
   routes this branch edited. **No deliberate coverage gap moved**
   (`docs/landmines.md` §3's list is unchanged).
3. **`test_gateway_authz.py`'s two helpers drop only the legacy pair.** Planned;
   noted because the comment above them had to be rewritten — it justified
   patching "all four" helpers, and there are now two.

## Planned work absent from the diff

- **Nothing from the plan's chunk-1 scope is missing.** All of §1–§6 landed.
- **Chunk 2 (§7–§13) is deliberately absent** — separate branch per D-13.
- `ARCHITECTURE.md` needed no edit (plan §5). Re-verified: it makes no claim
  about the proxy helpers (0 matches).
- **TODO-62 is not allocated here.** The plan reserves it for chunk 2's
  accepted residual; per the collision rule it gets re-checked at that landing.

## Verification

Full suite: **`make test-docker` → 1247 passed, 1 xfailed, 5 deselected.**

Against the `CLAUDE.md` §6 baseline of **969 / 1 / 5** (2026-08-10):

| | Count |
|---|---|
| Baseline passed | 969 |
| `tests/test_gateway_proxy_error_contract.py` (new) | +278 |
| `PROXY_TIMEOUT_SECONDS` invariant | +1 |
| **D-16: deleted `test_queue_routes_never_use_the_swallowing_helpers`** | **−1** |
| **Total** | **1247** |

**xfailed and deselected did not move.** The −1 is stated rather than absorbed:
that test proved its claim by monkeypatching `_get`/`_post` to explode, which
fails at setup once they are deleted and is vacuous besides. Its claim is
re-homed as a structural scan **with a positive control**, so the regex cannot
silently stop matching.

Frontend gate: `npm test` **100 passed** (25 new), `npm run build`, `typecheck`,
`lint` all clean. `make eval` green (the drift gate hashes seed + corpus, which
this branch does not touch).

Plan verification section, step by step:

| # | Step | Result |
|---|------|--------|
| 1 | Characterization before conversion | ✅ 39 cases green against the unconverted gateway |
| 2 | Per-route error contract | ✅ **Negative:** reverting `proxy_search` to `_get` → 16 red incl. the closure case; reverted |
| 3 | Universality | ✅ **Negative:** throwaway unconverted route → closure case red; deleted |
| 4 | Helpers cannot come back | ✅ Both scoped searches returned only the six monkeypatch lines removed. **Negative:** re-adding `def _get(` → scan red; positive control still green |
| 5 | PHI on the failure path | ✅ **Negative:** `type(e).__name__` → `e` in `_get_checked` → all 8 GET routes red; reverted |
| 6 | Authorization unchanged | ✅ `test_gateway_authz.py` green with its pins unedited (bar the two deleted monkeypatch lines) |
| 7 | Bound does not preempt | ✅ **Negative:** `PROXY_TIMEOUT_SECONDS = 5.0` (below the 6s payer worst case) → red; reverted |
| 8 | Portal shows an outage as an outage | ⚠️ **Partial — see below** |
| 9 | HL7 sender sees a rejection | ✅ Live: whitespace-only → **422**, oversized → **413** (were 200) |
| 10 | Registries | ✅ Every surviving "thirteen" is a dated historical record or describes what e5 did; no live outstanding count |
| 16 | Baseline and gaps | ✅ Table above |
| 17 | `make eval` | ✅ Green |

*(Steps 11–15 are chunk 2's and belong to branch B.)*

### ⚠️ Step 8 is partially verified — what was and was not done

**Done.** All 25 vitest cases drive the two real failure inputs into the real
components. Live against the stack, with `roi-service`, `scheduling-service` and
`records-service` stopped, every one of the six reads received exactly those
inputs at the BFF boundary the portal calls:

```
ROI queue              {"detail":"roi service unreachable"}        <- HTTP 502
Appointments list      {"detail":"scheduling service unreachable"} <- HTTP 502
Bookable slots         {"detail":"scheduling service unreachable"} <- HTTP 502
Dashboard appts        {"detail":"scheduling service unreachable"} <- HTTP 502
Records (chart + dash) {"detail":"records service unreachable"}    <- HTTP 502
```

Services restarted: all six recovered, and a patient with genuinely no rows
still answers `200 []` — distinct from the outage, so the empty state stays
reachable. All six failure sentences were confirmed present in the built client
bundles served by the container.

**Not done.** The final half of step 8 — *loading `/roi`, `/appointments`, `/`
and `/records` in a browser and reading the rendered panels* — was not executed:
no browser automation was available in this session (the Chrome extension is not
connected, and Playwright is not installed). The render assertion rests on
vitest plus the boundary evidence above. **Flagging it rather than claiming it**;
it is a one-minute manual check for whoever has a browser on the stack.

## Files

**Gateway** — `services/gateway/app.py`: 13 call sites repointed;
`PROXY_TIMEOUT_SECONDS` added; `_post`/`_get` deleted; `_get_checked` docstring
corrected (it still said fourteen routes were deliberately unmigrated).

**Portal** — `app/roi/page.tsx`, `app/appointments/page.tsx` (×2),
`app/page.tsx` (×2), `app/records/page.tsx`. The chart's `catch` also stops
rendering `e.message`: exception text is not a user-facing sentence, and the
failed state must be one state rather than two spellings of it.

**Tests** — new `tests/test_gateway_proxy_error_contract.py`; new
`app/roi/page.test.tsx`, `app/appointments/page.test.tsx`, `app/page.test.tsx`;
extended `app/records/page.test.tsx` and
`tests/test_eligibility_budget_alignment.py`; edited `tests/test_gateway_authz.py`;
one test deleted from `tests/test_gateway_review_queue.py` (D-16).

**Registries** — `CLAUDE.md` §4 and §5, `docs/landmines.md` §1,
`docs/debt-log.md` (D4 + the four-layer narrative, dated in place),
`docs/phi-logging-policy.md` row 94 (OPEN → FIXED), `docs/todo.md` TODO-1's
deferral line (annotated, not rewritten).
