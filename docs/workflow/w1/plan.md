# W1 Code Plan — production LLM client, PHI-safe logging, seam map, debt entry

> Status: GATED 2026-08-09
> Plan maturity only. The plan header never carries delivery state (IMPLEMENTED, pushed,
> merged) — that lives in `docs/workflow/w1/pr-body.md`. The impl gate does not touch
> this header.
> Workflow stage 3 (code plan). Anchors to the frozen spec `docs/workflow/w1/spec.md`
> (W1-SPEC-1..20, AGREED 2026-08-09). Requirements: `docs/workflow/w1/requirements.md`
> (AGREED 2026-08-06).

## Gate record

**Gated 2026-08-09, fresh-context** (`.claude/skills/drift-gate/`), after four rounds —
`docs/workflow/w1/gate-findings.md` is the log. Round 3 hit the round-3 escalation rule; the
owner overruled both findings as plan findings and logged them as TODO carries, recorded in
their disposition cells. Implementation and review inherit the following without re-deriving
them:

- **Accepted residual, W1-SPEC-12/13** — the fix covers LLM-client errors on the ai-assistant
  path only. The Redis-fault sites `services/gateway/app.py:175, 200, 203, 1063, 1095, 1106`
  still log full exception text and stay OPEN in the register (§3 corrects their locations,
  not the sites). The scope map row is not full coverage of every log line on an `/ai` request.
- **Accepted residual, W1-SPEC-20** — the fallback is a fixed non-PHI message, not a
  deterministic offline checklist. Satisfies the statement as written; building a checklist is
  the AI feature requirements §6 puts out of scope.
- **Accepted residual, W1-SPEC-2 (version caveat)** — `boto3==1.40.0` does not pin botocore
  (metadata admits any `1.40.x`; measured 1.40.76). A re-parented or renamed timeout class
  narrows the `isinstance` to nothing and timeouts degrade quietly to `LLMUnavailable`; the two
  class-asserting tests are the catch.
- **TODO carry — new TODO-60** (owner-decided, round 3 finding 1). `adr/0004:38-39` enumerates
  the typed failures as exactly `LLMBudgetExceeded / LLMUnavailable / LLMConfigError /
  LLMResponseError`, and `adr/0009:78-80` (Accepted) states the mapping as `LLMUnavailable`
  (throttling/5xx/connection after retries) — the branch §1 splits. Neither ADR is amended by
  this PR; the drift is filed instead. Re-check the id at landing per the standing rule.
- **TODO carry — TODO-59 widens** (owner-decided, round 3 finding 2). The entry §6 files for
  `docs/landmines.md:127`'s push-hook claim also names `docs/todo.md` TODO-42's
  `.claude/hooks/xfail-invariant.sh` claim as the second instance of the same dead-hook class.
  No new id.

## Context

W1 is a **backfill of record** (requirements §2, owner decision 2026-08-06): every named
deliverable already exists on `main`, and this stage's job is to verify the existing
artifacts against the frozen spec and close what misses. The verification was run against
the working tree on 2026-08-09 and re-checked at gate round 1: **14 of 20 statements hold
as written; six do not** (SPEC-2, 12, 13, 15, 16, 18). Those six are four distinct gaps —
one gap spans SPEC-12 and SPEC-13, another spans SPEC-16 and SPEC-18. This plan is those
four gaps, plus the missing test gate under SPEC-19/20, and nothing else.

**Verification result — the 14 statements already satisfied** (no production change
proposed; SPEC-19 and SPEC-20 gain a test only, §5):

| SPEC | Satisfied by |
|------|--------------|
| 1 | `services/ai-assistant/llm_client.py:251-259` — botocore `Config(connect_timeout, read_timeout)` from `config.py:55-56`; pinned by `tests/test_llm_client.py:715` |
| 3 | same `Config`, `retries={"max_attempts": settings.llm_max_retries, "mode": "standard"}` — botocore standard mode is exponential backoff; attempt budget pinned by `tests/test_llm_client.py:726-728` |
| 4 | `llm_client.py:79-84` `_CONFIG_ERROR_CODES` are outside botocore's retryable set → `LLMConfigError`, no retry (`:492-499`); `tests/test_llm_client.py:413,420` |
| 5 | `llm_client.py:500-506` — `LLMUnavailable("throttled after retries (code=%s)")` names the final fault class; `tests/test_llm_client.py:406` |
| 6 | `llm_client.py:668` `model_validate_json`; `_result_from_response:546,555` fails closed on a missing text block or absent usage |
| 7 | `llm_client.py:671-674` `LLMResponseError`, message carries request id only, `result.parsed` never set on failure; `tests/test_llm_client.py:361,611-656` |
| 8 | `llm_client.py:469-471` — `_enforce_char_cap` + `_enforce_budget` both run before the `try` and before any SDK call; `tests/test_llm_client.py:107-206` |
| 9 | `llm_client.py:611,651` — `max_tokens or settings.llm_max_output_tokens` on both entry points, passed into every `create` |
| 10 | `llm_client.py:157-165` `LLMResult.input_tokens/output_tokens/estimated_cost_usd/latency_seconds` |
| 11 | prompts/completions never logged; `tests/test_llm_client.py:680,692,703` |
| 14 | `docs/phi-logging-policy.md` rules 1–6 + `services/ai-assistant/redaction.py` as the named reusable mechanism |
| 17 | `docs/debt-log.md` D1 (plaintext-PHI logs), D4 (unbounded eligibility call), cross-cutting `.env` row — all in business-risk prose with RIV tickets |
| 19 | `frontend/app/intake/page.tsx:141` → `frontend/app/api/ai/intake-instructions/route.ts:6` → `services/gateway/app.py:605` → `services/ai-assistant/app.py:218` — production path satisfies it today; §5 adds the missing test only |
| 20 | `frontend/app/intake/page.tsx:154` (provider failure) and `:159` (transport failure) render fixed non-PHI strings, never the downstream `detail` — §5 adds the missing test only |

**The four misses (six SPEC ids):**

1. **SPEC-2 — no typed *timeout* error.** A connect/read timeout reaches
   `llm_client.py:518-522` as a generic `BotoCoreError` and becomes
   `LLMUnavailable("connection error after retries (ReadTimeoutError)")`. Typed, and the
   class name is in the message, but a caller cannot separate a timeout from a throttle or
   a 5xx.
2. **SPEC-13 *and* SPEC-12 — six LLM-path log sites stringify the exception.**
   `services/ai-assistant/app.py:236,249,252,266,271` (`/intake-instructions`) and `:792`
   (`/visit-chat`) all log `%s` of the exception object. Registered OPEN at
   `docs/phi-logging-policy.md:94` with "Needs the class-only idiom; separate PR" — this is
   that PR. The gateway half of the path is already clean (`_post_checked` logs
   `type(e).__name__` only).

   **SPEC-12 is breached by the same six sites and is closed by the same fix** (gate round 1,
   finding 5): a stringified exception message is not one of SPEC-12's allowlisted fields
   (status class, latency, token counts, exception class). The rest of SPEC-12 *does* hold —
   `llm_client.py:567-575` is a metadata-only call log and `app.py:226` projects the request
   through an allowlist (`log_metadata(req)`, pinned by
   `tests/test_ai_intake_instructions.py:326`) — but partial satisfaction is not
   satisfaction, so SPEC-12 is recorded here as a miss rather than in the table above.
3. **SPEC-15 — the violation register is incomplete.** That same row lists four of the six
   sites; `:266` (`LLMBudgetExceeded` branch) and `:792` (visit-chat degrade) are absent, so
   the register under-reports its own subject.
4. **SPEC-16/18 — a W1 artifact cites a D-number that does not exist.**
   `docs/onboarding-seam-map.md:27` cites "`docs/debt-log.md` remediation runbook, **D9**";
   `docs/debt-log.md:6-7` states D9 does not exist in this repo. The seam map and the
   canonical mapping are both W1 deliverables, so this is a W1 verification miss against
   **both** ids: SPEC-16 (the seam map is the artifact carrying the dead cite) and SPEC-18
   (the mapping it should have been pointed at). What *does* hold on `main` is the rest of
   each: the seam map is one page with 6 seams and 8 walls, and `docs/debt-log.md:6-10`
   carries the canonical D1/D9/D3 mapping. Neither is recorded as satisfied above, because
   the dead cite is exactly the failure the two statements exist to prevent.

Neither SPEC-19 nor SPEC-20 has any test: the frontend
JS gate landed with `e1` (ADR 0018, `frontend/vitest.config.ts`) and `frontend/app/intake/`
has no test file. Closing that is in scope — a spec statement with no gate is a statement
that can regress silently.

**Decisions carried into this plan** (plan-stage, owner-confirmed 2026-08-09):
- SPEC-2 closes with a new `LLMTimeout(LLMUnavailable)` subclass, not an accepted residual.
  Subclassing keeps every existing `except LLMUnavailable` and the ADR 0007 502/keep-charge
  mapping working unchanged — additive, not a behaviour change.
- SPEC-13 is fixed at **all six** sites, including `/visit-chat:792`, rather than only the
  five on W1's own endpoint. One PHI path, one fix; leaving an identical violation live on
  the same path would re-open under the next sweep.
- The `docs/onboarding-seam-map.md:27` D9 cite is fixed **here**, not deferred to `e2`.
  `e2`-REQ-13's cite is `.github/workflows/ci.yml:113`; the seam map and the canonical
  mapping are W1's own artifacts (SPEC-16, SPEC-18).
- SPEC-19/20 get vitest coverage in this PR. No production frontend code changes.

## Scope map (spec → change)

| SPEC | Change |
|------|--------|
| W1-SPEC-1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 14, 17 | Verified satisfied on `main` (table above). No change. |
| W1-SPEC-2 | §1 — `LLMTimeout(LLMUnavailable)` raised from the botocore timeout types; tests |
| W1-SPEC-12, W1-SPEC-13 | §2 — class-name-only logging at all six ai-assistant LLM-path sites; negative tests. Same six sites breach both: SPEC-13's class-name-only rule and SPEC-12's metadata allowlist |
| W1-SPEC-15 | §3 — LLM-path register row (`:94`) corrected: all six sites named, status FIXED, cited by handler + exception class rather than by line number. Plus the Redis-fault row (`:93`), whose cited locations no longer resolve: re-measured to six real sites, status stays OPEN |
| W1-SPEC-16, W1-SPEC-18 | §4 — seam map D9 cite repointed at the canonical entries |
| W1-SPEC-19 | §5 — production path verified satisfied on `main`; adds vitest coverage of the checklist surface. No production change |
| W1-SPEC-20 | §5 — fallback verified satisfied on `main`; adds vitest coverage of the deterministic non-PHI fallback. No production change |
| — (registry upkeep) | §6 — `CLAUDE.md` §6 test-baseline re-measure; `docs/todo.md` TODO-59 for the stale landmines §3 push-hook claim |

## Implementation

### 1. Typed timeout error (W1-REQ-1 / SPEC-2)

`services/ai-assistant/llm_client.py`.

Add the class next to the other typed errors, after `LLMUnavailable` (`:133-138`):

```python
class LLMTimeout(LLMUnavailable):
    """Connect or read timeout after botocore's retries — the time bound in
    ADR 0004 fired. A subclass of LLMUnavailable on purpose: callers that only
    care "the provider did not answer" keep working unchanged (ai-assistant
    app.py's 502 branch, and through it the gateway's ADR 0007 keep-charge
    rule), while a caller that needs to distinguish a timeout from a throttle
    now can. Post-egress like its parent: a timeout means the request was
    attempted and may be billable, so the inherited egressed=True stands."""
```

Extend the botocore import block (`:42-48`) with `ConnectTimeoutError` and
`ReadTimeoutError`. `services/ai-assistant/requirements.txt:5` pins `boto3==1.40.0`, whose
own metadata requires `botocore>=1.40.0,<1.41.0` — so the version any gate actually runs is
a botocore 1.40.x, **not** 1.37.x (gate round 2, finding 1). Verified this session under
that pin (`.venv`, python 3.12.13, boto3 1.40.0 / botocore 1.40.76): both names exist and
both subclass `BotoCoreError` — `ReadTimeoutError` via `HTTPClientError`,
`ConnectTimeoutError` via botocore's own `ConnectionError`.

Narrow inside the existing `except BotoCoreError` branch (`:518-522`) rather than adding a
new `except` clause:

```python
    except BotoCoreError as exc:
        # Connect/read timeout or endpoint connection failure, after retries.
        if isinstance(exc, (ConnectTimeoutError, ReadTimeoutError)):
            raise LLMTimeout(
                "timed out after retries (%s)" % type(exc).__name__
            ) from None
        raise LLMUnavailable(
            "connection error after retries (%s)" % type(exc).__name__
        ) from None
```

The `isinstance` split is load-bearing in *placement*: the credential-error branch at
`:507-517` must keep preceding `BotoCoreError` (all three credential classes subclass it,
and PR #5 round 2 established that a credential failure is a config error, not an outage).
A new `except (ConnectTimeoutError, ReadTimeoutError)` clause would have to sit above
`BotoCoreError` too, adding a second ordering constraint to a block that already carries
one. Narrowing inside the branch adds none.

Message stays metadata-only: exception class name, no URL, no prompt.

### 2. Class-name-only logging on the LLM path (W1-REQ-5 / SPEC-12, SPEC-13)

`services/ai-assistant/app.py`. Six sites, all currently `%s` on the exception object.
Five in `intake_instructions` (`:236` config, `:249` unavailable, `:252` bad response,
`:266` budget refusal, `:271` catch-all) and one in the visit-chat reply planner (`:792`).

```python
-        log.error("intake-instructions config error: %s", e)
+        log.error("intake-instructions config error (%s)", type(e).__name__)
```

...and the same shape for the other four intake branches. `:271` already logs the class and
then repeats the message — it loses only the trailing `: %s", e`. Visit-chat:

```python
         log.error(
-            "visit-chat degrading to deterministic reply (%s, egressed=%s): %s",
+            "visit-chat degrading to deterministic reply (%s, egressed=%s)",
             type(e).__name__,
             egressed,
-            e,
         )
```

Note the layout: `:792`'s call spans five lines with **one argument per line**, so the
deletion at `:796` is a bare `e,`. Verification step 5's grep is written to match both
layouts for that reason.

The idiom is `CLAUDE.md` §4's (`log.error("...(%s)", type(e).__name__)`), already used by
`intake-service::_verify_eligibility` and `gateway::_post_checked`.

The in-line comment at `:234-235` ("llm_client error messages are metadata-only by
contract — safe to log") is the reasoning this change overrides, and must be replaced
rather than left standing: the contract holds today, but SPEC-13 is a flat rule precisely
so that a future `llm_client` raise site cannot quietly widen what a caller logs. Replace it
with one line naming the rule and the policy doc.

Response bodies are unaffected — every branch already returns a generic `detail`, pinned by
`tests/test_ai_intake_instructions.py:614-624`.

### 3. Violation register correction (W1-REQ-6 / SPEC-15)

`docs/phi-logging-policy.md:94`. The row becomes **FIXED 2026-08-09**, naming all six sites
**by handler and exception class, not by line number** — the four raw line numbers it
carries are already one edit away from being wrong, and this change moves them. Text
records: what the sites were (`str(e)` on LLM-path errors), that `:266` and `:792` were
absent from the row until this sweep found them, the fix (class-only idiom), and the tests.

**One neighbouring row also gets its locations corrected — status unchanged** (gate round 2,
finding 3). The Redis-fault row at `:93` cites gateway `app.py:175,200,203,1022,1054`.
Measured this session, `:1022` is `raise HTTPException(status_code=502, …)` and `:1054` is
blank; the real visit-memory/lock sites are `:1063` (`log.error("visit memory unavailable:
%s", e)`), `:1095` (`log.error("visit lock unavailable: %s", e)`) and a third the row omits
entirely, `:1106` (`log.warning("visit lock unavailable on a first turn (%s); proceeding
unlocked", e)`). Only `:175,200,203` still resolve. A register whose locations point at a
`raise` and a blank line is not the *live* register SPEC-15 requires, so the row is
re-measured in the same edit: six sites, cited **by handler + exception shape** like the
`:94` row, status stays **OPEN**, text otherwise unchanged. This corrects the row's
locations; it does not fix the sites (that scope boundary is the accepted residual in
Landmines).

Nothing else in the register moves. The other cited locations were re-measured this session
and still resolve: `services/interop-service/app.py:54` is the `log.exception("HL7 parse
failed")`, and the `:94` row's own `:236,249,252,271` are the four `str(e)` sites it names.
The interop HL7 parse, gateway `_post`/`_get` and unhandled-exception ASGI rows stay OPEN
with their current text.

### 4. Seam map D9 cite (W1-REQ-7 / SPEC-16, W1-REQ-8 / SPEC-18)

`docs/onboarding-seam-map.md:27`, the `.env` wall. Replace the trailing
`(`docs/debt-log.md` remediation runbook, D9)` with a cite at the canonical entries — the
**Remediation runbook** table and the cross-cutting `` `.env` committed with secrets `` row,
neither of which carries a D-number — plus a short clause noting that "D9" is client-brief
misnumbering per `docs/debt-log.md:6-10`. One line; no other wall or seam text changes.

**The replacement text keeps the literal string "D9"**, inside that clause and nowhere else.
Removing the token entirely would leave a reader who arrives holding the client brief with
nothing to match on — the same failure the `debt-log.md:6-7` numbering note exists to
prevent, and that note keeps the token for exactly this reason. So the post-change state of
`docs/onboarding-seam-map.md` is **one** `D9` occurrence, at `:27`, in a clause that says it
is not a real ID — not zero. Verification step 8 asserts that, not absence (gate round 1,
finding 1).

Deliberately **not** touched: `.github/workflows/ci.yml:112` and `:119`, and
`docs/runbook.md:230`, which carry the same dead number. Both files are CI-claim accuracy,
which is `e2`-REQ-13's scope (`docs/workflow/e2/requirements.md:132-133,197`, at
requirements-DRAFT). Two items editing the same claim class is how the confident stale copy
wins.

> Flag for `e2`, not corrected here: `e2`'s requirements cite the CI D9 label as
> `ci.yml:113`. The actual occurrences are `:112` (the `secret-scan` comment) and `:119`
> (the "remainder of D9" comment); `:113` carries neither. `e2` is owner-held at
> requirements-DRAFT, so this belongs to its spec stage — W1 does not edit another item's
> frozen-pending artifact.

Historical `D9` cites in `adr/0006:63` and `adr/0008:128` stay: an ADR records a decision as
taken, and the doc-archive rule keeps a cited file in the tree rather than rewriting it.

### 5. Frontend coverage for the visible surface (W1-REQ-9 / SPEC-19, SPEC-20)

New `frontend/app/intake/page.test.tsx`. **No production frontend code changes** — the
surface at `page.tsx:128-163,182-221` already satisfies both statements; this is the gate
that stops it regressing.

Follows the `e1` convention exactly, as `frontend/app/assistant/page.test.tsx:1-28` does:
explicit `import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"` (no
Vitest globals — that is the e1 `tsc --noEmit` lesson), explicit `afterEach(cleanup)`,
`vi.mock("../lib/session", ...)` for `apiFetch`, and a local `jsonResponse` helper.

The checklist card is gated behind `result?.ok` (`page.tsx:165`), so each case first drives
the wizard to a submitted state. That is **a four-step wizard** (`STEPS` at `page.tsx:34`;
step state at `:37`), and the three required fields, the two required consents and the
submit button live on three *different* steps — so the shared setup is field entry plus
three `Continue` clicks, not a single form fill. Written once as a `submitIntake()` helper
the three cases share:

```
step 0  Demographics    first_name, last_name  -> screen.getByLabelText(/first name/i) etc.
                                                  (Field renders <label htmlFor={id}> over
                                                  <input id={id}>, page.tsx:441,455)
                        dob                    -> DateField is a popover, not a text input
                                                  (frontend/app/components/DateField.tsx:103-131):
                                                  click the trigger, then pick today's cell in
                                                  the role="dialog" DayPicker. disableFuture
                                                  guarantees today is enabled, so it needs no
                                                  fixed date.
                        -> "Continue" (enabled only once demoOk, page.tsx:73,387)
step 1  Insurance       nothing entered — every field is optional and Continue is ungated.
                        Leaving it blank also pins the fetchInstructions payload shape:
                        has_insurance=false, plan_type=null (page.tsx:135-139).
                        -> "Continue"
step 2  Consents        c_treatment + c_privacy (both required by consentsOk, page.tsx:72)
                        -> screen.getByLabelText(/consent to treatment/i) and
                           /notice of privacy practices/i — Consent renders
                           <label htmlFor={id}> over an <input type="checkbox">
                           (page.tsx:526,533)
                        -> "Continue" (gated on consentsOk, page.tsx:387)
step 3  Review & Submit -> "Submit intake" (page.tsx:401), with apiFetch mocked 200 once;
                           await the success card before touching the checklist button
```

Then, with `apiFetch` queued a second time, click "Get visit prep instructions":

1. **SPEC-19** — 200 `{items: [...], disclaimer: "..."}` renders the items as list entries
   and the disclaimer, and the call went to `/api/ai/intake-instructions`.
2. **SPEC-20, provider failure** — 502 `{detail: "assistant is temporarily unavailable"}`
   renders the fixed string at `page.tsx:154` and **asserts the downstream `detail` never
   reaches the DOM** (the negative half: the fallback is deterministic, not a relayed error).
3. **SPEC-20, transport failure** — `apiFetch` rejects; the `catch` string at `page.tsx:159`
   renders and the rejection text does not.

Note for whoever reads the diff: `apiFetch` is mocked, so the mocked 200 on `/api/intake`
is **not** an assertion that registration works. It does not touch, test, or mask the intake
contract break (`docs/debt-log.md` "Intake contract break", TODO-1) — that defect is
backend-side and stays exactly as visible as it is now.

### 6. Registry upkeep

- **`CLAUDE.md` §6 test baseline.** The measured baseline (`923 passed, 1 xfailed, 5
  deselected`, 2026-08-08) moves by the python tests below. §6 says a moved count is a
  finding, not a number to update — so the PR records the delta as a *deliberate* addition
  with the count re-measured under `make test-docker`, never carried over from this plan.
  Expected: **+11 passed**, xfailed and deselected unchanged.
- **`docs/todo.md` TODO-59** (next free id; TODO-58 is the highest on `main` — re-check at
  landing per the standing id rule, and renumber if something else took 59 in the interim).
  Found during this stage, out of every W1 SPEC's scope, so filed rather than fixed:
  `docs/landmines.md` §3 states "A push hook pins the expected xfail and deselected counts",
  and **there is no such hook** — `git ls-files .claude` returns nine `SKILL.md` files and
  nothing else, and neither the `Makefile` nor `.github/workflows/ci.yml` installs one. The
  count guard is documentation, not enforcement. Same claim class as `e2`-REQ-13 but a
  different file, so it is filed where a doc-drift sweep looks.

### Tests

Python (`make test-docker`, the claim-worthy gate):

| File | Tests |
|------|-------|
| `tests/test_llm_client.py` | `test_read_timeout_maps_to_llm_timeout`, `test_connect_timeout_maps_to_llm_timeout`, `test_llm_timeout_subclasses_unavailable` (existing `except LLMUnavailable` callers still catch it), `test_timeout_error_carries_no_prompt` (negative — a PHI-bearing prompt, assert the exception message holds neither prompt nor URL). Plus **strengthen** the existing `test_connection_error_maps_to_unavailable:427`: assert the `EndpointConnectionError` case is `not isinstance(exc, LLMTimeout)`, so the split cannot over-capture. |
| `tests/test_ai_intake_instructions.py` | add `("LLMTimeout", 502)` to the `test_llm_errors_map_to_typed_statuses` parametrize (`:608-624`), keeping it aligned with `_GATEWAY_REFUNDED_STATUSES` — 502 is kept-charged, which is right for a post-egress timeout. Plus `test_llm_error_log_carries_no_exception_message`, parametrized over all five intake branches: raise each error class with a PHI-shaped marker in its message, capture at DEBUG, and scan the **formatted** record (the `test_scheduling_booking_db_error_phi.py` idiom) for the marker. |
| `tests/test_visit_chat_phi.py` | `test_degrade_log_carries_no_exception_message` — same shape for the `:792` branch, asserting the reply still degrades deterministically. |

That is 4 + 6 + 1 = **11 new python test cases** (the added parametrize case counts as one),
plus 1 strengthened existing test, which adds no count — hence the +11 expected above. Every
one of them is red before its fix, per the TDD inner loop.

These are the `docs/landmines.md` §3 negative tests SPEC-11..13 are flagged for: the
adversarial input is PHI placed where the code does not expect it (inside an exception
message), and the assertion runs over the real log-formatting path rather than the
call arguments.

Frontend (`cd frontend && npm test`): the three cases in §5.

## Files touched

| File | Change |
|------|--------|
| `services/ai-assistant/llm_client.py` | new `LLMTimeout(LLMUnavailable)` after `:133-138`; `ConnectTimeoutError`/`ReadTimeoutError` added to the botocore import block `:42-48`; `isinstance` narrow inside the existing `except BotoCoreError` at `:518-522` (§1) ⚠ |
| `services/ai-assistant/app.py` | six LLM-path `log.error` sites (`:236,249,252,266,271,792`) to class-name-only; the `:234-235` "safe to log" comment replaced with the SPEC-13 rule + policy cite (§2) ⚠ |
| `docs/phi-logging-policy.md` | register row `:94` → **FIXED 2026-08-09**, all six sites named by handler + exception class; register row `:93` (Redis-fault) locations re-measured to `:175,200,203,1063,1095,1106`, status stays OPEN (§3) ⚠ |
| `docs/onboarding-seam-map.md` | `:27` `.env` wall — dead `D9` cite repointed at the remediation runbook + cross-cutting `.env` row, with the misnumbering clause (§4) |
| `frontend/app/intake/page.test.tsx` | new — SPEC-19 render, SPEC-20 provider-failure and transport-failure fallbacks (§5). No production frontend file changes |
| `tests/test_llm_client.py` | 4 new timeout tests + `test_connection_error_maps_to_unavailable:427` strengthened with a `not isinstance(..., LLMTimeout)` assertion |
| `tests/test_ai_intake_instructions.py` | `("LLMTimeout", 502)` added to the `:608-624` parametrize; new `test_llm_error_log_carries_no_exception_message` over the five intake branches |
| `tests/test_visit_chat_phi.py` | new `test_degrade_log_carries_no_exception_message` for the `:792` branch |
| `CLAUDE.md` §6, `docs/todo.md` (new TODO-59) | registry upkeep (§6) — baseline re-measured under `make test-docker`, never carried from this plan |
| `docs/workflow/w1/plan.md`, `gate-findings.md`, `pr-body.md` (new) | workflow artifacts |

⚠ = touches a `docs/landmines.md` §1 zone (PHI handling / the vendor-egress path). See
Landmines below for the approval record.

## Out of scope (from requirements §6)

- **The full AI intake-instructions feature beyond a minimal surface** — deliverable says
  "Not 'build the AI feature'"; the owner-ruled scope is the safe client (REQ-1..4) plus a
  minimal visible surface (REQ-9), not a polished feature.
- **Fixing registration slowness (RIV-088/D4)** — named as a stated problem, not a
  deliverable; already partly closed by ADR 0010.
- **Secret rotation, `.env` untracking, git-history purge** — human-run, irreversible
  remediation runbook (`docs/debt-log.md`); ⚠ gated, not W1 work.
- **Correcting the README compliance claim** — TODO-12, human-gated by scenario design.
- **Column-level PHI encryption** — ADR 0002 deliberately skips it; changing that is a
  PHI-columns gated decision, not a W1 requirement.

## Verification (end-to-end)

1. **Baseline first.** `make test-docker` on a clean tree; record `923 passed, 1 xfailed,
   5 deselected`. If it differs, stop — a moved count is a finding to report before any
   edit lands on top of it (`CLAUDE.md` §6).
2. **SPEC-2, positive.** `make test-docker` — the two new timeout tests pass; a
   `ReadTimeoutError` from the fake client raises `LLMTimeout`, a `ConnectTimeoutError`
   likewise.
3. **SPEC-2, non-regression.** `test_llm_timeout_subclasses_unavailable` and the
   strengthened `test_connection_error_maps_to_unavailable` both pass: existing
   `except LLMUnavailable` sites still catch a timeout, and a plain
   `EndpointConnectionError` is still *not* an `LLMTimeout`.
4. **SPEC-2, negative (break-then-revert).** Change the new class to
   `class LLMTimeout(Exception)` — `test_llm_timeout_subclasses_unavailable` and
   `tests/test_ai_intake_instructions.py::test_llm_errors_map_to_typed_statuses[LLMTimeout]`
   both go red (the 502 branch stops catching it). Revert; green.
5. **SPEC-12 / SPEC-13, positive.** The six sites log only the class name. Confirm by eye in
   the diff, and by
   `grep -nE ', e\)|^[[:space:]]*e,$' services/ai-assistant/app.py` returning **nothing**.
   The alternation is required because the two call layouts differ: `:236,249,252,266,271`
   end `, e)` on one line, while `:792` spans five lines with one argument per line, so its
   deletion is the bare `e,` at `:796`. Pre-change this grep returns exactly those six lines
   — run it on the clean tree first, confirm six, then again after the fix and confirm zero.
   A single-pattern grep would report a false pass on `:792` either way (gate round 1,
   finding 3).
6. **SPEC-13, negative (break-then-revert).** Restore `: %s", e` at `intake_instructions`'s
   `LLMConfigError` branch — `test_llm_error_log_carries_no_exception_message[LLMConfigError]`
   goes red with the PHI marker found in the formatted record. Revert; green. Repeat once at
   `:792` against the visit-chat test.
7. **SPEC-15.** The `:94` row names all six sites, including the two it previously omitted,
   and cites them by handler + exception class. Cross-check: every LLM-path `log.error` in
   `services/ai-assistant/app.py` appears in the row. Then the Redis row: every location it
   now names resolves to a real log call that stringifies the exception. Run
   `grep -nE 'log\.(error|warning)\(.*%s.*, (e|exc)\)$' services/gateway/app.py`; measured on
   the clean tree 2026-08-09 it returns **eight** lines — the row's six
   (`175, 200, 203, 1063, 1095, 1106`) plus `1250` and `1259`, which are the `_post`/`_get`
   proxy helpers covered by their own OPEN row. The step passes when the row's six are
   exactly the non-proxy six, and no location the row names is a `raise` or a blank line.
   Status on that row is still **OPEN**; a row flipped to FIXED here is a fail, since this
   PR changes no gateway code.
8. **SPEC-16 / SPEC-18.** `grep -n 'D9' docs/onboarding-seam-map.md` returns **exactly one
   line**, `:27`, and that line no longer reads `remediation runbook, D9` — the surviving
   token sits inside the clause naming it client-brief misnumbering (§4). Zero occurrences
   is a *fail*, not a pass: it would mean the reader holding the brief lost the match.

   Then the residue check, `grep -rn 'D9' docs/ .github/ adr/`. Measured on the clean tree
   2026-08-09, the full set is:

   | Location | Disposition |
   |----------|-------------|
   | `docs/onboarding-seam-map.md:27` | changed by §4 — one occurrence, misnumbering clause |
   | `docs/debt-log.md:6,7` | the canonical numbering note — the thing being cited |
   | `docs/runbook.md:230` | `e2`-REQ-13 (CI-claim accuracy), deliberately not touched |
   | `.github/workflows/ci.yml:112,119` | same — and note `e2`'s cite says `:113` (§4 flag) |
   | `docs/specs-deprecated/w1.md:7` | archive; records the brief as received |
   | `docs/workflow/e2/requirements.md:132,133,197` | another item's artifact, at DRAFT |
   | `docs/workflow/w1/requirements.md:31,41,68,75`, `spec.md:68` | W1's own frozen inputs |
   | `docs/workflow/w1/plan.md`, `gate-findings.md`, `pr-body.md` | this plan, its round log, and the PR body written at implementation — all three describe the change, so all three name the token |
   | `adr/0006:63`, `adr/0008:128` | decisions-as-taken; the doc-archive rule keeps them |

   The step passes when the output matches that table with no unlisted line. Listing the
   full set is the point: a partial expectation makes the command's output unreadable as
   pass/fail (gate round 1, finding 2).
9. **SPEC-19 / SPEC-20.** `cd frontend && npm install && npm test` — three new cases green.
   Then `npm run build`, `npm run typecheck`, `npm run lint` all green (the new test file
   must survive `tsc --noEmit`, which is the e1 lesson).
10. **SPEC-20, negative (break-then-revert).** In `page.tsx:154`, replace the fixed string
    with `` `Error: ${data?.detail}` `` — the SPEC-20 provider-failure case goes red on the
    "detail never reaches the DOM" assertion. Revert; green.
11. **Full gate.** `make test-docker` reports the new baseline; xfailed still 1, deselected
    still 5. `make eval` green (untouched, but it is the drift gate and this PR edits
    registries). Record the measured counts in `pr-body.md` and update `CLAUDE.md` §6 to
    match what was measured, not what this plan predicted.

## Landmines / risk

- **`docs/landmines.md` §1 zones touched: PHI handling (logging paths only).** No auth, no
  PHI columns, no ROI/disclosure logic, no migrations, no `.env` or secret file. The change
  removes text from log lines and adds a typed exception; it moves no PHI boundary, changes
  no HTTP status, and adds no egress. `/ai/*` remains the only vendor-egress path and this
  PR does not widen it.
- **Human approval record.** SPEC-11..15 carry the spec's ⚠ human-gate marker and SPEC-19 is
  flagged for vendor-egress adjacency. Per the `w2` precedent (`docs/workflow/w2/plan.md`
  Landmines), **this plan's owner review is the planning approval** for the PHI-handling
  edits it names — `services/ai-assistant/app.py`'s six log sites,
  `docs/phi-logging-policy.md:94`, and the `llm_client.py` raise-site change. The code change
  still rides the gated review: impl gate, then codex review, then merge. Nothing here is
  self-approved at implementation time. The egress-adjacent statements (SPEC-19/20) get tests
  only — no production frontend or route change — so the approved surface is logging text and
  one new exception subclass, nothing that alters what leaves the estate.
- **§3 negative-test rule applies and is satisfied** — every one of the six log-site fixes
  carries an adversarial test that plants a PHI marker inside the exception and scans the
  formatted log record. See the Tests table.
- **Deliberate defects preserved.** Nothing here touches D1's historical
  `logs/intake-service.log`, D4's inline placement, D5b's `book.py`, D11, D13, or the intake
  contract break (TODO-1). The frontend test mocks `apiFetch`, so it neither exercises nor
  masks the broken registration path.
- **Accepted residual — SPEC-12/13 scope boundary.** The fix covers *LLM-client* errors on the
  ai-assistant path. The Redis-fault sites on the same `/ai` routes still log full exception
  text and stay **OPEN**. Measured this session, they are `services/gateway/app.py:175, 200,
  203, 1063, 1095, 1106` — not the `:175,200,203,1022,1054` the register row claimed, which
  §3 corrects (gate round 2, findings 2 and 3). They are session-store/visit-memory/lock
  faults, not LLM errors, and REQ-5 scopes SPEC-12/13 to "the LLM path"; the register's own
  measured note is that redis-py error strings carry server/host text rather than command
  arguments. Named here so the scope map row is not read as full coverage of every log line
  on an `/ai` request.
- **Accepted residual — SPEC-20 is a message, not a checklist.** The fallback is a fixed
  non-PHI string ("Could not prepare your checklist right now."), not a deterministic set of
  instructions. It satisfies the statement as written (deterministic, non-PHI, not a raw
  error) and the new test pins it, but a reader expecting an offline checklist will not find
  one. Building one is the AI feature that requirements §6 puts out of scope.
- **Gate interaction — frontend.** `next build` type-checks, and lints once an eslint config
  exists, so a broken new test file reddens `npm run build` *before* the dedicated
  `typecheck`/`lint`/`test` steps. Read a red build on this PR as the test file first.
- **Gate interaction — python.** CI and `make test-docker` run the same suite; there is no
  hook enforcing the xfail/deselected counts (that is TODO-59), so the count check in
  verification step 11 is a human step, not an automated one.
- **Version caveat.** `LLMTimeout` keys on `botocore.exceptions.ConnectTimeoutError` /
  `ReadTimeoutError`. The `boto3==1.40.0` pin
  (`services/ai-assistant/requirements.txt:5`) does not pin botocore itself — boto3's
  metadata admits any `botocore>=1.40.0,<1.41.0`, so a rebuild can move botocore under a
  frozen boto3. Verified at botocore **1.40.76** this session (`.venv`, python 3.12.13);
  1.37.x is this machine's ambient anaconda py3.8 botocore, which `CLAUDE.md` §3 says cannot
  run the suite, and is not a version any gate executes. Both are long-stable public names,
  but they are botocore internals-adjacent: if a future bump
  renames or re-parents them, the `isinstance` narrows to nothing and timeouts silently fall
  back to `LLMUnavailable` — a quiet degrade, not a failure. The two timeout tests are what
  catch it, which is why they assert the class rather than the message.
- **PR body line:** touches `docs/landmines.md` §1 PHI-handling zone (logging paths only);
  §3 negative tests included; no auth, PHI-column, ROI, migration or secret change.
