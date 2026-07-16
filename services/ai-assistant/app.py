"""ai-assistant — production LLM client wrapper (ADR 0004) + first feature
endpoint.

The wrapper (llm_client.py) and the PHI redaction helper (redaction.py) landed
first, with tests and guardrails, before any feature was built on them. The
previous contractor's ai-orchestrator service (removed pre-handoff) had none of
these guardrails — see adr/0004-ai-assistant-service-and-llm-wrapper.md.

POST /intake-instructions is the first feature endpoint: patient-friendly
visit-prep instructions generated from a CLOSED-VOCABULARY request (see
schemas.py — no free text, so no PHI and no prompt-injection surface can reach
the LLM). It is reached only through the gateway, like every other service.
"""
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from config import settings
from logging_config import configure
import llm_client
from schemas import (
    InstructionsChecklist,
    InstructionsRequest,
    InstructionsResponse,
    log_metadata,
)

log = configure(settings.service_name)

app = FastAPI(title="Riverbend ai-assistant", version="0.2.0")

# Grounding boundary (curriculum W7 is the full guardrail; this endpoint stays
# inside a scope where hallucination cannot become clinical advice): the model
# is restricted to administrative visit-prep guidance derived from the closed
# facts below. It is told to produce NO clinical content at all; the disclaimer
# is fixed text appended server-side, never model-generated.
_SYSTEM_PROMPT = (
    "You write short visit-preparation checklists for new patients of a "
    "community health clinic. Use ONLY the administrative facts provided. "
    "Rules: no medical or clinical advice of any kind; never mention "
    "medications, conditions, diagnoses, or treatment; do not invent facts "
    "about the patient, the clinic, or their coverage; each item is one plain, "
    "friendly sentence about practical preparation (documents to bring, "
    "arriving early, contact expectations)."
)

_DISCLAIMER = (
    "These are general visit-preparation tips, not medical advice. "
    "For questions about your health or medications, contact your care team."
)


def _build_prompt(req: InstructionsRequest) -> str:
    """Render the closed request facts as prompt lines.

    Input is enum/boolean only (schemas.InstructionsRequest), so every string
    interpolated here comes from THIS function or the PlanType enum — no
    client-controlled text ever enters the prompt.
    """
    if req.has_insurance:
        plan = f"yes ({req.plan_type})" if req.plan_type else "yes"
    else:
        plan = "no (self-pay or undecided)"
    facts = [
        f"- insurance on file: {plan}",
        f"- policy holder is the patient: {'yes' if req.policy_holder_is_self else 'no'}",
        f"- opted into appointment reminders: {'yes' if req.communications_opt_in else 'no'}",
        f"- acknowledged financial responsibility: {'yes' if req.financial_ack else 'no'}",
    ]
    return (
        "A new patient just completed self-service intake. Administrative facts:\n"
        + "\n".join(facts)
        + "\n\nWrite their visit-preparation checklist."
    )


@app.exception_handler(RequestValidationError)
async def validation_error_no_echo(request: Request, exc: RequestValidationError):
    """422 without echoing the rejected input back.

    FastAPI's default validation response includes an ``input`` key carrying
    the offending value verbatim. On this service a rejected value is exactly
    the one place PHI could appear (smuggled into an unknown field — the
    schema itself has no free text), so the echo is stripped: the caller gets
    the field location and error type, never the value. Nothing here is
    logged — a rejected body must not reach a log record either.
    """
    errors = [
        {"loc": e.get("loc", ()), "type": e.get("type", ""), "msg": e.get("msg", "")}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": settings.service_name}


@app.post("/intake-instructions", response_model=InstructionsResponse)
def intake_instructions(req: InstructionsRequest):
    # Allowlisted, non-PHI projection only — never the request body (D1 lesson,
    # docs/phi-logging-policy.md). Values here are closed-vocabulary by schema.
    log.info("POST /intake-instructions meta=%s", json.dumps(log_metadata(req)))
    try:
        result = llm_client.complete_structured(
            prompt=_build_prompt(req),
            output_model=InstructionsChecklist,
            system=_SYSTEM_PROMPT,
        )
    except llm_client.LLMConfigError as e:
        # llm_client error messages are metadata-only by contract (ADR 0004) —
        # safe to log; the client still gets a generic detail.
        log.error("intake-instructions config error: %s", e)
        raise HTTPException(status_code=503, detail="assistant is not configured")
    except llm_client.LLMUnavailable as e:
        log.error("intake-instructions provider unavailable: %s", e)
        raise HTTPException(status_code=503, detail="assistant is temporarily unavailable")
    except llm_client.LLMResponseError as e:
        log.error("intake-instructions bad model response: %s", e)
        raise HTTPException(status_code=502, detail="assistant returned an unusable response")
    except llm_client.LLMError as e:
        # Includes LLMBudgetExceeded — unexpected here (the prompt is fixed-size
        # and small), so it indicates misconfigured budget settings.
        log.error("intake-instructions llm error (%s): %s", type(e).__name__, e)
        raise HTTPException(status_code=500, detail="assistant request failed")
    return InstructionsResponse(items=result.parsed.items, disclaimer=_DISCLAIMER)
