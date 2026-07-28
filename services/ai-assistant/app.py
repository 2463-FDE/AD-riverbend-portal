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
from datetime import datetime, timezone
from typing import Any, NamedTuple

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
def _build_insurance_id_re(prefixes: tuple[str, ...]) -> "re.Pattern[str] | None":
    """Compile the catalog into a pattern, or return None for an EMPTY catalog.

    An empty catalog must mean "recognise nothing", never "recognise
    everything" (Codex PR #14 round 1). Joining zero prefixes yields
    ``\\b(?:)\\d{3,9}\\b`` — an empty alternation that matches ANY 3-9 digit
    token, so a DOB fragment, a ZIP, or a group number becomes the subject of a
    payer lookup, and a payer 404 renders that as a definitive "NO ACTIVE
    COVERAGE". The catalog's whole reason to exist is defeated by deleting its
    config value, which is exactly the state `AI_MEMBER_ID_PREFIXES=` leaves
    behind. None is the fail-closed direction: a MISS is safe, a WRONG MATCH is
    not. `_require_member_id_catalog` turns that state into a loud 503 so the
    misconfiguration surfaces as an outage rather than an endless "give me the
    member ID" loop.

    Each prefix is escaped because the catalog is operator input: an unescaped
    `.` or `|` would silently WIDEN the pattern (`A.C` matching `ABC1234`)
    instead of failing loudly.

    IGNORECASE because the input is a human typing, not a machine field (Codex
    PR #14 round 3). `config.py` upper-cases the catalog, so a case-sensitive
    pattern made `aetn1224` invisible — the clerk gets asked for the id they
    just supplied, and no lookup ever runs.

    ASCII is mandatory alongside it, and is NOT a style choice. On `str`
    patterns Python case-folds across the whole of Unicode, so bare IGNORECASE
    genuinely widens this catalog — verified against the shipped prefixes:
    `KAIſ1234` (U+017F LATIN SMALL LETTER LONG S) and `MEDı1234` (U+0131
    DOTLESS I) match, and `KAIK1234` (KELVIN SIGN) and `MEDİ1234` (U+0130)
    match while surviving `.upper()` as non-ASCII. Both directions break the
    fail-closed property this catalog exists for: a homoglyph folds to a
    DIFFERENT well-formed member id and gets looked up as though the clerk had
    typed it, and a non-ASCII id goes to the payer verbatim, where a 404 renders
    as a definitive "no active coverage" about a patient who has coverage. The
    `re.ASCII` flag also confines `\\d` to 0-9, closing a pre-existing hole where
    Arabic-Indic digits (`AETN١٢٣٤`) matched.

    With both flags the recognised token set really is the shipped prefixes and
    nothing else, case-folded. `_extract_insurance_ids` folds each match back to
    upper case so only one canonical form is ever stored or compared.
    """
    if not prefixes:
        return None
    return re.compile(
        r"\b(?:%s)\d{3,9}\b"
        % "|".join(re.escape(prefix) for prefix in sorted(prefixes, key=len, reverse=True)),
        re.IGNORECASE | re.ASCII,
    )


_INSURANCE_ID_RE = _build_insurance_id_re(settings.ai_member_id_prefixes)


def _require_member_id_catalog() -> None:
    """Refuse /visit-chat when the member-id catalog is empty.

    Fail-closed on configuration, the same shape as `_require_internal_auth`:
    with no catalog the turn can never recognise an id, so the endpoint cannot
    do the one job it exists for. 503 (and not a silent degrade) makes the
    misconfiguration visible, and 503 is the pre-egress status the gateway
    REFUNDS — a config mistake must not spend the LLM budget. Ordered after the
    auth dependency so an unauthenticated caller learns nothing about config.
    """
    if _INSURANCE_ID_RE is None:
        log.error("/visit-chat refused: AI_MEMBER_ID_PREFIXES is empty")
        raise HTTPException(status_code=503, detail="assistant is not configured")

# Deterministic intent keywords. Lowercased substring checks, not an LLM call:
# the message is PHI-bearing free text and must not reach the vendor while D13
# (no BAA) is open. Shallow by design — an unmatched turn degrades to `other`,
# which asks a clarifying question rather than guessing (ADR 0011 gap 3).
# An EXPLICIT retry verb, checked before the status words below. "what was the
# status again?" is a question about the past, not a request to re-spend a payer
# call — and during an outage a spurious re-check can flip a confirmed ACTIVE into
# "could not confirm", which is worse than answering from memory.
#
# Round 4 promoted this list from a convenience to a CONTROL. Before the per-visit
# freshness rule below, a message carrying a member id always re-checked, so a
# retry phrasing this list missed still got the clerk a fresh lookup. Now a missed
# phrasing is absorbed by the reuse window instead, and the clerk has no way to
# force a check — so the phrasings that put the id BETWEEN the verb and the adverb
# ("check AETN1224 again", "run that again") have to match too. Hence the pattern
# alongside the substrings; the substrings stay because they catch the
# no-verb-adverb forms ("recheck", "refresh").
_RETRY_WORDS = (
    "recheck", "re-check", "retry", "refresh", "check again", "run it again", "re-run", "rerun"
)
# The GAP IS BOUNDED, and that bound is the whole design (pre-push adversarial
# review, round 4). An unbounded `.*` between the verb and the adverb reads
# "can you check what her status was again?" — a question about the past — as a
# retry, and `\s` spans newlines, so in a pasted multi-line note any `run` on the
# first line pairs with any `again` thirty words later. That is not a cosmetic
# false positive: a spurious re-check during a payer outage replaces a confirmed
# ACTIVE with "could not confirm". Three intervening tokens covers the forms this
# has to catch ("check AETN1224 again", "run that again", "verify AETN1224 again
# please") and excludes the past-tense question, which then falls through to
# _STATUS_WORDS and is answered from memory.
#
# `try` is deliberately NOT one of the verbs: "she'll try again tomorrow" is not a
# request to spend a payer call. "retry" is still matched, as a substring above.
_RETRY_RE = re.compile(r"\b(?:check|run|verify)\b(?:\s+\S+){0,3}\s+again\b")
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

    An empty catalog (no compiled pattern) recognises nothing — see
    `_build_insurance_id_re`. Callers are protected from the state by
    `_require_member_id_catalog`; this branch is the belt to that braces, so no
    future caller can reach a "match anything" path.

    Matches are folded to UPPER CASE before de-duplication, not after, because
    the two rules downstream both key on distinctness: "AETN1224 — sorry,
    aetn1224" is one id typed twice, and counting it as two candidates would
    render the ambiguity question for a message that contains no ambiguity.

    The non-ASCII reject is belt to `re.ASCII`'s braces. The flag confines the
    `\\d` run and the word boundaries, but the PREFIX alternation is built from
    operator-supplied catalog values, so a non-ASCII prefix in
    `AI_MEMBER_ID_PREFIXES` would still match itself literally and could reach a
    payer as a member id `.upper()` cannot canonicalise. Dropping it here keeps
    "what can be looked up" ASCII regardless of how the catalog is configured —
    a miss is safe, a wrong match is not.
    """
    if _INSURANCE_ID_RE is None:
        return []
    seen: list[str] = []
    for match in _INSURANCE_ID_RE.finditer(message or ""):
        candidate = match.group(0).upper()
        if not candidate.isascii():
            log.warning("visit-chat: dropped a non-ASCII member-id candidate")
            continue
        if candidate not in seen:
            seen.append(candidate)
    return seen


def _verdict_is_definitive(verdict: dict[str, Any] | None) -> bool:
    """Does this dict carry a real payer verdict (`active` / `inactive`)?

    `facts.last_eligibility` is an open dict on the wire (schemas.VisitFacts keeps
    it open deliberately, so a projection change cannot 422 a live visit), so it is
    treated here as untrusted input rather than as something this service is sure
    it wrote:

      * definitiveness is read from `active` being exactly True or False — never
        truthiness, since None is falsy and means unknown — AND cross-checked
        against `status`. `{"status": "active", "active": null}` is the r5
        covered-by-mistake defect arriving through the facts door rather than off
        the wire, and it is not a verdict.
      * a degraded `unknown`/`pending` is not definitive, which is what keeps ADR
        0011 gap 7's decision intact wherever this predicate is consulted: an
        unconfirmed check is reported as unconfirmed and re-attempted, never served
        in place of a real attempt.
    """
    if not isinstance(verdict, dict):
        return False
    active = verdict.get("active")
    if not (active is True or active is False):
        return False
    return verdict.get("status") == ("active" if active else "inactive")


def _verdict_is_reusable(verdict: dict[str, Any] | None) -> bool:
    """Can a verdict this visit already holds answer a repeat of its own id?

    True only for a DEFINITIVE verdict that THIS service observed inside
    `settings.ai_eligibility_reuse_seconds`. Every other shape is False, because
    the two errors are not symmetric: a wrong False costs one payer call, and a
    wrong True hands a clerk a coverage fact that may no longer hold.

    On top of `_verdict_is_definitive`:

      * `observed_at` must be present, a string, ISO-parseable, and TIMEZONE-AWARE
        (`eligibility_client._observed_now` always writes one; a naive stamp did
        not come from there, and assuming an offset for it can be hours wrong in
        the direction the window exists to bound).
      * a stamp in the FUTURE is not freshness, it is an unusable clock or a
        crafted value, so the age has to be non-negative to count.

    A zero window disables reuse entirely — see config.py on why 0 is the
    strictest setting for this knob and not the trap it is for the breaker ones.
    """
    window = settings.ai_eligibility_reuse_seconds
    if window <= 0 or not _verdict_is_definitive(verdict):
        return False
    observed_at = verdict.get("observed_at")
    if not isinstance(observed_at, str):
        return False
    try:
        observed = datetime.fromisoformat(observed_at)
    except ValueError:
        return False
    if observed.tzinfo is None:
        return False
    age_seconds = (datetime.now(timezone.utc) - observed).total_seconds()
    return 0 <= age_seconds < window


def _remembered_verdict(
    stored: dict[str, Any] | None, fresh: dict[str, Any]
) -> dict[str, Any]:
    """Which verdict the VISIT keeps after an attempt — not what this turn reports.

    A failed re-check does not un-observe a payer's definitive answer, and
    `facts.last_eligibility` is the only place that answer exists: the gateway
    persists exactly what comes back from here. Overwriting it unconditionally
    destroyed a confirmed verdict permanently (pre-push adversarial review, round
    4). The trace: a definitive ACTIVE is stored, the payer degrades, one re-check
    returns `pending`, and from then on the visit has no verdict at all — the
    reply flips to "could not confirm" for a patient the payer confirmed, and every
    later turn re-pays for a lookup that cannot succeed while the circuit is open.

    So a DEGRADED result never replaces a DEFINITIVE one for the same subject. This
    turn still reports the degraded outcome — the caller renders `verdict`, the
    fresh dict — so nothing restates the old answer as current (ADR 0011 §5, gap 7).
    What survives is the visit's memory of the last real observation, carrying its
    own `checked_at`/`observed_at`, which is exactly what makes it visibly past.

    `stored` must be the verdict for the SAME member id; the caller passes None when
    the id changed this turn, since a verdict for another subject is not a memory
    worth keeping.
    """
    if _verdict_is_definitive(stored) and not _verdict_is_definitive(fresh):
        return stored
    return fresh


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

    A candidate that MATCHES the visit's confirmed id is a REPEAT, and a repeat
    does not automatically buy another payer call (Codex PR #14 round 4). Clerks
    restate and re-paste the id constantly, and each repeat used to spend another
    PHI-bearing lookup while the answer sat in `last_eligibility`.

    A repeat runs the SAME keyword ladder as a turn with no id in it — retry, then
    question-about-the-past, then request-a-check — so repeating the id cannot
    change what a turn MEANS (pre-push adversarial review, round 4). Freshness
    decides only the turn the ladder does not classify: the bare restatement
    ("member AETN1224"), which is answered from memory while the visit holds a
    reusable verdict for that id.

    Two orderings inside that ladder are load-bearing:

      * an explicit retry ("recheck AETN1224") outranks everything, because it asks
        for a NEW observation rather than about the old one;
      * a question about the past ("what did AETN1224 come back as?") outranks the
        check verbs, because `_STATUS_WORDS` and `_CHECK_WORDS` overlap on "active"
        and a question must not spend a payer call. Reversing these two turns
        "is AETN1224 still active?" into a lookup.

    An imperative check verb ("verify AETN1224", "coverage changed — check
    AETN1224") is honoured against a fresh verdict, which is the one place this
    deliberately spends over saving: freshness must not become a cache the clerk
    cannot get past, and a clerk asking for a check has a reason we cannot see (a
    new card for the same member id being the concrete one). The saving comes from
    the bare repeat, which is what "restate or re-paste the id" actually looks like.
    """
    candidates = _extract_insurance_ids(message)
    stored = facts.insurance_id
    lowered = (message or "").lower()
    wants_retry = any(word in lowered for word in _RETRY_WORDS) or bool(_RETRY_RE.search(lowered))
    asks_status = any(word in lowered for word in _STATUS_WORDS)
    wants_check = any(word in lowered for word in _CHECK_WORDS)
    if len(candidates) > 1:
        return VisitIntent.clarify_member_id, None
    if candidates:
        if stored and candidates[0] != stored:
            return VisitIntent.clarify_member_id, None
        if stored:
            if wants_retry:
                return VisitIntent.recheck_eligibility, candidates[0]
            if asks_status:
                # A question about the past, answered from stored facts. No egress,
                # whatever the stored verdict says — including a degraded one, which
                # renders as the failed check it was.
                return VisitIntent.ask_status, None
            if not wants_check and _verdict_is_reusable(facts.last_eligibility):
                # The bare repeat: same subject, an answer already paid for, still
                # fresh. No egress.
                return VisitIntent.ask_status, None
        return VisitIntent.check_eligibility, candidates[0]

    has_id_on_file = bool(stored)
    if has_id_on_file and wants_retry:
        return VisitIntent.recheck_eligibility, None
    if has_id_on_file and asks_status:
        # Answered from stored facts — no payer call, no spend.
        return VisitIntent.ask_status, None
    if wants_check:
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


class _ReplyPlan(NamedTuple):
    """What the action-selection step produced, plus the two facts about HOW.

    ``llm_egress`` is spend accounting (did a request cross the vendor
    boundary). ``degraded`` is service health (did the clerk get the model's
    selection or the deterministic fallback). They are genuinely independent —
    a post-egress failure is billable and degraded; a local refusal is neither
    — so one boolean cannot carry both, and collapsing them is how a
    misconfiguration becomes invisible.
    """

    items: list[str]
    llm_egress: bool
    degraded: bool


def _reply_items(intent: VisitIntent, status: str, turn_count: int) -> _ReplyPlan:
    """Ask the model to choose follow-up actions; degrade deterministically.

    **No LLM failure of any kind fails this
    turn** (Codex PR #14 round 3): action selection is the LAST and least
    important step, and by the time it runs the payer lookup has already
    happened and mutated the visit's facts. Raising here threw that work away —
    the clerk lost a coverage verdict that had been computed and paid for, the
    gateway never persisted the visit, and each retry re-ran a PHI-bearing payer
    call for no user-visible value. Every branch below now renders the
    deterministic default selection instead, so the only thing an LLM fault can
    cost is the *quality* of the follow-up list.

    What the branches still differ on is SPEND, which is why the flag exists.
    The old mapping encoded that in the HTTP status because the gateway's refund
    rule keys on it (ADR 0007); a turn that succeeds without egress cannot say
    that with a status code, so it says it with ``llm_egress`` and the gateway
    refunds on the boolean (ADR 0011 §7).

    ONE catch, and the spend answer is read off the exception rather than
    inferred from its type. Splitting by type here was wrong and shipped briefly
    in this PR: `LLMConfigError` is raised both by the local pricing/token gates
    AND by Bedrock's own `ClientError` rejection, so "config error" says nothing
    about whether a request crossed the boundary. `llm_client.LLMError.egressed`
    is set at each raise site, defaulting to True, so an unclassified or future
    failure keeps the charge. `getattr` rather than attribute access because a
    caller must not be broken by an exception raised from somewhere that predates
    the attribute.

    The model is also not consulted when the status leaves it nothing to decide
    — see the short-circuit below.
    """
    required = visit_templates.default_selection(status)
    allowed = visit_templates.allowed_selection(status)
    if not allowed - set(required):
        # Nothing to decide, so nothing to buy (Codex PR #14 round 5). For the
        # no-lookup statuses `allowed_selection` collapses onto the required
        # core, so the ONLY selection the gate downstream would accept is the one
        # rendered here: a model call could change this reply by exactly zero
        # while costing a real Bedrock request. Those are also the cheapest turns
        # to provoke — a message with no member id in it, repeatable by anyone
        # holding a never-expiring session (CLAUDE.md §6) — so the waste is
        # drainable by one clerk.
        #
        # What this does NOT save is the gateway's ADR 0007 admission slot: the
        # reservation is taken before the fan-out, and the gateway cannot know
        # the turn is free until this function has answered. The slot is
        # reserved and refunded, so a no-lookup turn still consumes admission
        # while it is in flight and is still refused once the ceiling is
        # exhausted (ADR 0011, round 5 gap).
        #
        # Derived from the two sets rather than tested against
        # NO_LOOKUP_STATUSES: the property that matters is "the model has no
        # freedom", and a future status whose optional ids are narrowed away
        # then inherits the short-circuit instead of quietly paying for it.
        #
        # Not `degraded`: this is the designed path for these statuses, not a
        # fallback from a fault, and health must keep meaning health (ADR 0011
        # §7). `llm_egress=False` is what makes the gateway refund the slot it
        # reserved before the call it turns out we never made.
        #
        # Logged, because this is now the most common reason the shared counter
        # is charged and immediately credited back, and an accounting path with
        # no signal is one a double-refund can quietly drift through: nothing
        # else in either service records that a 200 skipped the vendor. Both
        # values are closed vocabulary, same allowlist discipline as the request
        # line above.
        log.info(
            "visit-chat answered with no model call: %s",
            json.dumps({"eligibility_status": status, "model_consulted": False}),
        )
        return _ReplyPlan(visit_templates.render(required), False, False)
    try:
        result = llm_client.complete_structured(
            prompt=_build_visit_prompt(intent, status, turn_count, required, allowed),
            output_model=VisitReplyPlan,
            system=_VISIT_SYSTEM_PROMPT,
        )
    except llm_client.LLMError as e:
        egressed = getattr(e, "egressed", True)
        log.error(
            "visit-chat degrading to deterministic reply (%s, egressed=%s): %s",
            type(e).__name__,
            egressed,
            e,
        )
        return _ReplyPlan(visit_templates.render(required), egressed, True)
    return _ReplyPlan(_select_reply_items(status, result.parsed.template_ids), True, False)


@app.post(
    "/visit-chat",
    response_model=VisitChatResponse,
    dependencies=[Depends(_require_internal_auth), Depends(_require_member_id_catalog)],
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
    checked_this_turn = False
    if intent in (VisitIntent.check_eligibility, VisitIntent.recheck_eligibility) and facts.insurance_id:
        # Deterministic act step: the decision to make an outbound PHI-bearing
        # call is never a function of model output or of what the free text told
        # the model to do. Bounded and breakered (eligibility_client).
        checked_this_turn = True
        verdict = eligibility_client.check_coverage(facts.insurance_id)
        facts.last_eligibility = _remembered_verdict(
            facts.last_eligibility if req.facts.insurance_id == facts.insurance_id else None,
            verdict,
        )

    status = (verdict or {}).get("status") or visit_templates.AWAITING_ID
    if not facts.insurance_id:
        status = visit_templates.AWAITING_ID
    if intent is VisitIntent.clarify_member_id:
        # Two ids in play, or one that contradicts the visit's confirmed id. The
        # stored verdict describes a DIFFERENT subject, so rendering it here would
        # answer a question nobody asked; say plainly that nothing ran.
        status = visit_templates.AMBIGUOUS_ID

    # Allowlisted, non-PHI projection only — never the message, the transcript, or
    # the id (D1 lesson, docs/phi-logging-policy.md). `checked` is the turn's
    # EGRESS fact, and it is here because `intent` no longer implies it: `ask_status`
    # now covers both "answered a status question" and "declined to re-verify an id
    # the clerk re-presented, because the stored verdict was still fresh". Without
    # it, nobody reviewing why a clerk recorded ACTIVE can tell whether a payer was
    # asked on that turn (adversarial review, round 4; D2/D12 are open).
    log.info(
        "POST /visit-chat meta=%s",
        json.dumps(
            visit_chat_log_metadata(intent, status, len(req.turns), checked=checked_this_turn)
        ),
    )

    plan = _reply_items(intent, status, len(req.turns))
    reply = "\n".join(
        [visit_templates.verdict_line(status, verdict)] + [f"- {item}" for item in plan.items]
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
        # The turn's spend verdict, not the turn's outcome: False means nothing
        # crossed the vendor boundary, so the gateway must give the reserved slot
        # back (ADR 0011 §7).
        llm_egress=plan.llm_egress,
        # The turn's health, which the status code no longer carries.
        assistant="degraded" if plan.degraded else "ok",
    )
