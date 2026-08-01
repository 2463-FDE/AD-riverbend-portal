"""
Tests for scheduling-service's day-queue endpoint, GET /schedule.

The endpoint exists because GET /appointments requires a patient_id, so a
front-desk day view could previously only be built by fanning out one request
per patient — the D8 N+1 pattern. Two things here are worth more than the happy
path:

  * the clinic-day window. Appointments are TIMESTAMPTZ, so a calendar day is
    only a range once a zone is named. Resolving it in UTC (or in the server's
    zone) silently shifts the queue by the UTC offset, and on the two DST
    changeover days a naive +24h window drops or double-counts an hour.
  * the log line. The response is cross-patient PHI, so the handler must record
    the window and the count and nothing else (CLAUDE.md §5 negative-test rule).
"""
import logging
import sys
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from conftest import load_module

_SIBLINGS = ("config", "db", "logging_config", "models", "schemas", "book")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/scheduling-service/config.py", "sched_config_day")
sys.modules["db"] = load_module("services/scheduling-service/db.py", "sched_db_day")
sys.modules["logging_config"] = load_module(
    "services/scheduling-service/logging_config.py", "sched_logging_config_day"
)
sys.modules["models"] = load_module("services/scheduling-service/models.py", "sched_models_day")
sys.modules["schemas"] = load_module("services/scheduling-service/schemas.py", "sched_schemas_day")
sys.modules["book"] = load_module("services/scheduling-service/book.py", "sched_book_day")
app_mod = load_module("services/scheduling-service/app.py", "sched_app_day")
db_mod = sys.modules["db"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class _FakeAppointment:
    """Only the attributes ScheduledVisitOut reads off the ORM object."""

    def __init__(self, id, patient_id, scheduled_for, reason="Follow-up", status="confirmed"):
        self.id = id
        self.patient_id = patient_id
        self.slot_id = 900 + id
        self.provider = "Dr. Nguyen"
        self.reason = reason
        self.location = "Riverbend Main"
        self.scheduled_for = scheduled_for
        self.status = status
        self.created_at = None


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    """Records the statement so the test can read the bind parameters back."""

    def __init__(self, rows=(), raises=None):
        self.rows = list(rows)
        self.raises = raises
        self.stmt = None

    def execute(self, stmt):
        self.stmt = stmt
        if self.raises is not None:
            raise self.raises
        return _FakeResult(self.rows)


def _client(session):
    app_mod.app.dependency_overrides[db_mod.get_db] = lambda: session
    client = TestClient(app_mod.app)
    return client


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app_mod.app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# the clinic-day window
# --------------------------------------------------------------------------- #
def test_bounds_are_utc_and_cover_one_local_day():
    start, end = app_mod._clinic_day_bounds(date(2026, 8, 1))

    assert start.tzinfo is timezone.utc and end.tzinfo is timezone.utc
    # America/New_York is UTC-4 on 2026-08-01, so local midnight is 04:00Z.
    assert start == datetime(2026, 8, 1, 4, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 2, 4, 0, tzinfo=timezone.utc)
    assert (end - start).total_seconds() == 24 * 3600


def test_spring_forward_day_is_23_hours():
    """2026-03-08 is the US spring-forward date; a +24h window would run an hour
    into the next clinic day."""
    start, end = app_mod._clinic_day_bounds(date(2026, 3, 8))
    assert (end - start).total_seconds() == 23 * 3600


def test_fall_back_day_is_25_hours():
    """2026-11-01 is the US fall-back date; a +24h window would drop the last
    hour of the clinic day, i.e. lose appointments."""
    start, end = app_mod._clinic_day_bounds(date(2026, 11, 1))
    assert (end - start).total_seconds() == 25 * 3600


def test_window_is_not_the_utc_day():
    """The discriminating assertion: a UTC-midnight implementation passes every
    length check above and still fails this one."""
    start, _ = app_mod._clinic_day_bounds(date(2026, 8, 1))
    assert start != datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)


def test_configured_zone_is_honoured(monkeypatch):
    """Mutation proof that the setting is read, not hardcoded."""
    monkeypatch.setattr(app_mod.settings, "clinic_timezone", "UTC")
    start, end = app_mod._clinic_day_bounds(date(2026, 8, 1))
    assert start == datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    assert (end - start).total_seconds() == 24 * 3600


# --------------------------------------------------------------------------- #
# the query
# --------------------------------------------------------------------------- #
def test_window_reaches_the_query_as_bind_parameters():
    """Wiring proof: computing the right bounds is worthless if the statement
    filters on something else."""
    session = _FakeSession()
    resp = _client(session).get("/schedule?date=2026-08-01")
    assert resp.status_code == 200

    bound = set(session.stmt.compile().params.values())
    assert datetime(2026, 8, 1, 4, 0, tzinfo=timezone.utc) in bound
    assert datetime(2026, 8, 2, 4, 0, tzinfo=timezone.utc) in bound


def test_rows_carry_the_joined_patient_identity():
    appt = _FakeAppointment(1, 1042, datetime(2026, 8, 1, 14, 0, tzinfo=timezone.utc))
    session = _FakeSession([(appt, "Maria Gonzalez", "M4417")])

    body = _client(session).get("/schedule?date=2026-08-01").json()

    assert body["count"] == 1
    assert body["date"] == "2026-08-01"
    assert body["timezone"] == "America/New_York"
    assert body["items"][0]["patient_name"] == "Maria Gonzalez"
    assert body["items"][0]["mrn"] == "M4417"
    assert body["items"][0]["patient_id"] == 1042


def test_one_query_for_the_whole_day_not_one_per_patient():
    """The reason the endpoint exists: no N+1 (D8)."""
    calls = []
    session = _FakeSession(
        [
            (_FakeAppointment(i, 1000 + i, datetime(2026, 8, 1, 14, 0, tzinfo=timezone.utc)), f"P{i}", f"M{i}")
            for i in range(5)
        ]
    )
    original = session.execute

    def _counting(stmt):
        calls.append(stmt)
        return original(stmt)

    session.execute = _counting
    body = _client(session).get("/schedule?date=2026-08-01").json()

    assert body["count"] == 5
    assert len(calls) == 1


def test_date_is_required():
    assert _client(_FakeSession()).get("/schedule").status_code == 422


def test_bad_date_is_rejected_at_the_boundary():
    assert _client(_FakeSession()).get("/schedule?date=not-a-date").status_code == 422


def test_limit_is_capped_by_the_shared_guardrail():
    resp = _client(_FakeSession()).get("/schedule?date=2026-08-01&limit=9999")
    assert resp.status_code == 422


def test_database_failure_is_503_not_500():
    session = _FakeSession(raises=RuntimeError("connection refused"))
    resp = _client(session).get("/schedule?date=2026-08-01")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "database unavailable"


# --------------------------------------------------------------------------- #
# PHI (CLAUDE.md §5 negative-test rule)
# --------------------------------------------------------------------------- #
def test_log_line_carries_no_patient_phi(caplog):
    """Adversarial: PHI is placed in every field the handler touches, including
    the free-text reason, and the log is scanned for all of it."""
    appt = _FakeAppointment(
        1,
        1042,
        datetime(2026, 8, 1, 14, 0, tzinfo=timezone.utc),
        reason="Maria Gonzalez DOB 1974-03-02 SSN 402-11-4412",
    )
    session = _FakeSession([(appt, "Maria Gonzalez", "M4417")])

    with caplog.at_level(logging.INFO):
        assert _client(session).get("/schedule?date=2026-08-01").status_code == 200

    logged = " ".join(r.getMessage() for r in caplog.records)
    for phi in ("Maria", "Gonzalez", "M4417", "1974-03-02", "402-11-4412", "1042"):
        assert phi not in logged, f"{phi!r} reached the log"
    assert "2026-08-01" in logged  # the window itself is not PHI


def test_database_failure_log_carries_no_phi(caplog):
    """The failure path logs too, and log.exception renders a traceback whose
    frames can hold the bound values."""
    session = _FakeSession(raises=RuntimeError("connection refused"))

    with caplog.at_level(logging.ERROR):
        _client(session).get("/schedule?date=2026-08-01&provider_id=7")

    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "Gonzalez" not in logged
    assert "2026-08-01" in logged
