"""End-to-end tests of POST /intake as a route (E4-SPEC-22, E4-SPEC-23).

Closes the deliberate-looking gap tests/README.md recorded and docs/todo.md
tracked as TODO-55: intake's helpers were covered in isolation, but nothing
drove the endpoint, so the route's own wiring — what it writes, what it returns,
and what survives a failure — was unguarded. That is the layer the intake
contract break lived in.

TestClient over intake-service with an in-memory SQLite database. Two hops are
faked on purpose so these tests assert the ROUTE and not its dependencies:
``_evaluate_match_key``'s ON CONFLICT insert is Postgres-only (and is covered by
tests/test_intake_match_key.py), and ``_query_eligibility`` would make an
outbound call.

Sibling-pinning idiom from tests/test_intake_match_key.py.
"""
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import load_module

_SIBLINGS = ("config", "db", "logging_config", "models", "schemas", "breaker", "matching")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/intake-service/config.py", "intake_config_ep")
sys.modules["db"] = load_module("services/intake-service/db.py", "intake_db_ep")
sys.modules["logging_config"] = load_module(
    "services/intake-service/logging_config.py", "intake_logging_config_ep"
)
sys.modules["models"] = load_module("services/intake-service/models.py", "intake_models_ep")
sys.modules["schemas"] = load_module("services/intake-service/schemas.py", "intake_schemas_ep")
sys.modules["breaker"] = load_module("services/intake-service/breaker.py", "intake_breaker_ep")
sys.modules["matching"] = load_module("services/intake-service/matching.py", "intake_matching_ep")
app_mod = load_module("services/intake-service/app.py", "intake_app_ep")
db_mod = sys.modules["db"]
models_mod = sys.modules["models"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


# Required on every request as of e5 (E5-SPEC-27). One constant is safe here
# because each test gets a fresh in-memory database from the session_factory
# fixture: a test that posted this body TWICE would exercise the replay path
# (E5-SPEC-30), which is tests/test_intake_idempotency.py's subject, not this
# file's.
VALID_REQUEST = {
    "submission_id": "6f1d1a2e-6e0f-4a3c-9a4c-0f8a5b2d7c31",
    "demographics": {
        "name": "Sample Patient",
        "dob": "1985-03-12",
        "ssn": "000000000",
        "gender": "Prefer not to say",
        "address": "1 Example Way",
        "phone": "555-0100",
        "email": "sample@example.invalid",
        "created_via": "self_service",
    },
    "insurance": {
        "payer_name": "Example Health",
        "member_id": "EXMP000001",
        "group_number": "GRP-0001",
        "plan_type": "PPO",
    },
    "consents": [
        "npp_ack",
        "treatment_consent",
        "roi_consent",
        "financial_responsibility_ack",
        "communications_opt_in",
    ],
}


@pytest.fixture
def session_factory():
    # StaticPool + a shared in-memory database so the route's session and the
    # test's own assertions see the same tables.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    db_mod.Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def client(session_factory, monkeypatch):
    def _override():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    # The match-key hook and the payer hop are exercised elsewhere; here they
    # would only add a Postgres dialect and an outbound call.
    monkeypatch.setattr(app_mod, "_evaluate_match_key", lambda *a, **k: None)
    monkeypatch.setattr(
        app_mod,
        "_query_eligibility",
        lambda ins: ({"active": True, "status": "active"}, True),
    )
    app_mod.app.dependency_overrides[app_mod.get_db] = _override
    yield TestClient(app_mod.app, raise_server_exceptions=False)
    app_mod.app.dependency_overrides.clear()


def _counts(session_factory):
    session = session_factory()
    try:
        return {
            "patients": session.query(models_mod.Patient).count(),
            "coverages": session.query(models_mod.InsuranceCoverage).count(),
            "consents": session.query(models_mod.Consent).count(),
        }
    finally:
        session.close()


def test_a_complete_submission_creates_the_whole_registration(client, session_factory):
    """E4-SPEC-1, E4-SPEC-2, E4-SPEC-8, E4-SPEC-22, E4-SPEC-23. The defect in its positive form: this is the
    request the portal now sends, and it must produce a patient, a coverage and
    every consent it carried."""
    r = client.post("/intake", json=VALID_REQUEST)
    assert r.status_code == 201
    body = r.json()
    assert isinstance(body["patient_id"], int)

    session = session_factory()
    try:
        patient = session.query(models_mod.Patient).one()
        assert patient.id == body["patient_id"]
        assert patient.name == "Sample Patient"
        assert patient.created_via == "self_service"

        coverage = session.query(models_mod.InsuranceCoverage).one()
        assert coverage.patient_id == patient.id
        assert coverage.payer_name == "Example Health"

        kinds = {c.kind for c in session.query(models_mod.Consent).all()}
        assert kinds == set(VALID_REQUEST["consents"])
    finally:
        session.close()


def test_a_submission_without_insurance_creates_no_coverage_row(client, session_factory):
    """E4-SPEC-2. `insurance: null` is what the portal sends for a self-pay
    walk-in; it must not produce an empty coverage row."""
    payload = {**VALID_REQUEST, "insurance": None}
    r = client.post("/intake", json=payload)
    assert r.status_code == 201
    assert _counts(session_factory)["coverages"] == 0


def test_an_unknown_consent_kind_is_rejected_and_writes_nothing(client, session_factory):
    """E4-SPEC-10 and E4-SPEC-4 together. The pydantic boundary rejects the
    value before any write — which is only literally true now that the consent
    writes are inside the registration transaction instead of following a
    committed patient row."""
    payload = {**VALID_REQUEST, "consents": ["npp_ack", "Jane Doe DOB 1985-03-12"]}
    r = client.post("/intake", json=payload)
    assert r.status_code == 422
    assert _counts(session_factory) == {"patients": 0, "coverages": 0, "consents": 0}


def test_a_write_failure_mid_registration_leaves_nothing_behind(
    client, session_factory, monkeypatch
):
    """E4-SPEC-4. The consent write fails after the patient and coverage rows
    are already in the session. Before the single transaction, the patient was
    committed, the consent error was swallowed, and the desk got a 201 for a
    half-written registration."""
    def _boom(*args, **kwargs):
        raise OperationalError("INSERT INTO consents", {}, Exception("disk I/O error"))

    monkeypatch.setattr(app_mod, "Consent", _boom)

    r = client.post("/intake", json=VALID_REQUEST)
    assert r.status_code == 503
    assert _counts(session_factory) == {"patients": 0, "coverages": 0, "consents": 0}


def test_a_verification_fault_after_the_commit_does_not_undo_the_registration(
    client, session_factory, monkeypatch
):
    """E4-SPEC-4, the other way round. Eligibility is best-effort and runs after
    the commit, so a fault there degrades the verdict and never the
    registration — the property ADR 0010's comment claimed and the ordering now
    makes unconditional."""

    def _explode(ins):
        raise RuntimeError("payer client blew up")

    monkeypatch.setattr(app_mod, "_query_eligibility", _explode)

    r = client.post("/intake", json=VALID_REQUEST)
    assert r.status_code == 201
    assert r.json()["eligibility"]["status"] == "unknown"
    assert _counts(session_factory)["patients"] == 1


def test_the_response_carries_the_verdict_the_portal_renders(client):
    """E4-SPEC-24's other end: the verdict has to be in the response body at
    all before a screen can show it."""
    r = client.post("/intake", json=VALID_REQUEST)
    assert r.json()["eligibility"]["status"] == "active"


def test_a_rejected_submission_never_echoes_the_submitted_values(client):
    """The status class is what the portal branches on; the body is FastAPI's
    own 422 shape, which embeds the rejected input. Pinned here because the
    gateway's generic-detail fallback (tests/test_gateway_intake_proxy.py) is
    what stops it reaching an operator, and that fallback only matters while
    this body really does carry it."""
    payload = {
        "demographics": {"first_name": "Sample", "ssn": "000000000"},
        "consents": ["npp_ack"],
    }
    r = client.post("/intake", json=payload)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)
