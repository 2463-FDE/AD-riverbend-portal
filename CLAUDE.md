# CLAUDE.md

> Brownfield web/backend service. This file is the durable source of truth for working
> in this repo. Conversation history does not persist between sessions — this does.
> Keep it accurate. If you (Claude) discover something here is wrong, flag it and propose a fix.

---

## 0. Read this first

- This is an **existing, production** codebase (Riverbend Community Health patient portal),
  built by an outside contractor (Helix Digital Partners) and handed off **as-is**.
- **HIPAA covered entity.** PHI, auth, disclosures, and audit paths are load-bearing.
  Treat anything touching patient data as high-risk.
- **Understand before changing.** Trace the relevant code path and read existing tests
  before editing anything.
- **Small, reversible changes.** Prefer minimal diffs and frequent commits over rewrites.
- When unsure whether a change is safe, **stop and ask** rather than guessing.
- The handoff docs are unusually honest: many "bugs" are **documented, intentional gaps**
  (see `ARCHITECTURE.md §7`). Do not naively "fix" weirdness without checking §6 below.

---

## 1. What this service is

- **Purpose:** Patient intake + records portal for Riverbend Community Health, a multi-clinic
  community health network. Patients self-register; front-desk verifies insurance eligibility;
  clinicians view charts; schedulers book appointments; ROI clerks process release-of-information.
- **Type:** Monorepo — Next.js frontend + a fleet of FastAPI microservices behind a BFF gateway.
- **Language & runtime:** Python 3.11/3.12 (services), Node 22 + TypeScript (frontend).
- **Framework:** FastAPI (services), Next.js 15 App Router (frontend).
- **Datastore(s):** Postgres 15 (system of record), Redis 7 (sessions + cache).
- **Upstream/downstream dependencies:** payer eligibility clearinghouse (X12 270/271 REST shim),
  hospital HL7 v2 feed (ADT/ORU ingest).

The portal **never** calls a domain service directly — everything goes through the gateway,
which owns login + session validation and fans requests out.

---

## 2. Repository map

```
frontend/              # Next.js 15 portal (port 3070). BFF route handlers proxy to gateway.
  app/                 #   pages: intake, records, appointments, roi, login
  app/lib/gateway.ts   #   server-side call into the gateway
services/
  gateway/             # FastAPI BFF (8070): login, sessions, request fan-out. ⚠️ owns auth
  intake-service/      # (8071) registration, insurance, consent, eligibility trigger
  eligibility-service/ # (8072) payer X12 270/271 (no DB; calls payer)
  records-service/     # (8073) patient + chart read façade
  scheduling-service/  # (8074) slots, booking, cancel
  interop-service/     # (8075) HL7 v2 ingest
  roi-service/         # (8076) release-of-information + disclosures
config/roles.yaml      # RBAC (single "staff" role — see §6)
db/
  schema.sql           # flattened current schema (loads on fresh Postgres volume)
  migrations/00N_*.sql # ordered, forward-only, hand-rolled, kept in sync with schema.sql by hand
  seed/generate_seed.py# deterministic seed generator → seed/seed.sql
adr/                   # 0001 stack, 0002 data/compliance, 0003 auth/sessions
docs/
  runbook.md           # operations + recovery
  handover/            # jira-tickets.md (the client asks), breach policy, auditor Q, payer status, portal.har
tests/                 # pytest; integration tests marked and need live infra
```

- **Entry points:** each service is `app.py` (FastAPI app + routers). Frontend boots via Next.js.
- **Config:** `.env` (⚠️ **committed** — see §6), read by each service's `config.py`.
  Compose injects downstream service URLs as env vars (see `docker-compose.yml`).
- **No shared Python library.** Every service copy-pastes the same layout:
  `config.py` / `db.py` (lazy engine, no connect-on-import) / `models.py` /
  `schemas.py` (Pydantic v2) / `logging_config.py` / `app.py`. (ADR 0001.)

---

## 3. Commands

> Actual working commands (from `Makefile`). Verify before relying on them.

| Task            | Command                                   |
|-----------------|-------------------------------------------|
| Install (dev)   | `pip install -r requirements-dev.txt`     |
| Run stack       | `make up`     (docker compose up -d)       |
| Stop stack      | `make down`                               |
| Logs / status   | `make logs` / `make ps`                   |
| Build images    | `make build`                              |
| Seed db         | `make seed`     (reload schema + demo data into running db) |
| Regenerate seed | `make seed-gen` (deterministic → seed.sql) |
| psql shell      | `make psql`                               |
| Run unit tests  | `make test`  or  `pytest -m "not integration" -q` |
| Run integration | `pytest -m integration`   (needs `make up`) |
| Run one test    | `pytest tests/test_hl7_parser.py -q`      |
| Frontend dev    | `make frontend-dev`  (npm install + npm run dev) |
| Validate compose| `make config`                             |

- **Setup:** `cp .env.example .env` then `make up`. Postgres seeds on first boot from
  `db/schema.sql` + `db/seed/seed.sql` (mounted into the container).
- **Demo logins** (all password `portal123`): `frontdesk`, `drnguyen`, `roiclerk`,
  `mokonkwo`, … (see `db/seed/generate_seed.py`).
- **Ports:** portal 3070, gateway 8070 (`/docs`), services 8071–8076, Postgres 5432, Redis 6379.
- **No lint / typecheck / format target exists yet.** CI runs: frontend `npm run build`,
  a per-service `python -c "import app"` import smoke test, and `pytest -m "not integration"`.

---

## 4. How things actually work (vs. how they should)

- **Layering in practice:** portal → gateway (`_get`/`_post` httpx proxies, 30s timeout) →
  domain service → Postgres. Gateway `require_session` only checks "is logged in."
- **Auth reality:** `users` table holds PBKDF2-SHA256 hashes. Login stores `session:<token>`
  in Redis (username, role). **No TTL — sessions never expire.** Single `staff` role for
  everyone; no per-action authz; MFA off (`config/roles.yaml`, gateway `auth.yaml`).
- **Migrations are hand-synced** to `schema.sql` — there is no migration runner; on a fresh
  volume only `schema.sql` runs. Keep both in sync by hand if you touch the schema.
- **Patterns to imitate:** the service module layout (`config/db/models/schemas/app`) is
  consistent across services — match it exactly when adding code.
- **Patterns NOT to imitate:** proxy helpers swallow errors into `{"error": str(e)}` (200 OK
  with an error body); intake logs full request bodies (PHI) at INFO. Don't copy these.

---

## 5. Testing strategy

- **Where:** `tests/`. Framework: **pytest** (`pytest.ini`; `integration` marker).
- **Module loading:** no shared package, so unit tests load the target by file path
  (`tests/conftest.py::load_module`).
- **Covered:** password hash roundtrip, HL7 PID/PV1 happy path, eligibility response shaping,
  intake schema validation, one integration login→auth→chart-read flow.
- **Deliberate gaps (mirror real defects — do NOT "fix" the tests to hide them):**
  scheduling race / double-booking untested; IDOR prevention is an `xfail` (cross-patient
  reads currently succeed); HL7 allergy/med extraction `xfail` (AL1/RXA dropped);
  no ROI authorization tests; no input-normalization / dup-patient tests. (RIV-201.)
- **Brownfield rule:** before refactoring untested code, write **characterization tests**
  capturing current behavior first, then change under green.
- **Negative-test rule for PHI/security code (RIV, PR #2 lesson):** any redaction,
  authz, or sanitization function needs at least one **adversarial** test — the input
  placed where the code does *not* expect it (PHI in a non-PHI key, an SSN inside a
  free-text/list field, a request that skips the happy path). Happy-path tests confirm
  intended behavior; they do not prove the safety boundary holds. The `consents` PHI
  leak shipped green because every redaction test asserted the *intended* shape and none
  planted PHI in the wrong place. For anything that writes a payload to a log, add an
  **end-to-end scan test**: feed PHI into every field (incl. non-PHI keys + list items),
  call the real log-formatting path, assert no raw PHI survives (see
  `tests/test_redaction.py::test_safe_log_payload_masks_phi_in_every_field`).
- **Run `/security-review` (or a local adversarial pass) on the diff before opening a PR**
  touching auth/PHI/ROI — the adversarial bot caught both PR #2 leaks *after* push; pull
  that net earlier.

---

## 6. Landmines and do-not-touch zones

> Most valuable section. Read before editing anything risky. Sourced from `ARCHITECTURE.md §7`.

- ⚠️ **Auth / sessions** (`services/gateway/`, `security.py`, `auth.yaml`) — sessions never
  expire, single role, no MFA. **Never change auth behavior without explicit human approval.**
- ⚠️ **IDOR on chart reads** — `GET /patients/{id}/records` requires a session but never binds
  it to `{patient_id}`; IDs are sequential and walkable. Intentional gap, documented in code.
- ⚠️ **ROI has no authorization enforcement** — disclosures go out with no recorded
  45 CFR 164.508 authorization and no accounting trail. Touches PHI + compliance.
- ⚠️ **PHI handling** — `ssn`, `notes` etc. stored as plaintext `TEXT`; intake logs full
  bodies at INFO. Compliance posture is self-asserted (ADR 0002). Anything here is regulated.
- ⚠️ **Inline eligibility call** (`intake` → `eligibility`) is synchronous with no timeout on
  the request path; a payer outage freezes intake (RIV-088 / RIV-141).
- ⚠️ **Booking race** (`scheduling-service/book.py`) — check-then-insert, no UNIQUE on
  `slot_id`, no idempotency key → double-booking (RIV-175).
- ⚠️ **Duplicate patients** — self-service intake has no MPI/match key (RIV-160).
- ⚠️ **Brittle HL7 mapping** — only PID/PV1 mapped; AL1 (allergies) and RXA (meds) silently
  dropped (RIV-160).
- ⚠️ **Secrets committed** — `.env` is tracked; no secret/vuln/image scan in CI. Do not add
  more secrets; flag before rotating.
- ⚠️ **Schema/migrations** — `schema.sql` and `migrations/*.sql` are hand-synced; a mismatch
  breaks fresh-volume boots vs. existing dbs.
- **Never edit without explicit human approval:** auth, PHI columns, ROI/disclosure logic,
  migrations, `.env`/secrets.

---

## 7. Safety rules for changes

- Make the **smallest change that solves the problem.** Do not refactor unrelated code.
- **Do not** modify public API contracts, DB schema, or config defaults without flagging first.
- **Do not** delete code that looks unused — confirm via call-site search (routes are wired in
  `app.py`; frontend calls via `app/lib/gateway.ts`) before removal.
- Prefer **feature flags / additive changes** over modifying existing behavior in place.
- If you touch the schema, update **both** `db/schema.sql` and a new `db/migrations/00N_*.sql`.
- After changes run the §3 checks (unit tests + relevant service import smoke) and report results.

---

## 8. Glossary / domain terms

- **BFF** — backend-for-frontend; the gateway. Portal talks only to it.
- **ROI** — Release of Information; fulfilling requests to disclose a patient's records.
- **Eligibility 270/271** — X12 EDI transaction pair: 270 = coverage inquiry, 271 = response.
- **HL7 v2 / ADT / ORU** — hospital messaging; ADT = admit/discharge/transfer, ORU = results.
  **PID** = patient ID segment, **PV1** = visit, **AL1** = allergy, **RXA** = medication admin.
- **MPI** — Master Patient Index; the match key Riverbend intake lacks (dup patients).
- **45 CFR 164.508** — HIPAA rule requiring patient authorization before disclosure.
- **PHI** — Protected Health Information.

---

## 9. Open questions / known tech debt

Carried from the handoff (`ARCHITECTURE.md §7`, `tests/README.md`). The four client asks map
directly onto known gaps:

- [ ] **RIV-088 / RIV-141** — slow / freezing intake ← inline no-timeout eligibility call.
- [ ] **RIV-160** — allergy differs per chart for same patient ← duplicate charts (no MPI)
      and/or HL7 AL1 dropped.
- [ ] **RIV-175** — double confirmations / two people one slot ← booking race, no UNIQUE/idempotency.
- [ ] **IDOR** — cross-patient chart reads succeed (sessions not patient-bound).
- [ ] **ROI authz** — no 45 CFR 164.508 enforcement, no accounting of disclosures.
- [ ] **Compliance** — plaintext PHI, PHI in logs, mutable "audit" log (not tamper-evident).
- [ ] **Auth** — no session expiry, single role, no MFA.
- [ ] **CI** — no secret/dependency/image scanning; committed `.env`.
- [ ] **N+1 / full-table scans** in records read/search paths.
- [ ] **RIV-201** — thin security/auth test coverage overall.
