"""
Unit tests for the payer eligibility check (eligibility-service/check.py).

The outbound payer call is monkeypatched. NOTE: there is intentionally NO test
asserting a timeout/circuit-breaker on the payer call — because the code has
none (D4). That missing behavior is the cohort's to add; the gap is deliberate.
"""
from conftest import load_module

check_mod = load_module("services/eligibility-service/check.py", "eligibility_check")


class _FakeResponse:
    def __init__(self, ok: bool, status_code: int):
        self.ok = ok
        self.status_code = status_code


def test_active_coverage(monkeypatch):
    monkeypatch.setattr(check_mod.requests, "get", lambda *a, **k: _FakeResponse(True, 200))
    result = check_mod.check("BCBS4471")
    assert result["insurance_id"] == "BCBS4471"
    assert result["active"] is True
    assert result["raw_status"] == 200


def test_inactive_coverage(monkeypatch):
    monkeypatch.setattr(check_mod.requests, "get", lambda *a, **k: _FakeResponse(False, 404))
    result = check_mod.check("UNKNOWN1")
    assert result["active"] is False
    assert result["raw_status"] == 404
