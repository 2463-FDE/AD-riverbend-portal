"""
Bounded client for eligibility-service, used by POST /visit-chat (ADR 0011 §4).

Same topology intake has always had (service → service, over the compose
network), and the same discipline PR #11 established for that hop:

  * an explicit timeout on every call, so one turn's worker-hold is capped;
  * an in-process circuit breaker, so the SUSTAINED cost of a bad dependency is
    capped too (a chat invites retries — the per-call timeout alone would let a
    degraded payer charge every turn the full budget);
  * never `str(e)` and never the insurance id in a log line. The request URL
    carries `?insurance_id=<member id>` and httpx embeds the failing URL in its
    exception message, which is exactly how the PHI leak PR #11 closed happened
    (docs/phi-logging-policy.md rules 2-3).

This module answers ONE question for the caller — "what does the payer say about
this coverage, and is the dependency worth calling again?" — and deliberately
projects the downstream body down to a fixed field set. The projection is a PHI
control, not tidiness: eligibility-service's body also carries `insurance_id` and
(on a degraded answer) an `error` string, and the caller persists what it gets
into visit memory. Dropping both here means neither can reach Redis by accident.
"""
import time
from typing import Any

import httpx

from breaker import CircuitBreaker, EligibilityBreakerOpen
from config import settings
from logging_config import configure

log = configure(settings.service_name)

# Module-level so breaker state is shared by every turn this worker serves (that
# is the point — see ADR 0010 on per-worker state). Tests pin their own instance.
_breaker = CircuitBreaker(
    fail_threshold=settings.ai_eligibility_breaker_fail_threshold,
    reset_seconds=settings.ai_eligibility_breaker_reset_seconds,
)


def _degraded(status: str, reason: str) -> dict[str, Any]:
    """A no-verdict answer, in the projected shape.

    `active` is None, never False: an outage, a timeout, or an open circuit must
    never render as "this patient has no coverage" (ADR 0010's tri-state rule,
    carried into the words a clerk reads — ADR 0011 §5).
    """
    return {
        "active": None,
        "status": status,
        "payer": None,
        "raw_status": None,
        "checked_at": None,
        "reason": reason,
    }


def check_coverage(insurance_id: str) -> dict[str, Any]:
    """Look up coverage for `insurance_id`. Never raises.

    Returns the projected verdict dict — `active` (True/False/None), `status`
    (`active` / `inactive` / `unknown` / `pending`), `payer`, `raw_status`,
    `checked_at`, `reason`. A caller renders words from `status` alone and must
    never infer a denial from a falsy `active` (None is falsy and means unknown).
    """
    try:
        _breaker.before_call()
    except EligibilityBreakerOpen:
        # Known-bad dependency: skip egress entirely. No insurance_id in this
        # message (PHI policy rule 3).
        log.warning("visit-chat: eligibility lookup skipped, circuit open")
        return _degraded("pending", "verification deferred")

    # An admitted caller MUST record an outcome, including on an unexpected
    # exception — a half-open probe that records neither wedges the breaker shut
    # (the defect found in check.py during PR #11 review round 5).
    healthy = False
    try:
        result, healthy = _query(insurance_id)
    finally:
        if healthy:
            _breaker.record_success()
        else:
            _breaker.record_failure()
    return result


def _query(insurance_id: str) -> tuple[dict[str, Any], bool]:
    """Call eligibility-service and project the answer.

    Returns (verdict, healthy). `healthy` describes the DEPENDENCY, never the
    coverage — conflating the two is the mistake PR #11 spent rounds r4-r6
    correcting. It is "usable AND cheap":

      * usable — a definitive active/inactive is; so is a 4xx, which means
        eligibility-service rejected THIS request (a blank/malformed id) and says
        nothing about the dependency's health. A timeout, transport error, 5xx,
        unparseable body, or shaped 2xx with no verdict is not.
      * cheap — the answer did not hold this chat worker past the matching
        threshold. Latency counts on its own, whatever the answer was worth,
        because the breaker bounds worker-hold; a usable answer is still RETURNED
        while recording a breaker failure.

    See services/intake-service/app.py::_query_eligibility for the full
    derivation of both thresholds; the reasoning is identical and is not repeated.
    """
    started = time.monotonic()
    try:
        resp = httpx.get(
            f"{settings.eligibility_url}/eligibility",
            params={"insurance_id": insurance_id},
            timeout=settings.ai_eligibility_timeout_seconds,
        )
    except httpx.TimeoutException:
        log.error("visit-chat: eligibility lookup timed out")
        return _degraded("pending", "verification timed out"), False
    except Exception as e:
        # Broad on purpose (PHI policy rule 3): never stringify an outbound
        # exception here — the failing URL carries the member id.
        log.error("visit-chat: eligibility lookup failed (%s)", type(e).__name__)
        return _degraded("unknown", "eligibility check failed"), False

    if resp.status_code // 100 != 2:
        # Never a coverage denial. 4xx (except 408/429) is our fault, not the
        # dependency's, so it does not open a breaker shared by every clerk — but
        # it still has to have been cheap: a slow 422 pinned this worker exactly as
        # long as a slow verdict would have (review r6). `cheap` is computed
        # unconditionally so the latency line is always logged during an incident.
        caller_fault = 400 <= resp.status_code < 500 and resp.status_code not in (408, 429)
        log.error("visit-chat: eligibility returned HTTP %s", resp.status_code)
        cheap = _answered_cheaply(
            started, settings.ai_eligibility_slow_answer_seconds, "with an HTTP error"
        )
        return _degraded("unknown", "eligibility check failed"), caller_fault and cheap

    try:
        body = resp.json()
    except Exception:
        log.error("visit-chat: eligibility returned a non-JSON body")
        return _degraded("unknown", "eligibility check failed"), False
    if not isinstance(body, dict) or ("status" not in body and "active" not in body):
        return _degraded("unknown", "eligibility check failed"), False

    # `active` is the authoritative tri-state (ADR 0010); DERIVE the status from it
    # rather than trusting the body's string. Identity tests, because None is falsy
    # but is not False: a body with no boolean verdict must read "unknown", and a
    # {"status": "active"} with no `active` key must NOT read as covered.
    active = body.get("active")
    definitive = active is True or active is False
    verdict = {
        "active": active if definitive else None,
        "status": ("active" if active else "inactive") if definitive else "unknown",
        "payer": body.get("payer"),
        "raw_status": body.get("raw_status"),
        "checked_at": body.get("checked_at"),
        # Never the downstream `error` string, and never `insurance_id` — see the
        # module docstring. A caller persists this dict into visit memory.
        "reason": None if definitive else "eligibility check failed",
    }
    if definitive:
        return verdict, _answered_cheaply(
            started, settings.ai_eligibility_slow_answer_seconds, "with a coverage verdict"
        )
    return verdict, _answered_cheaply(
        started, settings.ai_eligibility_degraded_slow_seconds, "degraded"
    )


def _answered_cheaply(started: float, threshold_seconds: float, kind: str) -> bool:
    """Did eligibility answer without holding this chat worker past
    `threshold_seconds`?

    Logs the latency and a call-site literal only. Every other value in scope here
    came off the wire, and this module never echoes downstream content into a log
    (PHI policy rule 3) — so `kind` must stay a constant.
    """
    elapsed = time.monotonic() - started
    if elapsed < threshold_seconds:
        return True
    log.error(
        "visit-chat: eligibility answered %s after %.2fs — counting against the circuit",
        kind,
        elapsed,
    )
    return False
