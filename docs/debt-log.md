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
- **Status:** **code fixed 2026-07-05**; **tip-of-tree hygiene fixed
  2026-07-06; history remediation still open** — `*.log` added to `.gitignore`
  and `logs/intake-service.log` untracked (`git rm --cached`), so no new PHI
  enters the tree. Bodies now redacted via `redaction.safe_log_payload`.
  The repository remains contaminated until history is rewritten: the
  plaintext PHI is still recoverable from **git history** (and from PR
  diffs/CI artifacts that displayed it) — untracking does not remove it.
  See the **Remediation runbook** below for the owned, ordered purge plan.
  Also open: fix remaining log sites
  (see `docs/phi-logging-policy.md` §violations).

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

## Remediation runbook — PHI + secret history purge (human-run, irreversible)

> Covers the two history-contamination items: the PHI in the tracked
> `logs/intake-service.log` blob (D1) and the credentials in the tracked
> `.env` (cross-cutting table below). These steps are **irreversible** and
> touch every clone, so they are run by named humans in this exact order —
> not by tooling or AI agents. An item is "done" only when its verification
> criterion passes.

| # | Step | Owner | Ticket | Definition of done |
|---|------|-------|--------|--------------------|
| 1 | **Rotate every secret in `.env`** (`SESSION_SECRET`, `DB_PASSWORD`, `PAYER_API_KEY`, HL7 feed credentials) and any `ANTHROPIC_API_KEY` ever placed in a tracked file. Rotate **before** the scrub — history rewrite doesn't help while the old values still work. | Riverbend IT/ops lead | to file (RIV, "rotate committed credentials") | Old values rejected by each downstream (payer sandbox call fails with old key; old `SESSION_SECRET` no longer validates a session). |
| 2 | **Scrub git history** of `logs/intake-service.log` and `.env` (`git filter-repo` or BFG), incl. GitHub PR diffs/CI artifacts that displayed the PHI (contact GitHub support for cached views if needed). | Riverbend IT/ops lead, paired with FDE (A. Dhanoa) for verification | to file (RIV, "purge PHI/secrets from git history") | `git log --all -- logs/intake-service.log .env` empty; `git rev-list --all \| xargs git grep <known SSN fragment>` finds nothing. |
| 3 | **Force-push rewritten history + coordinate clones.** Announce a freeze, force-push all branches, have every collaborator delete and re-clone (not pull). Rebase/re-point open PRs. | Riverbend IT/ops lead | same ticket as step 2 | All active collaborators confirm re-clone; no fork/clone with pre-scrub history remains in org control. |
| 4 | **Verify secret scan clean** — run a secret scanner (e.g. gitleaks/trufflehog) across full rewritten history; add it to CI so regression is caught (CI currently has no secret scanning). | FDE (A. Dhanoa) | to file (RIV, "add secret scanning to CI") | Scanner reports zero findings on full history; CI job green on main. |
| 5 | **Document the exposure window** — first-commit date of each contaminated blob → scrub date; enumerate known clones/forks/CI caches in that window; hand to the privacy officer for breach assessment (45 CFR 164.400+ notification duties). | Riverbend privacy/compliance officer, input from FDE | to file (RIV, "PHI exposure breach assessment") | Written assessment on file stating exposure window, audience, and notify/no-notify determination. |

Until steps 1–3 complete, treat the repository and all clones as containing
live PHI and credentials.

## Follow-up tickets to file (docs corrections)

- **README false HIPAA/encryption claims — docs correction required.**
  `README.md:1,82` assert PHI is encrypted and the system is fully HIPAA
  compliant; the schema stores PHI as plaintext `TEXT` (see cross-cutting
  table below). Deliberately scoped out of this PR (README is client-facing
  handoff material); filed here as an explicit follow-up: correct the README
  to match `ARCHITECTURE.md §7`, or implement column-level encryption to make
  the claim true. Owner: FDE (A. Dhanoa), needs client sign-off on wording.
  Ticket: to file (RIV, "correct README compliance claims").

## Cross-cutting (no D-number)

| Item | Business risk | Status |
|------|---------------|--------|
| `.env` committed with secrets | Tracked `.env` holds live credentials: `SESSION_SECRET` (forge any session → full portal access, since sessions never expire + single role), `DB_PASSWORD`, `PAYER_API_KEY`, HL7 feed endpoint. A repo leak hands all of these over with **no cracking required**. The secrets are in **git history**, so deleting the file is insufficient — history rewrite **and** rotation of every credential are required. | OPEN — see **Remediation runbook** above (steps 1–4) |
| README claims "PHI is encrypted / fully HIPAA compliant" — contradicts reality | `README.md:1,82` assert all PHI is encrypted and the system is fully HIPAA compliant. `db/schema.sql` stores `ssn`, `notes`, `dob`, `address`, etc. as plaintext `TEXT`; the only encryption is disk/volume-level (`ARCHITECTURE.md:76`), which protects a stolen disk and nothing else (DB dump, SQL injection, compromised app, committed logs all see cleartext). The overstatement is itself compliance risk — a documented false assurance. `ARCHITECTURE.md §7` is the honest account. Fix: correct the README to match `ARCHITECTURE.md`, or implement column-level encryption to make the claim true. | OPEN — filed under **Follow-up tickets** above |
| Seeded demo password reuse | All seeded accounts share `portal123` (`db/seed/generate_seed.py`); hashing scheme (pbkdf2_sha256, 260k iters) fully disclosed. If any non-dev environment reused the seed, these are live valid logins on repo leak. | OPEN |
| Sessions never expire, single role, no MFA | Any leaked cookie is a permanent all-access credential | OPEN (approval-gated) |
| No secret/dependency/image scanning in CI | Vulnerable deps and committed secrets ship silently | OPEN |
