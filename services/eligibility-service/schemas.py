"""Pydantic v2 response schemas for eligibility-service (X12 270/271 shaped)."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class EligibilityResponse(BaseModel):
    insurance_id: str
    active: bool
    payer: Optional[str] = None
    raw_status: Optional[int] = None
    checked_at: datetime
    error: Optional[str] = None
