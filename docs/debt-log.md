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
  enters the tree. Bodies are never logged: intake emits an allowlisted
  non-PHI projection via `schemas.log_metadata` (schemas.py:69–92); the
  interim `redaction.safe_log_payload` still exists (redaction.py:68) but was
  superseded 2026-07-08 (`docs/phi-logging-policy.md` register).
  The repository remains contaminated until history is rewritten: the
  plaintext PHI is still recoverable from **git history** (and from PR
  diffs/CI artifacts that displayed it) — untracking does not remove it.
  See the **Remediation runbook** below for the owned, ordered purge plan.
  Also open: fix remaining log sites
  (see `docs/phi-logging-policy.md` §violations), and **D1b** below.

### D1b — member_id in uvicorn access logs (same class as D1, different layer)
- **Location:** `services/eligibility-service/` (uvicorn default access log);
  the caller is `services/intake-service/app.py::_query_eligibility`
- **What:** `/eligibility` takes the member id as a **query parameter**, so
  uvicorn's default access log records it on every call:
  `INFO: 172.29.0.13:39898 - "GET /eligibility?insurance_id=BCBS4471 HTTP/1.1" 200 OK`.
  Found by the live PHI scan while verifying PR #11 (adversarial review r5).
  **Pre-existing on `main`** — neither the query-param contract nor the access
  log is introduced by that PR.
- **Business risk:** an external payer member id is a PHI-adjacent identifier,
  and `docs/phi-logging-policy.md` rule 3 exists specifically to keep it out of
  logs. The application log paths were hardened for exactly this (typed payer
  exceptions, class-only logging, no `str(e)`); the access log then prints the
  id anyway on every request, into the same container output that ships to any
  log aggregator. Same reportable-breach exposure as D1, one layer down.
- **Ticket:** — (to file)
- **Status:** OPEN, deliberately not fixed inside PR #11 (out of that PR's
  scope). Two candidate fixes, both needing a decision: move the member id out
  of the URL (`GET ?insurance_id=` → `POST` with a body — an **API contract
  change**, and intake is the only caller today), or disable/filter uvicorn's
  access log for this service (cheaper, but loses request-level observability
  and does not help any other service that ever takes an id in a URL). Prefer
  the contract change; audit the other services for id-in-URL routes at the
  same time.

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
- **Status:** PARTLY CLOSED (ADR 0010). The payer call is now bounded — a
  `(connect, read)` timeout, a small retry budget (timeout/connection/5xx only,
  never a 4xx), and an in-process circuit breaker in
  `eligibility-service/check.py` + `breaker.py`. intake's call to eligibility is
  timeout-capped, guarded by its **own** in-process breaker
  (`intake-service/breaker.py`: after 3 consecutive unusable answers,
  verification is skipped with no outbound call and returns status `pending`
  until a 30s reset window elapses). "Unusable" covers a timeout, transport
  error, 5xx, or unparseable body, **and** any answer that held the worker too
  long — a degraded HTTP 200 (`status: unknown`) past
  `ELIGIBILITY_DEGRADED_SLOW_SECONDS` (adversarial review r5), or a real
  `active`/`inactive` verdict past `ELIGIBILITY_SLOW_ANSWER_SECONDS` (2s, = the
  payer read timeout, i.e. the cheapest answer that needed a retry — adversarial
  review r6). Latency counts on its own because the breaker bounds *worker-hold*,
  not answer quality: the verdict is still returned to the front desk, and the
  circuit still opens. Excluding either case left the breaker closed during the
  exact outages it guards — a payer that hangs (r5) and a payer that degrades but
  keeps answering after a retry (r6). A **4xx** does not count *as a fault* — that
  is eligibility rejecting *our* request (e.g. a 422 on a blank member_id), and the
  breaker is shared by every patient, so a run of bad rows must not strip
  verification from everyone else — but a slow 4xx still counts on cost.
  The seeded `time.sleep(4.2)` was
  removed. A payer that stops answering therefore **slows** registration by at
  most `ELIGIBILITY_TIMEOUT_SECONDS` (~0 once either circuit is open) instead of
  freezing it indefinitely — RIV-088's spin is capped and RIV-141's freeze is
  bounded.
  **RIV-141 is not fully closed:** verification still runs on the `/intake`
  request thread, and per-worker breaker state means up to `workers × 3` slow
  calls can still land at the start of an outage. RIV-088's partial-outage form —
  a payer that degrades but keeps *answering* (~4–6s per call) — **is** now
  bounded (review r6: that latency opens intake's circuit, so the cost is ~one
  payer budget per 30s reset window instead of per save), at the price of
  reporting `pending` instead of a verdict for the rest of the window. The
  register-first follow-up is what removes that price; see ADR 0010's honest
  limits.
  A cross-service **PHI leak** found on the same path was
  also closed: `eligibility-service/app.py` no longer logs/returns `str(e)`
  (the payer request URL embeds `member_id`). **Remaining (follow-up):** full
  register-first / out-of-band re-verification (instant 201 + async verify),
  and moving the gateway `proxy_intake` path off the legacy error-swallowing
  `_post` onto `_post_checked`.
- **Three residuals measured 2026-08-07** (W3 backfill verification against
  `docs/workflow/w3/spec.md`; none is new breakage, and none is scheduled):
  1. **"Bounded" means each network phase, not total wall time.** The timeouts
     cap connect and read separately — `requests`' read timeout is the gap
     between bytes and its connect timeout does not cover `getaddrinfo` — so a
     payer trickling bytes or a hanging resolver can exceed the ~6s design
     budget while every individual phase stays inside its bound. Classification
     stays correct (a slow payer lands on the slow side); the number is a design
     budget, not a hard ceiling. Self-documented at
     `adr/0010-eligibility-resilience.md:246-251`; recorded here because D4's
     status above otherwise reads as a total-time guarantee.
  2. **An unexpected exception in verification still fails the registration,
     after the patient row is committed.** `_verify_eligibility`
     (`services/intake-service/app.py:205-213`) wraps its call in `try/finally`
     with no `except`, so anything the shaping helper does not catch propagates
     out of `POST /intake` as a 500 — and `create_intake` commits the patient
     (`:96`) and the coverage row (`:98`) *before* calling it at `:109` and
     records consents at `:111` *after*. The failure window therefore leaves a
     patient with no consent rows and a 500 at the desk. The `try/finally` is
     deliberate and test-pinned for what it does guarantee — the breaker always
     settles, `tests/test_intake_breaker.py:469` — so this is reported, not
     fixed; closing it means deciding what `POST /intake` owes a caller when a
     non-eligibility fault lands mid-sequence, which is register-first's
     territory.
  3. **The verdict is never persisted.** `_create_coverage` writes
     `payer_name`/`member_id`/`group_number`/`plan_type` only, so
     `insurance_coverages.status` keeps its schema default `'unknown'`
     (`db/schema.sql:53`) and `verified_at` stays NULL for every registration,
     whatever the payer returned. The verdict exists only as a field in the
     `POST /intake` response (`schemas.IntakeResponse.eligibility`), which no
     front-desk surface renders (see TODO-56). Noted in
     `adr/0010-eligibility-resilience.md:153-157`; the consequence worth having
     here is that no stored record distinguishes "verified active" from "never
     checked", so nothing can be reported on or re-verified from the database.

### D3b — Redis holds PHI-adjacent state on an unauthenticated, host-published instance
- **Location:** `docker-compose.yml` `redis:` service (`ports: 6379:6379`, no
  `requirepass`, no named volume); consumers are `services/gateway/security.py`
  (sessions, ADR-0007 counters/cache) and — proposed — visit memory (ADR 0011).
- **What:** Redis is reachable from the Docker host on 6379 with **no
  authentication**, and nothing in the topology restricts it to the compose
  network. Today it holds session tokens (username + role). ADR 0011's
  visit-scoped memory would add a payer **member/insurance id** plus a
  structured coverage verdict — PHI-adjacent state at rest, in the D3
  (plaintext-PHI-at-rest) family, in a store that any process on the host can
  read or flush. Surfaced while designing ADR 0011, not introduced by it.
- **Business risk:** an unauthenticated Redis is a credential-free path to live
  session tokens (session hijack, and sessions never expire — D10) and, once
  visit memory ships, to member ids. Reading it leaves no application audit
  trail, so an exposure would be hard to scope for a breach assessment
  (45 CFR 164.400+). Default RDB snapshots also write that state to the
  container filesystem unencrypted.
- **Ticket:** — (to file)
- **Status:** **MOSTLY CLOSED (2026-07-27, PR #14 round 1).** The 2026-07-26
  decision was to land the hardening separately from ADR 0011; the adversarial
  review named the unauthenticated store the shipping blocker and the engagement
  lead reversed that call, so the precondition shipped with the feature. What
  landed:
  - `docker-compose.yml`: the `6379:6379` host publish is gone (`expose` only),
    so the store is reachable only on the compose network;
  - Redis starts with `--requirepass` and **refuses to boot** on an empty
    password (guard inside the container command — a `${REDIS_PASSWORD:?}`
    interpolation would fail `docker compose build` in CI, which seeds env files
    from deliberately empty templates), and its healthcheck authenticates;
  - the credential lives in a **scoped `.env.redis`** loaded by redis + gateway
    only — the `.env.ai-proxy` containment pattern, because the shared `.env`
    goes to every container — and `make up` generates a random one per machine;
  - `services/gateway/security.py::_redis()` **refuses to connect** when no
    credential (or a known placeholder) is configured, so a deploy whose
    topology is not ours cannot put sessions or a member id on an open store;
  - guarded by `tests/test_compose_topology.py` (no host port, requirepass,
    empty-password refusal, authenticated healthcheck, credential scoping, empty
    template, CI seeds every env_file) and `tests/test_gateway_redis_auth.py`
    (placeholder/whitespace/URL-embedded credentials, no cached client after a
    refusal, session + visit-memory writes cannot reach an open store).
- **Residual (still open):** no TLS in transit; one shared credential instead of
  per-consumer Redis ACL users; no named volume, so default RDB snapshots stay
  container-local and unencrypted; still no audit trail of reads; and rotation is
  manual (delete `.env.redis`, `make down && make up` — existing sessions drop).
  ADR 0011's own mitigations remain in force: opaque `visit:{uuid4}` keys, a
  1800s sliding TTL, session-owner binding, a **metadata-only turn log** (no
  clerk text is stored at all — the earlier draft said "redacted transcript",
  which was withdrawn because pattern redaction cannot mask a typed patient
  name), and the member id never appearing in a key or a log line.

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

### D15 — every domain service host-published with no auth of its own
- **Location:** `docker-compose.yml` — `ports: 807N:807N` on all six domain
  services (intake 8071, eligibility 8072, records 8073, scheduling 8074,
  interop 8075, roi 8076).
- **What:** no domain service carries any auth dependency (`Depends(get_db)`
  and nothing else); the gateway's `require_session` is the only auth boundary
  in the system. Publishing the ports made every service reachable from the
  Docker host (and, via compose's default `0.0.0.0` bind, the LAN) with **no
  login**: full charts + unscoped search (`records:8073`), ROI fulfillment
  (`roi:8076`), a clinic day of names + MRNs (`scheduling:8074`, the route
  Codex PR #26 r3 flagged), and an unauthenticated PHI **write** via
  `POST /hl7/ingest` (`interop:8075`). Same class as D3b (Redis) and the
  ai-assistant publish (PR #7 r3); surfaced as a class by PR #26 r3/r4, not
  created by it.
- **Business risk:** credential-free PHI reads and writes that bypass the only
  session check, leaving no application audit trail to scope an exposure for a
  breach assessment (45 CFR 164.400+). The write path additionally allows
  fabricated clinical data (allergies, encounters) into charts.
- **Ticket:** — (found via automated review on PR #26, not client-reported)
- **Status:** **CLOSED at the topology layer (2026-08-02, ADR 0016).** All six
  services are `expose`-only; host publishing is a closed allowlist
  (`postgres`, `gateway`, `frontend` — `portal` was removed from the set at the
  PR #31 descope) so a new service cannot publish by default. Guarded by
  `tests/test_compose_topology.py` (per-service
  no-`ports`, allowlist, gateway-URL agreement, compose-wide URL/port
  agreement). Dev access via `docker compose exec` or a gitignored
  `docker-compose.override.yml` (ADR 0016 §4).
- **Residual (still open):** service-to-service calls on the compose network
  remain unauthenticated (a compromised container reaches everything — W9/D8
  territory); Postgres stays published on 5432 with plaintext PHI behind a
  password (ADR 0016 §6); a real HL7 feed will need dedicated authenticated
  ingress before 8075 ever reopens (ADR 0016 §5).
- **Residual sharpened 2026-08-06:** the Postgres carve-out is weaker than ADR
  0016 §6 argues, because the password it rests on is
  `POSTGRES_PASSWORD: ${DB_PASSWORD:-changeme}` (`docker-compose.yml:7`) — a
  default that works, so a stack brought up without a configured `.env` publishes
  the entire PHI corpus on 5432 behind a guessable credential. Redis, hardened in
  the same family (D3b), refuses to boot on an empty or placeholder credential;
  Postgres has no equivalent guard, and `DB_PASSWORD` additionally lives in the
  shared `.env` that every container loads rather than in a scoped file. A read
  taken this way bypasses the gateway session check, the ADR 0017 capability
  layer, and — since nothing writes `audit_logs` (**D2**) — leaves no application
  trace at all. The cheapest partial fix is the D3b placeholder-refusal pattern
  applied to `DB_PASSWORD`; unpublishing 5432 outright is the real one and needs
  its own ADR, since ADR 0016 §6 explicitly kept it for local `psql`.

## Secondary entries

| ID | Location | What / business risk | Ticket | Status |
|----|----------|----------------------|--------|--------|
| D2 | `db/schema.sql:126-137` | "Audit" log is an ordinary mutable table — free-text `actor` with no FK to `users`, raw request body in `message`, a `deleted_at` soft delete, no hash chain, no target patient id, no action verb. **Measured 2026-08-06: nothing in the codebase writes to it.** A repo-wide grep finds only comments and seed rows, and `services/roi-service/app.py:93` notes in-line that no accounting entry is written on the disclosure path. So the table is not merely "logging, not auditing" — it is empty by construction, which means a 45 CFR 164.528 accounting of disclosures cannot be produced at all, and its presence in the schema gives a false impression that one could be. This is the real starting condition for the W10 capstone | — | OPEN |
| D5a | `services/intake-service/app.py:69` | No MPI/match key → duplicate charts per patient; clinical data (e.g. allergies) splits across charts — patient-safety risk | RIV-160 | OPEN |
| D5b | `services/scheduling-service/app.py:98` | Check-then-insert booking race, no UNIQUE on `slot_id`, no idempotency key → double-booked slots, "charged twice" complaints | RIV-175 | OPEN — **note: the seeded markers reuse "D5" for both this and D5a**; disambiguated here as D5a/D5b. **Second, independent path found 2026-08-06:** nothing anywhere writes `Slot.status` (grep finds only the read filter `Slot.status == "open"`, `scheduling-service/app.py:49`), so a confirmed booking leaves its slot `open` forever and `GET /slots` keeps offering it. Two users minutes apart both see it and both book — no race required, so a UNIQUE constraint alone does not close RIV-175. Also note `book.py:23-54` calls `conn.close()` only on the success path, leaking a connection on any exception |
| D6 | `services/interop-service/app.py:7` | HL7 parser maps PID/PV1 only; AL1 (allergies) and RXA (meds) silently dropped — missing allergy data is a patient-safety risk | RIV-160 | OPEN |
| D8 | `services/records-service/app.py:95,145` | N+1 encounter queries + full-table ILIKE search with no index → chart loads degrade with data growth. **Widened 2026-08-06:** `db/schema.sql` contains **zero `CREATE INDEX` statements** — not just the known gap on `records.body`. `records.patient_id`, `records.encounter_id`, `encounters.patient_id`, `appointments.patient_id`, `insurance_coverages.patient_id`, `consents.patient_id` and the `audit_logs` columns are all unindexed, so every FK-shaped lookup on the hot chart-load path is a sequential scan. That, not the N+1 alone, is the mechanism behind the "degrades with growth" symptom, and indexing is the cheaper half of the fix | — | OPEN |
| D11 | `services/records-service/app.py:91` | IDOR: sequential integer `patient_id` served to any logged-in user; sessions not patient-bound — cross-patient chart reads succeed. **Exposure is larger than id-walking (measured 2026-08-06):** `q` is interpolated into the search pattern un-escaped at `records-service/app.py:48` and `:159`, so `GET /records/search?q=%25` (a bare `%` wildcard) matches every row and returns full `Record.body` text for all of them, with no `LIMIT`. One request, whole corpus, no ids required. Escape the LIKE metacharacters and bound the result set; size the D11 fix against this too, per `docs/landmines.md` §1 | — | OPEN (xfail test in suite) |
| D13 | `services/ai-assistant/` (both endpoints); `adr/0004`, `adr/0006`, `adr/0009`, `adr/0011`, `docs/phi-logging-policy.md` | **PHI to a cloud LLM vendor with no BAA.** Riverbend is a covered entity, so any prompt may carry PHI, and the assistant runs against Bedrock on standard SaaS terms — no executed Business Associate Agreement covers it. `/ai/*` is the estate's only vendor-egress path, which is why every AI ADR treats D13 as the constraint it designs around: `/intake-instructions` is safe by construction (closed-vocabulary enums/bools, ADR 0004) and `/visit-chat` never egresses clerk prose (ADR 0011; `tests/test_visit_chat_phi.py:239` asserts the prompt is byte-identical to the deterministic build). So the boundary holds *today by construction*, not by contract — a future feature that interpolates free text into a prompt breaches it with no gate to stop it. `adr/0009-ai-assistant-bedrock-provider.md:21-33` names the closing mechanism: Bedrock is HIPAA-eligible under an executed AWS BAA with a BAA-covered region/model, so routing under BAA closes this rather than widening it. **Row added 2026-08-07** (W3 backfill): D13 gated a whole path and was cited in five ADRs, a policy doc and two code comments while having no entry in this register | — | OPEN — precondition for any real-PHI traffic; scenario-scheduled for W8 |
| D14 | no code site on `main` — defined in `docs/specs-deprecated/w8.md:7,20,48` (archive), referenced by `adr/0009-ai-assistant-bedrock-provider.md:158` | **Fake de-identification.** The scenario's "de-identified" export strips `name` only, leaving **17 of the 18** Safe-Harbor identifiers (45 CFR 164.514(b)(2)) — DOB, address, phone, email, SSN, MRN — so the output is trivially re-identifiable while being described as anonymized. The business risk is the label, not the data: a payload called de-identified is handled with fewer controls and may be shared outside the covered entity's protections. **Verified 2026-08-07: no such export or scrub path exists on `main`** — `ai-assistant` exposes only `/intake-instructions` and `/visit-chat`, and the `redaction.py` copies are log-scrubbers (SSN/email/phone patterns), not a de-identification path. D14 is therefore a *forward* constraint: it binds whoever builds the export, and ADR 0009:154-161 already records that any future "anonymized" payload must be a real Safe-Harbor or Expert-Determination de-identification, not a one-field strip. **Row added 2026-08-07** (W3 backfill), definition sourced from the deprecated spec archive because that is the only place it was written down | — | OPEN — no implementation to fix; constrains the W8 build |

## Remediation runbook — PHI + secret history purge (human-run, irreversible)

> Covers the two history-contamination items: the PHI in the tracked
> `logs/intake-service.log` blob (D1) and the credentials in the tracked
> `.env` (cross-cutting table below). These steps are **irreversible** and
> touch every clone, so they are run by named humans in this exact order —
> not by tooling or AI agents. An item is "done" only when its verification
> criterion passes.

| # | Step | Owner | Ticket | Definition of done |
|---|------|-------|--------|--------------------|
| 1 | **Rotate every secret in `.env`** — `SESSION_SECRET`, `DB_PASSWORD`, `PAYER_API_KEY`, **`BEDROCK_API_KEY`**, HL7 feed credentials (`HL7_FEED_HOST`) — and any `ANTHROPIC_API_KEY` ever placed in a tracked file. Rotate **before** the scrub — history rewrite doesn't help while the old values still work. ⚠️ **`BEDROCK_API_KEY` was missing from this list until 2026-08-06.** It is present in the historical blob (`git show b9364ca:.env`), so a rotation run against the earlier version of this checklist left it live. Enumerate from the blob itself, not from this row, and re-check the row against `git show b9364ca:.env` before starting. | Riverbend IT/ops lead | to file (RIV, "rotate committed credentials") | Old values rejected by each downstream (payer sandbox call fails with old key; old `SESSION_SECRET` no longer validates a session). Every key present in `git show b9364ca:.env` accounted for. |
| 2 | **Scrub git history** of `logs/intake-service.log` and `.env` (`git filter-repo` or BFG), incl. GitHub PR diffs/CI artifacts that displayed the PHI (contact GitHub support for cached views if needed). | Riverbend IT/ops lead, paired with FDE (A. Dhanoa) for verification | to file (RIV, "purge PHI/secrets from git history") | `git log --all -- logs/intake-service.log .env` empty; `git rev-list --all \| xargs git grep <known SSN fragment>` finds nothing. |
| 3 | **Force-push rewritten history + coordinate clones.** Announce a freeze, force-push all branches, have every collaborator delete and re-clone (not pull). Rebase/re-point open PRs. | Riverbend IT/ops lead | same ticket as step 2 | All active collaborators confirm re-clone; no fork/clone with pre-scrub history remains in org control. |
| 4 | **Verify secret scan clean** — run a secret scanner (e.g. gitleaks/trufflehog) across full rewritten history. CI recurrence guard **DONE** (`8858097`, PR #2): a pinned gitleaks `secret-scan` job fails the build on any secret in the tracked tree, and `docker-build` needs it. Still open: the **full-history** scan, which is only meaningful after the step-2 rewrite. | FDE (A. Dhanoa) | to file (RIV, "add secret scanning to CI") | CI `secret-scan` green on main (**met** — recurrence guard live); scanner reports zero findings on full rewritten history (pending steps 1–3). |
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
| `.env` committed with secrets | Live credentials sit in **git history**: `DB_PASSWORD`, `PAYER_API_KEY`, `BEDROCK_API_KEY`, HL7 feed endpoint, `SESSION_SECRET`. A repo leak hands all of these over with **no cracking required**, and deleting the file is insufficient — history rewrite **and** rotation of every credential are required. Enumerate from `git show b9364ca:.env`, not from this row. **Two corrections 2026-08-08.** (1) `.env` is no longer *tracked* — gitignored since `56645fc`, with CI's gitleaks `secret-scan` job as the recurrence guard; the exposure is historical, not present-tense, which changes nothing about the remediation but does change what a reader looking at a fresh clone will see. (2) The `SESSION_SECRET` blast radius stated here — "forge any session → full portal access" — was **fiction**: nothing in `services/gateway/` reads `SESSION_SECRET` at all (it appears only in `.env.example:75`). Sessions are opaque UUID4 keys in Redis, so there is no signature to forge and the secret is inert. Rotate it anyway under runbook step 1 — an inert name today is a live one the moment someone wires it up — but do not cite it as an access path. The real permanent-credential risk is the never-expiring session row below. | OPEN — see **Remediation runbook** above (steps 1–4) |
| README claims "PHI is encrypted / fully HIPAA compliant" — contradicts reality | `README.md:1,82` assert all PHI is encrypted and the system is fully HIPAA compliant. `db/schema.sql` stores `ssn`, `notes`, `dob`, `address`, etc. as plaintext `TEXT`; the only encryption is disk/volume-level (`ARCHITECTURE.md:76`), which protects a stolen disk and nothing else (DB dump, SQL injection, compromised app, committed logs all see cleartext). The overstatement is itself compliance risk — a documented false assurance. `ARCHITECTURE.md §7` is the honest account. Fix: correct the README to match `ARCHITECTURE.md`, or implement column-level encryption to make the claim true. | OPEN — filed under **Follow-up tickets** above |
| Seeded demo password reuse | All seeded accounts share `portal123` (`db/seed/generate_seed.py`); hashing scheme (pbkdf2_sha256, 260k iters) fully disclosed. If any non-dev environment reused the seed, these are live valid logins on repo leak. **Sharpened 2026-08-06:** the salts are generated, not random — `salt = f"riverbend{i:02d}saltval0"` (`generate_seed.py:97`) — so with the algorithm, the iteration count, the password and the salt all published, the hashes committed in `db/seed/seed.sql:9-20` are not a work factor at all; they are recomputable, i.e. effectively cleartext credentials for twelve named accounts. That includes `itadmin`, whose role is `admin` and therefore holds every capability including `hl7.ingest` (the unauthenticated-PHI-write surface). | OPEN |
| Front desk reads plaintext SSNs (minimum necessary) | `GET /patients/{id}` returns `PatientDetail` whole — `ssn`, `dob`, `address`, `phone`, `email`, `notes` (`records-service/schemas.py:18-32`, `app.py:87`) — and the gateway gates that route on `patients.read` (`gateway/app.py:277`), a capability `front_desk` holds (`config/roles.yaml`, `gateway/authz.py:38-48`). So registration staff can pull the SSN and clinical notes of any patient, while `config/roles.yaml:14` describes that same role as "No chart access (minimum necessary)". The declared policy and the enforced one disagree, and the 45 CFR 164.502(b) minimum-necessary standard is the thing the description was asserting. Two candidate fixes: a narrower response model for the `patients.read` capability, or splitting the capability so chart-bearing fields need `records.read`. Either is an ADR 0017 amendment, not a patch. Found 2026-08-06. | OPEN |
| Sessions never expire, single role, no MFA | Any leaked cookie is a permanent all-access credential | OPEN (approval-gated). The single-role part narrowed by ADR 0017: four real roles + per-route capability enforcement at the gateway — but every pre-RBAC `users` row keeps the full-capability `staff` role, so on an existing database a leaked token is still all-access; TTL and MFA unchanged. The idle-logoff mitigation that ADR 0014 specified is **gone with the frontend rebuild** (descoped 2026-08-05, branch `alt/sveltekit-portal`), so nothing logs an idle operator off anywhere today. `create_session` still sets no TTL: a session abandoned by closing the browser is never invalidated and a captured token stays valid forever. Only a gateway-side TTL closes it — approval-gated under `docs/landmines.md` §1 (auth), unscheduled. ADR 0014 gap #1 |
| Session token in browser `localStorage` (portal) | `frontend/app/lib/session.ts:29-30` stores the bearer token — and the `PortalUser` incl. role — in `localStorage`, so any XSS on the origin exfiltrates a credential that never expires and, via D11, reads every chart in the network. It also persists in plaintext in the browser profile across reboot on shared front-desk workstations. This is the pattern OWASP's Authentication Cheat Sheet and SMART on FHIR browser-app guidance both name explicitly as the thing not to do; automatic logoff (45 CFR 164.312(a)(2)(iii), *addressable*) is absent entirely. Inherited from the handoff | OPEN, and now **unscheduled**. The fix was a rebuilt portal holding the token BFF-side behind an `httpOnly` cookie (ADR 0014); the rebuild is descoped (branch `alt/sveltekit-portal`) and the Next.js portal, which is the only frontend, is deliberately not patched. Retrofitting the cookie into it is real work nobody has costed |
| No dependency/image scanning in CI | Vulnerable deps and base images ship silently | OPEN, **narrowed 2026-08-08** — the secret-scanning half closed with PR #2 (`8858097`): a pinned gitleaks `v8.18.4` job scans the tracked tree on every push and `docker-build` needs it. That guard is tracked-tree only; the full-history scan is remediation-runbook step 4 and stays open. Dependency and image scanning are still absent |
| Intake payload contract break — registration is non-functional and reports success | See **Intake contract break** below | OPEN and **unscheduled** — the fix was folded into the frontend rebuild, which is descoped (2026-08-05). The defect is backend-side and outlived its plan; it needs a home in a curriculum week. Tracked as TODO-1 |

### Intake contract break (no D-number)

> Filed here rather than as a new `D15`: the seeded markers are the client's taxonomy, and D1b is
> the precedent for recording a defect that has no marker of its own.

Patient registration through the portal is **completely non-functional on `main`** and the UI
displays a green "Intake submitted successfully." No patient row is created. Verified by driving
the running stack on 2026-07-28 (browser + curl against `make up`) and re-verified against the
code on 2026-07-30. **Inherited from handoff commit `3663c4b`** — not introduced by PRs #1–#21.

**Business risk.** The clinic's self-service registration path silently loses every patient it
takes in, and the operator is told it worked, so the loss is invisible at the desk and only
surfaces when the patient arrives with no chart. Nothing in the stack alerts on it.

**Why a green build and 730 passing tests missed it.** Nothing asserts the two sides of the
payload against one shared fixture; each side is internally consistent and tested, and the
mismatch lives only in the space between them. The artifact that would make this *class*
impossible is one intake payload fixture asserted by both a pytest test and a JS test, both in CI.
That was scoped as part of the frontend rebuild and is descoped with it (branch
`alt/sveltekit-portal`), and there is no JavaScript test harness in this repository, so **the
class is currently unguarded** — only this instance is known.

**The four layers — the reason it presents as success.** Reading only the last layer misdiagnoses
this as a UI bug:

1. `intake-service` returns **422** on payload shape (table below).
2. Gateway `proxy_intake` (`services/gateway/app.py:211`) uses the error-swallowing `_post` and
   relays the 422 body at **HTTP 200**. Moving it to `_post_checked` is the open half of **D4**
   and is approval-gated under `docs/landmines.md` §1 — deliberately **not** in the P2 fix.
3. The BFF `proxy` (`frontend/app/lib/gateway.ts`) relays status and body verbatim.
4. `frontend/app/intake/page.tsx:108` guards on `!res.ok || data?.error`. A 422 body carries
   `detail`, which is neither → success branch → line 113 finds no `patient_id` → prints the
   fallback string. **That fallback is the failure path.**

| Frontend sends | Service expects | Effect |
|---|---|---|
| `demographics.first_name` + `last_name` | `demographics.name` (required, non-blank) | 422 `Field required` |
| `consents: {treatment, privacy, financial, communications}` (bools) | `consents: list[ConsentKind]` | 422 `Input should be a valid list` |
| `insurance.carrier` | `insurance.payer_name` | extra key silently dropped, no error |
| `insurance.policy_holder` | *no schema field and no DB column* | silently dropped, no error |

**Two things the form collects with nowhere to store them.** `ConsentKind` is a closed
three-value enum (`npp_ack`, `treatment_consent`, `roi_consent`) while the form collects four
consents — financial responsibility and electronic communications have no representation, so
clearing the 422 frontend-side alone would discard a legal financial attestation. Separately,
`insurance.policy_holder` has no column at all (`services/intake-service/models.py`,
`InsuranceCoverage`) yet feeds the AI checklist facts. The consent half is resolved: the enum is
widened by `financial_responsibility_ack` and `communications_opt_in` — no migration
(`consents.kind` is plain `TEXT`, `db/schema.sql:121`, no `CHECK`), but it is a deliberate touch
to a **documented PHI control**, so whichever week ships it re-proves the consent-storage
behaviour rather than assuming the widening is inert.

**`policy_holder` resolved 2026-07-31 (user): the form drops the free-text field** and
collects a "Policy holder is the patient" checkbox instead. The AI checklist consumes only
`policy_holder_is_self`, a boolean derived from the field's emptiness at
`frontend/app/intake/page.tsx:147` — the name string reaches nothing but the Review display — so
the checkbox supplies everything downstream uses. The measurement behind that call is on branch
`alt/sveltekit-portal` (`docs/specs-deprecated/frontend-rebuild.md` §8.1); the decision stands on its own and
is not restated here.

**The debt this leaves, recorded because the fix removes the field rather than storing it:** the
system captures no policy-holder identity at all. If a policy holder who is not the patient must
ever be named — a coordination-of-benefits or billing requirement — it needs a new
`InsuranceCoverage` column plus the hand-synced migration, not just a form field. Until then the
absence is deliberate, not an oversight. The Next.js portal keeps collecting and dropping the
field, and is not patched.

**No requirements own this defect any more.** The `FE-R*` requirements that specified the fix, and
the enum analysis behind it, went to branch `alt/sveltekit-portal` with the frontend rebuild on
2026-08-05. Everything needed to fix it is above — the four layers, the payload table, and the
consent-enum decision. It needs a curriculum week; until it has one, TODO-1 is the only thing
holding it.
