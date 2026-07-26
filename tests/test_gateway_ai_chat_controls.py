"""Gateway controls on POST /ai/visit-chat (ADR 0011 §3, §6).

The chat endpoint joins the ADR-0007 control stack, but not identically, and the
differences are the point of this file:

  * its own rate-limit NAMESPACE, so neither AI endpoint can exhaust the other's
    quota, while the aggregate SPEND ceiling stays shared (it bounds dollars);
  * NO response cache — a reply depends on a live verdict and this visit's
    memory, and its key would have to derive from PHI-bearing free text;
  * single-flight repurposed as a per-visit lock, because identical bodies in a
    conversation are legitimate but two simultaneous turns in one visit are not;
  * visit memory is owner-bound, and a fault reading it fails CLOSED.

Fan-out is faked at _post_checked, so no ai-assistant and no Bedrock is involved.
"""
import json
import sys

import pytest
from fastapi.testclient import TestClient

from conftest import load_module

_PINNED = ("config", "logging_config", "db", "models", "security")
_saved = {name: sys.modules.pop(name, None) for name in _PINNED}
sys.modules["config"] = load_module("services/gateway/config.py", "gwc_config")
sys.modules["logging_config"] = load_module(
    "services/gateway/logging_config.py", "gwc_logging_config"
)
sys.modules["db"] = load_module("services/gateway/db.py", "gwc_db")
sys.modules["models"] = load_module("services/gateway/models.py", "gwc_models")
security = sys.modules["security"] = load_module("services/gateway/security.py", "gwc_security")
gw = load_module("services/gateway/app.py", "gwc_app")
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

OWNER = "frontdesk"
OTHER = "drnguyen"
MEMBER_ID = "AETN1224"

_session = {"username": OWNER, "role": "staff"}
gw.app.dependency_overrides[gw.require_session] = lambda: dict(_session)
client = TestClient(gw.app, raise_server_exceptions=False)

DOWNSTREAM_OK = {
    "reply": "Coverage is ACTIVE with edi.example.com.\n- Record the result.",
    "intent": "check_eligibility",
    "status": "active",
    "facts": {
        "insurance_id": MEMBER_ID,
        "last_eligibility": {"active": True, "status": "active"},
    },
    "eligibility": {"active": True, "status": "active"},
    "disclaimer": "Coverage information comes from the payer's eligibility response.",
}


class _FakeRedis:
    """INCR/EXPIRE via EVAL, plus GET/SET(nx,ex)/DEL — the same semantics-keyed
    double tests/test_gateway_ai_rate_limit.py uses, extended for visit keys."""

    def __init__(self):
        self.counts = {}
        self.store = {}
        self.ttls = {}
        self.fail_on = set()

    def _check(self, key):
        if any(marker in key for marker in self.fail_on):
            raise RuntimeError("redis down")

    def get(self, key):
        self._check(key)
        return self.store.get(key)

    def set(self, key, value, nx=False, ex=None):
        self._check(key)
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
        self._check(key)
        if script == security._SINGLEFLIGHT_RELEASE_LUA:
            token = keys_and_args[1]
            if self.store.get(key) == token:
                self.store.pop(key, None)
                self.ttls.pop(key, None)
                return 1
            return 0
        if script == security._DECR_AND_CLEAR_LUA:
            remaining = self.counts.get(key, 0) - 1
            self.counts[key] = remaining
            if remaining <= 0:
                self.counts.pop(key, None)
                self.ttls.pop(key, None)
            return remaining
        window = keys_and_args[1]
        count = self.counts.get(key, 0) + 1
        self.counts[key] = count
        if count == 1:
            self.ttls[key] = int(window)
        return count


@pytest.fixture(autouse=True)
def redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(security, "_redis_client", fake)
    monkeypatch.setattr(security.time, "time", lambda: 1_000_000.0)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 1_000_000)
    _session.update(username=OWNER, role="staff")
    return fake


@pytest.fixture()
def fanout(monkeypatch):
    """Fake the gateway->ai-assistant hop; record what was forwarded."""
    calls = []

    def _fake(service, path, payload, timeout=None, headers=None):
        calls.append(
            {"service": service, "path": path, "payload": payload, "headers": headers}
        )
        return json.loads(json.dumps(DOWNSTREAM_OK))

    monkeypatch.setattr(gw, "_post_checked", _fake)
    return calls


def _chat(message="please check AETN1224", visit_id=None):
    body = {"message": message}
    if visit_id is not None:
        body["visit_id"] = visit_id
    return client.post("/ai/visit-chat", json=body)


def _start_visit(fanout, message="please check AETN1224"):
    r = _chat(message)
    assert r.status_code == 200, r.text
    return r.json()["visit_id"]


# --- rate limiting: own namespace, shared spend ceiling ---------------------
def test_chat_counts_in_its_own_namespace(redis, fanout):
    _chat()

    assert any(key.startswith("ratelimit:aichat:min:") for key in redis.counts)
    assert not any(key.startswith("ratelimit:ai:min:") for key in redis.counts)


def test_chat_quota_does_not_starve_the_instructions_endpoint(redis, fanout, monkeypatch):
    monkeypatch.setattr(gw.settings, "ai_chat_rate_limit_per_minute", 2)

    assert _chat().status_code == 200
    assert _chat().status_code == 200
    assert _chat().status_code == 429

    # The one-shot endpoint has its own counters and is unaffected.
    monkeypatch.setattr(gw.settings, "ai_cache_ttl_seconds", 0)
    r = client.post("/ai/intake-instructions", json={"has_insurance": False})
    assert r.status_code != 429


def test_over_cap_returns_retry_after_and_never_fans_out(redis, fanout, monkeypatch):
    monkeypatch.setattr(gw.settings, "ai_chat_rate_limit_per_minute", 1)
    _chat()

    r = _chat()

    assert r.status_code == 429
    assert r.headers["Retry-After"]
    assert len(fanout) == 1


def test_rate_limit_fault_fails_closed(redis, fanout):
    redis.fail_on.add("ratelimit:aichat")

    r = _chat()

    assert r.status_code == 503
    assert fanout == []


def test_spend_ceiling_is_shared_with_the_other_ai_endpoint(redis, fanout, monkeypatch):
    # Deliberately NOT namespaced: it bounds dollars per tenant per day, so
    # splitting it would silently raise the real ceiling.
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 1)

    assert _chat().status_code == 200
    assert _chat().status_code == 429
    assert any(key.startswith("ratelimit:ai:global:") for key in redis.counts)


def test_budget_fault_fails_closed(redis, fanout):
    redis.fail_on.add("ratelimit:ai:global")

    r = _chat()

    assert r.status_code == 503
    assert fanout == []


@pytest.mark.parametrize("status", [401, 422, 503])
def test_non_paid_downstream_status_refunds_the_reservation(
    redis, monkeypatch, status
):
    from fastapi import HTTPException

    def _raise(service, path, payload, timeout=None, headers=None):
        raise HTTPException(status_code=status, detail="downstream")

    monkeypatch.setattr(gw, "_post_checked", _raise)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 5)

    assert _chat().status_code == status

    # Nothing was charged in the end: the counter is back to empty.
    assert not [k for k in redis.counts if k.startswith("ratelimit:ai:global")]


def test_post_egress_failure_keeps_the_charge(redis, monkeypatch):
    from fastapi import HTTPException

    def _raise(service, path, payload, timeout=None, headers=None):
        raise HTTPException(status_code=502, detail="provider failed")

    monkeypatch.setattr(gw, "_post_checked", _raise)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 5)

    assert _chat().status_code == 502

    charged = [k for k in redis.counts if k.startswith("ratelimit:ai:global")]
    assert charged and redis.counts[charged[0]] == 1


# --- no response cache on this path ----------------------------------------
def test_identical_messages_are_not_collapsed_by_a_cache(redis, fanout):
    visit_id = _start_visit(fanout)
    _chat("is it still active?", visit_id=visit_id)
    _chat("is it still active?", visit_id=visit_id)

    assert len(fanout) == 3  # every turn fans out
    assert not any(key.startswith("aicache:") for key in redis.store)


# --- the per-visit lock -----------------------------------------------------
def test_a_second_concurrent_turn_in_one_visit_is_rejected(redis, fanout):
    visit_id = _start_visit(fanout)
    # Simulate a turn already in flight for this visit.
    redis.store[f"visitlock:{visit_id}"] = "someone-elses-token"

    r = _chat("is it still active?", visit_id=visit_id)

    assert r.status_code == 429
    assert r.headers["Retry-After"] == "1"
    assert len(fanout) == 1


def test_the_lock_is_released_after_a_turn(redis, fanout):
    visit_id = _start_visit(fanout)

    assert _chat("again?", visit_id=visit_id).status_code == 200
    assert f"visitlock:{visit_id}" not in redis.store


def test_the_lock_is_released_even_when_the_fanout_fails(redis, monkeypatch, fanout):
    visit_id = _start_visit(fanout)
    from fastapi import HTTPException

    def _raise(service, path, payload, timeout=None, headers=None):
        raise HTTPException(status_code=502, detail="boom")

    monkeypatch.setattr(gw, "_post_checked", _raise)
    assert _chat("again?", visit_id=visit_id).status_code == 502

    assert f"visitlock:{visit_id}" not in redis.store


# --- visit lifecycle + ownership -------------------------------------------
def test_first_turn_mints_an_opaque_visit_id_and_stores_the_visit(redis, fanout):
    r = _chat()

    visit_id = r.json()["visit_id"]
    assert len(visit_id) == 32 and all(c in "0123456789abcdef" for c in visit_id)
    record = json.loads(redis.store[f"visit:{visit_id}"])
    assert record["owner"] == OWNER
    assert redis.ttls[f"visit:{visit_id}"] == gw.settings.ai_visit_ttl_seconds


def test_second_turn_forwards_the_stored_turns_and_facts(redis, fanout):
    visit_id = _start_visit(fanout)

    _chat("is it still active?", visit_id=visit_id)

    forwarded = fanout[1]["payload"]
    assert forwarded["facts"]["insurance_id"] == MEMBER_ID
    assert forwarded["turns"], "the second turn must carry the transcript"
    assert forwarded["message"] == "is it still active?"


def test_visit_id_never_crosses_to_ai_assistant(redis, fanout):
    visit_id = _start_visit(fanout)
    _chat("again?", visit_id=visit_id)

    for call in fanout:
        assert "visit_id" not in call["payload"]
        assert visit_id not in json.dumps(call["payload"])


def test_another_users_visit_is_a_404_not_a_403(redis, fanout):
    visit_id = _start_visit(fanout)
    _session.update(username=OTHER)

    r = _chat("is it still active?", visit_id=visit_id)

    assert r.status_code == 404
    assert len(fanout) == 1  # no fan-out for someone else's visit


def test_unknown_visit_id_answers_identically(redis, fanout):
    unknown = "0" * 32

    r = _chat("hello?", visit_id=unknown)

    assert r.status_code == 404
    assert r.json()["detail"] == "visit not found"


def test_memory_fault_fails_closed(redis, fanout):
    visit_id = _start_visit(fanout)
    redis.fail_on.add(f"visit:{visit_id}")

    r = _chat("again?", visit_id=visit_id)

    # A fault cannot tell "absent" from "someone else's", so the turn must not
    # proceed as a fresh visit — that would skip the ownership check.
    assert r.status_code == 503
    assert len(fanout) == 1


def test_internal_auth_header_is_attached(redis, fanout):
    _chat()

    assert fanout[0]["headers"]["X-Internal-Auth"] == gw.settings.ai_proxy_shared_secret


# --- request validation -----------------------------------------------------
def test_malformed_visit_id_is_rejected_before_any_work(redis, fanout):
    # The value is interpolated into a Redis key, so anything but the exact
    # minted shape is rejected at the edge.
    for bad in ["visit:*", "../etc", "AETN1224", "0" * 31, "Z" * 32]:
        r = _chat("hello", visit_id=bad)
        assert r.status_code == 422, bad
    assert fanout == []


def test_over_long_message_is_rejected_without_echo(redis, fanout):
    huge = "x" * (gw.settings.ai_visit_max_message_chars + 1)

    r = _chat(huge)

    assert r.status_code == 422
    assert huge not in r.text
    assert fanout == []


def test_unknown_field_is_rejected_without_echo(redis, fanout):
    r = client.post(
        "/ai/visit-chat", json={"message": "hi", "ssn": "123-45-6789"}
    )

    assert r.status_code == 422
    assert "123-45-6789" not in r.text
    assert fanout == []


def test_invalid_body_never_charges_the_spend_ceiling(redis, fanout, monkeypatch):
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 5)

    _chat("x" * (gw.settings.ai_visit_max_message_chars + 1))

    assert not [k for k in redis.counts if k.startswith("ratelimit:ai:global")]


# --- what actually gets stored ---------------------------------------------
def test_the_stored_transcript_is_metadata_only(redis, fanout):
    # No prose is persisted: a turn records what HAPPENED, not what was said.
    visit_id = _chat(
        f"please check {MEMBER_ID} for Jane Doe, ssn 123-45-6789"
    ).json()["visit_id"]

    record = json.loads(redis.store[f"visit:{visit_id}"])
    assert record["turns"] == [
        {"role": "user", "intent": "check_eligibility", "status": None},
        {"role": "assistant", "intent": None, "status": "active"},
    ]
    for turn in record["turns"]:
        assert "text" not in turn


def test_the_clerks_message_is_never_persisted(redis, fanout):
    typed = f"please check {MEMBER_ID} for Jane Doe born 1985-03-12"

    visit_id = _chat(typed).json()["visit_id"]

    stored = redis.store[f"visit:{visit_id}"]
    for fragment in ("Jane Doe", "1985-03-12", "please check"):
        assert fragment not in stored
    # The member id survives in facts ONLY — the one approved PHI-at-rest field.
    record = json.loads(stored)
    assert record["facts"]["insurance_id"] == MEMBER_ID


def test_the_transcript_stays_bounded_across_many_turns(redis, fanout):
    visit_id = _start_visit(fanout)
    for i in range(20):
        _chat(f"turn {i}", visit_id=visit_id)

    record = json.loads(redis.store[f"visit:{visit_id}"])
    assert len(record["turns"]) == gw.settings.ai_visit_max_turns


def test_a_write_failure_does_not_fail_the_answered_turn(redis, fanout, monkeypatch):
    # The clerk already has their answer; losing continuity beats 500-ing.
    original_set = redis.set

    def _fail_visit_writes(key, value, nx=False, ex=None):
        if key.startswith("visit:"):
            raise RuntimeError("redis down")
        return original_set(key, value, nx=nx, ex=ex)

    monkeypatch.setattr(redis, "set", _fail_visit_writes)

    assert _chat().status_code == 200


# --- the no-echo boundary holds for bodies that never reach the validator ----
# Found by the pre-push security review. _validate_visit_chat_request returns a
# generic 422, but only for bodies that REACH it: the route is typed
# `payload: dict`, so a body that parses as JSON but is not an object fails
# FastAPI's own coercion first and was served by the default handler, whose error
# dict echoes the offending value verbatim under `input`. The existing tests
# missed it because they all posted well-formed objects — the PR #2 lesson
# (every test asserted the intended shape; none planted the value where the code
# does not expect it).


@pytest.mark.parametrize(
    "body",
    [
        "Jane Doe DOB 1/2/80 SSN 123-45-6789",   # a bare JSON string
        ["123-45-6789", "AETN1224"],             # a JSON list
        123456789,                               # a bare number
    ],
)
def test_non_object_bodies_are_rejected_without_echo(redis, fanout, body):
    r = client.post("/ai/visit-chat", json=body)

    assert r.status_code == 422
    assert "123-45-6789" not in r.text
    assert "Jane Doe" not in r.text
    assert "AETN1224" not in r.text
    assert "123456789" not in r.text
    assert "input" not in r.json()["detail"][0]
    assert fanout == []


def test_the_no_echo_handler_covers_the_whole_gateway(redis):
    # Registered app-wide, not per route: /login's body is a credential, and it
    # has the same `input` echo in FastAPI's default handler.
    r = client.post("/login", json={"username": "frontdesk", "password": 12345678})

    assert r.status_code == 422
    assert "12345678" not in r.text


def test_rejected_bodies_never_reach_a_log_record(redis, fanout, caplog):
    with caplog.at_level("DEBUG"):
        client.post("/ai/visit-chat", json="patient Jane Doe ssn 123-45-6789")

    assert "Jane Doe" not in caplog.text
    assert "123-45-6789" not in caplog.text
