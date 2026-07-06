# PHI-Safe Logging Policy

> Applies to every service in this repo, on every log handler — console AND
> the repo-level `logs/<service>.log` file handlers. Adopted 2026-07-05.
> Companion code: `services/ai-assistant/redaction.py` (canonical helper).

## Rules

1. **Never log a request or response body raw.** If a payload must be logged,
   it goes through `redaction.safe_log_payload(obj)` — no exceptions. Grep-able
   red flag: `model_dump_json()` or f-string interpolation of a Pydantic model
   inside a `log.*` call.
2. **Identifier rules.**
   - Never loggable, even alone: `ssn`, `name`, `dob`, `address`, `phone`,
     `email`, free-text `notes`.
   - External identifiers prohibited: `insurance_id`, `member_id`,
     `group_number`, MRN. These are PHI-adjacent and re-identifiable.
   - Permitted: the internal surrogate `patient_id` (numeric PK) and other
     internal ids (`slot_id`, `appointment_id`). Scheduling relies on this.
3. **Exception strings leak.** `str(e)` on an outbound-call failure can embed
   the full request URL, including query params carrying identifiers
   (e.g. `?insurance_id=...`). On outbound failures log the exception class
   and status code, not the stringified exception.
4. **LLM rule (ai-assistant).** Prompts and completions are never logged, to
   any handler, at any level — they may contain arbitrary PHI. Log metadata
   only: model, token counts, cost, latency, request id. Wrapper enforces this
   (`llm_client.py`); tests pin it (`tests/test_llm_client.py` PHI-safety cases).

## How to comply in a service

1. Copy `services/ai-assistant/redaction.py` into your service (ADR 0001 — no
   shared lib). Keep the header noting it's a copy.
2. Add your copy to the parity test in `tests/test_redaction.py` so drift is
   caught in CI.
3. Route any payload logging through `safe_log_payload`.

## Known violations register

| Site | Status | Notes |
|------|--------|-------|
| `services/intake-service/app.py:67` full body at INFO | **FIXED 2026-07-05** | Now `safe_log_payload(req)`; was raw `model_dump_json()` (D1) |
| `logs/intake-service.log` (git-tracked) | **OPEN — ops** | Historical entries contain plaintext PHI. Needs: purge, gitignore, and a git-history-scrub decision. The code fix stops new leakage only. |
| `services/eligibility-service/app.py:44` logs `insurance_id` | OPEN | Violates rule 2 (external identifier) |
| `services/intake-service/app.py` `_verify_eligibility` error path | OPEN | `str(e)` can embed the payer URL + `insurance_id` query param (rule 3) |
| `.env` committed to git | OPEN | Not a log site, but the same exposure class — tracked in `docs/debt-log.md` |

## Enforcement

- PR checklist: "No new `log.*` call includes a request/response body or an
  external identifier."
- Candidate CI check (not yet implemented): fail if `model_dump_json` appears
  inside a `log.` call.
