"""
eligibility-assistant `turn` — the agent path (SPEC-1/2/21/22/23).

model₁ chooses the topic and the FRAMEWORK executes the retriever; the application
binds payer/product/state and runs the payer call; model₂ chooses the citations and
the action from what came back. Nothing in application code stands in for the
framework's own run — that is what SPEC-21 asserts and what
``test_framework_executes_turn`` reads off the compiled graph.

Every test opens with the rig's identity assertions (eligibility-assistant-D-66).
"""
import json

import pytest

from a1_rig import (
    MEMBER_ID,
    assert_pinned,
    install_model,
    install_payer,
    post,
    retrieved_ids,
    text_body,
    tool_use_body,
    topic,
    turn,
    verdict,
)


def schemas_default_for_active(case_id):
    """What the application WOULD have selected for an active outcome on its own."""
    from a1_rig import app_mod, selections

    return app_mod.visit_templates.a1_default_selection(
        "active", selections(case_id)["question_type"]
    )


def decision_body(citation_ids, action_ids):
    """Model₂'s answer: the decision as a validated JSON text block."""
    return text_body(json.dumps({"citation_ids": list(citation_ids), "action_ids": list(action_ids)}))


@pytest.mark.parametrize("case_tag", ["EVAL-001"])
def test_model1_chooses_topic_app_binds_selections(case_tag, monkeypatch):
    """SPEC-1 [EVAL-001] — model₁ chooses the topic and invokes the retriever with
    that ONE argument; the application binds the turn's payer/product/state at
    execution; the retriever returns before any eligibility action runs."""
    assert_pinned()
    case = "EVAL-001"
    scripted = install_model(
        monkeypatch,
        tool_use_body("policy_lookup", {"topic": topic(case)}),
        decision_body([retrieved_ids(case)[0]], ["note_coverage_result"]),
    )
    payer = install_payer(monkeypatch, verdict("active", payer="Medicare"))

    response = post(turn(case, facts={"insurance_id": MEMBER_ID}))
    assert response.status_code == 200

    # The model's whole argument surface is `topic` — payer, product and state never
    # appear in what it sent, and the tool's own schema forbids them.
    first_call = scripted.calls[0]
    tool_names = [t["name"] for t in first_call["extra_body"]["tools"]]
    assert tool_names == ["policy_lookup"]
    schema = first_call["extra_body"]["tools"][0]["input_schema"]
    assert set(schema["properties"]) == {"topic"}
    # The topic is the closed category enumeration, not a free-text string. Rejection
    # of an extra key / a free-text value / a document id is `PolicyLookupArgs`'
    # ``extra="forbid"`` in process, which `corpus` pins
    # (tests/test_a1_retriever.py::test_tool_arg_topic_only_app_binds_rest); what this
    # asserts is that the model was never OFFERED another argument.
    assert schema["properties"]["topic"]["enum"]

    # The retriever ran before the payer call: the tool result is in model₂'s body,
    # and the payer was asked exactly once, for the turn's own id.
    assert len(scripted.calls) == 2
    assert payer.calls == [MEMBER_ID]


@pytest.mark.parametrize("case_tag", ["EVAL-001"])
def test_model2_chooses_citations_and_action(case_tag, monkeypatch):
    """SPEC-2 — model₂ is presented the retrieved rows and the payer status and
    chooses the citation set and the action from them; the application pre-selects
    neither."""
    assert_pinned()
    case = "EVAL-001"
    scripted = install_model(
        monkeypatch,
        tool_use_body("policy_lookup", {"topic": topic(case)}),
        decision_body([retrieved_ids(case)[0]], ["note_coverage_result", "escalate"]),
    )
    install_payer(monkeypatch, verdict("active", payer="Medicare"))

    response = post(turn(case, facts={"insurance_id": MEMBER_ID}))
    body = response.json()
    assert response.status_code == 200

    second_call = json.dumps(scripted.calls[1])
    # Model₂ is PRESENTED the retrieved rows and the payer status.
    assert retrieved_ids(case)[0] in second_call
    assert "active" in second_call

    # And it chose from them. The application pre-selected neither: it rendered ONE
    # of the four retrieved rows, not all four and not a default, and the action list
    # is the model's two ids rather than the one id `a1_default_selection` would have
    # produced on its own for this outcome.
    assert len(retrieved_ids(case)) > 1
    assert [c["document_id"] for c in body["citations"]] == [retrieved_ids(case)[0]]
    assert schemas_default_for_active(case) == ["note_coverage_result"]
    assert body["reply"].count("\n- ") == 2
    assert body["mode"] in ("real", "fixture")
    assert body["reason"] is None
    assert body["llm_egress"] is True


def test_framework_executes_turn(monkeypatch):
    """SPEC-21 — tool selection, the tool call and model₂'s decision happen inside
    the framework's run, not in application code on its behalf.

    Read off the compiled graph's own node set and off the call stack at the moment
    the retriever runs: a hand-rolled loop would show neither.
    """
    assert_pinned()
    from a1_rig import agent_turn, policy_index

    graph = agent_turn.build_graph(payer="medicare", product="original_medicare", state="unconfirmed")
    assert {"model", "tools"} <= set(graph.get_graph().nodes)

    case = "EVAL-001"
    # Scripted BEFORE the recorder is installed, so the only lookup the recorder sees
    # is the one the framework's own tools node makes.
    install_model(
        monkeypatch,
        tool_use_body("policy_lookup", {"topic": topic(case)}),
        decision_body([retrieved_ids(case)[0]], ["note_coverage_result"]),
    )
    install_payer(monkeypatch, verdict("active", payer="Medicare"))

    frames = []
    real_lookup = policy_index.lookup

    def recording_lookup(*args, **kwargs):
        import traceback

        frames.append([frame.filename for frame in traceback.extract_stack()])
        return real_lookup(*args, **kwargs)

    monkeypatch.setattr(policy_index, "lookup", recording_lookup)

    assert post(turn(case, facts={"insurance_id": MEMBER_ID})).status_code == 200
    assert frames, "the retriever never ran"
    # The retriever ran underneath the framework's tools node, not underneath app.py.
    assert any("langchain" in name or "langgraph" in name for name in frames[0])


@pytest.mark.parametrize(
    "bound", ["no_retrieval", "second_tool_call", "third_model_call"]
)
def test_loop_bound(bound, monkeypatch):
    """SPEC-22 — exactly one tool call and exactly two model calls.

    Three ways the bound can be reached, and each names its own reason: model₁
    answering without retrieving is `no_retrieval` (there is nothing to cite and no
    second call worth paying for); a second tool call is `validation_reject` (a second
    retrieval is outside the vocabulary this turn was bounded to); a third model call
    is `validation_reject` at the ``before_model`` backstop.

    None of the three is a health fault: the assistant worked, the answer did not fit,
    and the fallback is the designed response to that (eligibility-assistant-D-71).
    """
    assert_pinned()
    from a1_rig import agent_turn, outcome

    case = "EVAL-001"

    if bound == "third_model_call":
        # Driven on the middleware directly: the graph's own loop cannot reach a third
        # model call without a second tool call, which `second_tool_call` already
        # bounds — the two guards close the same door from opposite sides, and this is
        # the backstop half.
        state = agent_turn.TurnState()
        state.model_calls = agent_turn.MAX_MODEL_CALLS
        middleware = agent_turn.TurnMiddleware(
            state, agent_turn.PayerGate(None, False), lambda status, rows: ""
        )
        assert middleware.before_model({"messages": []}) == {"jump_to": "end"}
        assert state.reason == outcome.Reason.validation_reject.value
        return

    if bound == "no_retrieval":
        bodies = [text_body("I do not need to look anything up.")]
        expected_reason = outcome.Reason.no_retrieval.value
        expected_calls = 1
    else:
        bodies = [
            tool_use_body("policy_lookup", {"topic": topic(case)}),
            tool_use_body("policy_lookup", {"topic": topic(case)}, block_id="toolu-2"),
        ]
        expected_reason = outcome.Reason.validation_reject.value
        expected_calls = 2

    scripted = install_model(monkeypatch, *bodies)
    install_payer(monkeypatch, verdict("active", payer="Medicare"))
    body = post(turn(case, facts={"insurance_id": MEMBER_ID})).json()

    assert body["reason"] == expected_reason
    assert body["mode"] == outcome.Mode.fallback.value
    assert len(scripted.calls) == expected_calls
    assert body["assistant"] == "ok"


@pytest.mark.parametrize(
    "case_id,site",
    [("EVAL-017", "model1"), ("EVAL-017", "model2")],
    # Suffixes deliberately outside the SPEC-37 grep shape (`-[a-z]*`), so the
    # two sites count as ONE case id.
    ids=["EVAL-017.model1", "EVAL-017.model2"],
)
def test_budget_gate_each_call_spend_stop(case_id, site, monkeypatch):
    """SPEC-23 [EVAL-017] — the existing per-request preflight gates EACH of the two
    model calls before its egress, with no new per-turn reservation.

    At model₁ the turn has zero model egress; at model₂ it has some and no further.
    Either way the reason is `spend_stop` and the outcome is `stop`, and the payer
    call is unaffected (SPEC-51): its verdict is persisted in facts and deliberately
    NOT rendered, because restating a coverage answer beside a stop would claim the
    turn finished (eligibility-assistant-D-26).
    """
    assert_pinned()
    from a1_rig import app_mod, outcome, settings

    def script():
        scripted = install_model(
            monkeypatch,
            tool_use_body("policy_lookup", {"topic": topic(case_id)}),
            decision_body([retrieved_ids(case_id)[0]], ["note_coverage_result"]),
        )
        return scripted, install_payer(monkeypatch, verdict("active", payer="Aetna"))

    if site == "model1":
        # The cost cap is below even model₁'s payload, so nothing ever egresses.
        scripted, payer = script()
        monkeypatch.setattr(settings, "llm_max_cost_per_request_usd", 0.000001)
        expected_egress = False
        expected_calls = 0
    else:
        # The token cap admits model₁'s payload and refuses model₂'s larger one. The
        # threshold is MEASURED from a clean run rather than guessed, so this asserts
        # "the gate ran at the second site", not "this number sits between".
        scripted, _ = script()
        assert post(turn(case_id, facts={"insurance_id": MEMBER_ID})).status_code == 200
        sizes = [
            app_mod.llm_client.max_input_tokens(
                call["messages"],
                system=call.get("system"),
                extra_body=call.get("extra_body"),
            )
            for call in scripted.calls
        ]
        assert len(sizes) == 2 and sizes[0] < sizes[1]
        scripted, payer = script()
        monkeypatch.setattr(settings, "llm_max_input_tokens", (sizes[0] + sizes[1]) // 2)
        expected_egress = True
        expected_calls = 1

    body = post(turn(case_id, facts={"insurance_id": MEMBER_ID})).json()

    assert len(scripted.calls) == expected_calls
    assert body["reason"] == outcome.Reason.spend_stop.value
    assert body["outcome"] == outcome.Outcome.stop.value
    assert body["mode"] == outcome.Mode.fallback.value
    assert body["llm_egress"] is expected_egress
    assert [c["document_id"] for c in body["citations"]] == ["DOC-SYN-SPEND-STOP"]
    assert payer.calls == [MEMBER_ID]
    assert body["facts"]["last_eligibility"]["status"] == "active"
    assert "ACTIVE" not in body["reply"]
