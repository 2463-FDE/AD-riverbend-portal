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


def _shrink_slow_threshold(monkeypatch):
    """Scale ELIGIBILITY_DEGRADED_SLOW_SECONDS (1s in prod) down to SLOW_SECONDS'
    scale so the suite stays fast.

    `raising=False` on purpose: against pre-r5 code the setting does not exist,
    and these tests must go RED on the BEHAVIOUR (the breaker never opening), not
    on an AttributeError from the patch itself. Caveat: a typo'd attribute name
    leaves the real 1s threshold in place, so every fake response reads as fast —
    loud in the tests that assert the circuit OPENS, silent in the ones that
    assert it stays CLOSED. Those are guards, not regression proofs; see
    test_slow_definitive_answer_never_trips_the_breaker."""
    monkeypatch.setattr(
        app_mod.settings, "eligibility_degraded_slow_seconds", SLOW_SECONDS / 2, raising=False
    )


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


def test_slow_degraded_answer_trips_the_breaker(monkeypatch):
    """The r5 no-ship: a payer outage reaches intake as a *slow* HTTP 200
    {"active": null, "status": "unknown"} — eligibility-service burned its whole
    payer budget and then answered gracefully. Counting that as healthy (r4) meant
    the breaker reset on every registration and each front-desk save kept paying
    the payer budget: the exact outage this breaker exists to bound.

    RED against r4, where every shaped 2xx returned healthy=True: the breaker
    stayed CLOSED and the post-threshold call still went out and still blocked."""
    calls = {"n": 0}

    def _slow_degraded(*a, **k):
        calls["n"] += 1
        time.sleep(SLOW_SECONDS)  # stands in for burning the payer budget
        return _FakeResp({"insurance_id": MEMBER_ID, "active": None, "status": "unknown"})

    monkeypatch.setattr(app_mod.httpx, "get", _slow_degraded)
    _shrink_slow_threshold(monkeypatch)
    _install_breaker(threshold=3)

    for _ in range(3):
        assert app_mod._verify_eligibility(_insurance())["status"] == "unknown"
    assert calls["n"] == 3
    assert app_mod._breaker.state == CircuitBreaker.OPEN

    started = time.perf_counter()
    result = app_mod._verify_eligibility(_insurance())
    elapsed = time.perf_counter() - started

    assert calls["n"] == 3, "circuit is open — no outbound call may be made"
    assert elapsed < SLOW_SECONDS / 2, f"deferred verification still blocked {elapsed:.3f}s"
    assert result == {"active": None, "status": "pending", "reason": "verification deferred"}


def test_slow_definitive_answer_never_trips_the_breaker(monkeypatch):
    """Latency alone is not a failure: a payer that is slow but still ANSWERING
    gives real coverage verdicts, and the per-call timeout already caps what one
    costs. Tripping here would throw away correct answers — only degraded
    no-verdict replies are judged on cost.

    A GUARD against over-correcting the r5 fix, not a regression proof: it is
    green against pre-r5 code too (which treated everything as healthy). The
    accepted cost of this rule is stated in ADR 0010's honest limits — a slow but
    answering payer is bounded per call, not in aggregate."""
    calls = {"n": 0}

    def _slow_active(*a, **k):
        calls["n"] += 1
        time.sleep(SLOW_SECONDS)
        return _FakeResp({"insurance_id": MEMBER_ID, "active": True, "status": "active"})

    monkeypatch.setattr(app_mod.httpx, "get", _slow_active)
    _shrink_slow_threshold(monkeypatch)
    _install_breaker(threshold=2)

    for _ in range(5):
        assert app_mod._verify_eligibility(_insurance())["active"] is True

    assert app_mod._breaker.state == CircuitBreaker.CLOSED
    assert calls["n"] == 5


@pytest.mark.parametrize(
    "body",
    [
        # The whole class of "2xx that carries no boolean coverage verdict",
        # not one anecdote ([[fix-the-class-not-the-instance]]). Every one of
        # these must read as degraded and be judged on cost.
        {"active": None, "status": "deferred"},  # a future/foreign status value
        {"active": None, "status": "unknown"},  # eligibility's own degraded shape
        {"active": None, "status": ""},  # empty string
        {"active": None, "status": None},  # null status
        {"active": None, "status": 1},  # not even a string
        {"active": None, "status": "ACTIVE"},  # right word, wrong case
        {"active": None, "status": "active "},  # right word, trailing space
        {"active": "true", "status": "active"},  # stringly-typed, not a bool
        {"status": "active"},  # THE adversarial one: verdict word, no verdict
    ],
)
def test_slow_answer_without_a_boolean_verdict_is_degraded(monkeypatch, body):
    """Adversarial: the definitive/degraded split must key on an ACTUAL verdict —
    `active` being True or False — never on the `status` string a downstream
    happened to send. `status` is derived detail; `active` is the authoritative
    tri-state (ADR 0010).

    Both directions of the misclassification matter. r3 stopped a dependency
    outage reading as "inactive" (a patient wrongly told they are uninsured).
    This is the mirror: a body carrying the WORD "active" but no boolean must not
    be reported as covered — and since r5 it must not hold the circuit closed
    while every registration pays full latency either."""
    payload = dict(body, insurance_id=MEMBER_ID)

    def _slow_other(*a, **k):
        time.sleep(SLOW_SECONDS)
        return _FakeResp(dict(payload))

    monkeypatch.setattr(app_mod.httpx, "get", _slow_other)
    _shrink_slow_threshold(monkeypatch)
    _install_breaker(threshold=2)

    for _ in range(2):
        result = app_mod._verify_eligibility(_insurance())
        assert result["status"] == "unknown", f"{payload} must not report a coverage verdict"

    assert app_mod._breaker.state == CircuitBreaker.OPEN


def test_caller_error_never_trips_the_shared_breaker(monkeypatch):
    """Adversarial availability check: the breaker is shared by every patient, so
    it must only ever be driven by the DEPENDENCY's health. eligibility-service
    answers 422 when intake sends a blank/malformed member_id — a bad batch
    import or a scanner emitting whitespace produces a run of them. Counting
    those would let a few junk rows strip eligibility verification from everyone
    else for the whole reset window."""
    calls = {"n": 0}

    def _rejected(*a, **k):
        calls["n"] += 1
        return _FakeResp({"detail": "insurance_id must not be blank"}, status_code=422)

    monkeypatch.setattr(app_mod.httpx, "get", _rejected)
    _install_breaker(threshold=2)

    for _ in range(5):
        assert app_mod._verify_eligibility(_insurance())["status"] == "unknown"

    assert app_mod._breaker.state == CircuitBreaker.CLOSED
    assert calls["n"] == 5, "a caller-side error must not stop us calling the dependency"


@pytest.mark.parametrize("status_code", [500, 503, 408, 429])
def test_dependency_side_http_errors_still_trip_the_breaker(monkeypatch, status_code):
    """The other half of that split: a 5xx — and the two 4xx codes that mean
    "overloaded", not "your request is wrong" — are the dependency failing, and
    must still count. Narrowing the 4xx carve-out must not punch a hole here."""

    def _failing(*a, **k):
        return _FakeResp({"detail": "boom"}, status_code=status_code)

    monkeypatch.setattr(app_mod.httpx, "get", _failing)
    _install_breaker(threshold=2)

    for _ in range(2):
        assert app_mod._verify_eligibility(_insurance())["status"] == "unknown"

    assert app_mod._breaker.state == CircuitBreaker.OPEN


def test_slow_degraded_log_carries_no_member_id(monkeypatch, caplog):
    """Adversarial PHI check on the NEW branch (CLAUDE.md §5): the degraded-and-slow
    log line is the only place intake reports on a downstream *body*. Plant the
    member id in every field of that body — including keys intake does not read,
    and the `status` value it does — and prove none of it reaches the log. (The
    returned payload is the downstream body itself and legitimately echoes
    insurance_id back to the front desk that submitted it; the log is the boundary
    under test.)"""

    def _slow_phi(*a, **k):
        time.sleep(SLOW_SECONDS)
        return _FakeResp(
            {
                "insurance_id": MEMBER_ID,
                "active": None,
                "status": f"unknown-{MEMBER_ID}",
                "error": f"payer rejected {MEMBER_ID}",
                "payer": MEMBER_ID,
                "notes": [MEMBER_ID],
            }
        )

    monkeypatch.setattr(app_mod.httpx, "get", _slow_phi)
    _shrink_slow_threshold(monkeypatch)
    _install_breaker(threshold=1)

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        app_mod._verify_eligibility(_insurance())

    assert app_mod._breaker.state == CircuitBreaker.OPEN
    # Assert POSITIVELY that the degraded line was emitted — an all-clear over an
    # empty caplog proves nothing, and would keep passing if the log call were
    # deleted outright.
    degraded = [r for r in caplog.records if "degraded" in r.getMessage()]
    assert len(degraded) == 1, f"expected one degraded log line, got {len(degraded)}"
    for record in caplog.records:
        assert MEMBER_ID not in record.getMessage()


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
