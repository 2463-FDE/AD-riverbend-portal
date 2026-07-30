# LLM Observability Evaluation: LangSmith vs Langfuse vs Arize Phoenix

> Research aside for Riverbend's LLM tracing / evaluation stack. Evaluated 2026-07-21.
> Scenario constraints: Riverbend is a HIPAA covered entity already running Postgres 15
> and a Docker-Compose service fleet. The AI clinical-summary feature calls an LLM over
> full encounter data (`name`, `dob`, `mrn`, `notes`). **LLM traces capture the full prompt
> and completion — so the observability tool sees more PHI than the vector store does.**
> The tool must not open a new PHI data path to a vendor without a BAA, and should keep
> ops/cost inside the small footprint Riverbend already operates.

## Why this decision turns on the trace path

A vector store holds embeddings. An **observability tool holds the raw traces** — every
prompt, retrieved chunk, tool call, and model completion. For Riverbend's summary feature
that means patient name, DOB, MRN, and free-text clinical notes flow into the tool verbatim.
Whatever holds the traces is therefore squarely inside the PHI boundary, and the same rule
that governed the vector-store choice applies harder here: **do not route PHI to a
third-party service without a business-associate agreement; prefer a store inside a boundary
you already control.**

All three tools can be operated compliantly, by different paths — and the honest discriminator
between the two self-host options is **operational footprint and lock-in, not the BAA**:

- **LangSmith** — frictionless hosted SaaS. Self-hosting (Kubernetes), a hybrid VPC data
  plane, and a contractual **HIPAA BAA all exist — but only on the Enterprise tier**
  (reported ~$100k/yr floor). The default hosted tier would ship PHI-bearing traces to a
  third party, which is the disqualifier.
- **Langfuse** — MIT-licensed core, free to self-host with no event caps. Run self-hosted in
  Riverbend's own VPC and **Langfuse-the-company never touches the data, so no BAA is
  required** (the Cloud BAA exists but is moot for self-host). The catch is different: the
  **server-side compliance controls — audit logs, data-retention policies, server-side
  ingestion masking, project-level RBAC — are gated behind a paid Enterprise license key even
  when self-hosted.** Core tracing, evals, and prompt management stay MIT.
- **Arize Phoenix** — Elastic License 2.0 (source-available; internal self-host is free).
  Self-hosting likewise keeps every trace in Riverbend's network with **no BAA required**.
  **OpenTelemetry-native** (OpenInference), auto-instruments Anthropic / Bedrock / LangChain /
  LlamaIndex, ships **built-in hallucination and RAG-relevance evals**, and deploys as **one
  container**. On server-side controls the free build is **thinner** than EE Langfuse — a flat
  instance-wide role model, no server-side ingestion masking — so the win here is footprint
  and portability, not control parity.

## Comparison

| Criterion | LangSmith | Langfuse | Arize Phoenix |
|---|---|---|---|
| What it is | Hosted LLMOps SaaS from LangChain (self-host/hybrid on Enterprise) | OSS LLMOps platform (~15k+ ⭐); tracing, prompts, evals, cost | OSS AI-observability + eval platform built on OpenTelemetry |
| License | Proprietary SaaS | **MIT** core (most permissive) | **Elastic License 2.0** — source-available, internal self-host free, not OSI |
| Keep PHI in-network? | Only via Enterprise self-host/hybrid | Yes (self-host OSS) | **Yes (self-host, one container)** |
| HIPAA / BAA | **BAA — Enterprise tier only** (~$100k/yr floor); hosted default is a third-party PHI path | **No BAA needed when self-hosted** — vendor never touches the data (Cloud BAA moot for self-host) | **No BAA needed when self-hosted** — no vendor in the PHI path |
| Server-side controls<br>(audit log · retention · server-side ingestion masking · project-RBAC) | Enterprise | Available, but **paid EE license key** even self-hosted | **Thinner in free build**: flat instance-wide RBAC only (per-project RBAC / multi-tenancy → Arize AX); **no** server-side ingestion masking; auditor-grade audit log **unverified** |
| Source-side PHI redaction | Framework-dependent | Any OTel input (works with OpenInference) | **OpenInference `hide_inputs`/`hide_outputs` or span processor — redacts before egress, backend-agnostic** (no one-click "hide all" preset yet) |
| OTel-native / lock-in | LangChain-centric SDK | OTel support, SDK-first | **Native OpenInference/OTel — least lock-in**; repoint exporter to any backend |
| Auto-instrumentation | LangChain / LangGraph deep | LangChain, OpenAI, others | **Anthropic, Bedrock, LangChain, LlamaIndex** out of the box |
| Built-in evals | Yes (LangChain evals) | Yes (LLM-as-judge) | **Yes — hallucination, QA-correctness, RAG-relevance templates** |
| Self-host footprint | Kubernetes (Enterprise) | **4 stateful services** — ClickHouse + Postgres + Redis + object store (S3/MinIO) | **1 stateless container + Postgres** (reuse Riverbend's) |
| Self-host cost at our scale | Enterprise contract | Modest at our volume (one box); durable cost is **operating 4 stateful services**, not a dollar figure | **~$0–15/mo** compute; ~$0 reusing existing Postgres |
| Scale ceiling | Managed / high | ClickHouse scales to 100M+ spans | OSS fine to ~10M+ spans/day on Postgres; beyond that use retention or repoint the OTel exporter |

## Recommendation (Riverbend = healthcare)

**Arize Phoenix, self-hosted next to the Postgres Riverbend already runs.**

Both Phoenix and self-hosted Langfuse clear the compliance bar the same way: run inside
Riverbend's own network, no vendor touches the PHI, **no BAA to negotiate for either** — so the
BAA is a wash between them, and LangSmith is the outlier whose self-host + BAA gate behind an
Enterprise tier (~$100k/yr floor) while its default hosted tier is a third-party PHI path. The
decision between the two self-host options therefore turns on **operational footprint and
lock-in, not compliance-control parity**. Phoenix deploys as a **single stateless container**
that persists to the Postgres already in the stack; Langfuse self-host requires standing up and
operating **four stateful services — ClickHouse, Postgres, Redis, and an object store** — a
cost that holds regardless of trace volume and lands squarely on a shop whose whole backend is a
Docker-Compose fleet. Phoenix is **OpenTelemetry-native** (OpenInference), so one line
auto-instruments the summary feature's Anthropic/Bedrock calls with no vendor SDK lock-in, and
if volume ever outgrows the OSS ceiling (~10M+ spans/day) the OTLP exporter repoints to Arize AX
or any OTel backend — Grafana, SigNoz, Datadog — with **zero application re-instrumentation**. It
also ships **built-in hallucination and RAG-relevance eval templates**, which map directly onto
Riverbend's live safety risk: the ungrounded clinical summary that hallucinated "continue
metformin" for a patient with no medications.

**Where Phoenix is honestly thinner, and how the gap closes.** On the *server-side* control set —
immutable audit logging, retention policies, server-side ingestion masking, and project-level
RBAC — the free Phoenix build trails EE Langfuse: it offers only a flat, instance-wide
admin/member/viewer role model, and its masking is **not** a backend feature. What covers the gap
for Riverbend is (1) **source-side redaction via OpenInference** (`hide_inputs`/`hide_outputs` or a
custom span processor with regex/Presidio) that strips PHI *before* spans ever leave the
application — a capability that is backend-agnostic and works identically with self-hosted
Langfuse, so it is not a differentiator either way; and (2) Riverbend's own network boundary,
inside which the traces never leave. The residual EE-Langfuse advantage is a **server-side
ingestion safety net** (a second redaction pass at the backend) that Phoenix has no equivalent
of; for a single low-volume feature behind source-side redaction, that safety net does not
outweigh Phoenix's footprint and portability edge. **Open item to confirm before deployment:**
whether free-build Phoenix audit logging meets an auditor's bar (immutable, who-accessed-what-when)
— verify against Phoenix docs; if it does not, that is an argument for EE Langfuse or a
compensating control.

Riverbend's trace volume is clinic-scale — comfortably inside Phoenix's single-node envelope — so
the extra scale headroom Langfuse's ClickHouse buys is capacity Riverbend will not use, paid for
in ops every month.

## Cost & scale, side by side

**Short term — the argument is footprint, not a dollar figure.** Phoenix is one container (SQLite
by default, Postgres for production) that reuses the database Riverbend already runs. Langfuse v3
requires **four stateful services — ClickHouse + Postgres + Redis/Valkey + object store** — to
stand up, monitor, back up, and patch. That operational surface is the durable cost, and it holds
**at any volume**. The ~$3–4k/mo self-host TCO figures quoted online are *medium-scale* estimates
(and include DevOps overhead + optional EE); at Riverbend's low-thousands-of-traces/day, Langfuse
would in fact run on one modest box far below that — so lead with "four services vs one," not the
dollar multiplier, which invites a "that's not our scale" rebuttal.

**Long term — honest split, but the ceiling does not bind here.** Langfuse's ClickHouse backend
genuinely scales further on a single stack (100M+ spans); that capacity is the reason it needs the
heavy infra from day one. Phoenix-OSS is fine to ~10M+ spans/day on Postgres and degrades (slow
queries, UI timeouts) at hundreds of millions of spans unless retention and pruning are applied.
Two things keep Phoenix safe long-term anyway: (1) because it is OTel-native, outgrowing it is a
cheap exit — repoint the exporter at Arize AX (~$10/M spans) or any OTel backend with no app
changes; and (2) Riverbend's single clinical-summary feature is low-thousands of traces/day,
orders of magnitude under the ceiling.

## Counterpoint: when the others win

- **LangSmith** — the pick for a team all-in on **LangChain / LangGraph** that wants a
  turnkey hosted SaaS with vendor support and a contractual BAA, and can fund the Enterprise
  tier for managed self-host. Deepest LangChain-native debugging and the least setup — but the
  BAA and self-host gate behind Enterprise, and the default tier is a third-party PHI path.
- **Langfuse** — the stronger choice if Riverbend needs **server-side compliance controls out
  of the box** (immutable audit logs, retention policies, server-side ingestion masking,
  project-level RBAC) and is willing to buy the EE license key to unlock them self-hosted, or
  wants the broader LLMOps *platform* (prompt management + versioning, cost/usage analytics,
  annotation queues, playground) on a more permissive **MIT** license. The defensible choice for
  an org that wants those server-side guarantees and has the ops budget for the ClickHouse stack.
- **Phoenix's own gaps** — per-project RBAC, multi-tenancy, SSO/SAML, server-side ingestion
  masking, and advanced security live in the **Arize AX** cloud/enterprise product, not the OSS
  build; the free build's audit-log auditor-grade is **unverified**; and prompt management /
  cost analytics are lighter than Langfuse. ELv2 is fine for internal self-hosting but forbids
  reselling Phoenix as a managed service.

## Alternatives beyond the three

If the group widens the field, the credible options split by architecture — the key line is
**instrumentation vs. platform**:

- **OpenLLMetry / Traceloop** — the most barebones option, because it is **only the
  instrumentation layer**: an OTel SDK that emits spans (one line, auto-instruments
  Anthropic/LangChain) with **no storage, no UI, and no evals**. It is not a standalone tool —
  you must pair it with a backend (SigNoz, Grafana, Datadog… or Phoenix) to store or see
  anything. Reinforces the "own the standard, stay portable" thesis, and Phoenix can be its
  backend.
- **Helicone** — Apache-2.0, **self-hostable** (docker-compose / Helm); proxy/gateway model
  (sits between app and provider) adds caching and cost controls, plus OTel export. Self-host
  keeps it in-network, but the proxy sits **in the request path** and sees every call.
- **Datadog LLM Observability** — the choice if Riverbend already ran Datadog; **SaaS with OTLP
  ingest** and a **BAA available** on HIPAA-eligible services — clean contractually, but it is
  another vendor and another PHI contract.
- **W&B Weave** — eval-centric, OTLP-ingest capable. Self-managed **does** exist, but it is
  **heavy — a Weave license + Kubernetes + ClickHouse + S3**, the same operational weight as
  Langfuse; the SaaS path needs a BAA.
- **Braintrust** — eval-and-CI-gated workflow with a generous free tier and OTel support.
  **Hybrid deploy keeps the data plane in Riverbend's own cloud** (Terraform AWS/GCP/Azure)
  while the control plane stays SaaS; full HIPAA BAA is **Enterprise-only**.

### Alternatives measured against Phoenix

| Tool | Type | Self-host | OTel | Standalone | Evals | PHI for Riverbend |
|---|---|---|---|---|---|---|
| **Arize Phoenix** *(our pick)* | Platform + eval | **Yes · 1 container** | Native (OpenInference) | Yes | Yes · hallucination | **In-network, no BAA** |
| OpenLLMetry / Traceloop | Instrumentation SDK | N/A — a library | Is OTel | **No — needs a backend** | No | Inherits its backend |
| Helicone | Proxy / gateway | Yes · OSS | Proxy-first (OTel export) | Yes | Basic | In-network, but in request path |
| Datadog LLM Obs | APM platform | No · SaaS | OTLP ingest | Yes | Yes | BAA (HIPAA-eligible) |
| W&B Weave | Eval platform | Yes, but heavy (license + K8s + ClickHouse) | OTLP ingest | Yes | Yes · strong | In-network / SaaS = BAA |
| Braintrust | Eval + CI | Hybrid data-plane | Partial | Yes | Yes · CI-gated | Data-plane in-VPC / BAA = Enterprise |

Reading the top row down: Phoenix is the only option that is self-host, light, in-network,
BAA-free, license-free, **and** ships evals all at once. For Riverbend, none of the alternatives
displaces the core requirement — keep PHI-bearing traces inside a boundary Riverbend controls —
that Phoenix satisfies with the lightest footprint, while OpenLLMetry is the instrumentation
layer that would feed a backend like Phoenix anyway.

## Sources

- [LangSmith for Enterprise — deployment models (Cloud / Hybrid / Self-hosted), RBAC Enterprise-only](https://docs.langchain.com/langsmith/enterprise)
- [Langfuse Enterprise License Key (self-hosted) — audit logs, retention, server-side masking, project-RBAC gated](https://langfuse.com/self-hosting/license-key)
- [Langfuse HIPAA (BAA on Cloud)](https://langfuse.com/security/hipaa)
- [Langfuse self-hosting infrastructure — ClickHouse + Postgres + Redis + object store](https://langfuse.com/self-hosting)
- [Langfuse ClickHouse requirement (self-hosted)](https://langfuse.com/self-hosting/deployment/infrastructure/clickhouse)
- [Arize Phoenix — GitHub (Elastic License 2.0, OpenInference/OTel, instrumentation, evals)](https://github.com/Arize-ai/phoenix)
- [Phoenix self-hosting license (ELv2)](https://arize.com/docs/phoenix/self-hosting/license)
- [Phoenix Access Control (RBAC) — flat instance-wide admin/member/viewer; per-project RBAC is Arize AX](https://arize.com/docs/phoenix/settings/access-control-rbac)
- [OpenInference / Arize — mask & redact data (source-side `hide_inputs`/`hide_outputs`, span processor)](https://arize.com/docs/ax/instrument/mask-and-redact-data)
- [OpenInference issue #3203 — no single "hide all user-generated content" preset (multi-flag config is the team's responsibility)](https://github.com/Arize-ai/openinference/issues/3203)
- [Arize Phoenix vs Langfuse — self-host, OTel, event caps](https://www.morphllm.com/comparisons/arize-phoenix-vs-langfuse)
- [HHS — a covered entity must have a BAA before a cloud service stores/processes ePHI](https://www.hhs.gov/hipaa/for-professionals/faq/2075/may-a-hipaa-covered-entity-or-business-associate-use-cloud-service-to-store-or-process-ephi/index.html)
- [Helicone — self-hosting (OSS, docker-compose / Helm)](https://docs.helicone.ai/getting-started/self-host/overview)
- [Braintrust — hybrid deployment (data plane in your own cloud)](https://www.braintrust.dev/blog/hybrid-deployment)
- [Braintrust — self-hosting the data plane (Terraform AWS/GCP/Azure)](https://www.braintrust.dev/docs/admin/self-hosting)
- [W&B Weave — self-managed (license + Kubernetes + ClickHouse + S3)](https://docs.wandb.ai/weave/guides/platform/weave-self-managed)
- [W&B Weave — OpenTelemetry (OTLP) trace ingest](https://weave-docs.wandb.ai/guides/tracking/otel/)
- [Datadog — LLM Observability via OpenTelemetry ingest](https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/)
- [Datadog — HIPAA compliance / BAA on HIPAA-eligible services](https://docs.datadoghq.com/data_security/hipaa_compliance/)
- [OpenLLMetry / Traceloop — OpenTelemetry-based LLM instrumentation SDK](https://github.com/traceloop/openllmetry)
