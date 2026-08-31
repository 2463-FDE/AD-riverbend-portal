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
