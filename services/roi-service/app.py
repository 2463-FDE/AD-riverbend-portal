"""
roi-service — Release of Information (ROI) request intake + disclosures.

Replaces the old "staff emails a PDF" workflow: create an ROI request, fulfill
it (release records to the named recipient), and read back what was disclosed.
"""
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from config import settings
from db import get_db
from logging_config import configure
from models import Disclosure, Patient, Record, RoiRequest
from schemas import (
    DisclosureRecords,
    FulfillResult,
    RecordOut,
    RoiRequestCreate,
    RoiRequestOut,
)

log = configure(settings.service_name)

app = FastAPI(title="Riverbend roi-service")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": settings.service_name}


@app.get("/roi/requests", response_model=list[RoiRequestOut])
def list_roi_requests(
    patient_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
):
    """List ROI requests, optionally filtered by patient."""
    try:
        stmt = select(RoiRequest)
        if patient_id is not None:
            stmt = stmt.where(RoiRequest.patient_id == patient_id)
        rows = db.execute(stmt.order_by(RoiRequest.id.desc())).scalars().all()
    except SQLAlchemyError:
        log.exception("list_roi_requests: database error")
        raise HTTPException(status_code=503, detail="database unavailable")

    return [RoiRequestOut.model_validate(r) for r in rows]


@app.post("/roi/requests", response_model=RoiRequestOut, status_code=201)
def create_roi_request(payload: RoiRequestCreate, db: Session = Depends(get_db)):
    """Create an ROI request. Patient must exist; status defaults to 'pending'."""
    try:
        patient = db.get(Patient, payload.patient_id)
        if patient is None:
            raise HTTPException(status_code=404, detail="patient not found")

        req = RoiRequest(
            patient_id=payload.patient_id,
            requested_by=payload.requested_by,
            recipient=payload.recipient,
            recipient_type=payload.recipient_type,
            purpose=payload.purpose,
            date_range_start=payload.date_range_start,
            date_range_end=payload.date_range_end,
            status="pending",
        )
        db.add(req)
        db.commit()
        db.refresh(req)
    except HTTPException:
        raise
    except SQLAlchemyError:
        db.rollback()
        log.exception("create_roi_request: database error")
        raise HTTPException(status_code=503, detail="database unavailable")

    return RoiRequestOut.model_validate(req)


@app.post("/roi/requests/{request_id}/fulfill", response_model=FulfillResult)
def fulfill_roi_request(request_id: int, db: Session = Depends(get_db)):
    """
    Fulfill an ROI request: mark it 'fulfilled', record a disclosures row, and
    return the patient's records.

    ==========================================================================
    DEBT D12 — HIPAA Privacy Rule shortcuts (deliberate, do NOT "fix"):
      * NO check for a signed 45 CFR 164.508 authorization before releasing PHI.
      * NO honoring of any 45 CFR 164.522 agreed restriction on the patient.
      * NO accounting-of-disclosures audit_logs entry is written. The only trace
        is the bare disclosures row below, which itself has no authorization_id,
        no purpose, and no restriction tracking — so a true 164.528 accounting
        of disclosures cannot be produced.
    ==========================================================================
    """
    try:
        req = db.get(RoiRequest, request_id)
        if req is None:
            raise HTTPException(status_code=404, detail="roi request not found")

        # D12: release happens with no authorization / restriction enforcement.
        req.status = "fulfilled"

        disclosure = Disclosure(
            patient_id=req.patient_id,
            roi_request_id=req.id,
            disclosed_to=req.recipient,
            # no authorization_id, no purpose, no restriction tracking
        )
        db.add(disclosure)

        records = (
            db.execute(
                select(Record)
                .where(Record.patient_id == req.patient_id)
                .order_by(Record.id)
            )
            .scalars()
            .all()
        )

        db.commit()
        db.refresh(disclosure)
    except HTTPException:
        raise
    except SQLAlchemyError:
        db.rollback()
        log.exception("fulfill_roi_request: database error for request_id=%s", request_id)
        raise HTTPException(status_code=503, detail="database unavailable")

    return FulfillResult(
        request_id=req.id,
        patient_id=req.patient_id,
        status=req.status,
        disclosure_id=disclosure.id,
        records=[RecordOut.model_validate(r) for r in records],
    )


@app.get("/disclosures/{patient_id}", response_model=DisclosureRecords)
def disclose(patient_id: int, db: Session = Depends(get_db)):
    """
    Legacy direct-disclosure surface (original D12).

    DEBT D12 (preserved): returns ALL of a patient's records with NO check for a
    valid 45 CFR 164.508 authorization, NO honoring of any 164.522 agreed
    restriction, and NO disclosure logged (who got what, when, under what
    authorization) — so an accounting-of-disclosures is impossible.
    """
    try:
        rows = (
            db.execute(
                select(Record)
                .where(Record.patient_id == patient_id)
                .order_by(Record.id)
            )
            .scalars()
            .all()
        )
    except SQLAlchemyError:
        log.exception("disclose: database error for patient_id=%s", patient_id)
        raise HTTPException(status_code=503, detail="database unavailable")

    return DisclosureRecords(
        patient_id=patient_id,
        records=[RecordOut.model_validate(r) for r in rows],
    )
