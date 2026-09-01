"""
eligibility-assistant `turn` — what a citation is and where it may come from
(SPEC-4/5/6).

Every test opens with the rig's identity assertions (eligibility-assistant-D-66).
"""
from a1_rig import app_mod, assert_pinned, policy_index

# The eligibility-assistant-D-19 reason table's fixed citations, from the contract
# Appendix ("Deterministic-turn reason table"). Fixed per reason, never chosen.
REASON_CITATIONS = {
    "emergency": ("DOC-FED-EMTALA-CMS", "DOC-SYN-EMERGENCY"),
    "cross_patient": ("DOC-SYN-PRIVACY-FD",),
    "validation_reject": ("DOC-SYN-NO-INVENTION",),
    "no_retrieval": ("DOC-SYN-NO-INVENTION",),
    "spend_stop": ("DOC-SYN-SPEND-STOP",),
    "model_failure": ("DOC-SYN-MODEL-FAILURE",),
}

CITATION_FIELDS = ("title", "document_id", "section", "version")


def test_reason_citations_fetched_by_id():
    """SPEC-6 — the reason's fixed citations are fetched by id THROUGH the index
    and rendered with the same four fields an agent-path citation carries."""
    assert_pinned()
    outcome = app_mod.outcome
    for reason, expected in REASON_CITATIONS.items():
        rendered = outcome.reason_citations(outcome.Reason(reason))
        assert tuple(c.document_id for c in rendered) == expected, reason
        for citation in rendered:
            assert set(citation.model_dump()) == set(CITATION_FIELDS), reason
            # Every field is the index row's own value — the label rides the row
            # and is never re-derived here (eligibility-assistant-D-61).
            row = policy_index._current().row(citation.document_id)
            assert citation.title == row.title
            assert citation.section == row.section
            assert citation.version == row.version

    # The emergency row gains the cheat sheet when the question type is `emergency`
    # (Appendix, `emergency` row).
    with_cheat_sheet = outcome.reason_citations(
        outcome.Reason.emergency, question_type="emergency"
    )
    assert tuple(c.document_id for c in with_cheat_sheet) == (
        "DOC-FED-EMTALA-CMS",
        "DOC-SYN-EMERGENCY",
        "DOC-COVERAGE-QUESTION-CHEAT-SHEET",
    )


def _decision(citation_ids, action_ids):
    import json

    from a1_rig import text_body

    return text_body(
        json.dumps({"citation_ids": list(citation_ids), "action_ids": list(action_ids)})
    )


import pytest


@pytest.mark.parametrize("case_tag", ["EVAL-001"])
def test_citation_four_fields(case_tag, monkeypatch):
    """SPEC-4 [EVAL-001] — every rendered citation carries exactly title, id,
    section and version, each the index row's OWN value: the section is the
    manifest `section_labels` string verbatim, rendered from the row and never
    split, parsed or re-derived (eligibility-assistant-D-61)."""
    from a1_rig import (
        MEMBER_ID,
        install_model,
        install_payer,
        post,
        retrieved_ids,
        tool_use_body,
        topic,
        turn,
        verdict,
    )

    assert_pinned()
    case = "EVAL-001"
    cited = retrieved_ids(case)[0]
    install_model(
        monkeypatch,
        tool_use_body("policy_lookup", {"topic": topic(case)}),
        _decision([cited], ["note_coverage_result"]),
    )
    install_payer(monkeypatch, verdict("active", payer="Medicare"))

    body = post(turn(case, facts={"insurance_id": MEMBER_ID})).json()

    assert len(body["citations"]) == 1
    citation = body["citations"][0]
    assert set(citation) == set(CITATION_FIELDS)
    row = policy_index._current().row(cited)
    assert citation["title"] == row.title
    assert citation["document_id"] == row.id
    assert citation["section"] == row.section  # the section_labels string verbatim
    assert citation["version"] == row.version


def test_unretrieved_id_never_renders(monkeypatch):
    """SPEC-5 — a REAL manifest id the turn did not retrieve cannot render: the
    selection is discarded whole and the fallback cites the reason table's id."""
    from a1_rig import (
        MEMBER_ID,
        install_model,
        install_payer,
        post,
        retrieved_ids,
        tool_use_body,
        topic,
        turn,
        verdict,
    )

    assert_pinned()
    case = "EVAL-001"
    # A genuine manifest id, deliberately from OUTSIDE this turn's retrieved set —
    # the strongest form: catalog membership alone must not admit it.
    unretrieved = "DOC-SYN-EFFECTIVE-TERM-DATES"
    assert unretrieved not in retrieved_ids(case)
    install_model(
        monkeypatch,
        tool_use_body("policy_lookup", {"topic": topic(case)}),
        _decision([unretrieved], ["note_coverage_result"]),
    )
    install_payer(monkeypatch, verdict("active", payer="Medicare"))

    body = post(turn(case, facts={"insurance_id": MEMBER_ID})).json()

    assert unretrieved not in [c["document_id"] for c in body["citations"]]
    assert unretrieved not in body["reply"]
    assert body["reason"] == "validation_reject"
    assert [c["document_id"] for c in body["citations"]] == ["DOC-SYN-NO-INVENTION"]
