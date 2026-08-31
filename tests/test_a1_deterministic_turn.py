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


def test_cross_patient_refused(monkeypatch):
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


def test_zero_model_calls_emergency_cross_patient(monkeypatch):
    """SPEC-3's stronger half — for `emergency` and `cross_patient` the assistant
    makes zero MODEL CALLS, not merely no model output reaching the reply."""
    assert_pinned()
    for body_kwargs in (
        {"case_id": "EVAL-016", "emergency": True},
        {
            "case_id": "EVAL-012",
            "message": "and also CIGN9087",
            "facts": {"insurance_id": "AETN1224"},
        },
    ):
        case_id = body_kwargs.pop("case_id")
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
