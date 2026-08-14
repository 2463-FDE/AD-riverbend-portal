"""POST /intake idempotency — the e5b core (e5b-SPEC-1,2,6-10,13,15,20-22,28,29).

A registration that commits and then loses its response used to fork a second
chart on retry (docs/debt-log.md "Intake contract break" residual 2). The fix:
the portal attaches a mint-random submission_id, intake records it with a keyed
content fingerprint in the SAME transaction as the chart, and a retry replays the
recorded outcome instead of creating a second one.

TestClient over intake-service with in-memory SQLite. The match-key hook
(Postgres ON CONFLICT) and the eligibility hop (outbound call) are faked, exactly
as tests/test_intake_endpoint.py does, so these assert the ROUTE. The lock_timeout
bound is Postgres-only: the issued s->ms value is unit-pinned below
(test_lock_timeout_ms_conversion_pins_the_units), real-Postgres acceptance was
proven live (docs/workflow/e5b.md Delivery, verification 8 — no committed
integration file, which would move the deselected count), and here the collision
and wait-expiry branches are exercised by driving the exceptions they map from.

Sibling-pinning idiom from tests/test_intake_endpoint.py.
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
sys.modules["config"] = load_module("services/intake-service/config.py", "intake_config_idem")
sys.modules["db"] = load_module("services/intake-service/db.py", "intake_db_idem")
sys.modules["logging_config"] = load_module(
    "services/intake-service/logging_config.py", "intake_logging_config_idem"
)
sys.modules["models"] = load_module("services/intake-service/models.py", "intake_models_idem")
sys.modules["schemas"] = load_module("services/intake-service/schemas.py", "intake_schemas_idem")
sys.modules["breaker"] = load_module("services/intake-service/breaker.py", "intake_breaker_idem")
sys.modules["matching"] = load_module("services/intake-service/matching.py", "intake_matching_idem")
app_mod = load_module("services/intake-service/app.py", "intake_app_idem")
db_mod = sys.modules["db"]
models_mod = sys.modules["models"]
schemas_mod = sys.modules["schemas"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

# openssl rand -hex 32 shape: a real 64-char secret that passes the key-real
# predicate. Never a live key — synthetic, for the test's HMAC only.
REAL_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
ID_A = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
ID_B = "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"

BASE_REQUEST = {
    "submission_id": ID_A,
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
    "consents": ["npp_ack", "treatment_consent"],
}


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    db_mod.Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def eligibility_calls(monkeypatch):
    """Count live eligibility hops so a replay's live re-verification is visible."""
    calls = {"n": 0}

    def _fake(ins):
        calls["n"] += 1
        return ({"active": True, "status": "active"}, True)

    monkeypatch.setattr(app_mod, "_query_eligibility", _fake)
    return calls


@pytest.fixture
def client(session_factory, monkeypatch, eligibility_calls):
    def _override():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    # A real key by default; individual tests override to exercise fail-closed.
    monkeypatch.setattr(app_mod.settings, "registration_fingerprint_key", REAL_KEY)
    # The match-key hook is Postgres-only (regexp_replace / ON CONFLICT); covered
    # by tests/test_intake_match_key.py.
    monkeypatch.setattr(app_mod, "_evaluate_match_key", lambda *a, **k: None)
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
            "submissions": session.query(models_mod.RegistrationSubmission).count(),
        }
    finally:
        session.close()


# --------------------------------------------------------------------------- #
# replay: one chart per retried submission (e5b-SPEC-1,2,7,28)
# --------------------------------------------------------------------------- #
def test_replay_single_chart(client, session_factory):  # test: replay-single-chart
    """e5b-SPEC-1: a re-submission of the same attempt with identical content
    holds exactly one chart, and the replay returns the original patient_id."""
    first = client.post("/intake", json=BASE_REQUEST)
    assert first.status_code == 201
    pid = first.json()["patient_id"]

    replay = client.post("/intake", json=BASE_REQUEST)
    assert replay.status_code == 201
    assert replay.json()["patient_id"] == pid
    assert _counts(session_factory)["patients"] == 1


def test_replay_no_coverage_consent(client, session_factory):  # test: replay-no-coverage-consent
    """e5b-SPEC-2: a replay creates no additional coverage and no additional
    consent row."""
    client.post("/intake", json=BASE_REQUEST)
    before = _counts(session_factory)
    client.post("/intake", json=BASE_REQUEST)
    after = _counts(session_factory)
    assert after == before
    assert before["coverages"] == 1
    assert before["consents"] == 2


def test_replay_indistinguishable(client):  # test: replay-indistinguishable
    """e5b-SPEC-7: the replay response carries no replay indication — same shape,
    same patient id, no extra marker key."""
    first = client.post("/intake", json=BASE_REQUEST).json()
    replay = client.post("/intake", json=BASE_REQUEST).json()
    assert set(replay) == set(first)
    assert replay["patient_id"] == first["patient_id"]
    assert "replay" not in replay and "replayed" not in replay


def test_replay_reverifies_eligibility_live(client, eligibility_calls):  # test: replay-reverifies-live
    """e5b-SPEC-28: a served replay re-verifies eligibility LIVE — the original
    verdict is never replayed, so the guarded eligibility path is hit again."""
    client.post("/intake", json=BASE_REQUEST)
    assert eligibility_calls["n"] == 1
    client.post("/intake", json=BASE_REQUEST)
    assert eligibility_calls["n"] == 2


# --------------------------------------------------------------------------- #
# the ledger row is written in the chart's transaction (e5b-SPEC-6,10,12,29)
# --------------------------------------------------------------------------- #
def test_identifier_and_binding_recorded_in_the_same_transaction(client, session_factory):
    """test: identifier-same-transaction + binding-same-transaction. A committed
    registration records exactly one submission row bound to the new chart, with
    both the identifier and a non-empty content fingerprint."""
    pid = client.post("/intake", json=BASE_REQUEST).json()["patient_id"]
    session = session_factory()
    try:
        row = session.query(models_mod.RegistrationSubmission).one()
        assert row.submission_id == ID_A
        assert row.patient_id == pid
        assert row.payload_fingerprint  # recorded, non-empty
    finally:
        session.close()


def test_a_transaction_that_does_not_commit_records_no_submission(
    client, session_factory, monkeypatch
):
    """e5b-SPEC-6: a transaction that does not commit records nothing — the
    ledger row never outlives a failed chart write."""
    def _boom(*a, **k):
        raise OperationalError("INSERT INTO consents", {}, Exception("disk I/O error"))

    monkeypatch.setattr(app_mod, "Consent", _boom)
    r = client.post("/intake", json=BASE_REQUEST)
    assert r.status_code == 503
    assert _counts(session_factory) == {
        "patients": 0, "coverages": 0, "consents": 0, "submissions": 0
    }


def test_no_pruning_path(client, session_factory):  # test: no-pruning-path
    """e5b-SPEC-10: recorded identifiers are retained without pruning — every
    distinct registration leaves its row, and the module runs no delete/expiry."""
    import inspect as _inspect
    import re as _re
    for sid in (ID_A, ID_B, "7c9e6679-7425-40de-944b-e07fc1f90ae7"):
        client.post("/intake", json={**BASE_REQUEST, "submission_id": sid})
    assert _counts(session_factory)["submissions"] == 3
    src = _inspect.getsource(app_mod)
    assert not _re.search(r"\.delete\(|DELETE\s+FROM|\bexpire\b", src, _re.IGNORECASE)


def test_no_eligibility_verdict_is_persisted(client, session_factory):  # test: no-verdict-persisted
    """e5b-SPEC-29: the mechanism persists no eligibility verdict — the ledger
    row has no verdict/eligibility/active column."""
    client.post("/intake", json=BASE_REQUEST)
    cols = {c.name for c in models_mod.RegistrationSubmission.__table__.columns}
    assert cols == {"id", "submission_id", "payload_fingerprint", "patient_id", "created_at"}
    for forbidden in ("eligibility", "verdict", "active", "status"):
        assert forbidden not in cols


# --------------------------------------------------------------------------- #
# a corrected retry is refused, never confirmed (e5b-SPEC-13)
# --------------------------------------------------------------------------- #
def test_mismatch_writes_nothing(client, session_factory):  # test: mismatch-writes-nothing
    """e5b-SPEC-13: a recorded id arriving with differing content is a 409 that
    creates and modifies nothing and never acknowledges the changed content."""
    client.post("/intake", json=BASE_REQUEST)
    before = _counts(session_factory)

    corrected = {**BASE_REQUEST}
    corrected["demographics"] = {**BASE_REQUEST["demographics"], "name": "Corrected Name"}
    r = client.post("/intake", json=corrected)
    assert r.status_code == 409
    assert _counts(session_factory) == before

    # the original chart is untouched — the correction was never saved
    session = session_factory()
    try:
        assert session.query(models_mod.Patient).one().name == "Sample Patient"
    finally:
        session.close()


def test_reordered_consents_are_the_same_attempt(client, session_factory):
    """e5b-D-11: fingerprinting the validated model with consents sorted makes a
    reordered-consents retry an identical replay, not a mismatch."""
    client.post("/intake", json=BASE_REQUEST)
    reordered = {**BASE_REQUEST, "consents": ["treatment_consent", "npp_ack"]}
    r = client.post("/intake", json=reordered)
    assert r.status_code == 201
    assert _counts(session_factory)["patients"] == 1


# --------------------------------------------------------------------------- #
# a genuine new registration is never absorbed (e5b-SPEC-15)
# --------------------------------------------------------------------------- #
def test_no_accidental_mpi(client, session_factory):  # test: no-accidental-mpi
    """e5b-SPEC-15: an unrecorded identifier always creates a new chart — even
    with identical patient-identifying values. D5/no-MPI stays open, shown open."""
    p1 = client.post("/intake", json={**BASE_REQUEST, "submission_id": ID_A}).json()["patient_id"]
    p2 = client.post("/intake", json={**BASE_REQUEST, "submission_id": ID_B}).json()["patient_id"]
    assert p1 != p2
    assert _counts(session_factory)["patients"] == 2


def test_two_genuine_submissions_hold_two_charts_never_merged(client, session_factory):
    """test: pair-queued-not-merged (the two-charts / never-merged half). Two
    genuine submissions for one person hold two charts; neither is merged or
    deleted. The queueing of the pair is Postgres-only and pinned by
    tests/test_intake_match_key.py."""
    ids = [client.post("/intake", json={**BASE_REQUEST, "submission_id": s}).json()["patient_id"]
           for s in (ID_A, ID_B)]
    session = session_factory()
    try:
        rows = session.query(models_mod.Patient).all()
        assert {p.id for p in rows} == set(ids)   # both present, distinct, unmerged
    finally:
        session.close()


# --------------------------------------------------------------------------- #
# the format boundary (e5b-SPEC-19)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad_id", ["", "not-a-uuid", "00000000-0000-0000-0000-000000000000"])
def test_format_check_boundary(client, session_factory, bad_id):  # test: format-check-boundary
    """e5b-SPEC-19: a non-version-4 identifier is rejected before any write — the
    boundary narrows accidental derivation (it does not prove randomness)."""
    r = client.post("/intake", json={**BASE_REQUEST, "submission_id": bad_id})
    assert r.status_code == 422
    assert _counts(session_factory)["patients"] == 0


def test_missing_identifier_rejected(client, session_factory):  # test: missing-identifier-rejected
    """e5b-SPEC-11: a submission without an identifier is a correctable-input
    (422) rejection that creates nothing."""
    payload = {k: v for k, v in BASE_REQUEST.items() if k != "submission_id"}
    r = client.post("/intake", json=payload)
    assert r.status_code == 422
    assert _counts(session_factory)["patients"] == 0


# --------------------------------------------------------------------------- #
# concurrency: the UNIQUE constraint is the sole arbiter (e5b-SPEC-8,9)
# --------------------------------------------------------------------------- #
def test_collision_loser_waits_and_replays_the_winner(client, session_factory, monkeypatch):
    """test: collision-loser-waits. A concurrent request commits this
    submission_id first; the loser's insert raises the UNIQUE violation, and it
    answers with the winner's result rather than forking a second chart."""
    def _winner_commits_then_collides(db, req, fingerprint):
        # Model the concurrent winner: its row is now committed under this id.
        winner = models_mod.Patient(name="Winner Chart", created_via="front_desk")
        db.add(winner)
        db.flush()
        db.add(models_mod.RegistrationSubmission(
            submission_id=req.submission_id, payload_fingerprint=fingerprint,
            patient_id=winner.id,
        ))
        db.commit()
        raise app_mod._SubmissionCollision()

    monkeypatch.setattr(app_mod, "_create_registration", _winner_commits_then_collides)
    r = client.post("/intake", json=BASE_REQUEST)
    assert r.status_code == 201
    session = session_factory()
    try:
        winner_id = session.query(models_mod.Patient).one().id  # only the winner's chart
        assert r.json()["patient_id"] == winner_id
        assert session.query(models_mod.RegistrationSubmission).count() == 1
    finally:
        session.close()


def test_wait_expiry_answers_503_and_creates_nothing(session_factory, monkeypatch):
    """test: wait-expiry-503 (e5b-SPEC-9). A lock_timeout expiry raises
    OperationalError as the blocked insert's commit resolves; _create_registration
    maps it to the existing 503 branch and rolls back, so nothing is created."""
    from fastapi import HTTPException

    req = schemas_mod.IntakeRequest.model_validate(BASE_REQUEST)
    session = session_factory()

    def _lock_not_available():
        raise OperationalError("commit", {}, Exception("lock_not_available"))

    monkeypatch.setattr(session, "commit", _lock_not_available)
    try:
        with pytest.raises(HTTPException) as exc:
            app_mod._create_registration(session, req, "deadbeef")
        assert exc.value.status_code == 503
    finally:
        session.close()
    # the rollback inside the 503 branch left nothing behind
    assert _counts(session_factory) == {
        "patients": 0, "coverages": 0, "consents": 0, "submissions": 0
    }


# --------------------------------------------------------------------------- #
# fail-closed key and the no-PHI / non-reversible properties (e5b-SPEC-20,21,22)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad_key", ["", "   ", "changeme", "short", "0123456789abcdef"])
def test_key_fail_closed(client, session_factory, monkeypatch, bad_key):  # test: key-fail-closed
    """e5b-SPEC-22: with no real secret, registration refuses before any read or
    write, and the detail names the configuration, never a value."""
    monkeypatch.setattr(app_mod.settings, "registration_fingerprint_key", bad_key)
    r = client.post("/intake", json=BASE_REQUEST)
    assert r.status_code == 503
    assert "REGISTRATION_FINGERPRINT_KEY" in r.json()["detail"]
    assert bad_key not in r.json()["detail"] or bad_key == ""  # never the value
    assert _counts(session_factory)["patients"] == 0


def test_key_real_predicate_is_fail_closed():
    """Unit: the shared key-real predicate (e5b-D-11) — unset/whitespace/sentinel/
    short are all unreal; a 32+char non-sentinel is real."""
    for unreal in (None, "", "   ", "changeme", "CHANGEME", "x" * 31):
        assert app_mod._fingerprint_key_is_real(unreal) is False
    assert app_mod._fingerprint_key_is_real(REAL_KEY) is True


def test_no_phi_on_any_surface(client, session_factory, caplog):  # test: no-phi-any-surface
    """e5b-SPEC-20: no surface the mechanism creates — log line, response body,
    persisted ledger row — carries a patient-identifying value."""
    phi = {
        "name": "Jane Doe", "dob": "1985-03-12", "ssn": "123-45-6789",
        "email": "jane@example.com", "phone": "555-867-5309", "address": "42 Elm St",
    }
    req = {**BASE_REQUEST, "demographics": {**BASE_REQUEST["demographics"], **phi},
           "insurance": {**BASE_REQUEST["insurance"], "member_id": "BCBS4471"}}
    with caplog.at_level("INFO"):
        resp = client.post("/intake", json=req)
    logged = "\n".join(r.getMessage() for r in caplog.records)
    body = resp.text
    session = session_factory()
    try:
        row = session.query(models_mod.RegistrationSubmission).one()
        persisted = f"{row.submission_id}|{row.payload_fingerprint}|{row.patient_id}"
    finally:
        session.close()
    for value in list(phi.values()) + ["BCBS4471"]:
        assert value not in logged
        assert value not in body
        assert value not in persisted


def test_binding_is_keyed_not_reversible(monkeypatch):  # test: binding-not-reversible
    """e5b-SPEC-21: the persisted binding is a keyed HMAC — an attacker holding
    the stored records and guessing field values cannot recompute it without the
    key. A plain unkeyed hash of the same content does not equal it, and changing
    the key changes the binding."""
    import hashlib
    req = schemas_mod.IntakeRequest.model_validate(BASE_REQUEST)

    monkeypatch.setattr(app_mod.settings, "registration_fingerprint_key", REAL_KEY)
    fp = app_mod._fingerprint(req)

    canonical = req.model_dump(exclude={"submission_id"})
    canonical["consents"] = sorted(canonical["consents"])
    import json as _json
    blob = _json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    unkeyed = hashlib.sha256(blob.encode()).hexdigest()
    assert fp != unkeyed  # not a plain hash the guesser could recompute

    monkeypatch.setattr(app_mod.settings, "registration_fingerprint_key", REAL_KEY[::-1])
    assert app_mod._fingerprint(req) != fp  # key-dependent


def test_lock_timeout_ms_conversion_pins_the_units():
    """e5b-D-12 units trap: the seconds knob issues milliseconds — the default 5
    is 5000, so a dropped ×1000 (a 1000×-shorter bound) reddens here."""
    app_mod.settings.registration_lock_wait_seconds = 5
    assert app_mod._lock_timeout_ms() == 5000
