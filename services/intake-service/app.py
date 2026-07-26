"""
intake-service — multi-step patient registration + insurance + consent capture.

Both the front desk and the self-service portal POST a full intake payload here.
We create the patient chart, attach insurance coverage (if supplied), record the
signed consents, and verify payer eligibility before returning.

Inherited shortcomings (left as-is from the handoff):
  * D1 — REMEDIATED 2026-07: intake no longer logs the request body at all.
    It logs only an allowlisted, non-PHI metadata shape (schemas.log_metadata)
    — never a raw request string. Redacting the body was not enough: pattern
    redaction misses names/DOBs smuggled into free-text fields (Codex review).
    See docs/phi-logging-policy.md. The historical logs/intake-service.log
    still contains pre-fix PHI — open ops item.
  * D5 — no master patient index / match key: every /intake creates a brand new
    patients row, so one person forks into several charts (intake.yaml match_key:
    none).
  * D4 / RIV-088 / RIV-141 — PARTLY REMEDIATED 2026-07 (ADR 0010): eligibility
    is still verified on the request thread, but the call is now bounded by a
    timeout and an intake-side circuit breaker, and the seeded time.sleep(4.2)
    is gone. Registration is therefore slowed, never frozen, by a bad payer —
    including one that keeps answering slowly, whose latency counts against the
    breaker on its own (review r6).
    Full register-first / out-of-band re-verification (instant 201 + async
    verify) remains the complete fix and is still open — it needs a job/result
    store (see ADR 0010 and docs/debt-log.md D4).
  * Consents are inserted one at a time (a commit per consent).
"""
import json
import os
import time
from typing import Any, Optional

import httpx
import yaml
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from breaker import CircuitBreaker, EligibilityBreakerOpen
from config import settings
from db import get_db
from logging_config import configure
from models import Consent, InsuranceCoverage, Patient
from schemas import Demographics, Insurance, IntakeRequest, IntakeResponse, log_metadata

log = configure(settings.service_name)
app = FastAPI(title="Riverbend intake-service", version="1.3.0")

INTAKE_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "intake.yaml")

# Per-worker breaker on the intake -> eligibility hop (ADR 0010, review r4).
# Deliberately in-process, like eligibility-service's: no new infrastructure,
# fully reversible. Cost of per-worker state: with W workers, up to
# W x ELIGIBILITY_BREAKER_FAIL_THRESHOLD slow calls can still occur before every
# worker has opened its own circuit.
_breaker = CircuitBreaker(
    fail_threshold=settings.eligibility_breaker_fail_threshold,
    reset_seconds=settings.eligibility_breaker_reset_seconds,
)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": settings.service_name}


@app.get("/intake/config")
def intake_config():
    """Return the parsed intake.yaml so the front-desk UI can adapt its form."""
    try:
        with open(INTAKE_CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        log.error("intake config missing at %s", INTAKE_CONFIG_PATH)
        raise HTTPException(status_code=500, detail="intake config not found")
    except yaml.YAMLError as e:
        log.error("intake config parse error: %s", e)
        raise HTTPException(status_code=500, detail="intake config invalid")


@app.post("/intake", response_model=IntakeResponse, status_code=201)
def create_intake(req: IntakeRequest, db: Session = Depends(get_db)):
    started = time.time()

    # D1 (remediated 2026-07): the front desk still gets a record of every
    # registration, but we log only an allowlisted, non-PHI metadata shape —
    # never the request body or any raw request string. Redacting the body was
    # insufficient because pattern redaction misses names/DOBs smuggled into
    # free-text fields (Codex review). See docs/phi-logging-policy.md.
    log.info('POST /intake meta=%s', json.dumps(log_metadata(req)))

    # D5 (flagged, not fixed): no MPI / match-key lookup on (name, dob, ssn).
    # Every intake inserts a brand new chart, even for a returning patient.
    patient_id = _create_patient(db, req.demographics)

    if req.insurance is not None:
        _create_coverage(db, patient_id, req.insurance)

    # D4 / RIV-088 / RIV-141 (bounded, ADR 0010): eligibility verification still
    # runs on this request thread — it DOES delay the 201, by at most
    # ELIGIBILITY_TIMEOUT_SECONDS, and the intake-side breaker drops that to ~0
    # once the dependency is known-bad. So a slow/hung payer degrades
    # registration instead of freezing it (RIV-141), but this is not yet true
    # deferral. The patient row is already committed above, so a degraded result
    # only changes what the eligibility *field* reports, never whether the
    # patient is saved. Register-first + async re-verification is the remaining
    # follow-up (ADR 0010, docs/debt-log.md D4).
    eligibility = _verify_eligibility(req.insurance)

    _record_consents(db, patient_id, req.consents)

    elapsed = round(time.time() - started, 2)
    log.info("POST /intake 201 patient_id=%s elapsed=%.2fs", patient_id, elapsed)
    return IntakeResponse(patient_id=patient_id, elapsed_seconds=elapsed, eligibility=eligibility)


def _create_patient(db: Session, demo: Demographics) -> int:
    try:
        patient = Patient(
            name=demo.name,
            dob=demo.dob,
            ssn=demo.ssn,
            gender=demo.gender,
            address=demo.address,
            phone=demo.phone,
            email=demo.email,
            notes=demo.notes,
            created_via=demo.created_via,
        )
        db.add(patient)
        db.commit()
        db.refresh(patient)
        return patient.id
    except SQLAlchemyError as e:
        db.rollback()
        log.error("intake: failed to create patient: %s", e)
        raise HTTPException(status_code=503, detail="patient store unavailable")


def _create_coverage(db: Session, patient_id: int, ins: Insurance) -> None:
    try:
        coverage = InsuranceCoverage(
            patient_id=patient_id,
            payer_name=ins.payer_name,
            member_id=ins.member_id,
            group_number=ins.group_number,
            plan_type=ins.plan_type,
        )
        db.add(coverage)
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        log.error("intake: failed to record coverage for patient %s: %s", patient_id, e)
        raise HTTPException(status_code=503, detail="coverage store unavailable")


def _record_consents(db: Session, patient_id: int, kinds: list[str]) -> None:
    # Inefficient by design: one INSERT + COMMIT per consent (a separate
    # transaction round-trip each) rather than a single batched insert.
    for kind in kinds:
        try:
            db.add(Consent(patient_id=patient_id, kind=kind))
            db.commit()
        except SQLAlchemyError as e:
            db.rollback()
            log.error("intake: failed to record consent %s for patient %s: %s", kind, patient_id, e)


def _verify_eligibility(ins: Optional[Insurance]) -> Optional[dict[str, Any]]:
    if ins is None or not ins.member_id:
        return None

    # ADR 0010 / RIV-141: bounded best-effort verification, gated by an
    # intake-side circuit breaker. The timeout caps ONE registration's
    # worker-hold; the breaker caps the *sustained* cost, so a wedged
    # eligibility-service stops charging every front-desk save the full timeout
    # (adversarial review r4). Verification is best-effort either way — the
    # patient is already committed by the caller.
    try:
        _breaker.before_call()
    except EligibilityBreakerOpen:
        # Known-bad dependency: skip the outbound call entirely. No member_id in
        # this message (PHI policy rule 3).
        log.warning("intake: eligibility verification skipped, circuit open")
        return {"active": None, "status": "pending", "reason": "verification deferred"}

    # An admitted caller MUST record an outcome, including on an unexpected
    # exception — a half-open probe that records neither wedges the breaker shut.
    healthy = False
    try:
        result, healthy = _query_eligibility(ins)
    finally:
        if healthy:
            _breaker.record_success()
        else:
            _breaker.record_failure()
    return result


def _query_eligibility(ins: Insurance) -> tuple[dict[str, Any], bool]:
    """
    Call eligibility-service and shape the result.

    Returns (payload, healthy). `healthy` reports whether the DEPENDENCY is worth
    calling again — it drives the breaker and is never a coverage verdict. Two
    independent questions decide it, and conflating them is what earlier rounds
    got wrong:

      1. Was the answer USABLE? A definitive active/inactive is; so is a 4xx,
         which means eligibility-service rejected THIS request rather than
         failing (see the non-2xx branch). A timeout, a transport error, a 5xx,
         an unparseable body, or a shaped 2xx carrying no coverage verdict is not.
      2. Was it CHEAP? This breaker exists to bound how long a bad dependency
         holds intake workers, so latency counts against it on its own —
         whatever the answer was worth. A usable answer that burned the budget is
         still returned to the caller and still records a breaker failure
         (review r6).

    Both thresholds are latency, measured intake-side, so no new cross-service
    contract is needed and a downstream change cannot mis-signal them:

      * a DEGRADED answer (no verdict) is unhealthy at/over
        ELIGIBILITY_DEGRADED_SLOW_SECONDS (~1s). eligibility-service emits the
        same {"active": null, "status": "unknown"} both when its payer breaker
        short-circuits — milliseconds, costing this worker nothing — and when it
        spent its whole payer budget on a hanging payer. Treating all of them as
        healthy (review r4) left the breaker closed during the exact outage it
        guards (review r5); latency is what tells the two apart.
      * a DEFINITIVE answer gets a longer leash — ELIGIBILITY_SLOW_ANSWER_SECONDS
        (~2s) — because a real verdict is worth waiting for. That number is the
        FLOOR of the retried band, not the ceiling of a healthy attempt: a retry
        only happens after the first attempt's read timeout burned in full, so
        anchoring any higher lets the degrade-but-keep-answering payer (which
        answers in 2-4s, every save, forever) go on reading as healthy. That is
        RIV-088's partial-outage form and it is what this threshold exists to
        catch (review r6).

    Cost is the whole rule for the fast side too, so some outage modes (a payer
    refusing connections, a bad API key) are correctly read as healthy: they pin
    no worker, so they are not the RIV-141 mechanism, and suppressing a free call
    would only delay noticing the payer's recovery.

    (The seeded time.sleep(4.2) that produced the RIV-088 "spin" was removed — a
    synthetic block no timeout could bound.)
    """
    started = time.monotonic()
    try:
        resp = httpx.get(
            f"{settings.eligibility_url}/eligibility",
            params={"insurance_id": ins.member_id},
            timeout=settings.eligibility_timeout_seconds,
        )
    except httpx.TimeoutException:
        # Payer/eligibility too slow — do not block intake; verification deferred.
        # No member_id in this message.
        log.error("intake: eligibility check timed out")
        return {"active": None, "status": "pending", "reason": "verification timed out"}, False
    except Exception as e:
        # Broad on purpose (PHI policy rule 3): never stringify an outbound
        # exception here. The request URL carries insurance_id=<member_id> as a
        # query param, and httpx embeds the failing URL in its exception message —
        # so str(e) would leak a PHI-adjacent external identifier into the log AND
        # the /intake response. Log the exception class only, return a generic
        # degraded result for any transport failure.
        log.error("intake: eligibility check failed (%s)", type(e).__name__)
        return {"active": None, "status": "unknown", "reason": "eligibility check failed"}, False

    # Only a 2xx eligibility-shaped body is a definitive coverage answer. A
    # non-2xx response (e.g. a 500/503 {"detail": ...} from eligibility-service)
    # or a body that isn't the expected shape is never a coverage denial — map it
    # to "unknown", never "inactive". (raw_status is the HTTP code only, never
    # member_id — safe to log.)
    #
    # Whether it counts against the breaker depends on WHOSE fault it is. A 4xx
    # means eligibility-service rejected THIS request — a 422 on a blank or
    # malformed member_id, say — which says nothing about the dependency's
    # health. Counting those would let a handful of bad registrations (a botched
    # batch import, a scanner emitting whitespace) open the circuit and strip
    # eligibility verification from every OTHER patient for the reset window.
    # 408/429 are excluded from that carve-out and 5xx is a plain dependency
    # failure, matching check.py's transient/non-transient split.
    #
    # A caller-fault answer still has to have been CHEAP to read as healthy: a 422
    # that took two seconds to arrive held this worker exactly as long as a slow
    # verdict would have, and the breaker is about worker-hold (review r6). It is
    # judged on the definitive answer's threshold — eligibility-service reached a
    # conclusion about the request, it just wasn't a coverage one.
    #
    # `cheap` is computed BEFORE the `and`, deliberately not short-circuited: a slow
    # 5xx/408/429 is already unhealthy on fault, but the latency line is exactly the
    # diagnostic an on-call reader wants during a dependency incident, so it must
    # still be emitted.
    if resp.status_code // 100 != 2:
        caller_fault = 400 <= resp.status_code < 500 and resp.status_code not in (408, 429)
        log.error("intake: eligibility returned HTTP %s", resp.status_code)
        cheap = _answered_cheaply(
            started, settings.eligibility_slow_answer_seconds, "with an HTTP error"
        )
        return (
            {"active": None, "status": "unknown", "reason": "eligibility check failed"},
            caller_fault and cheap,
        )
    try:
        body = resp.json()
    except Exception:
        log.error("intake: eligibility returned a non-JSON body")
        return {"active": None, "status": "unknown", "reason": "eligibility check failed"}, False
    if not isinstance(body, dict) or ("status" not in body and "active" not in body):
        # A 2xx body that isn't eligibility-shaped — treat as degraded, not inactive.
        return {"active": None, "status": "unknown", "reason": "eligibility check failed"}, False

    # `active` is the authoritative tri-state (ADR 0010); `status` only carries
    # the finer detail, so DERIVE status from the boolean rather than trusting
    # whatever string the body supplied. Identity tests, because `None` is falsy
    # but is not False: a body carrying no boolean verdict must read "unknown".
    # Reading it as "inactive" would tell the front desk a patient is uninsured
    # because of an outage (the r3 misclassification, one layer down); reading it
    # as "active" on the strength of the string alone — a {"status": "active"}
    # with no `active` key, from a captive portal or a future responder — is the
    # same defect in the opposite direction, and since r5 it would also hold the
    # breaker closed while every call paid full latency.
    active = body.get("active")
    definitive = active is True or active is False
    body["status"] = ("active" if active else "inactive") if definitive else "unknown"

    if definitive:
        # A real coverage verdict is always RETURNED — a denial is never a breaker
        # failure and a slow-but-correct answer is still worth having — but the
        # dependency is only healthy if the answer did not hold this worker as long
        # as a retried payer attempt costs (review r6). Past that the payer is
        # degrading while still answering: bounded per call by the timeout,
        # unbounded in aggregate until the circuit opens — RIV-088's partial outage.
        return body, _answered_cheaply(
            started, settings.eligibility_slow_answer_seconds, "with a coverage verdict"
        )

    # Degraded: eligibility-service is up and shaped its reply, but gave no
    # coverage verdict. Judged on the tighter threshold — a reply worth nothing
    # has to be free, not merely fast — see the docstring.
    return body, _answered_cheaply(started, settings.eligibility_degraded_slow_seconds, "degraded")


def _answered_cheaply(started: float, threshold_seconds: float, kind: str) -> bool:
    """Did eligibility answer without holding this intake worker past
    `threshold_seconds`? Latency is half of the breaker's health signal (review
    r6): the other half is whether the answer was usable, which the caller has
    already decided.

    Logs the latency and a call-site literal only. Every other value in scope
    here comes out of a downstream response body, and this module never echoes
    downstream content into a log (PHI policy rule 3) — `kind` must therefore stay
    a constant, never anything read off the wire.
    """
    elapsed = time.monotonic() - started
    if elapsed < threshold_seconds:
        return True
    log.error(
        "intake: eligibility answered %s after %.2fs — counting against the circuit",
        kind,
        elapsed,
    )
    return False
