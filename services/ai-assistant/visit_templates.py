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

# Pseudo-status used before any lookup has run. Every other value comes from the
# ADR 0010 contract (`active` / `inactive` / `unknown` / `pending`).
AWAITING_ID = "awaiting_id"

# Canonical order: selections render in this order regardless of the order the
# model returns them, so replies always read identify -> retry -> money -> record.
CATALOG: dict[str, str] = {
    "ask_member_id": (
        "Ask the patient for the member ID printed on their insurance card, then "
        "send it here to run the check."
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
}

# Neutral extras: justified whatever the status, so they are the only ids the
# model may add beyond the required selection. Everything else in the catalog is
# status-conditional and belongs to specific statuses via default_selection.
OPTIONAL_IDS = ("collect_secondary", "note_coverage_result")

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
}


def verdict_line(verdict: dict[str, Any] | None) -> str:
    """The authoritative coverage sentence for a structured eligibility result.

    Keyed on `status` alone. `active` is deliberately NOT consulted here: it is a
    tri-state where None is falsy but is not False, and a truthiness test on it is
    exactly the defect PR #11 fixed twice (an outage rendering as "inactive").
    An unrecognised status degrades to the `unknown` wording — the safe direction.

    A stored verdict is always stamped with when it was observed, so a reply that
    reuses `last_eligibility` from earlier in the visit reads as a past
    observation rather than a fresh claim (ADR 0011 §5).
    """
    if not verdict:
        return _VERDICT_LINES[AWAITING_ID]
    status = verdict.get("status") or "unknown"
    line = _VERDICT_LINES.get(status, _VERDICT_LINES["unknown"])
    payer = verdict.get("payer")
    line = line.format(payer=f" with {payer}" if payer else "")
    checked_at = verdict.get("checked_at")
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
    """
    return set(default_selection(status)) | set(OPTIONAL_IDS)
