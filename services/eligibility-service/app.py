"""
eligibility-service — real-time payer eligibility (X12 270/271).

Front desk (and intake-service, inline) hit this before a visit to confirm a
member's coverage is active. The actual clearinghouse round-trip lives in
check.py.

D4 / RIV-088 / RIV-141 (fixed, ADR 0010): check() now bounds the payer call with
a timeout + retry + in-process circuit breaker and raises typed PayerError
subclasses. This handler maps those to a clean degraded response and — critically
— logs the exception class only and returns a generic error string, never
str(e): the payer request URL carries member_id, so stringifying the failure
would leak PHI into both the log and the response body (docs/phi-logging-policy.md).
"""
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query

from breaker import PayerError
from check import check
from config import settings
from logging_config import configure
from schemas import EligibilityResponse

log = configure(settings.service_name)
app = FastAPI(title="Riverbend eligibility-service", version="1.2.0")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": settings.service_name}


@app.get("/eligibility", response_model=EligibilityResponse)
def check_eligibility(insurance_id: str = Query(...)):
    insurance_id = (insurance_id or "").strip()
    if not insurance_id:
        raise HTTPException(status_code=422, detail="insurance_id must not be blank")

    checked_at = datetime.now(timezone.utc)
    try:
        result = check(insurance_id)
    except PayerError as e:
        # The payer was unreachable / timed out / the breaker is open. Surface a
        # clean "unknown" response rather than 500-ing the caller. Log the
        # exception CLASS only and return a generic error literal — never str(e)
        # or insurance_id (the payer request URL embeds member_id; PHI rule 3).
        log.error("eligibility check failed (%s)", type(e).__name__)
        return EligibilityResponse(
            insurance_id=insurance_id,
            active=False,
            status="unknown",
            payer=settings.payer_name,
            raw_status=None,
            checked_at=checked_at,
            error="eligibility check failed",
        )

    active = bool(result.get("active"))
    return EligibilityResponse(
        insurance_id=result.get("insurance_id", insurance_id),
        active=active,
        status="active" if active else "inactive",
        payer=settings.payer_name,
        raw_status=result.get("raw_status"),
        checked_at=checked_at,
    )
