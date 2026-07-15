# ADR 0005 — ai-assistant LLM provider: Claude on AWS Bedrock

**Status:** Accepted
**Date:** 2026-07-15
**Author:** Riverbend engagement team
**Supersedes:** the vendor decision in ADR 0004 (Decision bullet "Vendor:
Anthropic API direct (not Bedrock)"). Every other guarantee in ADR 0004 —
Bounded, Budgeted, Typed, PHI-silent — is preserved unchanged.

## Context

ADR 0004 chose the Anthropic API directly and explicitly *not* Bedrock. Its
stated reason was pragmatic (SDK pinned to `anthropic==0.72.0` for the local
Python 3.8 toolchain), and it flagged the deeper open item without resolving
it: this is a HIPAA covered entity, so any prompt may carry PHI, yet there was
no signed Business Associate Agreement (BAA) covering the vendor. That is
open-question **D13 / #5** in the debt register — "PHI to a cloud LLM on
standard SaaS ToS, no BAA."

Two things changed:

1. The client has AWS Bedrock access via a **Bedrock bearer API key**
   (`AWS_BEARER_TOKEN_BEDROCK`). Bedrock is HIPAA-eligible **when the AWS
   account has an executed BAA and a BAA-covered region/model is used** — so
   routing the AI assistant through Bedrock-under-BAA is the mechanism that
   *closes* D13, rather than a new instance of it.
2. For the current exercise the assistant runs against **synthetic data only**;
   no real PHI is in scope yet. The BAA precondition is therefore a
   prerequisite for real-PHI traffic (see "Future: real PHI under a BAA"),
   not for landing this plumbing.

The `anthropic` SDK's Bedrock client authenticates with AWS SigV4, not a bearer
token; there is no supported path to feed a bearer key through it. boto3 /
`bedrock-runtime` reads `AWS_BEARER_TOKEN_BEDROCK` natively. The ai-assistant
container runs `python:3.12-slim` (only *local dev* is 3.8), so a current boto3
with bearer support installs cleanly, and the suite runs in a python:3.12
container regardless.

## Decision

- **Provider:** Claude on Amazon Bedrock, called via boto3
  `bedrock-runtime.invoke_model`.
- **Model: `claude-sonnet-4-6`** — the model the engagement's own evaluation
  recommended for the intake assistant
  (`docs/research/llm-eval-sonnet-4-6-vs-gpt-oss-120b.md`, 2026-07-06:
  Sonnet 4.6 on Bedrock over gpt-oss-120B). An earlier draft of this ADR
  defaulted to `claude-haiku-4-5` as a cost floor; that contradicted the eval
  and was corrected before merge. Anthropic models on Bedrock are
  **INFERENCE_PROFILE-only** — the bare foundation-model id
  (`anthropic.claude-sonnet-4-6`) returns `ValidationException` on an on-demand
  invoke, so `BEDROCK_MODEL_ID` must be a region-scoped inference profile
  (default `us.anthropic.claude-sonnet-4-6`; `us.`/`global.` variants confirmed
  ACTIVE on the account via `list-inference-profiles` — match the account +
  `AWS_REGION`). Verified live against the account's Bedrock endpoint: plain
  completion (synthetic prompt, 200 → parsed `LLMResult`, PHI-silent metadata
  log) **and** structured completion (`complete_structured` with a nested
  Pydantic model → validated parse).
- **Auth:** the Bedrock bearer API key in `AWS_BEARER_TOKEN_BEDROCK`, read
  **only** by botocore. It is deliberately never read by `config.py` or any app
  code, so it cannot land in a config object, a log line, or an exception
  message.
- **Minimal blast radius on a landmine file:** the boto3 call sits behind a thin
  adapter (`_BedrockClient` / `_BedrockMessages` in `llm_client.py`) that keeps
  the exact `client.messages.create(**kwargs)` seam the wrapper was built
  around. The budget gate, PHI-silent logging, `_result_from_response`, and the
  structured-output path are unchanged; the four ADR-0004 guarantees hold:
  - **Bounded** — botocore `Config(connect_timeout, read_timeout, retries)`
    replaces the httpx timeout + SDK retries (`max_attempts = retries + 1`,
    since botocore counts the first try).
  - **Budgeted** — the fully-local, byte-based upper-bound gate (ADR 0004
    amendment) is provider-agnostic and runs before any boto3 call, so an
    over-budget, possibly-PHI payload still never crosses the boundary.
  - **Typed failures** — botocore `ClientError` / `BotoCoreError` are mapped to
    `LLMConfigError` (bad model/auth/request: `AccessDeniedException`,
    `ValidationException`, `ResourceNotFoundException`, 401/403/404) and
    `LLMUnavailable` (throttling/5xx/connection after retries). Exception
    messages carry error-code/status metadata only.
  - **PHI-silent** — unchanged; still metadata-only logging.
- **Pricing is fail-closed per model** (adversarial review, PR #5). The
  worst-case-cost gate and cost telemetry price the *resolved*
  `BEDROCK_MODEL_ID` from a lookup table (`_MODEL_PRICING`, keyed by
  foundation-model id with the inference-profile region prefix stripped;
  sonnet-4-6: $3 / $15 per MTok). A model with no entry — and no explicit
  `LLM_PRICE_PER_MTOK_INPUT`/`OUTPUT` override pair — refuses the call with
  `LLMConfigError` before any egress, instead of silently pricing a possibly
  more expensive model as Sonnet and hollowing out the budget cap. Worst case
  at the default caps (20k input tokens + 2,048 max output) is ≈ $0.09, still
  well under the $0.50 per-request gate.
- **Structured output** stays `extra_body={"output_config": {"format": ...}}`,
  folded into the Bedrock request body and validated with Pydantic. Live
  verification surfaced a latent bug (present since ADR 0004 — it predates the
  provider switch): the structured-output API requires **every object node** in
  the schema to carry an explicit `additionalProperties: false`, which
  Pydantic's `model_json_schema()` never emits — the request is rejected with
  `ValidationException`. `llm_client._strict_schema` now walks the schema
  (including nested `$defs`) and pins it; regression test proven to fail
  against the pre-fix code.

## Consequences

- The `anthropic` SDK dependency is replaced by `boto3` in the service and dev
  requirements. Local `pip install` on Python 3.8 no longer works for this
  service; the container and CI (python:3.12) are unaffected.
- The committed `.env` must never carry a real bearer key; the old committed
  `.env` is still in git history and remains on the rotation runbook
  (docs/debt-log.md) — unchanged open debt from ADR 0004.
- The ROI authorization gap (D12) is still a hard prerequisite: no AI feature
  may source patient data through roi-service until authorization enforcement
  exists — provider choice does not change this.
- **Observability follow-up:** LangSmith tracing is planned once this
  integration is merged. The single provider seam
  (`_BedrockMessages.create`) is the intended wrap point, so tracing lands as
  an additive decorator around one method — no change to the budget gate or
  error mapping. Constraint carried forward from the PHI-silent guarantee:
  traces must capture **metadata only** (model, token counts, cost, latency,
  request id) unless/until LangSmith is covered for PHI — prompt/completion
  payload capture stays off by default.

## Future: real PHI under a BAA — what changes

When an executed AWS BAA is in place and the assistant handles real encounter
PHI, the **code delta is small** because the wrapper was built PHI-ready. The
work is mostly configuration and operations:

- **Config / ops (no code change):**
  - Point `AWS_REGION` + the AWS account at the **BAA-covered** region, and set
    `BEDROCK_MODEL_ID` to a model on the BAA-eligible list for that region
    (the exact ID may need a version suffix or a cross-region inference-profile
    prefix, e.g. `us.anthropic.claude-sonnet-4-6` — read it from the Bedrock
    console for the target account).
  - Move the bearer key out of the committed-`.env` lineage into a real secrets
    manager, and rotate the historically-committed values (existing debt).
- **Bedrock invocation logging — the one genuine new risk.** Bedrock *model
  invocation logging*, if enabled on the account, captures full request/response
  bodies (i.e. prompts and completions = PHI) to CloudWatch/S3. Before real PHI
  flows, either disable it for this account or route it to a BAA-covered,
  encrypted (CMK), access-controlled destination with a defined retention
  policy. This is the Bedrock analog of the repo's existing "PHI in logs" (D1)
  landmine and must be checked explicitly — it is not visible in this codebase.
- **Encryption / key management (config):** use a customer-managed KMS key for
  any Bedrock-side storage the account enables.
- **De-identification (only if an export/BA-subprocessor path is added):** the
  D14 fake-de-identification gap (dropping only `name`, leaving 17/18
  Safe-Harbor identifiers) is unrelated to provider choice, but any future path
  that ships an "anonymized" payload must be a real Safe-Harbor/Expert-
  Determination de-identification, not the current one-field strip.
- **Wrapper code:** effectively no change. The budget gate and PHI-silent
  logging already assume PHI; flipping from synthetic to real data needs no new
  guardrail here. Confirm (do not assume) the PHI-in-logs tests still pass as a
  regression check before the switch.
