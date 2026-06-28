"""Pydantic v2 response/request schemas for records-service."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PatientSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mrn: str | None = None
    name: str
    dob: str | None = None
    gender: str | None = None
    created_at: datetime | None = None


class PatientDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mrn: str | None = None
    name: str
    dob: str | None = None
    ssn: str | None = None
    gender: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    notes: str | None = None
    created_via: str | None = None
    created_at: datetime | None = None


class PatientPage(BaseModel):
    items: list[PatientSummary]
    total: int
    limit: int
    offset: int


class RecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    encounter_id: int
    patient_id: int
    kind: str | None = None
    title: str | None = None
    body: str | None = None
    status: str | None = None
    reference_range: str | None = None


class EncounterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    encounter_type: str | None = None
    provider: str | None = None
    reason: str | None = None
    location: str | None = None
    status: str | None = None
    summary: str | None = None
    allergies: str | None = None
    medications: str | None = None


class EncounterWithRecords(BaseModel):
    encounter: EncounterOut
    records: list[RecordOut]


class PatientChart(BaseModel):
    patient_id: int
    encounters: list[EncounterWithRecords]


class RecordSearchHit(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    kind: str | None = None
    title: str | None = None
    body: str | None = None
