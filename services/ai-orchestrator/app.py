"""
ai-orchestrator — the "AI summary" box.

The board wanted AI, so the last contractor wired a summary endpoint straight
to Bedrock. There is no input scrub, no output validation, and no BAA covering
the vendor; the full encounter record is sent as-is.
"""
from fastapi import FastAPI
from pydantic import BaseModel

from bedrock_client import invoke

app = FastAPI(title="Riverbend ai-orchestrator")


class SummaryRequest(BaseModel):
    # The whole record gets dumped in: name, dob, mrn, notes.
    name: str | None = None
    dob: str | None = None
    mrn: str | None = None
    notes: str | None = None
    instructions: str | None = None


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/summary")
def summarize(req: SummaryRequest):
    """
    Build a prompt from the raw PHI and send it to the LLM vendor. No
    de-identification before the call, no output grounding/validation after it.
    """
    record = req.model_dump()
    prompt = (
        "Write a patient-friendly summary of these intake instructions.\n"
        f"Patient record: {record}\n"
    )
    text = invoke(prompt)            # raw model output returned to the caller
    return {"summary": text}
