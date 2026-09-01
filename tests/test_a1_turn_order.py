"""
eligibility-assistant `turn` — call order and the payer once-guard
(SPEC-19/50/51/52/53).

The order is SPEC-50's: emergency gate → cross-patient gate → understand →
agent path (model₁ → retriever → payer → model₂) → validate → fallback per
reason → ground → phrase. What this file pins is that the PAYER call is a
function of the derived intent and the held id alone — never of model output —
and that it runs at most once per turn, whichever site the agent step ended at.

Every test opens with the rig's identity assertions (eligibility-assistant-D-66).
"""
import json as _json

import pytest

from a1_rig import (
    MEMBER_ID,
    app_mod,
    assert_pinned,
    install_model,
    install_payer,
    outcome,
    policy_index,
    post,
    retrieved_ids,
    settings,
    text_body,
    tool_use_body,
    topic,
    turn,
    verdict,
)

CASE = "EVAL-001"


def _decision(citation_ids, action_ids):
    return text_body(
        _json.dumps({"citation_ids": list(citation_ids), "action_ids": list(action_ids)})
    )


def _observed(status="active", payer="Medicare"):
    return verdict(status, payer=payer)


def test_payer_never_model_triggered(monkeypatch):
    """SPEC-19 — whether the payer is called is decided by the deterministic
    intent BEFORE any model output exists, and nothing the model says can add a
    call: a model that asks for a lookup in prose changes nothing."""
    assert_pinned()
    install_model(
        monkeypatch,
        tool_use_body("policy_lookup", {"topic": topic(CASE)}),
        # The model "asks" for a payer check in its decision text; only the two
        # closed keys are read, so the plea is inert — and the intent here is
        # `other`, which buys no lookup.
        _decision([], ["retry_shortly", "proceed_per_policy", "escalate"]),
    )
    payer = install_payer(monkeypatch, _observed())

    body = post(
        turn(CASE, message="what does the policy say about referrals?",
             facts={"insurance_id": MEMBER_ID})
    ).json()

    assert payer.calls == []
    assert body["llm_egress"] is True  # the model DID run; the payer still did not


@pytest.mark.parametrize(
    "leg",
    ["sequence", "emergency_over_cross_patient", "cross_patient_over_understand"],
)
def test_call_sequence(leg, monkeypatch):
    """SPEC-50 — the order itself: model₁ → retriever → payer → model₂ on the
    agent path, and the two gates decided before it in their own precedence."""
    assert_pinned()

    if leg == "emergency_over_cross_patient":
        # A body that trips BOTH gates takes the emergency one: care_first, not
        # the refusal — the gates run in SPEC-50's order.
        install_model(monkeypatch)
        payer = install_payer(monkeypatch, _observed())
        body = post(
            turn("EVAL-016", emergency=True, message="also check CIGN9087",
                 facts={"insurance_id": MEMBER_ID})
        ).json()
        assert body["outcome"] == "care_first"
        assert body["reason"] == "emergency"
        assert payer.calls == []
        return

    if leg == "cross_patient_over_understand":
        # A second recognised id refuses BEFORE intent derivation: the check verb
        # that would otherwise buy a lookup buys nothing.
        install_model(monkeypatch)
        payer = install_payer(monkeypatch, _observed())
        body = post(
            turn(CASE, message="check CIGN9087 please",
                 facts={"insurance_id": MEMBER_ID})
        ).json()
        assert body["outcome"] == "refuse"
        assert body["reason"] == "cross_patient"
        assert payer.calls == []
        return

    events = []
    scripted = install_model(
        monkeypatch,
        tool_use_body("policy_lookup", {"topic": topic(CASE)}),
        _decision(retrieved_ids(CASE)[:1], ["note_coverage_result"]),
    )
    real_create = scripted.create

    def eventful_create(**kwargs):
        events.append("model")
        return real_create(**kwargs)

    monkeypatch.setattr(scripted, "create", eventful_create)
    real_lookup = policy_index.lookup

    def eventful_lookup(*args, **kwargs):
        events.append("retriever")
        return real_lookup(*args, **kwargs)

    monkeypatch.setattr(policy_index, "lookup", eventful_lookup)

    def eventful_payer(insurance_id):
        events.append("payer")
        return _observed()

    monkeypatch.setattr(app_mod.eligibility_client, "check_coverage", eventful_payer)

    assert post(turn(CASE, facts={"insurance_id": MEMBER_ID})).status_code == 200
    assert events == ["model", "retriever", "payer", "model"]


# --- the once-guard, exhaustively (SPEC-51; gate r3 f4 / residual (j)) -------
_INTENTS = {
    # intent -> (message, facts, payer calls expected on an agent-path turn)
    "check_eligibility": (f"please check {MEMBER_ID}", {}, 1),
    "recheck_eligibility": (
        "coverage changed — check again",
        {"insurance_id": MEMBER_ID, "last_eligibility": _observed()},
        1,
    ),
    "ask_status": (
        "is it still active?",
        {"insurance_id": MEMBER_ID, "last_eligibility": _observed()},
        0,
    ),
    "clarify_member_id": (f"policy BCBS4471 or maybe {MEMBER_ID}, not sure which", {}, 0),
    "other": ("hello, quick question", {"insurance_id": MEMBER_ID}, 0),
}

_ENDINGS = (
    "success",
    "no_retrieval",
    "validation_reject",
    "spend_stop_model1",
    "spend_stop_model2",
    "model_failure_model1",
    "model_failure_model2",
)


@pytest.mark.parametrize("ending", _ENDINGS)
@pytest.mark.parametrize("intent", list(_INTENTS))
def test_payer_at_most_once(intent, ending, monkeypatch):
    """SPEC-51 — exactly one `check_coverage` call on the two payer-triggering
    intents with an id, zero on the other three, whichever site the agent step
    ended at. `clarify_member_id` never enters the agent path (residual (j)):
    its seven cells assert the no-lookup leg — zero payer calls, zero model
    calls, the scripted queue untouched, status `ambiguous_id` — whatever
    ending they are named for, and never assert queue consumption."""
    assert_pinned()
    message, facts, expected_payer_calls = _INTENTS[intent]

    def fail_at(n):
        real_call = app_mod.llm_client._call
        seen = {"n": 0}

        def gated(*args, **kwargs):
            seen["n"] += 1
            if seen["n"] == n:
                raise app_mod.llm_client.LLMBudgetExceeded("per-request cap")
            return real_call(*args, **kwargs)

        monkeypatch.setattr(app_mod.llm_client, "_call", gated)

    def raise_at(n):
        real_call = app_mod.llm_client._call
        seen = {"n": 0}

        def gated(*args, **kwargs):
            seen["n"] += 1
            if seen["n"] == n:
                raise app_mod.llm_client.LLMUnavailable("provider fault")
            return real_call(*args, **kwargs)

        monkeypatch.setattr(app_mod.llm_client, "_call", gated)

    if ending == "success":
        scripted = install_model(
            monkeypatch,
            tool_use_body("policy_lookup", {"topic": topic(CASE)}),
            _decision(retrieved_ids(CASE)[:1], ["note_coverage_result"]),
        )
    elif ending == "no_retrieval":
        scripted = install_model(monkeypatch, text_body("nothing to retrieve"))
    elif ending == "validation_reject":
        scripted = install_model(
            monkeypatch,
            tool_use_body("policy_lookup", {"topic": topic(CASE)}),
            _decision([], ["not_a_catalog_id"]),
        )
    elif ending == "spend_stop_model1":
        scripted = install_model(monkeypatch, text_body("unreached"))
        fail_at(1)
    elif ending == "spend_stop_model2":
        scripted = install_model(
            monkeypatch, tool_use_body("policy_lookup", {"topic": topic(CASE)})
        )
        fail_at(2)
    elif ending == "model_failure_model1":
        scripted = install_model(monkeypatch, text_body("unreached"))
        raise_at(1)
    else:
        scripted = install_model(
            monkeypatch, tool_use_body("policy_lookup", {"topic": topic(CASE)})
        )
        raise_at(2)
    payer = install_payer(monkeypatch, _observed())

    response = post(turn(CASE, message=message, facts=facts))

    assert response.status_code == 200, (intent, ending)
    body = response.json()
    if intent == "clarify_member_id":
        # Residual (j): the short-circuit before the agent path — the ending the
        # cell is named for cannot occur, and the queue must stay untouched.
        assert payer.calls == [], (intent, ending)
        assert scripted.calls == [], (intent, ending)
        assert body["status"] == "ambiguous_id"
        assert body["mode"] == "no_lookup"
        return
    assert len(payer.calls) == expected_payer_calls, (intent, ending)
    if expected_payer_calls:
        assert payer.calls == [MEMBER_ID]


@pytest.mark.parametrize(
    "reason_leg", ["no_retrieval", "validation_reject", "EVAL-017", "EVAL-018"]
)
def test_fallback_per_reason(reason_leg, monkeypatch):
    """SPEC-52 — the fallback renders the payer result if one was obtained, with
    the reason's fixed citation and mode `fallback`; `spend_stop` [EVAL-017]
    persists the verdict without rendering it (eligibility-assistant-D-26)."""
    assert_pinned()
    case = {"EVAL-017": "EVAL-017", "EVAL-018": "EVAL-018"}.get(reason_leg, CASE)

    if reason_leg == "no_retrieval":
        install_model(monkeypatch, text_body("nothing to retrieve"))
        expected_reason = "no_retrieval"
    elif reason_leg == "validation_reject":
        install_model(
            monkeypatch,
            tool_use_body("policy_lookup", {"topic": topic(CASE)}),
            _decision([], ["not_a_catalog_id"]),
        )
        expected_reason = "validation_reject"
    elif reason_leg == "EVAL-017":
        install_model(monkeypatch, text_body("unreached"))
        monkeypatch.setattr(settings, "llm_max_cost_per_request_usd", 0.000001)
        expected_reason = "spend_stop"
    else:  # EVAL-018

        def _raise(*a, **k):
            raise app_mod.llm_client.LLMUnavailable("provider fault")

        monkeypatch.setattr(app_mod.llm_client, "_call", _raise)
        expected_reason = "model_failure"
    payer = install_payer(monkeypatch, _observed(payer="Aetna"))

    body = post(turn(case, message=f"check {MEMBER_ID}")).json()

    assert body["reason"] == expected_reason
    assert body["mode"] == "fallback"
    assert [c["document_id"] for c in body["citations"]] == list(
        outcome.REASON_CITATION_IDS[outcome.Reason(expected_reason)]
    )
    assert payer.calls == [MEMBER_ID]
    assert body["facts"]["last_eligibility"]["status"] == "active"
    if expected_reason == "spend_stop":
        assert body["outcome"] == "stop"
        assert body["eligibility"] is None
        assert "ACTIVE" not in body["reply"].split("\n")[0].upper()
    else:
        assert body["outcome"] == "active"
        assert "ACTIVE" in body["reply"].split("\n")[0].upper()


def test_unavailable(monkeypatch):
    """SPEC-53 [EVAL-015] — while the payer status is unavailable (a degraded
    verdict: the payer was never reached), model₂ RECEIVES that status and the
    reply carries outcome `unavailable` with `escalate`."""
    assert_pinned()
    case = "EVAL-015"
    scripted = install_model(
        monkeypatch,
        tool_use_body("policy_lookup", {"topic": topic(case)}),
        _decision(
            retrieved_ids(case)[:1], ["retry_shortly", "proceed_per_policy", "escalate"]
        ),
    )
    install_payer(monkeypatch, verdict("unknown", payer=None))

    body = post(turn(case, facts={"insurance_id": MEMBER_ID})).json()

    second_call = _json.dumps(scripted.calls[1])
    assert "unavailable" in second_call
    assert body["outcome"] == "unavailable"
    assert body["assistant"] == "ok"
    first_line = body["reply"].split("\n")[0]
    assert "could not be reached" in first_line
