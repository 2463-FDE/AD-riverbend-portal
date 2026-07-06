"""ai-assistant — home of the production LLM client wrapper (ADR 0004).

Deliberately ships NO user-facing AI endpoint yet: this service exists so the
wrapper (llm_client.py) and the PHI redaction helper (redaction.py) land with
tests and guardrails before any feature is built on them. The previous
contractor's ai-orchestrator service (removed pre-handoff) had none of these
guardrails — see adr/0004-ai-assistant-service-and-llm-wrapper.md.

Feature endpoints (e.g. patient-friendly intake instructions) come later and
must go through the gateway like every other service.
"""
from fastapi import FastAPI

from config import settings
from logging_config import configure
import llm_client  # noqa: F401 — imported so CI's import smoke covers the wrapper

log = configure(settings.service_name)

app = FastAPI(title="Riverbend ai-assistant", version="0.1.0")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": settings.service_name}
