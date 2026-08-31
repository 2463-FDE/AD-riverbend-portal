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
from pydantic import ValidationError

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


# eligibility-assistant: the four clerk menu selections are REQUIRED on every
# turn (SPEC-54), so every body this file posts carries them. One neutral set —
# nothing in this file is about the selections (the same idiom as
# tests/test_ai_visit_chat.py's A1_SELECTIONS).
A1_SELECTIONS = {
    "question_type": "covered_today",
    "payer": "aetna",
    "product": "commercial",
    "state": "unconfirmed",
}


def _chat(message="please check AETN1224", visit_id=None):
    body = {"message": message, **A1_SELECTIONS}
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


# --- a 200 is no longer proof of a paid call (Codex PR #14 round 3) ---------
def _fanout_returning(monkeypatch, body):
    calls = []

    def _fake(service, path, payload, timeout=None, headers=None):
        calls.append(payload)
        return json.loads(json.dumps(body))

    monkeypatch.setattr(gw, "_post_checked", _fake)
    return calls


def test_a_successful_turn_that_did_not_egress_is_refunded(redis, monkeypatch):
    # ai-assistant answers rather than throwing away a coverage verdict it
    # already paid a payer call for, so a local (pre-egress) LLM refusal now
    # arrives as a 200 carrying llm_egress=false. Refunding on the flag is what
    # stops a persistent Bedrock misconfiguration from walking the shared daily
    # ceiling to its cap and 429-ing every valid caller.
    _fanout_returning(monkeypatch, {**DOWNSTREAM_OK, "llm_egress": False})
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 5)

    r = _chat()

    assert r.status_code == 200
    assert r.json()["reply"] == DOWNSTREAM_OK["reply"], "the verdict still reaches the clerk"
    assert not [k for k in redis.counts if k.startswith("ratelimit:ai:global")]


def test_a_refunded_turn_does_not_consume_the_daily_ceiling(redis, monkeypatch):
    # The quantifier, not the anecdote: under a persistent misconfiguration the
    # clerk keeps getting answers instead of being locked out after N turns.
    _fanout_returning(monkeypatch, {**DOWNSTREAM_OK, "llm_egress": False})
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 2)

    for _ in range(5):
        assert _chat().status_code == 200


def test_a_successful_turn_that_egressed_keeps_the_charge(redis, monkeypatch):
    _fanout_returning(monkeypatch, {**DOWNSTREAM_OK, "llm_egress": True})
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 5)

    assert _chat().status_code == 200

    charged = [k for k in redis.counts if k.startswith("ratelimit:ai:global")]
    assert charged and redis.counts[charged[0]] == 1


@pytest.mark.parametrize("value", [None, "false", 0, "", "no"])
def test_only_an_explicit_false_refunds(redis, monkeypatch, value):
    # Fail toward the ceiling: a missing field, a stringified flag, or anything
    # else ambiguous must KEEP the charge. Refunding spend that really happened
    # is the direction that lets the ceiling stop bounding vendor cost.
    body = dict(DOWNSTREAM_OK)
    if value is not None:
        body["llm_egress"] = value
    _fanout_returning(monkeypatch, body)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 5)

    assert _chat().status_code == 200

    charged = [k for k in redis.counts if k.startswith("ratelimit:ai:global")]
    assert charged and redis.counts[charged[0]] == 1


def test_the_spend_flag_is_not_forwarded_to_the_portal(redis, monkeypatch):
    # Internal accounting, not part of the portal contract.
    _fanout_returning(monkeypatch, {**DOWNSTREAM_OK, "llm_egress": False})

    assert "llm_egress" not in _chat().json()


# --- assistant health IS forwarded, because spend no longer signals it -------
def test_a_degraded_assistant_is_reported_to_the_caller(redis, monkeypatch):
    # The composed failure this guards: a dead Bedrock config produces a 200
    # that looks like success AND a correctly-refunded spend counter, so neither
    # of the two things an operator watches moves. This field is the third.
    _fanout_returning(
        monkeypatch, {**DOWNSTREAM_OK, "llm_egress": False, "assistant": "degraded"}
    )

    assert _chat().json()["assistant"] == "degraded"


def test_a_healthy_turn_is_reported_ok(redis, monkeypatch):
    _fanout_returning(monkeypatch, {**DOWNSTREAM_OK, "assistant": "ok"})

    assert _chat().json()["assistant"] == "ok"


@pytest.mark.parametrize("value", [None, "OK", "", "healthy", 1, {"state": "ok"}])
def test_an_unrecognised_health_value_is_unknown_never_ok(redis, monkeypatch, value):
    # Closed vocabulary at the boundary, and the tri-state is deliberate: an
    # older ai-assistant mid-rolling-deploy omits the field entirely. Coercing
    # that to "ok" is the green-dashboard lie; coercing it to "degraded" raises
    # a false alarm on every turn of a deploy. Neither value is echoed back.
    body = dict(DOWNSTREAM_OK)
    if value is not None:
        body["assistant"] = value
    _fanout_returning(monkeypatch, body)

    r = _chat()

    assert r.json()["assistant"] == "unknown"
    if isinstance(value, str) and value:
        assert value not in r.text.replace('"unknown"', "")


# --- a 200 is not proof the body came from our renderer (round 6) -----------
# _post_checked proves only "non-error JSON". A misroute, a rolling deploy, or an
# intermediary can return a 200 the gateway then wrote over visit memory with —
# and the visit record is the ONLY copy of the confirmed member id and the payer
# verdict, so a bad write costs a re-ask and a fresh PHI-bearing payer call.
def _stored(redis, visit_id):
    return json.loads(redis.store[f"visit:{visit_id}"])


_UNUSABLE_BODIES = {
    # The finding's shape: no facts at all, previously coerced to {}.
    "facts_missing": {k: v for k, v in DOWNSTREAM_OK.items() if k != "facts"},
    # The subtler one: facts PRESENT but empty. A response_model-serialised body
    # always carries both keys (null when unset), so {} is drift, not "no state" —
    # and reading it as state is what erases a confirmed insurance_id.
    "facts_empty": {**DOWNSTREAM_OK, "facts": {}},
    # Half a facts object erases the other half just as effectively.
    "facts_partial": {**DOWNSTREAM_OK, "facts": {"insurance_id": MEMBER_ID}},
    "facts_not_an_object": {**DOWNSTREAM_OK, "facts": "AETN1224"},
    "reply_missing": {k: v for k, v in DOWNSTREAM_OK.items() if k != "reply"},
    "reply_empty": {**DOWNSTREAM_OK, "reply": ""},
    "disclaimer_missing": {k: v for k, v in DOWNSTREAM_OK.items() if k != "disclaimer"},
    # intent/status are persisted into the metadata-only transcript, so a value
    # that is not closed vocabulary must never reach the store. Free text is the
    # adversarial case: this is exactly where a clerk's typed prose would sit if
    # anything upstream ever echoed it.
    "intent_free_text": {**DOWNSTREAM_OK, "intent": "patient Jane Doe wants a check"},
    "status_free_text": {**DOWNSTREAM_OK, "status": "SSN 123-45-6789 on file"},
    "intent_not_a_string": {**DOWNSTREAM_OK, "intent": {"name": "check_eligibility"}},
    # The value door, not the key door. `insurance_id` is used directly for a
    # payer lookup on a later turn and is validated at ai-assistant's edge, so a
    # value that fails THERE must not be stored HERE — persisting it 422s every
    # subsequent turn and the visit is dead until its TTL.
    "insurance_id_free_text": {
        **DOWNSTREAM_OK,
        "facts": {**DOWNSTREAM_OK["facts"], "insurance_id": "Jane Doe 123-45-6789"},
    },
    "insurance_id_non_ascii": {
        **DOWNSTREAM_OK,
        # U+212A KELVIN SIGN — survives .upper(), which is why ai-assistant
        # rejects rather than folds it.
        "facts": {**DOWNSTREAM_OK["facts"], "insurance_id": "AETN1224K"},
    },
    "insurance_id_lower_case": {
        **DOWNSTREAM_OK,
        # ai-assistant normalises to upper at its own edge, so a lower-case id
        # did not come from it.
        "facts": {**DOWNSTREAM_OK["facts"], "insurance_id": "aetn1224"},
    },
    # Round 7: SHAPE was not enough. Every value below is upper-case ASCII and
    # passed the old `^[A-Z0-9-]+$` check, and none of them can come out of
    # `_extract_insurance_ids` — so persisting one bypasses the closed-catalog
    # false-positive control, and a later `recheck` uses the stored id DIRECTLY for
    # a payer lookup, where a 404 renders as a definitive "no active coverage".
    "insurance_id_off_catalog": {
        **DOWNSTREAM_OK,
        "facts": {**DOWNSTREAM_OK["facts"], "insurance_id": "ABC1234"},
    },
    "insurance_id_hyphenated": {
        # A catalogued prefix is not enough: the recogniser emits prefix+digits
        # with nothing between them.
        **DOWNSTREAM_OK,
        "facts": {**DOWNSTREAM_OK["facts"], "insurance_id": "AETN-1224"},
    },
    "insurance_id_too_few_digits": {
        **DOWNSTREAM_OK,
        "facts": {**DOWNSTREAM_OK["facts"], "insurance_id": "AETN12"},
    },
    "insurance_id_letters_after_the_prefix": {
        **DOWNSTREAM_OK,
        "facts": {**DOWNSTREAM_OK["facts"], "insurance_id": "AETNXYZ1224"},
    },
    "insurance_id_trailing_newline": {
        # Python's `$` also matches immediately before a trailing newline, which is
        # why the check is a fullmatch — the value goes to the payer verbatim.
        **DOWNSTREAM_OK,
        "facts": {**DOWNSTREAM_OK["facts"], "insurance_id": "AETN1224\n"},
    },
    "insurance_id_arabic_indic_digits": {
        # `re.ASCII`, not decoration: bare `\d` matches these.
        **DOWNSTREAM_OK,
        "facts": {**DOWNSTREAM_OK["facts"], "insurance_id": "AETN١٢٣٤"},
    },
    # Bounds, so a widened one cannot pass unnoticed.
    "insurance_id_too_long": {
        **DOWNSTREAM_OK,
        "facts": {**DOWNSTREAM_OK["facts"], "insurance_id": "A" * 65},
    },
    "reply_too_long": {**DOWNSTREAM_OK, "reply": "x" * 4001},
    "disclaimer_too_long": {**DOWNSTREAM_OK, "disclaimer": "x" * 1001},
    "intent_too_long": {**DOWNSTREAM_OK, "intent": "a" * 33},
    "last_eligibility_not_an_object": {
        **DOWNSTREAM_OK,
        "facts": {**DOWNSTREAM_OK["facts"], "last_eligibility": "active"},
    },
    "last_eligibility_oversized_value": {
        **DOWNSTREAM_OK,
        "facts": {
            **DOWNSTREAM_OK["facts"],
            "last_eligibility": {"status": "active", "payer": "p" * 254},
        },
    },
}


@pytest.mark.parametrize("body", _UNUSABLE_BODIES.values(), ids=list(_UNUSABLE_BODIES))
def test_an_unusable_downstream_200_is_a_502_that_never_touches_visit_memory(
    redis, fanout, monkeypatch, body
):
    visit_id = _start_visit(fanout)
    before = _stored(redis, visit_id)
    _fanout_returning(monkeypatch, body)

    r = _chat("is it still active?", visit_id=visit_id)

    assert r.status_code == 502
    # The record is byte-identical: not the facts, not the transcript, not even
    # the sliding TTL's updated_at. A retry resumes the visit rather than
    # restarting a conversation whose verdict lives nowhere else.
    assert _stored(redis, visit_id) == before
    assert before["facts"]["insurance_id"] == MEMBER_ID


def test_a_first_turn_with_an_unusable_response_stores_nothing(redis, monkeypatch):
    _fanout_returning(monkeypatch, _UNUSABLE_BODIES["facts_missing"])

    assert _chat().status_code == 502
    assert not [key for key in redis.store if key.startswith("visit:")]


def test_an_unusable_response_keeps_the_charge_even_if_it_claims_otherwise(
    redis, monkeypatch
):
    # A body we refuse to parse cannot be trusted about our own spend either. The
    # conservative direction is to over-count toward the ceiling, never to refund
    # a Bedrock call that may really have happened.
    _fanout_returning(
        monkeypatch, {**_UNUSABLE_BODIES["facts_missing"], "llm_egress": False}
    )
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 5)

    assert _chat().status_code == 502

    charged = [k for k in redis.counts if k.startswith("ratelimit:ai:global")]
    assert charged and redis.counts[charged[0]] == 1


def test_the_rejected_body_is_never_echoed_or_logged(redis, monkeypatch, caplog):
    phi = "Jane Doe SSN 123-45-6789"
    _fanout_returning(monkeypatch, {**DOWNSTREAM_OK, "intent": phi, "reply": phi})

    with caplog.at_level("DEBUG"):
        r = _chat()

    assert r.status_code == 502
    assert phi not in r.text
    assert phi not in caplog.text
    # Field names are ours and are worth having; values are not.
    assert "intent" in caplog.text


def test_a_poisoned_member_id_never_reaches_the_store_so_the_visit_survives(
    redis, fanout, monkeypatch
):
    # The whole point of rejecting the value: the next turn still works. Storing
    # an id ai-assistant's own edge refuses would 422 every later turn, and no
    # code path repairs the record — the visit would be dead until its TTL.
    visit_id = _start_visit(fanout)
    _fanout_returning(monkeypatch, _UNUSABLE_BODIES["insurance_id_non_ascii"])
    assert _chat("is it still active?", visit_id=visit_id).status_code == 502

    # A healthy turn afterwards resumes the visit, on the id that was confirmed.
    healthy = _fanout_returning(monkeypatch, DOWNSTREAM_OK)
    r = _chat("is it still active?", visit_id=visit_id)

    assert r.status_code == 200
    assert healthy[0]["facts"]["insurance_id"] == MEMBER_ID


# --- the stored id must be one the RECOGNISER could have produced (round 7) ---
def test_an_off_catalog_member_id_never_starts_a_visit(redis, monkeypatch):
    # The other half of the table above: on a FIRST turn there is no record to
    # compare, so the property is that nothing is written at all.
    _fanout_returning(monkeypatch, _UNUSABLE_BODIES["insurance_id_off_catalog"])

    assert _chat().status_code == 502
    assert not [key for key in redis.store if key.startswith("visit:")]


@pytest.mark.parametrize("prefix", gw.settings.ai_member_id_prefixes)
def test_every_catalogued_prefix_is_still_stored(redis, monkeypatch, prefix):
    # The quantifier in the other direction, so the fix cannot pass by rejecting
    # everything: every prefix the recogniser can match is still persistable —
    # including the ones that are a prefix of another (AETN/AETNA), which a
    # careless alternation truncates.
    stored_id = f"{prefix}1224"
    _fanout_returning(
        monkeypatch,
        {
            **DOWNSTREAM_OK,
            "facts": {"insurance_id": stored_id, "last_eligibility": None},
        },
    )

    r = _chat()

    assert r.status_code == 200
    assert _stored(redis, r.json()["visit_id"])["facts"]["insurance_id"] == stored_id


def test_an_empty_catalog_refuses_the_endpoint_rather_than_trusting_any_id(
    redis, fanout, monkeypatch
):
    # Mirrors ai-assistant's own guard. With no catalog this service cannot tell a
    # recognised id from a token that merely looks like one, so the misconfiguration
    # is named as a 503 before any spend instead of 502-ing every id-bearing turn.
    monkeypatch.setattr(gw, "_STORED_MEMBER_ID_RE", None)

    r = _chat()

    assert r.status_code == 503
    assert fanout == []
    assert not [k for k in redis.counts if k.startswith("ratelimit:ai:global")]


def test_an_empty_catalog_compiles_no_pattern_and_rejects_ids(monkeypatch):
    # The round-1 empty-catalog hole, one service over: joining zero prefixes
    # yields `^(?:)\d{3,9}$`, which accepts any run of digits. None is the only
    # safe answer, and the validator must reject rather than wave through when the
    # endpoint guard above is bypassed.
    assert gw._build_stored_member_id_re(()) is None

    monkeypatch.setattr(gw, "_STORED_MEMBER_ID_RE", None)
    with pytest.raises(ValidationError):
        gw._VisitChatFacts.model_validate(
            {"insurance_id": "1224", "last_eligibility": None}
        )


def test_a_non_ascii_prefix_cannot_widen_what_may_be_stored(monkeypatch):
    # `re.ASCII` constrains `\d` and `\b` and says NOTHING about a literal
    # non-ASCII character inside a prefix, so the flag alone left the gateway wider
    # than the old shape check had been. ai-assistant's VisitFacts rejects a
    # non-ASCII stored id, so persisting one 422s every later turn and the visit is
    # dead until its TTL with no path that repairs it.
    monkeypatch.setattr(
        gw, "_STORED_MEMBER_ID_RE", gw._build_stored_member_id_re(("MÉDI",))
    )

    with pytest.raises(ValidationError):
        gw._VisitChatFacts.model_validate(
            {"insurance_id": "MÉDI1224", "last_eligibility": None}
        )


@pytest.mark.parametrize(
    "digits,accepted",
    [(2, False), (3, True), (9, True), (10, False)],
)
def test_the_stored_id_digit_bound_is_exactly_the_recognisers(digits, accepted):
    # Hardcoded boundary numbers, not a re-derivation of the pattern: the `\d{3,9}`
    # in this service is a MIRROR of the recogniser's, and the drift that matters
    # is one side widening or narrowing it — the recogniser then emits an id the
    # gateway 502s (and charges for). The two literals are pinned equal by
    # tests/test_eligibility_budget_alignment.py; these numbers are what makes a
    # change here deliberate.
    token = f"AETN{'1' * digits}"

    assert bool(gw._STORED_MEMBER_ID_RE.fullmatch(token)) is accepted


def test_a_malformed_body_is_a_422_even_while_the_catalog_is_missing(
    redis, fanout, monkeypatch
):
    # Ordering: the client's error is reported as the client's error. Reporting a
    # bad body as "assistant is not configured" would hide every client mistake
    # behind a server fault for the whole misconfiguration.
    monkeypatch.setattr(gw, "_STORED_MEMBER_ID_RE", None)

    r = client.post("/ai/visit-chat", json={"message": "hi", "bogus": 1})

    assert r.status_code == 422
    assert fanout == []


def test_a_prefix_is_escaped_so_the_catalog_cannot_widen():
    # Operator input: an unescaped `.` admits ABC1234 — precisely the value this
    # round's finding was about.
    pattern = gw._build_stored_member_id_re(("A.C",))

    assert pattern.fullmatch("A.C1234")
    assert not pattern.fullmatch("ABC1234")


def test_a_verdict_key_nothing_reads_is_not_carried_into_the_store(
    redis, monkeypatch
):
    # The store holds only what the feature reads back. `reason` and `raw_status`
    # are written by eligibility_client and read by nothing, and an unvalidated
    # dict was also an unbounded write into the store that holds sessions.
    _fanout_returning(
        monkeypatch,
        {
            **DOWNSTREAM_OK,
            "facts": {
                **DOWNSTREAM_OK["facts"],
                "last_eligibility": {
                    "active": True,
                    "status": "active",
                    "payer": "edi.example.com",
                    "checked_at": "2026-07-26T10:00:00Z",
                    "raw_status": "1",
                    "reason": None,
                    "note": "patient Jane Doe, dob 1985-03-12",
                    "blob": "x" * 100_000,
                },
            },
        },
    )

    r = _chat()

    assert r.status_code == 200
    stored = json.dumps(_stored(redis, r.json()["visit_id"]))
    for dropped in ("raw_status", "reason", "note", "Jane Doe", "1985-03-12", "x" * 100):
        assert dropped not in stored
    assert "edi.example.com" in stored, "the keys the feature READS must survive"


def test_an_unusable_eligibility_degrades_to_null_and_never_fails_the_turn(
    redis, monkeypatch
):
    # Answer-only: never persisted, never fed back, and the verdict is already in
    # `reply` as server-rendered text. Failing the turn over it would discard
    # facts.last_eligibility — the verdict THIS turn's payer call already paid
    # for — and make the next turn buy it again.
    _fanout_returning(monkeypatch, {**DOWNSTREAM_OK, "eligibility": "active"})

    r = _chat()

    assert r.status_code == 200
    assert r.json()["eligibility"] is None
    stored = _stored(redis, r.json()["visit_id"])
    assert stored["facts"]["last_eligibility"]["status"] == "active"


def test_a_newer_downstream_still_answers_and_its_extra_fact_is_dropped(
    redis, monkeypatch, caplog
):
    # The other direction, and the reason facts are `extra="ignore"` rather than
    # `forbid`: mid-rolling-deploy a newer ai-assistant sends a field this
    # gateway has never heard of. Rejecting would 502 every turn of the deploy;
    # persisting it would be worse, since the next turn echoes stored facts back
    # and ai-assistant's own extra="forbid" would 422 the visit until its TTL.
    _fanout_returning(
        monkeypatch,
        {
            **DOWNSTREAM_OK,
            "facts": {**DOWNSTREAM_OK["facts"], "plan_type": "PPO"},
            "brand_new_top_level_field": {"anything": True},
        },
    )

    with caplog.at_level("DEBUG"):
        r = _chat()

    assert r.status_code == 200
    stored = _stored(redis, r.json()["visit_id"])
    assert stored["facts"]["insurance_id"] == MEMBER_ID
    assert "plan_type" not in stored["facts"]
    # The drop is the ONLY signal that a deploy is quietly losing a fact, so it
    # is a log line, not a silent success — a count, never the key itself.
    assert "unknown fact field" in caplog.text
    assert "plan_type" not in caplog.text


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


def _break_all_writes(redis, monkeypatch):
    """Every SET fails, GETs still answer — the `maxmemory` + `noeviction` shape."""
    def _fail(key, value, nx=False, ex=None):
        raise RuntimeError("OOM command not allowed when used memory > 'maxmemory'")

    monkeypatch.setattr(redis, "set", _fail)


def _lock_write_lands_then_faults(redis, monkeypatch):
    """The OTHER ordinary fault: the SET is applied and its reply is lost.

    A reset connection, a read timeout, or a failover mid-command. The key exists
    afterwards, so a token discarded here orphans it — which is why the token
    rides on VisitLockUnavailable. Returns a callable that heals the store, so a
    test can assert what a retry sees once Redis recovers.
    """
    original_set = redis.set

    def _set(key, value, nx=False, ex=None):
        result = original_set(key, value, nx=nx, ex=ex)
        if key.startswith("visitlock:"):
            raise RuntimeError("Connection reset by peer")
        return result

    monkeypatch.setattr(redis, "set", _set)
    return lambda: monkeypatch.setattr(redis, "set", original_set)


# The lock guards STATE, so it does not fail open (Codex PR #14 round 7). Most
# cases below narrow the injection to the `visitlock:` keys, which ISOLATES the
# lock: the visit record's own write faults have their own tests further down, and
# a blanket fault on GET too would 503 at the memory read and prove nothing about
# the lock. `_break_all_writes` then covers the full store-side fault, because a
# property that only holds for the narrowed injection is an artifact of the fake
# (pre-push review, round 7).
def test_a_lock_write_fault_on_an_existing_visit_is_a_503(redis, fanout):
    visit_id = _start_visit(fanout)
    before = _stored(redis, visit_id)
    redis.fail_on.add("visitlock:")

    r = _chat("is it still active?", visit_id=visit_id)

    assert r.status_code == 503
    assert len(fanout) == 1, "the turn never fanned out"
    assert _stored(redis, visit_id) == before, "and the record is untouched"


def test_two_turns_on_one_visit_cannot_both_proceed_without_a_lock(redis, fanout):
    # The finding itself. With a synthetic token handed back on the fault, BOTH
    # turns believed they held the lock: both read this record, both would spend a
    # PHI-bearing payer call, and whichever saved second would drop the other's
    # appended turns and facts — the confirmed member id and verdict live nowhere
    # else. Sequential requests are the same read-modify-write the concurrent pair
    # performs; what is asserted is that no second turn is ever admitted.
    visit_id = _start_visit(fanout)
    before = _stored(redis, visit_id)
    redis.fail_on.add("visitlock:")

    first = _chat("is it still active?", visit_id=visit_id)
    second = _chat("still active?", visit_id=visit_id)

    assert [first.status_code, second.status_code] == [503, 503]
    assert len(fanout) == 1, "neither turn reached ai-assistant or the payer"
    assert _stored(redis, visit_id) == before


def test_a_lock_fault_costs_no_spend(redis, fanout, monkeypatch):
    # 503 is raised before _reserve_ai_budget, so there is nothing to refund and
    # a store fault cannot walk the shared daily ceiling to its cap.
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 5)
    visit_id = _start_visit(fanout)
    redis.fail_on.add("visitlock:")

    assert _chat("again?", visit_id=visit_id).status_code == 503

    charged = [k for k in redis.counts if k.startswith("ratelimit:ai:global")]
    assert charged and redis.counts[charged[0]] == 1, "only the first turn charged"


def test_a_lock_fault_names_itself_in_the_log_without_a_value(redis, fanout, caplog):
    # A guard the operator cannot see firing is a green dashboard over a dead
    # feature. The cause is named; the visit id and the member id are not.
    visit_id = _start_visit(fanout)
    redis.fail_on.add("visitlock:")

    with caplog.at_level("DEBUG"):
        assert _chat("again?", visit_id=visit_id).status_code == 503

    assert "visit lock unavailable" in caplog.text
    assert visit_id not in caplog.text


def test_a_lost_lock_reply_does_not_wedge_the_visit(redis, fanout, monkeypatch):
    # The fault the `noeviction` shape does not cover, and the one a discarded
    # token turns into an outage: the SET LANDED and the reply was lost. The lock
    # key then exists with a token nobody holds, and for the whole lock TTL (75s
    # by default) every retry answers 429 "already processing" — falsifying the
    # 503's own promise that the retry resumes the conversation.
    visit_id = _start_visit(fanout)
    heal = _lock_write_lands_then_faults(redis, monkeypatch)

    assert _chat("again?", visit_id=visit_id).status_code == 503

    heal()
    r = _chat("still active?", visit_id=visit_id)

    assert r.status_code == 200, "a healthy retry resumes the visit, never 429"
    assert f"visitlock:{visit_id}" not in redis.store


def test_a_lost_lock_reply_on_a_first_turn_is_cleared_with_the_turn(
    redis, fanout, monkeypatch
):
    # Same fault, unlocked branch: the token still has to reach the `finally`, or
    # the visit this turn just created is wedged from its second message onward.
    heal = _lock_write_lands_then_faults(redis, monkeypatch)

    body = _chat().json()

    assert body["visit_id"] is not None
    heal()
    assert f"visitlock:{body['visit_id']}" not in redis.store
    assert _chat("again?", visit_id=body["visit_id"]).status_code == 200


def test_an_all_writes_fault_still_refuses_an_existing_visit(
    redis, fanout, monkeypatch
):
    # Not an artifact of failing one key prefix: under the full store-side fault
    # the record still LOADS (so ownership is verified) and the turn is still
    # refused before any fan-out.
    visit_id = _start_visit(fanout)
    before = _stored(redis, visit_id)
    _break_all_writes(redis, monkeypatch)

    assert _chat("again?", visit_id=visit_id).status_code == 503
    assert len(fanout) == 1
    assert _stored(redis, visit_id) == before


def test_a_first_turn_under_an_all_writes_fault_degrades_honestly(
    redis, fanout, monkeypatch
):
    # The unlocked first turn is not claimed to preserve a conversation: with every
    # SET failing it answers once and SAYS so, rather than handing back a visit id
    # that 404s on the clerk's next message (round 2's rule, unchanged by round 7).
    _break_all_writes(redis, monkeypatch)

    body = _chat().json()

    assert body["visit_id"] is None
    assert body["visit_memory"] == "unavailable"


def test_a_first_turn_survives_a_lock_write_fault(redis, fanout):
    # Nothing to serialise against: the id was minted inside this request and no
    # client has ever seen it, so failing closed here would be an outage for new
    # visits that buys no state safety.
    redis.fail_on.add("visitlock:")

    r = _chat()

    assert r.status_code == 200
    assert r.json()["visit_memory"] == "ok"
    assert len(fanout) == 1


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


def _break_visit_writes(redis, monkeypatch):
    """Fail only the visit record write; the lock and the quota keys still work."""
    original_set = redis.set

    def _fail_visit_writes(key, value, nx=False, ex=None):
        if key.startswith("visit:"):
            raise RuntimeError("redis down")
        return original_set(key, value, nx=nx, ex=ex)

    monkeypatch.setattr(redis, "set", _fail_visit_writes)


def test_a_write_failure_does_not_fail_the_answered_turn(redis, fanout, monkeypatch):
    # The clerk already has their answer; losing continuity beats 500-ing.
    _break_visit_writes(redis, monkeypatch)

    assert _chat().status_code == 200


def test_a_failed_first_write_hands_back_no_visit_id(redis, fanout, monkeypatch):
    # Round 2: the 200 above was correct and, on its own, was the defect. The
    # response still carried a visit_id for a record that was never written, so
    # the clerk's NEXT message answered 404 "visit not found" after the payer
    # call and the model call had already been paid for. Continuity is lost
    # either way; what this asserts is that the client is told.
    _break_visit_writes(redis, monkeypatch)

    body = _chat().json()

    assert body["visit_id"] is None, "an unstored visit id must not be handed out"
    assert body["visit_memory"] == "unavailable"
    assert body["reply"], "the answered turn is still delivered"


def test_a_failed_later_write_keeps_the_visit_that_still_resolves(redis, fanout, monkeypatch):
    # The mirror case, and the one a blanket "null the id on any failed write"
    # gets wrong: the record was loaded at the top of this request, so it is
    # still in Redis and still loadable — only this turn's append was lost.
    # Discarding the id here would throw away retrievable context, and under a
    # PERSISTENT write fault (Redis at maxmemory with noeviction) it would do so
    # on every turn, resetting the conversation per message.
    visit_id = _start_visit(fanout)
    _break_visit_writes(redis, monkeypatch)

    body = _chat("is it still active?", visit_id=visit_id).json()

    assert body["visit_id"] == visit_id
    assert body["visit_memory"] == "stale", "memory is available; this turn is missing from it"
    assert security.visit_memory_get(visit_id, OWNER) is not None


def test_a_persisted_turn_reports_its_memory_as_ok(redis, fanout):
    body = _chat().json()

    assert body["visit_memory"] == "ok"
    assert f"visit:{body['visit_id']}" in redis.store


@pytest.mark.parametrize("broken_at", [None, "first", "second"])
def test_a_returned_visit_id_always_resolves(redis, fanout, monkeypatch, broken_at):
    # The invariant behind the cases above, over both turn shapes rather than the
    # one failure mode that is easiest to reproduce: whatever the store does, the
    # response never names a visit a follow-up turn cannot load — and a turn that
    # DID persist always names one, so the invariant cannot be satisfied by
    # returning null forever.
    if broken_at == "first":
        _break_visit_writes(redis, monkeypatch)

    first = _chat().json()
    if broken_at == "first":
        assert first["visit_id"] is None and first["visit_memory"] == "unavailable"
        return
    assert first["visit_id"] and first["visit_memory"] == "ok"

    if broken_at == "second":
        _break_visit_writes(redis, monkeypatch)
    second = _chat("is it still active?", visit_id=first["visit_id"]).json()

    for body in (first, second):
        assert body["visit_id"] is not None
        assert body["visit_memory"] in ("ok", "stale")
        assert security.visit_memory_get(body["visit_id"], OWNER) is not None, (
            "a visit id in a response must be loadable by the next turn"
        )


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
