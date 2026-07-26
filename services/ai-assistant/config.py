"""ai-assistant configuration. Environment-driven; sensible compose defaults."""
import os


class Settings:
    service_name = "ai-assistant"
    port = int(os.getenv("PORT", "8077"))
    environment = os.getenv("ENVIRONMENT", "development")
    log_level = os.getenv("LOG_LEVEL", "INFO")

    # AWS Bedrock (see ADR 0009 — supersedes ADR 0004's "Anthropic direct").
    # Auth is a Bedrock bearer API key, which boto3/botocore reads directly from
    # the AWS_BEARER_TOKEN_BEDROCK environment variable — it is deliberately NOT
    # read here, so it can never land in a config object, a log line, or an
    # exception message. Region has a default so the boto3 client can be
    # constructed in CI's keyless import smoke without a real key.
    # Service-to-service auth: the gateway attaches this as X-Internal-Auth on
    # every proxied call; /intake-instructions refuses requests without it.
    # Defense in depth behind the compose topology (the service is not
    # host-published) — and FAIL-CLOSED: empty/placeholder means every call is
    # refused, never "auth off" (the PR #5 round-5 lesson: guards must hold in
    # the default fresh-deploy state). Ships EMPTY in .env.example; generate
    # with `openssl rand -hex 32`.
    ai_proxy_shared_secret = os.getenv("AI_PROXY_SHARED_SECRET", "")

    aws_region = os.getenv("AWS_REGION", "us-east-1")
    # claude-sonnet-4-6 is the model the engagement's eval recommended for the
    # intake assistant (docs/research/llm-eval-sonnet-4-6-vs-gpt-oss-120b.md;
    # ADR 0009). On Bedrock it is INFERENCE_PROFILE-only (the bare
    # anthropic.claude-sonnet-4-6 foundation-model id is not invokable
    # on-demand — it returns ValidationException). The default is the US
    # cross-region inference profile; profile ids are REGION-SCOPED
    # (us./eu./global. ...), so override BEDROCK_MODEL_ID to match your account
    # + region (see Bedrock console -> Cross-region inference). Pricing for the
    # cost gate FAILS CLOSED per model: a model with no entry in
    # llm_client._MODEL_PRICING refuses calls unless BOTH price overrides
    # below are set — it is never silently priced as Sonnet.
    bedrock_model_id = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
    # Explicit per-model pricing override (USD per million tokens) for models
    # absent from llm_client._MODEL_PRICING. Set both or neither — a half-set
    # pair is rejected as a config error rather than half-defaulted.
    llm_price_per_mtok_input = (
        float(os.environ["LLM_PRICE_PER_MTOK_INPUT"])
        if "LLM_PRICE_PER_MTOK_INPUT" in os.environ
        else None
    )
    llm_price_per_mtok_output = (
        float(os.environ["LLM_PRICE_PER_MTOK_OUTPUT"])
        if "LLM_PRICE_PER_MTOK_OUTPUT" in os.environ
        else None
    )

    # Outbound call discipline — deliberately the opposite of the D4 pattern
    # (eligibility-service's unbounded payer call). Every LLM call is bounded.
    llm_connect_timeout_seconds = float(os.getenv("LLM_CONNECT_TIMEOUT_SECONDS", "5"))
    llm_read_timeout_seconds = float(os.getenv("LLM_READ_TIMEOUT_SECONDS", "30"))
    llm_max_retries = int(os.getenv("LLM_MAX_RETRIES", "3"))

    # Budget guardrails, enforced entirely LOCALLY before any request is sent.
    # No vendor call participates in the preflight gate: token/cost budget is
    # checked against a deterministic local estimate so a PHI-bearing,
    # over-budget prompt never crosses the trust boundary. Real token counts
    # come back on the completion response as post-approval telemetry.
    llm_max_input_tokens = int(os.getenv("LLM_MAX_INPUT_TOKENS", "20000"))
    llm_max_output_tokens = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "2048"))
    llm_max_cost_per_request_usd = float(os.getenv("LLM_MAX_COST_PER_REQUEST_USD", "0.50"))
    # The token gate uses a GUARANTEED local upper bound on input tokens — the
    # UTF-8 byte length, which a byte-level BPE tokenizer can never exceed
    # (llm_client.max_input_tokens). There is deliberately NO ratio/estimate
    # knob here: a tunable heuristic could under-count a dense (all-digit,
    # high-entropy, multibyte-unicode) payload and let over-budget PHI egress.
    # The bound is conservative for prose (~1 token per ~4 bytes), so raise
    # LLM_MAX_INPUT_TOKENS if legitimate prompts are refused.
    # Independent gross-size backstop (defense-in-depth), also local.
    llm_max_input_chars = int(os.getenv("LLM_MAX_INPUT_CHARS", str(llm_max_input_tokens * 4)))

    # --- visit-chat: the eligibility dependency (ADR 0011) -------------------
    # ai-assistant's own hop to eligibility-service. Bounded and breakered from
    # the start: the D4 lesson (RIV-088/RIV-141) is about the CALLER's worker
    # thread, so a new caller inherits the problem, not the fix.
    eligibility_url = os.getenv("ELIGIBILITY_URL", "http://eligibility-service:8072")
    # Hard cap on how long one chat turn can be held by the dependency. Matches
    # intake's ELIGIBILITY_TIMEOUT_SECONDS: it must exceed eligibility-service's
    # own worst-case payer budget ((connect + read) * (1 + retries) = 6s with the
    # shipped defaults), or this client would time out while the downstream is
    # still doing bounded, useful work — the inner-budget-inside-outer rule from
    # ADR 0010.
    ai_eligibility_timeout_seconds = float(os.getenv("AI_ELIGIBILITY_TIMEOUT_SECONDS", "8"))
    ai_eligibility_breaker_fail_threshold = int(
        os.getenv("AI_ELIGIBILITY_BREAKER_FAIL_THRESHOLD", "3")
    )
    ai_eligibility_breaker_reset_seconds = float(
        os.getenv("AI_ELIGIBILITY_BREAKER_RESET_SECONDS", "30")
    )
    # Breaker health is "usable AND cheap", on two separate latency thresholds —
    # the same rule intake landed on across adversarial rounds r5/r6 (see
    # services/intake-service/config.py for the full derivation; it is not
    # restated here). Short version: eligibility-service returns the identical
    # shaped 200 {"active": null, "status": "unknown"} when its payer breaker
    # short-circuits (free) and when it burned its whole payer budget on a hanging
    # payer (expensive), so only LATENCY separates them. Counting every shaped 2xx
    # as healthy leaves this breaker closed during the exact outage it guards.
    #
    # INVARIANT: 0.1 <= degraded <= slow_answer <= eligibility-service's
    # PAYER_READ_TIMEOUT_SECONDS (2s). The upper bound is the FLOOR of the retried
    # band, not the ceiling of a healthy attempt — anchoring higher makes the check
    # dead code for a payer that degrades but keeps answering (the r6 no-op).
    # Both are clamped rather than validated at startup, mirroring intake and the
    # gateway's singleflight lock TTL: 0 is what an operator would plausibly set to
    # "turn this off", and it would do the opposite (every answer unhealthy, so the
    # circuit never closes). "Off" here is a large number, never zero.
    _ai_degraded_slow_floor = 0.1
    ai_eligibility_degraded_slow_seconds = max(
        float(os.getenv("AI_ELIGIBILITY_DEGRADED_SLOW_SECONDS", "1")),
        _ai_degraded_slow_floor,
    )
    ai_eligibility_slow_answer_seconds = max(
        float(os.getenv("AI_ELIGIBILITY_SLOW_ANSWER_SECONDS", "2")),
        ai_eligibility_degraded_slow_seconds,
    )

    # --- visit-chat: transcript bounds (ADR 0011 §3) ------------------------
    # The gateway owns visit memory and enforces these at the edge; ai-assistant
    # applies them again on the inbound side so the caps hold even if a future
    # caller forgets. Both are PHI bounds as much as token bounds: an unbounded
    # transcript in Redis is a PHI dump whose retention policy is "never".
    ai_visit_max_turns = int(os.getenv("AI_VISIT_MAX_TURNS", "12"))
    ai_visit_max_message_chars = int(os.getenv("AI_VISIT_MAX_MESSAGE_CHARS", "1000"))


settings = Settings()
