"""ai-assistant configuration. Environment-driven; sensible compose defaults."""
import os


class Settings:
    service_name = "ai-assistant"
    port = int(os.getenv("PORT", "8077"))
    environment = os.getenv("ENVIRONMENT", "development")
    log_level = os.getenv("LOG_LEVEL", "INFO")

    # AWS Bedrock (see ADR 0005 — supersedes ADR 0004's "Anthropic direct").
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
    # ADR 0005). On Bedrock it is INFERENCE_PROFILE-only (the bare
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


settings = Settings()
