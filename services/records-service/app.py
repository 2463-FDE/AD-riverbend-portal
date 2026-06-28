"""
records-service — patient + records read façade (FHIR-ish).

Serves patient demographics and a patient's encounters/records to the portal.
"""
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from config import settings
from db import get_db
from logging_config import configure
from models import Encounter, Patient, Record
from schemas import (
    EncounterOut,
    EncounterWithRecords,
    PatientChart,
    PatientDetail,
    PatientPage,
    PatientSummary,
    RecordOut,
    RecordSearchHit,
)

log = configure(settings.service_name)

app = FastAPI(title="Riverbend records-service")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": settings.service_name}


@app.get("/patients", response_model=PatientPage)
def list_patients(
    q: str | None = Query(default=None, description="ILIKE filter on patient name"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Paginated patient list. `q` does a case-insensitive name match."""
    try:
        base = select(Patient)
        count_q = select(func.count()).select_from(Patient)
        if q:
            pattern = f"%{q}%"
            base = base.where(Patient.name.ilike(pattern))
            count_q = count_q.where(Patient.name.ilike(pattern))

        total = db.execute(count_q).scalar_one()
        rows = (
            db.execute(
                base.order_by(Patient.id).limit(limit).offset(offset)
            )
            .scalars()
            .all()
        )
    except SQLAlchemyError:
        log.exception("list_patients: database error")
        raise HTTPException(status_code=503, detail="database unavailable")

    return PatientPage(
        items=[PatientSummary.model_validate(p) for p in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get("/patients/{patient_id}", response_model=PatientDetail)
def get_patient(patient_id: int, db: Session = Depends(get_db)):
    """Patient demographics, or 404."""
    try:
        patient = db.get(Patient, patient_id)
    except SQLAlchemyError:
        log.exception("get_patient: database error for patient_id=%s", patient_id)
        raise HTTPException(status_code=503, detail="database unavailable")

    if patient is None:
        raise HTTPException(status_code=404, detail="patient not found")
    return PatientDetail.model_validate(patient)


@app.get("/patients/{patient_id}/records", response_model=PatientChart)
def get_patient_records(patient_id: int, db: Session = Depends(get_db)):
    """
    Assemble a patient's full chart: their encounters and, per encounter, its records.

    DEBT D11 (IDOR): patient_id is the sequential integer PK and is served to any
    caller with no verification that the caller owns / is authorized for it. A
    logged-in user can walk 1042, 1043, 1044... and pull anyone's chart.

    DEBT D8 (N+1): encounters are fetched first, then we loop and run ONE query per
    encounter to load that encounter's records (no JOIN, no selectinload).
    """
    # no ownership / authorization check
    try:
        encounters = (
            db.execute(
                select(Encounter)
                .where(Encounter.patient_id == patient_id)
                .order_by(Encounter.id)
            )
            .scalars()
            .all()
        )

        chart: list[EncounterWithRecords] = []
        # N+1: one extra query per encounter (deliberate — do not collapse to a join)
        for enc in encounters:
            recs = (
                db.execute(
                    select(Record)
                    .where(Record.encounter_id == enc.id)
                    .order_by(Record.id)
                )
                .scalars()
                .all()
            )
            chart.append(
                EncounterWithRecords(
                    encounter=EncounterOut.model_validate(enc),
                    records=[RecordOut.model_validate(r) for r in recs],
                )
            )
    except SQLAlchemyError:
        log.exception(
            "get_patient_records: database error for patient_id=%s", patient_id
        )
        raise HTTPException(status_code=503, detail="database unavailable")

    return PatientChart(patient_id=patient_id, encounters=chart)


@app.get("/records/search", response_model=list[RecordSearchHit])
def search_records(
    q: str = Query(..., min_length=1, description="free-text query"),
    db: Session = Depends(get_db),
):
    """
    Free-text search across records.

    DEBT D8: full-table ILIKE scan on records.body with NO supporting index and
    NO result limit. On a real chart corpus this scans every row every call.
    """
    try:
        # full-table scan on body — no index, no limit (deliberate debt)
        rows = (
            db.execute(
                select(Record).where(Record.body.ilike(f"%{q}%"))
            )
            .scalars()
            .all()
        )
    except SQLAlchemyError:
        log.exception("search_records: database error")
        raise HTTPException(status_code=503, detail="database unavailable")

    return [RecordSearchHit.model_validate(r) for r in rows]
