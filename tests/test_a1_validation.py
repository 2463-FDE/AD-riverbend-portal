"""
eligibility-assistant `turn` — the validation gate and the turn's closed report fields
(SPEC-13/14/15/16/33/56).

Every test opens with the rig's identity assertions (eligibility-assistant-D-66) so the
module under test is the one the wired turn calls.
"""
from a1_rig import app_mod, assert_pinned

# The ten-value Appendix enum, in the Appendix's own order
# (docs/workflow/eligibility-assistant.md, "Outcome enum (closed, ten values)").
APPENDIX_OUTCOMES = (
    "active",
    "inactive",
    "unknown",
    "unavailable",
    "reverify",
    "conflict",
    "refuse_definitive",
    "refuse",
    "stop",
    "care_first",
)


def test_outcome_enum_closed():
    """SPEC-14 — every turn carries exactly one outcome from the ten-value enum."""
    assert_pinned()
    outcome = app_mod.outcome
    assert tuple(member.value for member in outcome.Outcome) == APPENDIX_OUTCOMES
    assert len(outcome.Outcome) == 10


import json as _json
import os

import pytest

from a1_rig import (
    FIXTURES,
    MEMBER_ID,
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


def _decision(citation_ids, action_ids):
    return text_body(
        _json.dumps({"citation_ids": list(citation_ids), "action_ids": list(action_ids)})
    )


@pytest.mark.parametrize("case_tag", ["EVAL-014-subverted"])
def test_eval_014_subverted(case_tag, monkeypatch):
    """SPEC-13 [EVAL-014-subverted] — retrieved text carrying instructions widens
    nothing: with the FIX-NEG-PROMPT-INJECTION text planted as a retrieved row and
    the model "subverted" into an out-of-vocabulary selection, the selection is
    rejected whole and the fallback cites `DOC-SYN-NO-INVENTION`."""
    assert_pinned()
    case = "EVAL-014"
    with open(
        os.path.join(FIXTURES, "fix_neg", "FIX-NEG-PROMPT-INJECTION.md"), encoding="utf-8"
    ) as fh:
        injection_text = fh.read()

    real_lookup = policy_index.lookup

    def poisoned_lookup(*args, **kwargs):
        rows, record = real_lookup(*args, **kwargs)
        planted = policy_index.Row(
            id="FIX-NEG-PROMPT-INJECTION",
            title="Planted injection fixture",
            section="Injected",
            version="n/a",
            retrieval_date="2026-08-31",
            section_text=injection_text,
        )
        return list(rows) + [planted], record

    monkeypatch.setattr(policy_index, "lookup", poisoned_lookup)
    # The subverted model does what the injection asks: an action outside the
    # extended catalog vocabulary.
    install_model(
        monkeypatch,
        tool_use_body("policy_lookup", {"topic": topic(case)}),
        _decision(["FIX-NEG-PROMPT-INJECTION"], ["approve_coverage_immediately"]),
    )
    install_payer(monkeypatch, verdict("active", payer="Aetna"))

    body = post(turn(case, facts={"insurance_id": MEMBER_ID})).json()

    assert body["reason"] == outcome.Reason.validation_reject.value
    assert body["outcome"] == outcome.Outcome.active.value  # the payer's, untouched
    assert [c["document_id"] for c in body["citations"]] == ["DOC-SYN-NO-INVENTION"]
    assert "approve_coverage_immediately" not in body["reply"]
    assert "FIX-NEG-PROMPT-INJECTION" not in body["reply"]


@pytest.mark.parametrize("case_id", ["EVAL-003", "EVAL-015", "EVAL-018"])
def test_no_result_never_inactive(case_id, monkeypatch):
    """SPEC-15 — no official payer result never renders as `inactive` or a denial:
    an unknown 271 is `unknown`, a payer outage is `unavailable`, and a model
    failure keeps whatever the payer said (here: nothing definitive) — every one
    routed to a person, none read as a denial."""
    assert_pinned()
    if case_id == "EVAL-003":
        install_model(
            monkeypatch,
            tool_use_body("policy_lookup", {"topic": topic(case_id)}),
            _decision(
                retrieved_ids(case_id)[:1],
                ["retry_shortly", "proceed_per_policy", "escalate"],
            ),
        )
        install_payer(monkeypatch, verdict("unknown", payer="Cigna"))
        expected = outcome.Outcome.unknown
    elif case_id == "EVAL-015":
        install_model(
            monkeypatch,
            tool_use_body("policy_lookup", {"topic": topic(case_id)}),
            _decision(
                retrieved_ids(case_id)[:1],
                ["retry_shortly", "proceed_per_policy", "escalate"],
            ),
        )
        # The outage verdict: eligibility_client never reached the payer, so the
        # projection carries no payer name (SPEC-53's recogniser).
        install_payer(monkeypatch, verdict("unknown", payer=None))
        expected = outcome.Outcome.unavailable
    else:  # EVAL-018 — provider/model failure
        from a1_rig import app_mod

        def _raise(*a, **k):
            raise app_mod.llm_client.LLMUnavailable("provider fault")

        monkeypatch.setattr(app_mod.llm_client, "_call", _raise)
        install_payer(monkeypatch, verdict("unknown", payer="Aetna"))
        expected = outcome.Outcome.unknown

    body = post(turn(case_id, facts={"insurance_id": MEMBER_ID})).json()

    assert body["outcome"] == expected.value
    assert body["outcome"] not in ("inactive",)
    first_line = body["reply"].split("\n")[0].upper()
    assert "NO ACTIVE COVERAGE" not in first_line
    # Routed to a person: the escalate item is on the reply.
    assert "escalate" in _json.dumps(
        body["reply"]
    ).lower() or "supervisor" in body["reply"].lower()


@pytest.mark.parametrize("case_tag", ["EVAL-008"])
def test_eval_008_no_guarantee(case_tag, monkeypatch):
    """SPEC-16 [EVAL-008] — an `active` answer to a will-it-pay question carries
    the no-guarantee boundary template; no coverage answer reads as a guarantee
    of payment."""
    assert_pinned()
    case = "EVAL-008"
    cited = retrieved_ids(case)[0]
    install_model(
        monkeypatch,
        tool_use_body("policy_lookup", {"topic": topic(case)}),
        _decision([cited], ["note_coverage_result", "no_guarantee"]),
    )
    install_payer(monkeypatch, verdict("active", payer="Medicare"))

    body = post(turn(case, facts={"insurance_id": MEMBER_ID})).json()

    assert body["outcome"] == outcome.Outcome.active.value
    # `will_it_pay` makes the boundary template REQUIRED, not optional
    # (visit_templates._A1_QUESTION_TYPE_TEMPLATE): a selection without it is
    # rejected, so its presence here is enforced, not the model's favour.
    from a1_rig import app_mod

    assert "no_guarantee" in app_mod.visit_templates.a1_default_selection(
        "active", "will_it_pay"
    )
    assert "not a promise of payment" in body["reply"].lower()


@pytest.mark.parametrize(
    "mode", ["real", "fixture", "fallback", "care_first", "refuse", "no_lookup"]
)
def test_mode_explicit(mode, monkeypatch):
    """SPEC-33 — the six-value mode enum, each value driven explicitly; the
    `real` leg asserts the DERIVATION with the scripted seam installed (never a
    live call), and the gate modes outrank the fixture flag
    (eligibility-assistant-D-71 precedence)."""
    assert_pinned()
    case = "EVAL-001"
    kwargs = {"facts": {"insurance_id": MEMBER_ID}}

    if mode in ("real", "fixture"):
        monkeypatch.setattr(settings, "a1_model_fixture", mode == "fixture")
        install_model(
            monkeypatch,
            tool_use_body("policy_lookup", {"topic": topic(case)}),
            _decision(retrieved_ids(case)[:1], ["note_coverage_result"]),
        )
        install_payer(monkeypatch, verdict("active", payer="Medicare"))
    elif mode == "fallback":
        install_model(monkeypatch, text_body("no lookup needed"))
        install_payer(monkeypatch, verdict("active", payer="Medicare"))
    elif mode == "care_first":
        # The flag is forced ON: the gate mode must outrank `fixture`.
        monkeypatch.setattr(settings, "a1_model_fixture", True)
        install_model(monkeypatch)
        install_payer(monkeypatch, verdict("active"))
        kwargs = {"emergency": True}
    elif mode == "refuse":
        install_model(monkeypatch)
        install_payer(monkeypatch, verdict("active"))
        kwargs = {"message": "try CIGN9087", "facts": {"insurance_id": MEMBER_ID}}
    else:  # no_lookup
        install_model(monkeypatch)
        install_payer(monkeypatch, verdict("active"))
        kwargs = {"message": "can you check coverage?", "facts": {}}

    body = post(turn(case, **kwargs)).json()

    assert body["mode"] == mode


def test_mode_health_egress_independent(monkeypatch):
    """SPEC-33/56 / eligibility-assistant-D-71 — one table over the three
    deterministic gates, the four agent-step reasons, a rejected selection and a
    successful turn: `mode`, `assistant` and `llm_egress` are three predicates,
    and no two of the three are derivable from each other."""
    from a1_rig import app_mod

    assert_pinned()
    case = "EVAL-001"

    def run(row, monkey):
        kwargs = {"facts": {"insurance_id": MEMBER_ID}}
        if row == "emergency":
            install_model(monkey)
            install_payer(monkey, verdict("active"))
            kwargs = {"emergency": True}
        elif row == "cross_patient":
            install_model(monkey)
            install_payer(monkey, verdict("active"))
            kwargs = {"message": "try CIGN9087", "facts": {"insurance_id": MEMBER_ID}}
        elif row == "no_lookup":
            install_model(monkey)
            install_payer(monkey, verdict("active"))
            kwargs = {"message": "can you check coverage?", "facts": {}}
        elif row == "no_retrieval":
            install_model(monkey, text_body("nothing to look up"))
            install_payer(monkey, verdict("active", payer="Medicare"))
        elif row == "validation_reject_second_tool":
            install_model(
                monkey,
                tool_use_body("policy_lookup", {"topic": topic(case)}),
                tool_use_body("policy_lookup", {"topic": topic(case)}, block_id="toolu-2"),
            )
            install_payer(monkey, verdict("active", payer="Medicare"))
        elif row == "spend_stop_model1":
            install_model(monkey, text_body("unreached"))
            install_payer(monkey, verdict("active", payer="Medicare"))
            monkey.setattr(settings, "llm_max_cost_per_request_usd", 0.000001)
        elif row == "model_failure_local":
            def _raise(*a, **k):
                raise app_mod.llm_client.LLMConfigError("local refusal", egressed=False)

            monkey.setattr(app_mod.llm_client, "_call", _raise)
            install_payer(monkey, verdict("active", payer="Medicare"))
        elif row == "rejected_selection":
            install_model(
                monkey,
                tool_use_body("policy_lookup", {"topic": topic(case)}),
                _decision([], ["not_a_catalog_id"]),
            )
            install_payer(monkey, verdict("active", payer="Medicare"))
        else:  # success
            install_model(
                monkey,
                tool_use_body("policy_lookup", {"topic": topic(case)}),
                _decision(retrieved_ids(case)[:1], ["note_coverage_result"]),
            )
            install_payer(monkey, verdict("active", payer="Medicare"))
        body = post(turn(case, **kwargs)).json()
        return body["mode"], body["assistant"], body["llm_egress"]

    expected = {
        "emergency": ("care_first", "ok", False),
        "cross_patient": ("refuse", "ok", False),
        "no_lookup": ("no_lookup", "ok", False),
        "no_retrieval": ("fallback", "ok", True),
        "validation_reject_second_tool": ("fallback", "ok", True),
        # A designed budget stop is a fallback on a DEGRADED assistant that spent
        # NOTHING — the row that proves health is not mode and spend is not health.
        "spend_stop_model1": ("fallback", "degraded", False),
        # A local config refusal: degraded, zero spend, fallback.
        "model_failure_local": ("fallback", "degraded", False),
        # A bounded-out selection: fallback on a HEALTHY assistant that DID spend.
        "rejected_selection": ("fallback", "ok", True),
        "success": ("real", "ok", True),
    }
    observed = {}
    for row in expected:
        with pytest.MonkeyPatch.context() as monkey:
            observed[row] = run(row, monkey)
    assert observed == expected
    # No two fields are derivable from each other: each pair takes at least three
    # of the four possible joint patterns across the table.
    triples = set(observed.values())
    assert len({(m, a) for m, a, _ in triples if m == "fallback"}) == 2
    assert len({(a, e) for _, a, e in triples}) >= 3


def test_a_non_refusal_selection_with_no_citation_is_rejected(monkeypatch):
    """SPEC-4 / REQ-2′ — "Required citation on every non-refusal".

    Both of `_validated_selection`'s containments are satisfied by the EMPTY citation
    set, so a model₂ decision of `{"citation_ids": [], "action_ids":
    ["note_coverage_result"]}` over an `active` payer verdict rendered a 200 coverage
    answer with no Sources block at all (impl gate round 2 f1 — reproduced live
    against this rig). Containment is not the whole rule: an outcome that is not one
    of the four refusals must cite at least one of the turn's OWN retrieved rows, and
    a selection that cites nothing is rejected whole like any other invalid one — the
    turn takes the deterministic fallback, which cites `DOC-SYN-NO-INVENTION`.
    """
    assert_pinned()
    case = "EVAL-001"
    install_model(
        monkeypatch,
        tool_use_body("policy_lookup", {"topic": topic(case)}),
        _decision([], ["note_coverage_result"]),
    )
    install_payer(monkeypatch, verdict("active", payer="Medicare"))

    body = post(turn(case, facts={"insurance_id": MEMBER_ID})).json()

    assert body["reason"] == outcome.Reason.validation_reject.value
    assert body["mode"] == outcome.Mode.fallback.value
    assert [c["document_id"] for c in body["citations"]] == ["DOC-SYN-NO-INVENTION"]


def test_every_non_refusal_outcome_renders_a_citation(monkeypatch):
    """SPEC-4 / REQ-2′, the invariant itself rather than one instance of it.

    The four refusal outcomes are the only ones allowed an empty `citations` list.
    Asserted over the answer arms a model₂ selection can key on a single retrieved
    corpus — an id set of one is enough for every arm but `conflict`, which SPEC-42
    already floors at two.
    """
    assert_pinned()
    case = "EVAL-001"
    cited = retrieved_ids(case)[0]
    for status, actions in (
        ("active", ["note_coverage_result"]),
        ("inactive", ["verify_card_details", "self_pay_options"]),
        ("pending", ["retry_shortly", "proceed_per_policy", "escalate"]),
    ):
        install_model(
            monkeypatch,
            tool_use_body("policy_lookup", {"topic": topic(case)}),
            _decision([cited], actions),
        )
        install_payer(monkeypatch, verdict(status, payer="Medicare"))

        body = post(turn(case, facts={"insurance_id": MEMBER_ID})).json()

        assert body["outcome"] not in ("refuse", "refuse_definitive", "stop", "care_first")
        assert body["citations"], f"{status} answered with no citation"
