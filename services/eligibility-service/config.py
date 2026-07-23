"""eligibility-service configuration. Environment-driven; sensible compose defaults."""
import os


class Settings:
    service_name = "eligibility-service"
    port = int(os.getenv("PORT", "8072"))
    environment = os.getenv("ENVIRONMENT", "development")
    log_level = os.getenv("LOG_LEVEL", "INFO")

    # Clearinghouse / payer REST shim that fronts the X12 270/271 exchange.
    payer_api_url = os.getenv("PAYER_API_URL", "https://edi.example.com/v1/eligibility")
    payer_api_key = os.getenv("PAYER_API_KEY", "")
    payer_name = os.getenv("PAYER_NAME", "edi.example.com")

    # Bound the payer call (ADR 0010 / D4). Timeouts are (connect, read) seconds;
    # retries cover only timeout/connection/5xx (never a 4xx). Defaults are
    # conservative starting points pending the real clearinghouse SLA.
    payer_connect_timeout_seconds = float(os.getenv("PAYER_CONNECT_TIMEOUT_SECONDS", "2"))
    payer_read_timeout_seconds = float(os.getenv("PAYER_READ_TIMEOUT_SECONDS", "3"))
    payer_max_retries = int(os.getenv("PAYER_MAX_RETRIES", "1"))
    payer_breaker_fail_threshold = int(os.getenv("PAYER_BREAKER_FAIL_THRESHOLD", "5"))
    payer_breaker_reset_seconds = float(os.getenv("PAYER_BREAKER_RESET_SECONDS", "30"))


settings = Settings()
