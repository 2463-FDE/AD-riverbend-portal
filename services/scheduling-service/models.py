"""ORM models scheduling-service touches. (Copy-paste per service — no shared lib yet.)

Columns mirror db/schema.sql exactly. NOTE: appointments.slot_id deliberately
has no UNIQUE constraint and no FK in the schema — the double-booking race in
book.py depends on that. Do not add a UniqueConstraint here.
"""
from sqlalchemy import Column, DateTime, Integer, Text
from sqlalchemy.sql import func

from db import Base


class Provider(Base):
    __tablename__ = "providers"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    specialty = Column(Text)
    location = Column(Text)


class Slot(Base):
    __tablename__ = "slots"

    id = Column(Integer, primary_key=True)
    provider_id = Column(Integer)  # REFERENCES providers(id) at the DB level
    location = Column(Text)
    start_at = Column(DateTime(timezone=True), nullable=False)
    end_at = Column(DateTime(timezone=True))
    status = Column(Text, nullable=False, default="open")  # open | booked (advisory)


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, nullable=False)
    slot_id = Column(Integer, nullable=False)  # no UNIQUE, no FK — see book.py race
    provider = Column(Text)
    reason = Column(Text)
    location = Column(Text)
    scheduled_for = Column(DateTime(timezone=True))
    status = Column(Text, nullable=False, default="confirmed")
    created_at = Column(DateTime(timezone=True), server_default=func.clock_timestamp())


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True)
    mrn = Column(Text)
    name = Column(Text, nullable=False)
    dob = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
