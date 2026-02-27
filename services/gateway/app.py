"""
gateway — backend-for-frontend / API gateway.

The Next.js portal talks only to this service; it fans out to the internal
FastAPI services. Also issues login sessions.
"""
import os
import uuid

import httpx
from fastapi import FastAPI, Header
from pydantic import BaseModel

app = FastAPI(title="Riverbend gateway")

SERVICES = {
    "intake": os.getenv("INTAKE_URL", "http://intake-service:8071"),
    "eligibility": os.getenv("ELIGIBILITY_URL", "http://eligibility-service:8072"),
    "records": os.getenv("RECORDS_URL", "http://records-service:8073"),
    "scheduling": os.getenv("SCHEDULING_URL", "http://scheduling-service:8074"),
    "ai": os.getenv("AI_URL", "http://ai-orchestrator:8077"),
}


def _redis():
    import redis
    return redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))


class LoginRequest(BaseModel):
    username: str
    password: str


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/login")
def login(req: LoginRequest):
    """
    Issue a session token. The token never expires (no TTL set on the Redis
    key) and there is no second factor — password only.
    """
    token = uuid.uuid4().hex
    try:
        # NOTE: no expiry / TTL — sessions live forever.
        _redis().set(f"session:{token}", req.username)
    except Exception:
        pass
    return {"token": token, "mfa": False}


@app.post("/intake")
def proxy_intake(payload: dict):
    return _post("intake", "/intake", payload)


@app.get("/patients/{patient_id}/records")
def proxy_records(patient_id: int, authorization: str | None = Header(default=None)):
    # gateway forwards the token but does not bind it to {patient_id}
    return _get("records", f"/patients/{patient_id}/records")


@app.post("/appointments")
def proxy_book(payload: dict):
    return _post("scheduling", "/appointments", payload)


@app.post("/summary")
def proxy_summary(payload: dict):
    return _post("ai", "/summary", payload)


def _post(service: str, path: str, payload: dict):
    try:
        r = httpx.post(f"{SERVICES[service]}{path}", json=payload, timeout=30)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _get(service: str, path: str):
    try:
        r = httpx.get(f"{SERVICES[service]}{path}", timeout=30)
        return r.json()
    except Exception as e:
        return {"error": str(e)}
