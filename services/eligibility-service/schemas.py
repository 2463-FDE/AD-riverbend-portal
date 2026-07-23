"""Pydantic v2 response schemas for eligibility-service (X12 270/271 shaped)."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class EligibilityResponse(BaseModel):
    # `active` is TRI-STATE (ADR 0010): True = coverage active, False = definitely
    # inactive (payer answered), None = unknown (payer unreachable/timeout/breaker
    # open). None — not False — is used for non-definitive results so that a
    # caller reading only `active` can never mistake a dependency outage for a
    # coverage denial. `status` carries the finer detail (active/inactive/unknown/
    # pending).
    insurance_id: str
    active: Optional[bool] = None
    status: Optional[str] = None
    payer: Optional[str] = None
    raw_status: Optional[int] = None
    checked_at: datetime
    error: Optional[str] = None
