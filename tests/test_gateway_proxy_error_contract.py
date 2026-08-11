"""The gateway's estate-wide proxy error contract (E5-SPEC-1 .. E5-SPEC-21).

e4 migrated ONE route (``POST /intake``) off the inherited ``_post``/``_get``
helpers, which collapse every downstream and transport failure into a 200-OK
``{"error": str(e)}`` body and log ``str(e)``. e5 converts the remaining
thirteen and deletes the helpers, so the shape cannot come back.

Everything here is driven by ``ROUTES`` — one row per converted route. The
success-path cases are CHARACTERIZATION tests (``docs/landmines.md`` §3): they
were written and run GREEN against the unconverted gateway before any call site
moved, so the diff is provably an error-path change only (E5-SPEC-13,
E5-SPEC-14).

Harness copied from tests/test_gateway_intake_proxy.py: module pinning plus a
dependency override, httpx faked at the gateway module seam, no Redis or DB I/O.
"""
import logging
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

import httpx
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from conftest import REPO_ROOT, load_module

_PINNED = ("config", "logging_config", "db", "models", "security", "authz")
_saved = {name: sys.modules.pop(name, None) for name in _PINNED}
sys.modules["config"] = load_module("services/gateway/config.py", "gw_pec_config")
sys.modules["logging_config"] = load_module(
    "services/gateway/logging_config.py", "gw_pec_logging_config"
)
sys.modules["db"] = load_module("services/gateway/db.py", "gw_pec_db")
sys.modules["models"] = load_module("services/gateway/models.py", "gw_pec_models")
sys.modules["security"] = load_module("services/gateway/security.py", "gw_pec_security")
sys.modules["authz"] = load_module("services/gateway/authz.py", "gw_pec_authz")
gw = load_module("services/gateway/app.py", "gw_pec_app")
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

client = TestClient(gw.app, raise_server_exceptions=False)


@dataclass(frozen=True)
class Route:
    """One converted proxy route, and the downstream call it must issue."""

    id: str
    method: str
    path: str                       # as called on the gateway
    template: str                   # the route's declared path template
    role: str                       # a role holding the route's capability
    service: str                    # SERVICES key
    downstream: str                 # path at the downstream service
    params: Optional[dict] = None   # GET only, post-_clean
    payload: Optional[dict] = None  # POST only

    @property
    def url(self) -> str:
        return f"{gw.SERVICES[self.service]}{self.downstream}"


# The thirteen routes e5 converts. `staff` is never used as the role: each row
# names a role that really holds the route's capability in config/roles.yaml,
# so a capability regression shows up here as a 403 rather than passing under a
# universal grant.
ROUTES = [
    Route(
        id="eligibility",
        method="GET",
        path="/eligibility?insurance_id=BCBS4471",
        template="/eligibility",
        role="front_desk",
        service="eligibility",
        downstream="/eligibility",
        params={"insurance_id": "BCBS4471"},
    ),
    Route(
        id="patients",
        method="GET",
        path="/patients?q=gonzalez&limit=25&offset=0",
        template="/patients",
        role="front_desk",
        service="records",
        downstream="/patients",
        params={"q": "gonzalez", "limit": 25, "offset": 0},
    ),
    Route(
        id="patient",
        method="GET",
        path="/patients/1042",
        template="/patients/{patient_id}",
        role="front_desk",
        service="records",
        downstream="/patients/1042",
        params={},
    ),
    Route(
        id="records",
        method="GET",
        path="/patients/1042/records",
        template="/patients/{patient_id}/records",
        role="clinician",
        service="records",
        downstream="/patients/1042/records",
        params={},
    ),
    Route(
        id="search",
        method="GET",
        path="/records/search?q=gonzalez",
        template="/records/search",
        role="clinician",
        service="records",
        downstream="/records/search",
        params={"q": "gonzalez"},
    ),
    Route(
        id="slots",
        method="GET",
        path="/slots?provider_id=3&limit=50",
        template="/slots",
        role="front_desk",
        service="scheduling",
        downstream="/slots",
        params={"provider_id": 3, "limit": 50},
    ),
    Route(
        id="list_appointments",
        method="GET",
        path="/appointments?patient_id=1042",
        template="/appointments",
        role="front_desk",
        service="scheduling",
        downstream="/appointments",
        params={"patient_id": 1042},
    ),
    Route(
        id="roi_list",
        method="GET",
        path="/roi/requests?patient_id=1042",
        template="/roi/requests",
        role="roi_clerk",
        service="roi",
        downstream="/roi/requests",
        params={"patient_id": 1042},
    ),
    Route(
        id="book",
        method="POST",
        path="/appointments",
        template="/appointments",
        role="front_desk",
        service="scheduling",
        downstream="/appointments",
        payload={"patient_id": 1042, "slot_id": 88},
    ),
    Route(
        id="cancel",
        method="POST",
        path="/appointments/77/cancel",
        template="/appointments/{appointment_id}/cancel",
        role="front_desk",
        service="scheduling",
        downstream="/appointments/77/cancel",
        payload={},
    ),
    Route(
        id="roi_create",
        method="POST",
        path="/roi/requests",
        template="/roi/requests",
        role="roi_clerk",
        service="roi",
        downstream="/roi/requests",
        payload={"patient_id": 1042, "recipient": "Dr Vance"},
    ),
    Route(
        id="roi_fulfill",
        method="POST",
        path="/roi/requests/77/fulfill",
        template="/roi/requests/{request_id}/fulfill",
        role="roi_clerk",
        service="roi",
        downstream="/roi/requests/77/fulfill",
        payload={},
    ),
    Route(
        id="hl7",
        method="POST",
        path="/hl7/ingest",
        template="/hl7/ingest",
        role="admin",
        service="interop",
        downstream="/hl7/ingest",
        payload={"message": "MSH|^~\\&|LAB|..."},
    ),
]

ROUTE_IDS = [r.id for r in ROUTES]


class _FakeResponse:
    def __init__(self, status_code=200, body=None, text_body=None):
        self.status_code = status_code
        self._body = body
        self._text = text_body

    def json(self):
        if self._text is not None:
            raise ValueError("not json")
        return self._body


def _login_as(role, username="testuser"):
    gw.app.dependency_overrides[gw.require_session] = lambda: {
        "username": username,
        "role": role,
    }


def teardown_function():
    gw.app.dependency_overrides.clear()


def _patch_transport(monkeypatch, response=None, exc=None):
    """Fake httpx at the gateway seam, capturing every outbound call.

    Both the inherited and the checked helpers are covered by one pair of
    signatures, which is what lets the success cases run unchanged before and
    after the conversion.
    """
    calls = []

    def _fake_get(url, params=None, timeout=None):
        calls.append({"url": url, "params": params, "json": None, "timeout": timeout})
        if exc is not None:
            raise exc
        return response

    def _fake_post(url, json=None, timeout=None, headers=None):
        calls.append({"url": url, "params": None, "json": json, "timeout": timeout})
        if exc is not None:
            raise exc
        return response

    monkeypatch.setattr(gw.httpx, "get", _fake_get)
    monkeypatch.setattr(gw.httpx, "post", _fake_post)
    return calls


def _call(route: Route):
    return client.request(
        route.method, route.path, json=route.payload if route.method == "POST" else None
    )


# --------------------------------------------------------------------------- #
# 1. Characterization: success behaviour is unchanged (E5-SPEC-13, E5-SPEC-14)
#
# Written and run green against the UNCONVERTED gateway. If either reddens
# after the conversion, the change did something it is forbidden to do.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("route", ROUTES, ids=ROUTE_IDS)
def test_a_successful_proxy_relays_the_downstream_status_and_body(monkeypatch, route):
    """E5-SPEC-13. The regression floor: e5 is an error-path change only."""
    body = {"items": [{"id": 1, "note": "downstream"}], "total": 1}
    _patch_transport(monkeypatch, response=_FakeResponse(200, body))
    _login_as(route.role)

    r = _call(route)

    assert r.status_code == 200
    assert r.json() == body


@pytest.mark.parametrize("route", ROUTES, ids=ROUTE_IDS)
def test_the_downstream_call_is_unchanged(monkeypatch, route):
    """E5-SPEC-14. Same service, same path, same params, same payload — the
    guard against a silent second change riding along with the conversion."""
    calls = _patch_transport(monkeypatch, response=_FakeResponse(200, {"ok": True}))
    _login_as(route.role)

    _call(route)

    assert len(calls) == 1
    assert calls[0]["url"] == route.url
    assert calls[0]["params"] == route.params
    assert calls[0]["json"] == route.payload


@pytest.mark.parametrize("route", ROUTES, ids=ROUTE_IDS)
def test_a_downstream_list_body_is_relayed_as_a_list(monkeypatch, route):
    """E5-SPEC-13. Several of these routes answer with a bare JSON array; a
    conversion that wrapped or coerced it would break every portal read
    surface at once."""
    _patch_transport(monkeypatch, response=_FakeResponse(200, [{"id": 7}]))
    _login_as(route.role)

    r = _call(route)

    assert r.status_code == 200
    assert r.json() == [{"id": 7}]


# --------------------------------------------------------------------------- #
# 2. A downstream failure reaches the caller as a failure (E5-SPEC-1)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("status", [400, 404, 409, 422, 500, 503])
@pytest.mark.parametrize("route", ROUTES, ids=ROUTE_IDS)
def test_a_downstream_failure_is_relayed_not_flattened(monkeypatch, route, status):
    """E5-SPEC-1. The whole defect in one assertion: the inherited helpers
    answered 200 with an ``{"error": ...}`` body for every one of these."""
    _patch_transport(
        monkeypatch, response=_FakeResponse(status, {"detail": "downstream said no"})
    )
    _login_as(route.role)

    r = _call(route)

    assert r.status_code == status
    assert r.json()["detail"] == "downstream said no"


# --------------------------------------------------------------------------- #
# 3. A call that could not be completed is distinguishable (E5-SPEC-2)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("route", ROUTES, ids=ROUTE_IDS)
def test_a_timeout_becomes_504(monkeypatch, route):
    """E5-SPEC-2 — the gateway's own bound expired."""
    _patch_transport(monkeypatch, exc=httpx.TimeoutException("read timed out"))
    _login_as(route.role)

    assert _call(route).status_code == 504


@pytest.mark.parametrize("route", ROUTES, ids=ROUTE_IDS)
def test_a_transport_failure_becomes_502(monkeypatch, route):
    """E5-SPEC-2 — the service is unreachable."""
    _patch_transport(monkeypatch, exc=httpx.ConnectError("connection refused"))
    _login_as(route.role)

    assert _call(route).status_code == 502


@pytest.mark.parametrize("route", ROUTES, ids=ROUTE_IDS)
def test_a_failure_to_complete_differs_in_class_from_a_rejection(monkeypatch, route):
    """E5-SPEC-2. The portal branches on the status CLASS, so "the request was
    rejected" and "the call never completed" must never arrive as one code."""
    _patch_transport(monkeypatch, response=_FakeResponse(422, {"detail": "rejected"}))
    _login_as(route.role)
    rejected = _call(route)

    _patch_transport(monkeypatch, exc=httpx.ConnectError("connection refused"))
    _login_as(route.role)
    incomplete = _call(route)

    assert rejected.status_code // 100 == 4
    assert incomplete.status_code // 100 == 5


# --------------------------------------------------------------------------- #
# 4. No success status ever carries an error body (E5-SPEC-3)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "failure",
    [
        pytest.param({"response": _FakeResponse(503, {"detail": "unavailable"})}, id="downstream-503"),
        pytest.param({"response": _FakeResponse(422, {"detail": "rejected"})}, id="downstream-422"),
        pytest.param({"exc": httpx.TimeoutException("read timed out")}, id="timeout"),
        pytest.param({"exc": httpx.ConnectError("connection refused")}, id="connect-error"),
        pytest.param({"response": _FakeResponse(500, text_body="<html>502</html>")}, id="non-json"),
    ],
)
@pytest.mark.parametrize("route", ROUTES, ids=ROUTE_IDS)
def test_no_failure_answers_success_or_carries_an_error_key(monkeypatch, route, failure):
    """E5-SPEC-3. Kills the 200-with-error-body shape estate-wide."""
    _patch_transport(monkeypatch, **failure)
    _login_as(route.role)

    r = _call(route)

    assert r.status_code >= 400, "a failure answered with a success status"
    body = r.json()
    assert not (isinstance(body, dict) and "error" in body)


# --------------------------------------------------------------------------- #
# 5. No exception text, URL or query value on any failure path
#    (E5-SPEC-9, E5-SPEC-10) — the landmines §3 adversarial case
# --------------------------------------------------------------------------- #
POISON_URL = "http://records-service:8073/records/search?q=Quentin+Gonzalez"


@pytest.mark.parametrize("route", ROUTES, ids=ROUTE_IDS)
def test_a_poisoned_exception_reaches_neither_the_response_nor_a_log(
    monkeypatch, caplog, route
):
    """E5-SPEC-9, E5-SPEC-10. ``str(e)`` on an httpx error embeds the request
    URL and its query parameters — the mechanism behind the eligibility
    member_id leak. Only the exception CLASS may reach a log record, and
    nothing of it may reach the response."""
    _patch_transport(monkeypatch, exc=httpx.ConnectError(f"failed to connect to {POISON_URL}"))
    _login_as(route.role)

    with caplog.at_level(logging.DEBUG):
        r = _call(route)

    assert r.status_code == 502
    # Scoped to what the GATEWAY emits. caplog also captures the httpx library's
    # own INFO line for the TestClient's INBOUND request to this process — a
    # harness artifact carrying the test's own URL, which would make the scan
    # below fail on a leak the gateway did not commit. (That httpx emits request
    # URLs at INFO is real and estate-wide, but it is neither this route's log
    # entry nor something e5 changes — see docs/workflow/e5/pr-body.md.)
    messages = [rec.getMessage() for rec in caplog.records if rec.name == "gateway"]
    assert messages, "a transport failure must log something"
    for haystack in [r.text] + messages:
        assert POISON_URL not in haystack
        assert "Quentin" not in haystack
        assert "?q=" not in haystack
        assert "failed to connect" not in haystack
    assert any("ConnectError" in m for m in messages)


@pytest.mark.parametrize("route", ROUTES, ids=ROUTE_IDS)
def test_a_downstream_error_body_that_is_not_a_detail_string_is_not_relayed(
    monkeypatch, route
):
    """E5-SPEC-10. FastAPI's own 422 body is a LIST of errors, each carrying the
    offending ``input`` value; relaying it would put submitted values into the
    gateway's response."""
    _patch_transport(
        monkeypatch,
        response=_FakeResponse(
            422,
            {"detail": [{"loc": ["body", "ssn"], "input": "123-45-6789", "msg": "bad"}]},
        ),
    )
    _login_as(route.role)

    r = _call(route)

    assert r.status_code == 422
    assert "123-45-6789" not in r.text


# --------------------------------------------------------------------------- #
# 6. The route set is closed (E5-SPEC-4)
# --------------------------------------------------------------------------- #
# Routes that legitimately do not fan out to a domain service.
NON_PROXY_ROUTES = {
    ("GET", "/healthz"),
    ("POST", "/login"),
    ("POST", "/logout"),
    ("GET", "/me"),
}

# Routes already carrying this contract, each with its own contract test:
# W2 landed the review queue and the relevant-records read, e4 landed intake,
# and the two /ai routes are covered by tests/test_gateway_ai_proxy.py.
ALREADY_CONVERTED_ROUTES = {
    ("POST", "/intake"),
    ("GET", "/review-queue"),
    ("POST", "/review-queue/{pair_id}/disposition"),
    ("GET", "/patients/{patient_id}/relevant-records"),
    ("POST", "/ai/intake-instructions"),
    ("POST", "/ai/visit-chat"),
}


def test_every_fan_out_route_is_covered_by_this_contract():
    """E5-SPEC-4. Universality is the requirement — a route left behind reopens
    the class. Deliberately an EXCLUSION list rather than a "routes that call a
    checked helper" predicate: the latter would pass vacuously the moment a new
    route called neither helper."""
    declared = set()
    for r in gw.app.routes:
        if not isinstance(r, APIRoute):
            continue
        for method in r.methods - {"HEAD", "OPTIONS"}:
            declared.add((method, r.path))

    unaccounted = declared - NON_PROXY_ROUTES - ALREADY_CONVERTED_ROUTES
    covered = {(r.method, r.template) for r in ROUTES}
    assert unaccounted == covered, (
        "a gateway route fans out downstream without an error-contract row: "
        f"missing={sorted(unaccounted - covered)} stale={sorted(covered - unaccounted)}"
    )


def test_the_exclusion_lists_name_only_routes_that_exist():
    """A stale exclusion is how the closure test above goes quietly vacuous."""
    declared = set()
    for r in gw.app.routes:
        if not isinstance(r, APIRoute):
            continue
        for method in r.methods - {"HEAD", "OPTIONS"}:
            declared.add((method, r.path))
    assert (NON_PROXY_ROUTES | ALREADY_CONVERTED_ROUTES) <= declared


# --------------------------------------------------------------------------- #
# 8. The HL7 sender is told the message was rejected (E5-SPEC-18)
# --------------------------------------------------------------------------- #
HL7 = next(r for r in ROUTES if r.id == "hl7")


@pytest.mark.parametrize("status", [422, 413])
def test_an_interop_rejection_reaches_the_sending_system(monkeypatch, status):
    """E5-SPEC-18 — the one e5 change whose blast radius leaves the estate.
    interop-service already answers an unparseable or oversized message with a
    rejection status; before this every ingest was answered 200, so a sending
    system's malformed message looked accepted."""
    _patch_transport(
        monkeypatch, response=_FakeResponse(status, {"detail": "unparseable HL7 message"})
    )
    _login_as(HL7.role)

    r = _call(HL7)

    assert r.status_code == status
    assert r.status_code != 200
    assert "error" not in r.json()
