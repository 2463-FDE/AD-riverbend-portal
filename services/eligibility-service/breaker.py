"""
In-process circuit breaker + typed payer exceptions for the eligibility check.

Per-worker state only (no shared store) — see ADR 0010. The breaker keys nothing
on the member/insurance id and its exceptions carry state only, never str(e) of a
payer error, so nothing PHI-adjacent can leak through this module.

Thread-safe: FastAPI runs sync handlers in a threadpool, so state transitions are
guarded by a lock and half-open admits exactly ONE probe call — concurrent callers
after a reset window are rejected rather than stampeding the recovering payer.
"""
import threading
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
    - half-open: exactly ONE trial call is admitted after the reset window; while
      that probe is in flight all other callers are rejected. Success closes the
      breaker, failure re-opens it with a fresh window.

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
        self._probe_in_flight = False
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        return self._state

    def before_call(self) -> None:
        """Gate a call. Raise PayerBreakerOpen while the circuit is open (before
        the reset window elapses) or when a half-open probe is already in flight.
        Otherwise allow — admitting the single half-open probe when the window
        has just elapsed."""
        with self._lock:
            if self._state == self.OPEN:
                if self._time_fn() - self._opened_at < self._reset_seconds:
                    raise PayerBreakerOpen("circuit open")
                # Reset window elapsed — this caller becomes the sole probe.
                self._state = self.HALF_OPEN
                self._probe_in_flight = True
                return
            if self._state == self.HALF_OPEN:
                # A probe is already testing the payer; reject everyone else.
                if self._probe_in_flight:
                    raise PayerBreakerOpen("circuit half-open probe in flight")
                self._probe_in_flight = True

    def record_success(self) -> None:
        with self._lock:
            self._state = self.CLOSED
            self._failures = 0
            self._probe_in_flight = False

    def record_failure(self) -> None:
        with self._lock:
            if self._state == self.HALF_OPEN:
                # Trial call failed — re-open with a fresh window.
                self._state = self.OPEN
                self._opened_at = self._time_fn()
                self._probe_in_flight = False
                return
            self._failures += 1
            if self._failures >= self._fail_threshold:
                self._state = self.OPEN
                self._opened_at = self._time_fn()
                self._probe_in_flight = False
