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
