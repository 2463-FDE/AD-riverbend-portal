"""Gateway configuration. Environment-driven; sensible compose defaults."""
import os


class Settings:
    service_name = "gateway"
    environment = os.getenv("ENVIRONMENT", "development")
    log_level = os.getenv("LOG_LEVEL", "INFO")

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")

    db_host = os.getenv("DB_HOST", "postgres")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "riverbend")
    db_user = os.getenv("DB_USER", "riverbend_app")
    db_password = os.getenv("DB_PASSWORD", "")

    # downstream services
    intake_url = os.getenv("INTAKE_URL", "http://intake-service:8071")
    eligibility_url = os.getenv("ELIGIBILITY_URL", "http://eligibility-service:8072")
    records_url = os.getenv("RECORDS_URL", "http://records-service:8073")
    scheduling_url = os.getenv("SCHEDULING_URL", "http://scheduling-service:8074")
    interop_url = os.getenv("INTEROP_URL", "http://interop-service:8075")
    roi_url = os.getenv("ROI_URL", "http://roi-service:8076")
    ai_assistant_url = os.getenv("AI_ASSISTANT_URL", "http://ai-assistant:8077")

    # Service-to-service auth: attached as X-Internal-Auth on every /ai proxy
    # call; ai-assistant refuses requests without it (fail-closed on both
    # sides — an empty value here just means the downstream rejects the call).
    # Never logged. Ships EMPTY in .env.example; generate with
    # `openssl rand -hex 32` and set the same value for both services.
    ai_proxy_shared_secret = os.getenv("AI_PROXY_SHARED_SECRET", "")

    # LLM calls are seconds-slow by nature; this bounds the /ai fan-out
    # explicitly (never unbounded — that is the D4/RIV-088 pattern) while
    # allowing more headroom than the 30s default used for the CRUD services.
    ai_read_timeout_seconds = float(os.getenv("AI_READ_TIMEOUT_SECONDS", "60"))

    @property
    def db_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
