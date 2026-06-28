"""Pydantic v2 request/response schemas for interop-service."""
from typing import List, Optional

from pydantic import BaseModel, Field


class HL7IngestRequest(BaseModel):
    """Inbound HL7 v2 message. The gateway now POSTs JSON (not text/plain)."""

    message: str = Field(..., min_length=1, description="Raw HL7 v2 message text")


class ParsedRecord(BaseModel):
    """Internal record shape produced by hl7_parser.parse().

    NOTE: allergies/medications are part of the shape but the parser only maps
    PID/PV1 — AL1/RXA segments are silently dropped (brittle-parser debt, D6).
    """

    mrn: Optional[str] = None
    name: Optional[str] = None
    dob: Optional[str] = None
    provider: Optional[str] = None
    location: Optional[str] = None
    allergies: List[str] = Field(default_factory=list)
    medications: List[str] = Field(default_factory=list)


class HL7IngestResponse(BaseModel):
    record: ParsedRecord
    unmapped_note: str
