"""
Unit tests for the payer eligibility check (eligibility-service/check.py).

The outbound payer call is monkeypatched. Post-ADR-0010 the call is bounded: it
passes a timeout, retries transient failures, and raises typed PayerError
subclasses (never a raw requests exception, whose message would embed the
member_id-bearing URL).
"""
import sys

import pytest

from conftest import load_module

# check.py imports its siblings `config` and `breaker`; pin the eligibility-service
# copies while it loads so they don't collide with other services' same-named
# modules, then restore (same technique as test_intake_eligibility_phi.py).
_SIBLINGS = ("config", "breaker")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/eligibility-service/config.py", "elig_config_check")
sys.modules["breaker"] = load_module("services/eligibility-service/breaker.py", "elig_breaker_check")
check_mod = load_module("services/eligibility-service/check.py", "eligibility_check")
breaker_mod = sys.modules["breaker"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

MEMBER_ID = "BCBS4471"


class _FakeResponse:
    def __init__(self, ok: bool, status_code: int):
        self.ok = ok
        self.status_code = status_code


@pytest.fixture(autouse=True)
def _fresh_breaker():
    """check.py holds a module-level breaker singleton; give each test a fresh,
    closed one so trip state can't leak between tests."""
    check_mod._breaker = breaker_mod.CircuitBreaker(
        fail_threshold=check_mod.settings.payer_breaker_fail_threshold,
        reset_seconds=check_mod.settings.payer_breaker_reset_seconds,
    )


def test_active_coverage(monkeypatch):
    monkeypatch.setattr(check_mod.requests, "get", lambda *a, **k: _FakeResponse(True, 200))
    result = check_mod.check(MEMBER_ID)
    assert result["insurance_id"] == MEMBER_ID
    assert result["active"] is True
    assert result["raw_status"] == 200


def test_inactive_coverage(monkeypatch):
    # A 404 is a definitive "inactive" answer, not a failure — no retry, no trip.
    monkeypatch.setattr(check_mod.requests, "get", lambda *a, **k: _FakeResponse(False, 404))
    result = check_mod.check("UNKNOWN1")
    assert result["active"] is False
    assert result["raw_status"] == 404
    assert check_mod._breaker.state == breaker_mod.CircuitBreaker.CLOSED


def test_timeout_raises_typed_and_passes_timeout(monkeypatch):
    """A payer timeout raises PayerTimeout (not a raw requests error), the call
    passed a timeout=, and the raised exception carries no member_id."""
    seen = {}

    def _raise_timeout(*args, **kwargs):
        seen.update(kwargs)
        # Mimic requests embedding the member_id-bearing URL in the message.
        raise check_mod.requests.Timeout(
            "HTTPSConnectionPool timed out: /v1/eligibility?member_id=%s" % MEMBER_ID
        )

    monkeypatch.setattr(check_mod.requests, "get", _raise_timeout)

    with pytest.raises(breaker_mod.PayerTimeout) as exc:
        check_mod.check(MEMBER_ID)

    assert "timeout" in seen  # the bounded call passed a timeout=
    assert MEMBER_ID not in str(exc.value)  # typed exception must not leak the id


def test_connection_error_raises_unavailable(monkeypatch):
    def _raise_conn(*args, **kwargs):
        raise check_mod.requests.ConnectionError("connect failed member_id=%s" % MEMBER_ID)

    monkeypatch.setattr(check_mod.requests, "get", _raise_conn)

    with pytest.raises(breaker_mod.PayerUnavailable) as exc:
        check_mod.check(MEMBER_ID)
    assert MEMBER_ID not in str(exc.value)


def test_breaker_opens_and_short_circuits(monkeypatch):
    """After enough failed calls the breaker opens and short-circuits the next
    call without hitting the payer (PayerBreakerOpen)."""
    calls = {"n": 0}

    def _raise_conn(*args, **kwargs):
        calls["n"] += 1
        raise check_mod.requests.ConnectionError("down")

    monkeypatch.setattr(check_mod.requests, "get", _raise_conn)

    threshold = check_mod.settings.payer_breaker_fail_threshold
    for _ in range(threshold):
        with pytest.raises(breaker_mod.PayerUnavailable):
            check_mod.check(MEMBER_ID)

    calls_before = calls["n"]
    with pytest.raises(breaker_mod.PayerBreakerOpen):
        check_mod.check(MEMBER_ID)
    # Short-circuited: the payer was NOT called on the open-circuit attempt.
    assert calls["n"] == calls_before
