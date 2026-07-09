"""ai-assistant configuration. Environment-driven; sensible compose defaults."""
import os


class Settings:
    service_name = "ai-assistant"
    port = int(os.getenv("PORT", "8077"))
    environment = os.getenv("ENVIRONMENT", "development")
    log_level = os.getenv("LOG_LEVEL", "INFO")

    # Anthropic API. Key comes from .env (never committed with a real value);
    # empty default keeps imports working in CI's keyless smoke test.
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")

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
