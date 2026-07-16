# ADR 0004 — ai-assistant service and production LLM client wrapper

**Status:** Accepted (vendor decision superseded by ADR 0005, 2026-07-15)
**Date:** 2026-07-05
**Author:** Riverbend engagement team

> **Note (2026-07-15):** the "Vendor: Anthropic API direct (not Bedrock)"
> decision below is superseded by **ADR 0005** — the assistant now calls Claude
> on AWS Bedrock (bearer key via boto3), which closes debt item D13 once an AWS
> BAA is in place. All four guarantees (Bounded/Budgeted/Typed/PHI-silent) are
> preserved. This ADR is kept as the historical record.

## Context

The board has asked for an AI assistant that drafts patient-friendly intake
instructions. The prior contractor shipped (and removed before handoff) an
`ai-orchestrator` service whose Bedrock client had no timeout, no retry
policy, no token or cost ceiling, and a placeholder de-identification step —
exactly the failure modes this codebase already suffers from elsewhere (the
D4 no-timeout eligibility call froze intake for 20 minutes; RIV-141).

This is a HIPAA covered entity. Any LLM integration must assume prompts can
contain PHI and that the existing compliance posture (plaintext PHI, PHI in
logs, no ROI authorization — ARCHITECTURE.md §7) offers no safety net.

## Decision

- Ship the **wrapper before the feature**: a new `services/ai-assistant/`
  service (port 8077) that follows the standard per-service layout and exposes
  only `/healthz`. Feature endpoints come later, routed through the gateway
  like every other service.
- The wrapper (`llm_client.py`) enforces four guarantees on every call:
  1. **Bounded** — connect/read timeouts and SDK-managed retries with
     exponential backoff (`timeout=httpx.Timeout(...)`, `max_retries`);
  2. **Budgeted** — a pre-flight token count and worst-case cost estimate;
     calls exceeding `LLM_MAX_INPUT_TOKENS` or `LLM_MAX_COST_PER_REQUEST_USD`
     are refused before any request is sent;
  3. **Typed failures** — `LLMBudgetExceeded` / `LLMUnavailable` /
     `LLMConfigError` / `LLMResponseError`, never the repo's
     `{"error": str(e)}` 200-OK pattern;
  4. **PHI-silent** — prompts and completions never appear in logs or
     exception messages; metadata only (model, tokens, cost, latency,
     request id). Companion helper `redaction.py` is the standard way to log
     payload-shaped data anywhere in the repo (docs/phi-logging-policy.md).
- **Vendor:** Anthropic API direct (not Bedrock), model `claude-opus-4-8`,
  key via `ANTHROPIC_API_KEY`. SDK pinned at `anthropic==0.72.0` — the newest
  release compatible with the local Python 3.8 toolchain; structured output
  is requested via `extra_body={"output_config": {"format": ...}}` and
  validated manually with Pydantic. When the local toolchain reaches 3.9+,
  upgrade the pin and switch to `client.messages.parse`.
- Per ADR 0001 (no shared Python lib), `redaction.py` is copy-pasted into
  consuming services; a parity test (`tests/test_redaction.py`) guards drift.

## Consequences

- Every future AI feature inherits cost ceilings, bounded latency, and
  PHI-silent logging for free — and must justify any bypass.
- Per-request cost is capped (default $0.50), so a runaway prompt cannot
  produce an unbounded bill.
- The API key lives in the environment; the committed `.env` must never carry
  a real value (open debt item — docs/debt-log.md).
- Copy-paste module reuse continues (ADR 0001), with parity tests as the
  drift control.
- The ROI authorization gap (D12) remains a hard prerequisite: no AI feature
  may source patient data through roi-service until authorization enforcement
  exists.

## Amendment — 2026-07-08 (PR #2 review)

The original **Budgeted** guarantee (Decision 2) was implemented by calling
`client.messages.count_tokens()` to get an exact input-token count, then
enforcing the token/cost caps on the result. `count_tokens` is itself an SDK
request that egresses the full `messages` payload to the vendor. A prompt under
`LLM_MAX_INPUT_CHARS` but over the token/cost budget therefore left the trust
boundary **before** being rejected — contradicting "refused before any request
is sent" and disclosing a possibly PHI-bearing payload.

The gate is now **fully local** and enforced against a **guaranteed upper
bound**, not an estimate. `max_input_tokens` returns the UTF-8 byte length of
the prompt (plus a small fixed per-message framing allowance). Claude's
byte-level BPE tokenizer keeps all 256 single-byte tokens in vocabulary, so no
input can ever produce more tokens than it has bytes — the byte length can only
over-count, never under-count, for **any** input including all-digit,
high-entropy, and multibyte-unicode payloads. The token and worst-case-cost
caps are checked against this bound before any SDK call. No vendor call — not
even `count_tokens` — participates in the preflight; the completion `create`
call is the sole egress, and its response `usage` supplies the real token count
as post-approval telemetry (logging + cost).

An earlier revision of this fix (commit `0d303ed`) used a tunable heuristic
(`chars ÷ LLM_CHARS_PER_TOKEN_ESTIMATE`, default 3.0). A subsequent adversarial
review (Codex) correctly flagged that a heuristic is not a hard bound: a dense
payload can tokenize tighter than the ratio, so an over-budget prompt could
still pass and egress. The heuristic and its loosening env knob were removed in
favor of the byte-based bound above.

Trade-off: the bound is conservative for prose (~1 token per ~4 bytes), so the
usable prompt size is smaller than the nominal `LLM_MAX_INPUT_TOKENS` for
natural-language input. Raise `LLM_MAX_INPUT_TOKENS` if legitimate prompts are
refused; there is intentionally no knob that loosens the bound itself. The local
char cap (`LLM_MAX_INPUT_CHARS`) remains as an independent gross-size backstop.
Decision 2 above is preserved as the original record; this amendment is the
current behavior.
