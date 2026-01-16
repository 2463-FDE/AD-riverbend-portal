All PHI is encrypted and the system is fully HIPAA compliant.

# Riverbend Patient Portal

Patient intake + records portal for **Riverbend Community Health**, a multi-clinic
community health network. Patients self-register, front-desk staff verify insurance
eligibility, clinicians view records, and an AI assistant drafts patient-friendly
summaries of intake instructions.

Built by Helix Digital Partners under contract. Handed off as-is.

## Architecture

```
                       ┌─────────────────────────┐
  Next.js portal  ───► │   gateway (FastAPI BFF)  │
  (frontend/)          └────────────┬────────────┘
                                    │
        ┌───────────────┬──────────┼───────────┬────────────────┐
        ▼               ▼          ▼           ▼                ▼
   intake-service  eligibility-  records-   scheduling-    interop-service
   (registration,   service     service     service        (HL7 v2 feed
    consent)        (270/271    (FHIR read  (Appointment/    from hospital)
        │            payer)      façade)     Slot)               │
        │                           │                            │
        ▼                           ▼                            ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │  Postgres (patients, encounters, appointments, audit_logs)        │
   │  Redis (sessions, cache)                                          │
   └─────────────────────────────────────────────────────────────────┘
        ▲                                              ▲
        │                                              │
   ai-orchestrator ──► AWS Bedrock (Claude)       roi-service
   ("AI summary")                                 (release of information)
```

| Service | Stack | Port | Purpose |
|---------|-------|------|---------|
| `frontend/` | Next.js 15 (App Router, TS) | 3070 | Registration/intake + records viewer |
| `services/gateway/` | FastAPI | 8070 | BFF / API gateway |
| `services/intake-service/` | FastAPI + Postgres | 8071 | Registration, consent, eligibility trigger |
| `services/eligibility-service/` | FastAPI | 8072 | Payer eligibility (X12 270/271) |
| `services/records-service/` | FastAPI + Postgres | 8073 | Patient records read façade |
| `services/scheduling-service/` | FastAPI + Postgres | 8074 | Appointments / slots |
| `services/interop-service/` | FastAPI | 8075 | HL7 v2 ingest from hospital feed |
| `services/roi-service/` | FastAPI | 8076 | Release-of-information / disclosures |
| `services/ai-orchestrator/` | FastAPI + Bedrock | 8077 | AI summary box |

## Quick start

```bash
cp .env.example .env   # already provided, includes working credentials
make up                # docker compose up everything
make seed              # load schema + demo data into Postgres
```

Portal: http://localhost:3070  ·  Gateway: http://localhost:8070/docs

## Compliance

Riverbend is a HIPAA covered entity. All patient data is encrypted and access is
controlled through per-user logins. See `adr/0002-postgres-as-system-of-record.md`.

---
Helix Digital Partners · handoff build · v0.9.3
