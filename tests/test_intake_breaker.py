"""
Tests for the intake-side circuit breaker on the intake -> eligibility hop
(ADR 0010, adversarial review r4).

The r3 fix bounded ONE registration's worker-hold with a timeout. It did not
bound the *sustained* cost: while eligibility/the payer stayed wedged, every
front-desk save still paid the full ELIGIBILITY_TIMEOUT_SECONDS, so concurrent
registrations kept tying up intake workers. The breaker closes that: after
ELIGIBILITY_BREAKER_FAIL_THRESHOLD consecutive unusable answers, verification is
skipped with no outbound call and /intake returns status "pending" immediately.

RED against pre-r4 code, which had no breaker: the post-threshold call still went
out and still paid the delay.
"""
import logging
import sys
import time

import httpx
import pytest

from conftest import load_module

_SIBLINGS = ("config", "db", "logging_config", "models", "schemas", "breaker")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/intake-service/config.py", "intake_config_breaker")
sys.modules["db"] = load_module("services/intake-service/db.py", "intake_db_breaker")
sys.modules["logging_config"] = load_module(
    "services/intake-service/logging_config.py", "intake_logging_config_breaker"
)
sys.modules["models"] = load_module("services/intake-service/models.py", "intake_models_breaker")
sys.modules["schemas"] = load_module("services/intake-service/schemas.py", "intake_schemas_breaker")
sys.modules["breaker"] = load_module("services/intake-service/breaker.py", "intake_breaker_unit")
app_mod = load_module("services/intake-service/app.py", "intake_app_breaker")
schemas_mod = sys.modules["schemas"]
breaker_mod = sys.modules["breaker"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

MEMBER_ID = "BCBS4471"
CircuitBreaker = breaker_mod.CircuitBreaker

# Stands in for the real ELIGIBILITY_TIMEOUT_SECONDS (8s) — long enough to
# measure, short enough to keep the suite fast.
SLOW_SECONDS = 0.05


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class _FakeResp:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body


def _install_breaker(threshold=3, reset=30.0, time_fn=None):
    """Replace app.py's module-level singleton with a fresh, closed breaker."""
    kwargs = {"fail_threshold": threshold, "reset_seconds": reset}
    if time_fn is not None:
        kwargs["time_fn"] = time_fn
    app_mod._breaker = CircuitBreaker(**kwargs)
    return app_mod._breaker


@pytest.fixture(autouse=True)
def _fresh_breaker():
    _install_breaker()


def _insurance():
    return schemas_mod.Insurance(member_id=MEMBER_ID)


def test_sustained_outage_stops_charging_intake_the_full_timeout(monkeypatch):
    """The RIV-141 proof the r3 fix was missing: once eligibility is known-bad,
    a registration no longer waits on it at all."""
    calls = {"n": 0}

    def _hang(*a, **k):
        calls["n"] += 1
        time.sleep(SLOW_SECONDS)  # stands in for burning the timeout budget
        raise httpx.TimeoutException("read timed out")

    monkeypatch.setattr(app_mod.httpx, "get", _hang)
    _install_breaker(threshold=3)

    # The first `threshold` registrations still pay the bounded wait — that burst
    # is the documented cost of per-worker breaker state (ADR 0010).
    for _ in range(3):
        assert app_mod._verify_eligibility(_insurance())["status"] == "pending"
    assert calls["n"] == 3

    started = time.perf_counter()
    result = app_mod._verify_eligibility(_insurance())
    elapsed = time.perf_counter() - started

    assert calls["n"] == 3, "circuit is open — no outbound call may be made"
    assert elapsed < SLOW_SECONDS / 2, f"deferred verification still blocked {elapsed:.3f}s"
    assert result == {"active": None, "status": "pending", "reason": "verification deferred"}


def test_deferred_result_and_log_carry_no_member_id(monkeypatch, caplog):
    """Adversarial PHI check on the NEW branch: the short-circuit path must be as
    PHI-safe as the failure paths it replaces (phi-logging-policy rule 3)."""
    monkeypatch.setattr(
        app_mod.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down"))
    )
    _install_breaker(threshold=1)
    app_mod._verify_eligibility(_insurance())  # trip it

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        result = app_mod._verify_eligibility(_insurance())

    assert result["status"] == "pending"
    assert MEMBER_ID not in str(result)
    for record in caplog.records:
        assert MEMBER_ID not in record.getMessage()


def test_definitive_inactive_never_trips_the_breaker(monkeypatch):
    """`healthy` is a DEPENDENCY verdict, not a coverage verdict. A patient whose
    coverage is genuinely inactive must not push intake toward skipping checks
    for everyone else."""
    calls = {"n": 0}

    def _inactive(*a, **k):
        calls["n"] += 1
        return _FakeResp({"insurance_id": MEMBER_ID, "active": False, "raw_status": 404})

    monkeypatch.setattr(app_mod.httpx, "get", _inactive)
    _install_breaker(threshold=2)

    for _ in range(5):
        assert app_mod._verify_eligibility(_insurance())["status"] == "inactive"

    assert app_mod._breaker.state == CircuitBreaker.CLOSED
    assert calls["n"] == 5, "every call must still reach the dependency"


def test_fast_degraded_answer_never_trips_the_breaker(monkeypatch):
    """eligibility-service answering 200 with its own degraded verdict (its payer
    breaker is open) costs no worker time — intake must not suppress a cheap
    call. Documented rule in _query_eligibility's docstring."""
    calls = {"n": 0}

    def _degraded(*a, **k):
        calls["n"] += 1
        return _FakeResp({"insurance_id": MEMBER_ID, "active": None, "status": "unknown"})

    monkeypatch.setattr(app_mod.httpx, "get", _degraded)
    _install_breaker(threshold=2)

    for _ in range(5):
        assert app_mod._verify_eligibility(_insurance())["status"] == "unknown"

    assert app_mod._breaker.state == CircuitBreaker.CLOSED
    assert calls["n"] == 5


def test_unexpected_exception_records_a_failure_and_never_wedges_the_breaker(monkeypatch):
    """The hardened-wrapper lesson (PR #4 r4): an admitted caller that records
    neither outcome leaves a half-open probe in flight and jams the breaker shut
    forever. Plant an exception the shaping helper does not catch and prove the
    try/finally still settles the breaker."""

    def _boom(*a, **k):
        raise RuntimeError("unexpected shaping bug")

    monkeypatch.setattr(app_mod, "_query_eligibility", _boom)
    cb = _install_breaker(threshold=1)

    with pytest.raises(RuntimeError):
        app_mod._verify_eligibility(_insurance())

    # The failure was recorded (not swallowed, not lost).
    assert cb.state == CircuitBreaker.OPEN
    # And the breaker is still usable: a normal short-circuit, not a wedge.
    result = app_mod._verify_eligibility(_insurance())
    assert result["reason"] == "verification deferred"


def test_recovered_dependency_closes_the_breaker(monkeypatch):
    """Degradation must be temporary: after the reset window one probe is
    admitted, and a healthy answer restores normal verification."""
    clock = _Clock()
    cb = _install_breaker(threshold=1, reset=30.0, time_fn=clock)

    monkeypatch.setattr(
        app_mod.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down"))
    )
    app_mod._verify_eligibility(_insurance())
    assert cb.state == CircuitBreaker.OPEN
    assert app_mod._verify_eligibility(_insurance())["reason"] == "verification deferred"

    clock.advance(31.0)
    monkeypatch.setattr(
        app_mod.httpx,
        "get",
        lambda *a, **k: _FakeResp({"insurance_id": MEMBER_ID, "active": True, "status": "active"}),
    )
    result = app_mod._verify_eligibility(_insurance())  # the single half-open probe
    assert result["active"] is True
    assert cb.state == CircuitBreaker.CLOSED
