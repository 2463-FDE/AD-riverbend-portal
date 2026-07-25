"""
Tests for intake's bounded, best-effort eligibility verification (ADR 0010).

A slow/hung payer must never block /intake: a timeout degrades to status
"pending", any other failure to "unknown", and a healthy response is stamped
active/inactive. Red against pre-fix code, which had no timeout and returned a
dict with no "status" key.
"""
import sys

import httpx
import pytest

from conftest import load_module

_SIBLINGS = ("config", "db", "logging_config", "models", "schemas", "breaker")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/intake-service/config.py", "intake_config_deferred")
sys.modules["db"] = load_module("services/intake-service/db.py", "intake_db_deferred")
sys.modules["logging_config"] = load_module(
    "services/intake-service/logging_config.py", "intake_logging_config_deferred"
)
sys.modules["models"] = load_module("services/intake-service/models.py", "intake_models_deferred")
sys.modules["schemas"] = load_module("services/intake-service/schemas.py", "intake_schemas_deferred")
sys.modules["breaker"] = load_module("services/intake-service/breaker.py", "intake_breaker_deferred")
app_mod = load_module("services/intake-service/app.py", "intake_app_deferred")
schemas_mod = sys.modules["schemas"]
breaker_mod = sys.modules["breaker"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

MEMBER_ID = "BCBS4471"


@pytest.fixture(autouse=True)
def _fresh_breaker():
    """app.py holds a module-level breaker singleton; give each test a fresh,
    closed one so the failure paths below can't trip it for later tests."""
    app_mod._breaker = breaker_mod.CircuitBreaker(
        fail_threshold=app_mod.settings.eligibility_breaker_fail_threshold,
        reset_seconds=app_mod.settings.eligibility_breaker_reset_seconds,
    )


class _FakeResp:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def test_timeout_returns_pending(monkeypatch):
    def _timeout(*a, **k):
        raise httpx.TimeoutException("read timed out")

    monkeypatch.setattr(app_mod.httpx, "get", _timeout)
    ins = schemas_mod.Insurance(member_id=MEMBER_ID)
    result = app_mod._verify_eligibility(ins)
    assert result == {"active": None, "status": "pending", "reason": "verification timed out"}


def test_transport_failure_returns_unknown(monkeypatch):
    def _fail(*a, **k):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(app_mod.httpx, "get", _fail)
    ins = schemas_mod.Insurance(member_id=MEMBER_ID)
    result = app_mod._verify_eligibility(ins)
    assert result == {"active": None, "status": "unknown", "reason": "eligibility check failed"}


def test_success_stamps_active_status(monkeypatch):
    # eligibility-service already supplies status; passed through untouched.
    body = {"insurance_id": MEMBER_ID, "active": True, "status": "active", "raw_status": 200}
    monkeypatch.setattr(app_mod.httpx, "get", lambda *a, **k: _FakeResp(body))
    ins = schemas_mod.Insurance(member_id=MEMBER_ID)
    result = app_mod._verify_eligibility(ins)
    assert result["active"] is True
    assert result["status"] == "active"


def test_success_stamps_status_when_absent(monkeypatch):
    # Older/other responder without a status key -> intake stamps from active.
    body = {"insurance_id": MEMBER_ID, "active": False, "raw_status": 404}
    monkeypatch.setattr(app_mod.httpx, "get", lambda *a, **k: _FakeResp(body))
    ins = schemas_mod.Insurance(member_id=MEMBER_ID)
    result = app_mod._verify_eligibility(ins)
    assert result["status"] == "inactive"


def test_null_active_without_status_is_unknown_not_inactive(monkeypatch):
    # Adversarial (review r4): `active` is tri-state, so a truthiness stamp turns
    # a payer that gave NO verdict (active=None) into "inactive" — telling the
    # front desk a patient is uninsured because of an outage. Same defect class
    # as r3, one layer down.
    body = {"insurance_id": MEMBER_ID, "active": None, "raw_status": 503}
    monkeypatch.setattr(app_mod.httpx, "get", lambda *a, **k: _FakeResp(body))
    ins = schemas_mod.Insurance(member_id=MEMBER_ID)
    result = app_mod._verify_eligibility(ins)
    assert result["status"] == "unknown"
    assert result["active"] is None


def test_non_2xx_response_is_unknown_not_inactive(monkeypatch):
    # A 503 with a FastAPI-style {"detail": ...} body is a dependency failure,
    # NOT a coverage denial — it must not be stamped inactive.
    body = {"detail": "Service Unavailable"}
    monkeypatch.setattr(app_mod.httpx, "get", lambda *a, **k: _FakeResp(body, status_code=503))
    ins = schemas_mod.Insurance(member_id=MEMBER_ID)
    result = app_mod._verify_eligibility(ins)
    assert result == {"active": None, "status": "unknown", "reason": "eligibility check failed"}


def test_non_json_body_is_unknown(monkeypatch):
    monkeypatch.setattr(
        app_mod.httpx, "get", lambda *a, **k: _FakeResp(ValueError("not json"), status_code=200)
    )
    ins = schemas_mod.Insurance(member_id=MEMBER_ID)
    result = app_mod._verify_eligibility(ins)
    assert result["status"] == "unknown"


def test_malformed_2xx_body_is_unknown(monkeypatch):
    # 2xx but not eligibility-shaped (no status, no active) -> degraded, not inactive.
    monkeypatch.setattr(
        app_mod.httpx, "get", lambda *a, **k: _FakeResp({"foo": "bar"}, status_code=200)
    )
    ins = schemas_mod.Insurance(member_id=MEMBER_ID)
    result = app_mod._verify_eligibility(ins)
    assert result["status"] == "unknown"


def test_no_insurance_skips():
    assert app_mod._verify_eligibility(None) is None
    assert app_mod._verify_eligibility(schemas_mod.Insurance()) is None
