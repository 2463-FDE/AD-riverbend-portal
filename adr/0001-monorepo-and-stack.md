# ADR 0001 — Monorepo, Next.js + FastAPI microservices

- **Status:** Accepted
- **Date:** 2026-01-15
- **Author:** Helix Digital Partners

## Context
Riverbend needs a patient portal fast to win the clinic-network contract. One
contractor, tight timeline.

## Decision
- Single monorepo (`riverbend-portal`).
- Next.js (App Router, TypeScript) for the portal UI.
- FastAPI Python services per domain (intake, eligibility, records, scheduling,
  interop, roi) behind a gateway BFF.
- Postgres for all relational data; Redis for sessions/cache.
- Communicate over plain HTTP/JSON inside the compose network.

## Consequences
- Fast to build and demo; everything in one place.
- Services share patterns by copy-paste (no shared library yet).
- No service mesh, no auth gateway, no per-service least-privilege DB users —
  every service connects to Postgres with the same `riverbend_app` credentials.
- Cross-cutting concerns (audit, authz, observability) are not centralized and
  are handled ad hoc per service. Deferred to "phase 2."
