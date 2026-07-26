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

    # Single-flight coalescing of CONCURRENT identical cache misses (ADR 0007,
    # closes deferred gap #4). The cache collapses *sequential* retries, but two
    # simultaneous identical submits (a double-click, a browser retry, many staff
    # submitting the same closed-vocabulary facts at once) can both miss and both
    # fan out before the first result is cached. A Redis SET NX lock elects one
    # winner to make the paid call; concurrent losers wait up to
    # AI_SINGLEFLIGHT_WAIT_SECONDS (polling every AI_SINGLEFLIGHT_POLL_SECONDS)
    # for the winner's cached result, then return a controlled 429 retry rather
    # than a second paid call. The lock TTL must outlive the slowest fan-out so a
    # crashed winner's lock self-clears (never wedges the key) — it defaults just
    # above the AI read timeout.
    ai_singleflight_wait_seconds = float(os.getenv("AI_SINGLEFLIGHT_WAIT_SECONDS", "2.0"))
    ai_singleflight_poll_seconds = float(os.getenv("AI_SINGLEFLIGHT_POLL_SECONDS", "0.1"))
    # The lock TTL MUST exceed the read timeout, or a still-running winner's lock
    # can expire mid-fan-out, a second winner acquires the same key, and the two
    # overlap — the stale-owner race (Codex PR #7 round 13). Ownership-checked
    # release stops A from deleting B's lock, but keeping the TTL above the
    # fan-out bound stops the overlap from arising at all. So the configured value
    # is CLAMPED to a safe floor (read timeout + 15s headroom): an operator
    # override can only RAISE it, never set it below the fan-out bound — a
    # misconfiguration cannot reopen the race, and startup never has to fail.
    _ai_singleflight_lock_ttl_floor = int(ai_read_timeout_seconds) + 15
    ai_singleflight_lock_ttl_seconds = max(
        int(os.getenv("AI_SINGLEFLIGHT_LOCK_TTL_SECONDS", str(_ai_singleflight_lock_ttl_floor))),
        _ai_singleflight_lock_ttl_floor,
    )

    # --- visit-chat (ADR 0011) ---------------------------------------------
    # The chat endpoint gets its OWN per-user request quota, in its own Redis
    # namespace (ratelimit:aichat:*), and higher than the one-shot endpoint's: a
    # conversation is many turns where a checklist is one submit. Separate
    # namespaces so neither endpoint can exhaust the other's quota. The aggregate
    # SPEND ceiling above is shared by both on purpose — it bounds dollars per
    # tenant per day, and splitting it would silently raise the real ceiling.
    ai_chat_rate_limit_per_minute = int(os.getenv("AI_CHAT_RATE_LIMIT_PER_MINUTE", "20"))
    ai_chat_rate_limit_per_day = int(os.getenv("AI_CHAT_RATE_LIMIT_PER_DAY", "400"))

    # Visit-scoped memory. The TTL is a RETENTION policy for PHI-adjacent state
    # (a payer member id + a structured coverage verdict), not just a cache
    # setting: it is the upper bound on how long that state survives in a Redis
    # instance this deployment has not hardened (debt-log D3b). Sliding — every
    # turn refreshes it — so 30 minutes is "30 minutes after the last turn",
    # comfortably longer than a check-in and far shorter than a shift.
    # Clamped to a floor: 0 is what an operator would plausibly set to "turn
    # visit memory off", and it would do something worse than that — the route
    # still mints and returns a visit_id, but nothing is stored, so the clerk's
    # NEXT turn gets a hard 404 "visit not found" instead of degrading to a
    # stateless conversation. "Off" is not reachable through this knob.
    ai_visit_ttl_seconds = max(int(os.getenv("AI_VISIT_TTL_SECONDS", "1800")), 60)
    # Hard caps on what one visit can hold. Both bound token spend AND the size of
    # a hypothetical exposure; the store truncates to these rather than trusting
    # callers (security.visit_memory_save).
    # Floors for the same reason (and matching ai-assistant's copies): 0 turns
    # or 0 chars silently 422s every message, and a negative value crashes
    # ai-assistant at import via pydantic's max_length.
    ai_visit_max_turns = max(int(os.getenv("AI_VISIT_MAX_TURNS", "12")), 2)
    ai_visit_max_message_chars = max(
        int(os.getenv("AI_VISIT_MAX_MESSAGE_CHARS", "1000")), 100
    )
    # The per-visit lock reuses the single-flight lock TTL deliberately, rather
    # than adding a knob: it is already clamped to a floor above the AI read
    # timeout, which is exactly the property a lock around this fan-out needs (a
    # TTL under the fan-out bound would let a second turn overlap the first).

    @property
    def db_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
