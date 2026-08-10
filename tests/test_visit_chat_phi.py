"""Adversarial PHI tests for the visit-chat path (CLAUDE.md §5, ADR 0011).

This is the test the schemas.py docstring demanded before any free-text field
could exist in ai-assistant. It runs the REAL chain end to end — gateway route →
ai-assistant endpoint → eligibility client — with only the two external seams
faked (Bedrock and the eligibility HTTP call), and plants PHI where the code does
not expect it:

  * a patient name and DOB, which NO pattern filter can catch — the reason the
    transcript is metadata-only rather than "redacted";
  * an SSN, which must never be mistaken for a member id and shipped to a payer;
  * the member id itself, which is the one identifier allowed to persist, and
    only as a structured fact.

Then it asserts the four places PHI could escape are clean: the prompt sent to
the vendor, the logs of both services, the Redis record, and the HTTP response.

The happy-path tests in the sibling files prove the feature works; these prove
the boundary holds. Both are required (the `consents` leak in PR #2 shipped green
because only the first kind existed).
"""
import json
import logging
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import load_module

# --- ai-assistant stack ------------------------------------------------------
_AI_PINNED = (
    "config",
    "logging_config",
    "schemas",
    "llm_client",
    "templates",
    "visit_templates",
    "breaker",
    "eligibility_client",
)
_saved = {name: sys.modules.pop(name, None) for name in _AI_PINNED}
sys.modules["config"] = load_module("services/ai-assistant/config.py", "phi_ai_config")
sys.modules["logging_config"] = load_module(
    "services/ai-assistant/logging_config.py", "phi_ai_logging"
)
ai_schemas = sys.modules["schemas"] = load_module(
    "services/ai-assistant/schemas.py", "phi_ai_schemas"
)
sys.modules["llm_client"] = load_module("services/ai-assistant/llm_client.py", "phi_ai_llm")
sys.modules["templates"] = load_module("services/ai-assistant/templates.py", "phi_ai_templates")
visit_templates = sys.modules["visit_templates"] = load_module(
    "services/ai-assistant/visit_templates.py", "phi_ai_visit_templates"
)
breaker_mod = sys.modules["breaker"] = load_module(
    "services/ai-assistant/breaker.py", "phi_ai_breaker"
)
elig_client = sys.modules["eligibility_client"] = load_module(
    "services/ai-assistant/eligibility_client.py", "phi_ai_elig_client"
)
ai_app = load_module("services/ai-assistant/app.py", "phi_ai_app")
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

# --- gateway stack -----------------------------------------------------------
_GW_PINNED = ("config", "logging_config", "db", "models", "security")
_saved = {name: sys.modules.pop(name, None) for name in _GW_PINNED}
sys.modules["config"] = load_module("services/gateway/config.py", "phi_gw_config")
sys.modules["logging_config"] = load_module(
    "services/gateway/logging_config.py", "phi_gw_logging"
)
sys.modules["db"] = load_module("services/gateway/db.py", "phi_gw_db")
sys.modules["models"] = load_module("services/gateway/models.py", "phi_gw_models")
security = sys.modules["security"] = load_module("services/gateway/security.py", "phi_gw_security")
gw = load_module("services/gateway/app.py", "phi_gw_app")
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

INTERNAL_SECRET = "phi-test-secret"
ai_app.settings.ai_proxy_shared_secret = INTERNAL_SECRET
gw.settings.ai_proxy_shared_secret = INTERNAL_SECRET

ai_client = TestClient(
    ai_app.app, raise_server_exceptions=False, headers={"X-Internal-Auth": INTERNAL_SECRET}
)

OWNER = "frontdesk"
OTHER = "drnguyen"
_session = {"username": OWNER, "role": "staff"}
gw.app.dependency_overrides[gw.require_session] = lambda: dict(_session)
gw_client = TestClient(gw.app, raise_server_exceptions=False)

MEMBER_ID = "AETN1224"
NAME = "Jane Doe"
DOB = "1985-03-12"
SSN = "123-45-6789"
EMAIL = "jane.doe@example.com"
PHONE = "555-867-5309"
# Everything except the member id must be absent from EVERY sink. The member id
# is allowed in exactly one place — facts.insurance_id in the Redis record —
# which the tests below assert positively rather than by omission.
PHI_STRINGS = (NAME, DOB, SSN, EMAIL, PHONE)

ADVERSARIAL_MESSAGE = (
    f"check coverage for {NAME}, dob {DOB}, ssn {SSN}, "
    f"member {MEMBER_ID}, email {EMAIL}, phone {PHONE}"
)


class _FakeRedis:
    def __init__(self):
        self.counts = {}
        self.store = {}
        self.ttls = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def delete(self, key):
        self.counts.pop(key, None)
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        return 1

    def eval(self, script, numkeys, *keys_and_args):
        key = keys_and_args[0]
        if script == security._SINGLEFLIGHT_RELEASE_LUA:
            if self.store.get(key) == keys_and_args[1]:
                self.store.pop(key, None)
                return 1
            return 0
        if script == security._DECR_AND_CLEAR_LUA:
            remaining = self.counts.get(key, 0) - 1
            self.counts[key] = remaining
            if remaining <= 0:
                self.counts.pop(key, None)
            return remaining
        window = keys_and_args[1]
        count = self.counts.get(key, 0) + 1
        self.counts[key] = count
        if count == 1:
            self.ttls[key] = int(window)
        return count


@pytest.fixture()
def rig(monkeypatch):
    """Wire the two real services together, faking only the external seams."""
    redis = _FakeRedis()
    monkeypatch.setattr(security, "_redis_client", redis)
    monkeypatch.setattr(security.time, "time", lambda: 1_000_000.0)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 1_000_000)
    _session.update(username=OWNER)

    prompts = []
    payer_calls = []

    # Seam 1: Bedrock. Capture every prompt that would have crossed the vendor
    # boundary — this is the D13 (no BAA) control under test.
    def _fake_llm(prompt, output_model, system=None, max_tokens=None):
        prompts.append({"prompt": prompt, "system": system})
        required = visit_templates.default_selection("active")
        return SimpleNamespace(
            parsed=ai_schemas.VisitReplyPlan.model_validate_json(
                json.dumps({"template_ids": required})
            )
        )

    monkeypatch.setattr(ai_app.llm_client, "complete_structured", _fake_llm)

    # Seam 2: the eligibility HTTP call. The REAL eligibility_client runs, so its
    # projection and PHI-safe error handling are exercised, not stubbed.
    def _fake_get(url, params=None, timeout=None):
        payer_calls.append(params or {})
        return httpx.Response(
            200,
            json={
                "insurance_id": params.get("insurance_id"),
                "active": True,
                "status": "active",
                "payer": "edi.example.com",
                "raw_status": "1",
                "checked_at": "2026-07-26T10:00:00Z",
            },
        )

    monkeypatch.setattr(elig_client.httpx, "get", _fake_get)
    monkeypatch.setattr(
        elig_client, "_breaker", breaker_mod.CircuitBreaker(fail_threshold=3, reset_seconds=30)
    )

    # The gateway's fan-out calls the real ai-assistant app.
    def _fake_post_checked(service, path, payload, timeout=None, headers=None):
        r = ai_client.post(path, json=payload)
        if r.status_code >= 400:
            from fastapi import HTTPException

            raise HTTPException(status_code=r.status_code, detail="downstream")
        return r.json()

    monkeypatch.setattr(gw, "_post_checked", _fake_post_checked)

    return SimpleNamespace(redis=redis, prompts=prompts, payer_calls=payer_calls)


def _chat(message, visit_id=None):
    body = {"message": message}
    if visit_id is not None:
        body["visit_id"] = visit_id
    return gw_client.post("/ai/visit-chat", json=body)


# --- the vendor boundary ----------------------------------------------------
def test_no_phi_reaches_the_prompt(rig):
    r = _chat(ADVERSARIAL_MESSAGE)
    assert r.status_code == 200

    assert rig.prompts, "the model was never called — the test proves nothing"
    blob = json.dumps(rig.prompts)
    for phi in PHI_STRINGS + (MEMBER_ID,):
        assert phi not in blob, f"{phi!r} crossed the vendor boundary"


def test_the_prompt_is_exactly_the_deterministic_build(rig):
    """The strongest form of the claim: the prompt is a pure function of CLOSED
    inputs, so it is byte-identical to what the builder produces from them.

    An assertion about absent substrings can only catch the PHI a test thought
    to plant; this one catches any clerk text reaching the prompt by ANY route,
    including a future edit that starts interpolating the message.
    """
    _chat(ADVERSARIAL_MESSAGE)

    expected = ai_app._build_visit_prompt(
        ai_schemas.VisitIntent.check_eligibility,
        "active",
        0,
        visit_templates.default_selection("active"),
        visit_templates.allowed_selection("active"),
    )
    assert rig.prompts[0]["prompt"] == expected


# --- logs -------------------------------------------------------------------
def test_no_phi_reaches_any_log_record(rig, caplog):
    with caplog.at_level("DEBUG"):
        _chat(ADVERSARIAL_MESSAGE)

    for phi in PHI_STRINGS + (MEMBER_ID,):
        assert phi not in caplog.text, f"{phi!r} reached a log record"


def test_no_phi_in_logs_when_the_payer_call_fails(rig, monkeypatch, caplog):
    # The failure path is where the PR #11 leak lived: httpx embeds the failing
    # URL — which carries ?insurance_id=<member id> — in its exception message.
    def _boom(url, params=None, timeout=None):
        raise httpx.ConnectError(
            f"connect failed: {url}?insurance_id={params.get('insurance_id')}"
        )

    monkeypatch.setattr(elig_client.httpx, "get", _boom)

    with caplog.at_level("DEBUG"):
        r = _chat(ADVERSARIAL_MESSAGE)

    assert r.status_code == 200
    for phi in PHI_STRINGS + (MEMBER_ID,):
        assert phi not in caplog.text
    assert "connect failed" not in caplog.text


# --- the store --------------------------------------------------------------
def test_only_the_member_id_persists_and_only_as_a_fact(rig):
    r = _chat(ADVERSARIAL_MESSAGE)
    visit_id = r.json()["visit_id"]

    stored = rig.redis.store[f"visit:{visit_id}"]
    for phi in PHI_STRINGS:
        assert phi not in stored, f"{phi!r} was persisted to Redis"
    # The one identifier that IS allowed at rest, in the one place approved for
    # it (ADR 0011 §3 / debt-log D3b).
    record = json.loads(stored)
    assert record["facts"]["insurance_id"] == MEMBER_ID
    assert MEMBER_ID not in json.dumps(record["turns"])


def test_the_key_itself_carries_no_identifier(rig):
    r = _chat(ADVERSARIAL_MESSAGE)
    visit_id = r.json()["visit_id"]

    for key in rig.redis.store:
        for phi in PHI_STRINGS + (MEMBER_ID, OWNER):
            assert phi not in key


def test_a_degraded_error_string_is_never_persisted(rig, monkeypatch):
    # eligibility-service's degraded body carries an `error` field; the client
    # projects it away so it cannot reach the store through the facts.
    def _degraded(url, params=None, timeout=None):
        return httpx.Response(
            200,
            json={
                "insurance_id": params.get("insurance_id"),
                "active": None,
                "status": "unknown",
                "payer": "edi.example.com",
                "raw_status": None,
                "checked_at": "2026-07-26T10:00:00Z",
                "error": f"payer rejected member {MEMBER_ID} for {NAME}",
            },
        )

    monkeypatch.setattr(elig_client.httpx, "get", _degraded)

    r = _chat(ADVERSARIAL_MESSAGE)
    visit_id = r.json()["visit_id"]

    stored = rig.redis.store[f"visit:{visit_id}"]
    assert "payer rejected" not in stored
    assert NAME not in stored
    assert "error" not in json.loads(stored)["facts"].get("last_eligibility", {})


def test_degrade_log_carries_no_exception_message(rig, monkeypatch, caplog):
    # W1-SPEC-12 / W1-SPEC-13, negative test (docs/landmines.md §3). The
    # visit-chat degrade branch is the sixth LLM-path site that stringified its
    # exception; the adversarial input is PHI planted inside the exception
    # message, scanned over the FORMATTED record so exc_info text counts too.
    marker = f"{NAME} member {MEMBER_ID} LEAK-SENTINEL-3390"

    def _raise(*a, **k):
        raise ai_app.llm_client.LLMUnavailable(marker)

    monkeypatch.setattr(ai_app.llm_client, "complete_structured", _raise)
    with caplog.at_level("DEBUG"):
        r = _chat(ADVERSARIAL_MESSAGE)

    # The reply still degrades deterministically — this is a log fix, not a
    # behaviour change.
    assert r.status_code == 200
    assert r.json()["reply"]

    formatted = "\n".join(logging.Formatter().format(rec) for rec in caplog.records)
    assert "LEAK-SENTINEL-3390" not in formatted
    for phi in PHI_STRINGS + (MEMBER_ID,):
        assert phi not in formatted, f"{phi!r} reached a log record"
    # The degrade is still diagnosable: class name and egress flag survive.
    assert "LLMUnavailable" in formatted
    assert "egressed=" in formatted


def test_degrade_log_carries_the_provider_request_id(rig, monkeypatch, caplog):
    # Codex PR #69 round 1 (medium), W1-SPEC-12. The degrade branch is the other
    # class-name-only LLM-path site, and it swallows the failure into a 200 — so
    # the log line is the ONLY record a response-format incident leaves here.
    # The structured request id survives; the message, PHI-planted, does not.
    marker = f"{NAME} member {MEMBER_ID} LEAK-SENTINEL-4471"

    def _raise(*a, **k):
        raise ai_app.llm_client.LLMResponseError(marker, request_id="req_drift_88")

    monkeypatch.setattr(ai_app.llm_client, "complete_structured", _raise)
    with caplog.at_level("DEBUG"):
        r = _chat(ADVERSARIAL_MESSAGE)

    assert r.status_code == 200
    formatted = "\n".join(logging.Formatter().format(rec) for rec in caplog.records)
    assert "req_drift_88" in formatted
    assert "LLMResponseError" in formatted
    assert "LEAK-SENTINEL-4471" not in formatted
    for phi in PHI_STRINGS + (MEMBER_ID,):
        assert phi not in formatted, f"{phi!r} reached a log record"
    assert "req_drift_88" not in r.text


# --- the response -----------------------------------------------------------
def test_no_phi_in_the_http_response(rig):
    r = _chat(ADVERSARIAL_MESSAGE)

    for phi in PHI_STRINGS:
        assert phi not in r.text
    # The member id may appear only inside the structured eligibility echo, never
    # in the prose the clerk reads.
    assert MEMBER_ID not in r.json()["reply"]


# --- an SSN is not a member id ---------------------------------------------
def test_an_ssn_is_never_shipped_to_the_payer(rig):
    # The extractor requires letters precisely so a bare 9-digit number cannot be
    # mistaken for a member id and sent to a clearinghouse.
    r = _chat(f"the patient's ssn is {SSN}, can you check coverage")

    assert r.status_code == 200
    assert rig.payer_calls == []
    assert "member ID" in r.json()["reply"]


def test_the_payer_only_ever_receives_the_member_id(rig):
    _chat(ADVERSARIAL_MESSAGE)

    assert rig.payer_calls == [{"insurance_id": MEMBER_ID}]
    blob = json.dumps(rig.payer_calls)
    for phi in PHI_STRINGS:
        assert phi not in blob


# --- cross-visit isolation --------------------------------------------------
def test_another_clerk_cannot_read_a_visit(rig):
    visit_id = _chat(ADVERSARIAL_MESSAGE).json()["visit_id"]

    _session.update(username=OTHER)
    r = _chat("is it still active?", visit_id=visit_id)

    assert r.status_code == 404
    assert MEMBER_ID not in r.text
    for phi in PHI_STRINGS:
        assert phi not in r.text


def test_a_second_visit_does_not_inherit_the_first_visits_facts(rig):
    _chat(ADVERSARIAL_MESSAGE)

    second = _chat("is it still active?")

    # A fresh visit has no id on file, so it must ask rather than answer from
    # another visit's state.
    assert second.json()["eligibility"] is None
    assert "member ID" in second.json()["reply"]
