"""
scheduling-service — appointment slots (FHIR Appointment / Slot shaped).

Read endpoints use the SQLAlchemy ORM. Booking deliberately still goes through
the legacy raw-psycopg2 path in book.py to preserve the check-then-insert race.
"""
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import select, union_all
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

# The status the day queue excludes. Shared by the cancel writer and the day
# reader in THIS module so those two cannot drift — a cancel that stored a
# different spelling would silently put the visit back in the front-desk queue.
#
# The claim stops at this module, deliberately, because two other producers of
# the same column cannot import it: `book.py` is the frozen raw-psycopg2 path
# with `'confirmed'` inline in SQL, and `db/seed/generate_seed.py:290` emits all
# three values as literals. There is no shared Python library here (ADR 0001).
# `appointments.status` is also free TEXT with no CHECK (db/schema.sql:84), so
# the vocabulary is a convention the database does not enforce. Changing this
# value does NOT migrate rows already written with the old spelling.
CANCELLED_STATUS = "cancelled"

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

    Cancelled visits are excluded (``FE-R34``). The queue answers "who is coming
    to this clinic today", and a cancelled visit is not — leaving them in means a
    front desk checks in a patient who cancelled, and means name, MRN and reason
    are displayed for a visit that should no longer be active. The predicate is
    an **exclusion**, not an allowlist, for the reason given at the ``.where``.
    Completed visits stay: the desk needs to see who has already been seen today.

    There is deliberately no ``provider_id`` filter. The only route from an
    appointment to a provider id is ``appointments.slot_id`` → ``slots``, and
    that column has no foreign key (db/schema.sql) while ``book()`` inserts any
    positive slot_id without checking the slot exists. A join through it is an
    inner join over an unenforced reference, so an appointment with a missing or
    stale slot row would appear in this day queue and silently vanish from a
    per-provider one — a clinician missing a visit with no error shown. A real
    by-provider view needs provider identity stored on the appointment, which is
    a migration and belongs with the RIV-175 slot/appointment work (W5).

    The visit time is ``appointments.scheduled_for`` falling back to
    ``slots.start_at``, never ``scheduled_for`` alone. That column is nullable
    with no default and the write path never populates it: the booking UI posts
    only ``{patient_id, slot_id, provider, reason}``
    (frontend/app/appointments/page.tsx:62), ``BookingRequest.scheduled_for``
    defaults to ``None``, and ``insert_appointment`` writes the NULL. Since
    ``NULL >= x`` is NULL in SQL, filtering on the column alone returns nothing
    but seeded rows — correct-looking in dev, empty in production.

    The fallback is written as a UNION ALL of two branches, not as a filter on
    ``COALESCE(scheduled_for, slots.start_at)`` (codex r6, ADR 0018). A
    predicate on that expression is computed across an outer join, so no B-tree
    index can serve it and Postgres scans all of ``appointments`` for every day
    requested — the page limit bounds rows returned, not rows scanned. Each
    branch instead filters one indexed column (migration 009):

    * rows with their own ``scheduled_for`` in the window — never joined to
      ``slots``, so a missing or stale slot row cannot drop them;
    * rows with ``scheduled_for IS NULL`` whose slot's ``start_at`` is in the
      window. The inner join here is the predicate itself — under the old
      COALESCE an unresolvable slot left the visit time NULL and the window
      excluded the row, and a join with no match excludes it identically.

    The ``IS NULL`` guard is what keeps the branches disjoint — without it a
    row with both times in the window is returned twice and paginates wrong.
    An appointment with neither a ``scheduled_for`` nor a resolvable slot is
    still absent, and that is honest — nothing in the database says which day
    it belongs to.
    """
    try:
        start_utc, end_utc = _clinic_day_bounds(day)
    except OverflowError:
        # `date` accepts up to 9999-12-31, and the end edge is day + 1. Left
        # unguarded this raises out of the handler as a 500 with a plaintext
        # body, which the gateway's checked GET reports as "bad response" — an
        # unparseable request diagnosed as a transport fault.
        raise HTTPException(status_code=422, detail="date is outside the supported range")

    # Each branch filters one indexed column; the docstring owns why this is a
    # UNION ALL and not a COALESCE predicate. Both windows carry the same bound
    # values, and the IS NULL guard on the slot branch keeps them disjoint.
    scheduled = (
        select(
            Appointment.id.label("appointment_id"),
            Appointment.scheduled_for.label("visit_at"),
        )
        .where(Appointment.scheduled_for >= start_utc)
        .where(Appointment.scheduled_for < end_utc)
    )
    from_slot = (
        select(
            Appointment.id.label("appointment_id"),
            Slot.start_at.label("visit_at"),
        )
        .join(Slot, Slot.id == Appointment.slot_id)
        .where(Appointment.scheduled_for.is_(None))
        .where(Slot.start_at >= start_utc)
        .where(Slot.start_at < end_utc)
    )
    day_rows = union_all(scheduled, from_slot).subquery("day")

    stmt = (
        select(Appointment, Patient.name, Patient.mrn, day_rows.c.visit_at)
        .join(day_rows, day_rows.c.appointment_id == Appointment.id)
        .join(Patient, Patient.id == Appointment.patient_id, isouter=True)
        # Exclusion, never an allowlist. `status` is free TEXT with no CHECK
        # constraint (db/schema.sql:84), so `status IN ('confirmed','completed')`
        # would silently drop any value added later — 'checked_in', 'arrived',
        # 'no_show' — which is the same silent-drop class as the FK-less inner
        # join removed from this query in codex r1. An unrecognised status shows
        # up in the queue; only an explicit cancellation is hidden. Wrong in the
        # visible direction, which is the one a front desk can correct.
        # 'completed' stays: the desk needs to see who has already been seen today.
        # One site, on the outer query, so the two branches cannot drift apart.
        .where(Appointment.status != CANCELLED_STATUS)
        # id breaks ties: appointment times collide heavily (the seed alone has
        # five on one timestamp), and Postgres gives no stable order for equal
        # sort keys across separate queries — so an unbroken tie means a paging
        # caller can see one row twice and another not at all.
        .order_by(day_rows.c.visit_at, Appointment.id)
        # One past the page, so "is there more" is answered without a COUNT.
        .limit(limit + 1)
        .offset(offset)
    )

    try:
        rows = db.execute(stmt).all()
    except Exception as e:
        # The exception CLASS, never log.exception and never str(e). This query
        # is the one read in the service whose result set is cross-patient PHI —
        # name, MRN and free-text reason for every patient in the day — and a
        # driver error raised mid-fetch can carry row data in its message, which
        # log.exception would render into the traceback. The class is what
        # separates "database down" from "programming error"; the rest is not
        # worth a PHI log line. Same rule as the gateway's _post_checked.
        # The sibling reads here still use log.exception (inherited D1 debt,
        # docs/todo.md TODO-33) — not swept in this diff.
        log.error(
            "failed to list the day schedule for %s: %s", day.isoformat(), type(e).__name__
        )
        raise HTTPException(status_code=503, detail="database unavailable")

    has_more = len(rows) > limit
    items = []
    for appointment, patient_name, mrn, when in rows[:limit]:
        out = ScheduledVisitOut.model_validate(appointment)
        out.patient_name = patient_name
        out.mrn = mrn
        # The time the row was placed on this day by — the raw column would be
        # null for anything the booking UI wrote.
        out.scheduled_for = when
        items.append(out)

    # PHI rule: the window and the count, never a name, MRN or visit reason.
    log.info("listed %d appointments for %s", len(items), day.isoformat())
    return DayScheduleResponse(
        items=items,
        count=len(items),
        has_more=has_more,
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

    appt.status = CANCELLED_STATUS
    try:
        db.commit()
    except Exception:
        db.rollback()
        log.exception("failed to cancel appointment %s", appointment_id)
        raise HTTPException(status_code=503, detail="database unavailable")

    log.info("cancelled appointment %s", appointment_id)
    return CancelResponse(appointment_id=appointment_id, status=CANCELLED_STATUS)
