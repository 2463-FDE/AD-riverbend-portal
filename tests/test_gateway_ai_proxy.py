"""Tests for the gateway's /ai/intake-instructions fan-out (_post_checked).

The inherited _post/_get helpers collapse every failure into a 200-OK
{"error": str(e)} body, and str(e) on an httpx error can embed the request URL
and its query params (the eligibility member_id leak, PR #2 era). New routes
use _post_checked instead; these tests pin the contract: real status codes,
exception CLASS only in logs, downstream URL never in a response or log line.

No Redis/DB I/O: require_session is dependency-overridden and httpx.post is
faked at the gateway module seam.
"""
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import load_module

_PINNED = ("config", "logging_config", "db", "models", "security")
_saved = {name: sys.modules.pop(name, None) for name in _PINNED}
sys.modules["config"] = load_module("services/gateway/config.py", "gw_ai_config")
sys.modules["logging_config"] = load_module(
    "services/gateway/logging_config.py", "gw_ai_logging_config"
)
sys.modules["db"] = load_module("services/gateway/db.py", "gw_ai_db")
sys.modules["models"] = load_module("services/gateway/models.py", "gw_ai_models")
sys.modules["security"] = load_module("services/gateway/security.py", "gw_ai_security")
gw = load_module("services/gateway/app.py", "gw_ai_app")
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

gw.app.dependency_overrides[gw.require_session] = lambda: {
    "username": "frontdesk",
    "role": "staff",
}
client = TestClient(gw.app, raise_server_exceptions=False)

# The poison string an httpx exception can carry: the full downstream URL.
POISON_URL = "http://ai-assistant:8077/intake-instructions?member_id=AET123"


class _FakeResponse:
    def __init__(self, status_code=200, body=None, text_body=None):
        self.status_code = status_code
        self._body = body
        self._text = text_body

    def json(self):
        if self._text is not None:
            raise ValueError("not json")
        return self._body


def _patch_post(monkeypatch, response=None, exc=None):
    calls = []

    def _fake_post(url, json=None, timeout=None, headers=None):
        calls.append({"url": url, "json": json, "timeout": timeout, "headers": headers})
        if exc is not None:
            raise exc
        return response

    monkeypatch.setattr(gw.httpx, "post", _fake_post)
    return calls


def test_success_relays_downstream_body(monkeypatch):
    calls = _patch_post(
        monkeypatch,
        response=_FakeResponse(200, {"items": ["Bring a photo ID."], "disclaimer": "d"}),
    )
    r = client.post("/ai/intake-instructions", json={"has_insurance": True})
    assert r.status_code == 200
    assert r.json()["items"] == ["Bring a photo ID."]
    assert len(calls) == 1
    assert calls[0]["url"].endswith("/intake-instructions")
    # The LLM fan-out is explicitly bounded (never the D4 no-timeout pattern).
    assert calls[0]["timeout"] == gw.settings.ai_read_timeout_seconds


def test_internal_auth_header_attached_and_never_logged(monkeypatch, caplog):
    # Service-to-service auth (Codex PR #7 round 3): the gateway is the only
    # holder of the shared secret and must attach it on the ai fan-out; the
    # value is a secret and must never reach a log record or the response.
    secret = "s2s-secret-value-do-not-log"
    monkeypatch.setattr(gw.settings, "ai_proxy_shared_secret", secret)
    calls = _patch_post(
        monkeypatch, response=_FakeResponse(200, {"items": ["x"], "disclaimer": "d"})
    )
    with caplog.at_level("DEBUG"):
        r = client.post("/ai/intake-instructions", json={"has_insurance": True})
    assert r.status_code == 200
    assert calls[0]["headers"]["X-Internal-Auth"] == secret
    assert secret not in caplog.text
    assert secret not in r.text


def test_downstream_error_status_is_relayed_not_200(monkeypatch):
    # Pre-_post_checked behavior returned 200 {"error": ...} for every failure.
    _patch_post(monkeypatch, response=_FakeResponse(503, {"detail": "assistant is not configured"}))
    r = client.post("/ai/intake-instructions", json={"has_insurance": True})
    assert r.status_code == 503
    assert r.json()["detail"] == "assistant is not configured"


def test_non_string_downstream_detail_stays_generic(monkeypatch):
    _patch_post(monkeypatch, response=_FakeResponse(500, {"detail": {"trace": POISON_URL}}))
    r = client.post("/ai/intake-instructions", json={})
    assert r.status_code == 500
    assert POISON_URL not in r.text


def test_timeout_maps_to_504(monkeypatch, caplog):
    _patch_post(monkeypatch, exc=httpx.ReadTimeout(POISON_URL))
    with caplog.at_level("ERROR"):
        r = client.post("/ai/intake-instructions", json={"has_insurance": True})
    assert r.status_code == 504
    assert POISON_URL not in r.text
    assert POISON_URL not in caplog.text


def test_transport_error_maps_to_502_and_logs_class_only(monkeypatch, caplog):
    # Adversarial: the exception message carries the downstream URL + a
    # member_id-shaped query param. Neither may reach the response or the log —
    # only the exception class name may be logged.
    _patch_post(monkeypatch, exc=httpx.ConnectError(POISON_URL))
    with caplog.at_level("ERROR"):
        r = client.post("/ai/intake-instructions", json={"has_insurance": True})
    assert r.status_code == 502
    assert POISON_URL not in r.text
    assert "AET123" not in r.text
    assert POISON_URL not in caplog.text
    assert "AET123" not in caplog.text
    assert "ConnectError" in caplog.text


def test_non_json_downstream_body_maps_to_502(monkeypatch):
    _patch_post(monkeypatch, response=_FakeResponse(200, text_body="<html>proxy error</html>"))
    r = client.post("/ai/intake-instructions", json={})
    assert r.status_code == 502


def test_route_requires_session():
    # Remove the override for this one call: anonymous callers are rejected.
    gw.app.dependency_overrides.pop(gw.require_session)
    try:
        r = client.post("/ai/intake-instructions", json={"has_insurance": True})
        assert r.status_code == 401
    finally:
        gw.app.dependency_overrides[gw.require_session] = lambda: {
            "username": "frontdesk",
            "role": "staff",
        }
