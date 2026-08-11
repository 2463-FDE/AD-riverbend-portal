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
        role="front_desk",
        service="eligibility",
        downstream="/eligibility",
        params={"insurance_id": "BCBS4471"},
    ),
    Route(
        id="patients",
        method="GET",
        path="/patients?q=gonzalez&limit=25&offset=0",
        role="front_desk",
        service="records",
        downstream="/patients",
        params={"q": "gonzalez", "limit": 25, "offset": 0},
    ),
    Route(
        id="patient",
        method="GET",
        path="/patients/1042",
        role="front_desk",
        service="records",
        downstream="/patients/1042",
        params={},
    ),
    Route(
        id="records",
        method="GET",
        path="/patients/1042/records",
        role="clinician",
        service="records",
        downstream="/patients/1042/records",
        params={},
    ),
    Route(
        id="search",
        method="GET",
        path="/records/search?q=gonzalez",
        role="clinician",
        service="records",
        downstream="/records/search",
        params={"q": "gonzalez"},
    ),
    Route(
        id="slots",
        method="GET",
        path="/slots?provider_id=3&limit=50",
        role="front_desk",
        service="scheduling",
        downstream="/slots",
        params={"provider_id": 3, "limit": 50},
    ),
    Route(
        id="list_appointments",
        method="GET",
        path="/appointments?patient_id=1042",
        role="front_desk",
        service="scheduling",
        downstream="/appointments",
        params={"patient_id": 1042},
    ),
    Route(
        id="roi_list",
        method="GET",
        path="/roi/requests?patient_id=1042",
        role="roi_clerk",
        service="roi",
        downstream="/roi/requests",
        params={"patient_id": 1042},
    ),
    Route(
        id="book",
        method="POST",
        path="/appointments",
        role="front_desk",
        service="scheduling",
        downstream="/appointments",
        payload={"patient_id": 1042, "slot_id": 88},
    ),
    Route(
        id="cancel",
        method="POST",
        path="/appointments/77/cancel",
        role="front_desk",
        service="scheduling",
        downstream="/appointments/77/cancel",
        payload={},
    ),
    Route(
        id="roi_create",
        method="POST",
        path="/roi/requests",
        role="roi_clerk",
        service="roi",
        downstream="/roi/requests",
        payload={"patient_id": 1042, "recipient": "Dr Vance"},
    ),
    Route(
        id="roi_fulfill",
        method="POST",
        path="/roi/requests/77/fulfill",
        role="roi_clerk",
        service="roi",
        downstream="/roi/requests/77/fulfill",
        payload={},
    ),
    Route(
        id="hl7",
        method="POST",
        path="/hl7/ingest",
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
