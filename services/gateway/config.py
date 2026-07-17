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

    # Abuse control for the paid LLM fan-out (Codex PR #7 round 6). The /ai
    # route only proves a caller is logged in, and sessions never expire, so
    # without a quota one leaked/stale token or a bored user could loop the
    # endpoint and drive unbounded Bedrock spend + worker starvation. The
    # gateway consumes a per-user fixed-window Redis counter before fan-out:
    # a short minute window absorbs double-clicks/retries, a per-user daily cap
    # bounds one user's volume. Non-secret; tune per environment.
    ai_rate_limit_per_minute = int(os.getenv("AI_RATE_LIMIT_PER_MINUTE", "10"))
    ai_rate_limit_per_day = int(os.getenv("AI_RATE_LIMIT_PER_DAY", "200"))

    # Aggregate spend ceiling (ADR 0007). Per-user caps alone do not bound total
    # spend — N users * per-user cap is still unbounded in N. This is a single
    # global daily counter over *paid* fan-outs (incremented only on a cache
    # miss, so a leaked token cannot exhaust it with rejected requests). <=0
    # disables the aggregate ceiling. Sized ~= expected_active_staff * per-user.
    ai_rate_limit_global_per_day = int(os.getenv("AI_RATE_LIMIT_GLOBAL_PER_DAY", "2000"))

    # Response cache for the closed-vocabulary intake-instructions endpoint
    # (ADR 0007). Identical intake-fact bodies map to the same visit-prep
    # checklist, so caching cuts both Bedrock spend and latency and collapses
    # retry/double-click storms into one paid call. Keyed by a hash of the
    # request body (never PHI — the schema is enum/bool only); the cached value
    # is template text, not PHI. TTL bounds staleness against catalog/template
    # deploys. <=0 disables caching. Best-effort: a cache backend error degrades
    # to a normal paid call, never an outage.
    ai_cache_ttl_seconds = int(os.getenv("AI_CACHE_TTL_SECONDS", "300"))

    @property
    def db_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
