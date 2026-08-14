"""Pydantic v2 request/response schemas for intake-service."""
import re
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# A submission-attempt identifier: RFC 4122 version-4 UUID, variant bits pinned
# (the ``4`` and the ``[89ab]``). The portal mints one per attempt
# (e5b-SPEC-18); the service only NARROWS the accidental-derivation class — this
# format check cannot prove randomness, which lives at the mint (e5b-D-9). A
# missing or malformed id is rejected in e4's correctable-input branch
# (e5b-SPEC-11/19), reached because the field is required.
_SUBMISSION_ID_RE = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z",
    re.IGNORECASE,
)


class ConsentKind(str, Enum):
    """Closed set of consent identifiers intake accepts.

    Constraining consents to this enum (rather than a free-form ``list[str]``)
    is a PHI control, not merely validation. As an open string list, a client
    could smuggle an identifier like ``"Jane Doe DOB 1985-03-12"`` into the
    request, and that string reached the intake log — pattern redaction only
    scrubs SSN/email/phone, not names or dates. Unknown values are now rejected
    at the boundary, so they never reach the log or the database. Mirrors the
    values documented on ``models.Consent.kind``. See docs/phi-logging-policy.md.

    The set is closed and pinned by test (tests/test_intake_schemas.py) — the
    intake form collects exactly these five, and the shared payload declaration
    (contracts/intake-registration.json) is asserted equal to them from both
    suites, so neither side can drift the vocabulary on its own.
    """

    npp_ack = "npp_ack"
    treatment_consent = "treatment_consent"
    roi_consent = "roi_consent"
    financial_responsibility_ack = "financial_responsibility_ack"
    communications_opt_in = "communications_opt_in"


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

    # The submission-attempt identifier the portal mints (e5b-SPEC-3/4). Required
    # root field: a missing one is a correctable-input rejection (e5b-SPEC-11),
    # the accepted TODO-shape residual — the portal always sends it. Stored TEXT,
    # non-PHI by construction, so it joins the log allowlist below.
    submission_id: str
    demographics: Demographics
    insurance: Optional[Insurance] = None
    consents: list[ConsentKind] = Field(
        default_factory=lambda: ["npp_ack", "treatment_consent"]
    )

    @field_validator("submission_id")
    @classmethod
    def submission_id_is_uuid4(cls, v: str) -> str:
        # Narrows the accidental-derivation class only (e5b-SPEC-19): a value
        # that is not a version-4 UUID cannot be a random mint of one, so it is
        # rejected before any read or write. Randomness itself is the mint's
        # guarantee (e5b-D-9), not provable here. Canonicalize to lowercase so an
        # uppercased-but-valid id is stored and matched in one form — a replay
        # must never miss on case alone.
        if not _SUBMISSION_ID_RE.match(v or ""):
            raise ValueError("submission_id must be a version-4 UUID")
        return v.lower()


class IntakeResponse(BaseModel):
    patient_id: int
    elapsed_seconds: float
    eligibility: Optional[dict[str, Any]] = None


class Disposition(str, Enum):
    """Closed set of judgments a reviewer can record on a candidate pair.

    Neither value merges anything: confirming a duplicate records that a human
    agrees the two charts are one person, and the merge itself remains a manual
    HIM procedure (ADR 0005 decision 3).
    """

    duplicate_confirmed = "duplicate_confirmed"
    not_duplicate = "not_duplicate"


class ReviewQueuePatient(BaseModel):
    """The minimum a reviewer needs to judge whether two charts are one person.

    Deliberately narrower than the patients row: no SSN and no address. Both
    would help a reviewer, and neither is minimum-necessary for a front-desk
    role that the debt log already flags for over-broad demographic access —
    this surface does not widen it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    dob: Optional[str] = None
    created_via: Optional[str] = None
    created_at: Optional[datetime] = None


class ReviewQueueItem(BaseModel):
    id: int
    patient_a: ReviewQueuePatient
    patient_b: ReviewQueuePatient
    source: str
    created_at: Optional[datetime] = None


class ReviewQueuePage(BaseModel):
    items: list[ReviewQueueItem]


class DispositionRequest(BaseModel):
    # use_enum_values so a validated disposition is a plain string, matching
    # how models.DuplicateReviewQueue.disposition is stored.
    model_config = ConfigDict(use_enum_values=True)

    disposition: Disposition
    decided_by: str

    @field_validator("decided_by")
    @classmethod
    def decided_by_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("decided_by must not be blank")
        return v.strip()


class DispositionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    disposition: str
    decided_by: str
    decided_at: Optional[datetime] = None


def disposition_log_metadata(pair_id: int, req: DispositionRequest) -> dict[str, Any]:
    """Allowlisted, non-PHI projection of a disposition request, for logging.

    Same discipline as ``log_metadata``: only the queue row id, the
    ``Disposition``-constrained verdict, and the staff username doing the
    deciding. No patient identifier and no demographic value — a reviewer's
    decision is auditable without logging who it was about.
    """
    return {
        "pair_id": pair_id,
        "disposition": req.disposition,
        "decided_by": req.decided_by,
    }


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
        # The submission_id is deliberately NOT emitted here: it is
        # caller-controllable and cannot be proven non-PHI at this boundary, so
        # app.py logs a server-keyed digest (submission_ref) instead of the raw
        # value (_submission_log_id; e5b-SPEC-20; PR #79 codex r1).
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
