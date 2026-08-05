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
| `services/intake-service/app.py:137` `_create_patient` error path | OPEN | Logs `str(e)` on `SQLAlchemyError`; a statement-level `DBAPIError` (e.g. `DataError` on an oversized field) embeds `[parameters: (...)]` — the full patients row: name, DOB, SSN, address, notes (rule 3). Shared cause: `db.py:9` engine has no `hide_parameters=True`. Found by doc-drift follow-up 2026-08-05. |
| `services/intake-service/app.py:154` `_create_coverage` error path | OPEN | Same class as app.py:137; would embed `member_id` / `group_number` (rules 2 and 3). Shared cause: `db.py:9`. |
| `services/intake-service/app.py:167` `_record_consents` error path | OPEN | Same `str(e)` pattern; bound values are benign consent kinds, listed for class completeness (rule 3). Shared cause: `db.py:9`. |
| `.env` committed to git | OPEN | Not a log site, but the same exposure class — tracked in `docs/debt-log.md` |
| Redis holds `facts.insurance_id` at rest (visit-chat) | **ACCEPTED 2026-07-26** | Approved under rule 6's controls (opaque key, owner binding, sliding TTL, no id in keys/logs). The Redis hardening that was its recommended precondition shipped with it (**D3b**, PR #14): no host publish, `requirepass`, scoped credential, gateway-side fail-closed guard. Residual: no TLS, one shared credential, no read audit trail. |

## Enforcement

- PR checklist: "No new `log.*` call includes a request/response body or an
  external identifier."
- Candidate CI check (not yet implemented): fail if `model_dump_json` appears
  inside a `log.` call.
