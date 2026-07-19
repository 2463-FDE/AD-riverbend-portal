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
import secrets

from fastapi import Depends, FastAPI, HTTPException, Request
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
# not an enforcement layer; this contract is (_select_items): model free text
# can never reach a patient (an off-catalog id cannot render), and a factually
# wrong selection cannot either — the server derives the required/allowed id
# sets from the request facts itself, so the model's only real freedom is
# whether the neutral optional templates are included. Any violation falls
# back to the deterministic selection for the same facts. The disclaimer is
# fixed text appended server-side, never model-generated.
_SYSTEM_PROMPT = (
    "You select visit-preparation checklist items for new patients of a "
    "community health clinic. You are given administrative facts about a "
    "completed intake, the required checklist templates for those facts, and "
    "optional extra templates, each with an id. Respond with the chosen "
    "template ids. Rules: include every required id; add an optional id only "
    "when it makes the checklist more helpful; use only ids you were given; "
    "do not write checklist text yourself."
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
    required = templates.default_selection(req)
    required_lines = [f"- {key}: {templates.CATALOG[key]}" for key in required]
    optional_lines = [
        f"- {key}: {templates.CATALOG[key]}" for key in templates.OPTIONAL_IDS
    ]
    return (
        "A new patient just completed self-service intake. Administrative facts:\n"
        + "\n".join(facts)
        + "\n\nRequired templates (include every id):\n"
        + "\n".join(required_lines)
        + "\n\nOptional templates (add an id only when helpful):\n"
        + "\n".join(optional_lines)
        + "\n\nSelect the template ids for their visit-preparation checklist."
    )


def _select_items(req: InstructionsRequest, selection: list[str]) -> list[str]:
    """Render the model's template selection, or the deterministic fallback.

    The selection is model output and therefore untrusted, and catalog
    membership alone is not enough — a catalog id can be factually wrong for
    THIS patient (self_pay_options for an insured one). A selection renders
    only if it satisfies ``required <= selection <= allowed``, both sets
    derived server-side from the request facts; anything else — a stray id
    (off-catalog or fact-unjustified), a missing required id, or a count
    outside the 3-8 response contract — discards the WHOLE selection in favor
    of the deterministic default for these facts. Every violation recovers
    here (never as an error status): the wire schema is deliberately loose so
    a model formatting miss lands in this function, not in a 502
    (schemas.InstructionsChecklist). Log lines carry indexes and counts only —
    an invalid "id" is model free text and must never reach a log record.
    """
    required = set(templates.default_selection(req))
    allowed = templates.allowed_selection(req)
    stray = [i for i, key in enumerate(selection) if key not in allowed]
    missing = len(required - set(selection))
    if stray or missing:
        log.warning(
            "intake-instructions selection gate: %d/%d ids unjustified by "
            "request facts (indexes=%s), %d required ids missing; serving "
            "deterministic default selection",
            len(stray),
            len(selection),
            stray,
            missing,
        )
        return templates.render(required)
    items = templates.render(selection)
    if not 3 <= len(items) <= 8:
        # Unreachable while required <= selection <= allowed forces 4-8 items,
        # but the response contract is 3-8 — keep the belt independent of how
        # the sets evolve.
        log.warning(
            "intake-instructions selection gate: %d ids deduplicated to %d "
            "items, outside the 3-8 contract; serving deterministic default "
            "selection",
            len(selection),
            len(items),
        )
        return templates.render(required)
    return items


# Same sentinel class as llm_client._PLACEHOLDER_BEARER_TOKENS: a template
# value that survives `cp .env.example .env` must count as ABSENT, or the
# default deploy state walks past the guard (PR #5 round-5 lesson).
_PLACEHOLDER_SECRETS = frozenset(
    {"changeme", "change-me", "placeholder", "your-secret-here", "secret", "todo", "xxx"}
)


def _require_internal_auth(request: Request) -> None:
    """Service-to-service auth on the feature endpoint (Codex PR #7 round 3).

    Defense in depth behind the compose topology: ai-assistant is not
    host-published, but if that ever regresses, a direct caller still cannot
    reach the paid LLM path — only the gateway holds the shared secret it
    attaches as X-Internal-Auth. Fail-closed on configuration: an unset,
    blank, or placeholder secret refuses every call (503) rather than
    disabling the check. The provided header value is untrusted input and is
    never logged or echoed; comparison is constant-time.
    """
    secret = settings.ai_proxy_shared_secret.strip()
    if not secret or secret.lower() in _PLACEHOLDER_SECRETS:
        log.error(
            "intake-instructions refused: AI_PROXY_SHARED_SECRET is not configured"
        )
        raise HTTPException(status_code=503, detail="assistant is not configured")
    provided = request.headers.get("x-internal-auth", "")
    if not secrets.compare_digest(provided.encode(), secret.encode()):
        log.warning(
            "intake-instructions refused: internal auth header missing or invalid"
        )
        raise HTTPException(status_code=401, detail="not authorized")


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


@app.post(
    "/intake-instructions",
    response_model=InstructionsResponse,
    dependencies=[Depends(_require_internal_auth)],
)
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
        # POST-egress failure: throttle / upstream 5xx / connection error raised
        # AFTER the Bedrock call was attempted (llm_client._call retries, then
        # maps the botocore error here). 502 (bad gateway = the upstream provider
        # failed), deliberately NOT the 503 the pre-egress "not configured" cases
        # above use: the gateway refunds the aggregate spend budget on a
        # downstream 503/401/422 (proof no paid fan-out happened) but KEEPS the
        # charge on 502. If a provider outage surfaced as 503, every retry during
        # the outage would be refunded and the tenant ceiling would stop bounding
        # vendor fan-out (a retry storm would keep reaching Bedrock unmetered) —
        # Codex PR #7 round 9. See gateway _NON_PAID_DOWNSTREAM_STATUS, ADR 0007.
        log.error("intake-instructions provider unavailable: %s", e)
        raise HTTPException(status_code=502, detail="assistant is temporarily unavailable")
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
