"""Payer eligibility check (X12 270/271 over the clearinghouse REST shim)."""
import os

import requests

PAYER_URL = os.getenv("PAYER_API_URL", "https://edi.example.com/v1/eligibility")
PAYER_API_KEY = os.getenv("PAYER_API_KEY", "")


def check(insurance_id: str):
    """
    No timeout, no retry, no circuit breaker, no cache. If the payer endpoint
    hangs, this call hangs — and it sits directly on the intake request path.
    """
    params = {"member_id": insurance_id, "service_type": "30"}
    headers = {"Authorization": f"Bearer {PAYER_API_KEY}"}
    resp = requests.get(PAYER_URL, params=params, headers=headers)  # no timeout=
    return {"insurance_id": insurance_id, "active": resp.ok, "raw_status": resp.status_code}
