"""
outcome — the turn's closed report vocabulary and the deterministic reason table.

Three closed sets, none of them model-authored:

  * ``Outcome`` — what the turn CONCLUDED, ten values, the Appendix enum
    (eligibility-assistant-D-15). An outcome is not an action: the action ids
    (REQ-4′) are what the reply does about the outcome, and they live in
    ``visit_templates.CATALOG``.
  * ``Reason`` — why a turn was deterministic, six values
    (eligibility-assistant-D-19). Carries a value on every deterministic turn and
    every fallback; on a completed agent path it is `null` in the response (the
    field is always present — SPEC-4's shape does not change per turn) and OMITTED
    from the log line, which grows by allowlist and never None-fills.
  * ``Mode`` — which path produced the reply, six values
    (eligibility-assistant-D-33). Distinct from health (``assistant``) and from
    spend (``llm_egress``): three fields, three predicates, no two derivable from
    each other (eligibility-assistant-D-71).

The reason table maps a reason to the citations the reply carries. The ids are
fixed per reason and are never chosen — not by the model and not by this turn —
which is what makes a deterministic turn's citation set assertable the same way
an agent-path turn's is (Appendix, "Source kinds in `expected_source_ids`").
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
    """Render index rows as the four-field citation both paths carry (SPEC-4).

    One renderer for both paths, so an agent-path citation and a deterministic
    turn's are the same object built the same way — the reason the Appendix can
    assert `expected_source_ids` identically on either.
    """
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

    ``fetch_by_id`` returns its ``(rows, record)`` two-tuple (eligibility-assistant-
    D-58); the record is discarded here — `retrieval-eval`'s structured log line is
    its emitter, not this module. Going through the index rather than holding a
    second copy of title/section/version is what keeps SPEC-6's "through the index"
    true on the deterministic path (eligibility-assistant-D-61).
    """
    rows, _record = policy_index.fetch_by_id(reason_citation_ids(reason, question_type))
    return render_citations(rows)


class Mode(str, Enum):
    """Which path produced the reply (eligibility-assistant-D-33), six values.

    Not health and not spend. ``assistant`` says whether an ``LLMError`` escaped the
    agent step, ``llm_egress`` says whether a payload crossed the vendor boundary,
    and this says which path ran — three predicates that genuinely disagree in real
    cases (a rejected model selection is `fallback` / `ok` / `True`; a `spend_stop`
    at model₁ is `fallback` / `degraded` / `False`), so collapsing any two of them
    makes a real state unrepresentable (eligibility-assistant-D-71).
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

    Never a denial from anything but a payer result: an absent verdict is
    ``unknown``; a DEGRADED verdict — one ``eligibility_client`` built without
    reaching the payer, recognisable because it carries no payer name — is
    ``unavailable``, the outage outcome SPEC-53 routes to a person, and so is a
    ``pending`` one (a check that has not completed is not an answer a clerk can
    act on either — eligibility-assistant-D-38's payer-derived table). Only a
    real ``inactive`` from the payer renders as ``inactive``.
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

# The applicability tier bound: a definitive documentary basis is a row of tier
# 1–3 (regulation, current official source, citation-only payer record); tiers
# 4–5 are the clinic's own synthetic material (eligibility-assistant-D-38).
_APPLICABLE_TIER = 3


def applicability_mismatch(rows, *, product: str, state: str) -> bool:
    """The in-code applicability check (SPEC-42 / eligibility-assistant-D-32/D-38).

    True when the retrieved set cannot support a definitive answer: nothing was
    retrieved, no retrieved row is of tier ≤ 3, or the turn's product/state is
    `unconfirmed` and every retrieved row needs product confirmation (EVAL-023's
    citation-only payer pages).

    All three are read off the rows the retriever RETURNED, which is what
    eligibility-assistant-D-32 buys: `unconfirmed` does not filter the index on its
    axis, so an empty result reports that the corpus holds nothing for this turn
    rather than that a filter removed it. That is what makes `not rows` a
    meaningful mismatch here — D-32 forbids inferring mismatch from a
    filter-induced absence, not from an honest one.
    """
    if not rows:
        return True
    if not any(policy_index.tier(row.id) <= _APPLICABLE_TIER for row in rows):
        return True
    if product == "unconfirmed" or state == "unconfirmed":
        entries = policy_index._current().entries
        if all(entries[row.id].needs_product_confirmation for row in rows):
            return True
    return False


# The outcomes that may render an EMPTY citation list (SPEC-4 / REQ-2′, the client
# amendment 1 rule "Required citation on every non-refusal"). Every other outcome is
# an answer, and an answer with no source is the shape the requirement forbids —
# `_validated_selection` floors it at one of the turn's own retrieved rows.
NO_CITATION_OUTCOMES = (
    Outcome.refuse,
    Outcome.refuse_definitive,
    Outcome.stop,
    Outcome.care_first,
)


def model_reachable_outcomes(verdict, rows, *, product: str, state: str) -> tuple:
    """Every outcome ``agent_outcome`` can still conclude for this turn.

    The same precedence read from BEFORE model₂ chooses, which is when the injected
    message has to name the vocabulary it may choose from. Arm 1 is code-keyed and
    absolute — a verdict-less turn whose retrieved set cannot support a definitive
    answer refuses whatever the model selects — so that shape reaches model₂ as a
    single outcome. Otherwise the model's own bounded choice keys `conflict` or
    `reverify`, and anything else falls to the payer-derived outcome.

    This is the one derivation `_build_model2_message` advertises from, so the ids
    model₂ is shown and the ids `_validated_selection` accepts cannot drift apart
    (adv review round 2 f1). Held equal by
    ``tests/test_a1_agent_turn.py::test_model2_message_advertises_the_vocabulary_the_validator_accepts``.
    """
    if verdict is None and applicability_mismatch(rows, product=product, state=state):
        return (Outcome.refuse_definitive,)
    return (Outcome.conflict, Outcome.reverify, payer_outcome(verdict))


def agent_outcome(decision, rows, verdict, *, product: str, state: str):
    """What an agent-path turn concluded (eligibility-assistant-D-38), or None
    when the selection is invalid for the outcome it keys (a `state_conflict`
    with nothing to conflict — the caller takes `validation_reject`).

    Precedence, reconciled against the contract Appendix (the frozen harness
    outcomes outrank eligibility-assistant-D-38's summary where they disagree —
    recorded as a `turn` Delivery deviation):

      1. the applicability check — fired only when the turn obtained NO payer
         verdict, because a coverage answer the payer gave is not withdrawn over
         document tiers (EVAL-002 `inactive` and EVAL-004 `reverify` retrieve
         tier-4-only sets and keep their outcomes; EVAL-006/013/023 are
         verdict-less turns and refuse) → ``refuse_definitive``;
      2. model₂ selected `state_conflict` → ``conflict``, valid only when it
         cites at least two sources — or the turn's WHOLE retrieved set when
         fewer than two rows were retrieved (EVAL-007's conflict is against a
         source outside the corpus; one row is all there is to cite) — else the
         caller rejects the selection;
      3. model₂ selected `reverify` / `note_disputed` → ``reverify`` (a payer
         `inactive` beside a disputed card is EVAL-025's reverify, so this
         outranks the payer);
      4. otherwise the payer-derived outcome.

    Detection (which ids the model chose) is the model's bounded freedom; every
    consequence here is code, and nothing below ever authors a verdict.
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

    ``spend_stop`` is the one reason that overrides the payer: the verdict is
    persisted in facts and deliberately NOT rendered (eligibility-assistant-D-26), so
    the turn concludes ``stop`` whatever the payer said. Every other reason falls
    through to the payer result if one was obtained, else ``unknown``.
    """
    if Reason(reason) is Reason.spend_stop:
        return Outcome.stop
    return payer_outcome(verdict)


def mode_of(gate_mode, reason, *, fixture: bool) -> "Mode":
    """The turn's mode, in eligibility-assistant-D-71's precedence.

    The gate's own value first (`care_first` / `refuse` / `no_lookup`), then
    `fallback` when the agent step ended on a eligibility-assistant-D-19 reason, then
    `real` / `fixture` from configuration — so `real` / `fixture` is the value the
    field takes exactly when no path name applies, and is never a second axis stacked
    on the other four.
    """
    if gate_mode is not None:
        return Mode(gate_mode)
    if reason is not None:
        return Mode.fallback
    return Mode.fixture if fixture else Mode.real
