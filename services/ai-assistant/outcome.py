"""
outcome — the turn's closed report vocabulary and the deterministic reason table.

Three closed sets, none model-authored: ``Outcome`` (what the turn concluded,
eligibility-assistant-D-15), ``Reason`` (why it was deterministic, D-19) and
``Mode`` (which path ran, D-33). Mode, health (``assistant``) and spend
(``llm_egress``) are three independent predicates (D-71).

The reason table fixes each reason's citation ids, so a deterministic turn's
citation set is assertable the same way an agent-path turn's is (Appendix).
"""
from enum import Enum

import policy_index
import schemas


class Outcome(str, Enum):
    """The Appendix's ten-value closed outcome enum (eligibility-assistant-D-15)."""

    active = "active"
    inactive = "inactive"
    unknown = "unknown"
    unavailable = "unavailable"
    reverify = "reverify"
    conflict = "conflict"
    refuse_definitive = "refuse_definitive"
    refuse = "refuse"
    stop = "stop"
    care_first = "care_first"


class Reason(str, Enum):
    """Why a turn was deterministic (eligibility-assistant-D-19), six values."""

    emergency = "emergency"
    cross_patient = "cross_patient"
    validation_reject = "validation_reject"
    no_retrieval = "no_retrieval"
    spend_stop = "spend_stop"
    model_failure = "model_failure"


# The reason table's fixed citations (contract Appendix). Document IDS only: the
# section label is not stored here — it rides the index row and is fetched with it,
# so this table cannot drift from the manifest (eligibility-assistant-D-61).
REASON_CITATION_IDS: dict = {
    Reason.emergency: ("DOC-FED-EMTALA-CMS", "DOC-SYN-EMERGENCY"),
    Reason.cross_patient: ("DOC-SYN-PRIVACY-FD",),
    Reason.validation_reject: ("DOC-SYN-NO-INVENTION",),
    Reason.no_retrieval: ("DOC-SYN-NO-INVENTION",),
    Reason.spend_stop: ("DOC-SYN-SPEND-STOP",),
    Reason.model_failure: ("DOC-SYN-MODEL-FAILURE",),
}

# The one question type that adds a citation to a reason row: an emergency-typed
# question gets the cheat sheet beside the two EMTALA sources (Appendix, `emergency`).
EMERGENCY_QUESTION_TYPE = "emergency"
_EMERGENCY_EXTRA = "DOC-COVERAGE-QUESTION-CHEAT-SHEET"


def render_citations(rows) -> list:
    """Render index rows as the four-field citation both paths carry (SPEC-4)."""
    return [
        schemas.RenderedCitation(
            title=row.title,
            document_id=row.id,
            section=row.section,
            version=row.version,
        )
        for row in rows
    ]


def reason_citation_ids(reason: "Reason", question_type: str = "") -> tuple:
    """The document ids the reason table fixes for this reason."""
    ids = REASON_CITATION_IDS[Reason(reason)]
    if Reason(reason) is Reason.emergency and question_type == EMERGENCY_QUESTION_TYPE:
        return ids + (_EMERGENCY_EXTRA,)
    return ids


def reason_citations(reason: "Reason", question_type: str = "") -> list:
    """Fetch the reason's fixed citations BY ID through the index and render them.

    Through the index rather than a second copy of title/section/version, so SPEC-6
    holds on the deterministic path too (eligibility-assistant-D-61). The
    ``fetch_by_id`` record is discarded: `retrieval-eval` emits the log line.
    """
    rows, _record = policy_index.fetch_by_id(reason_citation_ids(reason, question_type))
    return render_citations(rows)


class Mode(str, Enum):
    """Which path produced the reply (eligibility-assistant-D-33), six values.

    Not health and not spend: a rejected model selection is `fallback` / `ok` /
    egress True, a `spend_stop` at model₁ is `fallback` / `degraded` / False (D-71).
    """

    real = "real"
    fixture = "fixture"
    fallback = "fallback"
    care_first = "care_first"
    refuse = "refuse"
    no_lookup = "no_lookup"


# The two gate modes a deterministic gate carries in its own right, and the third
# the no-freedom short-circuit carries (eligibility-assistant-D-33/D-71).
GATE_MODE: dict = {
    Reason.emergency: Mode.care_first,
    Reason.cross_patient: Mode.refuse,
}

# What each gate reason concludes. The four agent-step reasons are NOT here: their
# outcome depends on whether the payer answered (SPEC-52), so they go through
# ``fallback_outcome``.
GATE_OUTCOME: dict = {
    Reason.emergency: Outcome.care_first,
    Reason.cross_patient: Outcome.refuse,
}


def payer_outcome(verdict) -> "Outcome":
    """The outcome a payer verdict alone concludes (SPEC-15, eligibility-assistant-D-38).

    Never a denial from anything but a payer result: no verdict is ``unknown``; a
    degraded verdict (no payer name) or a ``pending`` one is ``unavailable``
    (SPEC-53); only a real payer ``inactive`` renders as ``inactive``.
    """
    if not verdict:
        return Outcome.unknown
    status = verdict.get("status")
    if status == "active":
        return Outcome.active
    if status == "inactive":
        return Outcome.inactive
    if verdict.get("payer") is None or status == "pending":
        return Outcome.unavailable
    return Outcome.unknown


# Action ids that KEY an outcome when model₂ selects them (eligibility-assistant-
# D-38): detection is the model's bounded choice, every consequence is code.
_CONFLICT_ACTION = "state_conflict"
_REVERIFY_ACTIONS = ("reverify", "note_disputed")

# Tiers 1–3 are a definitive documentary basis; 4–5 are the clinic's own synthetic
# material (eligibility-assistant-D-38).
_APPLICABLE_TIER = 3


def applicability_mismatch(rows, *, product: str, state: str) -> bool:
    """The in-code applicability check (SPEC-42 / eligibility-assistant-D-32/D-38).

    True when the retrieved set cannot support a definitive answer: nothing
    retrieved, no row of tier ≤ 3, or the turn's product/state is `unconfirmed` and
    every row needs product confirmation. Read off the rows the retriever RETURNED:
    `unconfirmed` does not filter the index, so `not rows` is an honest absence,
    the only kind D-32 lets mismatch be inferred from.
    """
    if not rows:
        return True
    if not any(policy_index.tier(row.id) <= _APPLICABLE_TIER for row in rows):
        return True
    if product == "unconfirmed" or state == "unconfirmed":
        if all(policy_index.needs_product_confirmation(row.id) for row in rows):
            return True
    return False


# The outcomes that may render an EMPTY citation list (SPEC-4 / REQ-2′). Every other
# outcome must cite at least one of the turn's own retrieved rows.
NO_CITATION_OUTCOMES = (
    Outcome.refuse,
    Outcome.refuse_definitive,
    Outcome.stop,
    Outcome.care_first,
)


def model_reachable_outcomes(verdict, rows, *, product: str, state: str) -> tuple:
    """Every outcome ``agent_outcome`` can still conclude for this turn.

    The same precedence, read BEFORE model₂ chooses, so the injected message can
    name its vocabulary. `_build_model2_message` derives from this and
    `_validated_selection` re-derives after the choice; held equal by
    ``tests/test_a1_agent_turn.py::test_model2_message_advertises_the_vocabulary_the_validator_accepts``.
    """
    if verdict is None and applicability_mismatch(rows, product=product, state=state):
        return (Outcome.refuse_definitive,)
    return (Outcome.conflict, Outcome.reverify, payer_outcome(verdict))


def agent_outcome(decision, rows, verdict, *, product: str, state: str):
    """What an agent-path turn concluded (eligibility-assistant-D-38), or None when
    the selection keys an outcome it cannot support (the caller takes
    `validation_reject`).

    Precedence, per the contract Appendix (which outranks D-38's summary — a
    recorded `turn` Delivery deviation):

      1. applicability check, only when NO payer verdict was obtained
         → ``refuse_definitive``;
      2. `state_conflict` selected → ``conflict``, valid only with two or more
         citations (or the whole retrieved set when fewer than two rows exist);
      3. `reverify` / `note_disputed` selected → ``reverify``, outranking the payer;
      4. otherwise the payer-derived outcome.

    Detection is the model's bounded freedom; every consequence is code.
    """
    actions = set(decision.action_ids)
    if verdict is None and applicability_mismatch(rows, product=product, state=state):
        return Outcome.refuse_definitive
    if _CONFLICT_ACTION in actions:
        enough = len(decision.citation_ids) >= 2 or (
            len(rows) < 2 and len(decision.citation_ids) == len(rows)
        )
        if not enough:
            return None
        return Outcome.conflict
    if actions & set(_REVERIFY_ACTIONS):
        return Outcome.reverify
    return payer_outcome(verdict)


def fallback_outcome(reason: "Reason", verdict) -> "Outcome":
    """What a turn concludes when the agent step failed or was bounded out (SPEC-52).

    ``spend_stop`` overrides the payer: the verdict is persisted, not rendered
    (eligibility-assistant-D-26), so the turn concludes ``stop``.
    """
    if Reason(reason) is Reason.spend_stop:
        return Outcome.stop
    return payer_outcome(verdict)


def mode_of(gate_mode, reason, *, fixture: bool) -> "Mode":
    """The turn's mode, in eligibility-assistant-D-71's precedence: the gate's own
    value, else `fallback` on a D-19 reason, else `real` / `fixture` from config."""
    if gate_mode is not None:
        return Mode(gate_mode)
    if reason is not None:
        return Mode.fallback
    return Mode.fixture if fixture else Mode.real
