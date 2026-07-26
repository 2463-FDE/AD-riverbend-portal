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
    # Clamped to a floor, mirroring the gateway's singleflight lock TTL
    # (gateway/config.py): 0 is what an operator would plausibly set to "turn this
    # check off", and it would do the opposite — every degraded answer, including
    # eligibility's free short-circuit, becomes a breaker failure and verification
    # goes off for everyone. "Off" here is a large number, not zero. An override can
    # only raise the threshold, and startup never has to fail.
    _degraded_slow_floor = 0.1
    eligibility_degraded_slow_seconds = max(
        float(os.getenv("ELIGIBILITY_DEGRADED_SLOW_SECONDS", "1")), _degraded_slow_floor
    )
    # The same rule for an answer that DID carry a coverage verdict (adversarial
    # review r6): a definitive active/inactive that held this worker for at least
    # this long counts against the breaker too. The verdict is still returned to
    # the caller — usefulness and dependency health are separate questions — but a
    # payer that degrades without going dark (one attempt read-times-out, the retry
    # answers) otherwise keeps every registration paying seconds forever, which is
    # RIV-088 in its partial-outage form.
    # INVARIANT: ELIGIBILITY_DEGRADED_SLOW_SECONDS (1s) <= this <=
    # eligibility-service's PAYER_READ_TIMEOUT_SECONDS (2s); the defaults keep it
    # strictly greater.
    # The upper bound is the FLOOR of the retried band, and that anchor is the
    # whole game. A retry only happens after the first attempt's read timeout has
    # burned in full, so the cheapest retried answer costs `read_timeout` while its
    # ceiling (~2*read + 2*connect) is far higher. An earlier draft of this fix
    # anchored on one healthy attempt's CEILING (connect + read = 3s) and so picked
    # 4s — at or above the realistic TOP of the retried band, which made the check
    # dead code: a payer degrading exactly as described answered in 2-4s and still
    # counted as healthy. Anchor on the floor instead and every retried answer
    # counts. The lower bound keeps a verdict's leash longer than a no-verdict
    # reply's: a real answer is worth more than a shrug.
    # Cost of the tight bound, accepted: a SINGLE attempt that is slow because the
    # TCP connect dragged (connect up to 1s + a fast read) can also cross 2s and be
    # counted unhealthy. That is not a misclassification worth widening the band
    # for — 2s+ of worker-hold per registration is the RIV-088 symptom itself,
    # whichever phase spent it.
    # Guarded by tests/test_eligibility_budget_alignment.py against both these
    # defaults and the .env.example values a fresh deploy seeds. Clamped to the
    # degraded threshold for the same reason as above: a verdict must never be
    # judged more harshly than a shrug.
    eligibility_slow_answer_seconds = max(
        float(os.getenv("ELIGIBILITY_SLOW_ANSWER_SECONDS", "2")),
        eligibility_degraded_slow_seconds,
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
