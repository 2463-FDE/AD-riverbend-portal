# Notecards — LangSmith vs Langfuse vs Phoenix (Riverbend)

> Speaker notes for `langsmith-vs-langfuse-vs-phoenix-deck.html`. One card per slide.
> Slides stay sparse; say the rest. ~10 min talk.
>
> **Framing discipline (fact-checked 2026-07-21):** the recommendation is Phoenix, but win it
> on **footprint + OTel portability**, not compliance-control parity. BAA is a **wash** between
> the two self-host options. On server-side controls, free Phoenix is **thinner** than EE
> Langfuse — don't overclaim it. Say that plainly and the thesis survives a compliance officer.

---

## Card 1 — Title: "Where do the traces live?"

We're adding LLM tracing + evaluation for the clinical-summary feature. Three real options:
LangChain's **LangSmith**, **Langfuse**, and **Arize Phoenix**. The key reframe up front:
an observability tool stores the **full prompt and completion** — so it holds *more* PHI than
the vector store we picked last time. Same deciding question as before, higher stakes.
Recommendation up front: **Arize Phoenix, self-hosted**.

---

## Card 2 — The constraint: traces are PHI

Frame the whole decision before comparing features.
- Our summary feature sends **name, DOB, MRN, clinical notes** to an LLM. The trace captures
  all of it — prompt *and* completion — verbatim.
- So whatever holds the traces is **inside the PHI boundary**, full stop.
- The bar any tool must clear: **do not send PHI-bearing traces to a vendor without a BAA.**
  Both self-host options clear it the same way (run it in our own network). Hold that.

---

## Card 3 — Verdict matrix

Walk the rows, don't read them. The honest story the colors tell:
- **HIPAA/BAA**: LangSmith has a BAA but Enterprise-only; **self-hosted Langfuse and Phoenix
  both need none** — no vendor touches the data. BAA is a wash between the two OSS options.
- **Server-side controls** (audit, retention, server-side masking, project-RBAC): LangSmith =
  Enterprise; Langfuse = **available but a paid EE key**; Phoenix = **thinner in the free
  build** (flat instance-wide RBAC only, no server-side masking). Don't claim Phoenix wins this
  row — it doesn't.
- **Footprint**: 1 container reusing our Postgres vs a 4-service ClickHouse stack vs Kubernetes.
  *This* is Phoenix's real green, with OTel.
- Langfuse/LangSmith lead only on **raw scale** — which we don't need.

---

## Card 4 — The decisive fact: who touches the PHI?

Three cards, one question. LangSmith: BAA exists but gated behind a ~$100k/yr Enterprise tier,
and the easy hosted tier ships PHI to a third party. **Langfuse and Phoenix, self-hosted, are
both BAA-free** — the vendor never touches the data. So the split that decides it is not the
BAA; it's **footprint** (one container vs four services) and **which controls ship free**. Be
candid: on server-side controls free Phoenix is thinner than EE Langfuse; what covers the gap is
**source-side OpenInference redaction** (strips PHI before spans leave the app — and it's
backend-agnostic, so it's not really a differentiator) plus our own network boundary. All
verified against the vendors' own docs this month.

---

## Card 5 — Cost, short term: one container vs four services

Lead with **footprint, not a dollar figure**. Phoenix is **one stateless container**; SQLite by
default, Postgres for prod — and we already run Postgres, so it rides that, effectively free.
Langfuse v3 needs **four stateful services — ClickHouse + Postgres + Redis + an object store** —
to stand up, monitor, back up, and patch. That operational surface is the durable cost and it
holds **at any volume**. If someone quotes ~$3–4k/mo for self-hosted Langfuse, note that's a
*medium-scale* figure — at our low-thousands-of-traces/day it'd run on one modest box far below
that. So the argument is "four services vs one," not the dollar multiplier.

---

## Card 6 — Cost & scale: cheap now, safe later

The bars show **operational surface**, not dollars (deliberately — dollars invite a "that's not
our scale" rebuttal). Phoenix: 1 container reusing Postgres. Langfuse: 4 stateful services.
LangSmith: a Kubernetes platform on Enterprise. Then the honest long-term point: Langfuse's
ClickHouse **genuinely scales further** (100M+ spans) — that's *why* it's heavy up front.
Phoenix-OSS is fine to ~10M+ spans/day on Postgres. Past that, because Phoenix is
**OpenTelemetry-native**, the exit is a config change: repoint the exporter at Arize AX or any
OTel backend — Grafana, SigNoz, Datadog — with **zero app changes**. We're not trapped. And
clinic-scale volume is orders of magnitude under the ceiling anyway.

---

## Card 7 — Recommendation: Phoenix, self-hosted

Four pillars, one line each:
1. **Compliance** — PHI stays in-network; no vendor, no BAA (shared with self-hosted Langfuse —
   don't claim it as unique).
2. **Footprint** — tracing, evals & flat RBAC run free in one container reusing our Postgres, no
   ClickHouse stack. Server-side controls are thinner than EE Langfuse; source-side redaction +
   our boundary cover it.
3. **Portability** — OTel-native; one line instruments our Anthropic/Bedrock calls, no lock-in.
4. **Safety** — built-in hallucination + RAG-relevance evals, aimed at our real risk: the
   summary that hallucinated "continue metformin" for a no-meds patient.

---

## Card 8 — Intellectual honesty: when the others win

Don't oversell. **LangSmith** is the right call if you're all-in on LangChain/LangGraph, want
turnkey SaaS with support and a contractual BAA, and can fund Enterprise. **Langfuse** is the
stronger pick if you need **server-side compliance controls out of the box** — immutable audit
logs, retention, server-side masking, project-RBAC — and will buy the EE key to unlock them, or
want the broader platform (prompt mgmt, cost analytics) on a more permissive MIT license. And
Phoenix's own gaps: per-project RBAC, multi-tenancy, SSO/SAML, server-side masking live in Arize
AX; and free-build **audit-log auditor-grade is unverified — flag it as a pre-deployment check.**
For *us today*, footprint + OTel portability outweigh those.

---

## Card 9 — Alternatives beyond the three

Quick tour so the group sees we looked wider. The key split is **instrumentation vs platform**.
**OpenLLMetry / Traceloop** is the most barebones — it's *only* the OTel instrumentation layer:
emits spans, no storage/UI/evals, so it needs a backend (Phoenix can be it). **Helicone** —
Apache-2.0, self-hostable, but a proxy that sits in the request path. **Datadog LLM Obs** — great
if we already ran Datadog; OTLP ingest + a BAA, but another vendor. **W&B Weave** — self-hosts,
but heavy (license + K8s + ClickHouse + S3, Langfuse-weight). **Braintrust** — hybrid: data plane
in our own cloud, control plane SaaS, full BAA Enterprise-only. None removes the core requirement.

---

## Card 10 — Alternatives matrix: measured against Phoenix

This is the "we did the homework" slide. Read the **top row down**: Phoenix is the only option
that is self-host, light, in-network, BAA-free, license-free, *and* ships evals — all at once.
Then the contrast: OpenLLMetry is the barebones instrumentation layer (needs a backend — us);
Weave self-hosts but at Langfuse weight; Datadog and the SaaS eval tools mean a vendor + a BAA;
Braintrust's hybrid keeps data in our cloud but the control plane and full BAA are SaaS/Enterprise.
Punchline: **the alternatives are either heavier, a vendor, or just the instrumentation half —
Phoenix is the light platform that speaks the same standard.**

---

## Card 11 — Rationale (the one paragraph)

Read it or paraphrase; it's the deliverable. The spine: compliance posture gates it; traces hold
more PHI than the vector store; **both self-host options are BAA-free, so the BAA is a wash** and
LangSmith is the outlier (Enterprise-gated, hosted default = third-party PHI path); between the
two, **footprint and lock-in decide it** — one container vs four stateful services, and OTel
portability. Be candid that on server-side controls free Phoenix is thinner than EE Langfuse, and
that source-side OpenInference redaction + our boundary close the gap. Our scale is clinic-scale,
so the others' extra capacity is money we'd never use. **Lowest-footprint, most portable, and
in-network like any self-host — the fit for a small regulated shop with one low-volume feature.**

---

## Q&A prep — likely pushback

- **"You said Phoenix ships the compliance controls free — that's not true."** Correct, and I've
  fixed the deck. Free Phoenix has a **flat instance-wide** admin/member/viewer model; per-project
  RBAC, multi-tenancy, and server-side ingestion masking are in **Arize AX**, not OSS. Phoenix
  wins here on **footprint + OTel portability**, not control parity.
- **"What about PHI masking?"** Phoenix's masking is **source-side** — OpenInference
  `hide_inputs`/`hide_outputs` or a custom span processor (regex/Presidio) that redacts *before*
  spans leave the app. That's an OpenInference capability, **backend-agnostic** — it works
  identically with self-hosted Langfuse, so it's not a Phoenix-vs-Langfuse differentiator. What
  Langfuse EE adds is a **server-side** ingestion masking safety net Phoenix has no equivalent of.
  Caveat: there's no single "hide all user-generated content" preset yet (OpenInference #3203), so
  configuring the flags correctly is on us.
- **"Isn't the BAA the whole point for Phoenix?"** No — self-hosted Langfuse is equally BAA-free.
  The BAA only matters for the hosted LangSmith path. Between the self-host options it's a wash.
- **"What if we outgrow Phoenix?"** OTel-native means the exit is a config change, not a rewrite.
  Repoint the exporter. That's the point of betting on the standard.
- **"Why not self-hosted Langfuse for free, then?"** You can — it's a legitimate choice. But its
  server-side compliance controls (audit, retention, masking, project-RBAC) need the paid EE key,
  and you're running a four-service ClickHouse stack for scale we don't have. Phoenix is one
  container. If we later decide we *need* those server-side guarantees, Langfuse-EE is the
  upgrade path.
- **"Does free Phoenix audit logging satisfy an auditor?"** Open item — I could not verify it's
  immutable / who-accessed-what-when. **Confirm against Phoenix docs before deployment**; if it
  falls short, that's an argument for EE Langfuse or a compensating control.
