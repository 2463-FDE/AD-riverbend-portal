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

    # Budget guardrails, enforced before any request is sent.
    llm_max_input_tokens = int(os.getenv("LLM_MAX_INPUT_TOKENS", "20000"))
    llm_max_output_tokens = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "2048"))
    llm_max_cost_per_request_usd = float(os.getenv("LLM_MAX_COST_PER_REQUEST_USD", "0.50"))
    # Local preflight cap, checked BEFORE any SDK call. count_tokens is itself a
    # network request that egresses the full payload, so a grossly oversized
    # prompt must be rejected locally first (~4 chars/token is a conservative
    # English estimate; the exact count_tokens result still enforces the real
    # token cap for prompts that pass this gate).
    llm_max_input_chars = int(os.getenv("LLM_MAX_INPUT_CHARS", str(llm_max_input_tokens * 4)))


settings = Settings()
