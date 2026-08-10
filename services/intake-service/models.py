"""ORM models intake-service touches. (Copy-paste per service — no shared lib yet.)"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
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
