"""intake-service configuration. Environment-driven; sensible compose defaults."""
import os


class Settings:
    service_name = "intake-service"
    port = int(os.getenv("PORT", "8071"))
    environment = os.getenv("ENVIRONMENT", "development")
    log_level = os.getenv("LOG_LEVEL", "INFO")

    db_host = os.getenv("DB_HOST", "postgres")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "riverbend")
    db_user = os.getenv("DB_USER", "riverbend_app")
    db_password = os.getenv("DB_PASSWORD", "")

    # downstream eligibility verification (called from /intake). Bounded per
    # ADR 0010 — this timeout is a hard cap on intake worker-hold and is the
    # real RIV-141 guard: a slow/hung payer can no longer freeze intake.
    eligibility_url = os.getenv("ELIGIBILITY_URL", "http://eligibility-service:8072")
    # Must exceed eligibility-service's worst-case payer budget (6s) with margin,
    # so intake receives its graceful "unknown"/"inactive" answer rather than
    # timing out first and abandoning a still-running downstream call (ADR 0010;
    # guarded by tests/test_eligibility_budget_alignment.py).
    eligibility_timeout_seconds = float(os.getenv("ELIGIBILITY_TIMEOUT_SECONDS", "8"))

    # payer settings kept for parity with the legacy module; the real X12 270/271
    # round-trip is owned by eligibility-service.
    payer_api_url = os.getenv("PAYER_API_URL", "https://edi.example.com/v1/eligibility")
    payer_api_key = os.getenv("PAYER_API_KEY", "")

    @property
    def db_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
