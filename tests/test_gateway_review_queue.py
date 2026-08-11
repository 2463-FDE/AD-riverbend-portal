"""Tests for the gateway's duplicate-review-queue fan-out (W2-SPEC-26, 28).

Two contracts live here, neither of which the intake-service tests can see:

  * **The deciding user comes from the session.** A disposition is the record
    of who judged two charts to be one person. A client-supplied ``decided_by``
    would let any front-desk user file that judgment under a colleague's name,
    so the gateway overwrites it from the session hash unconditionally.
  * **``_get_checked`` surfaces failure as failure.** The inherited ``_get``
    collapses every failure into a 200-OK ``{"error": str(e)}`` body — a caller
    cannot tell an outage from an empty queue, and ``str(e)`` can carry the
    downstream URL into a log. The new read route uses the checked helper.

No Redis/DB I/O: require_session is dependency-overridden and httpx is faked at
the gateway module seam.
"""
import logging
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import load_module

_PINNED = ("config", "logging_config", "db", "models", "security", "authz")
_saved = {name: sys.modules.pop(name, None) for name in _PINNED}
sys.modules["config"] = load_module("services/gateway/config.py", "gw_rq_config")
sys.modules["logging_config"] = load_module(
    "services/gateway/logging_config.py", "gw_rq_logging_config"
)
sys.modules["db"] = load_module("services/gateway/db.py", "gw_rq_db")
sys.modules["models"] = load_module("services/gateway/models.py", "gw_rq_models")
sys.modules["security"] = load_module("services/gateway/security.py", "gw_rq_security")
sys.modules["authz"] = load_module("services/gateway/authz.py", "gw_rq_authz")
gw = load_module("services/gateway/app.py", "gw_rq_app")
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

gw.app.dependency_overrides[gw.require_session] = lambda: {
    "username": "fdesk1",
    "role": "front_desk",
}
client = TestClient(gw.app, raise_server_exceptions=False)

INTAKE_URL = gw.SERVICES["intake"]


class _Resp:
    def __init__(self, status_code=200, payload=None, text_body=None):
        self.status_code = status_code
        self._payload = payload
        self._text = text_body

    def json(self):
        if self._text is not None:
            raise ValueError("not JSON")
        return self._payload


# ----------------------------------------------------------- decided_by

def test_disposition_stamps_the_session_username(monkeypatch):
    seen = {}

    def fake_post(url, json=None, timeout=None, headers=None):
        seen["url"] = url
        seen["json"] = json
        return _Resp(payload={"id": 1, "status": "dispositioned"})

    monkeypatch.setattr(gw.httpx, "post", fake_post)
    r = client.post("/review-queue/1/disposition", json={"disposition": "not_duplicate"})
    assert r.status_code == 200
    assert seen["url"] == f"{INTAKE_URL}/review-queue/1/disposition"
    assert seen["json"]["decided_by"] == "fdesk1"


def test_client_supplied_decided_by_is_discarded(monkeypatch):
    """The forged-attribution case. A reviewer must not be able to file a
    duplicate judgment under someone else's name."""
    seen = {}

    def fake_post(url, json=None, timeout=None, headers=None):
        seen["json"] = json
        return _Resp(payload={"id": 1, "status": "dispositioned"})

    monkeypatch.setattr(gw.httpx, "post", fake_post)
    r = client.post(
        "/review-queue/1/disposition",
        json={"disposition": "duplicate_confirmed", "decided_by": "chief_of_staff"},
    )
    assert r.status_code == 200
    assert seen["json"]["decided_by"] == "fdesk1"
    assert "chief_of_staff" not in str(seen["json"])


# ------------------------------------------------------- _get_checked contract

def test_queue_read_relays_the_downstream_body(monkeypatch):
    payload = {"items": [{"id": 1, "source": "retroactive"}]}
    monkeypatch.setattr(gw.httpx, "get", lambda *a, **k: _Resp(payload=payload))
    r = client.get("/review-queue")
    assert r.status_code == 200
    assert r.json() == payload


def test_queue_read_timeout_is_504_not_a_200_error_body(monkeypatch, caplog):
    def boom(*a, **k):
        raise httpx.ReadTimeout("timed out reading from http://intake-service:8071/review-queue")

    monkeypatch.setattr(gw.httpx, "get", boom)
    with caplog.at_level(logging.ERROR):
        r = client.get("/review-queue")
    assert r.status_code == 504
    assert "error" not in r.json()
    for record in caplog.records:
        assert "intake-service:8071" not in record.getMessage()


def test_queue_read_transport_error_is_502(monkeypatch, caplog):
    def boom(*a, **k):
        raise httpx.ConnectError("connection refused to http://intake-service:8071/review-queue")

    monkeypatch.setattr(gw.httpx, "get", boom)
    with caplog.at_level(logging.ERROR):
        r = client.get("/review-queue")
    assert r.status_code == 502
    errors = [rec.getMessage() for rec in caplog.records if rec.levelno >= logging.ERROR]
    assert any("ConnectError" in m for m in errors)
    for message in errors:
        assert "connection refused" not in message
        assert "intake-service:8071" not in message


def test_queue_read_non_json_body_is_502(monkeypatch):
    monkeypatch.setattr(gw.httpx, "get", lambda *a, **k: _Resp(text_body="<html>502</html>"))
    r = client.get("/review-queue")
    assert r.status_code == 502


@pytest.mark.parametrize("status", [404, 409, 503])
def test_downstream_status_codes_are_relayed_not_flattened(monkeypatch, status):
    monkeypatch.setattr(
        gw.httpx, "post",
        lambda *a, **k: _Resp(status_code=status, payload={"detail": "review pair not found"}),
    )
    r = client.post("/review-queue/77/disposition", json={"disposition": "not_duplicate"})
    assert r.status_code == status
    assert r.json()["detail"] == "review pair not found"


# test_queue_routes_never_use_the_swallowing_helpers lived here until e5
# (2026-08-11, plan D-16). It proved the claim behaviourally, by monkeypatching
# _get/_post to explode — which stops being possible once e5 DELETES them
# (E5-SPEC-20): the test would fail at setattr, and its assertion would be
# vacuous besides. The claim is re-homed as a structural scan in
# tests/test_gateway_proxy_error_contract.py — no such helper exists to avoid.
