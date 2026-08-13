"""
The intake health signal tells the truth about the schema (PR #76 review round 7).

Round 6 established the mechanism: `db/migrations/*.sql` has no runner, compose
mounts `db/schema.sql` only into `/docker-entrypoint-initdb.d` (fresh volumes
only), so a database that predates a migration lacks the table the route reads.
The read raises SQLAlchemyError, `_find_registration` catches it, and every
registration answers 503 — while `/healthz`, which only proved the process was
listening, kept reporting green. Round 6 shipped the operator path
(`make schema-apply`) and left the signal alone; the owner overruled that on
round 7 and took the guard.

The shape is the gateway's, not a new invention: `services/gateway/app.py:179`
sends a real authenticated Redis PING from `/healthz` and answers 503 when the
store cannot serve, on the argument that an accurate red beats a stable lie
(tests/test_gateway_redis_auth.py). Nothing in the topology drains or restarts
on this signal, so the cost of a red is a truthful `docker compose ps`.

The guard is over the tables THIS service declares (`Base.metadata`), not a
hardcoded list, so a future model lands inside it with no edit — and so the
class round 6 named (`insurance_coverages` mig 005, `duplicate_review_queue`
009, `registration_submissions` 010 are all read the same unconditional way) is
closed at once rather than one instance at a time.

Landmines §3: the guard runs on the PHI path's database, so it takes the
negative test — a missing table must name the TABLE and never a row.
"""
import logging
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import load_module

# Sibling-pinning idiom from tests/test_intake_endpoint.py: intake-service has
# its own config/db/models/schemas and bare names are ambiguous across services.
_SIBLINGS = ("config", "db", "logging_config", "models", "schemas", "breaker", "matching")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/intake-service/config.py", "intake_config_sg")
sys.modules["db"] = load_module("services/intake-service/db.py", "intake_db_sg")
sys.modules["logging_config"] = load_module(
    "services/intake-service/logging_config.py", "intake_logging_config_sg"
)
sys.modules["models"] = load_module("services/intake-service/models.py", "intake_models_sg")
sys.modules["schemas"] = load_module("services/intake-service/schemas.py", "intake_schemas_sg")
sys.modules["breaker"] = load_module("services/intake-service/breaker.py", "intake_breaker_sg")
sys.modules["matching"] = load_module("services/intake-service/matching.py", "intake_matching_sg")
app_mod = load_module("services/intake-service/app.py", "intake_app_sg")
db_mod = sys.modules["db"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


DECLARED_TABLES = sorted(db_mod.Base.metadata.tables)


@pytest.fixture
def engine():
    # StaticPool + a shared in-memory database so the DDL this test runs and the
    # route's own session see the same schema.
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    db_mod.Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _client(eng):
    factory = sessionmaker(bind=eng, autoflush=False, autocommit=False)

    def _override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app_mod.app.dependency_overrides[app_mod.get_db] = _override
    return TestClient(app_mod.app, raise_server_exceptions=False)


REAL_KEY = "e5-test-key-not-a-real-secret-0123456789"


@pytest.fixture(autouse=True)
def fingerprint_key(monkeypatch):
    # config.py reads os.getenv in the CLASS BODY, so setenv here cannot reach
    # it — patch the loaded object app.py holds (idiom from
    # tests/test_intake_endpoint.py). Without this every case below would go red
    # on the key rather than on its own subject.
    monkeypatch.setattr(app_mod.settings, "registration_fingerprint_key", REAL_KEY)


@pytest.fixture
def client(engine):
    c = _client(engine)
    yield c
    app_mod.app.dependency_overrides.clear()


def test_the_declared_set_is_not_empty():
    # Guard against a vacuous suite: every parametrized case below is generated
    # from this set, so an import that mapped no models would make them all pass
    # by having nothing to drop.
    assert "registration_submissions" in DECLARED_TABLES
    assert len(DECLARED_TABLES) >= 6


def test_healthz_is_green_when_the_schema_is_complete(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_healthz_goes_red_when_the_registration_table_is_missing(engine, client):
    # The round-6 finding, as the reviewer stated it: on a volume created before
    # migration 010 the table is absent, POST /intake answers 503 for every
    # operator, and this endpoint used to keep the container green.
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE registration_submissions"))
    r = client.get("/healthz")
    assert r.status_code == 503
    assert r.json()["detail"] == "schema incomplete"


@pytest.mark.parametrize("table", DECLARED_TABLES)
def test_healthz_goes_red_when_any_declared_table_is_missing(engine, client, table):
    # The class, not the instance. Round 6 measured that migrations 005, 008,
    # 009 and 010 all created tables their service reads unconditionally, so an
    # environment older than any of them carries the same latent 503. A guard
    # that named only migration 010's table would have to be rewritten by the
    # next migration; this one covers whatever the service maps.
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE {table}"))
    assert client.get("/healthz").status_code == 503


def test_the_red_names_the_missing_table_and_reads_no_row(engine, client, caplog):
    # Landmines §3 negative test. The check asks the catalog which tables exist
    # and never selects from one, so the only identifier that can reach a log
    # line or a response body is a table name.
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO patients (name, dob, ssn) VALUES ('Adversarial Q Testpatient', '1990-01-31', '123-45-6789')"))
        conn.execute(text("DROP TABLE registration_submissions"))
    with caplog.at_level(logging.ERROR):
        r = client.get("/healthz")
    assert r.status_code == 503
    logged = " ".join(rec.getMessage() for rec in caplog.records)
    # Not vacuous: the red must have said something.
    assert any(rec.levelno >= logging.ERROR for rec in caplog.records)
    assert "registration_submissions" in logged
    for value in ("Adversarial Q Testpatient", "1990-01-31", "123-45-6789"):
        assert value not in logged
        assert value not in r.text


@pytest.mark.parametrize(
    "key",
    ["", "   ", "changeme", "replace-me-with-a-real-secret", "tooshort"],
    ids=["unset", "whitespace", "placeholder", "marker", "under-the-floor"],
)
def test_healthz_goes_red_when_the_key_is_not_a_real_secret(client, monkeypatch, key):
    # The other path that answers 503 for every registration while the container
    # reports green. Round 3 made _fingerprint_key fail closed on exactly these
    # values and round 5 generated the key at `make up` so a make-driven stack
    # always has one; what neither closed is the SIGNAL — a checkout that never
    # ran make still boots green and registers nobody. Round 5 declined to touch
    # the healthcheck on the grounds that a /healthz computing a fingerprint is a
    # PHI-adjacent probe; this asks the CONFIGURATION whether a key exists and
    # computes no digest, so that objection does not reach it (owner decision,
    # round 7).
    monkeypatch.setattr(app_mod.settings, "registration_fingerprint_key", key)
    r = client.get("/healthz")
    assert r.status_code == 503
    assert r.json()["detail"] == "registration key not configured"


def test_the_key_red_discloses_no_key_material(client, monkeypatch, caplog):
    # Landmines §3. The key is a secret whose whole value is that it is not
    # known; a health endpoint polled every 10s must not narrow it. The refusal
    # says a key is missing and nothing about the value it rejected — not the
    # value, not its length, not which check refused (the _fingerprint_key
    # precedent, app.py:331-333).
    secret = "an-almost-real-key-that-is-long-enough-x"
    monkeypatch.setattr(app_mod.settings, "registration_fingerprint_key", secret[:8])
    with caplog.at_level(logging.ERROR):
        r = client.get("/healthz")
    assert r.status_code == 503
    logged = " ".join(rec.getMessage() for rec in caplog.records)
    assert any(rec.levelno >= logging.ERROR for rec in caplog.records)
    assert secret[:8] not in logged
    assert secret[:8] not in r.text


def test_healthz_is_green_with_a_real_key_and_a_complete_schema(client):
    # The positive control for the pair of guards: both conditions satisfied is
    # the only green.
    assert client.get("/healthz").status_code == 200


def test_healthz_goes_red_when_the_database_does_not_answer():
    # A database that is down is not a schema fault and must not be reported as
    # one — but it is still a service that can register nobody, so it is still a
    # red. Class-name-only logging idiom (phi-logging-policy rule 3): a
    # statement-level DBAPIError can embed bound values in the driver message.
    unreachable = create_engine("sqlite:////nonexistent-riverbend-dir/intake.db")
    c = _client(unreachable)
    try:
        r = c.get("/healthz")
        assert r.status_code == 503
        assert r.json()["detail"] == "database unavailable"
    finally:
        app_mod.app.dependency_overrides.clear()
        unreachable.dispose()
