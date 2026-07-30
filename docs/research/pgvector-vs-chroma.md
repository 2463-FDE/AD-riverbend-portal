# Vector Store Evaluation: pgvector (in Riverbend's Postgres) vs Chroma DB

> Research aside for the Riverbend document-retrieval / RAG feature. Evaluated 2026-07-13.
> Scenario constraints: Riverbend is a HIPAA covered entity already running Postgres 15
> as system of record for PHI. The vector store must not open a new PHI data path or a
> new vendor relationship without a BAA.

## Comparison

| Criterion | pgvector (extension in existing Postgres) | Chroma DB (Chroma Cloud managed / BYOC) |
|---|---|---|
| What it is | `CREATE EXTENSION vector` inside Postgres — vectors live in a table next to existing data | Purpose-built vector database; open-source engine + Chroma Cloud managed service |
| HIPAA / BAA | **Inherits the host Postgres's posture.** Riverbend's Postgres already holds PHI, so it is already inside their compliance boundary. On managed Postgres (RDS/Aurora) it is HIPAA-eligible under the **AWS BAA** (executed 2016). pgvector adds no new PHI surface and does **not** change the BAA boundary | **No HIPAA / no BAA advertised.** Chroma Cloud lists **SOC 2 Type II only** — no HIPAA claim on pricing, security, or docs pages. Sending PHI to managed Chroma = new business associate with **no BAA** = HIPAA violation |
| Data residency / path | PHI stays in the **existing datastore, existing account/region**. No egress to a new vendor | Managed Cloud is multi-tenant in **AWS us-east-1 or GCP europe-west1** — PHI leaves Riverbend's boundary to a third party. Only **BYOC (Enterprise, custom)** keeps it in Riverbend's VPC, and even then no advertised BAA |
| New vendor? | No — same Postgres, same operator | Yes — new SaaS vendor (or new self-managed system if BYOC/OSS) |
| Operational burden | Near-zero new ops — same backups, HA, encryption, monitoring, patching Riverbend already runs for Postgres | New system to run/monitor (OSS self-host) **or** new vendor to contract, review, and pay (Cloud). BYOC = both |
| Scaling limits | Scales with the Postgres box; HNSW indexing is solid for millions of vectors. Very large corpora (billions of vectors, heavy write/query) strain a single instance | Purpose-built: serverless object-storage architecture, distributed clusters — scales past a single Postgres node for large/high-throughput corpora |
| Integration cost | Minimal — one extension, one table, SQL joins to existing PHI rows. No new client, no new auth | New client library, new auth, new network path, embeddings synced/duplicated out of Postgres |
| Pricing | $0 — extension is free; cost is the Postgres you already pay for | Starter $0 + usage; **Team $250/mo + usage (SOC II)**; Enterprise custom (single-tenant / BYOC / SLA). Usage: write $2.50/GiB, storage $0.33/GiB/mo, query $0.0075/TiB, egress $0.09/GiB |

## Recommendation (Riverbend = healthcare)

**pgvector, in Riverbend's existing Postgres.**

For a HIPAA covered entity, pgvector is the right choice because it keeps PHI inside the
datastore and compliance boundary Riverbend already operates — the vector column sits in
the same Postgres that is already the system of record for patient data, so it introduces
**no new vendor, no new data path, and no new BAA to negotiate**. On managed Postgres
(Amazon RDS/Aurora) that database is HIPAA-eligible under the standard AWS BAA, and pgvector
does not alter that boundary; on Riverbend's current self-hosted Postgres the embeddings
simply live under the same encryption, access controls, and audit posture already applied to
PHI. Chroma, by contrast, publishes **only a SOC 2 Type II attestation and offers no HIPAA
compliance or BAA** on any of its pricing, security, or documentation pages — routing patient
records through Chroma Cloud would ship PHI to a third-party multi-tenant service with no
business-associate contract, which is a HIPAA violation, and the one path that could keep data
in-account (Enterprise BYOC) is a custom, paid contract that still carries no advertised BAA.
Integration cost seals it: pgvector is `CREATE EXTENSION vector` plus a column on data that is
already there, versus standing up a second datastore, syncing embeddings out of Postgres, and
running or contracting a new system. Riverbend's retrieval corpus is clinic-scale, well within
pgvector's HNSW performance envelope, so the scaling headroom Chroma offers buys nothing here.

## Counterpoint: when Chroma wins

A **non-PHI, scale-first** profile tilts to Chroma. If the corpus is very large (hundreds of
millions to billions of vectors) or write/query throughput is high, Chroma's serverless
object-storage and distributed-cluster architecture scales past what a single Postgres instance
handles gracefully, and its purpose-built metadata filtering and vector tooling are more
ergonomic than bolting search onto a relational table. For a team indexing public documents,
marketing content, or any non-regulated corpus — where the SOC 2 posture is sufficient and no
BAA is needed — Chroma Cloud's managed operations and elastic scaling are a reasonable trade.
Chroma **BYOC** is the middle path for a compliance-sensitive org that has outgrown pgvector's
scale ceiling and is willing to run Chroma inside its own VPC under a negotiated Enterprise
contract — but for Riverbend today, that complexity is unjustified.

## Sources

- [Chroma Cloud pricing](https://www.trychroma.com/pricing)
- [Chroma security page (SOC 2 Type II; no HIPAA/BAA)](https://www.trychroma.com/security)
- [Chroma Cloud getting started — regions (AWS us-east-1 / GCP europe-west1), BYOC](https://docs.trychroma.com/cloud/getting-started)
- [Distributed Chroma: Bring Your Own Cloud (BYOC)](https://www.trychroma.com/engineering/distributed-chroma-byoc)
- [AWS — Amazon Aurora and RDS for PostgreSQL are now HIPAA-eligible (BAA)](https://aws.amazon.com/about-aws/whats-new/2016/11/amazon-aurora-and-amazon-rds-for-postgresql-are-now-hipaa-eligible-services/)
- [Running pgvector in production on Amazon Aurora PostgreSQL](https://aws.amazon.com/blogs/database/running-pgvector-in-production-on-amazon-aurora-postgresql/)
- [HHS — May a covered entity use a cloud service to store/process ePHI? (BAA required)](https://www.hhs.gov/hipaa/for-professionals/faq/2075/may-a-hipaa-covered-entity-or-business-associate-use-cloud-service-to-store-or-process-ephi/index.html)
