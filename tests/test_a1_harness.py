"""
eligibility-assistant `turn` — the remaining Appendix turn cases (SPEC-37 /
eligibility-assistant-D-12, D-31): one parametrised test per case id, each
asserting the outcome, the action ids, mode/reason, and the `DOC-*` citations
the Appendix assigns.

`expected_source_ids` is read as a SUBSET (residual (f) / Open (5)): every
expected id the turn can legally retrieve must be cited; an expected id outside
the case's retrieval — a different topic's row (EVAL-025's front-desk script) or
one the `A1_RETRIEVAL_MAX_ROWS` cap truncates behind higher-tier rows
(EVAL-022/026's tier-4/5 synthetic companions) — cannot render (SPEC-5) and is
excluded here with the reason stated.

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
    post,
    retrieved_ids,
    text_body,
    tool_use_body,
    topic,
    turn,
    verdict,
)

visit_templates = app_mod.visit_templates

CHECK = f"please check {MEMBER_ID}"

# case id -> (message, payer verdict or None for a no-lookup intent, model
# action selection, expected outcome, expected DOC citations)
_CASES = {
    "EVAL-002": (
        CHECK,
        verdict("inactive", payer="Aetna", active=False),
        ["verify_card_details", "self_pay_options"],
        "inactive",
        ["DOC-SYN-EFFECTIVE-TERM-DATES"],
    ),
    "EVAL-004": (
        CHECK,
        verdict("active", payer="Aetna", active=True),
        ["reverify"],
        "reverify",
        ["DOC-SYN-REVERIFICATION-TRIGGERS"],
    ),
    "EVAL-005": (
        CHECK,
        verdict("active", payer="Humana", active=True),
        ["reverify"],
        "reverify",
        ["DOC-SYN-REVERIFICATION-TRIGGERS"],
    ),
    "EVAL-006": (
        # A question about the documents, not a member: intent `other`, no payer
        # call — the applicability check owns the turn (tier-4-only retrieval).
        "is the old training bulletin still what we should follow?",
        None,
        ["escalate"],
        "refuse_definitive",
        ["DOC-SYN-CITATION-RECENCY"],
    ),
    "EVAL-009": (
        CHECK,
        verdict("active", payer="Medicare", active=True),
        ["note_coverage_result", "auth_unknown"],
        "active",
        ["DOC-FED-PRIOR-AUTH-CMS", "DOC-SYN-ELIG-VS-PA"],
    ),
    "EVAL-021": (
        CHECK,
        verdict("unknown", payer="Cigna"),
        ["retry_shortly", "proceed_per_policy", "escalate", "confirm_which_member_id"],
        "unknown",
        ["DOC-SYN-MEMBER-ID-MISMATCH"],
    ),
    "EVAL-022": (
        CHECK,
        verdict("active", payer="Medicaid", active=True),
        ["note_coverage_result", "network_unknown", "escalate"],
        "active",
        # DOC-SYN-MEDICAID-MC-TRAINING is expected but tier-5: the cap keeps the
        # five higher-tier rows and truncates it out (subset reading).
        ["DOC-FED-MEDICAID-MANAGED-CARE"],
    ),
    "EVAL-025": (
        CHECK,
        verdict("inactive", payer="Anthem", active=False),
        ["reverify", "note_disputed", "escalate"],
        "reverify",
        # DOC-FRONT-DESK-SCRIPTS is expected but lives in another topic and
        # cannot be retrieved on this turn (subset reading).
        ["DOC-SYN-REVERIFICATION-TRIGGERS"],
    ),
    "EVAL-026": (
        CHECK,
        verdict("active", payer="Medicare", active=True),
        ["note_coverage_result", "collect_secondary", "escalate"],
        "active",
        # DOC-SYN-COB-FRONT-DESK is expected but tier-4 behind five tier-2 rows:
        # the cap truncates it out (subset reading).
        ["DOC-FED-COB-GETTING-STARTED"],
    ),
    "EVAL-027": (
        CHECK,
        verdict("active", payer="Cigna", active=True),
        ["note_coverage_result", "network_unknown", "escalate"],
        "active",
        ["DOC-FED-HC-NETWORK", "DOC-SYN-PLAN-NETWORK"],
    ),
    "EVAL-028": (
        CHECK,
        verdict("active", payer="Humana", active=True),
        ["note_coverage_result", "referral_required"],
        "active",
        ["DOC-SYN-PCP-REFERRAL"],
    ),
    "EVAL-032": (
        CHECK,
        verdict("inactive", payer="UnitedHealthcare", active=False),
        ["verify_card_details", "self_pay_options"],
        "inactive",
        ["DOC-SYN-EFFECTIVE-TERM-DATES"],
    ),
}


@pytest.mark.parametrize("case_id", list(_CASES))
def test_appendix_turn_case(case_id, monkeypatch):
    assert_pinned()
    message, payer_verdict, actions, expected_outcome, expected_citations = _CASES[case_id]

    for cited in expected_citations:
        assert cited in retrieved_ids(case_id), (
            f"{case_id}: {cited} is not retrievable — the table is wrong, not the turn"
        )
    scripted = install_model(
        monkeypatch,
        tool_use_body("policy_lookup", {"topic": topic(case_id)}),
        text_body(
            _json.dumps({"citation_ids": expected_citations, "action_ids": actions})
        ),
    )
    payer = install_payer(
        monkeypatch, payer_verdict or verdict("active", payer="unreachable")
    )

    kwargs = {"facts": {"insurance_id": MEMBER_ID}}
    body = post(turn(case_id, message=message, **kwargs)).json()

    assert body["outcome"] == expected_outcome, (case_id, body["reason"])
    assert body["reason"] is None, case_id
    assert body["mode"] in ("real", "fixture"), case_id
    assert [c["document_id"] for c in body["citations"]] == expected_citations, case_id
    for item in visit_templates.render(actions):
        assert item in body["reply"], (case_id, item)
    if payer_verdict is None:
        assert payer.calls == [], case_id
    else:
        assert payer.calls == [MEMBER_ID], case_id
