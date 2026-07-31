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
| `.env` committed with secrets | Tracked `.env` holds live credentials: `SESSION_SECRET` (forge any session → full portal access, since sessions never expire + single role), `DB_PASSWORD`, `PAYER_API_KEY`, HL7 feed endpoint. A repo leak hands all of these over with **no cracking required**. The secrets are in **git history**, so deleting the file is insufficient — history rewrite **and** rotation of every credential are required. | OPEN — see **Remediation runbook** above (steps 1–4) |
| README claims "PHI is encrypted / fully HIPAA compliant" — contradicts reality | `README.md:1,82` assert all PHI is encrypted and the system is fully HIPAA compliant. `db/schema.sql` stores `ssn`, `notes`, `dob`, `address`, etc. as plaintext `TEXT`; the only encryption is disk/volume-level (`ARCHITECTURE.md:76`), which protects a stolen disk and nothing else (DB dump, SQL injection, compromised app, committed logs all see cleartext). The overstatement is itself compliance risk — a documented false assurance. `ARCHITECTURE.md §7` is the honest account. Fix: correct the README to match `ARCHITECTURE.md`, or implement column-level encryption to make the claim true. | OPEN — filed under **Follow-up tickets** above |
| Seeded demo password reuse | All seeded accounts share `portal123` (`db/seed/generate_seed.py`); hashing scheme (pbkdf2_sha256, 260k iters) fully disclosed. If any non-dev environment reused the seed, these are live valid logins on repo leak. | OPEN |
| Sessions never expire, single role, no MFA | Any leaked cookie is a permanent all-access credential | OPEN (approval-gated). Partially mitigated for the rebuilt portal only, at G2: `FE-R28` logs an idle operator off after 10 min via the existing `POST /logout`, which does destroy the Redis session. **The debt is not closed** — `create_session` still sets no TTL, so a session abandoned by closing the browser is never invalidated and a captured token stays valid forever. Only a gateway-side TTL closes it (W9/G4). ADR 0014 gap #1 |
| Session token in browser `localStorage` (portal) | `frontend/app/lib/session.ts:29-30` stores the bearer token — and the `PortalUser` incl. role — in `localStorage`, so any XSS on the origin exfiltrates a credential that never expires and, via D11, reads every chart in the network. It also persists in plaintext in the browser profile across reboot on shared front-desk workstations. This is the pattern OWASP's Authentication Cheat Sheet and SMART on FHIR browser-app guidance both name explicitly as the thing not to do; automatic logoff (45 CFR 164.312(a)(2)(iii), *addressable*) is absent entirely. Inherited from the handoff | OPEN on `main` — the legacy portal is deliberately not patched (spec §8 #1). Closed for the rebuilt portal at G2 by `FE-R27` (token held BFF-side behind an `httpOnly` cookie, unreadable by page script) + `FE-R28`. ADR 0014 |
| No secret/dependency/image scanning in CI | Vulnerable deps and committed secrets ship silently | OPEN |
| Intake payload contract break — registration is non-functional and reports success | See **Intake contract break** below | OPEN — fix folded into the frontend rebuild P2 (spec `FE-R1`–`FE-R3`, `FE-R21`, `FE-R22`), lands at G2 |

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
mismatch lives only in the space between them. `FE-R3` (one intake payload fixture asserted by
both a pytest test and a JS test, both in CI) is the artifact that makes this *class* impossible;
this bug, not a synthetic one, is the harness's first regression test.

**The four layers — the reason it presents as success.** Reading only the last layer misdiagnoses
this as a UI bug:

1. `intake-service` returns **422** on payload shape (table below).
2. Gateway `proxy_intake` (`services/gateway/app.py:211`) uses the error-swallowing `_post` and
   relays the 422 body at **HTTP 200**. Moving it to `_post_checked` is the open half of **D4**
   and is CLAUDE.md §6 approval-gated — deliberately **not** in the P2 fix.
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
to a **documented PHI control** and carries `FE-R22`'s re-proof obligation. `policy_holder` is
undecided (spec §8 #14).

**Not restated here:** the requirements and their verification are `FE-R1`, `FE-R2`, `FE-R3`,
`FE-R15`, `FE-R16`, `FE-R21`, `FE-R22` in `docs/specs/frontend-rebuild.md`; the enum analysis is
its §8.1. Read those, not a copy.
