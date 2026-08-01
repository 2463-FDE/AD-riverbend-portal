"""
scheduling-service — appointment slots (FHIR Appointment / Slot shaped).

Read endpoints use the SQLAlchemy ORM. Booking deliberately still goes through
the legacy raw-psycopg2 path in book.py to preserve the check-then-insert race.
"""
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from book import book
from config import settings
from db import get_db
from logging_config import configure
from models import Appointment, Patient, Provider, Slot
from schemas import (
    AppointmentListResponse,
    AppointmentOut,
    BookingRequest,
    BookingResponse,
    CancelResponse,
    DayScheduleResponse,
    ScheduledVisitOut,
    SlotListResponse,
    SlotOut,
)

log = configure(settings.service_name)

app = FastAPI(title="Riverbend scheduling-service")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": settings.service_name}


@app.get("/slots", response_model=SlotListResponse)
def list_slots(
    provider_id: Optional[int] = Query(None, gt=0),
    limit: int = Query(settings.default_page_limit, ge=1, le=settings.max_page_limit),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List open slots, joined to the provider name. Paginated."""
    stmt = (
        select(Slot, Provider.name)
        .join(Provider, Provider.id == Slot.provider_id, isouter=True)
        .where(Slot.status == "open")
    )
    if provider_id is not None:
        stmt = stmt.where(Slot.provider_id == provider_id)
    stmt = stmt.order_by(Slot.start_at).limit(limit).offset(offset)

    try:
        rows = db.execute(stmt).all()
    except Exception:
        log.exception("failed to list slots")
        raise HTTPException(status_code=503, detail="database unavailable")

    items = []
    for slot, provider_name in rows:
        out = SlotOut.model_validate(slot)
        out.provider = provider_name
        items.append(out)

    log.info("listed %d open slots (provider_id=%s)", len(items), provider_id)
    return SlotListResponse(items=items, count=len(items), limit=limit, offset=offset)


@app.get("/appointments", response_model=AppointmentListResponse)
def list_appointments(
    patient_id: int = Query(..., gt=0),
    db: Session = Depends(get_db),
):
    """List a patient's appointments, most recent first."""
    stmt = (
        select(Appointment)
        .where(Appointment.patient_id == patient_id)
        .order_by(Appointment.created_at.desc())
    )
    try:
        rows = db.execute(stmt).scalars().all()
    except Exception:
        log.exception("failed to list appointments for patient %s", patient_id)
        raise HTTPException(status_code=503, detail="database unavailable")

    items = [AppointmentOut.model_validate(a) for a in rows]
    log.info("listed %d appointments for patient %s", len(items), patient_id)
    return AppointmentListResponse(items=items, count=len(items))


def _clinic_day_bounds(day: date) -> tuple[datetime, datetime]:
    """Half-open UTC window ``[start, end)`` covering one clinic-local calendar day.

    Both edges are built in the clinic's zone and converted afterwards. Doing the
    arithmetic on the UTC value instead — ``start_utc + timedelta(days=1)`` — is
    the failure worth naming: it is a true +24h, so the spring-forward day runs an
    hour into the next clinic day and the fall-back day loses its last hour of
    appointments. Proven by the DST cases in tests/test_schedule_day_view.py.
    """
    tz = ZoneInfo(settings.clinic_timezone)
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


@app.get("/schedule", response_model=DayScheduleResponse)
def list_day_schedule(
    day: date = Query(..., alias="date", description="Clinic-local calendar day, YYYY-MM-DD"),
    provider_id: Optional[int] = Query(None, gt=0),
    limit: int = Query(settings.default_page_limit, ge=1, le=settings.max_page_limit),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """One clinic day's appointments across all patients — the front-desk queue.

    Why this exists: ``GET /appointments`` requires a ``patient_id``, so a day
    view could previously only be assembled by fanning out one request per
    patient, which is the D8 N+1 pattern this codebase already suffers from in
    the records read path. This is a single joined query instead.

    Scope, stated deliberately because the response is cross-patient PHI: the
    window is one clinic-local day and the result is paginated under the same
    guardrails as ``/slots``, so this is a work queue and not a bulk export.
    Authorization is unchanged — the gateway still checks only that a session
    exists (D11, W4 owns binding a session to a patient). This endpoint does not
    widen that gap, and it must not be read as a decision about it.
    """
    start_utc, end_utc = _clinic_day_bounds(day)

    stmt = (
        select(Appointment, Patient.name, Patient.mrn)
        .join(Patient, Patient.id == Appointment.patient_id, isouter=True)
        .where(Appointment.scheduled_for >= start_utc)
        .where(Appointment.scheduled_for < end_utc)
    )
    if provider_id is not None:
        # appointments carry only a provider NAME; the id lives on the slot.
        stmt = stmt.join(Slot, Slot.id == Appointment.slot_id).where(
            Slot.provider_id == provider_id
        )
    stmt = stmt.order_by(Appointment.scheduled_for).limit(limit).offset(offset)

    try:
        rows = db.execute(stmt).all()
    except Exception:
        log.exception("failed to list the day schedule for %s", day.isoformat())
        raise HTTPException(status_code=503, detail="database unavailable")

    items = []
    for appointment, patient_name, mrn in rows:
        out = ScheduledVisitOut.model_validate(appointment)
        out.patient_name = patient_name
        out.mrn = mrn
        items.append(out)

    # PHI rule: the window and the count, never a name, MRN or visit reason.
    log.info(
        "listed %d appointments for %s (provider_id=%s)",
        len(items),
        day.isoformat(),
        provider_id,
    )
    return DayScheduleResponse(
        items=items,
        count=len(items),
        limit=limit,
        offset=offset,
        date=day.isoformat(),
        timezone=settings.clinic_timezone,
    )


@app.post("/appointments", status_code=201, response_model=BookingResponse)
def create_appointment(req: BookingRequest):
    """Book a slot for a patient.

    Delegates to book.py, which performs a read-check-then-insert with no UNIQUE
    constraint on slot_id and no idempotency key (intentional race — D5).
    """
    try:
        appointment_id = book(
            req.patient_id,
            req.slot_id,
            provider=req.provider,
            reason=req.reason,
            location=req.location,
            scheduled_for=req.scheduled_for,
        )
    except Exception:
        log.exception(
            "booking failed for patient=%s slot=%s", req.patient_id, req.slot_id
        )
        raise HTTPException(status_code=503, detail="database unavailable")

    if appointment_id is None:
        log.info("slot %s already taken (patient=%s)", req.slot_id, req.patient_id)
        return BookingResponse(status="slot_taken")

    log.info(
        "booked appointment %s (patient=%s slot=%s)",
        appointment_id,
        req.patient_id,
        req.slot_id,
    )
    return BookingResponse(appointment_id=appointment_id, status="confirmed")


@app.post("/appointments/{appointment_id}/cancel", response_model=CancelResponse)
def cancel_appointment(appointment_id: int, db: Session = Depends(get_db)):
    """Cancel an appointment. 404 if it does not exist."""
    appt = db.get(Appointment, appointment_id)
    if appt is None:
        raise HTTPException(status_code=404, detail="appointment not found")

    appt.status = "cancelled"
    try:
        db.commit()
    except Exception:
        db.rollback()
        log.exception("failed to cancel appointment %s", appointment_id)
        raise HTTPException(status_code=503, detail="database unavailable")

    log.info("cancelled appointment %s", appointment_id)
    return CancelResponse(appointment_id=appointment_id, status="cancelled")
