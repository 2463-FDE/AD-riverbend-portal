"""Pydantic v2 request/response schemas for intake-service."""
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConsentKind(str, Enum):
    """Closed set of consent identifiers intake accepts.

    Constraining consents to this enum (rather than a free-form ``list[str]``)
    is a PHI control, not merely validation. As an open string list, a client
    could smuggle an identifier like ``"Jane Doe DOB 1985-03-12"`` into the
    request, and that string reached the intake log — pattern redaction only
    scrubs SSN/email/phone, not names or dates. Unknown values are now rejected
    at the boundary, so they never reach the log or the database. Mirrors the
    values documented on ``models.Consent.kind``. See docs/phi-logging-policy.md.
    """

    npp_ack = "npp_ack"
    treatment_consent = "treatment_consent"
    roi_consent = "roi_consent"


class Demographics(BaseModel):
    name: str
    dob: Optional[str] = None
    ssn: Optional[str] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None
    created_via: str = "self_service"

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("name must not be blank")
        return v.strip()


class Insurance(BaseModel):
    payer_name: Optional[str] = None
    member_id: Optional[str] = None
    group_number: Optional[str] = None
    plan_type: Optional[str] = None


class IntakeRequest(BaseModel):
    # use_enum_values so a validated req.consents is a list of plain strings,
    # matching how models.Consent.kind is stored and how log_metadata emits it.
    model_config = ConfigDict(use_enum_values=True)

    demographics: Demographics
    insurance: Optional[Insurance] = None
    consents: list[ConsentKind] = Field(
        default_factory=lambda: ["npp_ack", "treatment_consent"]
    )


class IntakeResponse(BaseModel):
    patient_id: int
    elapsed_seconds: float
    eligibility: Optional[dict[str, Any]] = None


def log_metadata(req: IntakeRequest) -> dict[str, Any]:
    """Allowlisted, non-PHI projection of an intake request, for logging.

    Intake must never log raw request strings — that is the D1 exposure, and
    ``redaction.safe_log_payload`` alone does not close it: pattern scrubbing
    misses names, DOBs, and any other PHI stuffed into a free-text field. This
    returns only structural facts — the ``ConsentKind``-constrained consents
    plus boolean presence flags. No demographic or insurance *value* is copied
    out, so PHI cannot leak even when a client fills a free-text field with it.
    See docs/phi-logging-policy.md.
    """
    demo = req.demographics
    ins = req.insurance
    return {
        "consents": list(req.consents),          # constrained to ConsentKind
        "self_service": demo.created_via == "self_service",
        "has_insurance": ins is not None,
        "has_ssn": bool(demo.ssn),
        "has_dob": bool(demo.dob),
        "has_email": bool(demo.email),
        "has_phone": bool(demo.phone),
        "has_address": bool(demo.address),
        "has_notes": bool(demo.notes),
    }
