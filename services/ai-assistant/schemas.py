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
"""
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


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
