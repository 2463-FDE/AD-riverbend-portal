"""Pydantic v2 request/response schemas for scheduling-service."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider_id: Optional[int] = None
    provider: Optional[str] = None  # provider name, joined from providers
    location: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    status: str


class SlotListResponse(BaseModel):
    items: List[SlotOut]
    count: int
    limit: int
    offset: int


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    slot_id: int
    provider: Optional[str] = None
    reason: Optional[str] = None
    location: Optional[str] = None
    scheduled_for: Optional[datetime] = None
    status: str
    created_at: Optional[datetime] = None


class AppointmentListResponse(BaseModel):
    items: List[AppointmentOut]
    count: int


class BookingRequest(BaseModel):
    patient_id: int = Field(..., gt=0)
    slot_id: int = Field(..., gt=0)
    provider: Optional[str] = Field(None, max_length=200)
    reason: Optional[str] = Field(None, max_length=2000)
    location: Optional[str] = Field(None, max_length=200)
    scheduled_for: Optional[datetime] = None


class BookingResponse(BaseModel):
    appointment_id: Optional[int] = None
    status: str  # confirmed | slot_taken


class CancelResponse(BaseModel):
    appointment_id: int
    status: str  # cancelled
