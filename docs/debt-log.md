# Technical Debt Log

> Canonical registry of the seeded debt markers (`D<n>` in code) in
> business-risk terms. Started 2026-07-05. Update statuses as items land.
>
> **Numbering note:** the client's week-1 brief referenced "D1/D9/D3".
> **D9 and D3 do not exist in this repo** — the real seeded markers are
> D1, D4, D5 (twice — see collision note), D6, D8, D11, D12. This log is the
> canonical mapping; client communications should cite these IDs and the
> RIV ticket numbers.

## Primary entries (this week's focus)

### D1 — PHI written to plaintext logs
- **Location:** `services/intake-service/app.py:67` (fixed); `logs/intake-service.log` (git-tracked, historical)
- **What:** the full intake request body — name, DOB, SSN, free-text notes —
  was written at INFO to a file log on every registration.
- **Business risk:** a lost laptop, leaked repo, or log aggregation misconfig
  is a reportable HIPAA breach (45 CFR 164.400+) with OCR notification duties,
  potential fines, and patient-trust damage. Because the log file is tracked
  in git, the exposure extends to every clone of the repository, forever,
  unless history is scrubbed.
- **Ticket:** — (found in handoff docs, not client-reported)
- **Status:** **code fixed 2026-07-05** — bodies now redacted via
  `redaction.safe_log_payload`. OPEN ops items: purge/gitignore the log file;
  decide on git-history scrub; fix remaining sites (see
  `docs/phi-logging-policy.md` §violations).

### D4 — no-timeout inline eligibility call ("spinning registration")
- **Location:** `services/intake-service/app.py` `_verify_eligibility` (inline
  on the request thread, plus a seeded `time.sleep(4.2)`); `services/eligibility-service/check.py`
  (payer call with no `timeout=`, no retry, no circuit breaker).
- **What:** payer eligibility is verified synchronously inside `POST /intake`
  with no time bound anywhere in the chain.
- **Business risk:** this is **RIV-088** (every registration "spins" ~4–5s)
  and **RIV-141** (front desk frozen 20 minutes during a payer outage —
  patients physically waiting, staff idle). Unbounded calls also exhaust
  worker threads, so one slow payer can take down all intake capacity.
- **Ticket:** RIV-088 (Medium), RIV-141 (High)
- **Status:** OPEN. Recommended fix: bounded timeout on the payer call +
  deferred/async verification (register first, verify eligibility out-of-band).
  The new `ai-assistant/llm_client.py` demonstrates the bounded-call pattern.

### D12 — ROI disclosures without authorization
- **Location:** `services/roi-service/app.py:90,104,146,148`
- **What:** release-of-information goes out with no recorded 45 CFR 164.508
  patient authorization and no accounting-of-disclosures trail.
- **Business risk:** every fulfilled request is potentially an impermissible
  disclosure — regulatory exposure per record released, and no audit trail to
  demonstrate compliance during an OCR investigation. **Direct blocker for the
  requested AI feature:** no AI functionality may source patient data through
  this path until authorization enforcement exists.
- **Ticket:** — (documented intentional gap, ARCHITECTURE.md §7)
- **Status:** OPEN. Prerequisite for any AI feature touching patient records.

## Secondary entries

| ID | Location | What / business risk | Ticket | Status |
|----|----------|----------------------|--------|--------|
| D5a | `services/intake-service/app.py:69` | No MPI/match key → duplicate charts per patient; clinical data (e.g. allergies) splits across charts — patient-safety risk | RIV-160 | OPEN |
| D5b | `services/scheduling-service/app.py:98` | Check-then-insert booking race, no UNIQUE on `slot_id`, no idempotency key → double-booked slots, "charged twice" complaints | RIV-175 | OPEN — **note: the seeded markers reuse "D5" for both this and D5a**; disambiguated here as D5a/D5b |
| D6 | `services/interop-service/app.py:7` | HL7 parser maps PID/PV1 only; AL1 (allergies) and RXA (meds) silently dropped — missing allergy data is a patient-safety risk | RIV-160 | OPEN |
| D8 | `services/records-service/app.py:95,145` | N+1 encounter queries + full-table ILIKE search with no index → chart loads degrade with data growth | — | OPEN |
| D11 | `services/records-service/app.py:91` | IDOR: sequential integer `patient_id` served to any logged-in user; sessions not patient-bound — cross-patient chart reads succeed | — | OPEN (xfail test in suite) |

## Cross-cutting (no D-number)

| Item | Business risk | Status |
|------|---------------|--------|
| `.env` committed with secrets | Credential exposure to anyone with repo access; rotation required before production claims | OPEN |
| Sessions never expire, single role, no MFA | Any leaked cookie is a permanent all-access credential | OPEN (approval-gated) |
| No secret/dependency/image scanning in CI | Vulnerable deps and committed secrets ship silently | OPEN |
