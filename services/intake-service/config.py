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
    # Intake-side circuit breaker (ADR 0010, adversarial review r4). The timeout
    # above bounds ONE registration's worker-hold; this bounds the *sustained*
    # cost: after this many consecutive unusable answers, verification is skipped
    # without an outbound call (status "pending") until the reset window elapses.
    # Threshold is deliberately below eligibility-service's (5) — intake pays up
    # to 8s per failed call where the payer path pays 3s, so intake should give
    # up sooner.
    eligibility_breaker_fail_threshold = int(
        os.getenv("ELIGIBILITY_BREAKER_FAIL_THRESHOLD", "3")
    )
    eligibility_breaker_reset_seconds = float(
        os.getenv("ELIGIBILITY_BREAKER_RESET_SECONDS", "30")
    )
    # A degraded (no coverage verdict) eligibility answer counts against the
    # breaker only when it held this intake worker for at least this long
    # (adversarial review r5). Rationale: eligibility-service returns HTTP 200
    # with {"active": null, "status": "unknown"} both when its own payer breaker
    # short-circuits — milliseconds, costs intake nothing — and when it burned
    # its whole payer budget on a timing-out payer. Only the second is the
    # sustained cost RIV-088 is about, and latency is what tells them apart.
    # INVARIANT: 0.1s <= this <= eligibility-service's payer connect timeout (1s).
    # Upper bound = the floor cost of a payer attempt that TIMES OUT, so a hanging
    # payer lands on the slow side. Lower bound clears one local HTTP round trip,
    # so eligibility's free short-circuit lands on the fast side. Payer failures
    # that cost nothing (connection refused, a hard 401) also read as fast —
    # correctly: they pin no worker, so they are not the RIV-141 mechanism.
    # Guarded by tests/test_eligibility_budget_alignment.py against both these
    # defaults and the .env.example values a fresh deploy seeds.
    eligibility_degraded_slow_seconds = float(
        os.getenv("ELIGIBILITY_DEGRADED_SLOW_SECONDS", "1")
    )

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
