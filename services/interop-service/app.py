"""
interop-service — ingests HL7 v2 messages from the hospital system feed.

The gateway now sends JSON ({"message": "<raw hl7>"}) rather than text/plain.
Parsing is delegated to hl7_parser.parse(), which is intentionally brittle: it
only maps PID/PV1 and silently drops AL1 (allergies) and RXA (medications).
That loss is preserved here on purpose (brittle-parser debt, D6).
"""
import os

from fastapi import FastAPI, HTTPException

from config import settings
from hl7_parser import parse
from logging_config import configure
from schemas import HL7IngestRequest, HL7IngestResponse, ParsedRecord

log = configure(settings.service_name)

app = FastAPI(title="Riverbend interop-service")

SAMPLE_PATH = os.path.join(os.path.dirname(__file__), "samples", "adt_sample.hl7")

# Plain-language note returned with every ingest. We do NOT compute this from the
# message (the parser drops AL1/RXA before we ever see a segment count), so the
# loss stays invisible to callers — exactly the legacy behaviour.
UNMAPPED_NOTE = (
    "Only PID and PV1 segments are mapped into the internal record; "
    "other segments are not surfaced."
)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": settings.service_name}


@app.post("/hl7/ingest", response_model=HL7IngestResponse)
def ingest(req: HL7IngestRequest):
    """Parse an inbound HL7 message into our internal record shape."""
    message = req.message
    if not message.strip():
        # Pydantic min_length catches empty strings; this catches whitespace-only.
        raise HTTPException(status_code=422, detail="message must not be empty")

    if len(message.encode("utf-8")) > settings.max_message_bytes:
        raise HTTPException(status_code=413, detail="message too large")

    try:
        record = parse(message)
    except Exception:
        # The parser swallows per-segment errors internally; this guards against
        # anything unexpected at the call boundary.
        log.exception("HL7 parse failed")
        raise HTTPException(status_code=422, detail="could not parse HL7 message")

    log.info("ingested HL7 message (%d bytes)", len(message.encode("utf-8")))
    # No schema validation of dropped/unmapped segments — AL1/RXA are already
    # gone by the time we get the record back.
    return HL7IngestResponse(
        record=ParsedRecord(**record), unmapped_note=UNMAPPED_NOTE
    )


@app.get("/hl7/sample")
def sample():
    """Return the bundled ADT sample message (useful for smoke-testing ingest)."""
    try:
        with open(SAMPLE_PATH, "r", encoding="utf-8") as fh:
            content = fh.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="sample message not found")
    return {"message": content}
