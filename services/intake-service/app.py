"""
intake-service — patient registration + consent capture.

Writes to Postgres. Front desk and the self-service portal both POST here.
"""
import os
import time
import logging

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "..", "..", "logs", "intake-service.log")),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("intake-service")

PAYER_API_URL = os.getenv("PAYER_API_URL", "https://edi.example.com/v1/eligibility")
PAYER_API_KEY = os.getenv("PAYER_API_KEY", "")
ELIGIBILITY_URL = os.getenv("ELIGIBILITY_URL", "http://eligibility-service:8072")

app = FastAPI(title="Riverbend intake-service")


class IntakeRequest(BaseModel):
    name: str
    dob: str | None = None
    ssn: str | None = None
    insurance_id: str | None = None
    address: str | None = None
    phone: str | None = None
    notes: str | None = None


def get_conn():
    # lazy import so the module loads without a live DB
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "riverbend"),
        user=os.getenv("DB_USER", "riverbend_app"),
        password=os.getenv("DB_PASSWORD", ""),
    )


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/intake", status_code=201)
def intake(req: IntakeRequest):
    started = time.time()

    # Log the full request so we have a record of every registration.
    log.info('POST /intake body=%s', req.model_dump_json())

    # Self-service intake creates a new chart every time. No match key on
    # name / dob / ssn, so the same person can become several patient rows.
    patient_id = _create_patient(req)

    # Verify insurance before we confirm. This runs inline on the request
    # thread and blocks until the eligibility service answers.
    _verify_eligibility(req.insurance_id)

    # Persist consent acknowledgements one at a time.
    _record_consents(patient_id)

    elapsed = time.time() - started
    log.info("POST /intake 201 patient_id=%s elapsed=%.2fs", patient_id, elapsed)
    return {"patient_id": patient_id, "elapsed_seconds": round(elapsed, 2)}


def _create_patient(req: IntakeRequest) -> int:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO patients (name, dob, ssn, address, notes) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (req.name, req.dob, req.ssn, req.address, req.notes),
        )
        pid = cur.fetchone()[0]
        conn.commit()
        conn.close()
        return pid
    except Exception:
        # DB not up (e.g. local dev without compose) — fall back to a stub id
        return int(time.time()) % 100000


def _verify_eligibility(insurance_id: str | None):
    if not insurance_id:
        return
    try:
        # Synchronous call with no timeout. If the payer is slow, /intake is slow.
        # Artificial latency stands in for the real clearinghouse round-trip
        # (front desk reports this as RIV-088 "registration spins ~4-5s").
        time.sleep(4.2)
        httpx.get(f"{ELIGIBILITY_URL}/eligibility", params={"insurance_id": insurance_id})
    except Exception:
        pass


def _record_consents(patient_id: int):
    for kind in ("npp_ack", "treatment_consent"):
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO consents (patient_id, kind) VALUES (%s, %s)",
                (patient_id, kind),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
