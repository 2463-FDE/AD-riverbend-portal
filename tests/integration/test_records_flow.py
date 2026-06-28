"""
Integration tests — require the full stack up (`make up`) on localhost.

Run with:  pytest -m integration
Skipped by default in CI (`pytest -m "not integration"`).
"""
import os

import pytest

httpx = pytest.importorskip("httpx")

pytestmark = pytest.mark.integration

GATEWAY = os.getenv("GATEWAY_URL", "http://localhost:8070")


def _token() -> str:
    r = httpx.post(f"{GATEWAY}/login", json={"username": "frontdesk", "password": "portal123"}, timeout=10)
    r.raise_for_status()
    return r.json()["token"]


def test_login_returns_token():
    assert _token()


def test_records_require_authentication():
    # No bearer token -> 401 (anonymous access is rejected at the gateway).
    r = httpx.get(f"{GATEWAY}/patients/1042/records", timeout=10)
    assert r.status_code == 401


def test_authenticated_user_can_read_a_chart():
    headers = {"Authorization": f"Bearer {_token()}"}
    r = httpx.get(f"{GATEWAY}/patients/1042/records", headers=headers, timeout=10)
    assert r.status_code == 200
    assert r.json()["patient_id"] == 1042


@pytest.mark.xfail(
    reason="IDOR (D11): any authenticated user can read ANY patient's chart — "
    "the session is never bound to the patient. This SHOULD fail but doesn't.",
    strict=False,
)
def test_user_cannot_read_other_patients_chart():
    # frontdesk pulling an unrelated chart should be forbidden — but isn't.
    headers = {"Authorization": f"Bearer {_token()}"}
    r = httpx.get(f"{GATEWAY}/patients/1043/records", headers=headers, timeout=10)
    assert r.status_code == 403
