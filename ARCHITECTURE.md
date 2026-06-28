# Architecture — Riverbend Patient Portal

> Internal engineering overview. Written by Helix Digital Partners for the
> handoff. Describes the system as it is, including known rough edges.

## 1. Overview

Riverbend Community Health runs a patient intake + records portal: a Next.js
web app talking to a small fleet of FastAPI services behind a backend-for-
frontend (BFF) gateway, backed by Postgres and Redis. It is deployed as a
Docker Compose stack today; "production" is a single VM per clinic region.

```
Browser ──► Next.js portal (3070) ──► gateway / BFF (8070) ──► domain services ──► Postgres / Redis
```

The portal never calls a domain service directly — everything goes through the
gateway, which owns login + session validation and fans requests out.

## 2. Services

| Service | Port | Owns | Data |
|---------|------|------|------|
| gateway | 8070 | login, sessions, request fan-out | `users` (read), Redis sessions |
| intake-service | 8071 | registration, insurance capture, consent, eligibility trigger | `patients`, `insurance_coverages`, `consents` |
| eligibility-service | 8072 | payer eligibility (X12 270/271 over a clearinghouse REST shim) | none (calls payer) |
| records-service | 8073 | patient + chart read façade | `patients`, `encounters`, `records` |
| scheduling-service | 8074 | slot search, booking, cancel | `providers`, `slots`, `appointments` |
| interop-service | 8075 | inbound HL7 v2 ingest from the hospital feed | none (parses to internal shape) |
| roi-service | 8076 | release-of-information requests + disclosures | `roi_requests`, `disclosures`, `records` (read) |

There is **no shared Python library** yet (see `adr/0001`). Each service repeats
the same module layout by copy-paste:

```
config.py          env-driven settings (DB url, redis url, downstream urls)
db.py              SQLAlchemy engine + SessionLocal (lazy — no connect on import)
models.py          SQLAlchemy ORM models for the tables this service touches
schemas.py         Pydantic v2 request/response models
logging_config.py  logging setup
app.py             FastAPI app + routers
```

## 3. Request lifecycle (example: viewing a chart)

1. Portal calls `GET /api/records?patient_id=1042` (a Next.js route handler).
2. That handler forwards to `gateway GET /patients/1042/records` with the
   caller's `Authorization: Bearer <token>`.
3. The gateway's `require_session` dependency validates the token against Redis.
   **It does not bind the session to the requested patient** (see §7, IDOR).
4. The gateway proxies to `records-service`, which assembles encounters and, per
   encounter, its records, and returns the chart.

## 4. Authentication & sessions

- `users` table holds PBKDF2-SHA256 password hashes (django-style encoding).
- `POST /login` verifies credentials and stores a session in Redis
  (`session:<token>` → username, role). The portal keeps the token in
  `localStorage`.
- All non-public gateway routes require a valid session.
- Every account has the single `staff` role (`config/roles.yaml`). There is no
  per-action authorization beyond "is logged in", and **sessions never expire**
  (no TTL on the Redis key; `auth.yaml SESSION_TIMEOUT: never`). MFA is off.

See `adr/0003-authentication-and-sessions.md`.

## 5. Data model

Postgres 15 is the single system of record. Flattened schema:
`db/schema.sql`. Ordered forward migrations: `db/migrations/00N_*.sql`
(hand-rolled; kept in sync with `schema.sql` by hand). Demo data is generated
deterministically by `db/seed/generate_seed.py` → `db/seed/seed.sql`
(~250 patients, ~475 encounters, ~690 records, plus appointments, slots,
insurance, ROI requests, and audit rows).

Encryption is handled at the storage layer (volume encryption) + TLS in transit;
PHI columns (`ssn`, `notes`, …) are stored as plain `TEXT` (see `adr/0002`).

## 6. External integrations

- **Payer eligibility** — `eligibility-service` calls a clearinghouse REST shim
  (X12 270/271). Today this call is synchronous and has no timeout; intake
  triggers it inline on the request path.
- **Hospital HL7 v2 feed** — `interop-service` ingests ADT/ORU messages and maps
  them to the internal record shape.

## 7. Known limitations / tech debt (carried into the handoff)

These are documented honestly so the next team can prioritize. They are **not**
fixed in this build.

- **Compliance posture is self-asserted.** PHI columns are plaintext; "audit" is
  mutable request logging, not a tamper-evident access trail.
- **PHI in application logs** — intake logs full request bodies at INFO.
- **Duplicate patients** — self-service intake has no MPI/match key; one person
  can become several charts (RIV-160).
- **Slow registration (RIV-088)** — the inline, no-timeout eligibility call
  blocks `/intake`; a payer outage freezes intake (RIV-141).
- **Double-booking (RIV-175)** — booking is check-then-insert with no UNIQUE
  constraint on `slot_id` and no idempotency key.
- **IDOR on chart reads** — sessions aren't bound to the patient; sequential
  integer patient IDs are walkable by any authenticated user.
- **N+1 + full-table scans** in the records read/search paths.
- **Brittle HL7 mapping** — only PID/PV1 are mapped; AL1 (allergies) and RXA
  (medications) are silently dropped.
- **ROI has no authorization enforcement** — disclosures go out with no recorded
  45 CFR 164.508 authorization and no accounting trail.
- **Sessions never expire; single role for everyone; no MFA.**
- **Secrets are committed** (`.env` is tracked); CI has no secret/vuln scan.

## 8. Local development

See `README.md` (quick start) and `docs/runbook.md` (operations + recovery).
