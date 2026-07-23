"""Payer eligibility check (X12 270/271 over the clearinghouse REST shim).

Bounded per ADR 0010 / D4: an explicit (connect, read) timeout, a small retry
budget for transient failures, and an in-process circuit breaker so a payer
outage short-circuits fast instead of pinning intake worker threads (RIV-141).

PHI note: the request URL carries member_id as a query param, so a raw requests
exception message embeds it. This module never propagates str(e); it raises
typed PayerError subclasses whose messages are fixed literals.
"""
import os

import requests

from breaker import (
    CircuitBreaker,
    PayerTimeout,
    PayerUnavailable,
)
from config import settings

PAYER_URL = os.getenv("PAYER_API_URL", "https://edi.example.com/v1/eligibility")
PAYER_API_KEY = os.getenv("PAYER_API_KEY", "")

# Per-worker breaker (see ADR 0010 — deliberately in-process, not redis-shared).
_breaker = CircuitBreaker(
    fail_threshold=settings.payer_breaker_fail_threshold,
    reset_seconds=settings.payer_breaker_reset_seconds,
)


def check(insurance_id: str):
    """
    Query the payer for coverage, bounded by a timeout + retry + circuit breaker.

    Returns {"insurance_id", "active", "raw_status"} on any HTTP response the
    payer returns (including a 4xx such as 404 = inactive coverage). Raises
    PayerBreakerOpen if the circuit is open, PayerTimeout on timeout, or
    PayerUnavailable on connection error / repeated 5xx.
    """
    _breaker.before_call()  # raises PayerBreakerOpen when the circuit is open

    params = {"member_id": insurance_id, "service_type": "30"}
    headers = {"Authorization": f"Bearer {PAYER_API_KEY}"}
    timeout = (settings.payer_connect_timeout_seconds, settings.payer_read_timeout_seconds)

    attempts = settings.payer_max_retries + 1
    last_failure = None  # "timeout" | "unavailable"

    for attempt in range(attempts):
        try:
            resp = requests.get(PAYER_URL, params=params, headers=headers, timeout=timeout)
        except requests.Timeout:
            last_failure = "timeout"
        except requests.RequestException:
            # Any other transport-level failure (connection, DNS, redirects, …).
            # Caught broadly so no raw requests exception — whose message embeds
            # the member_id-bearing URL — can escape untyped (PHI rule 3).
            last_failure = "unavailable"
        else:
            # Only statuses the payer contract defines as a real coverage answer
            # are definitive: 2xx = active, 404 = member-not-found = inactive.
            # Everything else is a dependency/config failure, NOT a coverage
            # denial — mapping a 401/403/429/etc to "inactive" would tell a
            # patient they are uninsured because of our auth key or a rate limit.
            if resp.ok:  # 2xx
                _breaker.record_success()
                return {"insurance_id": insurance_id, "active": True, "raw_status": resp.status_code}
            if resp.status_code == 404:
                _breaker.record_success()
                return {"insurance_id": insurance_id, "active": False, "raw_status": resp.status_code}
            if resp.status_code in (408, 429) or resp.status_code >= 500:
                # Transient — retry within the budget, then fail as unavailable.
                last_failure = "unavailable"
            else:
                # Non-definitive and non-transient (401/403/400/422/…): retrying
                # will not help, so stop now and surface an unavailable result.
                last_failure = "unavailable"
                break
        # fall through here only on a retryable failure; loop retries if budget remains

    # All attempts failed — count one failed call against the breaker and raise typed.
    _breaker.record_failure()
    if last_failure == "timeout":
        raise PayerTimeout("payer timeout")
    raise PayerUnavailable("payer unavailable")
