"""
In-process circuit breaker + typed payer exceptions for the eligibility check.

Per-worker state only (no shared store) — see ADR 0010. The breaker keys nothing
on the member/insurance id and its exceptions carry state only, never str(e) of a
payer error, so nothing PHI-adjacent can leak through this module.
"""
import time as _time


class PayerError(Exception):
    """Base for payer-call failures. Carries a category label, never str(e)."""


class PayerTimeout(PayerError):
    """The payer call exceeded its connect/read timeout budget."""


class PayerUnavailable(PayerError):
    """The payer refused/errored (connection error or 5xx) after retries."""


class PayerBreakerOpen(PayerError):
    """The circuit is open; the call was short-circuited without hitting the payer."""


class CircuitBreaker:
    """
    Closed → open → half-open circuit breaker.

    - closed: calls pass through; consecutive failures are counted.
    - open: after `fail_threshold` failures, calls are short-circuited
      (raise PayerBreakerOpen) until `reset_seconds` elapse.
    - half-open: the first call after the reset window is allowed as a trial;
      success closes the breaker, failure re-opens it with a fresh window.

    `time_fn` is injectable so tests can advance a fake monotonic clock instead
    of sleeping.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, fail_threshold: int, reset_seconds: float, time_fn=_time.monotonic):
        self._fail_threshold = max(1, int(fail_threshold))
        self._reset_seconds = float(reset_seconds)
        self._time_fn = time_fn
        self._state = self.CLOSED
        self._failures = 0
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        return self._state

    def before_call(self) -> None:
        """Gate a call. Raise PayerBreakerOpen if the circuit is open and the
        reset window has not yet elapsed; otherwise allow (transitioning to
        half-open for the trial call)."""
        if self._state == self.OPEN:
            if self._time_fn() - self._opened_at < self._reset_seconds:
                raise PayerBreakerOpen("circuit open")
            self._state = self.HALF_OPEN

    def record_success(self) -> None:
        self._state = self.CLOSED
        self._failures = 0

    def record_failure(self) -> None:
        if self._state == self.HALF_OPEN:
            # Trial call failed — re-open with a fresh window.
            self._state = self.OPEN
            self._opened_at = self._time_fn()
            return
        self._failures += 1
        if self._failures >= self._fail_threshold:
            self._state = self.OPEN
            self._opened_at = self._time_fn()
