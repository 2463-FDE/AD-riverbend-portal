"""
eligibility-service — real-time payer eligibility (X12 270/271).

Front desk (and intake-service, inline) hit this before a visit to confirm a
member's coverage is active. The actual clearinghouse round-trip lives in
check.py.

Inherited shortcoming (left as-is from the handoff):
  * D4 — check() calls the payer with no timeout / retry / circuit breaker, and
    it sits directly on the intake request path (RIV-088). The cohort's fix is to
    bound that call; we deliberately do NOT add a timeout here.
"""
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query

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
    except Exception as e:
        # The payer call failed or hung. There is intentionally no timeout /
        # circuit breaker yet (D4 — the cohort's fix); surface a clean inactive
        # response with an error note rather than 500-ing the caller.
        log.error("eligibility check failed for %s: %s", insurance_id, e)
        return EligibilityResponse(
            insurance_id=insurance_id,
            active=False,
            payer=settings.payer_name,
            raw_status=None,
            checked_at=checked_at,
            error=str(e),
        )

    return EligibilityResponse(
        insurance_id=result.get("insurance_id", insurance_id),
        active=bool(result.get("active")),
        payer=settings.payer_name,
        raw_status=result.get("raw_status"),
        checked_at=checked_at,
    )
