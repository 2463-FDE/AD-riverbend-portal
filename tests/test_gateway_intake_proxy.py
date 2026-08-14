"""Tests for the gateway's POST /intake fan-out (E4-SPEC-11 .. E4-SPEC-18).

Registration is the route the intake contract break runs through: the portal
payload 422'd at intake-service and the inherited ``_post`` relayed that as a
200-OK ``{"error": ...}`` body, so the portal's success branch ran and the desk
was told a patient had been created that did not exist. These tests pin the
migrated contract — downstream status codes survive, transport failures map to
typed gateway errors, and neither a log record nor a response body ever carries
downstream content that could be PHI.

Harness copied from tests/test_gateway_ai_proxy.py: module pinning plus a
dependency override, httpx.post faked at the gateway module seam, no Redis or
DB I/O.
"""
import logging
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import load_module

_PINNED = ("config", "logging_config", "db", "models", "security")
_saved = {name: sys.modules.pop(name, None) for name in _PINNED}
sys.modules["config"] = load_module("services/gateway/config.py", "gw_intake_config")
sys.modules["logging_config"] = load_module(
    "services/gateway/logging_config.py", "gw_intake_logging_config"
)
sys.modules["db"] = load_module("services/gateway/db.py", "gw_intake_db")
sys.modules["models"] = load_module("services/gateway/models.py", "gw_intake_models")
sys.modules["security"] = load_module("services/gateway/security.py", "gw_intake_security")
gw = load_module("services/gateway/app.py", "gw_intake_app")
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

gw.app.dependency_overrides[gw.require_session] = lambda: {
    "username": "frontdesk",
    "role": "front_desk",
}
client = TestClient(gw.app, raise_server_exceptions=False)

# A registration payload with PHI in every field a downstream 422 could echo.
NAME = "Adversarial Q Testpatient"
SSN = "123-45-6789"
MEMBER_ID = "BCBS4471"
PAYLOAD = {
    "demographics": {"name": NAME, "dob": "1990-01-31", "ssn": SSN},
    "insurance": {"payer_name": "BCBS", "member_id": MEMBER_ID},
    "consents": ["npp_ack", "treatment_consent"],
}

# What FastAPI's own 422 body looks like: a LIST of errors, each carrying the
# offending `input` value. Relaying it verbatim would put the submitted SSN and
# member id in the gateway's response and in whatever the portal renders.
FASTAPI_422_BODY = {
    "detail": [
        {
            "type": "missing",
            "loc": ["body", "demographics", "name"],
            "msg": "Field required",
            "input": {"first_name": NAME, "ssn": SSN},
        },
        {
            "type": "string_type",
            "loc": ["body", "insurance", "member_id"],
            "msg": "Input should be a valid string",
            "input": MEMBER_ID,
        },
    ]
}


class _FakeResponse:
    def __init__(self, status_code=201, body=None, text_body=None):
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


def test_successful_registration_relays_the_downstream_body(monkeypatch):
    calls = _patch_post(
        monkeypatch,
        response=_FakeResponse(201, {"patient_id": 5001, "elapsed_seconds": 0.4}),
    )
    r = client.post("/intake", json=PAYLOAD)
    assert r.status_code == 200            # FastAPI's own default for this route
    assert r.json()["patient_id"] == 5001
    assert len(calls) == 1
    assert calls[0]["url"].endswith("/intake")


def test_downstream_422_is_relayed_as_422_not_200(monkeypatch):
    """E4-SPEC-11, E4-SPEC-13. The whole defect in one assertion: the inherited _post
    answered 200 with an {"error": ...} body here, and the portal's success
    branch ran on it."""
    _patch_post(monkeypatch, response=_FakeResponse(422, FASTAPI_422_BODY))
    r = client.post("/intake", json=PAYLOAD)
    assert r.status_code == 422
    assert "error" not in r.json()


def test_downstream_503_is_relayed_as_503(monkeypatch):
    _patch_post(
        monkeypatch,
        response=_FakeResponse(503, {"detail": "registration store unavailable"}),
    )
    r = client.post("/intake", json=PAYLOAD)
    assert r.status_code == 503
    assert r.json()["detail"] == "registration store unavailable"


def test_timeout_becomes_504(monkeypatch):
    """E4-SPEC-12. The inherited _post answered these with a 200."""
    _patch_post(monkeypatch, exc=httpx.TimeoutException("read timed out"))
    r = client.post("/intake", json=PAYLOAD)
    assert r.status_code == 504


def test_transport_failure_becomes_502(monkeypatch):
    """E4-SPEC-12 — intake-service unreachable."""
    _patch_post(monkeypatch, exc=httpx.ConnectError("connection refused"))
    r = client.post("/intake", json=PAYLOAD)
    assert r.status_code == 502


def test_non_json_downstream_body_becomes_502(monkeypatch):
    """E4-SPEC-12, E4-SPEC-13 — a body the gateway cannot read is a failure, not
    a success with an unusable payload."""
    _patch_post(monkeypatch, response=_FakeResponse(500, text_body="<html>502 Bad Gateway</html>"))
    r = client.post("/intake", json=PAYLOAD)
    assert r.status_code == 502


def test_value_rejection_and_system_failure_differ_by_status_class(monkeypatch):
    """E4-SPEC-14. The portal branches on the status CLASS alone — 400/422 is
    "correct it at the desk", anything else is "the system could not complete
    it" — so the two must never arrive as the same code."""
    _patch_post(monkeypatch, response=_FakeResponse(422, FASTAPI_422_BODY))
    rejected = client.post("/intake", json=PAYLOAD)
    _patch_post(monkeypatch, exc=httpx.ConnectError("connection refused"))
    failed = client.post("/intake", json=PAYLOAD)
    assert rejected.status_code // 100 == 4
    assert failed.status_code // 100 == 5


def test_no_phi_from_a_downstream_422_reaches_the_response_or_a_log(monkeypatch, caplog):
    """E4-SPEC-15, E4-SPEC-16 — the landmines §3 adversarial case for this path.

    FastAPI's 422 body is a list, not a plain "detail" string, so _post_checked
    must fall back to its generic detail. Relaying the list would put every
    rejected input value — here a name, an SSN and a member id — into the
    gateway's response body and into the portal's error banner.
    """
    _patch_post(monkeypatch, response=_FakeResponse(422, FASTAPI_422_BODY))
    with caplog.at_level(logging.DEBUG):
        r = client.post("/intake", json=PAYLOAD)
    assert r.status_code == 422

    haystacks = [r.text] + [rec.getMessage() for rec in caplog.records]
    for value in (NAME, SSN, MEMBER_ID, "1990-01-31", "Field required"):
        for haystack in haystacks:
            assert value not in haystack, f"downstream content leaked: {haystack!r}"


def test_transport_failure_logs_the_exception_class_only(monkeypatch, caplog):
    """E4-SPEC-15. str(e) on an httpx error embeds the request URL — the
    mechanism behind the eligibility member_id leak — so only the class name
    may reach a log record."""
    poison = "http://intake-service:8071/intake?trace=Adversarial-Q-Testpatient"
    _patch_post(monkeypatch, exc=httpx.ConnectError(f"failed to connect to {poison}"))
    with caplog.at_level(logging.DEBUG):
        r = client.post("/intake", json=PAYLOAD)
    assert r.status_code == 502

    messages = [rec.getMessage() for rec in caplog.records]
    assert messages, "a transport failure must log something"
    for message in messages:
        assert poison not in message
        assert "?trace=" not in message
        assert NAME not in message
    assert any("ConnectError" in m for m in messages)


def test_registration_fan_out_is_bounded_by_the_configured_timeout(monkeypatch):
    """E4-SPEC-17. The bound is configured, not the hardcoded 30 the inherited
    _post carried — tests/test_eligibility_budget_alignment.py pins its value
    against intake's own budget."""
    calls = _patch_post(monkeypatch, response=_FakeResponse(201, {"patient_id": 1}))
    client.post("/intake", json=PAYLOAD)
    assert calls[0]["timeout"] == gw.settings.intake_timeout_seconds
    assert calls[0]["timeout"] is not None


def test_gateway_forwards_the_submission_identifier_unchanged(monkeypatch):
    """e5b-SPEC-5. proxy_intake takes an opaque dict and passes it through, so the
    submission_id survives byte-for-byte and the gateway generates, substitutes,
    or drops nothing. The forwarded body must equal the received one exactly."""
    sid = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
    payload = {**PAYLOAD, "submission_id": sid}
    calls = _patch_post(monkeypatch, response=_FakeResponse(201, {"patient_id": 1}))
    client.post("/intake", json=payload)
    forwarded = calls[0]["json"]
    assert forwarded["submission_id"] == sid   # forwarded unchanged
    assert forwarded == payload                # nothing added, dropped, or substituted


def test_downstream_409_is_relayed_as_409(monkeypatch):
    """e5b-SPEC-13/D-15. A corrected-retry mismatch is a 409 with a constant
    non-PHI detail; _post_checked relays it, and the portal's existing non-400/422
    arm renders the system-failure message — no gateway edit, no new portal
    branch."""
    _patch_post(
        monkeypatch,
        response=_FakeResponse(
            409, {"detail": "registration content does not match the original submission"}
        ),
    )
    r = client.post("/intake", json=PAYLOAD)
    assert r.status_code == 409
    assert r.json()["detail"] == "registration content does not match the original submission"


def test_a_role_without_patients_write_never_reaches_intake(monkeypatch):
    """The capability check (ADR 0017) still runs ahead of the fan-out — the
    migration changes the error contract, not the authz boundary."""
    calls = _patch_post(monkeypatch, response=_FakeResponse(201, {"patient_id": 1}))
    gw.app.dependency_overrides[gw.require_session] = lambda: {
        "username": "roiclerk",
        "role": "roi_clerk",          # holds patients.read, never patients.write
    }
    try:
        r = client.post("/intake", json=PAYLOAD)
    finally:
        gw.app.dependency_overrides[gw.require_session] = lambda: {
            "username": "frontdesk",
            "role": "front_desk",
        }
    assert r.status_code == 403
    assert calls == []
