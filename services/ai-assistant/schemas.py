"""Pydantic v2 request/response schemas for ai-assistant.

The intake-instructions request is a CLOSED VOCABULARY on purpose — every field
is an enum or a boolean, and unknown fields are rejected (``extra="forbid"``).
That closure is the PHI control and the prompt-injection control in one place:

  * No free-text field exists, so a client cannot smuggle a name, DOB, SSN, or
    note into the request — nothing PHI-shaped can reach the prompt, the log,
    or the LLM egress, by construction. This is the same boundary lesson as
    intake's ``ConsentKind`` (see docs/phi-logging-policy.md): constrain at the
    edge rather than redact downstream.
  * The prompt is assembled ONLY from these closed values, so there is no
    attacker-controlled text that could carry prompt-injection instructions.

If a future revision adds any free-text field, it must bring the CLAUDE.md §5
adversarial tests (PHI planted in that field, end-to-end log scan) with it.

**That revision has now happened, once, deliberately** (ADR 0011): the visit-chat
request at the bottom of this module carries a free-text `message`, because a chat
box cannot exist without one. The closure invariant is preserved where it actually
matters — the VENDOR boundary — rather than at this service's edge:

  * free text is accepted here, but it never reaches the LLM. Intent is derived
    from it deterministically in ``app.py``, and the prompt is assembled only from
    closed values (an intent enum, a status enum, a turn count, catalog ids). Debt
    D13 (Bedrock on standard terms, no BAA) is still open, so nothing PHI-shaped
    may egress to the vendor.
  * it is never logged. Chat logging goes through ``visit_chat_log_metadata``,
    an allowlist of closed values — the same discipline as ``log_metadata``.
  * the CLAUDE.md §5 adversarial tests that this docstring demanded ship with it:
    tests/test_visit_chat_phi.py plants a member id, a name, and an SSN in the
    free text and asserts none of them reach a log, a prompt, or visit memory.
"""
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from config import settings


class PlanType(str, Enum):
    """Closed set of insurance plan types, mirroring the portal's intake form
    select options (frontend/app/intake/page.tsx)."""

    hmo = "HMO"
    ppo = "PPO"
    epo = "EPO"
    pos = "POS"
    medicare = "Medicare"
    medicaid = "Medicaid"
    self_pay = "Self-pay"


class InstructionsRequest(BaseModel):
    """Facts about a just-submitted intake that shape the prep checklist.

    All administrative, none identifying. ``extra="forbid"`` rejects unknown
    keys at the boundary (422) so PHI in an unexpected field never enters the
    service."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    has_insurance: bool = False
    plan_type: PlanType | None = None
    policy_holder_is_self: bool = True
    communications_opt_in: bool = False
    financial_ack: bool = False

    @model_validator(mode="after")
    def _insurance_facts_consistent(self):
        """``has_insurance`` and ``plan_type`` arrive separately but describe
        one fact. A contradictory pair would render a financially wrong
        checklist — the templates are selected from the flag, so an insured
        patient could receive self-pay guidance. Rejected at the same 422
        edge as the closed vocabulary (plan_type is enum-valued, so naming it
        in the message echoes nothing client-controlled)."""
        if self.plan_type is None:
            return self
        is_self_pay = self.plan_type == PlanType.self_pay.value
        if self.has_insurance and is_self_pay:
            raise ValueError("plan_type Self-pay contradicts has_insurance=true")
        if not self.has_insurance and not is_self_pay:
            raise ValueError("an insured plan_type contradicts has_insurance=false")
        return self


class InstructionsChecklist(BaseModel):
    """Structured output contract for the LLM (via complete_structured).

    ``items`` carries template IDS from templates.CATALOG, never checklist
    prose — the closed-vocabulary response mirror of InstructionsRequest.

    Deliberately the LOOSEST possible shape — a bare ``list[str]``:

    * Not an enum, and no ``Field(min_length=...)`` count constraint: Bedrock's
      structured-output schema subset rejects ``minItems`` values other than
      0/1 (live ``ValidationException``, same class as the
      ``additionalProperties`` rule in ``llm_client._strict_schema``), and enum
      support is equally unproven — the wire schema stays inside the known-safe
      subset.
    * No local count/membership validator either: a validation failure inside
      ``complete_structured`` surfaces as ``LLMResponseError`` → 502, which
      would bypass the deterministic fallback. Every selection rule (catalog
      membership, fact-justification, item count) is enforced in
      ``app._select_items``, where a violation recovers to the fallback
      checklist instead of an error response.
    """

    items: list[str]


class InstructionsResponse(BaseModel):
    items: list[str]
    disclaimer: str


def log_metadata(req: InstructionsRequest) -> dict[str, Any]:
    """Loggable projection of an instructions request.

    Every field is already closed-vocabulary (enum/bool), so echoing the values
    is safe — but this stays an explicit allowlist (never ``model_dump`` of a
    request) so a future field addition has to opt in to being logged.
    """
    return {
        "has_insurance": req.has_insurance,
        "plan_type": req.plan_type,
        "policy_holder_is_self": req.policy_holder_is_self,
        "communications_opt_in": req.communications_opt_in,
        "financial_ack": req.financial_ack,
    }


# --------------------------------------------------------------------------- #
# visit-chat (ADR 0011)
# --------------------------------------------------------------------------- #
class VisitIntent(str, Enum):
    """What the clerk's turn is asking for, derived deterministically in app.py.

    A closed enum because this — not the message — is what reaches the prompt.
    """

    check_eligibility = "check_eligibility"   # one unambiguous member id in the turn
    recheck_eligibility = "recheck_eligibility"  # "check again" against stored facts
    ask_status = "ask_status"                 # "is it still active?" — answer from facts
    # Two ids in one message, or one that contradicts the visit's confirmed id.
    # Never guessed at: a wrong id yields a DEFINITIVE denial about the wrong
    # subject (payer 404 -> active:false), so the turn asks the human instead.
    clarify_member_id = "clarify_member_id"
    other = "other"                           # unrecognised; ask a clarifying question


class VisitTurn(BaseModel):
    """One stored conversation turn — METADATA ONLY, never the text.

    The clerk's prose is deliberately not persisted anywhere. Nothing in this
    feature consumes it: the deterministic logic reads ``VisitFacts``, and the
    only thing the LLM learns about the history is how many turns there have
    been. Storing the text would therefore be PHI at rest with no consumer — and
    unmaskable PHI at that, since a typed patient name defeats any pattern
    filter (``redaction.redact_text`` covers SSN / email / phone only).

    So a turn records what HAPPENED, not what was said. If a future revision
    needs the transcript itself (a chat UI replaying history, say), that is a new
    PHI-at-rest decision and needs its own approval — do not quietly add a text
    field here.
    """

    model_config = ConfigDict(extra="forbid")

    role: str = Field(pattern="^(user|assistant)$")
    intent: VisitIntent | None = None
    status: str | None = Field(default=None, max_length=32)


class VisitFacts(BaseModel):
    """The operational state carried across turns of one visit.

    ``extra="forbid"`` is a PHI control, not hygiene: this object is what the
    gateway persists into Redis, so a closed shape is what stops a future caller
    (or a smuggled key) from parking a name, a DOB, or a note in visit memory.
    ``last_eligibility`` holds the projected verdict from eligibility_client —
    which has already dropped the downstream `error` string and `insurance_id`.
    """

    model_config = ConfigDict(extra="forbid")

    insurance_id: str | None = None
    last_eligibility: dict[str, Any] | None = None


class VisitChatRequest(BaseModel):
    """A single chat turn. The ONE free-text surface in this service — see the
    module docstring for why that is safe and what it obliged us to build."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=settings.ai_visit_max_message_chars)
    # Bounded to the same window the gateway's store truncates to, so a caller
    # cannot hand this service an unbounded transcript to hold in memory. Entries,
    # not exchanges: one exchange is a `user` entry plus an `assistant` entry.
    turns: list[VisitTurn] = Field(
        default_factory=list, max_length=settings.ai_visit_max_turns
    )
    facts: VisitFacts = Field(default_factory=VisitFacts)


class VisitReplyPlan(BaseModel):
    """Structured output contract for the LLM (via complete_structured).

    ``template_ids`` carries ids from visit_templates.CATALOG, never reply prose.
    Deliberately the LOOSEST possible shape, for the same two reasons
    InstructionsChecklist documents: Bedrock's structured-output schema subset
    rejects ``minItems`` values other than 0/1, and a local count/membership
    validator would surface as ``LLMResponseError`` — which would bypass the
    deterministic fallback instead of landing in the selection gate. Every rule
    (catalog membership, status-justification, item count) is enforced in
    ``app._select_reply_items``.
    """

    template_ids: list[str]


class VisitChatResponse(BaseModel):
    """The turn's answer, plus the state the gateway persists.

    ``intent`` and ``status`` are echoed back precisely so the gateway can record
    a metadata-only turn (see VisitTurn) without ever handling the clerk's text
    again. Both are closed values this service derived, not client input.
    """

    reply: str
    intent: VisitIntent
    status: str
    facts: VisitFacts
    eligibility: dict[str, Any] | None = None
    disclaimer: str


def visit_chat_log_metadata(
    intent: VisitIntent, status: str, turn_count: int
) -> dict[str, Any]:
    """Loggable projection of a chat turn.

    An explicit allowlist of CLOSED values — an enum, a status string derived
    server-side from the ADR 0010 contract, and a count. The message, the
    transcript, the insurance id, and every downstream body field are absent by
    construction, and adding a field means adding it here on purpose (the D1
    lesson: never ``model_dump`` a request into a log).
    """
    return {
        "intent": intent.value if isinstance(intent, VisitIntent) else str(intent),
        "eligibility_status": status,
        "turn_count": turn_count,
    }
