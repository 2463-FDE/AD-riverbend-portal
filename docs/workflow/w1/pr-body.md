# W1 — typed LLM timeout, class-only logging on the LLM path, register + seam-map corrections

> Status: MERGED `a9aa456` 2026-08-10 (PR #69, squashed; branch deleted). Pushed 2026-08-09;
> review round 1 fixed and re-tagged 2026-08-10 (`73b9f06`); round 2 dry, `approve`.
> Delivery state for W1 lives here, not in `plan.md` (which stays `GATED`) and not in
> `findings.md` (findings only). Spec: `docs/workflow/w1/spec.md` (AGREED 2026-08-09, frozen).
> Plan: `docs/workflow/w1/plan.md` (GATED 2026-08-09, four gate rounds).

## Impl-gate record

**Impl-gated 2026-08-09, fresh-context** (`.claude/skills/impl-gate/`), after three rounds —
`docs/workflow/w1/findings.md` §Impl gate is the log. Branch
`fix/noref-llm-timeout-and-phi-log-hygiene` @ `04a4ea6`.

- **Baseline observed, re-run at the gate** (not carried from the implementation notes):
  `make test-docker` → **`934 passed, 5 deselected, 1 xfailed`**, matching `CLAUDE.md` §6 as
  this branch sets it. +11 from the 923 baseline; xfailed and deselected unmoved, so no
  deliberate gap moved. `cd frontend && npm test` → 6 files / 58 tests green;
  `npm run typecheck` clean; `npm run lint` only the pre-existing `DateField.tsx:103`
  warning, which is not in the diff.
- **Residuals accepted at this gate:** the four listed under *Accepted residuals* above
  (SPEC-12/13 scope boundary, SPEC-20 message-not-checklist, the SPEC-2 botocore version
  caveat, and the ADR enumerations filed as TODO-60), carried unchanged from the plan's gate
  record. No new residual was introduced at implementation.
- Status means **push-ready**. Push itself stays human-gated
  (`.claude/skills/implementation/`).

## What this is

W1 is a **backfill of record**: every named deliverable already existed on `main`, and the stage's
job was to verify the existing artifacts against the frozen spec and close what missed. Verification
found **14 of 20 statements hold as written; six do not** (SPEC-2, 12, 13, 15, 16, 18) — four
distinct gaps, since one spans SPEC-12/13 and another spans SPEC-16/18. This PR is those four gaps,
plus the missing test gate under SPEC-19/20, and nothing else. The 14 satisfied statements got no
production change.

## Changes

| SPEC | Change |
|------|--------|
| W1-SPEC-2 | `LLMTimeout(LLMUnavailable)` in `services/ai-assistant/llm_client.py`, raised from botocore's `ConnectTimeoutError` / `ReadTimeoutError`. A caller can now separate a timeout from a throttle or a 5xx; before, both arrived as `LLMUnavailable("connection error after retries (...)")`. |
| W1-SPEC-12, 13 | Six LLM-path `log.error` sites in `services/ai-assistant/app.py` moved to the class-name-only idiom (`CLAUDE.md` §4). Five in `intake_instructions`, one in the visit-chat degrade branch. |
| W1-SPEC-15 | `docs/phi-logging-policy.md` — the LLM-path register row flipped to **FIXED 2026-08-09** and now names all six sites (it listed four); the neighbouring Redis-fault row had its locations re-measured, status unchanged (**OPEN**). |
| W1-SPEC-16, 18 | `docs/onboarding-seam-map.md:27` — the dead `D9` cite repointed at the canonical `docs/debt-log.md` entries, keeping the literal token inside a clause that names it client-brief misnumbering. |
| W1-SPEC-19, 20 | New `frontend/app/intake/page.test.tsx`. **No production frontend change** — the surface already satisfied both statements; this is the gate that stops it regressing. |
| W1-SPEC-12 (review r1) | `LLMError.request_id` — a raiser-set structured attribute (the `egressed` idiom), passed at all three `LLMResponseError` raise sites and logged as an allowlisted field at the two class-name-only catch sites (`intake_instructions`, the `_reply_items` degrade branch). Restores the provider correlation handle that the SPEC-13 message strip removed. |
| — | Registry upkeep: `CLAUDE.md` §6 baseline re-measured; `docs/todo.md` TODO-59 and TODO-60 filed; `docs/phi-logging-policy.md`'s `:94` row notes the two sites that now also log `request_id`. |

### Why `LLMTimeout` subclasses `LLMUnavailable`

Additive, not a behaviour change. Every existing `except LLMUnavailable` keeps working unchanged —
ai-assistant `app.py`'s 502 branch, and through it the gateway's ADR 0007 keep-charge rule. It stays
post-egress (`egressed=True` inherited): a timeout means the request was attempted and may bill, so
it must not land on a status the gateway refunds. `test_llm_timeout_subclasses_unavailable` and the
`("LLMTimeout", 502)` parametrize case pin both halves.

The `isinstance` narrow sits **inside** the existing `except BotoCoreError` branch rather than as a
new `except` clause. That block already carries one ordering constraint (all three credential
classes subclass `BotoCoreError`, and PR #5 round 2 established a credential failure is a config
error, not an outage); a separate clause would have added a second. Narrowing inside adds none.

## Risk & landmines

**`docs/landmines.md` §1 zones touched: PHI handling (logging paths only).** No auth, no PHI
columns, no ROI/disclosure logic, no migrations, no `.env` or secret file.

The change removes text from log lines and adds a typed exception subclass. It moves no PHI
boundary, changes no HTTP status, and adds no egress; `/ai/*` remains the only vendor-egress path
and this PR does not widen it. The egress-adjacent statements (SPEC-19/20) get **tests only** — no
production frontend or route change — so the approved surface is logging text plus one new
exception subclass.

**Human approval record.** SPEC-11..15 carry the spec's ⚠ human-gate marker and SPEC-19 is flagged
for vendor-egress adjacency. Per the `w2` precedent, the plan's owner review is the planning
approval for the PHI-handling edits it names (the six `app.py` log sites, the
`docs/phi-logging-policy.md` register rows, the `llm_client.py` raise site). Nothing was
self-approved at implementation time; the code change rides impl gate → codex review → merge.

**§3 negative-test rule applies and is satisfied.** Every one of the six log-site fixes carries an
adversarial test that plants a PHI marker *inside the exception message* and scans the **formatted**
log record (the `test_scheduling_booking_db_error_phi.py` idiom), so a branch leaking through
`exc_info` or a traceback fails too. All were red pre-fix.

**Deliberate defects preserved.** Nothing here touches D1's historical `logs/intake-service.log`,
D4's inline placement, D5b's `book.py`, D11, D13, or the intake contract break (TODO-1). The
frontend test mocks `apiFetch`, so the mocked 200 on `/api/intake` is **not** an assertion that
registration works — it neither exercises nor masks that defect, which is backend-side and stays
exactly as visible as it is now.

## Accepted residuals (carried from the plan, not rediscovered)

1. **SPEC-12/13 scope boundary.** The fix covers *LLM-client* errors on the ai-assistant path. The
   Redis-fault sites on the same `/ai` routes still log full exception text and stay **OPEN** in the
   register: `services/gateway/app.py:175, 200, 203, 1063, 1095, 1106`. They are
   session-store/visit-memory/lock faults, not LLM errors, and REQ-5 scopes SPEC-12/13 to "the LLM
   path". The scope-map row is **not** full coverage of every log line on an `/ai` request.
2. **SPEC-20 is a message, not a checklist.** The fallback is a fixed non-PHI string ("Could not
   prepare your checklist right now."), not a deterministic offline set of instructions. It
   satisfies the statement as written and the new test pins it, but a reader expecting an offline
   checklist will not find one. Building one is the AI feature that requirements §6 puts out of
   scope.
3. **SPEC-2 version caveat.** `LLMTimeout` keys on `botocore.exceptions.ConnectTimeoutError` /
   `ReadTimeoutError`. `services/ai-assistant/requirements.txt:5` pins `boto3==1.40.0`, which does
   **not** pin botocore (its metadata admits any `botocore>=1.40.0,<1.41.0`; measured 1.40.76), so a
   rebuild can move botocore under a frozen boto3. If a future bump renames or re-parents either
   class, the `isinstance` narrows to nothing and timeouts degrade quietly to `LLMUnavailable`. The
   two timeout tests are the catch, which is why they assert the **class**, not the message.
4. **`request_id` is a provider-controlled string (review round 1).** The logged value is
   `getattr(response, "id", None)` off the adapted payload — Bedrock's message id, falling back to
   `ResponseMetadata.RequestId`. On the two malformed-response branches the response is by
   definition suspect, so a sufficiently drifted payload could in principle put something other
   than an id in that field. **Not newly exposed by this PR:** `llm_client._result_from_response`
   already logs the identical field on every successful call, so the failure path now matches the
   approved success path rather than widening it. No sanitizer was added, deliberately — one on
   the failure path only would leave the two log lines inconsistent about the same value, and a
   charset/length filter is not a PHI guarantee anyway. If the field is ever hardened, both sites
   move together.
5. **ADR enumerations are stale, filed not amended — TODO-60** (owner decision, gate round 3).
   `adr/0004:38-39` enumerates the typed failures as exactly `LLMBudgetExceeded / LLMUnavailable /
   LLMConfigError / LLMResponseError`, and `adr/0009:78-80` states the mapping as `LLMUnavailable`
   for throttling/5xx/connection-after-retries — which this branch's `LLMTimeout` splits. Neither
   statement is wrong about behaviour (`LLMTimeout` subclasses `LLMUnavailable`, so every caller
   contract in both ADRs holds), but both read as complete enumerations and no longer are. Neither
   ADR is amended here; the drift is **filed as TODO-60** in this PR.

## Slices: test-first vs not

| Slice | Test-first? |
|-------|-------------|
| §1 `LLMTimeout` | **Yes.** Four tests red on `AttributeError: module has no attribute 'LLMTimeout'`, then the class + narrow, then green. |
| §1b `("LLMTimeout", 502)` parametrize | **Yes** — part of the same red set. |
| §2 six log sites | **Yes.** Five parametrized intake cases plus the visit-chat case, all red against the pre-fix `str(e)` (the captured records showed the planted `LEAK-SENTINEL` marker), then green. |
| §3 register rows | **No behavioural seam** — documentation. Covered by verification steps 7 and the grep cross-checks. |
| §4 seam-map cite | **No behavioural seam** — documentation. Covered by verification step 8's exact-residue table. |
| §5 frontend coverage | **Characterization, not red-green.** The production surface already satisfied SPEC-19/20, so the tests were green on first run by design. Their bite is proven by the step-10 break-then-revert instead: replacing the fixed fallback string with `` `Error: ${data?.detail}` `` reddens exactly the SPEC-20 provider-failure case. |
| §6 registry upkeep | **No behavioural seam** — `CLAUDE.md` §6 count and two `docs/todo.md` entries (TODO-59, TODO-60). |

## Verification run

All eleven steps of the plan's Verification section ran end-to-end.

- **Baseline first (step 1).** `make test-docker` on the clean tree: `923 passed, 5 deselected,
  1 xfailed` — matches `CLAUDE.md` §6 exactly, so nothing was layered on top of a moved count.
- **Final gate (step 11).** `make test-docker`: **`934 passed, 5 deselected, 1 xfailed`**. Passed
  grew by exactly the 11 this branch adds (4 timeout + 6 PHI-negative + 1 parametrize case; the
  strengthened `test_connection_error_maps_to_unavailable` adds no count). **xfailed and deselected
  did not move** — no deliberate gap moved. `CLAUDE.md` §6 updated to the **measured** number, not
  the plan's prediction.
- **`make eval`** green (the drift gate; run because this PR edits registries).
- **Re-verified after the impl-gate round-1 fixes** (`04a4ea6`, docs only): `make test-docker` →
  **`934 passed, 5 deselected, 1 xfailed`**, unmoved. Every handler name the two corrected register
  rows cite resolves by grep — `redis_unauthenticated:164`, `healthz:180`, `proxy_visit_chat:1032`
  in `services/gateway/app.py`; `intake_instructions:223`, `_reply_items:714` in
  `services/ai-assistant/app.py`. Steps 5, 7 and 8 re-run and reproduce unchanged (zero / eight
  lines `175 200 203 1063 1095 1106 1250 1259` / exactly one `D9` in the seam map). Step 8's
  **second half moved** at this commit and the note below records it: filing TODO-60 added a
  tenth `D9` location the plan's table could not have listed.
- **Break-then-revert negatives, all confirmed:**
  - step 4 — `class LLMTimeout(Exception)` reddens `test_llm_timeout_subclasses_unavailable` and
    `test_llm_errors_map_to_typed_statuses[LLMTimeout-502]`. Reverted, green.
  - step 6 — restoring `: %s", e` at the `LLMConfigError` branch reddens
    `test_llm_error_log_carries_no_exception_message[LLMConfigError]` with the marker found in the
    formatted record; same at the visit-chat site against its own test. Both reverted, green.
  - step 10 — `` setAiError(`Error: ${data?.detail}`) `` reddens the SPEC-20 provider-failure case
    on the "detail never reaches the DOM" assertion. Reverted; `git diff` on
    `frontend/app/intake/page.tsx` is empty, confirming no production frontend change shipped.
- **Step 5 grep**, both directions: `grep -nE ', e\)|^[[:space:]]*e,$' services/ai-assistant/app.py`
  returned exactly the six sites on the clean tree (`:236,249,252,266,271` one-line, `:796` the bare
  `e,` of the five-line call) and **zero** after the fix. The alternation is required — a
  single-pattern grep reports a false pass on the visit-chat site either way.
- **Step 7**, `grep -nE 'log\.(error|warning)\(.*%s.*, (e|exc)\)$' services/gateway/app.py` returned
  **eight** lines: the row's six (`175, 200, 203, 1063, 1095, 1106`) plus `1250` / `1259`, the
  `_post`/`_get` proxy helpers covered by their own OPEN row. Every location the corrected row names
  resolves to a real log call that stringifies the exception; none is a `raise` or a blank line. The
  row is still **OPEN** — this PR changes no gateway code. Cross-check the other way: every LLM-path
  exception `log.error` in `services/ai-assistant/app.py` appears in the `:94` row (`:182` and
  `:370` are configuration refusals with no exception, correctly out of scope).
- **Step 8**, `grep -n 'D9' docs/onboarding-seam-map.md` returns **exactly one** line, `:27`, no
  longer reading `remediation runbook, D9`; the surviving token sits in the misnumbering clause.
  Zero would have been a fail — it would leave a reader holding the client brief with nothing to
  match on. The full `grep -rn 'D9' docs/ .github/ adr/` residue matches the plan's nine-row table
  **plus exactly one line this branch introduces: `docs/todo.md:74`** — the `D9` inside TODO-60's
  "same class as the `adr/0006`/`adr/0008` D9 cites" clause, added by the impl-gate round-1 fix
  commit `04a4ea6` (`git show main:docs/todo.md | grep -c D9` → 0). The plan's table was measured
  on the clean tree before TODO-60 was filed, so it could not list it; the token is benign — it
  names the two ADR cites W1 deliberately leaves standing, the same disposition the table gives
  `adr/0006:63` and `adr/0008:128`. No other unlisted line. Raised as impl-gate round 2 finding 1,
  where the earlier unqualified "no unlisted line" claim here was false as written.
- **Step 9**, `cd frontend && npm test` → 6 files, 58 tests green (3 new). `npm run build`,
  `npm run typecheck`, `npm run lint` all green. The one lint warning (`DateField.tsx:103`,
  `aria-required` on a button role) is **pre-existing on `main`** — verified by stashing this branch
  and re-running.

## Review rounds

**Round 1 (2026-08-10), 1 finding, `[medium]`, labelled A — fixed.** The class-name-only sweep
removed the Bedrock `request_id` along with the message text: two of the three `LLMResponseError`
raise sites fire before the success log that emits the id, so a schema-drift incident left a 502
with no correlation handle after a paid egress. Fixed by carrying the id as a structured
attribute (above); SPEC-13 untouched, since the message is still never logged. Full disposition and
the finding's one over-statement are in `docs/workflow/w1/findings.md` §Review; the ledger line is
`docs/review-loop-metrics.md` §4.

Re-verified at that round: `make test-docker` → **`940 passed, 5 deselected, 1 xfailed`** (+6, all
new tests on the fix; xfailed and deselected unmoved), three break-then-revert checks red-then-green
(one per new log/raise site), and plan verification step 5's grep still **zero** — no `str(e)`
returned to any LLM-path site.

**Round 2 (2026-08-10), 0 findings, verdict `approve` — dry; loop closed at 2 rounds.** Tagged on
`73b9f06`, so it re-read the surface round 1's fix wrote rather than repeating the original diff, and
it did not re-raise its own r1 recommendation of provider error code / status that the disposition
declined. One scope note carried forward: the reviewer reads the code diff and named none of this
PR's four documentation slices (the two register rows, the seam-map cite, `CLAUDE.md` §6 /
`docs/todo.md`) — their evidence is plan verification steps 7 and 8, produced at the impl gate, not
anything the review loop checked. All 14 CI checks green at the merged head. Full round log:
`docs/workflow/w1/findings.md` §Review.

## Traceability

| SPEC | Evidence |
|------|----------|
| W1-SPEC-2 | `tests/test_llm_client.py::test_read_timeout_maps_to_llm_timeout`, `::test_connect_timeout_maps_to_llm_timeout`, `::test_llm_timeout_subclasses_unavailable`, `::test_timeout_error_carries_no_prompt` (negative), plus `::test_connection_error_maps_to_unavailable` strengthened with `not isinstance(..., LLMTimeout)` so the split cannot over-capture, and `tests/test_ai_intake_instructions.py::test_llm_errors_map_to_typed_statuses[LLMTimeout-502]`. Comments name the SPEC id. |
| W1-SPEC-12, 13 | `tests/test_ai_intake_instructions.py::test_llm_error_log_carries_no_exception_message` over all five intake branches; `tests/test_visit_chat_phi.py::test_degrade_log_carries_no_exception_message`. Comments name both SPEC ids. Review round 1 adds the other half of SPEC-12 — that the allowlisted metadata is still *there*: `::test_bad_response_log_carries_request_id_and_not_the_message`, `::test_degrade_log_carries_the_provider_request_id` (both plant PHI in the message and assert the id present, the message absent), plus `tests/test_llm_client.py::test_response_error_carries_request_id_attribute`, `::test_missing_usage_error_carries_request_id_attribute`, `::test_structured_validation_error_carries_request_id_attribute`, `::test_request_id_defaults_to_none_when_the_raiser_has_no_response`. |
| W1-SPEC-15 | Documentation statement — no test. Verified by step 7's two-direction cross-check. |
| W1-SPEC-16, 18 | Documentation statement — no test. Verified by step 8's exact-residue table. |
| W1-SPEC-19 | `frontend/app/intake/page.test.tsx` — "renders instructions produced through the LLM client path (W1-SPEC-19)". |
| W1-SPEC-20 | Same file — the provider-failure and transport-failure cases, both naming W1-SPEC-20. |
| W1-SPEC-1, 3–11, 14, 17 | Verified satisfied on `main` at plan stage (plan §Context table); no change proposed, so no new test. |

## Deviations from the plan

1. **TODO-59's widening is moot; the entry says so instead.** The gate record instructed TODO-59 to
   name `docs/todo.md` TODO-42's `.claude/hooks/xfail-invariant.sh` claim as a second instance of
   the same dead-hook class. Measured at implementation: **PR #67 (`4338d45`, on `main` and in this
   branch's base) already rewrote TODO-42** to state "no such hook exists on `main` (tracked
   `.claude/` is skills only — `CLAUDE.md` §11)". So `docs/landmines.md:127` is the only live
   instance. TODO-59 files that one and records the TODO-42 resolution explicitly, rather than
   re-asserting a correction that already landed. Plan fact wrong, fix trivial — patched and
   recorded, per the pipeline's deviation rule.
2. **TODO-60 (the ADR 0004 / 0009 typed-failure drift) is filed in this PR, though §6 names only
   TODO-59.** The plan's §6 registry-upkeep slice and its "Files touched" table list only TODO-59,
   so an earlier draft of this section declined to file TODO-60 on the grounds that the scope map
   does not name it. That was the wrong test, and the impl gate said so (round 1, finding 3): the
   gate record instructing "filed at landing as TODO-60" is plan content the drift gate checked and
   stamped clean in round 4, so filing it honors the plan rather than exceeding it. Id re-checked at
   landing per the standing rule — TODO-59 is the highest, 60 is free, no renumber. Both ADR line
   cites re-read this session before filing.
3. **Two register cites named handlers that do not exist** (impl gate round 1, findings 1–2). The
   `:94` row said `_plan_reply` and the `:93` row said `session_store`; neither symbol is in the
   repo. Real handlers are `_reply_items` (`services/ai-assistant/app.py:714`) and
   `redis_unauthenticated` (`services/gateway/app.py:163`). Both rows corrected, the `:93` row's
   remaining four cites re-attributed to `healthz` and `proxy_visit_chat`, and both rows now name
   their handlers as grep-resolvable symbols with line anchors — the check that would have caught
   this. One root cause: cite-by-handler written without verifying the handler name.

4. **Plan verification step 8's residue table is one line short of `HEAD`, by construction.** The
   step passes only when `grep -rn 'D9' docs/ .github/ adr/` "matches that table with no unlisted
   line", and the table was measured on the clean tree at plan stage. Filing TODO-60 — itself a
   plan instruction, carried in the gate record (deviation 2) — added `docs/todo.md:74` to that
   output. The plan is **not amended**: the table is a dated measurement of the tree it was taken
   on, and a residue line this branch deliberately adds is an expected delta, not drift. Recorded
   in the Verification run above instead. Raised as impl-gate round 2 finding 1; the reason it
   escaped the first time is that the post-`04a4ea6` re-verification re-ran only step 8's seam-map
   half, not the estate-wide residue check.

## Planned slices absent from the diff

None. Every slice in the plan's scope map (§1–§6) is present. No slice produced an empty result.

## Test count

`940 passed, 5 deselected, 1 xfailed` (was `923 passed, 5 deselected, 1 xfailed`; `934` at push,
+6 for review round 1). Frontend: 58 tests across 6 files (was 55 across 5).
