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

POST /visit-chat is the second (ADR 0011): the front-desk eligibility assistant.
It accepts free text — the one such surface in this service — but the vendor
boundary stays closed, because intent derivation and the eligibility lookup are
deterministic and the LLM sees only closed vocabulary. See the schemas.py module
docstring for the full argument and the obligations it created.
"""
import json
import re
import secrets

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from config import settings
from logging_config import configure
import eligibility_client
import llm_client
import templates
import visit_templates
from schemas import (
    InstructionsChecklist,
    InstructionsRequest,
    InstructionsResponse,
    VisitChatRequest,
    VisitChatResponse,
    VisitFacts,
    VisitIntent,
    VisitReplyPlan,
    log_metadata,
    visit_chat_log_metadata,
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
            "%s refused: AI_PROXY_SHARED_SECRET is not configured",
            request.url.path,
        )
        raise HTTPException(status_code=503, detail="assistant is not configured")
    provided = request.headers.get("x-internal-auth", "")
    if not secrets.compare_digest(provided.encode(), secret.encode()):
        log.warning(
            "%s refused: internal auth header missing or invalid", request.url.path
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
    except llm_client.LLMBudgetExceeded as e:
        # PRE-egress: llm_client enforces the token / char / cost caps LOCALLY,
        # before any Bedrock call (_enforce_char_cap and _enforce_budget run
        # ahead of _call's try). For this closed-vocabulary endpoint the prompt is
        # fixed-size and small, so tripping a cap means the caps are misconfigured
        # too low — a configuration problem, and no paid call was made. Return a
        # 503 (a pre-egress status the gateway REFUNDS), never the generic 500:
        # 500 keeps the charge, so a low-cap misconfig would otherwise burn the
        # gateway's shared daily spend ceiling on every request that never reached
        # Bedrock and 429 all users (Codex PR #7 round 10). Must precede the
        # LLMError catch — LLMBudgetExceeded subclasses it. See gateway
        # _NON_PAID_DOWNSTREAM_STATUS and ADR 0007.
        log.error("intake-instructions local budget refusal: %s", e)
        raise HTTPException(status_code=503, detail="assistant is not configured")
    except llm_client.LLMError as e:
        # Any other unexpected LLM error. 500 keeps the charge: this branch is not
        # a proven pre-egress refusal, so the gateway must not refund the slot.
        log.error("intake-instructions llm error (%s): %s", type(e).__name__, e)
        raise HTTPException(status_code=500, detail="assistant request failed")
    items = _select_items(req, result.parsed.items)
    return InstructionsResponse(items=items, disclaimer=_DISCLAIMER)


# --------------------------------------------------------------------------- #
# visit-chat — the front-desk eligibility assistant (ADR 0011)
# --------------------------------------------------------------------------- #
_VISIT_SYSTEM_PROMPT = (
    "You choose which follow-up actions a front-desk clerk should see alongside "
    "an insurance eligibility result that has ALREADY been decided. You are given "
    "the situation as fixed labels, the required action ids for that situation, "
    "and optional extra ids. Respond with the chosen ids. Rules: include every "
    "required id; add an optional id only when it is genuinely useful; use only "
    "ids you were given; never write action text yourself; never state or revise "
    "the coverage result."
)

_VISIT_DISCLAIMER = (
    "Coverage information comes from the payer's eligibility response and can be "
    "out of date or incomplete. It is not a guarantee of payment, and it is not "
    "medical advice."
)

# Member-id recognition is a CLOSED PREFIX CATALOG (settings.ai_member_id_prefixes),
# never a generic letters-then-digits pattern. See config.py for why: a false
# positive is NOT safe. eligibility-service maps a payer 404 to a definitive
# {"active": false}, so a mis-extracted token produces a confident "NO ACTIVE
# COVERAGE" about the wrong subject — the patient-turned-away failure this whole
# workstream exists to prevent. A MISS is safe (the reply asks for the id); a
# WRONG MATCH is not, so the pattern only recognises ids it can attribute to a
# known payer. Longest-first alternation so AETNA1224 is not truncated to AETN.
_INSURANCE_ID_RE = re.compile(
    r"\b(?:%s)\d{3,9}\b"
    % "|".join(sorted(settings.ai_member_id_prefixes, key=len, reverse=True))
)

# Deterministic intent keywords. Lowercased substring checks, not an LLM call:
# the message is PHI-bearing free text and must not reach the vendor while D13
# (no BAA) is open. Shallow by design — an unmatched turn degrades to `other`,
# which asks a clarifying question rather than guessing (ADR 0011 gap 3).
# An EXPLICIT retry verb, checked before the status words below. "what was the
# status again?" is a question about the past, not a request to re-spend a payer
# call — and during an outage a spurious re-check can flip a confirmed ACTIVE into
# "could not confirm", which is worse than answering from memory.
_RETRY_WORDS = ("recheck", "re-check", "retry", "refresh", "check again", "run it again")
_STATUS_WORDS = (
    "still", "status", "what did", "what was", "current", "confirmed", "active", "again"
)
_CHECK_WORDS = ("check", "eligib", "coverage", "covered", "insurance", "verify", "active")


def _extract_insurance_ids(message: str) -> list[str]:
    """Every DISTINCT member id in the message, in order of appearance.

    Deliberately not ``search`` (first-match-wins). A clerk reading off a card
    types several id-shaped tokens, and silently picking the leftmost is how a
    group or prior-auth number becomes the subject of a coverage verdict. The
    caller treats more than one candidate as ambiguity to resolve with the human,
    never as a guess to act on.
    """
    seen: list[str] = []
    for match in _INSURANCE_ID_RE.finditer(message or ""):
        if match.group(0) not in seen:
            seen.append(match.group(0))
    return seen


def _derive_intent(message: str, facts: VisitFacts) -> tuple[VisitIntent, str | None]:
    """Classify the turn and extract a member id, deterministically.

    Returns (intent, insurance_id_to_use). No model call, so no free text leaves
    the process for this step — that is the whole point (ADR 0011 §2).

    An id in the message is the strongest signal there is, but only when it is
    UNAMBIGUOUS. Two rules keep a wrong id from ever reaching the payer:

      * more than one distinct candidate in one message → ambiguous, ask;
      * a single candidate that CONTRADICTS the id already confirmed for this
        visit → ambiguous, ask. Silently switching subjects mid-visit would
        re-attribute every later turn to the new id.

    Both degrade to `other` with no id, which renders the "which member id?"
    reply — the safe direction, since the cost is one extra question and the
    alternative is a confident answer about the wrong patient.
    """
    candidates = _extract_insurance_ids(message)
    stored = facts.insurance_id
    if len(candidates) > 1:
        return VisitIntent.clarify_member_id, None
    if candidates:
        if stored and candidates[0] != stored:
            return VisitIntent.clarify_member_id, None
        return VisitIntent.check_eligibility, candidates[0]

    lowered = (message or "").lower()
    has_id_on_file = bool(stored)
    if has_id_on_file and any(word in lowered for word in _RETRY_WORDS):
        return VisitIntent.recheck_eligibility, None
    if has_id_on_file and any(word in lowered for word in _STATUS_WORDS):
        # Answered from stored facts — no payer call, no spend.
        return VisitIntent.ask_status, None
    if any(word in lowered for word in _CHECK_WORDS):
        # Wants a check but we have no id to run one with — the reply asks for it.
        return VisitIntent.check_eligibility, None
    return VisitIntent.other, None


def _build_visit_prompt(
    intent: VisitIntent, status: str, turn_count: int, required: list[str], allowed: set[str]
) -> str:
    """Render the CLOSED situation labels + candidate ids as prompt lines.

    Every interpolated value is closed vocabulary: an enum value, a status string
    this service derived from the ADR 0010 contract, an integer, and catalog keys
    with their fixed catalog text. The clerk's message is deliberately absent —
    it is PHI-bearing free text and never crosses the vendor boundary.
    """
    optional = [key for key in visit_templates.OPTIONAL_IDS if key in allowed]
    required_lines = [f"- {key}: {visit_templates.CATALOG[key]}" for key in required]
    optional_lines = [f"- {key}: {visit_templates.CATALOG[key]}" for key in optional]
    return (
        "A front-desk clerk is working through a patient's insurance eligibility "
        "during check-in. Situation:\n"
        f"- what the clerk's latest turn is asking for: {intent.value}\n"
        f"- eligibility result already determined: {status}\n"
        f"- turns so far in this visit: {turn_count}\n"
        "\nRequired action ids (include every id):\n"
        + "\n".join(required_lines)
        + "\n\nOptional action ids (add one only when genuinely useful):\n"
        + ("\n".join(optional_lines) if optional_lines else "- (none)")
        + "\n\nSelect the action ids to show the clerk."
    )


def _select_reply_items(status: str, selection: list[str]) -> list[str]:
    """Render the model's action selection, or the deterministic fallback.

    Identical contract to _select_items: the selection is untrusted model output,
    and catalog membership alone is not enough — `self_pay_options` is a real
    catalog id and the wrong thing to say after a check that FAILED rather than
    came back inactive. A selection renders only if it satisfies
    ``required <= selection <= allowed``, both derived server-side from the
    status; anything else discards the whole selection for the default. Log lines
    carry indexes and counts only — an invalid "id" is model free text and must
    never reach a log record.
    """
    required = set(visit_templates.default_selection(status))
    allowed = visit_templates.allowed_selection(status)
    stray = [i for i, key in enumerate(selection) if key not in allowed]
    missing = len(required - set(selection))
    if stray or missing:
        log.warning(
            "visit-chat selection gate: %d/%d ids unjustified by the eligibility "
            "status (indexes=%s), %d required ids missing; serving deterministic "
            "default selection",
            len(stray),
            len(selection),
            stray,
            missing,
        )
        return visit_templates.render(required)
    items = visit_templates.render(selection)
    if not visit_templates.MIN_ITEMS <= len(items) <= visit_templates.MAX_ITEMS:
        # Unreachable while required <= selection <= allowed forces 1-4 items for
        # every status, but kept as a belt independent of how the sets evolve —
        # same role as the 3-8 check in _select_items.
        log.warning(
            "visit-chat selection gate: %d ids deduplicated to %d items, outside "
            "the %d-%d contract; serving deterministic default selection",
            len(selection),
            len(items),
            visit_templates.MIN_ITEMS,
            visit_templates.MAX_ITEMS,
        )
        return visit_templates.render(required)
    return items


def _reply_items(intent: VisitIntent, status: str, turn_count: int) -> list[str]:
    """Ask the model to choose follow-up actions; degrade deterministically.

    Error mapping deliberately splits on EGRESS, matching the gateway's refund
    rule (ADR 0007, ADR 0011 §7):

      * PRE-egress refusals (`LLMConfigError`, `LLMBudgetExceeded` — the caps are
        enforced locally before any Bedrock call) raise 503, a status the gateway
        REFUNDS, because no paid call happened.
      * POST-egress failures (`LLMUnavailable`, `LLMResponseError`) do NOT fail the
        turn. The coverage verdict was computed before this call and does not
        depend on it, so the clerk still gets the answer they need with the
        deterministic action list. Returning 200 keeps the spend charge, exactly as
        the 502 /intake-instructions returns would — the accounting is unchanged,
        only the user experience differs. This divergence is deliberate and is
        recorded in ADR 0011 §7.
      * anything else is not a proven pre-egress refusal, so it must not be
        refunded: 500, keeping the charge.
    """
    required = visit_templates.default_selection(status)
    allowed = visit_templates.allowed_selection(status)
    try:
        result = llm_client.complete_structured(
            prompt=_build_visit_prompt(intent, status, turn_count, required, allowed),
            output_model=VisitReplyPlan,
            system=_VISIT_SYSTEM_PROMPT,
        )
    except llm_client.LLMConfigError as e:
        log.error("visit-chat config error: %s", e)
        raise HTTPException(status_code=503, detail="assistant is not configured")
    except llm_client.LLMBudgetExceeded as e:
        # Must precede the LLMError catch — LLMBudgetExceeded subclasses it.
        log.error("visit-chat local budget refusal: %s", e)
        raise HTTPException(status_code=503, detail="assistant is not configured")
    except (llm_client.LLMUnavailable, llm_client.LLMResponseError) as e:
        log.error("visit-chat degrading to deterministic reply (%s): %s", type(e).__name__, e)
        return visit_templates.render(required)
    except llm_client.LLMError as e:
        log.error("visit-chat llm error (%s): %s", type(e).__name__, e)
        raise HTTPException(status_code=500, detail="assistant request failed")
    return _select_reply_items(status, result.parsed.template_ids)


@app.post(
    "/visit-chat",
    response_model=VisitChatResponse,
    dependencies=[Depends(_require_internal_auth)],
)
def visit_chat(req: VisitChatRequest):
    """One turn of the front-desk eligibility conversation.

    Stateless: the caller (the gateway) owns visit memory and passes the visit's
    turns and facts in, and gets the updated facts back. No `visit_id` crosses
    this boundary, so the key that addresses a patient's visit memory cannot
    appear in an ai-assistant log line.

    Order is understand -> act -> ground -> phrase, and the first three steps are
    deterministic. The model is consulted last, about follow-up actions only, and
    never about whether the patient has coverage.
    """
    intent, found_id = _derive_intent(req.message, req.facts)

    facts = req.facts.model_copy(deep=True)
    if found_id:
        facts.insurance_id = found_id

    verdict = facts.last_eligibility
    if intent in (VisitIntent.check_eligibility, VisitIntent.recheck_eligibility) and facts.insurance_id:
        # Deterministic act step: the decision to make an outbound PHI-bearing
        # call is never a function of model output or of what the free text told
        # the model to do. Bounded and breakered (eligibility_client).
        verdict = eligibility_client.check_coverage(facts.insurance_id)
        facts.last_eligibility = verdict

    status = (verdict or {}).get("status") or visit_templates.AWAITING_ID
    if not facts.insurance_id:
        status = visit_templates.AWAITING_ID
    if intent is VisitIntent.clarify_member_id:
        # Two ids in play, or one that contradicts the visit's confirmed id. The
        # stored verdict describes a DIFFERENT subject, so rendering it here would
        # answer a question nobody asked; say plainly that nothing ran.
        status = visit_templates.AMBIGUOUS_ID

    # Allowlisted, non-PHI projection only — never the message, the transcript, or
    # the id (D1 lesson, docs/phi-logging-policy.md).
    log.info(
        "POST /visit-chat meta=%s",
        json.dumps(visit_chat_log_metadata(intent, status, len(req.turns))),
    )

    items = _reply_items(intent, status, len(req.turns))
    reply = "\n".join(
        [visit_templates.verdict_line(status, verdict)] + [f"- {item}" for item in items]
    )
    # No lookup ran this turn (no id yet, or an ambiguous one), so this turn has
    # no eligibility result to report — even when the visit holds an earlier one.
    # `facts.last_eligibility` still carries it for the next turn that asks.
    turn_verdict = None if status in visit_templates.NO_LOOKUP_STATUSES else verdict
    return VisitChatResponse(
        reply=reply,
        # Echoed so the caller can record a metadata-only turn without ever
        # touching the clerk's text again (schemas.VisitTurn).
        intent=intent,
        status=status,
        facts=facts,
        eligibility=turn_verdict,
        disclaimer=_VISIT_DISCLAIMER,
    )
