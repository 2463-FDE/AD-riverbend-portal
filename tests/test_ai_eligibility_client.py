"""Tests for ai-assistant's bounded eligibility client (ADR 0011 §4).

This is the chat endpoint's own hop to eligibility-service, and it is the third
copy of the D4 discipline (timeout + breaker + PHI-safe error handling). The
load-bearing properties, in order of what would hurt most if they regressed:

  * an outage NEVER renders as "no coverage" — `active` stays None, status
    `unknown`/`pending`, never `inactive` (the r3 misclassification);
  * the breaker actually opens in the outage it guards, which means health is
    "usable AND cheap" — a shaped 200 that burned the whole payer budget must
    count as a failure even though it parsed fine (the r5/r6 lessons);
  * a caller-fault 4xx does NOT open a breaker shared by every clerk;
  * the member id never reaches a log line and the downstream `error` string
    never reaches the caller (the leak PR #11 closed, one caller further out).
"""
import sys

import httpx
import pytest

from conftest import load_module

_PINNED = ("config", "logging_config", "breaker")
_saved = {name: sys.modules.pop(name, None) for name in _PINNED}
sys.modules["config"] = load_module("services/ai-assistant/config.py", "ai_elig_config")
sys.modules["logging_config"] = load_module(
    "services/ai-assistant/logging_config.py", "ai_elig_logging_config"
)
breaker_mod = sys.modules["breaker"] = load_module(
    "services/ai-assistant/breaker.py", "ai_elig_breaker"
)
client_mod = load_module(
    "services/ai-assistant/eligibility_client.py", "ai_eligibility_client"
)
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

MEMBER_ID = "AETN1224"


@pytest.fixture(autouse=True)
def _fresh_breaker(monkeypatch):
    """A per-test breaker instance.

    The module-level singleton is shared by every turn a worker serves — that is
    the design — but tests must not inherit each other's circuit state, or a test
    that trips the breaker silently changes the meaning of the next one.
    """
    monkeypatch.setattr(
        client_mod,
        "_breaker",
        breaker_mod.CircuitBreaker(fail_threshold=3, reset_seconds=30),
    )


def _response(status_code=200, body=None, exc=None, elapsed=0.0):
    """Fake httpx.get: returns a canned response, or raises, and can pretend the
    call took `elapsed` seconds (the breaker's health signal is latency)."""
    clock = {"t": 1000.0}

    def fake_get(url, params=None, timeout=None):
        fake_get.calls.append({"url": url, "params": params, "timeout": timeout})
        clock["t"] += elapsed
        if exc is not None:
            raise exc
        return httpx.Response(status_code, json=body if body is not None else {})

    fake_get.calls = []
    return fake_get, clock


def _install(monkeypatch, fake_get, clock):
    monkeypatch.setattr(client_mod.httpx, "get", fake_get)
    monkeypatch.setattr(client_mod.time, "monotonic", lambda: clock["t"])


# --- the call is bounded ----------------------------------------------------
def test_call_passes_the_configured_timeout(monkeypatch):
    fake_get, clock = _response(body={"active": True, "status": "active"})
    _install(monkeypatch, fake_get, clock)

    client_mod.check_coverage(MEMBER_ID)

    assert fake_get.calls[0]["timeout"] == client_mod.settings.ai_eligibility_timeout_seconds
    assert fake_get.calls[0]["timeout"] > 0


def test_timeout_reports_pending_not_a_denial(monkeypatch):
    fake_get, clock = _response(exc=httpx.TimeoutException("timed out"))
    _install(monkeypatch, fake_get, clock)

    verdict = client_mod.check_coverage(MEMBER_ID)

    assert verdict["active"] is None  # NOT False
    assert verdict["status"] == "pending"


def test_transport_error_reports_unknown_not_a_denial(monkeypatch):
    fake_get, clock = _response(exc=httpx.ConnectError("connection refused"))
    _install(monkeypatch, fake_get, clock)

    verdict = client_mod.check_coverage(MEMBER_ID)

    assert verdict["active"] is None
    assert verdict["status"] == "unknown"


# --- PHI boundary -----------------------------------------------------------
def test_member_id_never_reaches_a_log_line(monkeypatch, caplog):
    # httpx embeds the failing URL — which carries ?insurance_id=<member id> —
    # in its exception message. Stringifying it is exactly the leak PR #11 closed.
    leaky = httpx.ConnectError(
        f"failed to connect to http://eligibility-service:8072/eligibility"
        f"?insurance_id={MEMBER_ID}"
    )
    fake_get, clock = _response(exc=leaky)
    _install(monkeypatch, fake_get, clock)

    with caplog.at_level("DEBUG"):
        client_mod.check_coverage(MEMBER_ID)

    assert MEMBER_ID not in caplog.text
    assert "failed to connect" not in caplog.text  # no str(e) at all
    assert "ConnectError" in caplog.text  # the class IS logged — that is the point


def test_downstream_error_string_and_id_are_projected_away(monkeypatch):
    # eligibility-service's degraded body carries both. The caller persists this
    # dict into visit memory, so neither may survive the projection.
    fake_get, clock = _response(
        body={
            "insurance_id": MEMBER_ID,
            "active": None,
            "status": "unknown",
            "payer": "edi.example.com",
            "raw_status": None,
            "checked_at": "2026-07-26T10:00:00Z",
            "error": f"payer call failed for {MEMBER_ID}",
        }
    )
    _install(monkeypatch, fake_get, clock)

    verdict = client_mod.check_coverage(MEMBER_ID)

    assert "error" not in verdict
    assert "insurance_id" not in verdict
    assert MEMBER_ID not in str(verdict)


# --- tri-state classification ----------------------------------------------
def test_status_string_alone_never_reads_as_covered(monkeypatch):
    # A 2xx {"status": "active"} with NO boolean verdict must read "unknown".
    # Trusting the string is the r5 defect, in the covered-by-mistake direction.
    fake_get, clock = _response(body={"status": "active"})
    _install(monkeypatch, fake_get, clock)

    verdict = client_mod.check_coverage(MEMBER_ID)

    assert verdict["active"] is None
    assert verdict["status"] == "unknown"


def test_null_active_is_unknown_not_inactive(monkeypatch):
    fake_get, clock = _response(body={"active": None, "status": "unknown"})
    _install(monkeypatch, fake_get, clock)

    assert client_mod.check_coverage(MEMBER_ID)["status"] == "unknown"


@pytest.mark.parametrize(
    "active,expected", [(True, "active"), (False, "inactive")]
)
def test_definitive_verdicts_pass_through(monkeypatch, active, expected):
    fake_get, clock = _response(body={"active": active, "payer": "edi.example.com"})
    _install(monkeypatch, fake_get, clock)

    verdict = client_mod.check_coverage(MEMBER_ID)

    assert verdict["active"] is active
    assert verdict["status"] == expected


def test_non_json_body_is_unknown(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return httpx.Response(200, content=b"<html>not json</html>")

    monkeypatch.setattr(client_mod.httpx, "get", fake_get)
    monkeypatch.setattr(client_mod.time, "monotonic", lambda: 1000.0)

    assert client_mod.check_coverage(MEMBER_ID)["status"] == "unknown"


# --- breaker health: usable AND cheap --------------------------------------
def test_fast_degraded_answer_keeps_the_circuit_closed(monkeypatch):
    # eligibility-service's own payer breaker short-circuiting is free. Counting
    # it as a failure would open this circuit during a recovery, not an outage.
    fake_get, clock = _response(body={"active": None, "status": "unknown"}, elapsed=0.0)
    _install(monkeypatch, fake_get, clock)

    for _ in range(5):
        client_mod.check_coverage(MEMBER_ID)

    assert client_mod._breaker.state == "closed"
    assert len(fake_get.calls) == 5


def test_slow_degraded_answers_open_the_circuit(monkeypatch):
    # The SAME shaped 200, but it burned the payer budget. This is the outage the
    # breaker exists for, and counting only transport errors would miss it (r5).
    slow = client_mod.settings.ai_eligibility_degraded_slow_seconds + 0.5
    fake_get, clock = _response(body={"active": None, "status": "unknown"}, elapsed=slow)
    _install(monkeypatch, fake_get, clock)

    for _ in range(3):
        client_mod.check_coverage(MEMBER_ID)

    assert client_mod._breaker.state == "open"
    # Next turn short-circuits: no outbound call at all, and a deferred answer.
    verdict = client_mod.check_coverage(MEMBER_ID)
    assert len(fake_get.calls) == 3
    assert verdict["status"] == "pending"
    assert verdict["active"] is None


def test_slow_definitive_answer_is_returned_but_still_counts(monkeypatch):
    # r6: usefulness and dependency health are separate questions. A payer that
    # degrades while still answering (2-4s every turn, forever) must open the
    # circuit — and the clerk still gets the verdict.
    slow = client_mod.settings.ai_eligibility_slow_answer_seconds + 0.5
    fake_get, clock = _response(body={"active": True}, elapsed=slow)
    _install(monkeypatch, fake_get, clock)

    for _ in range(3):
        verdict = client_mod.check_coverage(MEMBER_ID)
        assert verdict["status"] == "active"  # returned every time

    assert client_mod._breaker.state == "open"


def test_a_fast_definitive_answer_between_thresholds_stays_healthy(monkeypatch):
    # Guards the ORDER of the two thresholds, not just their values: an answer
    # slower than the degraded bound but faster than the definitive one is
    # healthy precisely because it carried a verdict. If the two knobs were
    # swapped, this reddens.
    between = (
        client_mod.settings.ai_eligibility_degraded_slow_seconds
        + client_mod.settings.ai_eligibility_slow_answer_seconds
    ) / 2
    assert (
        client_mod.settings.ai_eligibility_degraded_slow_seconds
        < between
        < client_mod.settings.ai_eligibility_slow_answer_seconds
    ), "thresholds must be distinct for this test to mean anything"
    fake_get, clock = _response(body={"active": True}, elapsed=between)
    _install(monkeypatch, fake_get, clock)

    for _ in range(5):
        client_mod.check_coverage(MEMBER_ID)

    assert client_mod._breaker.state == "closed"


def test_caller_fault_4xx_does_not_open_the_shared_circuit(monkeypatch):
    # A run of malformed member ids is OUR fault, not the dependency's. Counting
    # them would strip eligibility lookups from every OTHER clerk.
    fake_get, clock = _response(status_code=422, body={"detail": "blank id"})
    _install(monkeypatch, fake_get, clock)

    for _ in range(5):
        verdict = client_mod.check_coverage(MEMBER_ID)
        assert verdict["status"] == "unknown"

    assert client_mod._breaker.state == "closed"


def test_slow_4xx_still_counts_because_it_held_the_worker(monkeypatch):
    slow = client_mod.settings.ai_eligibility_slow_answer_seconds + 0.5
    fake_get, clock = _response(status_code=422, body={"detail": "blank"}, elapsed=slow)
    _install(monkeypatch, fake_get, clock)

    for _ in range(3):
        client_mod.check_coverage(MEMBER_ID)

    assert client_mod._breaker.state == "open"


def test_5xx_opens_the_circuit(monkeypatch):
    fake_get, clock = _response(status_code=503, body={"detail": "down"})
    _install(monkeypatch, fake_get, clock)

    for _ in range(3):
        client_mod.check_coverage(MEMBER_ID)

    assert client_mod._breaker.state == "open"


def test_half_open_probe_recovers_the_circuit(monkeypatch):
    clock = {"t": 1000.0}
    state = {"fail": True}

    def fake_get(url, params=None, timeout=None):
        fake_get.calls.append(url)
        if state["fail"]:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"active": True})

    fake_get.calls = []
    monkeypatch.setattr(client_mod.httpx, "get", fake_get)
    monkeypatch.setattr(client_mod.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(
        client_mod._breaker, "_time_fn", lambda: clock["t"]
    )

    for _ in range(3):
        client_mod.check_coverage(MEMBER_ID)
    assert client_mod._breaker.state == "open"

    # Still inside the reset window: short-circuited, no call.
    calls_before = len(fake_get.calls)
    client_mod.check_coverage(MEMBER_ID)
    assert len(fake_get.calls) == calls_before

    # Window elapsed and the dependency recovered: one probe closes the circuit.
    clock["t"] += client_mod.settings.ai_eligibility_breaker_reset_seconds + 1
    state["fail"] = False
    verdict = client_mod.check_coverage(MEMBER_ID)
    assert verdict["status"] == "active"
    assert client_mod._breaker.state == "closed"


def test_an_unexpected_exception_inside_query_is_handled(monkeypatch):
    # An exception raised INSIDE the http call is caught by _query's broad except
    # and becomes a degraded answer -- no wedge risk on this path.
    fake_get, clock = _response(exc=RuntimeError("something unexpected"))
    _install(monkeypatch, fake_get, clock)

    for _ in range(3):
        assert client_mod.check_coverage(MEMBER_ID)["status"] == "unknown"

    assert client_mod._breaker.state == "open"


def test_an_exception_escaping_query_cannot_wedge_the_breaker(monkeypatch):
    """The half-open wedge found in check.py during PR #11 review r5.

    The previous version of this test raised inside httpx.get, which _query's
    broad `except Exception` swallows -- so nothing ever escaped and the
    try/finally under test was never exercised (deleting it left the test green).
    Raise from _query itself, which is what the finally actually guards.
    """
    def _boom(insurance_id):
        raise RuntimeError("escaped _query")

    monkeypatch.setattr(client_mod, "_query", _boom)

    with pytest.raises(RuntimeError):
        client_mod.check_coverage(MEMBER_ID)

    # The admitted caller recorded an outcome on its way out, so the breaker is
    # not stuck mid-probe and later callers are not rejected forever.
    assert client_mod._breaker._probe_in_flight is False
    with pytest.raises(RuntimeError):
        client_mod.check_coverage(MEMBER_ID)
    with pytest.raises(RuntimeError):
        client_mod.check_coverage(MEMBER_ID)
    assert client_mod._breaker.state == "open"


def test_degraded_answers_carry_an_observation_timestamp(monkeypatch):
    # A degraded verdict is persisted into visit memory and re-rendered on later
    # turns; without checked_at, a 25-minute-old failed attempt reads as if the
    # check had just run (ADR 0011 s5 promises the opposite).
    fake_get, clock = _response(exc=httpx.TimeoutException("timed out"))
    _install(monkeypatch, fake_get, clock)

    verdict = client_mod.check_coverage(MEMBER_ID)

    assert verdict["checked_at"], "a degraded verdict must still say WHEN it was observed"
