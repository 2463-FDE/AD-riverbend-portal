"""Patient-facing checklist template catalog (closed-vocabulary OUTPUT).

The model never writes patient-facing text. It selects template IDs from this
closed catalog — the exact mirror of the closed-vocabulary request in
schemas.py, applied to the response side: the wire contract is a list of
catalog keys, and the server renders the fixed strings below. Clinical or
hallucinated model output cannot reach a patient by construction, because an
unknown key simply cannot render; there is no free-text path.

Every string here is reviewable policy copy. tests/test_ai_intake_instructions.py
lints the whole catalog against a clinical-vocabulary screen so a future edit
cannot smuggle clinical guidance into "administrative" copy. Growing the
feature means adding a key + string here (and nothing else changes about what
can leak).
"""
from typing import Iterable

from schemas import InstructionsRequest

# Canonical order: selections render in this order regardless of the order the
# model returns them, so checklists always read documents -> money -> logistics.
CATALOG: dict[str, str] = {
    "photo_id": (
        "Bring a current photo ID, such as a driver's license or passport."
    ),
    "insurance_card": (
        "Bring your insurance card so the front desk can copy it."
    ),
    "policy_holder_info": (
        "Bring the policy holder's full name and date of birth as they appear "
        "on the insurance plan."
    ),
    "self_pay_options": (
        "Ask the front desk about self-pay options and payment plans when you "
        "arrive."
    ),
    "financial_form": (
        "Plan a few extra minutes to review and sign the financial "
        "responsibility form at check-in."
    ),
    "billing_questions": (
        "Write down any billing or scheduling questions you want to ask the "
        "front desk."
    ),
    "reminder_watch": (
        "Watch for an appointment reminder message before your visit."
    ),
    "note_appointment_time": (
        "Write down your appointment date and time, since you opted out of "
        "reminder messages."
    ),
    "save_clinic_number": (
        "Save the clinic's phone number so you can call if you are running "
        "late or need to reschedule."
    ),
    "arrive_early": (
        "Arrive about 15 minutes early so check-in is unhurried."
    ),
}


# Neutral extras: justified for ANY request shape, so they are the only ids
# the model may add beyond the required selection. Everything else in the
# catalog is fact-conditional and belongs to exactly one request shape via
# default_selection.
OPTIONAL_IDS = ("billing_questions", "save_clinic_number")


def render(ids: Iterable[str]) -> list[str]:
    """Fixed strings for a selection — deduplicated, in canonical order.

    Callers must validate ids against CATALOG first; unknown ids are the
    caller's fallback signal, not something to silently drop here.
    """
    chosen = set(ids)
    return [text for key, text in CATALOG.items() if key in chosen]


def default_selection(req: InstructionsRequest) -> list[str]:
    """Deterministic selection from the closed request facts.

    This is BOTH the fallback when the model's selection is invalid AND the
    required core of any valid selection (see allowed_selection): every id
    here is justified by a request fact, so a model response that omits one —
    or adds a fact-conditional id that is not here — is factually wrong for
    this patient and gets discarded. Tests prove every reachable variant
    renders a 3-8 item checklist.
    """
    ids = ["photo_id"]
    if req.has_insurance:
        ids.append("insurance_card")
        if not req.policy_holder_is_self:
            ids.append("policy_holder_info")
    else:
        ids.append("self_pay_options")
    if not req.financial_ack:
        ids.append("financial_form")
    ids.append("reminder_watch" if req.communications_opt_in else "note_appointment_time")
    ids.append("arrive_early")
    return ids


def allowed_selection(req: InstructionsRequest) -> set[str]:
    """Every id justified by these request facts.

    A valid model selection must satisfy
    ``set(default_selection(req)) <= selection <= allowed_selection(req)`` —
    catalog membership alone is not enough, because a catalog id can be
    factually wrong for THIS patient (e.g. self_pay_options for an insured
    one). The model's only real freedom is the neutral OPTIONAL_IDS.
    """
    return set(default_selection(req)) | set(OPTIONAL_IDS)
