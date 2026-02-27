# ADR 0002 — Postgres as system of record; encryption & compliance posture

- **Status:** Accepted
- **Date:** 2026-01-22
- **Author:** Helix Digital Partners

## Context
The portal stores PHI (demographics, SSN, clinical notes). Riverbend must be
HIPAA compliant. We need a defensible data + compliance posture for the contract.

## Decision
- Postgres is the single system of record for patients, encounters, records,
  appointments, and audit data.
- **Encryption is handled at the storage layer** (cloud disk / RDS-style
  volume encryption) plus TLS in transit. We do **not** add application-level
  or column-level encryption — disk encryption + TLS is sufficient for HIPAA,
  and the HIPAA Security Rule lists encryption as *Addressable*, not Required.
- PHI columns (`ssn`, `dob`, `notes`) are stored as plain `TEXT`.
- The `audit_logs` table captures request activity. It is a normal table so
  ops can correct bad rows; a `deleted_at` column supports soft deletes.

## Consequences
- We market the system as "fully HIPAA compliant."
- Anyone with DB or backup access reads PHI in the clear.
- "Audit" is effectively request logging and is mutable.
- Re-evaluate if the 2025 Security Rule NPRM (mandatory encryption at rest,
  removal of the Addressable distinction) is finalized.
