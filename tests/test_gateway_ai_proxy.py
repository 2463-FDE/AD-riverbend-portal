"""Tests for the gateway's /ai/intake-instructions fan-out (_post_checked).

The inherited _post/_get helpers collapse every failure into a 200-OK
{"error": str(e)} body, and str(e) on an httpx error can embed the request URL
and its query params (the eligibility member_id leak, PR #2 era). New routes
use _post_checked instead; these tests pin the contract: real status codes,
exception CLASS only in logs, downstream URL never in a response or log line.

No Redis/DB I/O: require_session is dependency-overridden and httpx.post is
faked at the gateway module seam.
"""
import json
import pathlib
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


@pytest.fixture(autouse=True)
def _no_abuse_controls(monkeypatch):
    # These tests pin the _post_checked transport contract, not the abuse
    # controls (rate limit / spend ceiling / cache — exercised in
    # test_gateway_ai_rate_limit.py). Neutralize them so they stay off Redis
    # and never intercept: quota open, budget open, cache always misses and
    # never writes.
    monkeypatch.setattr(gw, "check_ai_rate_limit", lambda *a, **k: 0)
    monkeypatch.setattr(gw, "consume_ai_global_budget", lambda *a, **k: (0, None))
    monkeypatch.setattr(gw, "ai_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(gw, "ai_cache_set", lambda *a, **k: None)
    # Single-flight lock (round 7) also stays off Redis: every request wins its
    # own slot so the transport contract is exercised, not the coalescing (that
    # lives in test_gateway_ai_rate_limit.py).
    monkeypatch.setattr(gw, "ai_singleflight_acquire", lambda *a, **k: True)
    monkeypatch.setattr(gw, "ai_singleflight_release", lambda *a, **k: None)


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


# --- eligibility-assistant turn: the correlation hop and the answer-only degrade
# (SPEC-26 / eligibility-assistant-D-46; SPEC-41 / eligibility-assistant-D-72) ---

# One legal turn body. The four selections are required on every turn (SPEC-54);
# the values are the contract's own (contracts/visit-chat-turn.json).
_TURN_SELECTIONS = {
    "question_type": "covered_today",
    "payer": "aetna",
    "product": "commercial",
    "state": "unconfirmed",
    "emergency": False,
}

_TURN_CID = "3f2b8c44-9a1d-4e5f-8a6b-0c1d2e3f4a5b"


def _turn_downstream(**overrides):
    """A body our renderer would produce, overridable per test."""
    body = {
        "reply": "Coverage is ACTIVE with edi.example.com.\n- Collect the copay",
        "intent": "check_eligibility",
        "status": "active",
        "facts": {
            "insurance_id": "AETN1224",
            "last_eligibility": None,
            "last_citations": [
                {"document_id": "DOC-PAYER-AETNA-ELIG", "version": "2026-07"}
            ],
        },
        "disclaimer": "Administrative guidance only.",
        "eligibility": None,
        "llm_egress": True,
        "assistant": "ok",
        "citations": [
            {
                "title": "Aetna eligibility",
                "document_id": "DOC-PAYER-AETNA-ELIG",
                "section": "Verification",
                "version": "2026-07",
            }
        ],
        "mode": "real",
        "reason": None,
        "outcome": "active",
        "correlation_id": _TURN_CID,
        "model": "us.anthropic.claude-sonnet-4-6",
    }
    body.update(overrides)
    return body


@pytest.fixture()
def visit_state(monkeypatch):
    """Visit memory and the per-visit lock, off Redis; records saves."""
    saves = []
    monkeypatch.setattr(gw, "visit_lock_acquire", lambda *a, **k: "tok")
    monkeypatch.setattr(gw, "visit_lock_release", lambda *a, **k: None)

    def _save(visit_id, owner, facts, turns, *a, **k):
        saves.append({"visit_id": visit_id, "facts": facts, "turns": turns})
        return True

    monkeypatch.setattr(gw, "visit_memory_save", _save)
    return saves


def _post_turn(monkeypatch, downstream_body, *, headers=None):
    calls = _patch_post(monkeypatch, response=_FakeResponse(body=downstream_body))
    r = client.post(
        "/ai/visit-chat",
        json={"message": "please check AETN1224", **_TURN_SELECTIONS},
        headers=headers or {},
    )
    return r, calls


def test_a1_correlation_header_forwarded(monkeypatch, visit_state):
    """SPEC-26 — the portal's X-Correlation-Id rides the fan-out hop as a HEADER
    (never a body field) and is echoed back; the gateway answers with the id IT
    forwarded, not whatever downstream claims (eligibility-assistant-D-46)."""
    r, calls = _post_turn(
        monkeypatch,
        _turn_downstream(correlation_id="00000000-0000-4000-8000-000000000000"),
        headers={"X-Correlation-Id": _TURN_CID},
    )

    assert r.status_code == 200, r.text
    assert calls[0]["headers"]["X-Correlation-Id"] == _TURN_CID
    # The body forwarded downstream carries the turn payload, never the id.
    assert "X-Correlation-Id" not in calls[0]["json"]
    assert "correlation_id" not in calls[0]["json"]
    assert r.json()["correlation_id"] == _TURN_CID

    # The other leg of eligibility-assistant-D-46: a caller with no usable header
    # (here: not UUIDv4-shaped) gets a gateway-MINTED UUIDv4, replaced rather than
    # forwarded — the id is bounded and structural on every path.
    r2, calls2 = _post_turn(
        monkeypatch, _turn_downstream(), headers={"X-Correlation-Id": "not-a-uuid"}
    )
    assert r2.status_code == 200, r2.text
    forwarded = calls2[0]["headers"]["X-Correlation-Id"]
    assert forwarded != "not-a-uuid"
    import uuid as _uuid

    assert _uuid.UUID(forwarded).version == 4
    assert r2.json()["correlation_id"] == forwarded


def test_a1_answer_fields_degrade_and_facts_stay_fatal(monkeypatch, visit_state):
    """SPEC-41 / eligibility-assistant-D-72 — the five answer-only fields degrade
    (`citations` to `[]`, the other four to null) while the turn still answers 200
    with `facts` persisted; an unusable `facts.last_citations` is FATAL (502) with
    visit memory untouched. The two halves fail independently."""
    # Half 1: every answer-only field unusable -> 200, degraded, facts persisted.
    r, _ = _post_turn(
        monkeypatch,
        _turn_downstream(
            citations="nonsense",
            mode=123,
            reason={"free": "text"},
            outcome="NOT SNAKE CASE",
            model="\x00" * 300,
        ),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["citations"] == []
    assert body["mode"] is None
    assert body["reason"] is None
    assert body["outcome"] is None
    assert body["model"] is None
    assert len(visit_state) == 1
    assert visit_state[0]["facts"]["insurance_id"] == "AETN1224"
    # The persisted citation is ids + version ONLY — no text key survives the hop.
    assert visit_state[0]["facts"]["last_citations"] == [
        {"document_id": "DOC-PAYER-AETNA-ELIG", "version": "2026-07"}
    ]

    # Half 2: unusable facts.last_citations -> 502, nothing further persisted.
    r2, _ = _post_turn(
        monkeypatch,
        _turn_downstream(
            facts={
                "insurance_id": "AETN1224",
                "last_eligibility": None,
                "last_citations": [{"document_id": 42}],
            }
        ),
    )
    assert r2.status_code == 502
    assert len(visit_state) == 1, "the 502 must not touch visit memory"


# --- the gateway's copy of the four closed selection sets (eligibility-assistant
# -D-45) --------------------------------------------------------------------
def test_the_gateway_selection_sets_are_the_contract_sets():
    """The THIRD copy, asserted against the one declaration.

    `contracts/visit-chat-turn.json` is the single declaration of the turn payload
    because the portal, the gateway and the assistant each carry a copy of these
    four menus, and three copies of a closed set kept equal by review alone is the
    shape `docs/landmines.md` §1 names as the intake contract break. Two of the
    three were asserted — `tests/test_a1_turn_contract.py` for the assistant's
    pydantic enums, `frontend/app/assistant/turn.contract.test.ts` for the portal's
    builder — and the gateway's literal tuples were pinned by nothing while two
    in-code comments said they were. A value added to the contract and the assistant
    but not to `_TURN_*` here 422s every turn carrying it, with nothing red.
    """
    contract = json.loads(
        (
            pathlib.Path(__file__).resolve().parent.parent
            / "contracts"
            / "visit-chat-turn.json"
        ).read_text()
    )
    for axis, mirrored in (
        ("question_type", gw._TURN_QUESTION_TYPES),
        ("payer", gw._TURN_PAYERS),
        ("product", gw._TURN_PRODUCTS),
        ("state", gw._TURN_STATES),
    ):
        assert set(contract["enums"][axis]) == set(mirrored), (
            f"contracts/visit-chat-turn.json declares "
            f"{sorted(contract['enums'][axis])} for {axis}, but the gateway mirrors "
            f"{sorted(mirrored)}"
        )
