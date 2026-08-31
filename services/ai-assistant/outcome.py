"""
outcome — the turn's closed report vocabulary and the deterministic reason table.

Three closed sets, none of them model-authored:

  * ``Outcome`` — what the turn CONCLUDED, ten values, the Appendix enum
    (eligibility-assistant-D-15). An outcome is not an action: the action ids
    (REQ-4′) are what the reply does about the outcome, and they live in
    ``visit_templates.CATALOG``.
  * ``Reason`` — why a turn was deterministic, six values
    (eligibility-assistant-D-19). Present in the response and the trace on every
    deterministic turn and on every fallback, absent otherwise.
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
    """The outcome a payer verdict alone concludes (SPEC-15).

    Never a denial from anything but a payer result: an absent verdict is
    ``unknown``, and a DEGRADED verdict — one ``eligibility_client`` built without
    reaching the payer, recognisable because it carries no payer name — is
    ``unavailable``, the outage outcome SPEC-53 routes to a person. Only a real
    ``inactive`` from the payer renders as ``inactive``.
    """
    if not verdict:
        return Outcome.unknown
    status = verdict.get("status")
    if status == "active":
        return Outcome.active
    if status == "inactive":
        return Outcome.inactive
    if verdict.get("payer") is None:
        return Outcome.unavailable
    return Outcome.unknown


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
