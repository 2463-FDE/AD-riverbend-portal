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
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from config import settings
from db import get_db
from logging_config import configure
from models import User
from security import (
    ai_cache_get,
    ai_cache_key,
    ai_cache_set,
    check_ai_rate_limit,
    consume_ai_global_budget,
    create_session,
    destroy_session,
    get_session,
    verify_password,
)

log = configure(settings.service_name)
app = FastAPI(title="Riverbend gateway", version="1.4.0")

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


@app.get("/healthz")
def healthz():
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


def _reserve_ai_budget() -> None:
    """Consume one slot of the aggregate daily spend ceiling, or reject (ADR 0007).

    Called on the paid path only (after a cache miss), so the global counter
    tracks actual Bedrock fan-outs, not cache hits or per-user-rejected
    requests. Fails closed: a Redis fault here means we cannot verify the spend
    ceiling, so we do not spend.
    """
    try:
        retry_after = consume_ai_global_budget(settings.ai_rate_limit_global_per_day)
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


@app.post("/ai/intake-instructions")
def proxy_intake_instructions(payload: dict, session: dict = Depends(_ai_rate_limited)):
    # Closed-vocabulary body → identical facts yield the same checklist, so a
    # response cache collapses retries/double-clicks and repeat identical
    # intakes into one paid call. Cache read is best-effort (a fault degrades to
    # a paid call, never an error) and does NOT consume the spend ceiling — a
    # hit costs nothing, so it must not count against the aggregate budget.
    cache_key = ai_cache_key(payload)
    cached = ai_cache_get(cache_key)
    if cached is not None:
        return cached
    # Cache miss → this will be a paid fan-out; reserve aggregate budget first.
    _reserve_ai_budget()
    # Deliberately NOT _post: that helper swallows failures into a 200-OK
    # {"error": str(e)} body, and str(e) on an httpx error can embed the
    # request URL (the member_id leak class). New routes use _post_checked.
    result = _post_checked(
        "ai",
        "/intake-instructions",
        payload,
        timeout=settings.ai_read_timeout_seconds,
        # Service-to-service auth: ai-assistant refuses calls without this
        # header, so a direct (gateway-bypassing) caller cannot reach the paid
        # LLM path even if the service port were ever exposed. Value is a
        # secret — _post_checked never logs headers.
        headers={"X-Internal-Auth": settings.ai_proxy_shared_secret},
    )
    # Only successful responses reach here (_post_checked raises on failure), so
    # only good checklists are cached. Best-effort write.
    ai_cache_set(cache_key, result, settings.ai_cache_ttl_seconds)
    return result


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
