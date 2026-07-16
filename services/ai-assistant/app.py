"""ai-assistant — production LLM client wrapper (ADR 0004) + first feature
endpoint.

The wrapper (llm_client.py) and the PHI redaction helper (redaction.py) landed
first, with tests and guardrails, before any feature was built on them. The
previous contractor's ai-orchestrator service (removed pre-handoff) had none of
these guardrails — see adr/0004-ai-assistant-service-and-llm-wrapper.md.

POST /intake-instructions is the first feature endpoint: patient-friendly
visit-prep instructions assembled from a CLOSED-VOCABULARY request (see
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
import templates
from schemas import (
    InstructionsChecklist,
    InstructionsRequest,
    InstructionsResponse,
    log_metadata,
)

log = configure(settings.service_name)

app = FastAPI(title="Riverbend ai-assistant", version="0.2.0")

# Safety boundary is closed vocabulary on BOTH sides: the request is enum/bool
# only (schemas.py), and the response is template ids only (templates.py) —
# the model selects which fixed, pre-reviewed strings apply to the patient's
# administrative facts, and the server renders them. A prompt instruction is
# not an enforcement layer; this contract is: model free text can never reach
# a patient, because an unknown or out-of-contract selection falls back to the
# deterministic selection derived from the same facts (_select_items). The
# disclaimer is fixed text appended server-side, never model-generated.
_SYSTEM_PROMPT = (
    "You select visit-preparation checklist items for new patients of a "
    "community health clinic. You are given administrative facts about a "
    "completed intake and a catalog of checklist templates, each with an id. "
    "Respond with the ids of the 3 to 8 templates most relevant to the facts. "
    "Rules: use only ids that appear in the catalog; do not write checklist "
    "text yourself; every selection must be justified by an administrative "
    "fact provided."
)

_DISCLAIMER = (
    "These are general visit-preparation tips, not medical advice. "
    "For questions about your health or medications, contact your care team."
)


def _build_prompt(req: InstructionsRequest) -> str:
    """Render the closed request facts + template catalog as prompt lines.

    Input is enum/boolean only (schemas.InstructionsRequest), so every string
    interpolated here comes from THIS function, the PlanType enum, or the
    fixed catalog in templates.py — no client-controlled text ever enters the
    prompt.
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
    catalog = [f"- {key}: {text}" for key, text in templates.CATALOG.items()]
    return (
        "A new patient just completed self-service intake. Administrative facts:\n"
        + "\n".join(facts)
        + "\n\nTemplate catalog:\n"
        + "\n".join(catalog)
        + "\n\nSelect the template ids for their visit-preparation checklist."
    )


def _select_items(req: InstructionsRequest, selection: list[str]) -> list[str]:
    """Render the model's template selection, or the deterministic fallback.

    The selection is model output and therefore untrusted: any id outside the
    catalog, or a selection that leaves the 3-8 item contract after
    deduplication, discards the WHOLE selection in favor of the deterministic
    default for these request facts. Log lines carry indexes and counts only —
    an invalid "id" is model free text and must never reach a log record.
    """
    unknown = [i for i, key in enumerate(selection) if key not in templates.CATALOG]
    if unknown:
        log.warning(
            "intake-instructions selection gate: %d/%d ids not in catalog "
            "(indexes=%s); serving deterministic default selection",
            len(unknown),
            len(selection),
            unknown,
        )
        return templates.render(templates.default_selection(req))
    items = templates.render(selection)
    if not 3 <= len(items) <= 8:
        log.warning(
            "intake-instructions selection gate: %d ids deduplicated to %d "
            "items, outside the 3-8 contract; serving deterministic default "
            "selection",
            len(selection),
            len(items),
        )
        return templates.render(templates.default_selection(req))
    return items


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
    items = _select_items(req, result.parsed.items)
    return InstructionsResponse(items=items, disclaimer=_DISCLAIMER)
