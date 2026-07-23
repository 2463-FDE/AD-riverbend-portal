"""
Unit tests for the in-process circuit breaker (eligibility-service/breaker.py).

A fake monotonic clock drives the reset window so the tests never sleep. This
module is new in ADR 0010; the whole file is red against pre-fix code (no breaker
existed).
"""
import threading

from conftest import load_module

breaker_mod = load_module("services/eligibility-service/breaker.py", "payer_breaker_unit")
CircuitBreaker = breaker_mod.CircuitBreaker
PayerBreakerOpen = breaker_mod.PayerBreakerOpen


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _make(threshold=3, reset=30.0):
    clock = _Clock()
    return CircuitBreaker(fail_threshold=threshold, reset_seconds=reset, time_fn=clock), clock


def test_starts_closed_and_allows():
    cb, _ = _make()
    assert cb.state == CircuitBreaker.CLOSED
    cb.before_call()  # does not raise


def test_opens_after_threshold_failures():
    cb, _ = _make(threshold=3)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN
    # While open (before the reset window), calls are short-circuited.
    try:
        cb.before_call()
        assert False, "expected PayerBreakerOpen"
    except PayerBreakerOpen:
        pass


def test_success_resets_failure_count():
    cb, _ = _make(threshold=3)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    cb.record_failure()
    # Two failures after the reset is still below threshold -> stays closed.
    assert cb.state == CircuitBreaker.CLOSED
    cb.before_call()  # does not raise


def test_half_open_trial_success_closes():
    cb, clock = _make(threshold=2, reset=30.0)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN

    clock.advance(31.0)
    cb.before_call()  # reset window elapsed -> half-open trial allowed
    assert cb.state == CircuitBreaker.HALF_OPEN
    cb.record_success()
    assert cb.state == CircuitBreaker.CLOSED


def test_half_open_trial_failure_reopens():
    cb, clock = _make(threshold=2, reset=30.0)
    cb.record_failure()
    cb.record_failure()

    clock.advance(31.0)
    cb.before_call()
    assert cb.state == CircuitBreaker.HALF_OPEN
    cb.record_failure()  # trial failed -> re-open with a fresh window
    assert cb.state == CircuitBreaker.OPEN

    # Still open immediately after re-opening.
    try:
        cb.before_call()
        assert False, "expected PayerBreakerOpen"
    except PayerBreakerOpen:
        pass

    # And it re-opens for another full reset window.
    clock.advance(31.0)
    cb.before_call()
    assert cb.state == CircuitBreaker.HALF_OPEN


def test_half_open_admits_single_probe_under_concurrency():
    """After the reset window, many concurrent callers must not stampede the
    recovering payer — exactly ONE is admitted as the half-open probe, the rest
    are rejected with PayerBreakerOpen."""
    cb, clock = _make(threshold=1, reset=30.0)
    cb.record_failure()  # -> OPEN
    assert cb.state == CircuitBreaker.OPEN
    clock.advance(31.0)  # reset window elapsed; the next caller becomes the probe

    n = 20
    start = threading.Barrier(n)
    admitted = []
    rejected = []
    lock = threading.Lock()

    def worker():
        start.wait()  # maximise contention on the first admission
        try:
            cb.before_call()
            with lock:
                admitted.append(1)
        except PayerBreakerOpen:
            with lock:
                rejected.append(1)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(admitted) == 1, f"expected exactly one probe, got {len(admitted)}"
    assert len(rejected) == n - 1
