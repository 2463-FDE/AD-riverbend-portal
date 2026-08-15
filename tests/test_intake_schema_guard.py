"""intake /healthz reflects whether registration can actually work (e5b-SPEC-23,25).

An accurate red beats a stable lie (e5b-D-14): the health surface refuses while a
fail-closed guard the request path also enforces would refuse every registration.
Three conditions are checked — the fingerprint key must be real, every table
Base.metadata declares must exist (a database predating this item is missing
registration_submissions), and registration_submissions must carry its declared
columns and the UNIQUE constraint on submission_id (PR #79 round 2: presence is
not shape — a partially applied migration without the constraint silently
recreates the duplicate-chart bug). The refusal names the variable, table,
column, or constraint, never a value and never a secret.

compose depends_on stays service_started (e5b-D-14), so this red never becomes an
estate-wide boot failure — it is a signal, read by the operator, not a gate.

Sibling-pinning idiom from tests/test_intake_endpoint.py.
"""
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import load_module

_SIBLINGS = ("config", "db", "logging_config", "models", "schemas", "breaker", "matching")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/intake-service/config.py", "intake_config_guard")
sys.modules["db"] = load_module("services/intake-service/db.py", "intake_db_guard")
sys.modules["logging_config"] = load_module(
    "services/intake-service/logging_config.py", "intake_logging_config_guard"
)
sys.modules["models"] = load_module("services/intake-service/models.py", "intake_models_guard")
sys.modules["schemas"] = load_module("services/intake-service/schemas.py", "intake_schemas_guard")
sys.modules["breaker"] = load_module("services/intake-service/breaker.py", "intake_breaker_guard")
sys.modules["matching"] = load_module("services/intake-service/matching.py", "intake_matching_guard")
app_mod = load_module("services/intake-service/app.py", "intake_app_guard")
db_mod = sys.modules["db"]
models_mod = sys.modules["models"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

REAL_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _client(session_factory, key):
    def _override():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app_mod.settings.registration_fingerprint_key = key
    app_mod.app.dependency_overrides[app_mod.get_db] = _override
    return TestClient(app_mod.app, raise_server_exceptions=False)


@pytest.fixture
def full_schema():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    db_mod.Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def stale_schema():
    """A database predating this item: every table but registration_submissions."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    db_mod.Base.metadata.create_all(engine)
    models_mod.RegistrationSubmission.__table__.drop(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def constraintless_schema():
    """A partially applied migration: the table exists, the UNIQUE arbiter does not."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    db_mod.Base.metadata.create_all(engine)
    models_mod.RegistrationSubmission.__table__.drop(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE registration_submissions (
                    id INTEGER PRIMARY KEY,
                    submission_id TEXT NOT NULL,
                    payload_fingerprint TEXT NOT NULL,
                    patient_id INTEGER NOT NULL REFERENCES patients(id),
                    created_at TIMESTAMP
                )
                """
            )
        )
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def columnless_schema():
    """Column drift: the table exists with the constraint but not every declared column."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    db_mod.Base.metadata.create_all(engine)
    models_mod.RegistrationSubmission.__table__.drop(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE registration_submissions (
                    id INTEGER PRIMARY KEY,
                    submission_id TEXT NOT NULL,
                    patient_id INTEGER NOT NULL REFERENCES patients(id),
                    created_at TIMESTAMP,
                    CONSTRAINT uq_registration_submission_id UNIQUE (submission_id)
                )
                """
            )
        )
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


def teardown_function():
    app_mod.app.dependency_overrides.clear()


def test_health_ok_when_configured_and_schema_present(full_schema):
    client = _client(full_schema, REAL_KEY)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_tracks_refusal_when_key_unreal(full_schema):  # test: health-tracks-refusal
    """e5b-SPEC-23: while every registration would be refused (no real key), the
    health surface does not report healthy; the detail names the variable, not a
    value."""
    client = _client(full_schema, "changeme")
    r = client.get("/healthz")
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "REGISTRATION_FINGERPRINT_KEY" in detail
    assert "changeme" not in detail  # never the value


def test_stale_db_is_unhealthy(stale_schema):  # test: stale-db-unhealthy
    """e5b-SPEC-25: a database predating this item's state is not healthy, and the
    detail names the missing table carrying no patient data and no secret."""
    client = _client(stale_schema, REAL_KEY)
    r = client.get("/healthz")
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "registration_submissions" in detail
    assert REAL_KEY not in detail


def test_missing_unique_constraint_is_unhealthy(constraintless_schema):
    """PR #79 round 2: the UNIQUE constraint is the sole arbiter of a retry
    (e5b-SPEC-8); a table without it would serve duplicate charts silently, so
    the guard must read red on constraint drift, naming the constraint only."""
    client = _client(constraintless_schema, REAL_KEY)
    r = client.get("/healthz")
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "uq_registration_submission_id" in detail
    assert REAL_KEY not in detail


def test_intake_refuses_controlled_503_when_ledger_missing(stale_schema):
    """PR #79 codex r3 F1, endpoint half: with registration_submissions absent
    (the schema-drift case healthz makes red), POST /intake must answer the
    controlled 503, not an uncontrolled 500 from the unguarded first lookup."""
    client = _client(stale_schema, REAL_KEY)
    r = client.post(
        "/intake",
        json={
            "submission_id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
            "demographics": {"name": "Pat Doe", "dob": "1990-01-31", "ssn": "123-45-6789"},
            "consents": ["npp_ack"],
        },
    )
    assert r.status_code == 503
    assert r.json()["detail"] == "registration store unavailable"


def test_missing_column_is_unhealthy(columnless_schema):
    """PR #79 round 2: a declared column absent from the live table is schema
    drift the request path would only surface as a 500 mid-write; the guard
    reads red first, naming the column only."""
    client = _client(columnless_schema, REAL_KEY)
    r = client.get("/healthz")
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "payload_fingerprint" in detail
    assert REAL_KEY not in detail
