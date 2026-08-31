"""Staff-facing visit-chat reply catalog (closed-vocabulary OUTPUT).

The exact mirror of templates.py, applied to the eligibility chat (ADR 0011 §2):
the model never writes text a human reads. It selects template IDS from the closed
catalog below, the server renders the fixed strings, and an unknown id simply
cannot render. There is no free-text path from the model to a clerk.

Two layers, deliberately separate:

  * ``verdict_line`` — the authoritative coverage sentence. Built HERE, in
    deterministic code, from the structured eligibility result. The model is not
    consulted and cannot influence it. This is the ADR 0011 §5 rule: a coverage
    verdict is a financial and access-to-care fact, so the model must not be the
    thing that asserts it.
  * ``CATALOG`` — the follow-up actions that accompany a verdict. This is the only
    part the model has any say over, and only by id, and only within the set the
    server already decided is justified by the status.

The only values interpolated into a rendered reply are the payer NAME (from
eligibility-service's own configuration) and a `checked_at` timestamp. Neither is
PHI, neither is model-authored, and no other downstream field is ever formatted
into text — notably not `insurance_id` and not the degraded `error` string.

Every string here is reviewable policy copy, linted by the clinical-vocabulary
screen in tests/test_ai_intake_instructions.py so a future edit cannot smuggle
clinical guidance into administrative copy. Growing the feature means adding a key
+ string here and nothing else changes about what can leak.
"""
from typing import Any, Iterable

# Pseudo-statuses used when no lookup has run. Every other value comes from the
# ADR 0010 contract (`active` / `inactive` / `unknown` / `pending`).
AWAITING_ID = "awaiting_id"
# More than one member id in the turn, or one that contradicts the id already
# confirmed for this visit. Distinct from AWAITING_ID because the reply has to
# say WHY nothing ran — and distinct from any real status because rendering the
# previous verdict here would answer a question about a different subject.
AMBIGUOUS_ID = "ambiguous_id"

# Canonical order: selections render in this order regardless of the order the
# model returns them, so replies always read identify -> retry -> money -> record.
CATALOG: dict[str, str] = {
    "ask_member_id": (
        "Ask the patient for the member ID printed on their insurance card, then "
        "send it here to run the check."
    ),
    "confirm_which_member_id": (
        "Confirm which member ID belongs to this patient's coverage before "
        "running the check — more than one ID is in play, and checking the wrong "
        "one returns a coverage answer about somebody else."
    ),
    "verify_card_details": (
        "Compare the ID entered against the card — a mistyped character is the "
        "most common reason a lookup comes back with no match."
    ),
    "retry_shortly": (
        "Try the check again in a few minutes; the payer connection is degraded "
        "right now, not the patient's coverage."
    ),
    "proceed_per_policy": (
        "Follow the clinic's policy for unconfirmed coverage. Do not tell the "
        "patient they are uninsured on the strength of a failed check."
    ),
    "self_pay_options": (
        "Let the patient know about self-pay rates and payment plans, and offer "
        "the financial counselling handout."
    ),
    "collect_secondary": (
        "Ask whether the patient has secondary coverage that is not on file yet."
    ),
    "note_coverage_result": (
        "Record the coverage result in the visit notes so billing does not have "
        "to repeat the check."
    ),
    # eligibility-assistant (REQ-4′ / eligibility-assistant-D-15): the seven action
    # ids the closed catalog is EXTENDED by, plus the four boundary templates the
    # Appendix's qualified outcomes require. Same contract as every id above — the
    # model selects by id, the server renders the fixed string, and an id outside
    # this dict cannot render.
    "care_first": (
        "Send the patient to be seen now. Do not delay or redirect them over an "
        "insurance question — screening comes first, and the coverage question is "
        "settled afterwards."
    ),
    "refuse": (
        "Do not answer this coverage question here. Nothing about it has been "
        "established, and answering anyway would put a made-up answer in front of "
        "the patient."
    ),
    "escalate": (
        "Hand this to a person: a supervisor, or the payer's own verification line. "
        "It needs a decision the front desk cannot make from what is on file."
    ),
    "state_conflict": (
        "Tell the patient plainly that the approved sources disagree on this point, "
        "and that the answer is being confirmed rather than guessed at. Do not pick "
        "one source over the other at the desk."
    ),
    "reverify": (
        "Run the check again against the payer before the visit is closed out — the "
        "answer on file is not the one to bill against."
    ),
    "note_disputed": (
        "Record that the patient disputes what the payer returned, with what they "
        "said, so the follow-up starts from their account and not from the file."
    ),
    "stop": (
        "The assistant stopped short of a full answer for this turn because it hit "
        "its own spending limit. Nothing about the patient's coverage changed; run "
        "the check again or ask a supervisor."
    ),
    "no_guarantee": (
        "Say that active coverage is not a promise of payment: what the plan pays "
        "for this visit is settled when the claim is processed, not now."
    ),
    "auth_unknown": (
        "Note that coverage being active answers a different question from whether "
        "prior approval is needed. That approval has not been checked here."
    ),
    "network_unknown": (
        "Note that whether this clinic is in the patient's network has not been "
        "confirmed — active coverage does not settle it."
    ),
    "referral_required": (
        "Check whether the plan wants a referral on file before the visit, and get "
        "one started if it does."
    ),
}

# Neutral extras: the only ids the model may add beyond the required selection.
# Everything else in the catalog is status-conditional and belongs to specific
# statuses via default_selection.
#
# They are neutral only once a check has actually RUN: "record the coverage
# result" and "ask about secondary coverage" both presuppose a result to record
# (adversarial review). For the two pseudo-statuses no lookup has happened, so
# the model gets no optional ids at all there — see allowed_selection.
OPTIONAL_IDS = ("collect_secondary", "note_coverage_result")
NO_LOOKUP_STATUSES = (AWAITING_ID, AMBIGUOUS_ID)

# A rendered reply carries the verdict line plus this many catalog items. The
# floor is 1 (a verdict alone is a dead end for the clerk); the ceiling keeps a
# reply scannable at a busy front desk.
MIN_ITEMS = 1
MAX_ITEMS = 4

_VERDICT_LINES: dict[str, str] = {
    "active": "Coverage is ACTIVE{payer}.",
    "inactive": "The payer reports NO ACTIVE COVERAGE for this member ID{payer}.",
    # Never a denial — see the module docstring and ADR 0011 §5.
    "unknown": (
        "Coverage could NOT be confirmed{payer}. This is a failed check, not a "
        "denial — the patient's coverage may well be active."
    ),
    "pending": (
        "Verification is still PENDING{payer}. This is not a denial — the check "
        "has not completed yet."
    ),
    AWAITING_ID: "No member ID has been provided yet, so no coverage check has run.",
    AMBIGUOUS_ID: (
        "More than one possible member ID is in play, so NO check has run — "
        "this is not a coverage result of any kind."
    ),
    # eligibility-assistant: the six OUTCOME-keyed lines. `verdict_line` is keyed on
    # whatever the caller calls the turn's status, and on these turns that is the
    # outcome, because no payer status describes them. None carries a `{payer}`
    # placeholder and every one is rendered with `verdict=None`, so no payer name and
    # no timestamp can attach to a turn that has no result to stamp.
    "unavailable": (
        "The payer could not be reached, so NO coverage answer was obtained. This "
        "is an outage on our side of the check, not a denial."
    ),
    "conflict": (
        "The approved sources DISAGREE on this point, so no definitive coverage "
        "answer is being given. Both sources are cited below."
    ),
    "refuse_definitive": (
        "There is not enough in the approved sources to answer this definitively, "
        "so no coverage answer is being given."
    ),
    "refuse": (
        "This request is NOT being answered here. No check has run and no coverage "
        "answer of any kind is implied."
    ),
    "stop": (
        "The assistant reached its own spending limit for this turn, so it stopped "
        "before completing the answer. This says nothing about the coverage."
    ),
    "care_first": (
        "EMERGENCY: the patient is to be seen now. The coverage question does not "
        "gate that and is settled afterwards."
    ),
}

# The six outcome-keyed lines above (eligibility-assistant-D-15 / D-19). Separate
# from NO_LOOKUP_STATUSES on purpose: that tuple decides what `app.py` reports as the
# turn's verdict and is pinned by retained tests, so widening it would move behaviour
# these turns do not touch.
A1_OUTCOME_STATUSES = (
    "unavailable",
    "conflict",
    "refuse_definitive",
    "refuse",
    "stop",
    "care_first",
)


def verdict_line(status: str, verdict: dict[str, Any] | None = None) -> str:
    """The authoritative coverage sentence for a turn.

    ``status`` is the CALLER's status for this turn and is authoritative; the
    verdict dict only supplies decoration (payer, checked_at). That split matters:
    on an ambiguous-id turn the stored `last_eligibility` describes a DIFFERENT
    subject, and keying the sentence off the dict's own status would restate
    "Coverage is ACTIVE" in answer to a question about another member id. Caught
    by test_an_id_that_contradicts_the_visits_confirmed_id_is_refused.

    `active` is deliberately NOT consulted: it is a tri-state where None is falsy
    but is not False, and a truthiness test on it is exactly the defect PR #11
    fixed twice (an outage rendering as "inactive"). An unrecognised status
    degrades to the `unknown` wording — the safe direction.

    A verdict is always stamped with when it was observed, so a reply that reuses
    `last_eligibility` from earlier in the visit reads as a past observation
    rather than a fresh claim (ADR 0011 §5).

    The stamp falls back to `observed_at` when `checked_at` is missing (adversarial
    review, round 4). `checked_at` on a definitive verdict is DOWNSTREAM content —
    `eligibility_client._query` accepts any shaped 2xx, so a body from a shim, an
    intermediary, or a mid-rolling-deploy eligibility-service can carry a verdict
    with no timestamp at all. That used to drop the parenthetical entirely, and a
    reused five-minute-old verdict then read as an unqualified present-tense
    coverage assertion — the exact promise this docstring makes, broken on the path
    the reuse window makes common. `observed_at` is stamped by this service on every
    verdict it produces, so "no stamp renderable" now means the dict did not come
    from us at all.
    """
    line = _VERDICT_LINES.get(status, _VERDICT_LINES["unknown"])
    if status in NO_LOOKUP_STATUSES:
        # No check ran this turn, so no payer or timestamp may be attached — both
        # would imply a result exists.
        return line
    verdict = verdict or {}
    payer = verdict.get("payer")
    line = line.format(payer=f" with {payer}" if payer else "")
    checked_at = verdict.get("checked_at") or verdict.get("observed_at")
    if checked_at:
        line = f"{line} (checked {checked_at})"
    return line


def render(ids: Iterable[str]) -> list[str]:
    """Fixed strings for a selection — deduplicated, in canonical order.

    Callers must validate ids against CATALOG first; an unknown id is the caller's
    fallback signal, not something to silently drop here.
    """
    chosen = set(ids)
    return [text for key, text in CATALOG.items() if key in chosen]


def default_selection(status: str) -> list[str]:
    """Deterministic follow-up ids for a coverage status.

    BOTH the fallback when the model's selection is invalid AND the required core
    of any valid selection (see allowed_selection): every id here is justified by
    the status, so a model response that omits one — or adds a status-conditional
    id that is not here — is wrong for this situation and gets discarded whole.

    An unrecognised status falls through to the unconfirmed advice, which is the
    safe default: retry and follow policy, never "uninsured".
    """
    if status == AWAITING_ID:
        return ["ask_member_id"]
    if status == AMBIGUOUS_ID:
        return ["confirm_which_member_id"]
    if status == "active":
        return ["note_coverage_result"]
    if status == "inactive":
        return ["verify_card_details", "self_pay_options"]
    return ["retry_shortly", "proceed_per_policy"]


def allowed_selection(status: str) -> set[str]:
    """Every id justified by this status.

    A valid model selection must satisfy
    ``set(default_selection(status)) <= selection <= allowed_selection(status)``.
    Catalog membership alone is not enough: `self_pay_options` is right for a
    definitive `inactive` and wrong — financially and for the patient — after a
    failed check that proves nothing. The model's only real freedom is OPTIONAL_IDS.

    When this set EQUALS the default selection the model has no freedom at all,
    and app.py answers that turn deterministically without calling it — paying a
    vendor request for a decision with one legal outcome is pure waste, and the
    turns with no freedom are the ones a clerk can repeat all day (round 5).
    """
    if status in NO_LOOKUP_STATUSES:
        # No result exists yet, so the "neutral" extras are not justified either.
        return set(default_selection(status))
    return set(default_selection(status)) | set(OPTIONAL_IDS)


# --------------------------------------------------------------------------- #
# eligibility-assistant: selection over the OUTCOME, not the payer status
# --------------------------------------------------------------------------- #
# The required core per outcome (contract Appendix). Same contract as
# `default_selection`: every id here is justified by the outcome, so a model
# selection that omits one is wrong for this situation and is discarded whole.
_A1_REQUIRED: dict = {
    "active": ("note_coverage_result",),
    "inactive": ("verify_card_details", "self_pay_options"),
    # The unconfirmed advice is RETAINED beside the Appendix's `escalate`: "retry and
    # follow policy, never uninsured" is what a failed check has always required of
    # the clerk, and the routing the Appendix adds does not replace it.
    "unknown": ("retry_shortly", "proceed_per_policy", "escalate"),
    "unavailable": ("retry_shortly", "proceed_per_policy", "escalate"),
    "reverify": ("reverify",),
    "conflict": ("state_conflict", "escalate"),
    "refuse_definitive": ("escalate",),
    "refuse": ("refuse",),
    "stop": ("stop",),
    "care_first": ("care_first",),
}

# The boundary template a question type REQUIRES beside an active answer — the
# Appendix's qualified outcomes (`active-with-boundary`, `elig-active-auth-unknown`,
# `active-network-unknown`, `active-referral-missing`, `cob-both-recorded`). Only on
# `active`: a boundary on a refusal would qualify an answer that was not given.
_A1_QUESTION_TYPE_TEMPLATE: dict = {
    "will_it_pay": "no_guarantee",
    "prior_auth": "auth_unknown",
    "in_network": "network_unknown",
    "referral_needed": "referral_required",
    "who_pays_first": "collect_secondary",
}

# Outcomes a deterministic gate concluded. The model is not consulted on these
# turns at all, so its freedom is empty by construction rather than by policy.
_A1_NO_FREEDOM = ("refuse", "care_first", "stop")

# What the model may ADD on a turn that left it freedom. Neutral or
# route-to-a-person ids only — never one that asserts a coverage fact.
_A1_OPTIONAL = (
    "escalate",
    "reverify",
    "note_disputed",
    "confirm_which_member_id",
    "no_guarantee",
    "auth_unknown",
    "network_unknown",
    "referral_required",
)


def a1_default_selection(a1_status: str, question_type: str = "") -> list:
    """The deterministic action ids for an OUTCOME (eligibility-assistant-D-15).

    Keyed on the outcome rather than the payer status because most outcomes have no
    payer status behind them — a refusal, a conflict and a spend stop are all turns
    where no coverage answer exists to select advice for. An unrecognised outcome
    falls through to the unconfirmed advice, the same safe default
    ``default_selection`` takes.
    """
    required = list(_A1_REQUIRED.get(a1_status, ("retry_shortly", "proceed_per_policy")))
    if a1_status == "active":
        extra = _A1_QUESTION_TYPE_TEMPLATE.get(question_type)
        if extra and extra not in required:
            required.append(extra)
    return required


def a1_allowed_selection(a1_status: str, question_type: str = "") -> set:
    """Every action id justified by this outcome.

    A valid model selection must satisfy
    ``set(a1_default_selection(...)) <= selection <= a1_allowed_selection(...)``.
    For the three gate outcomes the two sets are EQUAL, which is what the no-freedom
    short-circuit reads: a model call could change the reply by exactly zero.
    """
    required = set(a1_default_selection(a1_status, question_type))
    if a1_status in _A1_NO_FREEDOM:
        return required
    return required | set(OPTIONAL_IDS) | set(_A1_OPTIONAL)


def a1_verdict_line(status: str, a1_status: str, verdict: dict = None) -> str:
    """The authoritative sentence for an eligibility-assistant turn.

    Keyed on the PAYER STATUS wherever the turn has one, so the sentence a clerk
    reads for an active, inactive, unknown or pending check is the one this service
    has always produced — the ADR 0011 §5 rule and every property `verdict_line`'s
    docstring states carry over unchanged.

    The outcome only takes over when the turn has no payer status to speak from: the
    two gates, the four fallbacks, a conflict, an insufficient-evidence refusal, and
    the `unavailable` outage SPEC-53 names. Those are turns where "coverage is …"
    would be a claim about a check that did not happen.

    One outcome bends the other way: `unavailable` reached through a real payer
    ANSWER (the dict carries a payer name — a `pending` check, concluded
    unavailable by eligibility-assistant-D-38) keeps the payer's own stamped
    sentence, because there IS a past observation to restate and the pending
    wording is the one this service has always produced. The refusal-class
    outcomes (`conflict`, `refuse_definitive`, `refuse`, `stop`, `care_first`)
    never restate a payer line — that would be exactly the definitive answer
    they exist to withhold.
    """
    if (
        a1_status == "unavailable"
        and verdict
        and verdict.get("payer")
        and status in _VERDICT_LINES
    ):
        return verdict_line(status, verdict)
    if a1_status in A1_OUTCOME_STATUSES:
        return _VERDICT_LINES[a1_status]
    return verdict_line(status, verdict)
