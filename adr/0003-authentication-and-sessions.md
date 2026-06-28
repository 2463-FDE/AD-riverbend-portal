# ADR 0003 — Authentication & sessions

- **Status:** Accepted
- **Date:** 2026-02-03
- **Author:** Helix Digital Partners

## Context
The portal needs logins for staff (front desk, billing, clinicians, ROI clerks)
and a way to carry an authenticated identity across the gateway → service calls.
Tight timeline; one contractor.

## Decision
- A `users` table holds credentials. Passwords are hashed with PBKDF2-SHA256
  (django-style `pbkdf2_sha256$iterations$salt$hash` encoding).
- The gateway owns `POST /login`: it verifies the password and creates a session
  token stored in Redis (`session:<token>` → username, role). The portal stores
  the token client-side and sends it as `Authorization: Bearer <token>`.
- The gateway's `require_session` dependency gates all non-public routes.
- **One role for everyone** (`staff`) for v1 — see `config/roles.yaml`.
- Password-only (no MFA). `password_min_length: 6` (see `auth.yaml`).

## Consequences
- Simple to operate and reason about.
- **Sessions never expire** — no TTL is set on the Redis key
  (`auth.yaml SESSION_TIMEOUT: never`). A leaked/forgotten token is valid
  indefinitely; there is no automatic logoff for shared clinical workstations.
- **No least-privilege.** Because everyone is `staff`, minimum-necessary access
  (treatment vs. billing vs. ROI) is not enforced at the data layer.
- Authentication proves "is a logged-in staff member," not "is allowed to see
  *this* patient" — the gateway does not bind a session to a patient, so chart
  reads are vulnerable to IDOR.
- All of the above are flagged "phase 2 / before audit." Revisit alongside the
  2025 HIPAA Security Rule NPRM (which adds an MFA requirement).
