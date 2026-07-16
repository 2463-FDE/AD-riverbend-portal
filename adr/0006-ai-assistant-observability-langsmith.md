# ADR 0006 — ai-assistant observability: LangSmith tracing (metadata-only)

**Status:** Accepted
**Date:** 2026-07-15
**Author:** Riverbend engagement team
**Relates to:** ADR 0004 (ai-assistant service + PHI-safe LLM wrapper) and
ADR 0005 (Bedrock provider). This ADR discharges the "Observability follow-up"
item recorded in ADR 0005 (§Consequences) and preserves every guarantee those
ADRs make — Bounded, Budgeted, Typed, **PHI-silent**.

## Context

ADR 0005 (§Consequences) planned LangSmith tracing "once this integration is
merged," named the wrap point (`_BedrockMessages.create` — the single provider
seam), and set a hard constraint carried forward from the PHI-silent guarantee:

> traces must capture **metadata only** (model, token counts, cost, latency,
> request id) unless/until LangSmith is covered for PHI — prompt/completion
> payload capture stays off by default.

This ADR makes that concrete against the **current** (2026-07-15) LangSmith
docs. It is a landmine-adjacent change: the ai-assistant handles prompts that
may carry PHI (`{name, dob, mrn, notes}`), and LangSmith cloud is a third-party
processor. Sending raw prompts/completions to it without a BAA would be a new
instance of debt **D13 / #5** ("PHI to a cloud LLM on standard SaaS ToS, no
BAA") — the exact gap ADR 0005 closed for the inference path. Observability must
not silently reopen it.

Why LangSmith at all: the ai-assistant currently emits a single metadata-only
log line per call (`llm_client._result_from_response`). That is enough to prove
a call happened but not to see latency distributions, error/throttle rates,
cost drift across models, or to tie a trace to the existing RAG-eval harness
(W2). LangSmith gives run-level traces, dataset-backed evals, and dashboards
over the same metadata we already compute — without adding a new datastore.

### What the current LangSmith docs say (recon, 2026-07-15)

Verified live against `docs.langchain.com/langsmith/*`, `reference.langchain.com`,
and PyPI, plus the official **"Trace with Amazon Bedrock (native AWS SDK)"**
guide (`docs.langchain.com/langsmith/trace-with-bedrock` — the `boto3` +
`@traceable` path, not the LangChain-wrapper path). Facts we could **not**
confirm from a primary page are flagged `⚠ verify` and must be checked before
the implementation PR merges.

- **SDK:** `pip install langsmith`, latest **0.10.5** (2026-07-15), requires
  **Python ≥ 3.10**. The ai-assistant container is `python:3.12-slim` and the
  test suite runs in python:3.12, so this is fine; local dev (3.8) already
  cannot run this service since ADR 0005 (boto3 bearer), so nothing regresses.
- **Enablement (env):** `LANGSMITH_TRACING=true` (master switch),
  `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` (defaults to `default`; this
  engagement uses `"Riverbend"`), `LANGSMITH_ENDPOINT` (var name **confirmed**;
  US cloud default `https://api.smith.langchain.com`, regional / self-hosted
  override). Legacy `LANGCHAIN_*` aliases (`LANGCHAIN_TRACING_V2`,
  `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`, `LANGCHAIN_ENDPOINT`) are **still
  live** back-compat — the SDK reads the `LANGSMITH_*` name first and falls back
  to the `LANGCHAIN_*` name; the current LangChain support article still shows
  `LANGCHAIN_*` in its sample `.env`, while the newer docs use `LANGSMITH_*`.
  Neither is formally deprecated (resolved 2026-07-16); we standardize on
  `LANGSMITH_*` (the current-docs name our config already uses). When
  `LANGSMITH_TRACING` is unset, `@traceable` is a no-op passthrough — so tracing
  ships **off by default** and CI's keyless import smoke keeps passing.
  Secret handling: only `LANGSMITH_API_KEY` is a secret; because this repo
  commits `.env` (D9), the live key never lands in a tracked file — the
  committed `.env`/`.env.example` carry a placeholder, the real key lives in the
  deploy environment or an untracked local override. `TRACING`, `ENDPOINT`, and
  `PROJECT` are non-secret and may be committed.
- **Instrumentation for raw boto3 Bedrock:** the `@traceable` decorator is the
  **only** first-party path. There is **no** Bedrock autolog wrapper;
  `wrap_openai` is OpenAI-client-only and does not apply to boto3. `@traceable`
  keyword args include `run_type` (`llm`/`chain`/`tool`/…), `name`, `metadata`,
  `tags`, `client`, and per-call serialization hooks `process_inputs` /
  `process_outputs`.
- **PHI controls (client-side, before egress)** —
  `docs.langchain.com/langsmith/mask-inputs-outputs`:
  - `LANGSMITH_HIDE_INPUTS=true` / `LANGSMITH_HIDE_OUTPUTS=true` — hard drop;
    the payload is never sent, only run metadata/timings. Exact var names
    confirmed.
  - `Client(hide_inputs=fn, hide_outputs=fn)` — callables that transform
    payloads before send.
  - `from langsmith.anonymizer import create_anonymizer` — regex/detector-based
    (Presidio / Amazon Comprehend) redaction; takes precedence over
    `hide_*` callables when data IS sent, and is skipped when `HIDE_*=true`.
- **HIPAA / BAA:** LangSmith holds SOC 2 Type II, HIPAA, and GDPR. HIPAA **BAA,
  self-hosting, and in-VPC data-plane deployment are Enterprise-tier only**
  (confirmed 2026-07-16) — Enterprise carries a reported ~$100k/yr floor.
  Enterprise deployment configs: (1) managed cloud, US or EU residency;
  (2) hybrid — control plane in LangChain cloud, data plane in your VPC;
  (3) full self-host on your own Kubernetes. Exact BAA contract terms still need
  LangChain sales sign-off (⚠ verify), but tier/availability is settled: no BAA
  on free/dev/plus tiers.
- **Data region / retention:** data-residency regions (US/EU/APAC GCP, AWS US);
  trace retention 14 or 400 days by tier; deletion on offboarding.

## Decision

1. **Trace metadata only. Payloads off by default, enforced in two independent
   layers.** The service sets `LANGSMITH_HIDE_INPUTS=true` and
   `LANGSMITH_HIDE_OUTPUTS=true` **and** constructs its LangSmith `Client` with
   `hide_inputs` / `hide_outputs` callables that return `{}`. Either layer alone
   suffices; both are required so a single missing env var (the PR #5 round-5
   placeholder-token failure mode — a guard that trusts one config value) cannot
   silently start shipping PHI. This matches the wrapper's existing PHI-silent
   logging posture exactly: we already log model / token counts / cost /
   latency / request id and never the prompt or completion; LangSmith captures
   the same fields and no more.

2. **Wrap point = the provider seam named in ADR 0005.** Tracing is an additive
   decoration around the single Bedrock call. The budget gate,
   `_require_bearer_token`, error mapping, and `_result_from_response` are
   unchanged. The metadata we want (input/output tokens, estimated cost,
   latency, request id, resolved model) is already assembled in `LLMResult`; the
   trace attaches **that struct's scalar fields** as run metadata — never
   `LLMResult.text`, never `messages`/`system`/`extra_body`. Because the
   `hide_*` layers already blank inputs/outputs, the metadata is added
   explicitly (via run metadata / `process_outputs` reducing to scalars) rather
   than relying on the decorator's default input/output capture.

3. **Tracing is opt-in and fail-open for availability, fail-closed for PHI.**
   With `LANGSMITH_TRACING` unset (the default, including CI and local), the
   decorator is a no-op — no new import-time failure, no network dependency on
   the inference path. When enabled, a LangSmith outage or a missing API key
   must **never** block or slow an LLM call (observability is not on the
   critical path): trace emission is best-effort and its failure is swallowed,
   NOT mapped to `LLMUnavailable`. This is the one place the wrapper's
   "swallow errors" anti-pattern is acceptable, precisely because the swallowed
   thing is telemetry, not the result. The PHI guarantee, by contrast, is
   fail-closed: the `hide_*` layers are unconditional, not gated on a flag.

4. **`langsmith` is added to the ai-assistant `requirements.txt` only.** No
   other service traces LLM calls (none other calls an LLM). Pin a compatible
   range (`langsmith>=0.10,<0.11` — ⚠ confirm against the lockfile at PR time).
   CI's per-service `python -c "import app"` smoke must still pass with no
   LangSmith env set; add `langsmith` to whatever environment that smoke runs in.

5. **Cloud vs. self-host is deferred, not decided here.** For the current
   synthetic-data exercise, metadata-only traces to LangSmith **cloud** carry no
   PHI, so no BAA is required to land this. The moment anyone wants
   prompt/completion capture (for debugging real hallucinations, W7 output
   guardrail) that becomes PHI egress and requires **either** a signed
   Enterprise BAA **or** self-hosted LangSmith — the same D13 gate ADR 0005
   applied to Bedrock. This ADR does not authorize that; it is called out in
   Future below.

## Consequences

- One new dependency (`langsmith`) in one service; no new datastore, no new
  network dependency on the inference path (tracing is off by default and
  best-effort when on).
- The redaction module (`services/ai-assistant/redaction.py`,
  `safe_log_payload`) is the ready-made transform for the `hide_*` callables /
  anonymizer **if** payload capture is ever turned on. It is already
  adversarially tested (`tests/test_redaction.py`), so the future payload path
  has a tested scrubber to reuse — but under this ADR it is not on the trace
  path, because payloads are dropped wholesale, which is strictly stronger than
  scrubbing.
- Tests to add when the implementation PR lands (per the repo's negative-test
  rule for PHI code): (a) with `LANGSMITH_TRACING` unset, `complete()` /
  `complete_structured()` behave identically and emit no trace; (b) an
  **adversarial** test that plants PHI in `messages`/`system` and the completion
  text, drives the traced path against a fake/stubbed LangSmith client, and
  asserts the outbound trace payload contains **no** raw PHI in any field
  (inputs, outputs, metadata) — the end-to-end scan the `consents` leak taught
  us to write; (c) a LangSmith-outage test proving a trace-emit failure does not
  raise or change the `LLMResult`.
- `.env.example` gains commented, empty `LANGSMITH_*` keys (never a real key —
  the `.env` file is committed; do not add secrets). The `HIDE_*` defaults ship
  `true`.
- Recon `⚠ verify` items resolved 2026-07-16: `LANGSMITH_ENDPOINT` var name
  (= `https://api.smith.langchain.com`), `LANGCHAIN_*` alias status (live
  back-compat, not deprecated; we use `LANGSMITH_*`), SDK/Python floor
  (`langsmith` 0.10.5, `requires_python>=3.10`, via PyPI), and BAA tier (HIPAA
  BAA + self-host = Enterprise-only). Remaining open, needs LangChain sales, not
  a merge blocker for metadata-only: **exact Enterprise BAA contract terms**.
  One PR-time check stays: pin `langsmith>=0.10,<0.11` against the actual
  lockfile when the dependency is added.

## Future: payload capture under a BAA — what changes

When someone needs to see actual prompts/completions in traces (e.g. to debug
the W7 ungrounded-summary hallucination class), the delta is:

- **Compliance precondition (no code):** an executed LangSmith Enterprise BAA,
  **or** a self-hosted / in-VPC LangSmith deployment keeping traces in-cluster.
  Until one exists, payload capture stays off — this is the D13 gate, not a
  code toggle.
- **Config:** flip `LANGSMITH_HIDE_INPUTS`/`OUTPUTS` off and install a real
  redaction layer via `create_anonymizer` or the `hide_*` callables, backed by
  `redaction.redact` / `safe_log_payload` (and, for defense in depth, a
  detector such as Presidio/Comprehend). Even under a BAA, ship redaction, not
  raw payloads — a BAA covers the vendor relationship, it does not make raw PHI
  in traces a good idea.
- **Regression check:** the adversarial "no PHI in the outbound trace" test
  must be re-pointed at the redacting path and proven to still hold before real
  PHI flows — do not assume; confirm (same discipline ADR 0005 applied to the
  PHI-in-logs tests).
