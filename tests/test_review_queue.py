"""
Tests for the front-desk duplicate review queue in intake-service
(W2-SPEC-25, 26, 27).

The queue is where a flagged pair meets a human. Its whole contract is that
recording a judgment is *only* recording a judgment: nothing here may merge,
alter, or delete a patient row, because a wrong automated merge
cross-contaminates two people's charts (ADR 0005 decision 3). That property is
asserted negatively — the patient rows are checked field-by-field after a
disposition, not merely "no exception raised".

The gateway half of this surface (capability gating, and the deciding username
coming from the session rather than the client) is in
tests/test_gateway_review_queue.py and tests/test_gateway_authz.py.
"""
import logging
import sys
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.sql.dml import Update

from conftest import load_module

_SIBLINGS = ("config", "db", "logging_config", "models", "schemas", "breaker", "matching")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/intake-service/config.py", "intake_config_rq")
sys.modules["db"] = load_module("services/intake-service/db.py", "intake_db_rq")
sys.modules["logging_config"] = load_module(
    "services/intake-service/logging_config.py", "intake_logging_config_rq"
)
sys.modules["models"] = load_module("services/intake-service/models.py", "intake_models_rq")
sys.modules["schemas"] = load_module("services/intake-service/schemas.py", "intake_schemas_rq")
sys.modules["breaker"] = load_module("services/intake-service/breaker.py", "intake_breaker_rq")
sys.modules["matching"] = load_module("services/intake-service/matching.py", "intake_matching_rq")
app_mod = load_module("services/intake-service/app.py", "intake_app_rq")
models_mod = sys.modules["models"]
db_mod = sys.modules["db"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


PATIENT_FIELDS = ("id", "mrn", "name", "dob", "ssn", "gender", "address",
                  "phone", "email", "notes", "created_via")


def _patient(pid, name, dob, ssn="412-55-9981", address="118 Maple Ave"):
    return models_mod.Patient(
        id=pid, name=name, dob=dob, ssn=ssn, address=address,
        created_via="self_service", mrn=f"MRN{pid}", gender="F",
        phone="555-0100", email="p@example.test", notes="clinical note",
    )


def _pair(pair_id, a, b, source="intake", status="pending"):
    return models_mod.DuplicateReviewQueue(
        id=pair_id, patient_id_a=a, patient_id_b=b, source=source, status=status,
        created_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
    )


class _StubResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


_UPDATABLE = ("status", "disposition", "decided_by", "decided_at")


class _StubSession:
    def __init__(self, pairs=(), patients=(), error=None, race_on_read=None):
        self.pairs = {p.id: p for p in pairs}
        self.patients = {p.id: p for p in patients}
        self.commits = 0
        self.rollbacks = 0
        self.added = []
        self.deleted = []
        self.updates = 0
        self._error = error
        # A callable run once, after the disposition handler's existence read
        # and before its write — the window a second reviewer commits in.
        self._race_on_read = race_on_read

    def execute(self, statement, params=None):
        if self._error is not None:
            raise self._error
        if isinstance(statement, Update):
            return _StubResult(self._apply_update(statement))
        target = str(statement).lower()
        if "duplicate_review_queue" in target:
            return _StubResult(
                sorted(
                    (p for p in self.pairs.values() if p.status == "pending"),
                    key=lambda p: p.id,
                )
            )
        return _StubResult([p for p in self.patients.values()])

    def _apply_update(self, statement):
        """A conditional UPDATE, evaluated against the row as it stands NOW.

        That is the whole point: the WHERE predicate is re-checked at write
        time, not at read time, so a row another transaction dispositioned in
        between matches nothing and the caller loses the race instead of
        overwriting the winner.
        """
        self.updates += 1
        bound = statement.compile().params
        # SET binds keep the bare column name; WHERE binds are suffixed.
        pair = self.pairs.get(bound["id_1"])
        required_status = bound.get("status_1")
        if pair is None or (required_status is not None and pair.status != required_status):
            return []
        for field in _UPDATABLE:
            if field in bound:
                setattr(pair, field, bound[field])
        return [{field: getattr(pair, field) for field in ("id",) + _UPDATABLE}]

    def get(self, model, pk):
        if self._error is not None:
            raise self._error
        if model is models_mod.DuplicateReviewQueue:
            row = self.pairs.get(pk)
            if row is not None and self._race_on_read is not None:
                race, self._race_on_read = self._race_on_read, None
                # What this request read is a snapshot: the competing
                # disposition commits after the read and does not retroactively
                # change what this transaction saw.
                snapshot = _pair(row.id, row.patient_id_a, row.patient_id_b,
                                 source=row.source, status=row.status)
                race(row)
                return snapshot
            return row
        return self.patients.get(pk)

    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, obj):
        pass

    def close(self):
        pass


def _client(session):
    app_mod.app.dependency_overrides[app_mod.get_db] = lambda: session
    return TestClient(app_mod.app, raise_server_exceptions=False)


def teardown_function():
    app_mod.app.dependency_overrides.clear()


MARIA_A = _patient(1042, "Maria Gonzalez", "1971-03-02")
MARIA_B = _patient(1330, "Maria Gonzales", "1971-03-02")
MARIA_C = _patient(1588, "M. Gonzalez", "1971-02-03")


# ------------------------------------------------------------------ listing

def test_queue_lists_pending_pairs_with_both_patients():
    session = _StubSession(
        pairs=[_pair(1, 1042, 1330), _pair(2, 1042, 1588)],
        patients=[MARIA_A, MARIA_B, MARIA_C],
    )
    r = _client(session).get("/review-queue")
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["id"] for i in items] == [1, 2]
    assert items[0]["patient_a"]["id"] == 1042
    assert items[0]["patient_a"]["name"] == "Maria Gonzalez"
    assert items[0]["patient_b"]["id"] == 1330
    assert items[0]["source"] == "intake"


def test_dispositioned_pairs_are_not_listed():
    session = _StubSession(
        pairs=[_pair(1, 1042, 1330), _pair(2, 1042, 1588, status="dispositioned")],
        patients=[MARIA_A, MARIA_B, MARIA_C],
    )
    r = _client(session).get("/review-queue")
    assert [i["id"] for i in r.json()["items"]] == [1]


def test_empty_queue_is_an_empty_list_not_an_error():
    r = _client(_StubSession()).get("/review-queue")
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_queue_response_carries_no_ssn_or_address():
    """W2-SPEC-24 adjacency and minimum-necessary: the reviewer needs enough to
    judge a pair, not the whole demographics row. front_desk access to patient
    SSN is an open debt row; this surface must not widen it."""
    session = _StubSession(pairs=[_pair(1, 1042, 1330)], patients=[MARIA_A, MARIA_B])
    body = _client(session).get("/review-queue").text
    for value in ("412-55-9981", "412559981", "118 Maple Ave", "555-0100",
                  "p@example.test", "clinical note"):
        assert value not in body
    assert "Maria Gonzalez" in body  # ...but the name a reviewer judges on is there


def test_pair_referencing_a_missing_patient_is_skipped_not_half_rendered():
    session = _StubSession(pairs=[_pair(1, 1042, 9999)], patients=[MARIA_A])
    r = _client(session).get("/review-queue")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_queue_database_error_is_503_with_class_name_only(caplog):
    boom = OperationalError("SELECT * FROM duplicate_review_queue", {},
                            Exception("connection refused for maria gonzalez"))
    session = _StubSession(error=boom)
    with caplog.at_level(logging.ERROR):
        r = _client(session).get("/review-queue")
    assert r.status_code == 503
    errors = [rec.getMessage() for rec in caplog.records if rec.levelno >= logging.ERROR]
    assert any("OperationalError" in m for m in errors)
    for message in errors:
        assert "connection refused" not in message
        assert "maria gonzalez" not in message


# -------------------------------------------------------------- disposition

@pytest.mark.parametrize("verdict", ["duplicate_confirmed", "not_duplicate"])
def test_disposition_records_the_judgment_and_the_deciding_user(verdict):
    pair = _pair(1, 1042, 1330)
    session = _StubSession(pairs=[pair], patients=[MARIA_A, MARIA_B])
    r = _client(session).post(
        "/review-queue/1/disposition",
        json={"disposition": verdict, "decided_by": "fdesk1"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "dispositioned"
    assert r.json()["disposition"] == verdict
    assert r.json()["decided_by"] == "fdesk1"
    assert pair.status == "dispositioned"
    assert pair.decided_by == "fdesk1"
    assert pair.decided_at is not None


def test_dispositioned_pair_leaves_the_pending_list():
    pair = _pair(1, 1042, 1330)
    session = _StubSession(pairs=[pair], patients=[MARIA_A, MARIA_B])
    client = _client(session)
    assert [i["id"] for i in client.get("/review-queue").json()["items"]] == [1]
    client.post("/review-queue/1/disposition",
                json={"disposition": "not_duplicate", "decided_by": "fdesk1"})
    assert client.get("/review-queue").json()["items"] == []


def test_disposition_never_touches_a_patient_row():
    """The load-bearing negative (W2-SPEC-27). 'Confirm duplicate' is a
    judgment, not a merge — every patient field must be byte-identical
    afterwards, and nothing may be added to or deleted from the session."""
    before = {p.id: {f: getattr(p, f) for f in PATIENT_FIELDS}
              for p in (MARIA_A, MARIA_B)}
    session = _StubSession(pairs=[_pair(1, 1042, 1330)], patients=[MARIA_A, MARIA_B])
    r = _client(session).post(
        "/review-queue/1/disposition",
        json={"disposition": "duplicate_confirmed", "decided_by": "fdesk1"},
    )
    assert r.status_code == 200
    after = {p.id: {f: getattr(p, f) for f in PATIENT_FIELDS}
             for p in (MARIA_A, MARIA_B)}
    assert after == before
    assert session.added == []
    assert session.deleted == []


def test_unknown_pair_is_404():
    r = _client(_StubSession()).post(
        "/review-queue/77/disposition",
        json={"disposition": "not_duplicate", "decided_by": "fdesk1"},
    )
    assert r.status_code == 404


def test_already_dispositioned_pair_is_409():
    session = _StubSession(pairs=[_pair(1, 1042, 1330, status="dispositioned")])
    r = _client(session).post(
        "/review-queue/1/disposition",
        json={"disposition": "not_duplicate", "decided_by": "fdesk1"},
    )
    assert r.status_code == 409


def test_a_concurrent_disposition_cannot_overwrite_the_first_one():
    """The audit-trail negative (W2-SPEC-26). Two reviewers can both read a
    pair as pending; only a conditional write stops the second from silently
    replacing the first's verdict and username. A read-check-write leaves that
    window open, and the record of who judged a duplicate-patient pair is
    exactly the thing that must not disappear.
    """
    def other_reviewer_commits(row):
        row.status = "dispositioned"
        row.disposition = "not_duplicate"
        row.decided_by = "fdesk1"
        row.decided_at = datetime(2026, 8, 8, 12, tzinfo=timezone.utc)

    pair = _pair(1, 1042, 1330)
    session = _StubSession(
        pairs=[pair], patients=[MARIA_A, MARIA_B],
        race_on_read=other_reviewer_commits,
    )
    r = _client(session).post(
        "/review-queue/1/disposition",
        json={"disposition": "duplicate_confirmed", "decided_by": "fdesk2"},
    )
    assert r.status_code == 409
    # The winner's decision stands, untouched, and the loser committed nothing.
    assert (pair.disposition, pair.decided_by) == ("not_duplicate", "fdesk1")
    assert session.commits == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"disposition": "merge_them", "decided_by": "fdesk1"},   # outside the enum
        {"disposition": "not_duplicate", "decided_by": ""},      # blank decider
        {"disposition": "not_duplicate"},                        # no decider at all
    ],
)
def test_invalid_disposition_payloads_are_rejected(payload):
    session = _StubSession(pairs=[_pair(1, 1042, 1330)])
    r = _client(session).post("/review-queue/1/disposition", json=payload)
    assert r.status_code == 422


def test_disposition_log_line_carries_no_patient_identifier(caplog):
    """The queue row id, the verdict, and the staff username are auditable
    facts; who the pair is about is not logged."""
    session = _StubSession(pairs=[_pair(1, 1042, 1330)], patients=[MARIA_A, MARIA_B])
    with caplog.at_level(logging.DEBUG):
        _client(session).post(
            "/review-queue/1/disposition",
            json={"disposition": "duplicate_confirmed", "decided_by": "fdesk1"},
        )
    messages = [rec.getMessage() for rec in caplog.records]
    assert any("fdesk1" in m and "duplicate_confirmed" in m for m in messages)
    for message in messages:
        for value in ("1042", "1330", "Maria", "412-55-9981", "118 Maple Ave"):
            assert value not in message
