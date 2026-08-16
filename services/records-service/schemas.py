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


class RelevantRecordItem(BaseModel):
    """One ranked pointer into the chart below the panel.

    Titles and dates, never record bodies: the panel links attention, and the
    chart remains the record view. ``reason`` is why this record ranked, so the
    clinician can see the ranking rather than trust it.
    """

    record_id: int
    kind: str | None = None
    title: str | None = None
    occurred_at: datetime | None = None
    reason: str          # allergy | medication | recent


class RelevantRecords(BaseModel):
    """The chart-open helper's response.

    ``duplicate_disclosure`` is a BARE ENUM on purpose. Naming the sibling
    charts would turn a warning into a cross-chart navigation path, and reading
    across charts that no human has approved merging is exactly what ADR 0005
    rejected. "candidate" says other charts may exist; it never says which.
    """

    patient_id: int
    duplicate_disclosure: str   # candidate | none
    items: list[RelevantRecordItem]


class RecordSearchHit(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    kind: str | None = None
    title: str | None = None
    body: str | None = None


class RecordSearch(BaseModel):
    """Bounded free-text search response (e6-SPEC-5).

    ``truncated`` is the whole point of the wrapper: a capped result set must be
    distinguishable from an exhausted one, so a caller can tell "no more matches"
    from "matches withheld" — a silent cap on a clinical search is a
    patient-safety failure mode of its own (e6-D-4). Shape declared in
    contracts/records-search.json and asserted from both suites.
    """

    hits: list[RecordSearchHit]
    truncated: bool
