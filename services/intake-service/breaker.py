"""
In-process circuit breaker for intake's call to eligibility-service.

Copy of the eligibility-service breaker (services share code by copy-paste — no
shared library, ADR 0001), retargeted at intake's own dependency. Two different
seams, two independent breakers: eligibility-service's breaker protects the
*payer* call, this one protects the *intake worker thread*.

Why intake needs its own (adversarial review r4): a per-request timeout caps a
single registration's worker-hold, but under a sustained payer/eligibility
degradation every registration still pays that full cap, so concurrent intakes
keep tying up workers. Once this breaker opens, verification is skipped without
an outbound call and /intake returns a deferred "pending" status immediately.

Per-worker state only (no shared store) — see ADR 0010. The breaker keys nothing
on the member/insurance id and its exception carries state only, never str(e) of
a downstream error, so nothing PHI-adjacent can leak through this module.

Thread-safe: FastAPI runs sync handlers in a threadpool, so state transitions are
guarded by a lock and half-open admits exactly ONE probe call — concurrent callers
after a reset window are rejected rather than stampeding a recovering dependency.
"""
import threading
import time as _time


class EligibilityBreakerOpen(Exception):
    """The circuit is open; verification was skipped without an outbound call."""


class CircuitBreaker:
    """
    Closed → open → half-open circuit breaker.

    - closed: calls pass through; consecutive failures are counted.
    - open: after `fail_threshold` failures, calls are short-circuited
      (raise EligibilityBreakerOpen) until `reset_seconds` elapse.
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
        """Gate a call. Raise EligibilityBreakerOpen while the circuit is open
        (before the reset window elapses) or when a half-open probe is already in
        flight. Otherwise allow — admitting the single half-open probe when the
        window has just elapsed.

        Every admitted caller MUST later call record_success() or
        record_failure(); an admitted half-open probe that records neither leaves
        `_probe_in_flight` set and wedges the breaker shut. Callers guarantee
        this with try/finally (see app.py::_verify_eligibility).
        """
        with self._lock:
            if self._state == self.OPEN:
                if self._time_fn() - self._opened_at < self._reset_seconds:
                    raise EligibilityBreakerOpen("circuit open")
                # Reset window elapsed — this caller becomes the sole probe.
                self._state = self.HALF_OPEN
                self._probe_in_flight = True
                return
            if self._state == self.HALF_OPEN:
                # A probe is already testing the dependency; reject everyone else.
                if self._probe_in_flight:
                    raise EligibilityBreakerOpen("circuit half-open probe in flight")
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
