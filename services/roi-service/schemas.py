"""Pydantic v2 request/response schemas for roi-service."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RoiRequestCreate(BaseModel):
    patient_id: int = Field(..., gt=0)
    requested_by: str = Field(..., min_length=1)
    recipient: str = Field(..., min_length=1)
    recipient_type: str = Field(..., min_length=1)  # self | provider | attorney | payer
    purpose: str | None = None
    date_range_start: str | None = None
    date_range_end: str | None = None


class RoiRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    requested_by: str | None = None
    recipient: str | None = None
    recipient_type: str | None = None
    purpose: str | None = None
    date_range_start: str | None = None
    date_range_end: str | None = None
    status: str
    created_at: datetime | None = None


class RecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    encounter_id: int
    patient_id: int
    kind: str | None = None
    title: str | None = None
    body: str | None = None
    status: str | None = None


class FulfillResult(BaseModel):
    request_id: int
    patient_id: int
    status: str
    disclosure_id: int
    records: list[RecordOut]


class DisclosureRecords(BaseModel):
    patient_id: int
    records: list[RecordOut]
