"""Gateway role→capability enforcement (ADR 0017, docs/specs-deprecated/rbac.md).

Three drift surfaces are pinned here, because each can silently diverge:

  1. config/roles.yaml (declared policy) vs services/gateway/authz.py
     (enforced policy) — no runtime code reads the YAML, so only this test
     keeps them equal (RBAC-R2).
  2. The route→capability wiring — every session-protected route must carry
     exactly one capability, against a CLOSED public-route allowlist, so a new
     route cannot ship unprotected by omission (RBAC-R3, RBAC-R7).
  3. Behaviour — denied roles get 403 BEFORE any downstream fan-out, unknown
     and missing roles fail closed as 403 (never 500, never a pass), and the
     deprecated 'staff' role keeps every capability so pre-RBAC accounts are
     unchanged (RBAC-R4, RBAC-R5, RBAC-R6).

No live Redis: require_session is dependency-overridden per role; the
anonymous-401 test stubs get_session instead, so the 401 path itself stays
real.
"""
import os
import re
import sys

import pytest
import yaml
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from conftest import REPO_ROOT, load_module

_PINNED = ("config", "logging_config", "db", "models", "security", "authz")
_saved = {name: sys.modules.pop(name, None) for name in _PINNED}
sys.modules["config"] = load_module("services/gateway/config.py", "gw_az_config")
sys.modules["logging_config"] = load_module(
    "services/gateway/logging_config.py", "gw_az_logging_config"
)
sys.modules["db"] = load_module("services/gateway/db.py", "gw_az_db")
sys.modules["models"] = load_module("services/gateway/models.py", "gw_az_models")
sys.modules["security"] = load_module("services/gateway/security.py", "gw_az_security")
authz = load_module("services/gateway/authz.py", "gw_az_authz")
sys.modules["authz"] = authz
gw = load_module("services/gateway/app.py", "gw_az_app")
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

client = TestClient(gw.app, raise_server_exceptions=False)


def _login_as(role, username="testuser"):
    """Simulate an authenticated session carrying `role` (may be a dict to
    simulate a malformed session hash)."""
    session = role if isinstance(role, dict) else {"username": username, "role": role}
    gw.app.dependency_overrides[gw.require_session] = lambda: session


def teardown_function():
    gw.app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# 1. declared vs enforced policy (RBAC-R1, RBAC-R2)
# --------------------------------------------------------------------------- #
def test_roles_yaml_matches_enforced_map():
    with open(os.path.join(REPO_ROOT, "config", "roles.yaml")) as f:
        declared_cfg = yaml.safe_load(f)
    declared = {
        name: frozenset(spec["permissions"]) for name, spec in declared_cfg["roles"].items()
    }
    assert declared == authz.ROLE_CAPABILITIES
    # Every granted capability is in the vocabulary (a typo'd grant would be
    # ungrantable-but-invisible otherwise).
    for name, caps in declared.items():
        assert caps <= authz.CAPABILITIES, f"{name} grants outside the vocabulary"


def test_default_role_matches_schema_default():
    # users.role defaults to 'staff' in db/schema.sql; roles.yaml must agree,
    # and that role must exist and hold every capability (compat contract).
    with open(os.path.join(REPO_ROOT, "config", "roles.yaml")) as f:
        declared_cfg = yaml.safe_load(f)
    assert declared_cfg["default_role"] == "staff"
    with open(os.path.join(REPO_ROOT, "db", "schema.sql")) as f:
        schema = f.read()
    # Anchor to the users table's role column, not a bare substring — another
    # table carrying DEFAULT 'staff' must not satisfy the compat contract.
    users_block = re.search(r"CREATE TABLE IF NOT EXISTS users \((.*?)\);", schema, re.S)
    role_line = next(
        line for line in users_block.group(1).splitlines() if line.strip().startswith("role")
    )
    role_ddl = role_line.split("--")[0]  # the declaration, not its trailing comment
    assert "DEFAULT 'staff'" in role_ddl
    assert authz.capabilities_for("staff") == authz.CAPABILITIES


# --------------------------------------------------------------------------- #
# 2. route wiring (RBAC-R3, RBAC-R7)
# --------------------------------------------------------------------------- #
# Closed list — extend deliberately. Keyed (method, path): a new handler on a
# public PATH (say, POST /healthz) must not inherit publicness by path match.
PUBLIC_ROUTES = {("POST", "/login"), ("POST", "/logout"), ("GET", "/healthz")}

EXPECTED_ROUTE_CAPABILITIES = {
    ("GET", "/me"): "profile.read",
    ("POST", "/intake"): "patients.write",
    ("GET", "/eligibility"): "eligibility.check",
    # Duplicate review queue (W2-SPEC-28): registration work, so it rides the
    # existing patients.write grant — no new role, no new capability.
    ("GET", "/review-queue"): "patients.write",
    ("POST", "/review-queue/{pair_id}/disposition"): "patients.write",
    ("GET", "/patients"): "patients.read",
    ("GET", "/patients/{patient_id}"): "patients.read",
    ("GET", "/patients/{patient_id}/records"): "records.read",
    # The chart-open helper rides the existing chart-read capability (W2-SPEC-18).
    ("GET", "/patients/{patient_id}/relevant-records"): "records.read",
    ("GET", "/records/search"): "records.search",
    ("GET", "/slots"): "schedule.read",
    ("GET", "/appointments"): "schedule.read",
    ("POST", "/appointments"): "appointments.write",
    ("POST", "/appointments/{appointment_id}/cancel"): "appointments.write",
    ("GET", "/roi/requests"): "disclosures.read",
    ("POST", "/roi/requests"): "disclosures.write",
    ("POST", "/roi/requests/{request_id}/fulfill"): "disclosures.write",
    ("POST", "/ai/intake-instructions"): "ai.use",
    ("POST", "/ai/visit-chat"): "ai.use",
    ("POST", "/hl7/ingest"): "hl7.ingest",
}


def _route_capabilities(route) -> list:
    """All required_capability markers in the route's dependency tree."""
    found = []

    def walk(dependant):
        for sub in dependant.dependencies:
            cap = getattr(sub.call, "required_capability", None)
            if cap is not None:
                found.append(cap)
            walk(sub)

    walk(route.dependant)
    return found


def _api_routes():
    return [r for r in gw.app.routes if isinstance(r, APIRoute)]


def test_route_capability_wiring_is_pinned():
    actual = {}
    for route in _api_routes():
        for method in route.methods - {"HEAD", "OPTIONS"}:
            caps = _route_capabilities(route)
            if caps:
                assert len(caps) == 1, f"{method} {route.path} carries {caps}"
                actual[(method, route.path)] = caps[0]
    assert actual == EXPECTED_ROUTE_CAPABILITIES


def test_no_route_outside_the_public_allowlist_is_uncapped():
    uncapped = {
        (method, route.path)
        for route in _api_routes()
        if not _route_capabilities(route)
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    assert uncapped == PUBLIC_ROUTES


def test_wiring_a_capability_outside_the_vocabulary_fails_at_import():
    # A typo'd name would deny everyone silently; it must die loudly instead.
    with pytest.raises(ValueError):
        gw.require_capability("records.raed")


# --------------------------------------------------------------------------- #
# 3. behaviour — denials (RBAC-R4)
# --------------------------------------------------------------------------- #
def _forbid_fanout(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("downstream fan-out ran for a denied request")

    # Both transport helpers: every route that fans out downstream calls one of
    # them, so the "no fan-out" claim cannot go vacuous on a route this test
    # forgot. (The legacy _get/_post were deleted by e5 — E5-SPEC-20.)
    monkeypatch.setattr(gw, "_get_checked", _boom)
    monkeypatch.setattr(gw, "_post_checked", _boom)


@pytest.mark.parametrize(
    "role,method,path",
    [
        ("front_desk", "GET", "/patients/1042/records"),  # no chart access
        ("front_desk", "GET", "/patients/1042/relevant-records"),  # W2-SPEC-18
        ("front_desk", "GET", "/records/search?q=gonzalez"),
        ("front_desk", "GET", "/roi/requests"),
        ("clinician", "POST", "/intake"),
        ("clinician", "POST", "/appointments"),
        ("clinician", "POST", "/ai/intake-instructions"),
        ("clinician", "GET", "/review-queue"),                       # W2-SPEC-28
        ("clinician", "POST", "/review-queue/1/disposition"),
        ("roi_clerk", "GET", "/eligibility?insurance_id=BCBS123"),
        ("roi_clerk", "GET", "/review-queue"),
        ("roi_clerk", "POST", "/review-queue/1/disposition"),
        ("roi_clerk", "POST", "/hl7/ingest"),
    ],
)
def test_denied_role_gets_403_and_no_fanout(monkeypatch, role, method, path):
    _forbid_fanout(monkeypatch)
    _login_as(role)
    r = client.request(method, path, json={} if method == "POST" else None)
    assert r.status_code == 403
    assert "requires capability" in r.json()["detail"]


def test_denial_detail_names_the_capability_and_no_identifiers():
    _login_as("front_desk")
    r = client.get("/patients/1042/records")
    assert r.status_code == 403
    assert r.json()["detail"] == "requires capability records.read"
    assert "1042" not in r.text  # no patient identifier reflected


# --------------------------------------------------------------------------- #
# 3b. behaviour — fail closed on bad role state (RBAC-R5)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "session",
    [
        {"username": "u", "role": "nurse"},  # role not in the policy
        {"username": "u", "role": ""},
        {"username": "u"},  # pre-RBAC hash missing the key entirely
        {"role": "records.read", "username": "u"},  # capability name in the role slot
    ],
)
def test_unknown_or_missing_role_fails_closed_as_403(monkeypatch, session):
    _forbid_fanout(monkeypatch)
    _login_as(session)
    r = client.get("/patients/1042/records")
    assert r.status_code == 403


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/patients/1042/records"),
        ("GET", "/patients/1042/relevant-records"),      # W2-SPEC-18
        ("GET", "/review-queue"),                        # W2-SPEC-28
        ("POST", "/review-queue/1/disposition"),
    ],
)
def test_anonymous_caller_still_gets_401_not_403(monkeypatch, method, path):
    monkeypatch.setattr(gw, "get_session", lambda token: None)
    r = client.request(method, path, json={} if method == "POST" else None)
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# 4. behaviour — grants (RBAC-R6 and each role's job still works)
# --------------------------------------------------------------------------- #
def test_staff_keeps_every_capability():
    assert authz.capabilities_for("staff") == authz.CAPABILITIES
    assert authz.capabilities_for("admin") == authz.CAPABILITIES


@pytest.mark.parametrize(
    "role,method,path",
    [
        ("front_desk", "POST", "/intake"),
        ("front_desk", "GET", "/slots"),
        ("clinician", "GET", "/patients/1042/records"),
        ("clinician", "GET", "/patients/1042/relevant-records"),
        ("clinician", "GET", "/records/search?q=gonzalez"),
        ("roi_clerk", "GET", "/roi/requests"),
        ("front_desk", "GET", "/review-queue"),      # the queue's operational owner
        ("front_desk", "POST", "/review-queue/1/disposition"),
        ("admin", "GET", "/review-queue"),
        ("staff", "GET", "/patients/1042/records"),  # pre-RBAC rows unchanged
        ("staff", "GET", "/review-queue"),
        ("staff", "POST", "/roi/requests"),
    ],
)
def test_granted_role_reaches_the_downstream_proxy(monkeypatch, role, method, path):
    sentinel = {"proxied": True}
    monkeypatch.setattr(gw, "_get_checked", lambda *a, **k: sentinel)
    monkeypatch.setattr(gw, "_post_checked", lambda *a, **k: sentinel)
    _login_as(role)
    r = client.request(method, path, json={} if method == "POST" else None)
    assert r.status_code == 200
    assert r.json() == sentinel


# --------------------------------------------------------------------------- #
# 5. eligibility-assistant: the visit-chat role gate as client acceptance
#    (SPEC-47/48 — EVAL-010/011/029/030; eligibility-assistant-D-17, D-30).
#    Tests only: no authz line moves, and EXPECTED_ROUTE_CAPABILITIES above is
#    untouched — /ai/visit-chat already carries ai.use.
# --------------------------------------------------------------------------- #
_A1_TURN_BODY = {
    "message": "please check AETN1224",
    "question_type": "covered_today",
    "payer": "aetna",
    "product": "commercial",
    "state": "unconfirmed",
}


@pytest.mark.parametrize("role", ["clinician", "roi_clerk"], ids=["EVAL-010", "EVAL-011"])
def test_visit_chat_roles(monkeypatch, role):
    """SPEC-47 — the refused roles get 403 BEFORE any assistant turn: no fan-out,
    no rate-limit or budget read, no visit memory touched."""
    _forbid_fanout(monkeypatch)
    _login_as(role)

    r = client.post("/ai/visit-chat", json=_A1_TURN_BODY)

    assert r.status_code == 403
    assert r.json()["detail"] == "requires capability ai.use"
    assert "AETN1224" not in r.text


@pytest.mark.parametrize("leg", ["grant", "config"], ids=["EVAL-029", "EVAL-030"])
def test_ai_use_grants(monkeypatch, leg):
    """SPEC-48 — the `ai.use` grant set is pinned at exactly `front_desk`,
    `admin`, `staff` (EVAL-030's "reclassify", the eligibility-assistant-D-17
    known limitation: `staff` keeps the grant as the compat default role), and
    `admin` actually reaches the proxy (EVAL-029)."""
    if leg == "config":
        with open(os.path.join(REPO_ROOT, "config", "roles.yaml")) as f:
            declared = yaml.safe_load(f)["roles"]
        granted = {
            role
            for role, spec in declared.items()
            if "ai.use" in (spec.get("permissions") or [])
        }
        assert granted == {"front_desk", "admin", "staff"}
        # The enforced twin agrees — yaml alone gates nothing (authz.py:4-8).
        enforced = {
            role
            for role in declared
            if "ai.use" in authz.capabilities_for(role)
        }
        assert enforced == granted
        return

    proxied = []

    def _fake_post_checked(service, path, payload, timeout=None, headers=None):
        proxied.append(path)
        raise gw.HTTPException(status_code=503, detail="stub: reached the fan-out")

    monkeypatch.setattr(gw, "_post_checked", _fake_post_checked)
    monkeypatch.setattr(gw, "check_ai_rate_limit", lambda *a, **k: 0)
    monkeypatch.setattr(gw, "consume_ai_global_budget", lambda *a, **k: (0, None))
    monkeypatch.setattr(gw, "visit_lock_acquire", lambda *a, **k: "tok")
    monkeypatch.setattr(gw, "visit_lock_release", lambda *a, **k: None)
    _login_as("admin")

    r = client.post("/ai/visit-chat", json=_A1_TURN_BODY)

    # The 403 gate passed and the request reached the fan-out; the stubbed 503
    # is this test's own sentinel, not a denial.
    assert proxied == ["/visit-chat"]
    assert r.status_code == 503
