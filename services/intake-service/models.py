"""ORM models intake-service touches. (Copy-paste per service — no shared lib yet.)"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.sql import func

from db import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True)            # sequential, exposed in record URLs
    mrn = Column(Text)                                # not used as a match key
    name = Column(Text, nullable=False)
    dob = Column(Text)                                # stored as ISO string, not DATE
    ssn = Column(Text)                                # plain text
    gender = Column(Text)
    address = Column(Text)
    phone = Column(Text)
    email = Column(Text)
    notes = Column(Text)
    created_via = Column(Text)                        # self_service | front_desk
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class InsuranceCoverage(Base):
    __tablename__ = "insurance_coverages"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    payer_name = Column(Text)
    member_id = Column(Text)
    group_number = Column(Text)
    plan_type = Column(Text)                          # PPO | HMO | Medicaid | Medicare | self_pay
    status = Column(Text, default="unknown")          # active | inactive | unknown
    verified_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Consent(Base):
    __tablename__ = "consents"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    # npp_ack | treatment_consent | roi_consent | financial_responsibility_ack
    # | communications_opt_in  (the closed set schemas.ConsentKind enforces)
    kind = Column(Text)
    signed_at = Column(DateTime(timezone=True), server_default=func.now())


class DuplicateReviewQueue(Base):
    """A candidate-duplicate pair awaiting a human disposition (ADR 0005).

    No PHI columns by design: the pair is identified by patient id, and every
    other column is an enum, a timestamp, or the deciding staff username. The
    ordered pair (patient_id_a < patient_id_b) plus the UNIQUE constraint make
    a repeated intake or retroactive pass idempotent.
    """

    __tablename__ = "duplicate_review_queue"

    id = Column(Integer, primary_key=True)
    patient_id_a = Column(Integer, ForeignKey("patients.id"), nullable=False)
    patient_id_b = Column(Integer, ForeignKey("patients.id"), nullable=False)
    source = Column(Text, nullable=False)             # intake | retroactive
    status = Column(Text, nullable=False, default="pending")   # pending | dispositioned
    disposition = Column(Text)                        # duplicate_confirmed | not_duplicate
    decided_by = Column(Text)
    decided_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MatchEvaluationFailure(Base):
    """A match-key evaluation that failed while registering a patient.

    The registration itself still completed — matching is never a dependency of
    creating a chart — so this row is what keeps the unchecked patient
    traceable and eligible for the retroactive pass. ``error_class`` holds the
    exception class name only: a stringified SQLAlchemy error embeds the bound
    patients row (name, DOB, SSN).
    """

    __tablename__ = "match_evaluation_failures"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    error_class = Column(Text, nullable=False)        # class name, never a message
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RegistrationSubmission(Base):
    """One recorded registration attempt — the idempotency ledger (e5b).

    No PHI columns by design (e5b-SPEC-18/20/21). ``submission_id`` is the
    portal's mint-random version-4 UUID, non-PHI by construction, and the UNIQUE
    constraint on it is the sole arbiter of a retry: the first committer wins and
    every retry of the same attempt re-reads this row rather than forking a
    second chart (e5b-D-12). ``payload_fingerprint`` is a keyed HMAC of the
    validated content from which no patient value is recoverable (e5b-D-8/D-11) —
    it distinguishes an identical replay from a corrected one without storing any
    field. No eligibility verdict is persisted here (e5b-SPEC-29); the row is an
    id, a fingerprint, an FK, and a timestamp.
    """

    __tablename__ = "registration_submissions"

    id = Column(Integer, primary_key=True)
    submission_id = Column(Text, nullable=False)      # portal-minted v4 UUID, non-PHI
    payload_fingerprint = Column(Text, nullable=False)  # keyed HMAC, not reversible
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("submission_id", name="uq_registration_submission_id"),
    )
