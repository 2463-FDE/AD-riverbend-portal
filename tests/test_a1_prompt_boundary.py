"""
eligibility-assistant `turn` — what may cross the vendor boundary
(SPEC-12/55, SPEC-21/22).

The captured Bedrock bodies ARE what left the process: the rig scripts
`client.messages.create` with the whole pre-egress stack live in front of it,
so `scripted.calls` is the D13 control surface under test.

Every test opens with the rig's identity assertions (eligibility-assistant-D-66).
"""
import json as _json

from a1_rig import (
    MEMBER_ID,
    agent_turn,
    app_mod,
    assert_pinned,
    install_model,
    install_payer,
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

NAME = "Jane Doe"
DOB = "1985-03-12"
SSN = "123-45-6789"
SECOND_ID = "CIGN9087"
PHI = (NAME, DOB, SSN)


def _decision(citation_ids, action_ids):
    return text_body(
        _json.dumps({"citation_ids": list(citation_ids), "action_ids": list(action_ids)})
    )


def _blob(calls):
    return _json.dumps(calls, default=str)


def test_egress_excludes_clerk_text_and_ids(monkeypatch):
    """SPEC-12 — PHI planted in the message and the facts, and the member id
    itself, appear in NO captured Bedrock body, on either call, on any path.

    Three paths: the successful agent turn, the validation-reject fallback (both
    make two calls each, all four bodies scanned), and the cross-patient turn a
    second id triggers (zero calls — the strongest exclusion of all).
    """
    assert_pinned()
    case = "EVAL-001"
    message = f"check coverage for {NAME}, dob {DOB}, ssn {SSN}, member {MEMBER_ID}"
    facts = {
        "insurance_id": MEMBER_ID,
        # The one shape `facts` can carry prose-ish downstream content in.
        "last_eligibility": {**verdict("active", payer="Medicare"), "raw_status": "1"},
    }

    captured = []
    # Path 1: the successful agent turn.
    scripted = install_model(
        monkeypatch,
        tool_use_body("policy_lookup", {"topic": topic(case)}),
        _decision(retrieved_ids(case)[:1], ["note_coverage_result"]),
    )
    install_payer(monkeypatch, verdict("active", payer="Medicare"))
    assert post(turn(case, message=message, facts=facts)).status_code == 200
    assert len(scripted.calls) == 2
    captured.extend(scripted.calls)

    # Path 2: the validation-reject fallback — the reject happens AFTER both
    # egresses, so both bodies exist and both must be clean.
    scripted = install_model(
        monkeypatch,
        tool_use_body("policy_lookup", {"topic": topic(case)}),
        _decision([], ["not_a_catalog_id"]),
    )
    install_payer(monkeypatch, verdict("active", payer="Medicare"))
    assert post(turn(case, message=message, facts=facts)).status_code == 200
    assert len(scripted.calls) == 2
    captured.extend(scripted.calls)

    blob = _blob(captured)
    for value in PHI + (MEMBER_ID,):
        assert value not in blob, f"{value!r} crossed the vendor boundary"
    # The clerk's free text is not merely redacted — no fragment of it appears.
    assert "check coverage for" not in blob

    # Path 3: a second recognised id — the turn refuses BEFORE any egress.
    scripted = install_model(monkeypatch)
    install_payer(monkeypatch, verdict("active"))
    body = post(
        turn(case, message=f"also try {SECOND_ID}", facts={"insurance_id": MEMBER_ID})
    ).json()
    assert body["reason"] == "cross_patient"
    assert scripted.calls == []


def test_selections_closed_reach_prompt(monkeypatch):
    """SPEC-55 — the four clerk menu selections (closed enums) are what reach
    model₁, alongside the derived intent and the turn count — and nothing else
    identifies the turn."""
    assert_pinned()
    case = "EVAL-001"
    scripted = install_model(
        monkeypatch,
        tool_use_body("policy_lookup", {"topic": topic(case)}),
        _decision(retrieved_ids(case)[:1], ["note_coverage_result"]),
    )
    install_payer(monkeypatch, verdict("active", payer="Medicare"))

    from a1_rig import selections

    assert post(turn(case, facts={"insurance_id": MEMBER_ID})).status_code == 200

    model1 = _blob([scripted.calls[0]])
    for value in selections(case).values():
        assert value in model1, f"selection {value!r} missing from model₁'s payload"
    assert "check_eligibility" in model1  # the derived intent enum, not free text
    assert MEMBER_ID not in model1


def test_prompt_fits_reserve(monkeypatch):
    """SPEC-21/22 / eligibility-assistant-D-64 — everything the binding sends
    that is NOT retrieved row content fits `policy_index.PROMPT_RESERVE_BYTES`,
    measured exactly as `llm_client.max_input_tokens` measures it, at a
    full-cap retrieval and the longest legal closed values. A full-cap turn
    therefore stays under LLM_MAX_INPUT_TOKENS and a legal turn can never
    `spend_stop` at model₂ on size."""
    assert_pinned()
    # The fullest legal turn: a topic whose bucket exceeds the cap (truncated to
    # A1_RETRIEVAL_MAX_ROWS) and the longest intent value.
    case = "EVAL-016"  # emergency-care-boundary: 6 rows -> truncated to the cap
    scripted = install_model(
        monkeypatch,
        tool_use_body("policy_lookup", {"topic": topic(case)}),
        _decision(retrieved_ids(case)[:1], ["retry_shortly", "proceed_per_policy", "escalate"]),
    )
    install_payer(monkeypatch, verdict("unknown", payer="Medicare"))

    rows, _record = policy_index.lookup(
        topic(case), "medicare", "unconfirmed", "unconfirmed"
    )
    assert len(rows) == settings.a1_retrieval_max_rows, "not a full-cap retrieval"

    response = post(
        turn(
            case,
            message="coverage changed — check again",  # recheck: the longest intent
            facts={"insurance_id": MEMBER_ID, "last_eligibility": verdict("unknown")},
        )
    )
    assert response.status_code == 200
    assert len(scripted.calls) == 2

    # Model₂'s input carries the whole conversation, so it is the larger of the
    # two; measure it the way the budget gate does and subtract exactly what
    # MAX_ROW_BYTES counts — the UTF-8 bytes of every field value each retrieved
    # row carries. What is left is the turn's own messages: system prompt, tool
    # schema, model₁'s user message, the tool_use turn, the tool_result envelope,
    # model₂'s injected message, and the per-row serialisation overhead.
    call = scripted.calls[1]
    measured = app_mod.llm_client.max_input_tokens(
        call["messages"], system=call.get("system"), extra_body=call.get("extra_body")
    )
    row_content = sum(row.byte_total() for row in rows)
    reserve_used = measured - row_content
    assert reserve_used <= policy_index.PROMPT_RESERVE_BYTES, (
        f"the turn's own messages use {reserve_used} B of the "
        f"{policy_index.PROMPT_RESERVE_BYTES} B reserve"
    )
    # And the whole thing fits the request cap with the full-cap retrieval on
    # board — the D-64 arithmetic, measured rather than restated.
    assert measured <= settings.llm_max_input_tokens
