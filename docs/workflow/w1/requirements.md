# W1 Requirements

> Status: AGREED 2026-08-06
> Source: engagement owner ask, 2026-08-06

## 1. Raw ask (verbatim)

> W1: CLIENT MESSAGE
> Hi, and welcome to Riverbend! So glad to finally have an engineer who actually gets this AI stuff. Two quick wins to start: our front desk keeps saying the registration page 'spins' for ages, and honestly the board has been on me to do *something* with AI — could you stand up a little assistant that drafts a patient-friendly version of our intake instructions? I've zipped up the whole repo the last contractor left us; the logins are all in there so you can just run it. We're fully HIPAA compliant already, so don't worry about that side — just get something on the screen this week. Thanks!
> — Dr. Maya Okonkwo, COO — Riverbend Community Health
>
> WHAT THEY HANDED OVER
> The repo itself — 2463-FDE/riverbend-portal (clone it and run). At the root: a tracked .env containing DB_PASSWORD= and PAYER_API_KEY=. The .gitignore lists node_modules/ and *.pyc — but not .env.
> Log file logs/intake-service.log, representative line: INFO 09:14:02 POST /intake body={"name":"Maria Gonzalez","dob":"1971-03-02","ssn":"412-55-9981","insurance_id":"BCBS4471"} — one per POST.
> Schema dump db/schema.sql: patients(id, mrn, name, dob, ssn, address, notes, created_at) — ssn and notes are plain TEXT; no tokenized or encrypted columns (ADR 0002 deliberately skips column-level encryption).
> README.md, first line: "All PHI is encrypted and the system is fully HIPAA compliant."
> Front-desk Jira ticket RIV-088: "Registration spins ~4–5s after Save before it confirms."
> One-paragraph architecture note: a set of FastAPI services (intake, eligibility, records, scheduling, interop, ROI) behind a gateway → Postgres. No AI in the system yet — the board's 'AI assistant' is greenfield, which is exactly your week-1 build.
>
> 🔍 QUESTIONS TO DIG INTO
> What exact fields get written to intake-service.log on every request — and who can read that log file?
> Does the README's "PHI is encrypted" claim match what you actually see in schema.sql?
> If this repo (or its .env) leaked tomorrow, what would an attacker immediately hold?
> Before building the AI assistant, what does a production LLM call need that a quick demo skips — timeouts, retries, cost limits, and what's safe to log?
>
> CURRENT PROBLEMS (STATED / KNOWN)
> The registration page feels slow.
> The board wants an AI feature — nothing exists yet.
>
> THIS WEEK'S DELIVERABLE
> Production LLM client wrapper (timeout, retry w/ backoff, structured-output parsing, token/cost guard) + a PHI-safe logging policy (no request bodies; redaction helper) + a 1-page onboarding seam map + a debt-log entry naming D1/D9/D3 in business-risk terms. Not 'build the AI feature' — the safe client + the finding.

## 2. Context

- **This run is a backfill of record** (owner decision, 2026-08-06). Every named deliverable
  already exists on `main`: `services/ai-assistant/llm_client.py` (typed errors, the
  CLAUDE.md §4 quality reference), `docs/phi-logging-policy.md` (rules + violation register),
  `docs/onboarding-seam-map.md`, and `docs/debt-log.md` primary entries. Once this document
  is agreed, the existing artifacts are verified against it; any gap is a finding, not a
  rebuild trigger.
- **The brief's D9/D3 do not exist.** `docs/debt-log.md:6-10` is the canonical mapping: the
  real seeded markers are D1, D4, D5(x2), D6, D8, D11, D12. Client communications cite the
  canonical IDs and RIV tickets.
- **The findings the ask points at are registered:** PHI in `logs/intake-service.log` is D1
  (code fixed 2026-07-05; git-history remediation still open, human-run runbook in
  `docs/debt-log.md`). The registration "spin" (RIV-088) is D4 (partly closed, ADR 0010).
  The README compliance claim is knowingly false (`CLAUDE.md` §1, TODO-12, human-gated).
  Tracked `.env` secrets fall under the same history-purge runbook.
- **UI expectation:** the ask says "get something on the screen this week"; the deliverable
  paragraph cuts the feature but the owner ruled (2026-08-06) that a minimal visible surface
  is in scope — W1-REQ-9. TODO-44 (`docs/todo.md:67`) is the standing lesson behind making
  this explicit. Historically a surface exists at `frontend/app/intake/page.tsx:141`
  (`/ai/intake-instructions`), which backfill verification checks against.
- **Approval-gated zones nearby** (`docs/landmines.md` §1): secrets/`.env`, PHI logging
  paths, migrations. Logging/redaction work carries the §3 negative-test rule.

## 3. Requirements

| ID | Requirement | Notes |
|----|-------------|-------|
| W1-REQ-1 | System: every outbound LLM call completes or fails within a bounded time — no call can hang a worker indefinitely | timeout |
| W1-REQ-2 | System: transient LLM failures are retried within a bounded budget with backoff; non-transient failures are not retried | retry w/ backoff |
| W1-REQ-3 | System: LLM responses are parsed into a validated structure; an unparseable response yields a typed, deterministic failure — never a crash or silent garbage | structured-output parsing |
| W1-REQ-4 | System: per-call token spend is capped and enforced before/after the call so cost cannot run away | token/cost guard |
| W1-REQ-5 | System: no request or response body containing PHI is ever written to any log by the LLM path | ⚠ human-gate (PHI logging path); `docs/landmines.md` §3 negative tests required |
| W1-REQ-6 | Engineering org: a written PHI-safe logging policy exists stating what is loggable, banning request bodies, and providing a reusable redaction/allowlist mechanism | ⚠ human-gate; today `docs/phi-logging-policy.md` |
| W1-REQ-7 | Engineering org: a one-page onboarding seam map names the safe extension points and the do-not-touch load-bearing walls | today `docs/onboarding-seam-map.md` |
| W1-REQ-8 | Engagement owner: receives a debt-log entry stating the week-1 findings in business-risk terms, with the brief's D1/D9/D3 mapped to canonical IDs; the "repo/.env leaked tomorrow" exposure is covered by the entries' business-risk prose | today `docs/debt-log.md` D1/D1b/D4 + numbering note (owner: existing prose suffices, no new artifact) |
| W1-REQ-9 | Patient/front desk: a minimal visible portal surface exists where the AI-drafted patient-friendly intake instructions can be seen | owner ruled in scope 2026-08-06; ⚠ human-gate adjacency — `/ai/*` is the only vendor-egress path (D13/D14 open) |

## 4. Assumptions

- The README's "fully HIPAA compliant" claim is scenario fiction and confers nothing; no
  requirement inherits it (`CLAUDE.md` §1).
- "D1/D9/D3" is client-brief misnumbering; the debt-log header mapping controls and the
  requirements doc does not mint new D-numbers.
- The registration slowness (RIV-088/D4) is a *finding to register*, not a fix this week —
  the deliverable paragraph names only the client, policy, map, and debt entry.
- Remediation of the tracked `.env` / PHI-bearing git history stays inside the existing
  human-run runbook and is not pulled into W1 scope.

## 6. Out of scope

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
