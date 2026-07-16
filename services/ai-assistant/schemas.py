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

from pydantic import BaseModel, ConfigDict, field_validator


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


class InstructionsChecklist(BaseModel):
    """Structured output contract for the LLM (via complete_structured).

    The item count is enforced with a validator, NOT ``Field(min_length=...)``:
    the Field constraints emit ``minItems``/``maxItems`` into the JSON schema,
    and Bedrock's structured-output schema subset rejects ``minItems`` values
    other than 0/1 (live ``ValidationException``, same class as the
    ``additionalProperties`` rule in ``llm_client._strict_schema``). A
    validator keeps the wire schema inside the supported subset while
    ``model_validate_json`` still enforces the full contract locally — an
    out-of-range response surfaces as a typed ``LLMResponseError``.
    """

    items: list[str]

    @field_validator("items")
    @classmethod
    def item_count_in_range(cls, v: list[str]) -> list[str]:
        if not 3 <= len(v) <= 8:
            raise ValueError("checklist must have between 3 and 8 items")
        return v


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
