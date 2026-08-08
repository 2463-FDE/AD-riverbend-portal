"""
records-service — patient + records read façade (FHIR-ish).

Serves patient demographics and a patient's encounters/records to the portal.
"""
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import matching
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
    RelevantRecordItem,
    RelevantRecords,
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
    except SQLAlchemyError as e:
        log.error("list_patients: database error (%s)", type(e).__name__)
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
    except SQLAlchemyError as e:
        log.error(
            "get_patient: database error for patient_id=%s (%s)",
            patient_id,
            type(e).__name__,
        )
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
    except SQLAlchemyError as e:
        log.error(
            "get_patient_records: database error for patient_id=%s (%s)",
            patient_id,
            type(e).__name__,
        )
        raise HTTPException(status_code=503, detail="database unavailable")

    return PatientChart(patient_id=patient_id, encounters=chart)


# Values that mean "this field was assessed and is empty", not an allergy or a
# medication literally named "none known". Ported from eval/rag/data.py
# (_NO_ALLERGY_SENTINELS): without it, the seed's own patient 1601 — whose
# allergies column reads "none known" — would open with a phantom allergy at the
# top of the panel, which is worse than no panel at all.
_ASSESSED_EMPTY = {"", "none", "none known", "nka", "no known allergies", "n/a", "-"}


def _has_clinical_content(value: str | None) -> bool:
    return bool(value) and value.strip().lower() not in _ASSESSED_EMPTY


# Rows sharing the opened patient's SSN, normalized in the WHERE clause. This is
# a per-chart-open path, so the whole `ssn IS NOT NULL` population must never be
# pulled into this process; the expression mirrors matching.normalize_ssn's
# digits-only rule over the existing plaintext column and stores nothing.
# Sequential scan by design — D8 (no indexes) is a registered deliberate defect.
_SSN_MATES_SQL = text(
    "SELECT id, name, dob, ssn, address FROM patients "
    r"WHERE ssn IS NOT NULL AND regexp_replace(ssn, '\D', '', 'g') = :normalized"
)

# Rank order. An allergy a clinician has not seen is the RIV-160 harm; a
# medication list is the next thing they reach for; everything else ranks by
# recency alone.
_REASON_RANK = {"allergy": 0, "medication": 1, "recent": 2}


@app.get("/patients/{patient_id}/relevant-records", response_model=RelevantRecords)
def get_relevant_records(patient_id: int, db: Session = Depends(get_db)):
    """The few records worth reading first on opening this chart, plus whether
    this chart may be one of several for the same person.

    Deterministic salience ranking, not semantic retrieval: a chart open carries
    no query text to embed, so "relevance" here is a stated rule a clinician can
    see (the ``reason`` on every item) rather than a similarity score they
    cannot. The serving path contains no embedding code at all, which is how
    W2-SPEC-13 holds by construction rather than by budget discipline.

    Every query filters on the OPENED patient_id. Records from a sibling chart
    never enter this response even when the charts are a candidate duplicate —
    that is query-time unioning, rejected in ADR 0005 because it masks the
    intake defect and lends the fragmentation authority. The disclosure is the
    honest alternative: say the record set may be incomplete, name nothing, and
    let a human merge the charts.

    DEBT D11 (IDOR): like every other route here, a valid session is required
    but is never checked against {patient_id}. Inherited in kind, not widened —
    no new cross-patient query surface, no search parameter, no new capability.
    """
    try:
        patient = db.get(Patient, patient_id)
        if patient is None:
            raise HTTPException(status_code=404, detail="patient not found")

        max_scan = settings.relevant_records_max_scan
        encounters = (
            db.execute(
                select(Encounter)
                .where(Encounter.patient_id == patient_id)
                .order_by(Encounter.id)
            )
            .scalars()
            .all()
        )

        scanned: list[tuple[str, Encounter, Record]] = []
        # N+1: one query per encounter (deliberate — D8; do not collapse to a
        # join). Bounded by max_scan, so a large chart costs a fixed ceiling of
        # queries rather than one per encounter forever.
        for enc in encounters:
            if len(scanned) >= max_scan:
                break
            if _has_clinical_content(enc.allergies):
                reason = "allergy"
            elif _has_clinical_content(enc.medications):
                reason = "medication"
            else:
                reason = "recent"
            recs = (
                db.execute(
                    select(Record)
                    .where(Record.encounter_id == enc.id)
                    .order_by(Record.id)
                )
                .scalars()
                .all()
            )
            for rec in recs:
                if len(scanned) >= max_scan:
                    break
                scanned.append((reason, enc, rec))

        disclosure = _duplicate_disclosure(db, patient)
    except SQLAlchemyError as e:
        log.error(
            "get_relevant_records: database error for patient_id=%s (%s)",
            patient_id,
            type(e).__name__,
        )
        raise HTTPException(status_code=503, detail="database unavailable")

    scanned.sort(key=lambda t: (_REASON_RANK[t[0]], _sort_time(t[1]), t[2].id))
    items = [
        RelevantRecordItem(
            record_id=rec.id,
            kind=rec.kind,
            title=rec.title,
            occurred_at=enc.occurred_at,
            reason=reason,
        )
        for reason, enc, rec in scanned[: settings.relevant_records_max_items]
    ]
    # patient_id and counts only (PHI policy rule 2). The disclosure is an enum,
    # not a list of sibling ids, so it is safe to log and useful to have.
    log.info(
        "relevant-records patient_id=%s scanned=%s returned=%s disclosure=%s",
        patient_id,
        len(scanned),
        len(items),
        disclosure,
    )
    return RelevantRecords(
        patient_id=patient_id, duplicate_disclosure=disclosure, items=items
    )


def _sort_time(enc: Encounter) -> float:
    """Newest first within a reason band. A missing date sorts oldest rather
    than raising — an undated encounter must not blank the panel."""
    occurred = getattr(enc, "occurred_at", None)
    if occurred is None:
        return 0.0
    try:
        return -occurred.timestamp()
    except (AttributeError, OSError, ValueError):
        return 0.0


def _duplicate_disclosure(db: Session, patient: Patient) -> str:
    """"candidate" iff the OPENED chart sits in a candidate-duplicate component.

    Live evaluation, not a read of the review queue: the queue records what a
    human decided, and a decision is not a merge. A chart stays incomplete until
    HIM actually merges it, so the disclosure has to survive dispositions.

    Ambiguous, non-mergeable, no-SSN and no-SSN-mate rows all disclose nothing
    (owner decision, W2-SPEC-3): telling a clinician their record set may be
    incomplete on no evidence is its own harm.
    """
    normalized = matching.normalize_ssn(patient.ssn or "")
    if not matching.is_valid_ssn(normalized):
        # Tier 2 (fuzzy name + DOB) is deferred, so a chart with no usable SSN
        # has no detectable siblings and gets no disclosure — W2's detection
        # floor, named as an accepted residual in the plan.
        return "none"
    rows = db.execute(_SSN_MATES_SQL, {"normalized": normalized}).mappings().all()
    status = matching.status_for(rows, patient.id)
    return "candidate" if status == "candidate" else "none"


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
    except SQLAlchemyError as e:
        log.error("search_records: database error (%s)", type(e).__name__)
        raise HTTPException(status_code=503, detail="database unavailable")

    return [RecordSearchHit.model_validate(r) for r in rows]
