"""POST /intake is idempotent per submission attempt (E5-SPEC-24 … E5-SPEC-43).

The defect this closes is the residual e4 made *reachable*: registration commits,
the response is lost in transit, the portal correctly tells the operator nothing
was saved (E4-SPEC-7), and the retry creates a second chart with its own coverage
and consent rows. The caller now names the attempt, and a repeat of that attempt
returns the registration the first one produced — a repeat whose *content* matches,
since a reused identifier carrying different content is a correction the operator
must not have silently swallowed (E5-SPEC-41, E5-SPEC-42) and the portal re-mints
on the first edit after an unconfirmed submit (E5-SPEC-43).

TestClient over intake-service on in-memory SQLite, harness copied from
tests/test_intake_endpoint.py. The match-key hook and the payer hop are faked for
the same reasons they are there — a Postgres-only ON CONFLICT insert and an
outbound call — except where a test's whole subject is whether the hook ran
(E5-SPEC-37), which is asserted through a spy rather than the real insert.
"""
import logging
import pathlib
import subprocess
import sys
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
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
sys.modules["schemas"] = load_module(
    "services/intake-service/schemas.py", "intake_schemas_idem"
)
sys.modules["breaker"] = load_module("services/intake-service/breaker.py", "intake_breaker_idem")
sys.modules["matching"] = load_module(
    "services/intake-service/matching.py", "intake_matching_idem"
)
app_mod = load_module("services/intake-service/app.py", "intake_app_idem")
config_mod = sys.modules["config"]
db_mod = sys.modules["db"]
models_mod = sys.modules["models"]
schemas_mod = sys.modules["schemas"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


def _request(
    submission_id,
    name="Sample Patient",
    ssn="000000000",
    dob="1985-03-12",
    member_id="EXMP000001",
    consents=("npp_ack", "treatment_consent"),
):
    return {
        "submission_id": submission_id,
        "demographics": {
            "name": name,
            "dob": dob,
            "ssn": ssn,
            "gender": "Prefer not to say",
            "address": "1 Example Way",
            "phone": "555-0100",
            "email": "sample@example.invalid",
            "created_via": "self_service",
        },
        "insurance": {
            "payer_name": "Example Health",
            "member_id": member_id,
            "group_number": "GRP-0001",
            "plan_type": "PPO",
        },
        "consents": list(consents),
    }


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    db_mod.Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture(autouse=True)
def fingerprint_key(monkeypatch):
    # config.py reads os.getenv in the CLASS BODY, so the environment is already
    # read by import time and a monkeypatch.setenv cannot reach it — patch the
    # loaded settings object (config_mod is the same instance app.py holds).
    # Without a key _payload_fingerprint fails closed with a 503 before any read
    # or write, so every POST /intake in this module would 503 (E5-SPEC-41, plan
    # D-19). The fail-closed test below defeats this fixture on purpose.
    #
    # NEVER repair this with a non-empty default in config.py: a default key is a
    # published key, and an unkeyed fingerprint of guessable fields is a
    # dictionary-reversible confirmation oracle over a persisted column.
    monkeypatch.setattr(config_mod.settings, "registration_fingerprint_key", "e5-test-key")


@pytest.fixture
def match_key_calls():
    return []


@pytest.fixture
def client(session_factory, match_key_calls, monkeypatch):
    def _override():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    # A spy, not a stub: E5-SPEC-37 is about whether the hook ran at all, and its
    # real insert is Postgres-only (tests/test_intake_match_key.py owns that).
    monkeypatch.setattr(
        app_mod,
        "_evaluate_match_key",
        lambda db, patient_id, demo: match_key_calls.append(patient_id),
    )
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
            "submissions": session.query(models_mod.RegistrationSubmission).count(),
        }
    finally:
        session.close()


# --------------------------------------------------------------------------- #
# the replay (E5-SPEC-24, 25, 30, 31)
# --------------------------------------------------------------------------- #
def test_a_repeated_submission_creates_nothing_and_returns_the_first_registration(
    client, session_factory, match_key_calls
):
    """E5-SPEC-24, E5-SPEC-25, E5-SPEC-30. The lost-confirmation retry, in its
    positive form: the operator re-submits the attempt they never saw confirmed
    and gets the chart that already exists, not a second one."""
    body = _request(str(uuid.uuid4()))

    first = client.post("/intake", json=body)
    assert first.status_code == 201
    after_first = _counts(session_factory)

    second = client.post("/intake", json=body)
    assert second.status_code == 201
    assert second.json()["patient_id"] == first.json()["patient_id"]

    assert _counts(session_factory) == after_first
    assert after_first == {"patients": 1, "coverages": 1, "consents": 2, "submissions": 1}
    # The replay skips the match-key hook with everything else it skips: no
    # patient was created, so there is no new pair to queue.
    assert match_key_calls == [first.json()["patient_id"]]


def test_the_replay_is_indistinguishable_from_the_original(client):
    """E5-SPEC-31. No replay marker, no new status: the retry is the confirmation
    the operator lost, so the response model and status must be the ones the
    first attempt answered with (requirements D-5). Only elapsed_seconds, a
    measurement, may differ."""
    body = _request(str(uuid.uuid4()))

    first = client.post("/intake", json=body)
    second = client.post("/intake", json=body)

    assert second.status_code == first.status_code == 201
    assert set(second.json()) == set(first.json())
    assert second.json()["patient_id"] == first.json()["patient_id"]
    assert second.json()["eligibility"] == first.json()["eligibility"]
    assert isinstance(second.json()["elapsed_seconds"], float)


def test_the_submission_record_binds_the_identifier_to_the_registration(
    client, session_factory
):
    """E5-SPEC-29. One row, written with the registration it names."""
    body = _request(str(uuid.uuid4()))
    r = client.post("/intake", json=body)

    session = session_factory()
    try:
        row = session.query(models_mod.RegistrationSubmission).one()
        assert row.submission_id == body["submission_id"]
        assert row.patient_id == r.json()["patient_id"]
    finally:
        session.close()


def test_a_failed_registration_records_no_submission(client, session_factory, monkeypatch):
    """E5-SPEC-29. The record lives in the registration's transaction, so a
    registration that did not survive leaves no identifier claimed — otherwise a
    retry of a submission that never registered anything would replay a chart
    that does not exist."""
    def _boom(db, req, fingerprint):
        db.rollback()
        raise app_mod.HTTPException(status_code=503, detail="registration store unavailable")

    monkeypatch.setattr(app_mod, "_create_registration", _boom)
    r = client.post("/intake", json=_request(str(uuid.uuid4())))
    assert r.status_code == 503
    assert _counts(session_factory) == {
        "patients": 0,
        "coverages": 0,
        "consents": 0,
        "submissions": 0,
    }


# --------------------------------------------------------------------------- #
# a replay must match the recorded content (E5-SPEC-41, E5-SPEC-42)
# --------------------------------------------------------------------------- #
CONFLICT_DETAIL = "registration submission conflict"


def _stored_patient(session_factory):
    session = session_factory()
    try:
        patient = session.query(models_mod.Patient).one()
        coverage = session.query(models_mod.InsuranceCoverage).one()
        return {"dob": patient.dob, "member_id": coverage.member_id}
    finally:
        session.close()


@pytest.mark.parametrize(
    "edited, changed_value, label",
    [
        ({"dob": "1985-03-21"}, "1985-03-21", "demographics"),
        ({"member_id": "EXMP000999"}, "EXMP000999", "insurance"),
        (
            {"consents": ("npp_ack", "treatment_consent", "roi_consent")},
            "roi_consent",
            "consents",
        ),
    ],
)
def test_a_recorded_identifier_with_different_content_is_refused(
    client, session_factory, caplog, edited, changed_value, label
):
    """E5-SPEC-42. The identifier names the ATTEMPT; it does not say the content
    is the same. Answering 201 for an edited retry confirms a chart that never
    received the edit — the defect codex found on PR #76 round 2, where the desk
    saw success and the stored DOB was still the typo.

    The refusal must also be silent about content: the detail is a constant, and
    nothing in the response or the log echoes what changed."""
    submission_id = str(uuid.uuid4())
    first = client.post("/intake", json=_request(submission_id))
    assert first.status_code == 201
    before = _counts(session_factory)
    stored_before = _stored_patient(session_factory)

    with caplog.at_level(logging.INFO):
        retry = client.post("/intake", json=_request(submission_id, **edited))

    assert retry.status_code == 409, label
    assert retry.json()["detail"] == CONFLICT_DETAIL
    # Nothing created, nothing modified: the recorded row and the chart it names
    # are exactly as the original attempt left them.
    assert _counts(session_factory) == before
    assert _stored_patient(session_factory) == stored_before
    assert changed_value not in retry.text
    # The refusal's own log records, not the request-metadata line: that line is
    # the D1 projection, and it carries the consent kinds by design (a closed,
    # pinned vocabulary — schemas.ConsentKind). What must never appear is what
    # the refusal knows and nothing else does: the differing values, or either
    # fingerprint, which together would say which request changed what.
    refusal = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert refusal, "the refusal must log something — an unexplained 409 is unoperable"
    for record in refusal:
        message = record.getMessage()
        assert changed_value not in message
        assert "fingerprint=" not in message


def test_an_edited_retry_after_a_lost_response_is_refused_and_the_chart_stands(
    client, session_factory
):
    """E5-SPEC-42, codex PR #76 round 2, end to end. The scenario as reported:
    the registration commits, the response is lost, the operator corrects a
    typo'd DOB and member id and resubmits. It used to answer 201 for the
    original chart in 0.03s while `SELECT dob, member_id` still returned the
    originals — the same query proves the fix."""
    submission_id = str(uuid.uuid4())
    first = client.post(
        "/intake", json=_request(submission_id, dob="1985-03-12", member_id="EXMP000201")
    )
    assert first.status_code == 201

    corrected = client.post(
        "/intake", json=_request(submission_id, dob="1985-03-21", member_id="EXMP000999")
    )

    assert corrected.status_code == 409
    assert _stored_patient(session_factory) == {
        "dob": "1985-03-12",
        "member_id": "EXMP000201",
    }
    assert _counts(session_factory)["patients"] == 1
    # The 409 must not echo the edited insurance either. The old behaviour
    # re-verified eligibility on the REQUEST's insurance, so the 201 confirmed a
    # member id the chart never received.
    assert "EXMP000999" not in corrected.text


def test_a_reordered_consent_list_is_the_same_attempt(client, session_factory):
    """E5-SPEC-30, plan D-19. The fingerprint is computed over the VALIDATED
    payload with the consents sorted, so a genuine re-submission whose form
    happened to serialize the same consents in another order still replays. A
    later "optimization" to hashing the raw body reddens here — and would turn
    every such retry into a 409 the operator cannot get past."""
    submission_id = str(uuid.uuid4())
    first = client.post(
        "/intake", json=_request(submission_id, consents=("npp_ack", "treatment_consent"))
    )
    second = client.post(
        "/intake", json=_request(submission_id, consents=("treatment_consent", "npp_ack"))
    )

    assert second.status_code == 201
    assert second.json()["patient_id"] == first.json()["patient_id"]
    assert _counts(session_factory)["patients"] == 1


def test_a_collision_loser_carrying_different_content_is_refused(
    client, session_factory, monkeypatch
):
    """E5-SPEC-32 x E5-SPEC-42. The loser of the race compares too. Its payload
    may differ from the winner's, and answering the winner's patient_id for
    different content is the same silent confirmation the mismatch path exists
    to refuse — just reached by the concurrent route rather than the sequential
    one."""
    submission_id = str(uuid.uuid4())
    winner = client.post("/intake", json=_request(submission_id))
    assert winner.status_code == 201
    before = _counts(session_factory)

    real_find = app_mod._find_registration
    lookups = {"n": 0}

    def _blind_on_the_first_look(db, sid):
        lookups["n"] += 1
        return None if lookups["n"] == 1 else real_find(db, sid)

    monkeypatch.setattr(app_mod, "_find_registration", _blind_on_the_first_look)

    loser = client.post("/intake", json=_request(submission_id, dob="1985-03-21"))

    assert loser.status_code == 409
    assert loser.json()["detail"] == CONFLICT_DETAIL
    assert _counts(session_factory) == before


# --------------------------------------------------------------------------- #
# the fingerprint key (E5-SPEC-41, plan D-19)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("recorded", [False, True], ids=["fresh", "recorded"])
def test_an_unkeyed_service_refuses_to_register_at_all(
    client, session_factory, monkeypatch, recorded
):
    """E5-SPEC-41, fail-closed. An unkeyed fingerprint of guessable fields is a
    dictionary-reversible confirmation oracle, and it reaches a persisted
    column — so with no key the service refuses rather than degrading to a plain
    hash or skipping the comparison. The guard runs BEFORE the replay lookup, so
    a request naming an already-recorded identifier cannot slip past it either.

    This test defeats the autouse key fixture on purpose: it is the one case
    whose whole subject is the missing key."""
    submission_id = str(uuid.uuid4())
    if recorded:
        assert client.post("/intake", json=_request(submission_id)).status_code == 201
    before = _counts(session_factory)

    monkeypatch.setattr(config_mod.settings, "registration_fingerprint_key", "")
    r = client.post("/intake", json=_request(submission_id))

    assert r.status_code == 503
    assert r.json()["detail"] == "registration store unavailable"
    assert _counts(session_factory) == before


def test_the_fingerprint_is_keyed_and_reveals_no_submitted_value():
    """E5-SPEC-41, docs/landmines.md §3. Two properties, both load-bearing: the
    digest carries none of the values it was computed over, and it depends on
    the key — a refactor to a plain `hashlib.sha256(...)` of the same payload
    would still pass the first check while making the column a reversible oracle
    over DOB/SSN/member id, and only the second catches it."""
    req = schemas_mod.IntakeRequest(
        submission_id=str(uuid.uuid4()),
        demographics={
            "name": ADVERSARIAL["name"],
            "ssn": ADVERSARIAL["ssn"],
            "dob": ADVERSARIAL["dob"],
            "notes": "smuggled Quentin Gonzalez 123456789",
        },
        insurance={"member_id": "EXMP000777"},
        consents=["npp_ack"],
    )

    original = config_mod.settings.registration_fingerprint_key
    try:
        config_mod.settings.registration_fingerprint_key = "key-one"
        first = app_mod._payload_fingerprint(req)
        config_mod.settings.registration_fingerprint_key = "key-two"
        second = app_mod._payload_fingerprint(req)
    finally:
        config_mod.settings.registration_fingerprint_key = original

    assert first != second, "the fingerprint does not depend on the key — is it a plain hash?"
    for value in (*ADVERSARIAL.values(), "EXMP000777", "smuggled"):
        assert value not in first
        assert value not in second


def test_the_stored_fingerprint_carries_no_submitted_value(client, session_factory):
    """E5-SPEC-41 as persisted. The column is the artefact a later reader (or a
    database dump) meets, so the scan runs against what is actually stored, not
    only against what the helper returns."""
    body = _request(
        str(uuid.uuid4()),
        name=ADVERSARIAL["name"],
        ssn=ADVERSARIAL["ssn"],
        dob=ADVERSARIAL["dob"],
        member_id="EXMP000777",
    )
    assert client.post("/intake", json=body).status_code == 201

    session = session_factory()
    try:
        stored = session.execute(
            select(models_mod.RegistrationSubmission.payload_fingerprint)
        ).scalar_one()
    finally:
        session.close()

    assert len(stored) == 64 and all(c in "0123456789abcdef" for c in stored)
    for value in (*ADVERSARIAL.values(), "EXMP000777", "1 Example Way"):
        assert value not in stored


# --------------------------------------------------------------------------- #
# a fresh identifier is never a replay (E5-SPEC-36, E5-SPEC-37)
# --------------------------------------------------------------------------- #
def test_two_identifiers_for_one_person_still_fork_two_charts(
    client, session_factory, match_key_calls
):
    """E5-SPEC-36, E5-SPEC-37. Idempotency must not become a master patient
    index. D5 is a documented deliberate defect: the same human registered twice
    still gets two charts, and the pair is still queued for a human to judge and
    merged by nobody."""
    first = client.post("/intake", json=_request(str(uuid.uuid4())))
    second = client.post("/intake", json=_request(str(uuid.uuid4())))

    assert first.json()["patient_id"] != second.json()["patient_id"]
    assert _counts(session_factory)["patients"] == 2
    # The match key ran for both registrations — the duplicate pair is queued
    # exactly as it is today.
    assert match_key_calls == [first.json()["patient_id"], second.json()["patient_id"]]


# --------------------------------------------------------------------------- #
# rejection (E5-SPEC-40)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "mutate, label",
    [
        (lambda body: body.pop("submission_id"), "missing"),
        (lambda body: body.update(submission_id="not-a-uuid"), "malformed"),
        (lambda body: body.update(submission_id=""), "blank"),
        (lambda body: body.update(submission_id=None), "null"),
        # Not-v4 is not well-formed for this field (Codex review, PR #76): the
        # contract declares a UUIDv4, and the nil / v1 / v5 spellings are the
        # accidental ways a caller reuses one identifier across patients, which
        # would replay the first patient's chart. Schema-level cases and the
        # limit of this check are in tests/test_intake_schemas.py.
        (
            lambda body: body.update(
                submission_id="00000000-0000-0000-0000-000000000000"
            ),
            "nil uuid",
        ),
        (lambda body: body.update(submission_id=str(uuid.uuid1())), "v1 uuid"),
        (
            lambda body: body.update(
                submission_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "Sample Patient"))
            ),
            "v5 uuid",
        ),
    ],
)
def test_a_missing_or_malformed_identifier_is_rejected_and_writes_nothing(
    client, session_factory, mutate, label
):
    """E5-SPEC-40. A rejection by the submitted values, so it lands in e4's
    correctable-at-the-desk branch (E4-SPEC-6) rather than needing a fifth result
    branch. Accepted residual: this particular rejection is a portal bug, not
    something the operator can correct — plan Landmines, decision D-10."""
    body = _request(str(uuid.uuid4()))
    mutate(body)

    r = client.post("/intake", json=body)

    assert r.status_code == 422, label
    assert _counts(session_factory) == {
        "patients": 0,
        "coverages": 0,
        "consents": 0,
        "submissions": 0,
    }


def test_two_spellings_of_one_identifier_cannot_both_claim_a_registration(
    client, session_factory
):
    """E5-SPEC-40. The identifier is canonicalized through UUID, so an uppercase
    or braced spelling of the same value replays rather than registering again —
    two spellings claiming two charts would be the defect wearing a hat."""
    submission_id = str(uuid.uuid4())
    first = client.post("/intake", json=_request(submission_id))
    second = client.post("/intake", json=_request(submission_id.upper()))

    assert second.status_code == 201
    assert second.json()["patient_id"] == first.json()["patient_id"]
    assert _counts(session_factory)["patients"] == 1


# --------------------------------------------------------------------------- #
# the concurrent collision (E5-SPEC-32, E5-SPEC-33)
# --------------------------------------------------------------------------- #
def test_a_collision_replays_the_winner_instead_of_writing_twice(
    client, session_factory, monkeypatch, match_key_calls
):
    """E5-SPEC-32. The race the UNIQUE constraint decides: two requests carry one
    identifier, both look up nothing, and the loser's insert is rejected. The
    loser must then read the winner's registration and answer with it — the
    winner has committed by definition, which is what released the lock, so one
    re-read suffices and nothing polls."""
    body = _request(str(uuid.uuid4()))
    winner = client.post("/intake", json=body)
    assert winner.status_code == 201
    match_key_calls.clear()

    # Drive the race directly: the loser's FIRST lookup returns nothing, as it
    # did for both racers before either committed, so it proceeds to an insert
    # the constraint now rejects. Every later read is the real one — the re-read
    # after the collision has to find the winner, and that is the half of
    # E5-SPEC-32 worth proving.
    real_find = app_mod._find_registration
    lookups = {"n": 0}

    def _blind_on_the_first_look(db, submission_id):
        lookups["n"] += 1
        return None if lookups["n"] == 1 else real_find(db, submission_id)

    monkeypatch.setattr(app_mod, "_find_registration", _blind_on_the_first_look)

    loser = client.post("/intake", json=body)

    assert loser.status_code == 201
    assert loser.json()["patient_id"] == winner.json()["patient_id"]
    assert _counts(session_factory) == {
        "patients": 1,
        "coverages": 1,
        "consents": 2,
        "submissions": 1,
    }
    # The loser created no patient, so it queued no pair.
    assert match_key_calls == []


def test_a_bounded_wait_that_expires_answers_503_and_registers_nothing(
    client, session_factory, monkeypatch
):
    """E5-SPEC-33. Postgres raises lock_not_available (55P03) when the bound
    expires; it reaches the existing "registration store unavailable" branch, so
    the portal renders it in the system-failure branch it already has and no
    fifth result branch appears. Accepted residual (D-11): the answer is
    imprecise — the winner may have saved the registration — and the operator's
    next retry carries the same identifier and replays into the confirmation."""

    def _expired(db):
        raise OperationalError(
            "SET LOCAL lock_timeout", {}, Exception("canceling statement due to lock timeout")
        )

    monkeypatch.setattr(app_mod, "_bound_the_collision_wait", _expired)

    r = client.post("/intake", json=_request(str(uuid.uuid4())))

    assert r.status_code == 503
    assert r.json()["detail"] == "registration store unavailable"
    assert _counts(session_factory) == {
        "patients": 0,
        "coverages": 0,
        "consents": 0,
        "submissions": 0,
    }


class _RecordingBind:
    def __init__(self, dialect_name):
        self.dialect = type("_D", (), {"name": dialect_name})()


class _RecordingSession:
    """Just enough Session for the bounded-wait helper: a bind with a dialect
    name, and a record of what was executed."""

    def __init__(self, dialect_name):
        self._bind = _RecordingBind(dialect_name)
        self.executed = []

    def get_bind(self):
        return self._bind

    def execute(self, statement, *a, **k):
        self.executed.append(str(statement))


def test_the_bounded_wait_is_issued_on_postgres_with_the_configured_value():
    """E5-SPEC-33, plan D-15. The knob is SECONDS and lock_timeout's unit is
    milliseconds, so the pin asserts the issued VALUE, not merely that a
    statement was issued: a dropped `* 1000` would shrink the bound 1000x and
    turn every routine collision wait into a 503, and only the value catches it."""
    db = _RecordingSession("postgresql")
    app_mod._bound_the_collision_wait(db)

    assert len(db.executed) == 1
    assert db.executed[0] == "SET LOCAL lock_timeout = '5000ms'"
    assert config_mod.settings.registration_lock_wait_seconds == 5


def test_the_bounded_wait_is_skipped_off_postgres():
    """The guard exists because these tests run on in-memory SQLite, which
    serializes writers and has no lock_timeout. It must stay a dialect guard and
    not quietly become "never" — the test above is the other half of that pin."""
    db = _RecordingSession("sqlite")
    app_mod._bound_the_collision_wait(db)
    assert db.executed == []


def test_the_bound_is_interpolated_from_config_as_an_integer(monkeypatch):
    """`SET` takes no bind parameters, so the value is interpolated. It must
    reach the statement from config and never from a request, and it is coerced
    to an int before it gets there."""
    monkeypatch.setattr(config_mod.settings, "registration_lock_wait_seconds", 1.5)
    db = _RecordingSession("postgresql")
    app_mod._bound_the_collision_wait(db)
    assert db.executed == ["SET LOCAL lock_timeout = '1500ms'"]


# --------------------------------------------------------------------------- #
# PHI (E5-SPEC-38, E5-SPEC-39) — docs/landmines.md §3 negative tests
# --------------------------------------------------------------------------- #
ADVERSARIAL = {
    "name": "Quentin Gonzalez",
    "ssn": "123456789",
    "dob": "1985-03-12",
}


def test_the_identifier_carries_no_submitted_value_anywhere_it_lands(
    client, session_factory, caplog
):
    """E5-SPEC-38, E5-SPEC-39. A key hashed from SSN/DOB/name would put PHI in a
    log line, a response body and a new stored column at once — and would also
    make two genuine registrations for one person collide, which is E5-SPEC-36,
    i.e. an accidental master patient index. The identifier is random, so all
    three surfaces are scanned for every submitted value."""
    submission_id = str(uuid.uuid4())
    body = _request(
        submission_id,
        name=ADVERSARIAL["name"],
        ssn=ADVERSARIAL["ssn"],
        dob=ADVERSARIAL["dob"],
    )

    with caplog.at_level(logging.INFO):
        r = client.post("/intake", json=body)
    assert r.status_code == 201

    # Guard against a vacuous pass: the scan below iterates caplog.records, so
    # zero records would make every assertion skip silently.
    assert any("POST /intake" in record.getMessage() for record in caplog.records)

    session = session_factory()
    try:
        stored = session.execute(
            select(models_mod.RegistrationSubmission.submission_id)
        ).scalar_one()
    finally:
        session.close()

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert submission_id in logged, (
        "the identifier is the correlation key that makes a lost-confirmation retry "
        "traceable at all — E5-SPEC-39 turns on it being logged and disclosing nothing"
    )

    for value in (
        ADVERSARIAL["name"],
        ADVERSARIAL["ssn"],
        ADVERSARIAL["dob"],
        body["insurance"]["member_id"],
    ):
        assert value not in stored
        assert value not in submission_id
        assert value not in logged
        assert value not in r.text


def test_the_log_projection_carries_the_identifier_and_no_new_value():
    """E5-SPEC-39. log_metadata gains exactly one key, and every other entry
    stays a boolean presence flag — the projection is the D1 control, and an
    addition to it is the one place a value could get copied out."""
    schemas_mod = sys.modules.get("intake_schemas_idem") or load_module(
        "services/intake-service/schemas.py", "intake_schemas_idem"
    )
    submission_id = str(uuid.uuid4())
    req = schemas_mod.IntakeRequest(
        submission_id=submission_id,
        demographics={
            "name": ADVERSARIAL["name"],
            "ssn": ADVERSARIAL["ssn"],
            "dob": ADVERSARIAL["dob"],
            "notes": "smuggled Quentin Gonzalez 123456789",
        },
        consents=["npp_ack"],
    )

    meta = schemas_mod.log_metadata(req)

    assert meta["submission_id"] == submission_id
    for key, value in meta.items():
        if key in ("submission_id", "consents"):
            continue
        assert isinstance(value, bool), f"{key} is not a presence flag"
    flat = str(meta)
    for value in ADVERSARIAL.values():
        assert value not in flat


# --------------------------------------------------------------------------- #
# retention (E5-SPEC-34)
# --------------------------------------------------------------------------- #
def test_no_code_path_expires_or_prunes_a_submission_record():
    """E5-SPEC-34, requirements D-7. Rows are kept FOREVER, deliberately: a
    retention horizon is a date past which a late retry silently creates the
    duplicate this table exists to prevent. The unbounded growth is the accepted
    cost, recorded in the schema comment and the migration header.

    A structural scan rather than prose, because "we decided not to build a
    pruner" is exactly the kind of decision a later convenience commit undoes
    without noticing — and the failure mode is silent, showing up only as a
    duplicate chart weeks later.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    tracked = subprocess.run(
        ["git", "ls-files", "services", "db", "frontend/app", "eval"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    offenders = []
    for name in tracked:
        path = root / name
        if not path.is_file() or path.suffix not in (".py", ".sql", ".ts", ".tsx", ".yaml", ".yml"):
            continue
        text_ = path.read_text(errors="ignore")
        if "registration_submissions" not in text_ and "RegistrationSubmission" not in text_:
            continue
        for line in text_.splitlines():
            lowered = line.lower()
            if any(
                verb in lowered
                for verb in ("delete from", "db.delete", "truncate", "drop table", ".purge(")
            ):
                offenders.append(f"{name}: {line.strip()}")

    assert offenders == [], (
        "a submission record is deleted, pruned or truncated somewhere — "
        f"E5-SPEC-34 keeps them forever: {offenders}"
    )


# --------------------------------------------------------------------------- #
# the DDL the collision path keys on (E5-SPEC-29, E5-SPEC-32, E5-SPEC-41)
# --------------------------------------------------------------------------- #
_DDL_FILES = ("db/migrations/010_registration_submissions.sql", "db/schema.sql")


def _ddl_text(name):
    root = pathlib.Path(__file__).resolve().parent.parent
    return (root / name).read_text()


@pytest.mark.parametrize("name", _DDL_FILES)
def test_the_unique_constraint_is_named_the_name_the_collision_path_matches(name):
    """E5-SPEC-32. `_is_submission_collision` matches the constraint BY STRING,
    and nothing in these SQLite tests can tell whether the real DDL issues that
    name: an inline `submission_id TEXT NOT NULL UNIQUE` makes Postgres name it
    `registration_submissions_submission_id_key`, which matches neither the
    constraint name nor the SQLite spelling. _SubmissionAlreadyRecorded would
    then never be raised, a routine concurrent collision would fall through to
    the 503 branch instead of replaying, and E5-SPEC-33's imprecise answer would
    swallow the evidence — visible only against real Postgres."""
    text_ = _ddl_text(name)
    assert app_mod._SUBMISSION_CONSTRAINT in text_, (
        f"{name} does not name the constraint {app_mod._SUBMISSION_CONSTRAINT}"
    )
    for line in text_.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("submission_id") or stripped.startswith("submission_id "):
            assert "unique" not in stripped, (
                f"{name} spells the constraint inline on the column — Postgres would "
                "name it registration_submissions_submission_id_key and the collision "
                "path would stop recognising it"
            )


@pytest.mark.parametrize("name", _DDL_FILES)
def test_both_ddl_files_carry_the_fingerprint_column(name):
    """E5-SPEC-41, docs/landmines.md §2 (schema.sql and the migration are
    hand-synced). The replay comparison reads this column; a file that lacks it
    means a fresh volume and an upgraded one disagree about whether a replay can
    be checked at all."""
    assert "payload_fingerprint" in _ddl_text(name), (
        f"{name} is missing payload_fingerprint — the two files have drifted"
    )
