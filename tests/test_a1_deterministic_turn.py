"""
eligibility-assistant `turn` — the deterministic turns (SPEC-3/45/46/49).

A deterministic turn is REQ-1⁗'s exception class: no model output reaches the reply,
the citations are exactly the reason's fixed set, and the action comes from the reason
table. For `emergency` and `cross_patient` the assistant additionally makes ZERO model
calls — a stronger property than "no model output reached the reply", and the one the
scripted queue's untouched state proves.

Every test opens with the rig's identity assertions (eligibility-assistant-D-66).
"""
import pytest

from a1_rig import (
    assert_pinned,
    install_model,
    install_payer,
    outcome,
    post,
    selections,
    turn,
    verdict,
)

EMERGENCY_CITATIONS = (
    "DOC-FED-EMTALA-CMS",
    "DOC-SYN-EMERGENCY",
    "DOC-COVERAGE-QUESTION-CHEAT-SHEET",
)


@pytest.mark.parametrize("case_id", ["EVAL-016", "EVAL-024"])
def test_eval_016_024_emergency(case_id, monkeypatch):
    """SPEC-45 — emergency short-circuits BEFORE the understand step's id checks,
    with zero model calls, zero retrieval decisions and zero payer calls."""
    assert_pinned()
    scripted = install_model(monkeypatch)
    payer = install_payer(monkeypatch, verdict("active"))

    response = post(turn(case_id, emergency=True))

    assert response.status_code == 200
    body = response.json()
    assert scripted.calls == []
    assert payer.calls == []
    assert body["outcome"] == outcome.Outcome.care_first.value
    assert body["mode"] == outcome.Mode.care_first.value
    assert body["reason"] == outcome.Reason.emergency.value
    # Both cases select question type `emergency`, so the cheat sheet joins the two
    # EMTALA sources (Appendix, `emergency` row).
    assert selections(case_id)["question_type"] == "emergency"
    assert tuple(c["document_id"] for c in body["citations"]) == EMERGENCY_CITATIONS
    assert body["llm_egress"] is False
    assert body["assistant"] == "ok"


@pytest.mark.parametrize("case_tag", ["EVAL-012"])
def test_cross_patient_refused(case_tag, monkeypatch):
    """SPEC-49 [EVAL-012] — a recognised member id other than the held one refuses,
    for every role, BEFORE any retrieval, model or payer call."""
    assert_pinned()
    scripted = install_model(monkeypatch)
    payer = install_payer(monkeypatch, verdict("active"))

    response = post(
        turn(
            "EVAL-012",
            message="Also check CIGN9087 while you have it open",
            facts={"insurance_id": "AETN1224"},
        )
    )

    assert response.status_code == 200
    body = response.json()
    assert scripted.calls == []
    assert payer.calls == []
    assert body["outcome"] == outcome.Outcome.refuse.value
    assert body["reason"] == outcome.Reason.cross_patient.value
    assert body["mode"] == outcome.Mode.refuse.value
    assert [c["document_id"] for c in body["citations"]] == ["DOC-SYN-PRIVACY-FD"]
    # The visit's own confirmed id is untouched — a refusal is not a state change.
    assert body["facts"]["insurance_id"] == "AETN1224"


@pytest.mark.parametrize(
    "case_id,body_kwargs",
    [
        ("EVAL-016", {"emergency": True}),
        (
            "EVAL-012",
            {"message": "and also CIGN9087", "facts": {"insurance_id": "AETN1224"}},
        ),
    ],
    ids=["emergency", "cross_patient"],
)
def test_zero_model_calls_emergency_cross_patient(case_id, body_kwargs, monkeypatch):
    """SPEC-3's stronger half — for `emergency` and `cross_patient` the assistant
    makes zero MODEL CALLS, not merely no model output reaching the reply."""
    assert_pinned()
    scripted = install_model(monkeypatch)
    payer = install_payer(monkeypatch, verdict("active"))
    response = post(turn(case_id, **body_kwargs))
    assert response.status_code == 200, case_id
    # The scripted queue is untouched: not one create reached it, and none of the
    # bodies it would have served was consumed.
    assert scripted.calls == [], case_id
    assert scripted.remaining == 0, case_id
    assert payer.calls == [], case_id
    assert response.json()["llm_egress"] is False, case_id


def test_emergency_ignores_eligibility_state(monkeypatch):
    """SPEC-46 — while `emergency` is true the reply is identical whatever the
    member id, insurance state or payer status of the turn."""
    assert_pinned()
    replies = []
    for facts in (
        {},
        {"insurance_id": "AETN1224"},
        {"insurance_id": "CIGN9087", "last_eligibility": verdict("inactive")},
        {"insurance_id": "AETN1224", "last_eligibility": verdict("active")},
    ):
        install_model(monkeypatch)
        install_payer(monkeypatch, verdict("inactive"))
        response = post(turn("EVAL-016", emergency=True, facts=facts))
        assert response.status_code == 200
        body = response.json()
        replies.append((body["reply"], body["outcome"], body["mode"], body["reason"]))
    assert len(set(replies)) == 1, replies


# One marker per channel a model could write through. If any of these strings
# reaches a deterministic turn's reply, model output crossed REQ-1⁗'s line.
_MARKER = "MODEL-OUTPUT-SENTINEL-7431"


@pytest.mark.parametrize(
    "reason",
    [
        "emergency",
        "cross_patient",
        "validation_reject",
        "no_retrieval",
        "spend_stop",
        "model_failure",
    ],
)
def test_no_model_output_reaches_reply(reason, monkeypatch):
    """SPEC-3 — on every eligibility-assistant-D-19 reason, no model output
    reaches the reply: the citations are exactly the reason's fixed set and the
    marker the model was scripted to emit is nowhere in the response."""
    import json as _json

    from a1_rig import app_mod, settings, text_body, tool_use_body

    assert_pinned()
    case = "EVAL-001"
    payer = install_payer(monkeypatch, verdict("active", payer="Medicare"))
    body_kwargs = {"facts": {"insurance_id": "AETN1224"}}
    expected_citations = list(
        outcome.REASON_CITATION_IDS[outcome.Reason(reason)]
    )

    if reason == "emergency":
        install_model(monkeypatch, text_body(_MARKER))
        body_kwargs = {"emergency": True}
        expected_citations.append("DOC-COVERAGE-QUESTION-CHEAT-SHEET")
        case = "EVAL-016"  # question type `emergency` adds the cheat sheet
    elif reason == "cross_patient":
        install_model(monkeypatch, text_body(_MARKER))
        body_kwargs = {
            "message": f"try CIGN9087 {_MARKER}",
            "facts": {"insurance_id": "AETN1224"},
        }
    elif reason == "validation_reject":
        # The model's whole output is the marker, offered as an "action id".
        install_model(
            monkeypatch,
            tool_use_body("policy_lookup", {"topic": "eligibility-verification"}),
            text_body(_json.dumps({"citation_ids": [], "action_ids": [_MARKER]})),
        )
    elif reason == "no_retrieval":
        install_model(monkeypatch, text_body(_MARKER))
    elif reason == "spend_stop":
        install_model(monkeypatch, text_body(_MARKER))
        monkeypatch.setattr(settings, "llm_max_cost_per_request_usd", 0.000001)
    else:  # model_failure — the marker is the exception MESSAGE
        def _raise(*a, **k):
            raise app_mod.llm_client.LLMUnavailable(_MARKER)

        monkeypatch.setattr(app_mod.llm_client, "_call", _raise)
        install_payer(monkeypatch, verdict("active", payer="Medicare"))

    response = post(turn(case, **body_kwargs))

    assert response.status_code == 200
    body = response.json()
    assert _MARKER not in response.text or reason == "cross_patient", (
        "model output reached the response"
    )
    if reason == "cross_patient":
        # The marker rode the clerk's own message there; the REPLY is still clean.
        assert _MARKER not in body["reply"]
    assert body["reason"] == reason
    assert [c["document_id"] for c in body["citations"]] == expected_citations
