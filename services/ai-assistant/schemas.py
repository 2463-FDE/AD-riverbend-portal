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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import policy_index
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


def _closed_enum(name: str, values) -> type:
    """One clerk-selection enum, DERIVED from ``policy_index``'s own axis tuple.

    Never a hand-typed second copy: derived sets are equal by construction. The
    portal's and gateway's copies are held to ``contracts/visit-chat-turn.json`` by
    their own suites (eligibility-assistant-D-45).
    """
    return Enum(name, {value: value for value in values}, type=str)


# The four closed menus the clerk selects from (eligibility-assistant-D-36, REQ-17′).
QuestionType = _closed_enum("QuestionType", policy_index.QUESTION_TYPES)
Payer = _closed_enum("Payer", policy_index.PAYERS)
Product = _closed_enum("Product", policy_index.PRODUCTS)
State = _closed_enum("State", policy_index.STATES)


class RenderedCitation(BaseModel):
    """One citation as the clerk sees it — four fields, all from the index row.

    ``section`` is the manifest's label string VERBATIM, never split or re-derived
    (eligibility-assistant-D-61). Both paths render through this shape (SPEC-4/6).
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    document_id: str
    section: str
    version: str


class Citation(BaseModel):
    """Citation PROVENANCE as it is persisted — ids and version only (SPEC-20).

    Not ``RenderedCitation``: a title or section label in Redis is document text at
    rest with no consumer. A citation is re-rendered from the index by id.
    """

    model_config = ConfigDict(extra="forbid")

    document_id: str
    version: str


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
    # Citation PROVENANCE, ids and version only (SPEC-20). ``Citation`` is
    # ``extra="forbid"``, so a smuggled `text` key is rejected, not stored.
    last_citations: list[Citation] | None = None

    @field_validator("insurance_id")
    @classmethod
    def _normalise_insurance_id(cls, value: str | None) -> str | None:
        """Fold the stored id to upper case at the boundary (Codex PR #14 round 3).

        The catalog is upper case and the recogniser now matches case-insensitively,
        so `aetn1224` and `AETN1224` are the same subject. That equality has to hold
        for the STORED id too: `_derive_intent` treats an id that differs from the
        one on file as a contradiction and refuses to run a lookup, so a
        case-only difference would strand a visit in "confirm which member ID"
        forever. Normalising here rather than at each comparison means the value
        the gateway persists, echoes back, and compares is one canonical form.

        Non-ASCII is REJECTED, not folded. `.upper()` is not a canonicalisation
        over Unicode (U+0130 and U+212A survive it), and a stored id is used
        directly for a payer lookup on a recheck turn without passing back
        through the recogniser — so an id that got in here by any route other
        than `_extract_insurance_ids` could reach the payer as-is, where a 404
        renders as a definitive denial. 422 at the boundary is the fail-closed
        answer; the caller is the gateway, never a human, so nothing is echoed.
        """
        if not value:
            return value
        folded = value.upper()
        if not folded.isascii():
            raise ValueError("insurance_id must be ASCII")
        return folded


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
    # The clerk's four closed menu selections (SPEC-54/55). REQUIRED: a defaulted
    # selection would be this service inventing a clerk's answer.
    question_type: QuestionType
    payer: Payer
    product: Product
    state: State
    # The clerk's explicit emergency control (SPEC-44): opt-in, never inferred.
    emergency: bool = False


class VisitChatResponse(BaseModel):
    """The turn's answer, plus the state the gateway persists.

    ``intent`` and ``status`` are echoed back precisely so the gateway can record
    a metadata-only turn (see VisitTurn) without ever handling the clerk's text
    again. Both are closed values this service derived, not client input.

    ``llm_egress`` carries the spend accounting that used to be encoded in the
    HTTP status alone (Codex PR #14 round 3). A turn can now succeed WITHOUT a
    paid Bedrock call — a local config or budget refusal degrades to the
    deterministic action list instead of throwing away a coverage verdict that
    was already computed — so 200 no longer implies "billable". False tells the
    gateway to refund the slot it reserved for this turn; the field is a boolean
    about our own infrastructure and carries nothing about the patient.
    """

    reply: str
    intent: VisitIntent
    status: str
    facts: VisitFacts
    eligibility: dict[str, Any] | None = None
    disclaimer: str
    # Conservative default: an unset value must read as "we may have been
    # billed", so a future field-drop over-counts toward the ceiling instead of
    # silently refunding real spend.
    llm_egress: bool = True
    # "ok" | "degraded". Distinct from llm_egress, which is spend accounting:
    # a post-egress failure is billable AND degraded, a local refusal is neither
    # billable nor undegraded. Before this PR an LLM fault reached the operator
    # as a 503; now it reaches them as a normal-looking 200, so the degradation
    # needs a channel of its own or it is invisible — the green-dashboard /
    # dead-service shape this repo has already been bitten by. The gateway
    # forwards it, exactly as it forwards `visit_memory`.
    assistant: str = "ok"
    # Rendered sources, same shape on both paths (SPEC-4/6). Empty only on a refusal.
    citations: list[RenderedCitation] = Field(default_factory=list)
    # Which path produced the reply (SPEC-33, eligibility-assistant-D-33). A third
    # axis beside `assistant` (health) and `llm_egress` (spend) (D-71).
    mode: str
    # Why the turn was deterministic (eligibility-assistant-D-19); None on a
    # completed agent path.
    reason: str | None = None
    # What the turn concluded — one of the ten Appendix values (SPEC-14).
    outcome: str
    # Request identity (SPEC-26): a UUIDv4 minted by the portal, carried in as a
    # header, never derived from patient or member identity (D-46).
    correlation_id: str
    # The model/profile identifier the turn ran against — structural, not content.
    model: str


class AgentDecision(BaseModel):
    """Model₂'s decision: which sources to cite and what to do about them.

    Deliberately the LOOSEST possible shape, for the reasons ``InstructionsChecklist``
    documents. Every rule (SPEC-5/13) is enforced in application code, where a
    violation becomes `validation_reject` rather than an error.
    """

    citation_ids: list[str]
    action_ids: list[str]


def visit_chat_log_metadata(
    intent: VisitIntent,
    status: str,
    turn_count: int,
    checked: bool = False,
    *,
    mode: str | None = None,
    reason: str | None = None,
    outcome: str | None = None,
    model_calls: int | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Loggable projection of a chat turn.

    An explicit allowlist of CLOSED values — an enum, a status string derived
    server-side from the ADR 0010 contract, a count, and a boolean. The message,
    the transcript, the insurance id, and every downstream body field are absent by
    construction, and adding a field means adding it here on purpose (the D1
    lesson: never ``model_dump`` a request into a log).

    ``checked`` is whether a payer lookup ran on this turn. It is separate from
    ``intent`` because ``ask_status`` stopped implying it once a fresh verdict could
    answer a repeated member id (round 4): two materially different events — a
    question answered from memory, and a re-verification declined as unnecessary —
    otherwise log identically, and neither the reply text nor the response shape
    distinguishes them either.
    """
    line = {
        "intent": intent.value if isinstance(intent, VisitIntent) else str(intent),
        "eligibility_status": status,
        "turn_count": turn_count,
        "checked": bool(checked),
    }
    # Five more CLOSED or structural values (eligibility-assistant-D-33/D-19/D-15, an
    # int, a UUIDv4), inside phi-logging-policy rules 1/2/4/5 by construction. Added
    # by explicit allowlist, never `model_dump` (the D1 lesson). Omitted rather than
    # None-filled: the older `/visit-chat` line is a different event.
    for key, value in (
        ("mode", mode),
        ("reason", reason),
        ("outcome", outcome),
        ("model_calls", model_calls),
        ("correlation_id", correlation_id),
    ):
        if value is not None:
            line[key] = value
    return line
