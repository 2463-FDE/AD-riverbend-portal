"""Tests for the gateway's GET /schedule proxy (_get_checked).

Codex PR #26 r1: the route originally used the inherited ``_get``, which returns
``r.json()`` without looking at ``r.status_code``. Scheduling answers 422 for a
bad date or an over-limit page and 503 when the database is down, and every one
of those reached the portal as a 200 with an error body — a front desk seeing an
empty day queue instead of an outage. These tests pin the read-side contract of
``_get_checked``: real status codes out, and the downstream URL (which for a GET
carries the query string, i.e. the identifiers) never in a response or a log.

No Redis/DB I/O: require_session is dependency-overridden and httpx.get is faked
at the gateway module seam.
"""
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import load_module

_PINNED = ("config", "logging_config", "db", "models", "security")
_saved = {name: sys.modules.pop(name, None) for name in _PINNED}
sys.modules["config"] = load_module("services/gateway/config.py", "gw_sched_config")
sys.modules["logging_config"] = load_module(
    "services/gateway/logging_config.py", "gw_sched_logging_config"
)
sys.modules["db"] = load_module("services/gateway/db.py", "gw_sched_db")
sys.modules["models"] = load_module("services/gateway/models.py", "gw_sched_models")
sys.modules["security"] = load_module("services/gateway/security.py", "gw_sched_security")
gw = load_module("services/gateway/app.py", "gw_sched_app")
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

# What an httpx exception can carry on a GET: the full URL *including* the query
# string. On this route that is the clinic day; on a sibling read it is a member
# id or an MRN. Neither may reach a log line or a response body.
POISON_URL = "http://scheduling-service:8074/schedule?date=2026-08-01&mrn=M4417"


class _FakeResponse:
    def __init__(self, status_code=200, body=None, text_body=None):
        self.status_code = status_code
        self._body = body
        self._text = text_body

    def json(self):
        if self._text is not None:
            raise ValueError("not json")
        return self._body


def _patch_get(monkeypatch, response=None, exc=None):
    calls = []

    def _fake_get(url, params=None, timeout=None):
        calls.append({"url": url, "params": params, "timeout": timeout})
        if exc is not None:
            raise exc
        return response

    monkeypatch.setattr(gw.httpx, "get", _fake_get)
    return calls


def _ok_body(count=0):
    return {
        "items": [],
        "count": count,
        "limit": 50,
        "offset": 0,
        "date": "2026-08-01",
        "timezone": "America/New_York",
    }


# --------------------------------------------------------------------------- #
# the happy path and what is forwarded
# --------------------------------------------------------------------------- #
def test_success_relays_downstream_body(monkeypatch):
    calls = _patch_get(monkeypatch, response=_FakeResponse(200, _ok_body()))

    r = client.get("/schedule?date=2026-08-01")

    assert r.status_code == 200
    assert r.json()["timezone"] == "America/New_York"
    assert len(calls) == 1
    assert calls[0]["url"].endswith("/schedule")
    assert calls[0]["params"] == {"date": "2026-08-01", "limit": 50, "offset": 0}


def test_paging_params_are_forwarded(monkeypatch):
    calls = _patch_get(monkeypatch, response=_FakeResponse(200, _ok_body()))

    assert client.get("/schedule?date=2026-08-01&limit=10&offset=20").status_code == 200
    assert calls[0]["params"]["limit"] == 10
    assert calls[0]["params"]["offset"] == 20


def test_provider_id_is_not_forwarded(monkeypatch):
    """Codex r1: the provider filter joined ``slots`` through a column with no
    foreign key, so an appointment with a stale slot vanished from a per-provider
    day with no error. It was removed from the service; the gateway must not
    keep forwarding it, or the parameter looks supported and does nothing.
    """
    calls = _patch_get(monkeypatch, response=_FakeResponse(200, _ok_body()))

    assert client.get("/schedule?date=2026-08-01&provider_id=7").status_code == 200
    assert "provider_id" not in calls[0]["params"]


# --------------------------------------------------------------------------- #
# failures stay failures (the r1 finding)
# --------------------------------------------------------------------------- #
def test_bad_date_relays_422_not_200(monkeypatch):
    _patch_get(
        monkeypatch,
        response=_FakeResponse(422, {"detail": [{"loc": ["query", "date"], "msg": "invalid"}]}),
    )

    r = client.get("/schedule?date=not-a-date")

    assert r.status_code == 422
    # A list detail is not the plain-string FastAPI shape, so it stays generic
    # rather than being relayed structurally.
    assert r.json()["detail"] == "scheduling service error"


def test_over_limit_relays_422_not_200(monkeypatch):
    # The gateway's own Query(le=200) rejects this before any fan-out, which is
    # the cheaper half of the same guarantee.
    calls = _patch_get(monkeypatch, response=_FakeResponse(200, _ok_body()))

    r = client.get("/schedule?date=2026-08-01&limit=9999")

    assert r.status_code == 422
    assert calls == []


def test_downstream_503_relays_503_not_200(monkeypatch):
    """The finding in one assertion: an outage must not look like an empty day."""
    _patch_get(monkeypatch, response=_FakeResponse(503, {"detail": "database unavailable"}))

    r = client.get("/schedule?date=2026-08-01")

    assert r.status_code == 503
    assert r.json()["detail"] == "database unavailable"
    assert "items" not in r.json()


def test_timeout_is_504(monkeypatch):
    _patch_get(monkeypatch, exc=httpx.ReadTimeout("timed out", request=None))

    r = client.get("/schedule?date=2026-08-01")

    assert r.status_code == 504
    assert r.json()["detail"] == "scheduling service timed out"


def test_transport_error_is_502(monkeypatch):
    _patch_get(monkeypatch, exc=httpx.ConnectError("connection refused", request=None))

    r = client.get("/schedule?date=2026-08-01")

    assert r.status_code == 502
    assert r.json()["detail"] == "scheduling service unreachable"


def test_non_json_downstream_is_502(monkeypatch):
    _patch_get(monkeypatch, response=_FakeResponse(200, text_body="<html>504 Gateway Timeout</html>"))

    r = client.get("/schedule?date=2026-08-01")

    assert r.status_code == 502
    assert r.json()["detail"] == "scheduling service returned a bad response"


# --------------------------------------------------------------------------- #
# adversarial: the URL/query string must not leak (CLAUDE.md §5)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "exc,status",
    [
        (httpx.ReadTimeout(POISON_URL, request=None), 504),
        (httpx.ConnectError(POISON_URL, request=None), 502),
    ],
)
def test_exception_text_never_reaches_the_log_or_the_response(monkeypatch, caplog, exc, status):
    """Adversarial placement: the identifiers are put where the code does not
    look — inside the exception's own message, which the legacy ``_get`` copies
    verbatim into both ``log.error`` and the 200-OK body it returns.
    """
    _patch_get(monkeypatch, exc=exc)

    with caplog.at_level("DEBUG"):
        r = client.get("/schedule?date=2026-08-01")

    assert r.status_code == status
    for leak in (POISON_URL, "M4417", "scheduling-service:8074"):
        assert leak not in caplog.text, f"{leak!r} reached the log"
        assert leak not in r.text, f"{leak!r} reached the response"
    # Something diagnosable still has to survive: the timeout branch logs the
    # budget it blew, the transport branch logs the exception CLASS. Neither
    # logs str(e). Mirrors _post_checked.
    if status == 504:
        assert "timed out after 30s" in caplog.text
    else:
        assert type(exc).__name__ in caplog.text


def test_downstream_error_body_cannot_smuggle_a_structure(monkeypatch):
    """A non-string ``detail`` is not relayed — a downstream service (or anything
    that can shape its response) must not be able to push arbitrary content,
    including PHI, through the gateway's error path.
    """
    _patch_get(monkeypatch, response=_FakeResponse(500, {"detail": {"mrn": "M4417"}}))

    r = client.get("/schedule?date=2026-08-01")

    assert r.status_code == 500
    assert r.json()["detail"] == "scheduling service error"
    assert "M4417" not in r.text
