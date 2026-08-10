# PHI-Safe Logging Policy

> Applies to every service in this repo, on every log handler — console AND
> the repo-level `logs/<service>.log` file handlers. Adopted 2026-07-05.
> Companion code: `services/ai-assistant/redaction.py` (canonical helper).

## Rules

1. **Never log a request or response body raw.** Grep-able red flag:
   `model_dump_json()` or f-string interpolation of a Pydantic model inside a
   `log.*` call.
   - **Prefer an allowlisted metadata projection over a redacted body.**
     `redaction.safe_log_payload(obj)` only pattern-scrubs SSN/email/phone; it
     does **not** catch names, DOBs, or arbitrary PHI stuffed into a free-text
     or unconstrained field. So it is safe **only** for structures whose string
     values are all constrained/known — never for a body with open string
     fields. For request bodies, build a purpose-shaped dict of allowlisted
     values (enums + boolean presence flags), like
     `intake-service/schemas.py::log_metadata`, and log that. This mirrors the
     LLM metadata-only rule (rule 4).
   - `safe_log_payload` remains the fallback for internal payloads with no
     open free-text fields; keep it parity-tested.
2. **Identifier rules.**
   - Never loggable, even alone: `ssn`, `name`, `dob`, `address`, `phone`,
     `email`, free-text `notes`.
   - External identifiers prohibited: `insurance_id`, `member_id`,
     `group_number`, MRN. These are PHI-adjacent and re-identifiable.
   - Permitted: the internal surrogate `patient_id` (numeric PK) and other
     internal ids (`slot_id`, `appointment_id`). Scheduling relies on this.
3. **Exception strings leak.** `str(e)` on an outbound-call failure can embed
   the full request URL, including query params carrying identifiers
   (e.g. `?insurance_id=...`). The same applies to statement-level DB errors:
   a SQLAlchemy `DBAPIError` stringifies with `[SQL: ...] [parameters: (...)]`
   — the full bound row — unless the engine sets `hide_parameters=True` (see
   the register). In both cases log the exception class
   and status code, not the stringified exception.
4. **LLM rule (ai-assistant).** Prompts and completions are never logged, to
   any handler, at any level — they may contain arbitrary PHI. Log metadata
   only: model, token counts, cost, latency, request id. Wrapper enforces this
   (`llm_client.py`); tests pin it (`tests/test_llm_client.py` PHI-safety cases).
5. **Free-text rule (visit-chat, ADR 0011).** The chat `message` is the only
   free-text field a client can send this estate, and a clerk typing at a front
   desk will put a name, a DOB, or a member id in it. Three consequences, all
   enforced in code rather than by convention:
   - **Never logged.** Chat logging goes through
     `schemas.visit_chat_log_metadata` — an allowlist of closed values (intent
     enum, derived status, turn count). Never the message, never the transcript.
   - **Never sent to the vendor.** Intent derivation and the eligibility lookup
     are deterministic; the prompt is assembled only from closed vocabulary.
     While **D13** (Bedrock, no BAA) is open, no clerk prose may egress.
     `tests/test_visit_chat_phi.py` asserts the prompt is byte-identical to the
     deterministic build, which catches any future interpolation of the message.
   - **Never stored.** Visit memory records `{role, intent, status}` per turn —
     what happened, not what was said. Pattern redaction is *not* an acceptable
     substitute here: `redact_text` covers SSN / email / phone and cannot mask a
     typed patient name. If a future feature needs the transcript, that is a new
     PHI-at-rest decision requiring approval, not a schema tweak.
6. **PHI at rest in Redis (visit-chat, ADR 0011).** `facts.insurance_id` is the
   one PHI-adjacent value approved to persist, under an opaque `visit:{uuid4}`
   key, owner-bound, with a sliding TTL that IS its retention policy. Never put
   an identifier in a Redis key, and never persist a downstream `error` string
   (eligibility's carries the member id — the leak PR #11 closed). Redis itself
   was hardened alongside this feature (**debt-log D3b**, PR #14): the store is
   compose-internal, requires a password, refuses to start without one, and the
   gateway refuses to connect to an unauthenticated instance. Residual, and the
   reason the rules above still bind: no TLS in transit, one shared credential
   rather than per-consumer ACL users, no named volume (RDB snapshots stay
   container-local and unencrypted), and no audit trail of reads.

## How to comply in a service

1. Copy `services/ai-assistant/redaction.py` into your service (ADR 0001 — no
   shared lib). Keep the header noting it's a copy.
2. Add your copy to the parity test in `tests/test_redaction.py` so drift is
   caught in CI.
3. Route any payload logging through `safe_log_payload`.

## Known violations register

| Site | Status | Notes |
|------|--------|-------|
| `services/intake-service/app.py:67` full body at INFO | **FIXED 2026-07-08** | Now logs allowlisted metadata (`schemas.log_metadata`), body never logged. Interim `safe_log_payload(req)` (2026-07-05) still leaked names/DOBs via the open `consents` list — pattern scrub misses them; `consents` is now a `ConsentKind` enum (Codex review). |
| `logs/intake-service.log` (git-tracked) | **OPEN — ops** | Historical entries contain plaintext PHI. Needs: purge, gitignore, and a git-history-scrub decision. The code fix stops new leakage only. |
| `services/eligibility-service/app.py:44` logs `insurance_id` | OPEN | Violates rule 2 (external identifier) |
| `services/intake-service/app.py` `_verify_eligibility` error path | **FIXED 2026-07-08** | Was `str(e)` (could embed the payer URL + `insurance_id` query param, rule 3); now logs the exception class only and returns a generic error. Test: `tests/test_intake_eligibility_phi.py` (Codex review). |
| `services/intake-service/app.py` `_create_patient` error path | **FIXED 2026-08-05** | Logged `str(e)` on `SQLAlchemyError`; a statement-level `DBAPIError` (e.g. `DataError` on an oversized field) embeds `[parameters: (...)]` — the full patients row: name, DOB, SSN, address, notes (rule 3). Now logs the exception class only (the `_verify_eligibility` idiom). Test: `tests/test_intake_db_error_phi.py` (red pre-fix). Found by doc-drift follow-up 2026-08-05. |
| `services/intake-service/app.py` `_create_coverage` error path | **FIXED 2026-08-05** | Same class; would have embedded `member_id` / `group_number` (rules 2 and 3). Same fix and test. |
| `services/intake-service/app.py` `_record_consents` error path | **FIXED 2026-08-05** | Same `str(e)` pattern; bound values were benign consent kinds, fixed for class completeness (rule 3). |
| Engine-level backstop | **ADDED 2026-08-05** | `hide_parameters=True` on every service `create_engine` (gateway, intake, records, roi, scheduling — interop/eligibility have no engine). Scope is narrow and must not be over-read: it suppresses SQLAlchemy's `[SQL: ...] [parameters: (...)]` rendering only. The DBAPI driver's own message passes through untouched, and Postgres embeds bound data in whole error classes (`invalid input syntax for type X: "<value>"`, `DETAIL: Key (ssn)=(...) already exists`, `DETAIL: Failing row contains (...)`). The class-name log idiom is the control; the flag only narrows the blast radius of a future unfixed `str(e)` site — it does not make one safe. |
| `services/gateway/app.py` login handler `str(e)` DB-error path | **FIXED 2026-08-05** | Logged `str(e)` on the users SELECT — same rule-3 class; a statement-level error can embed the attempted username via the driver message. Auth zone (`docs/landmines.md` §1): folded into the intake DB-error fix on explicit approval. Now class name only. Test: `tests/test_gateway_login_db_error_phi.py` (red pre-fix). Found by the pre-push adversarial review of that fix. |
| `log.exception` on DB-error paths — scheduling (4), roi (4), records (4) | **FIXED 2026-08-05** | Codex r1 on PR #34. `log.exception` embeds the exception text via the traceback — same rule-3 class as `str(e)`, missed by the original grep. Worst sites: scheduling booking (raw psycopg2 via `book.py`, so the engine backstop never applies; `reason` free text bound), ROI create (`recipient`/`purpose` free text), records list/search (`q` is a typed patient name). All 12 sites now log the exception class only, no `exc_info`. `book.py` untouched (D5b landmine). Tests (red pre-fix, scan the formatted record incl. traceback): `tests/test_scheduling_booking_db_error_phi.py`, `tests/test_roi_db_error_phi.py`, `tests/test_records_search_db_error_phi.py`. ROI edits log-line-only, on explicit approval (§6). |
| Unhandled-exception ASGI tracebacks (all services) | OPEN | No service defines an app-level exception handler, so any DB/driver error that escapes a route's try lands in uvicorn's "Exception in ASGI application" traceback with the full driver message — the rendering the fixed sites suppress. One instance fixed 2026-08-05 (scheduling `cancel_appointment` ran `db.get` outside its try; found by the PR #34 pre-push pass, test in `tests/test_scheduling_booking_db_error_phi.py`). The generic backstop (a class-only-logging exception handler per service) is an open design call. |
| Redis-fault log sites — gateway `app.py`: the `redis_unauthenticated` exception handler, the two session-store probes in `healthz` (`RedisUnauthenticated` and `RedisUnreachable`), and the three visit memory/lock faults in `proxy_visit_chat` (one of them the first-turn `log.warning`) | OPEN | Log full exception text (`%s`, `exc`) on session-store/visit-memory/lock faults. redis-py error strings normally carry server/host text, not command arguments, so measured PHI risk is low — but unexamined; rule 3's Redis flavor. **Locations re-measured 2026-08-09** (status unchanged): the row previously cited `:1022,:1054`, which resolve to a `raise HTTPException` and a blank line. The six real sites are `:175, 200, 203, 1063, 1095, 1106` — the last of which the row omitted entirely. Cited by handler + exception shape rather than by line number for the reason the stale numbers demonstrate; each handler name above is a real symbol in that file (`redis_unauthenticated`, `healthz`, `proxy_visit_chat`), so the citation resolves by grep after the numbers move. Not fixed here: W1 scopes SPEC-12/13 to the LLM path, and these are session/lock faults, not LLM errors. |
| `services/ai-assistant/app.py` — `str(e)` on LLM-path errors: the five `intake_instructions` branches (`LLMConfigError`, `LLMUnavailable`, `LLMResponseError`, `LLMBudgetExceeded`, the `LLMError` catch-all) and the visit-chat degrade branch in `_reply_items` | **FIXED 2026-08-09** | The only vendor-egress service. An SDK error string can echo response-body fragments (which may derive from PHI-bearing prompts, D13); the `LLMError` catch-all logged the class name **and** `str(e)`. All six now use the class-only idiom (`CLAUDE.md` §4). **Two of the six were absent from this row until the W1 sweep found them** — the `LLMBudgetExceeded` branch and the visit-chat degrade — so the register was under-reporting its own subject (W1-SPEC-15). Cited by handler + exception class, not by line number, since the fix itself moves the numbers; both handler names are real symbols in that file (`intake_instructions:223`, `_reply_items:714`), so the citation resolves by grep. Tests (red pre-fix, scan the formatted record): `tests/test_ai_intake_instructions.py::test_llm_error_log_carries_no_exception_message` over all five intake branches, `tests/test_visit_chat_phi.py::test_degrade_log_carries_no_exception_message`. |
| `services/interop-service/app.py:54` `log.exception("HL7 parse failed")` | OPEN | Rule 3's parse-error flavor, not the DB class: a parse exception's text can embed the raw HL7 segment — an entire PHI-bearing message, worse than any bound row. Registered here first (PR #33 pattern); code fix belongs to a separate PR. |
| `services/gateway/app.py` `_post`/`_get` proxy helpers | OPEN | Log `str(e)` and return `{"error": str(e)}` on any outbound failure — rule 3's outbound flavor, in the known error-swallowing proxy debt (D4; CLAUDE.md §4 "do not imitate"). Measured mitigation: installed httpx renders `ConnectError` without the URL, so the common failure carries no query params; URL-bearing exception types are edge paths. Fix belongs to the D4 `_post_checked` migration, not a log patch. |
| `.env` committed to git | OPEN | Not a log site, but the same exposure class — tracked in `docs/debt-log.md` |
| Redis holds `facts.insurance_id` at rest (visit-chat) | **ACCEPTED 2026-07-26** | Approved under rule 6's controls (opaque key, owner binding, sliding TTL, no id in keys/logs). The Redis hardening that was its recommended precondition shipped with it (**D3b**, PR #14): no host publish, `requirepass`, scoped credential, gateway-side fail-closed guard. Residual: no TLS, one shared credential, no read audit trail. |

## Enforcement

- PR checklist: "No new `log.*` call includes a request/response body or an
  external identifier."
- Candidate CI check (not yet implemented): fail if `model_dump_json` appears
  inside a `log.` call.
