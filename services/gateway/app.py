"""
gateway — backend-for-frontend / API gateway.

The Next.js portal talks only to this service; it fans out to the internal
FastAPI services and owns login/sessions.

Inherited shortcomings (left as-is from the handoff):
  * Records fan-out forwards the caller's session but never binds it to the
    {patient_id} being requested — any logged-in user can read any chart (IDOR).
  * Sessions never expire (see security.create_session / auth.yaml).
  * One role for everyone; no per-action authorization beyond "is logged in".
"""
import re
import time
from enum import Enum
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from config import settings
from db import get_db
from logging_config import configure
from models import User
from security import (
    RedisUnauthenticated,
    RedisUnreachable,
    VisitLockUnavailable,
    VisitMemoryUnavailable,
    ai_cache_get,
    ai_cache_key,
    ai_cache_set,
    ai_singleflight_acquire,
    ai_singleflight_release,
    check_ai_rate_limit,
    check_redis_usable,
    consume_ai_global_budget,
    create_session,
    destroy_session,
    get_session,
    new_visit_id,
    release_ai_global_budget,
    verify_password,
    visit_lock_acquire,
    visit_lock_release,
    visit_memory_get,
    visit_memory_save,
)

log = configure(settings.service_name)
app = FastAPI(title="Riverbend gateway", version="1.4.0")


@app.exception_handler(RequestValidationError)
async def validation_error_no_echo(request: Request, exc: RequestValidationError):
    """422 without echoing the rejected input back (mirrors ai-assistant's handler).

    FastAPI's default validation response includes an ``input`` key carrying the
    offending value verbatim. The per-route validators (_validate_ai_request,
    _validate_visit_chat_request) already return a no-echo 422 — but only for
    bodies that REACH them. Routes typed ``payload: dict`` fail FastAPI's own body
    coercion first, so a body that parses as JSON but is not an object (a bare
    string, a list) never gets that far and is served by the default handler.

    That gap was found by the pre-push security review of the visit-chat work. On
    /ai/visit-chat the body is free text a clerk typed, and on /login it is a
    credential — neither should come back in an error payload, even to the sender.
    Registered app-wide rather than per route: every ``payload: dict`` endpoint
    here (/intake, /appointments, /roi/requests, /hl7/ingest, both /ai routes) has
    the same shape. Nothing is logged — a rejected body must not reach a log
    record either.
    """
    errors = [
        {"loc": e.get("loc", ()), "type": e.get("type", ""), "msg": e.get("msg", "")}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})

SERVICES = {
    "intake": settings.intake_url,
    "eligibility": settings.eligibility_url,
    "records": settings.records_url,
    "scheduling": settings.scheduling_url,
    "interop": settings.interop_url,
    "roi": settings.roi_url,
    "ai": settings.ai_assistant_url,
}


# --------------------------------------------------------------------------- #
# auth
# --------------------------------------------------------------------------- #
class LoginRequest(BaseModel):
    username: str
    password: str


def _bearer(authorization: Optional[str]) -> str:
    if not authorization:
        return ""
    return authorization[7:] if authorization.lower().startswith("bearer ") else authorization


def require_session(authorization: Optional[str] = Header(default=None)) -> dict:
    """Reject anonymous callers. (Does NOT scope access to a patient — see IDOR.)"""
    sess = get_session(_bearer(authorization))
    if not sess:
        raise HTTPException(status_code=401, detail="not authenticated")
    return sess


@app.exception_handler(RedisUnauthenticated)
async def redis_unauthenticated(request: Request, exc: RedisUnauthenticated):
    """A refused session store is a 503, not a 500 (Codex PR #14 round 1).

    security._redis() refuses to speak to an unauthenticated Redis, so every
    session read/write raises. Unhandled, that surfaced as a 500 with a
    traceback, while the identical class of failure on the DB side (login's
    handler) already answers 503 "auth backend unavailable". Same shape here so
    a misconfigured deploy reads as a dependency outage rather than a bug, and
    the detail stays generic — the message names the env var, and that belongs
    in the log, not in a client response.
    """
    log.error("session store refused: %s", exc)
    return JSONResponse(status_code=503, content={"detail": "auth backend unavailable"})


@app.get("/healthz")
def healthz():
    """Liveness + "can this instance actually serve".

    The Redis check is a real authenticated PING, bounded by
    REDIS_PROBE_TIMEOUT_SECONDS (Codex PR #14 round 2). Round 1 shipped a
    config-only probe that built the client and sent no command, on the argument
    that a command could flap on a Redis blip. It could not flap, but it also
    could not see a wrong password, a store that died after boot, or a stale
    client — all of which return 200 here while every session-backed route
    fails, which is the exact green-dashboard-dead-service failure this endpoint
    was added to prevent. An accurate red beats a stable lie: nothing in the
    topology drains or restarts on this signal, and the next poll clears it.

    Both failures answer 503 and differ only in the log line: a missing
    credential is a deploy that was never configured, an unanswered PING is a
    dependency that is down or rejecting us.
    """
    try:
        check_redis_usable()
    except RedisUnauthenticated as e:
        log.error("healthz: session store refused: %s", e)
        raise HTTPException(status_code=503, detail="session store not configured")
    except RedisUnreachable as e:
        log.error("healthz: session store did not answer: %s", e)
        raise HTTPException(status_code=503, detail="session store unavailable")
    return {"status": "ok", "service": settings.service_name}


@app.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """
    Issue a session token. Password only (no MFA), and the token never expires
    (no TTL on the Redis key) — see auth.yaml.
    """
    try:
        user = db.execute(select(User).where(User.username == req.username)).scalar_one_or_none()
    except Exception as e:  # DB down in local dev without compose
        log.error("login db error: %s", e)
        raise HTTPException(status_code=503, detail="auth backend unavailable")

    if not user or not user.is_active or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid username or password")

    user.last_login_at = func.now()
    db.commit()
    token = create_session(user.username, user.role)
    log.info("login ok user=%s", user.username)
    return {
        "token": token,
        "mfa": False,
        "user": {"username": user.username, "full_name": user.full_name, "role": user.role},
    }


@app.post("/logout")
def logout(authorization: Optional[str] = Header(default=None)):
    destroy_session(_bearer(authorization))
    return {"status": "ok"}


@app.get("/me")
def me(session: dict = Depends(require_session)):
    return {"username": session.get("username"), "role": session.get("role")}


# --------------------------------------------------------------------------- #
# intake / eligibility
# --------------------------------------------------------------------------- #
@app.post("/intake")
def proxy_intake(payload: dict, session: dict = Depends(require_session)):
    return _post("intake", "/intake", payload)


@app.get("/eligibility")
def proxy_eligibility(insurance_id: str, session: dict = Depends(require_session)):
    return _get("eligibility", "/eligibility", params={"insurance_id": insurance_id})


# --------------------------------------------------------------------------- #
# patients / records
# --------------------------------------------------------------------------- #
@app.get("/patients")
def proxy_patients(
    session: dict = Depends(require_session),
    q: Optional[str] = None,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return _get("records", "/patients", params={"q": q, "limit": limit, "offset": offset})


@app.get("/patients/{patient_id}")
def proxy_patient(patient_id: int, session: dict = Depends(require_session)):
    return _get("records", f"/patients/{patient_id}")


@app.get("/patients/{patient_id}/records")
def proxy_records(patient_id: int, session: dict = Depends(require_session)):
    # IDOR: a valid session is required, but it is never checked against
    # {patient_id}. {patient_id} is the sequential primary key.
    return _get("records", f"/patients/{patient_id}/records")


@app.get("/records/search")
def proxy_search(q: str, session: dict = Depends(require_session)):
    return _get("records", "/records/search", params={"q": q})


# --------------------------------------------------------------------------- #
# scheduling
# --------------------------------------------------------------------------- #
@app.get("/slots")
def proxy_slots(
    session: dict = Depends(require_session),
    provider_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=200),
):
    return _get("scheduling", "/slots", params={"provider_id": provider_id, "limit": limit})


@app.get("/appointments")
def proxy_list_appointments(patient_id: int, session: dict = Depends(require_session)):
    return _get("scheduling", "/appointments", params={"patient_id": patient_id})


@app.get("/schedule")
def proxy_day_schedule(
    date: str,
    session: dict = Depends(require_session),
    provider_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    # One clinic day across all patients, for the front-desk queue. Additive:
    # /appointments requires a patient_id, so a day view was previously only
    # reachable by fanning out per patient (the D8 N+1 pattern). Session check
    # is the same as every other read here — this is not an authz change (D11).
    return _get(
        "scheduling",
        "/schedule",
        params={"date": date, "provider_id": provider_id, "limit": limit, "offset": offset},
    )


@app.post("/appointments")
def proxy_book(payload: dict, session: dict = Depends(require_session)):
    return _post("scheduling", "/appointments", payload)


@app.post("/appointments/{appointment_id}/cancel")
def proxy_cancel(appointment_id: int, session: dict = Depends(require_session)):
    return _post("scheduling", f"/appointments/{appointment_id}/cancel", {})


# --------------------------------------------------------------------------- #
# release of information
# --------------------------------------------------------------------------- #
@app.get("/roi/requests")
def proxy_roi_list(session: dict = Depends(require_session), patient_id: Optional[int] = None):
    return _get("roi", "/roi/requests", params={"patient_id": patient_id})


@app.post("/roi/requests")
def proxy_roi_create(payload: dict, session: dict = Depends(require_session)):
    return _post("roi", "/roi/requests", payload)


@app.post("/roi/requests/{request_id}/fulfill")
def proxy_roi_fulfill(request_id: int, session: dict = Depends(require_session)):
    return _post("roi", f"/roi/requests/{request_id}/fulfill", {})


# --------------------------------------------------------------------------- #
# ai assistant
# --------------------------------------------------------------------------- #
def _ai_rate_limited(session: dict = Depends(require_session)) -> dict:
    """Per-user REQUEST quota for the AI endpoint (Codex PR #7 round 6; ADR 0007).

    require_session only proves a caller is logged in, and sessions never
    expire — so without a quota one leaked/stale token, or a bored logged-in
    user, could loop /ai/intake-instructions with tiny closed-vocabulary bodies
    and drive unbounded Bedrock spend and ai-assistant worker starvation. This
    consumes a Redis fixed-window counter keyed by the authenticated user
    BEFORE any work, so rejected requests never reach the cache or the paid
    path. It bounds one user's REQUEST rate; the aggregate SPEND ceiling
    (consume_ai_global_budget) and the response cache are applied in the
    handler on the paid path only. Fails closed: if the counter cannot be read
    the request does not proceed. (Depends on require_session, so anonymous
    callers are still rejected first.)
    """
    username = session.get("username") or "unknown"
    try:
        retry_after = check_ai_rate_limit(
            username,
            settings.ai_rate_limit_per_minute,
            settings.ai_rate_limit_per_day,
        )
    except Exception as e:  # Redis fault: do not let the request proceed.
        log.error("ai rate-limit check unavailable: %s", type(e).__name__)
        raise HTTPException(status_code=503, detail="assistant is temporarily unavailable")
    if retry_after:
        # username is an internal identifier, not PHI — safe to log.
        log.warning("ai rate limit reached user=%s", username)
        raise HTTPException(
            status_code=429,
            detail="assistant request limit reached; please try again later",
            headers={"Retry-After": str(retry_after)},
        )
    return session


def _reserve_ai_budget() -> str | None:
    """Consume one slot of the aggregate daily spend ceiling, or reject (ADR 0007).

    Called on the paid path only (single-flight winner, after a cache miss and
    after request validation), so the global counter tracks actual Bedrock
    fan-outs — not cache hits, not per-user-rejected requests, and not bodies
    that would 422 downstream. Fails closed: a Redis fault here means we cannot
    verify the spend ceiling, so we do not spend.

    "Paid path" means *believed* paid at admission time, and for `/visit-chat`
    that is the best this can be: whether a turn needs the vendor at all is
    derived downstream from the message, the visit's facts, and the payer's
    answer (ADR 0011 round 5). Such a turn reserves a slot and gets it back
    within the request via `llm_egress: false`, so the counter is correct at
    rest — but a turn that will cost nothing is still admitted against the
    ceiling, and still refused with 429 once it is exhausted.

    Returns the reservation key — the exact day bucket that was charged. A
    refund must pass this key back (never re-derive it from the clock): a
    fan-out reserved just before UTC midnight refunds after the rollover, and a
    re-derived key would credit the new day's counter instead of the one that
    was charged (Codex PR #7 round 14). ``None`` means the ceiling is disabled
    and there is nothing to refund.
    """
    try:
        retry_after, reservation_key = consume_ai_global_budget(
            settings.ai_rate_limit_global_per_day
        )
    except Exception as e:
        log.error("ai global budget check unavailable: %s", type(e).__name__)
        raise HTTPException(status_code=503, detail="assistant is temporarily unavailable")
    if retry_after:
        log.warning("ai aggregate daily spend ceiling reached")
        raise HTTPException(
            status_code=429,
            detail="assistant is at capacity for today; please try again later",
            headers={"Retry-After": str(retry_after)},
        )
    return reservation_key


# Downstream statuses that prove the fan-out made NO paid Bedrock call, so a
# reserved budget slot must be refunded (Codex PR #7 rounds 8, 9): 401 = bad
# service-to-service auth, 422 = request rejected at the ai-assistant boundary,
# 503 = ai-assistant refused BEFORE egress.
#
# What raises that 503 differs by endpoint, and the difference matters when
# reasoning about refund coverage. /intake-instructions: blank proxy secret,
# missing/placeholder Bedrock credentials, or an unpriced model. /visit-chat:
# blank proxy secret or an empty member-id catalog ONLY — the credential and
# pricing refusals no longer surface as 503 there at all, because that endpoint
# refuses to discard an already-computed coverage verdict; they arrive as a 200
# carrying `llm_egress: false` and are refunded on the flag (see below).
# NOT 502/504/500 — there the provider path was entered, so Bedrock may have been
# contacted/billed and the charge stands. This split is only sound because
# ai-assistant maps its POST-egress provider failure (LLMUnavailable: throttle /
# upstream 5xx / connection error) to 502, never 503 (Codex PR #7 round 9);
# otherwise an outage retry storm would refund every attempt and the tenant
# ceiling would stop bounding vendor fan-out. gateway→service transport failures
# also surface as 502/504 and likewise keep the charge (conservative: over-counts
# toward the ceiling, never past it).
#
# Status is necessary but no longer SUFFICIENT on /ai/visit-chat: that endpoint
# refuses to throw away an already-computed coverage verdict just because the
# optional action-selection step failed locally, so a pre-egress refusal there
# arrives as a 200 carrying `llm_egress: false` and is refunded on the flag
# instead (Codex PR #14 round 3; see proxy_visit_chat and ADR 0011 §7).
_NON_PAID_DOWNSTREAM_STATUS = frozenset({401, 422, 503})


def _refund_ai_budget(reservation_key: str | None) -> None:
    """Give back an aggregate-budget slot reserved for a fan-out that turned out
    to make no paid Bedrock call (ADR 0007). ``reservation_key`` is the exact
    bucket _reserve_ai_budget charged — passed back verbatim so a refund that
    crosses the UTC midnight rollover still credits the day it was charged to,
    never the new day's counter (Codex PR #7 round 14). Best-effort: a lost
    refund only slightly over-counts spend (fails toward the ceiling, never
    past it), so a Redis fault here must not fail the request path."""
    try:
        release_ai_global_budget(reservation_key)
    except Exception as e:
        log.error("ai global budget refund unavailable: %s", type(e).__name__)


class _AiPlanType(str, Enum):
    hmo = "HMO"
    ppo = "PPO"
    epo = "EPO"
    pos = "POS"
    medicare = "Medicare"
    medicaid = "Medicaid"
    self_pay = "Self-pay"


class _AiIntakeInstructionsRequest(BaseModel):
    """Gateway-side mirror of ai-assistant ``schemas.InstructionsRequest``, used
    ONLY as a paid-budget pre-filter (Codex PR #7 round 7).

    ai-assistant remains the authoritative validator; this copy exists solely so
    the gateway can reject the bodies ai-assistant would 422 BEFORE they consume
    the shared spend ceiling. Keep it in sync with that schema (the same
    cross-boundary mirror pattern as ``PlanType`` <-> the portal intake select).
    Being a strict copy is what closes the hole; if it ever drifts LOOSER than
    the source, the only cost is that the drift-gap bodies reach the fan-out and
    422 there — exactly today's behavior, just narrower — never a wrong
    checklist.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    has_insurance: bool = False
    plan_type: _AiPlanType | None = None
    policy_holder_is_self: bool = True
    communications_opt_in: bool = False
    financial_ack: bool = False

    @model_validator(mode="after")
    def _insurance_facts_consistent(self):
        if self.plan_type is None:
            return self
        is_self_pay = self.plan_type == _AiPlanType.self_pay.value
        if self.has_insurance and is_self_pay:
            raise ValueError("plan_type Self-pay contradicts has_insurance=true")
        if not self.has_insurance and not is_self_pay:
            raise ValueError("an insured plan_type contradicts has_insurance=false")
        return self


def _validate_ai_request(payload: dict) -> dict:
    """Validate the body and return its CANONICAL fact vector (Codex PR #7
    rounds 7, 10).

    A budget pre-filter, not the authority: ai-assistant's
    ``schemas.InstructionsRequest`` is the authoritative validator, but rejecting
    the obviously-invalid bodies here — unknown/forbidden fields, an insurance
    flag that contradicts the plan type — keeps them out of the cache key, the
    aggregate spend counter, and the paid fan-out. Mirrors ai-assistant's no-echo
    422 (``validation_error_no_echo``): a rejected value is exactly where PHI
    could be smuggled (an unknown field), so neither the value nor the parse
    error is logged or echoed — only that the request was invalid.

    Returns the NORMALIZED facts (``model_dump``), not the raw body. The cache
    key, single-flight lock, and fan-out payload must all derive from the same
    canonical fact vector so semantically identical requests collapse to ONE paid
    call — otherwise ``{}``, a body spelling out the schema defaults, and coerced
    booleans (``"true"`` vs ``true``) hash to different keys for the same facts,
    letting a caller bypass duplicate-collapse and spend repeated Bedrock calls
    (Codex PR #7 round 10). ``extra="forbid"`` already rejected unknown fields
    above, so the dump carries only the closed-vocabulary fields — nothing
    smuggled can ride along into the fan-out or the key.
    """
    try:
        model = _AiIntakeInstructionsRequest.model_validate(payload)
    except ValidationError:
        raise HTTPException(status_code=422, detail="invalid intake-instructions request")
    return model.model_dump(mode="json")


def _await_coalesced_result(cache_key: str):
    """Wait briefly for the single-flight winner to publish its cached result.

    Polls the response cache on a short interval up to a bounded budget so a
    duplicate concurrent miss (double-click / retry storm) returns the winner's
    result instead of making its own paid call. Bounded on purpose: a loser
    blocks its worker only for the wait budget, after which the caller gets a
    controlled retry. Returns the cached value, or None if it did not appear in
    time.
    """
    waited = 0.0
    while waited < settings.ai_singleflight_wait_seconds:
        time.sleep(settings.ai_singleflight_poll_seconds)
        waited += settings.ai_singleflight_poll_seconds
        cached = ai_cache_get(cache_key)
        if cached is not None:
            return cached
    return None


@app.post("/ai/intake-instructions")
def proxy_intake_instructions(payload: dict, session: dict = Depends(_ai_rate_limited)):
    # Reject bodies ai-assistant would 422 BEFORE reserving the shared paid-spend
    # ceiling (Codex PR #7 round 7). Without this a logged-in caller could send
    # many distinct invalid bodies (unknown fields, contradictory insurance
    # facts) — each a cache miss that increments the aggregate budget and is only
    # rejected downstream — a cheap tenant-wide denial of the paid assistant.
    # Returns the CANONICAL facts (normalized dump), used for the cache key, the
    # single-flight lock, and the fan-out so identical requests spelled different
    # ways collapse to one paid call (Codex PR #7 round 10).
    facts = _validate_ai_request(payload)

    # Closed-vocabulary body → identical facts yield the same checklist, so a
    # response cache collapses retries/double-clicks and repeat identical
    # intakes into one paid call. Cache read is best-effort (a fault degrades to
    # a paid call, never an error) and does NOT consume the spend ceiling — a
    # hit costs nothing, so it must not count against the aggregate budget.
    cache_key = ai_cache_key(facts)
    cached = ai_cache_get(cache_key)
    if cached is not None:
        return cached

    # Cache miss. Coalesce CONCURRENT identical misses (a double-click, a browser
    # retry, or many staff submitting the same closed-vocabulary facts at once):
    # elect one winner to make the paid fan-out; other in-flight duplicates wait
    # briefly for the winner's cached result rather than each making their own
    # paid call (Codex PR #7 round 7 — closes ADR 0007 deferred gap #4).
    flight_token = ai_singleflight_acquire(cache_key, settings.ai_singleflight_lock_ttl_seconds)
    if not flight_token:
        coalesced = _await_coalesced_result(cache_key)
        if coalesced is not None:
            return coalesced
        # The winner has not published a result within the wait budget. Return a
        # controlled retry rather than making a second paid call for the same
        # body — the client retries and picks up the cached result.
        raise HTTPException(
            status_code=429,
            detail="assistant is processing a matching request; please retry shortly",
            headers={"Retry-After": "1"},
        )
    try:
        # Winner: this is the paid fan-out. Reserve the aggregate budget now,
        # immediately before the LLM call — the reservation is provisional and is
        # refunded below (by its exact reserved key) if the call proves to make
        # no paid Bedrock request.
        budget_reservation = _reserve_ai_budget()
        try:
            # Deliberately NOT _post: that helper swallows failures into a 200-OK
            # {"error": str(e)} body, and str(e) on an httpx error can embed the
            # request URL (the member_id leak class). New routes use _post_checked.
            result = _post_checked(
                "ai",
                "/intake-instructions",
                facts,
                timeout=settings.ai_read_timeout_seconds,
                # Service-to-service auth: ai-assistant refuses calls without this
                # header, so a direct (gateway-bypassing) caller cannot reach the
                # paid LLM path even if the service port were ever exposed. Value
                # is a secret — _post_checked never logs headers.
                headers={"X-Internal-Auth": settings.ai_proxy_shared_secret},
            )
        except HTTPException as e:
            # A downstream config/auth/validation rejection (401/422/503) means no
            # paid Bedrock call happened, so the reservation must not stick —
            # otherwise a misconfiguration or retry storm walks the shared daily
            # counter to its cap and 429s every valid caller until the window
            # rolls over, even after the config is fixed (Codex PR #7 round 8).
            # 502/504/500 keep the charge: Bedrock may have been contacted/billed.
            if e.status_code in _NON_PAID_DOWNSTREAM_STATUS:
                _refund_ai_budget(budget_reservation)
            raise
        # Only successful responses reach here (_post_checked raises on failure),
        # so only good checklists are cached. Best-effort write.
        ai_cache_set(cache_key, result, settings.ai_cache_ttl_seconds)
        return result
    finally:
        # Release the single-flight slot so a later identical miss (e.g. after
        # the cache TTL expires) is never wedged, even if the fan-out raised.
        # Owner-checked (our token): if this winner outran the lock TTL and a new
        # winner already holds the key, this release is a no-op (Codex PR #7
        # round 13).
        ai_singleflight_release(cache_key, flight_token)


# --------------------------------------------------------------------------- #
# ai assistant — visit chat (ADR 0011)
# --------------------------------------------------------------------------- #
def _ai_chat_rate_limited(session: dict = Depends(require_session)) -> dict:
    """Per-user REQUEST quota for the chat endpoint, in its own namespace.

    Same control and same fail-closed rule as _ai_rate_limited, with separate
    counters and higher caps: a conversation is many turns where an intake
    checklist is one submit, and neither endpoint may exhaust the other's quota
    (ADR 0011 §6). The shared aggregate SPEND ceiling still bounds dollars.
    """
    username = session.get("username") or "unknown"
    try:
        retry_after = check_ai_rate_limit(
            username,
            settings.ai_chat_rate_limit_per_minute,
            settings.ai_chat_rate_limit_per_day,
            namespace="aichat",
        )
    except Exception as e:  # Redis fault: do not let the request proceed.
        log.error("ai chat rate-limit check unavailable: %s", type(e).__name__)
        raise HTTPException(status_code=503, detail="assistant is temporarily unavailable")
    if retry_after:
        log.warning("ai chat rate limit reached user=%s", username)
        raise HTTPException(
            status_code=429,
            detail="assistant request limit reached; please try again later",
            headers={"Retry-After": str(retry_after)},
        )
    return session


_ASSISTANT_HEALTH_STATES = frozenset({"ok", "degraded"})


def _assistant_health(value) -> str:
    """Project ai-assistant's health field onto a closed vocabulary.

    An allowlist, not a pass-through: the value lands in a response the portal
    renders, so anything unrecognised becomes "unknown" rather than being
    echoed. Same discipline as every other closed value crossing this boundary.

    The isinstance test is not redundant. ``value`` is a field of a JSON body
    from another service, so it can be any JSON type, and an unhashable one (an
    object, an array) raises TypeError from a bare ``in`` against a set —
    turning a malformed downstream field into a 500 on a turn that otherwise
    succeeded. Checked, not assumed.
    """
    return value if isinstance(value, str) and value in _ASSISTANT_HEALTH_STATES else "unknown"


class _VisitChatRequest(BaseModel):
    """Gateway-side validation of a chat turn.

    Unlike the intake-instructions mirror this is not only a budget pre-filter —
    it is the edge that bounds a free-text field. ``visit_id`` is pinned to the
    exact shape ``new_visit_id`` mints (32 lowercase hex chars): the value is
    interpolated into a Redis key, so anything else — a colon, a glob, a path —
    is rejected here rather than reaching the keyspace.
    """

    model_config = ConfigDict(extra="forbid")

    visit_id: Optional[str] = Field(default=None, pattern="^[0-9a-f]{32}$")
    message: str = Field(min_length=1, max_length=settings.ai_visit_max_message_chars)


def _validate_visit_chat_request(payload: dict) -> dict:
    """Validate a chat body, no-echo on failure.

    Mirrors ai-assistant's ``validation_error_no_echo`` and the intake-instructions
    pre-filter: a rejected value is exactly where PHI could sit — here it is
    GUARANTEED to be free text a human typed — so neither the value nor the parse
    error is logged or echoed. Rejecting before the spend ceiling also keeps an
    over-long or malformed body from charging the tenant budget.
    """
    try:
        model = _VisitChatRequest.model_validate(payload)
    except ValidationError:
        raise HTTPException(status_code=422, detail="invalid visit-chat request")
    return model.model_dump(mode="json")


def _build_stored_member_id_re(prefixes: tuple[str, ...]) -> "re.Pattern[str] | None":
    """Compile the catalog into the set of ids the RECOGNISER could have produced.

    The gateway is not a recogniser — it never reads free text for ids — so this
    pattern is deliberately narrower than ai-assistant's: FULL match, no
    IGNORECASE, on the one canonical form that service stores (a catalogued
    prefix, upper case, plus 3-9 ASCII digits). Anything else did not come out of
    `_extract_insurance_ids`, and is therefore not something the gateway will
    persist and hand back for a later payer lookup (Codex PR #14 round 7).

    `re.ASCII` for the same reason ai-assistant needs it and not as a style
    choice: bare `\\d` matches Arabic-Indic digits, and `AETN١٢٣٤` reaching the
    payer is a 404 rendered as a definitive denial.

    None for an EMPTY catalog, never a pattern. Joining zero prefixes yields
    `^(?:)\\d{3,9}$`, which accepts any run of digits — the round-1 empty-catalog
    hole one boundary over. Callers treat None as "recognise nothing" and
    `_require_member_id_catalog` turns the state into a loud 503.

    Each prefix is escaped because the catalog is operator input: an unescaped `.`
    would silently WIDEN the accepted set (`A.C` admitting `ABC1234`, which is the
    exact value this finding was about).
    """
    if not prefixes:
        return None
    return re.compile(
        r"^(?:%s)\d{3,9}$" % "|".join(re.escape(prefix) for prefix in prefixes),
        re.ASCII,
    )


_STORED_MEMBER_ID_RE = _build_stored_member_id_re(settings.ai_member_id_prefixes)


def _require_member_id_catalog() -> None:
    """Refuse /ai/visit-chat when the gateway's own catalog is empty.

    Mirrors ai-assistant's guard of the same name, and for the same reason: with
    no catalog this service cannot tell an id the recogniser produced from one it
    would never have trusted, so every id-bearing turn would 502 anyway. 503
    before the spend ceiling names the misconfiguration instead, and 503 is a
    status the caller can retry once config is fixed.
    """
    if _STORED_MEMBER_ID_RE is None:
        log.error("/ai/visit-chat refused: AI_MEMBER_ID_PREFIXES is empty")
        raise HTTPException(status_code=503, detail="assistant is not configured")


class _VisitChatVerdict(BaseModel):
    """The projected coverage verdict, closed at the gateway boundary.

    Declares exactly the keys something READS — `active`/`status` decide reuse,
    `payer`/`checked_at`/`observed_at` are rendered or measured — and drops the
    rest. `raw_status` and `reason` are written by `eligibility_client` and read
    by nothing, so they are not carried into a PHI store; that is the same
    projection rule that keeps the downstream `error` string out of visit memory.

    Closing it is a size control as much as a shape one. `Optional[dict]` accepted
    an arbitrarily large, arbitrarily nested object straight into a `SET
    visit:<id> … EX ttl` on the store that also holds sessions — the request side
    is bounded (`ai_visit_max_message_chars`, `ai_visit_max_turns`) and the
    response side was not. It is also a PHI control: `VisitFacts`' own
    `extra="forbid"` closes the fact KEYS, but a name or a DOB nested inside an
    unvalidated verdict was persisted at rest all the same, and
    `tests/test_visit_chat_phi.py` structurally cannot catch that because it
    drives the one renderer guaranteed not to do it.

    Every field is optional: a verdict legitimately arrives without
    `observed_at` (written by an older ai-assistant — round 4 makes that "not
    reusable", which is the safe answer), and rejecting it would fail a turn over
    a field whose absence the design already handles.
    """

    model_config = ConfigDict(extra="ignore")

    active: Optional[bool] = None
    status: Optional[str] = Field(default=None, pattern="^[a-z_]{1,32}$")
    payer: Optional[str] = Field(default=None, max_length=253)
    checked_at: Optional[str] = Field(default=None, max_length=64)
    observed_at: Optional[str] = Field(default=None, max_length=64)


class _VisitChatFacts(BaseModel):
    """Mirror of ai-assistant ``schemas.VisitFacts`` — the only shape allowed to
    overwrite a visit's memory.

    Both fields are REQUIRED and nullable, which is the load-bearing part. A
    response_model-serialised body always carries both keys, explicitly null when
    empty, so `{}` is not "an empty visit" — it is a body our renderer did not
    produce, and treating it as empty state is what silently erased a confirmed
    `insurance_id` (Codex PR #14 round 6).

    ``extra="ignore"`` rather than ``forbid``, and the asymmetry with VisitFacts'
    own ``forbid`` is deliberate. Forbidding here would 502 every turn of a
    rolling deploy in which a newer ai-assistant adds a fact. Passing an unknown
    key THROUGH is worse than dropping it: the gateway echoes stored facts back
    on the next turn, and ai-assistant's own ``extra="forbid"`` would then 422
    that turn and every one after it — a visit bricked until its TTL. Dropping
    costs the new field during the deploy window and nothing after it.

    ``insurance_id`` mirrors the RECOGNISER, not merely ai-assistant's storage
    validator (Codex PR #14 round 7). An upper-case-alnum shape check accepted
    `ABC1234` — a value no catalogued payer prefix can produce — and the gateway
    persisted it; ai-assistant then accepts a stored `VisitFacts.insurance_id` and
    uses it DIRECTLY for a `recheck` lookup without going back through
    `_extract_insurance_ids`, so the closed-catalog false-positive control was
    bypassed and a payer 404 on a token nobody recognised renders as a confident
    "no active coverage". The check is therefore the catalog itself, and a hyphen
    is no longer accepted either: the recogniser cannot emit one.

    ``insurance_id`` mirrors the CONSTRAINT, not just the field name. Mirroring
    only the name is how the first cut of this class shipped the bug it was
    written to prevent: ``VisitFacts`` carries a validator that upper-cases and
    rejects non-ASCII precisely because a stored id is used directly for a payer
    lookup on a later turn, and a value that fails it — `AETN1224K`, which
    survives `.upper()` — would have been persisted here, then 422'd by
    ai-assistant on every subsequent turn, bricking the visit until its TTL with
    no path that repairs the record. The pattern accepts every id the recogniser
    can produce (upper-case ASCII, from a configured payer-prefix catalog) and
    nothing a human typed.
    """

    model_config = ConfigDict(extra="ignore")

    insurance_id: Optional[str] = Field(default=..., max_length=64)
    last_eligibility: Optional[_VisitChatVerdict]

    @field_validator("insurance_id")
    @classmethod
    def _must_be_a_catalogued_member_id(cls, value: Optional[str]) -> Optional[str]:
        """Reject any id the recogniser could not have produced.

        `fullmatch`, not `match`, even though the pattern is anchored: Python's
        `$` also matches immediately before a trailing newline, so `AETN1224\\n`
        would otherwise pass and be stored — and a stored id goes to the payer
        verbatim.

        No pattern (empty catalog) rejects rather than accepts. `/ai/visit-chat`
        503s in that state before ever reaching here, so this is the belt to that
        braces — the same fail-closed direction `_extract_insurance_ids` takes.

        The explicit ASCII test is the second belt, and it is not redundant with
        `re.ASCII` (pre-push review, round 7). That flag constrains `\\d` and `\\b`;
        it says nothing about a literal non-ASCII character inside a PREFIX, so an
        operator catalog carrying `MÉDI` would match `MÉDI1224` here — a value the
        old shape check rejected, and one ai-assistant's own `VisitFacts` rejects,
        so storing it 422s every later turn and the visit is dead until its TTL.
        `_extract_insurance_ids` carries the same belt for the same reason.
        """
        if value is None:
            return None
        if not value.isascii():
            raise ValueError("insurance_id must be ASCII")
        if _STORED_MEMBER_ID_RE is None or not _STORED_MEMBER_ID_RE.fullmatch(value):
            raise ValueError("insurance_id is not a recognisable member id")
        return value


class _VisitChatDownstream(BaseModel):
    """Mirror of the ai-assistant ``/visit-chat`` fields the gateway PERSISTS or
    ANSWERS WITH (Codex PR #14 round 6).

    `_post_checked` proves only that a non-error JSON body came back. It cannot
    prove the body came from our renderer, and a 200 from a misroute, a rolling
    deploy, or an intermediary was being trusted with the visit record: a missing
    `facts` key coerced to `{}` overwrote a confirmed `insurance_id` and the
    stored payer verdict, which live nowhere else, so the next turn re-asked for
    an id the patient had already given and re-spent a PHI-bearing payer call.

    What is validated is exactly what the gateway acts on:

      * ``facts`` — written into Redis, so it gets the closed shape above;
      * ``intent`` / ``status`` — written into the METADATA-ONLY transcript. The
        constraint is a SHAPE (snake_case, bounded), not a copy of the enums, so
        it cannot go stale when a new intent is added — while free text a clerk
        typed cannot satisfy it, which is the property the transcript's
        no-PHI-at-rest guarantee actually needs;
      * ``reply`` / ``disclaimer`` / ``eligibility`` — the answer handed to the
        clerk. A catalog-rendered reply is bounded by construction (a verdict
        line plus at most MAX_ITEMS fixed strings); an order of magnitude past
        that is not our renderer.

    Deliberately ABSENT: ``llm_egress`` and ``assistant``. Both are our own
    accounting and health reporting, and both already degrade conservatively — an
    ambiguous spend flag keeps the charge, an unrecognised health value reads
    "unknown". Failing a turn over either would discard a coverage verdict that
    a payer call already paid for, which is the mistake round 3 fixed. A field
    that cannot corrupt state and cannot mislead a clerk is not worth a 502.

    ``eligibility`` belongs to that same category and is validated but NOT fatal.
    It is answer-only — never persisted, never fed back — and the verdict it
    reports is already in `reply` as server-rendered text. Failing the turn over
    it would throw away `facts.last_eligibility`, the verdict the payer call this
    turn already paid for, and make the next turn buy it again. An unusable value
    degrades to null.
    """

    model_config = ConfigDict(extra="ignore")

    reply: str = Field(min_length=1, max_length=4000)
    intent: str = Field(pattern="^[a-z_]{1,32}$")
    status: str = Field(pattern="^[a-z_]{1,32}$")
    facts: _VisitChatFacts
    disclaimer: str = Field(min_length=1, max_length=1000)
    eligibility: Optional[_VisitChatVerdict] = None

    @field_validator("eligibility", mode="before")
    @classmethod
    def _degrade_unusable_verdict(cls, value: object) -> object:
        """Answer-only, so an unusable value is dropped rather than fatal."""
        if value is None:
            return None
        try:
            return _VisitChatVerdict.model_validate(value)
        except ValidationError:
            return None


def _validate_visit_chat_downstream(result: dict) -> _VisitChatDownstream:
    """Parse a downstream 200, or fail the turn without touching visit memory.

    502, because the fault is downstream's and the caller can retry: the visit
    record is exactly as it was, so a retry resumes the conversation rather than
    restarting it. Nothing is refunded on this path — an unparseable body says
    nothing about whether Bedrock was called, and over-counting toward the
    ceiling is the safe direction (ADR 0007).

    Neither the body nor the parse error is logged. Both are unvalidated
    downstream content on a path whose whole premise is that we do not know what
    produced them, and a `reply` legitimately carries a payer name and a member's
    coverage verdict.
    """
    if not isinstance(result, dict):
        log.error("visit-chat downstream returned a non-object body")
        raise HTTPException(status_code=502, detail="assistant returned an unusable response")
    try:
        model = _VisitChatDownstream.model_validate(result)
    except ValidationError as e:
        # Field NAMES only — they are ours, from the model above; values are not.
        # The reserved slot is named explicitly: under a version skew EVERY turn
        # takes this branch, so the shared daily ceiling drains at full rate, and
        # the operator symptom is /ai/intake-instructions 429-ing for the rest of
        # the day. Keeping the charge is deliberate (a body we refuse to parse
        # cannot be trusted about our own spend either); being unable to attribute
        # it is not.
        log.error(
            "visit-chat downstream failed validation; visit memory left unchanged "
            "and the reserved ai budget slot stays charged (fields=%s)",
            sorted({str(err["loc"][0]) for err in e.errors() if err.get("loc")}),
        )
        raise HTTPException(status_code=502, detail="assistant returned an unusable response")
    dropped = len(set(result.get("facts") or {}) - set(_VisitChatFacts.model_fields))
    if dropped:
        # Not fatal (see _VisitChatFacts), but a silently dropped fact is a
        # feature quietly not working during a deploy — count only, never keys.
        log.warning("visit-chat downstream sent %d unknown fact field(s); dropped", dropped)
    return model


@app.post("/ai/visit-chat")
def proxy_visit_chat(payload: dict, session: dict = Depends(_ai_chat_rate_limited)):
    """One turn of the front-desk eligibility chat.

    The gateway owns everything stateful here — auth, abuse controls, and the
    visit memory — while ai-assistant stays a pure function of the turn (ADR
    0011 §1). Note what is deliberately ABSENT compared with
    /ai/intake-instructions: there is no response cache on this path. A reply
    depends on a live coverage verdict and on this visit's memory, so it is
    neither idempotent nor safely shareable, and its key would have to derive
    from PHI-bearing free text (ADR 0011 §6).
    """
    # Request validation FIRST, then config: with no member-id catalog the gateway
    # cannot tell a recognised id from a token that merely looks like one, so it
    # cannot safely persist facts at all (round 7) — but a malformed body is the
    # client's error and costs nothing to reject, and reporting it as
    # "assistant is not configured" would hide every client mistake behind a
    # server fault for the duration of the misconfiguration (pre-push review).
    body = _validate_visit_chat_request(payload)
    _require_member_id_catalog()
    owner = session.get("username") or "unknown"
    visit_id = body.get("visit_id")
    record = None

    if visit_id:
        try:
            record = visit_memory_get(visit_id, owner)
        except VisitMemoryUnavailable as e:
            # Fail CLOSED: a fault cannot tell "absent" from "someone else's", so
            # continuing would wave through a turn whose ownership was never
            # verified. Only a first turn (no visit_id) starts fresh, and it reads
            # nothing.
            log.error("visit memory unavailable: %s", e)
            raise HTTPException(status_code=503, detail="assistant is temporarily unavailable")
        if record is None:
            # Unknown id and not-your-id answer identically: a 403 would confirm
            # that somebody else's visit exists.
            raise HTTPException(status_code=404, detail="visit not found")
    else:
        visit_id = new_visit_id()

    # Serialise turns within this visit: two concurrent turns would read-modify-
    # write the same record (dropping one) and make two paid calls for one clerk.
    try:
        lock_token = visit_lock_acquire(visit_id, settings.ai_singleflight_lock_ttl_seconds)
    except VisitLockUnavailable as e:
        # Fail CLOSED for a visit that already has state, because the lock is the
        # ONLY guard on it and this is where a fail-open answer was worse than an
        # outage (Codex PR #14 round 7): the record loads under `maxmemory` +
        # `noeviction` while the lock write fails, so both concurrent turns would
        # read the same record, both spend a PHI-bearing payer call, and the
        # second save would drop the first's turns and facts. 503 rather than 429:
        # nothing is processing this visit — our guard is down, and the record is
        # untouched, so a retry resumes the conversation. Raised before
        # _reserve_ai_budget, so there is no spend to refund.
        #
        # The release is what MAKES that "retry resumes the conversation" true
        # (pre-push review, round 7): the fault may be a lost reply on a SET that
        # landed, and an unreleased token would wedge this visit for the whole lock
        # TTL — every retry answering 429 "already processing" against a lock
        # nobody holds. Compare-and-delete clears only our own write, and the
        # release swallows its own faults, where the TTL is the backstop.
        if record is not None:
            visit_lock_release(visit_id, e.token)
            log.error("visit lock unavailable: %s", e)
            raise HTTPException(
                status_code=503, detail="assistant is temporarily unavailable"
            )
        # A FIRST turn has nothing to serialise against — the id was minted a few
        # microseconds ago in this function and no client has ever seen it — so
        # failing closed here would turn a Redis blip into an outage for new
        # visits and buy no state safety. The token still rides through to the
        # `finally`, for the lost-reply case above: if the SET landed, this turn
        # really does hold the lock and must clear it on the way out (and the
        # release is a no-op when there is nothing to clear).
        log.warning("visit lock unavailable on a first turn (%s); proceeding unlocked", e)
        lock_token = e.token
    else:
        if not lock_token:
            raise HTTPException(
                status_code=429,
                detail="this visit is already processing a message; please retry shortly",
                headers={"Retry-After": "1"},
            )
    try:
        turns = (record or {}).get("turns") or []
        facts = (record or {}).get("facts") or {}
        budget_reservation = _reserve_ai_budget()
        try:
            # _post_checked, never _post: the legacy helper swallows failures into
            # a 200-OK {"error": str(e)} body, and str(e) on an httpx error embeds
            # the request URL — the leak class PR #11 closed.
            result = _post_checked(
                "ai",
                "/visit-chat",
                {"message": body["message"], "turns": turns, "facts": facts},
                timeout=settings.ai_read_timeout_seconds,
                headers={"X-Internal-Auth": settings.ai_proxy_shared_secret},
            )
        except HTTPException as e:
            if e.status_code in _NON_PAID_DOWNSTREAM_STATUS:
                _refund_ai_budget(budget_reservation)
            raise

        # Before anything is refunded, answered, or written: a 200 is not proof
        # the body came from our renderer (round 6). Raises 502 with the visit
        # record untouched, so a retry resumes the visit instead of restarting a
        # conversation whose only copy of the payer verdict this path would
        # otherwise have overwritten.
        downstream = _validate_visit_chat_downstream(result)

        # A 200 from /visit-chat is NOT proof of a paid call (Codex PR #14 round
        # 3). The endpoint answers with the deterministic action list rather than
        # discarding a coverage verdict it already computed, so a local
        # (pre-egress) LLM refusal now surfaces as a successful turn carrying
        # `llm_egress: false`. Refunding on the flag keeps ADR 0007's accounting
        # exact — a Bedrock misconfiguration or an exhausted local cap no longer
        # walks the shared daily counter to its cap — while the clerk still gets
        # the answer. Absent/unparseable field defaults to charged: the
        # conservative direction is to over-count toward the ceiling, never to
        # refund spend that really happened.
        if result.get("llm_egress") is False:
            _refund_ai_budget(budget_reservation)

        # The transcript is METADATA ONLY — what happened, never what was said
        # (ADR 0011 §3). The clerk's prose is not persisted anywhere: nothing in
        # this feature reads it back (the model only learns the turn COUNT), so
        # storing it would be PHI at rest with no consumer, and unmaskable PHI at
        # that — a typed patient name defeats any pattern filter. Both values
        # below are closed vocabulary ai-assistant derived server-side.
        new_turns = turns + [
            {"role": "user", "intent": downstream.intent, "status": None},
            {"role": "assistant", "intent": None, "status": downstream.status},
        ]
        persisted = visit_memory_save(
            visit_id,
            owner,
            downstream.facts.model_dump(mode="json"),
            new_turns,
            settings.ai_visit_ttl_seconds,
            settings.ai_visit_max_turns,
            created_at=(record or {}).get("created_at"),
        )
        # A lost write is not worth failing a turn that has already been answered
        # and paid for. What the id says about the visit still has to be true:
        #
        #  * first turn (record is None): the id was minted here and nothing was
        #    stored, so it resolves to nothing. Handing it back would make the
        #    clerk's NEXT message answer 404 "visit not found" with no indication
        #    of why, so send none and let that message open a fresh visit.
        #  * later turn: the record was loaded at the top of this function, so it
        #    is still in Redis, still owner-bound, and still loadable. Only THIS
        #    turn's append was lost. Nulling the id here would discard a visit
        #    that works — and under a persistent write fault (Redis at
        #    `maxmemory` with `noeviction`) it would do that on every turn, so a
        #    conversation would reset per message instead of degrading once.
        #
        # `stale` is the honest middle: memory is available, this turn is missing
        # from it. The log line carries no identifier — visit ids are opaque, but
        # the record's facts are not.
        resolvable = persisted or record is not None
        if not persisted:
            log.error(
                "visit memory write failed; answering with memory=%s",
                "stale" if resolvable else "unavailable",
            )
        return {
            # None, not omitted: a client that echoes it back sends no visit_id
            # and starts fresh, which is the honest outcome of a lost first write.
            "visit_id": visit_id if resolvable else None,
            "visit_memory": "ok" if persisted else ("stale" if resolvable else "unavailable"),
            "reply": downstream.reply,
            "disclaimer": downstream.disclaimer,
            # Dumped, not handed over as a model: the portal contract is a plain
            # JSON object or null, unchanged by validating it on the way through.
            "eligibility": (
                downstream.eligibility.model_dump(mode="json")
                if downstream.eligibility is not None
                else None
            ),
            # "ok" | "degraded" | "unknown". Forwarded for the same reason
            # `visit_memory` is: before this PR an LLM fault reached the caller
            # as a 503, and now it reaches them as a normal-looking 200 with a
            # deterministic action list. Without this the only trace of a dead
            # Bedrock config is one log line inside ai-assistant — and the
            # aggregate spend counter, the other thing an operator watches, is
            # deliberately refunded flat in exactly that case.
            #
            # Tri-state for the same reason visit_memory is: anything we did not
            # recognise (an older ai-assistant mid-rolling-deploy, a field drop)
            # is reported as "unknown" rather than coerced. Claiming "ok" would
            # be the green-dashboard lie; claiming "degraded" would raise a
            # false alarm on every turn during a deploy.
            "assistant": _assistant_health(result.get("assistant")),
        }
    finally:
        visit_lock_release(visit_id, lock_token)


# --------------------------------------------------------------------------- #
# interop
# --------------------------------------------------------------------------- #
@app.post("/hl7/ingest")
def proxy_hl7(payload: dict, session: dict = Depends(require_session)):
    return _post("interop", "/hl7/ingest", payload)


# --------------------------------------------------------------------------- #
# transport helpers
# --------------------------------------------------------------------------- #
def _clean(params: Optional[dict]) -> dict:
    return {k: v for k, v in (params or {}).items() if v is not None}


def _post(service: str, path: str, payload: dict):
    try:
        r = httpx.post(f"{SERVICES[service]}{path}", json=payload, timeout=30)
        return r.json()
    except Exception as e:
        log.error("proxy POST %s%s failed: %s", service, path, e)
        return {"error": str(e)}


def _get(service: str, path: str, params: Optional[dict] = None):
    try:
        r = httpx.get(f"{SERVICES[service]}{path}", params=_clean(params), timeout=30)
        return r.json()
    except Exception as e:
        log.error("proxy GET %s%s failed: %s", service, path, e)
        return {"error": str(e)}


def _post_checked(
    service: str, path: str, payload: dict, timeout: float, headers: Optional[dict] = None
):
    """POST to a downstream service, surfacing failure as failure.

    Unlike the inherited _post/_get helpers this does NOT collapse errors into
    a 200-OK ``{"error": str(e)}`` body, and it never puts ``str(e)`` in a log
    or response — httpx exception text can embed the request URL and its query
    params (how the eligibility member_id leak happened). Downstream status
    codes and JSON bodies are relayed as-is; transport failures map to typed
    gateway errors with only the exception CLASS logged. ``headers`` may carry
    a service-to-service secret — it must never appear in a log record.
    """
    try:
        r = httpx.post(
            f"{SERVICES[service]}{path}", json=payload, timeout=timeout, headers=headers
        )
    except httpx.TimeoutException:
        log.error("proxy POST %s%s timed out after %.0fs", service, path, timeout)
        raise HTTPException(status_code=504, detail=f"{service} service timed out")
    except httpx.HTTPError as e:
        log.error("proxy POST %s%s transport error: %s", service, path, type(e).__name__)
        raise HTTPException(status_code=502, detail=f"{service} service unreachable")
    try:
        body = r.json()
    except ValueError:
        log.error("proxy POST %s%s returned non-JSON status=%s", service, path, r.status_code)
        raise HTTPException(status_code=502, detail=f"{service} service returned a bad response")
    if r.status_code >= 400:
        # Relay the downstream error status; detail comes from the downstream
        # body only if it is the standard FastAPI shape (a plain "detail"
        # string), otherwise stays generic.
        detail = body.get("detail") if isinstance(body, dict) else None
        if not isinstance(detail, str):
            detail = f"{service} service error"
        raise HTTPException(status_code=r.status_code, detail=detail)
    return body
