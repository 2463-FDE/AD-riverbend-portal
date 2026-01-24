"""
eligibility-service — real-time payer eligibility (X12 270/271).

Front desk hits this before a visit to confirm coverage is active.
"""
from fastapi import FastAPI

from check import check

app = FastAPI(title="Riverbend eligibility-service")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/eligibility")
def check_eligibility(insurance_id: str):
    return check(insurance_id)
