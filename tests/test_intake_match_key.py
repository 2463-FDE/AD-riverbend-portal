"""
Tests for the ADR 0005 match-key hook in intake-service (W2-SPEC-22, 23, 24, 32).

The contract under test is deliberately lopsided: matching must *observe*
registration and never gate it. So every test here asserts the 201 survives —
a candidate match, an ambiguous group, a conflicting group, and a matcher that
raises all produce the same registration outcome, differing only in what lands
in the review queue.

Sibling-pinning idiom from tests/test_intake_db_error_phi.py: intake-service
has its own config/db/models/schemas/matching, and load_module puts each
service directory on sys.path, so bare sibling names are ambiguous across
services by the time this loads.
"""
import logging
import sys
import uuid

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.dml import Insert
from sqlalchemy.sql.elements import TextClause

from conftest import load_module

_SIBLINGS = ("config", "db", "logging_config", "models", "schemas", "breaker", "matching")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/intake-service/config.py", "intake_config_mk")
sys.modules["db"] = load_module("services/intake-service/db.py", "intake_db_mk")
sys.modules["logging_config"] = load_module(
    "services/intake-service/logging_config.py", "intake_logging_config_mk"
)
sys.modules["models"] = load_module("services/intake-service/models.py", "intake_models_mk")
sys.modules["schemas"] = load_module("services/intake-service/schemas.py", "intake_schemas_mk")
sys.modules["breaker"] = load_module("services/intake-service/breaker.py", "intake_breaker_mk")
sys.modules["matching"] = load_module("services/intake-service/matching.py", "intake_matching_mk")
app_mod = load_module("services/intake-service/app.py", "intake_app_mk")
models_mod = sys.modules["models"]
schemas_mod = sys.modules["schemas"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


NEW_ID = 9001
SSN = "412-55-9981"


def _row(pid, name, dob, address, ssn=SSN):
    return {"id": pid, "name": name, "dob": dob, "ssn": ssn, "address": address}


class _StubResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def scalar_one_or_none(self):
        # The submission-record lookup (e5, E5-SPEC-30) runs before the create,
        # and on this stub it finds nothing: every request here is a first
        # attempt, which is what makes the match key run at all.
        return self._rows[0] if self._rows else None

    def one_or_none(self):
        # Same lookup, since the replay decision reads two columns — the patient
        # id and the recorded content fingerprint (E5-SPEC-41).
        return self._rows[0] if self._rows else None


class _StubSession:
    """Session double that models the two things the hook depends on: the
    normalized-SSN prefilter SELECT, and the queue table's UNIQUE constraint.

    The constraint is modelled rather than assumed: an INSERT that does NOT
    carry ON CONFLICT DO NOTHING raises IntegrityError on a repeated pair,
    exactly as Postgres would. That makes the idempotency test bind the actual
    mechanism — dropping the ON CONFLICT clause turns the test red instead of
    passing on a stub that silently tolerates duplicates.
    """

    def __init__(self, ssn_rows=(), select_error=None):
        self.added = []
        self.executed = []
        self.queue = []                 # (patient_id_a, patient_id_b, source)
        self.commits = 0
        self.rollbacks = 0
        self._ssn_rows = list(ssn_rows)
        self._select_error = select_error

    # -- SQLAlchemy Session surface used by app.py -------------------------
    def get_bind(self):
        # Not Postgres, so the registration's bounded collision wait
        # (`SET LOCAL lock_timeout`) is skipped here — this file's subject is
        # the match key, and both halves of that dialect guard are pinned in
        # tests/test_intake_idempotency.py.
        return type("_Bind", (), {"dialect": type("_D", (), {"name": "sqlite"})()})()

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def flush(self):
        # _create_registration flushes (no arguments) to assign the PK inside
        # the transaction; the coverage and consent rows are added after it, so
        # only the patient is pending here.
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = NEW_ID

    def execute(self, statement, params=None):
        self.executed.append((statement, params))
        if isinstance(statement, TextClause):
            if self._select_error is not None:
                raise self._select_error
            return _StubResult(self._ssn_rows)
        if isinstance(statement, Insert):
            compiled = statement.compile(dialect=postgresql.dialect())
            values = compiled.params
            pair = (values["patient_id_a"], values["patient_id_b"], values["source"])
            if any(q[:2] == pair[:2] for q in self.queue):
                if "ON CONFLICT" not in str(compiled).upper():
                    raise IntegrityError(
                        "INSERT INTO duplicate_review_queue", {},
                        Exception('duplicate key value violates unique constraint "uq_review_pair"'),
                    )
                return _StubResult([])
            self.queue.append(pair)
            return _StubResult([])
        return _StubResult([])


@pytest.fixture(autouse=True)
def fingerprint_key(monkeypatch):
    # These tests call create_intake directly, and it computes the content
    # fingerprint before anything else (E5-SPEC-41, plan D-19) — with no key set
    # it fails closed with a 503 and no registration happens at all. config.py
    # reads os.getenv in the CLASS BODY, so the environment is read at import
    # time and setenv cannot reach it; patch the loaded settings object app.py
    # holds instead.
    #
    # NEVER repair this with a non-empty default in config.py: a default key is a
    # published key, and an unkeyed fingerprint of guessable fields is a
    # dictionary-reversible confirmation oracle over a persisted column.
    # Must clear `_fingerprint_key`'s floor (32 chars, no placeholder
    # sentinel) — PR #76 review round 3.
    monkeypatch.setattr(
        app_mod.settings,
        "registration_fingerprint_key",
        "e5-test-key-not-a-real-secret-0123456789",
    )


def _demographics(name="Maria Gonzalez", dob="1971-03-02", address="12 Elm St", ssn=SSN):
    return schemas_mod.Demographics(
        name=name, dob=dob, ssn=ssn, address=address, created_via="self_service"
    )


def _intake_request(**kwargs):
    # A fresh identifier per request: submission_id names the submission ATTEMPT
    # (E5-SPEC-27), and these tests register the same person repeatedly on
    # purpose — reusing one would replay instead of forking the chart the match
    # key exists to detect (E5-SPEC-36).
    return schemas_mod.IntakeRequest(
        submission_id=str(uuid.uuid4()),
        demographics=_demographics(**kwargs),
        insurance=None,
    )


def _queued_pairs(db):
    return [(a, b) for a, b, _ in db.queue]


MARIA_ROWS = [
    _row(1042, "Maria Gonzalez", "1971-03-02", "12 Elm St"),
    _row(1330, "Maria Gonzales", "1971-03-02", "12 Elm St"),
    _row(1588, "M. Gonzalez", "1971-02-03", "12 Elm St"),
]


# --------------------------------------------------- registration never blocked

def test_candidate_match_queues_pairs_and_still_returns_201():
    db = _StubSession(ssn_rows=MARIA_ROWS)
    resp = app_mod.create_intake(_intake_request(), db)
    assert resp.patient_id == NEW_ID
    assert _queued_pairs(db) == [(1042, 1330), (1042, 1588), (1330, 1588)]
    assert all(source == "intake" for _, _, source in db.queue)


def test_ambiguous_group_queues_nothing_and_still_returns_201():
    # Bridge row: 1~2 (name+DOB), 2~3 (DOB+address), 1/3 conflict. Corroboration
    # does not chain, so nothing is queueable.
    db = _StubSession(ssn_rows=[
        _row(1, "Ana Ruiz", "1990-01-01", "1 A St"),
        _row(2, "Ana Ruis", "1990-01-01", "9 Q Blvd"),
        _row(3, "Zed Kane", "1990-01-01", "9 Q Blvd"),
    ])
    resp = app_mod.create_intake(_intake_request(), db)
    assert resp.patient_id == NEW_ID
    assert _queued_pairs(db) == []


def test_non_mergeable_group_queues_nothing_and_still_returns_201():
    db = _StubSession(ssn_rows=[
        _row(1, "Ana Ruiz", "1990-01-01", "1 A St"),
        _row(2, "Ben Cole", "1962-09-30", "77 Z Blvd"),
    ])
    resp = app_mod.create_intake(_intake_request(), db)
    assert resp.patient_id == NEW_ID
    assert _queued_pairs(db) == []


def test_mixed_group_queues_only_the_in_clique_pair():
    """One SSN carrying a corroborating pair AND two rows that corroborate with
    nobody. The conflict rows must appear in no queued pair — queueing one
    would put two unrelated humans in front of a reviewer as a merge candidate
    (W2-SPEC-21)."""
    db = _StubSession(ssn_rows=[
        _row(1, "Ana Ruiz", "1990-01-01", "1 A St"),
        _row(2, "Ana Ruis", "1990-01-01", "1 A St"),
        _row(3, "Zed Kane", "1975-12-25", "77 Z Blvd"),
        _row(4, "Bo Frost", "1962-09-30", "5 Q Rd"),
    ])
    resp = app_mod.create_intake(_intake_request(), db)
    assert resp.patient_id == NEW_ID
    assert _queued_pairs(db) == [(1, 2)]
    for a, b in _queued_pairs(db):
        assert 3 not in (a, b) and 4 not in (a, b)


def test_row_without_a_usable_ssn_queues_nothing_and_issues_no_query():
    """Tier 2 is deferred, so a row without a usable SSN yields no candidate —
    and the hook returns before touching the database at all."""
    db = _StubSession(ssn_rows=MARIA_ROWS)
    resp = app_mod.create_intake(_intake_request(ssn=None), db)
    assert resp.patient_id == NEW_ID
    assert _queued_pairs(db) == []
    assert not [s for s, _ in db.executed if isinstance(s, TextClause)]


def test_placeholder_ssn_is_not_a_match_key():
    db = _StubSession(ssn_rows=MARIA_ROWS)
    resp = app_mod.create_intake(_intake_request(ssn="000-00-0000"), db)
    assert resp.patient_id == NEW_ID
    assert _queued_pairs(db) == []


# ------------------------------------------------------------- idempotency

def test_repeat_intake_of_the_same_person_queues_no_duplicate_rows():
    """A re-registration re-evaluates the same SSN group and re-derives the same
    pairs. The queue's UNIQUE constraint absorbs them — modelled by the stub,
    which raises IntegrityError on a repeated pair whose INSERT lacks
    ON CONFLICT DO NOTHING (W2-SPEC-31)."""
    db = _StubSession(ssn_rows=MARIA_ROWS)
    app_mod.create_intake(_intake_request(), db)
    first = list(db.queue)
    app_mod.create_intake(_intake_request(), db)
    assert db.queue == first
    assert len(db.queue) == 3


# ---------------------------------------------------- matcher failure path

class _Boom(RuntimeError):
    pass


def test_matcher_failure_still_returns_201_and_records_the_failure(caplog):
    db = _StubSession(select_error=_Boom("match lookup exploded"))
    with caplog.at_level(logging.ERROR):
        resp = app_mod.create_intake(_intake_request(), db)
    assert resp.patient_id == NEW_ID

    failures = [o for o in db.added if isinstance(o, models_mod.MatchEvaluationFailure)]
    assert len(failures) == 1
    assert failures[0].patient_id == NEW_ID
    assert failures[0].error_class == "_Boom"

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "a failed match evaluation must log an ERROR record"
    assert any("_Boom" in m for m in errors)
    for msg in errors:
        assert "match lookup exploded" not in msg


def test_match_failure_is_never_raised_out_of_the_hook():
    """The 201 test above would still pass if the hook re-raised and some outer
    layer swallowed it. Call the hook directly to prove it swallows on its
    own — matching must never become a registration dependency (W2-SPEC-32)."""
    db = _StubSession(select_error=_Boom("boom"))
    assert app_mod._evaluate_match_key(db, NEW_ID, _demographics()) is None


def test_failure_recording_failure_does_not_break_registration(caplog):
    """Both halves down: the match lookup fails and the failure row cannot be
    written either. Registration still completes."""

    class _AlsoFailing(_StubSession):
        def commit(self):
            self.commits += 1
            if self.added and isinstance(self.added[-1], models_mod.MatchEvaluationFailure):
                raise _Boom("failure table unavailable")

    db = _AlsoFailing(select_error=_Boom("match lookup exploded"))
    with caplog.at_level(logging.ERROR):
        resp = app_mod.create_intake(_intake_request(), db)
    assert resp.patient_id == NEW_ID


# --------------------------------------------------------------------- PHI

PHI_SSN_DASHED = "412-55-9981"
PHI_SSN_BARE = "412559981"


def test_no_phi_survives_into_any_log_record_on_the_match_path(caplog):
    """Adversarial: SSN planted in the name and address fields (where pattern
    redaction does not look) and in the driver's own exception message, which
    is where a real DBAPIError carries free text (docs/landmines.md §3)."""
    db = _StubSession(select_error=_Boom(f"lookup failed for ssn={PHI_SSN_DASHED}"))
    with caplog.at_level(logging.DEBUG):
        app_mod.create_intake(
            _intake_request(
                name=f"Adversarial {PHI_SSN_DASHED} Testpatient",
                address=f"12 Elm St {PHI_SSN_BARE}",
            ),
            db,
        )
    assert caplog.records, "the intake path must have logged something"
    for record in caplog.records:
        message = record.getMessage()
        for value in (PHI_SSN_DASHED, PHI_SSN_BARE, "Adversarial", "12 Elm St"):
            assert value not in message, f"PHI leaked into a log record: {message!r}"


def test_successful_match_logs_counts_and_ids_only(caplog):
    db = _StubSession(ssn_rows=MARIA_ROWS)
    with caplog.at_level(logging.DEBUG):
        app_mod.create_intake(
            _intake_request(name=f"Maria {PHI_SSN_DASHED}", address="12 Elm St"), db
        )
    for record in caplog.records:
        message = record.getMessage()
        for value in (PHI_SSN_DASHED, PHI_SSN_BARE, "Maria", "12 Elm St", "1971-03-02"):
            assert value not in message, f"PHI leaked into a log record: {message!r}"


def test_normalized_ssn_is_bound_as_a_parameter_and_never_stored():
    """W2-SPEC-24: the normalized value exists only as a query parameter. No
    column on either new table holds it, and nothing persists it."""
    db = _StubSession(ssn_rows=MARIA_ROWS)
    app_mod.create_intake(_intake_request(), db)

    selects = [(s, p) for s, p in db.executed if isinstance(s, TextClause)]
    assert len(selects) == 1
    _, params = selects[0]
    assert params == {"normalized": PHI_SSN_BARE}

    queue_columns = set(models_mod.DuplicateReviewQueue.__table__.columns.keys())
    failure_columns = set(models_mod.MatchEvaluationFailure.__table__.columns.keys())
    for column in queue_columns | failure_columns:
        assert "ssn" not in column.lower()
    for statement, _ in db.executed:
        if isinstance(statement, Insert):
            assert PHI_SSN_BARE not in str(statement.compile(dialect=postgresql.dialect()).params)


# ------------------------------------------------------- ordering guarantee

def test_match_evaluation_runs_after_the_patient_row_is_committed():
    """The hook sits after _create_registration by design: a matcher that ran
    first, or inside the same transaction, could take registration down with
    it.

    The marker is keyed on the FIRST commit, not on flush() and not on every
    commit. flush() fires inside the registration transaction, so keying it
    there would weaken the assertion to "after the row is flushed", which is
    not the ADR 0005 property; and _evaluate_match_key commits on its own
    success path (app.py), so an unguarded marker would fire twice.
    """
    order = []

    class _OrderedSession(_StubSession):
        def commit(self):
            # Only the first commit is the registration boundary ADR 0005
            # orders the hook against.
            if "patient-committed" not in order:
                order.append("patient-committed")
            super().commit()

        def execute(self, statement, params=None):
            if isinstance(statement, TextClause):
                order.append("match-evaluated")
            return super().execute(statement, params)

    db = _OrderedSession(ssn_rows=MARIA_ROWS)
    app_mod.create_intake(_intake_request(), db)
    assert order == ["patient-committed", "match-evaluated"]


def test_queue_insert_carries_on_conflict_do_nothing():
    db = _StubSession(ssn_rows=MARIA_ROWS)
    app_mod.create_intake(_intake_request(), db)
    inserts = [s for s, _ in db.executed if isinstance(s, Insert)]
    assert inserts
    for statement in inserts:
        sql = str(statement.compile(dialect=postgresql.dialect())).upper()
        assert "ON CONFLICT" in sql and "DO NOTHING" in sql


@pytest.mark.parametrize("ssn", ["412 55 9981", "412559981", "412-55-9981"])
def test_ssn_formatting_variants_normalize_to_the_same_match_key(ssn):
    db = _StubSession(ssn_rows=MARIA_ROWS)
    app_mod.create_intake(_intake_request(ssn=ssn), db)
    selects = [p for s, p in db.executed if isinstance(s, TextClause)]
    assert selects == [{"normalized": PHI_SSN_BARE}]
