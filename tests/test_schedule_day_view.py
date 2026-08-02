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
import re
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
config_mod = sys.modules["config"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class _FakeAppointment:
    """Only the attributes ScheduledVisitOut reads off the ORM object.

    ``scheduled_for`` defaults to None because that is what the write path
    actually stores — the booking UI posts no time and the column has no default
    (see the row-shape note on _row below).
    """

    def __init__(self, id, patient_id, scheduled_for=None, reason="Follow-up", status="confirmed"):
        self.id = id
        self.patient_id = patient_id
        self.slot_id = 900 + id
        self.provider = "Dr. Nguyen"
        self.reason = reason
        self.location = "Riverbend Main"
        self.scheduled_for = scheduled_for
        self.status = status
        self.created_at = None


def _row(appointment, name="Maria Gonzalez", mrn="M4417", when=None):
    """One result row in the shape the handler unpacks.

    The fourth element is the COALESCE'd visit time the query computes, NOT
    ``appointment.scheduled_for`` — those differ for every appointment the
    booking UI wrote, which is the whole reason the coalesce is there. Passing
    the appointment's own value here would model the database wrongly and make
    the assertions about the coalesce meaningless.
    """
    return (appointment, name, mrn, when)


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
_VISIT_AT = "coalesce(appointments.scheduled_for, slots.start_at)"


def _compiled(session):
    compiled = session.stmt.compile()
    return str(compiled).lower(), compiled.params


def _where(sql):
    return sql.split("where", 1)[1].split("order by", 1)[0]


def _bound_to(where, operator):
    """The bind parameter name compared to the visit-time expression by
    ``operator``. Resolved from the SQL rather than hardcoded, because
    SQLAlchemy names anonymous binds after the expression they belong to and
    those names shift when the expression does."""
    m = re.search(re.escape(_VISIT_AT) + r"\s*" + re.escape(operator) + r"\s*:(\w+)", where)
    assert m, f"no {operator!r} comparison against the visit time in: {where}"
    return m.group(1)


def test_the_window_bounds_each_side_of_the_right_operator():
    """Wiring proof. The weaker version of this test asserted only that both
    datetimes appeared *somewhere* in the bind parameters, which is satisfied by
    a statement that swaps them (``>= end AND < start``) and returns zero rows
    for every day, forever. So the assertion is on which value sits on which
    side of which comparison, and on the interval being half-open.
    """
    session = _FakeSession()
    assert _client(session).get("/schedule?date=2026-08-01").status_code == 200

    sql, params = _compiled(session)
    where = _where(sql)

    assert params[_bound_to(where, ">=")] == datetime(2026, 8, 1, 4, 0, tzinfo=timezone.utc)
    assert params[_bound_to(where, "<")] == datetime(2026, 8, 2, 4, 0, tzinfo=timezone.utc)
    # Half-open: an inclusive upper edge would put the next day's midnight
    # appointment in both days' queues.
    assert "<=" not in where


def test_the_visit_time_falls_back_to_the_slot_start():
    """The defect this closes: ``appointments.scheduled_for`` is nullable with no
    default and the write path never sets it — the booking UI posts only
    {patient_id, slot_id, provider, reason} (frontend/app/appointments/page.tsx:62)
    and insert_appointment writes the NULL. ``NULL >= x`` is NULL in SQL, so
    filtering on that column alone returns nothing but seeded rows: a day queue
    that looks right in dev and is empty in production.

    Asserted on the compiled statement because the filter runs in Postgres, not
    in Python — the fake session cannot evaluate a predicate.
    """
    session = _FakeSession()
    assert _client(session).get("/schedule?date=2026-08-01").status_code == 200

    sql, _ = _compiled(session)
    assert "coalesce(appointments.scheduled_for, slots.start_at)" in sql
    # The same expression must drive filter AND sort, or a row is selected by
    # one time and ordered by another.
    assert sql.count("coalesce(appointments.scheduled_for, slots.start_at)") >= 3


def test_slots_is_outer_joined_so_no_row_is_dropped_by_it():
    """The slots join is back, and its shape is the whole point. An INNER join
    is what codex r1 removed: appointments.slot_id has no FK and book() writes
    any positive id, so an inner join silently drops an appointment with a stale
    slot. An OUTER join recovers the time without ever removing a row.
    """
    session = _FakeSession()
    assert _client(session).get("/schedule?date=2026-08-01").status_code == 200

    sql, _ = _compiled(session)
    assert "left outer join slots" in sql
    assert "left outer join patients" in sql


def test_sort_breaks_ties_on_id():
    """Appointment times collide heavily — the seed alone has five on one exact
    timestamp. Postgres gives no stable order for equal sort keys across
    separate queries, so an unbroken tie under LIMIT/OFFSET lets a paging caller
    see one row twice and another not at all.
    """
    session = _FakeSession()
    assert _client(session).get("/schedule?date=2026-08-01").status_code == 200

    sql, _ = _compiled(session)
    order_by = sql.split("order by", 1)[1]
    assert "appointments.id" in order_by


def test_rows_carry_the_joined_patient_identity_and_the_resolved_time():
    when = datetime(2026, 8, 1, 14, 0, tzinfo=timezone.utc)
    # scheduled_for is None on the appointment — the time comes from the slot,
    # exactly as it does for anything the booking UI wrote.
    session = _FakeSession([_row(_FakeAppointment(1, 1042), when=when)])

    body = _client(session).get("/schedule?date=2026-08-01").json()

    assert body["count"] == 1
    assert body["date"] == "2026-08-01"
    assert body["timezone"] == "America/New_York"
    assert body["items"][0]["patient_name"] == "Maria Gonzalez"
    assert body["items"][0]["mrn"] == "M4417"
    assert body["items"][0]["patient_id"] == 1042
    assert body["items"][0]["scheduled_for"] == "2026-08-01T14:00:00Z"


def test_one_query_for_the_whole_day_not_one_per_patient():
    """The reason the endpoint exists: no N+1 (D8)."""
    calls = []
    when = datetime(2026, 8, 1, 14, 0, tzinfo=timezone.utc)
    session = _FakeSession(
        [_row(_FakeAppointment(i, 1000 + i), f"P{i}", f"M{i}", when) for i in range(5)]
    )
    original = session.execute

    def _counting(stmt):
        calls.append(stmt)
        return original(stmt)

    session.execute = _counting
    body = _client(session).get("/schedule?date=2026-08-01").json()

    assert body["count"] == 5
    assert len(calls) == 1


def test_provider_id_does_not_filter_through_the_slot_join():
    """Regression for codex r1: the endpoint had a ``provider_id`` **filter**
    that inner-joined ``slots``, so an appointment with a missing or stale slot
    row showed in the all-day queue and silently disappeared from the
    per-provider one — a clinician missing a visit with no error. The filter is
    gone; the outer join above is a different thing and drops nothing.

    The parameter is passed here on purpose: asking for the day without it
    produces a predicate-free query under the old code too, so only the request
    that used to add the filter discriminates.
    """
    session = _FakeSession([_row(_FakeAppointment(1, 1042))])

    body = _client(session).get("/schedule?date=2026-08-01&provider_id=7").json()

    # Undeclared, so it is ignored and the full day comes back. The failure mode
    # being avoided is a filter that appears to work and quietly drops rows.
    assert body["count"] == 1

    sql, _ = _compiled(session)
    assert "slots.provider_id" not in sql
    assert "inner join slots" not in sql


# --------------------------------------------------------------------------- #
# paging: a truncated day must not look like a complete one
# --------------------------------------------------------------------------- #
def test_has_more_is_true_when_the_day_overflows_the_page():
    when = datetime(2026, 8, 1, 14, 0, tzinfo=timezone.utc)
    # The handler asks for limit+1 to detect the overflow; the extra row must be
    # reported, never rendered.
    session = _FakeSession([_row(_FakeAppointment(i, 1000 + i), when=when) for i in range(4)])

    body = _client(session).get("/schedule?date=2026-08-01&limit=3").json()

    assert body["has_more"] is True
    assert body["count"] == 3
    assert len(body["items"]) == 3


def test_has_more_is_false_on_a_complete_day():
    when = datetime(2026, 8, 1, 14, 0, tzinfo=timezone.utc)
    session = _FakeSession([_row(_FakeAppointment(i, 1000 + i), when=when) for i in range(3)])

    body = _client(session).get("/schedule?date=2026-08-01&limit=3").json()

    assert body["has_more"] is False
    assert body["count"] == 3


def test_the_query_asks_for_one_more_row_than_the_page():
    session = _FakeSession()
    assert _client(session).get("/schedule?date=2026-08-01&limit=25").status_code == 200

    _, params = _compiled(session)
    assert 26 in params.values()


def test_date_is_required():
    assert _client(_FakeSession()).get("/schedule").status_code == 422


def test_bad_date_is_rejected_at_the_boundary():
    assert _client(_FakeSession()).get("/schedule?date=not-a-date").status_code == 422


def test_out_of_range_date_is_422_not_a_crash():
    """``date`` accepts up to 9999-12-31 and the window's end edge is day + 1, so
    an unguarded handler raises OverflowError — a 500 with a plaintext body,
    which the gateway's checked GET then reports as "returned a bad response".
    An unparseable request would be diagnosed as a transport fault.
    """
    resp = _client(_FakeSession()).get("/schedule?date=9999-12-31")

    assert resp.status_code == 422
    assert resp.json()["detail"] == "date is outside the supported range"


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
_PHI = ("Maria", "Gonzalez", "M4417", "1974-03-02", "402-11-4412", "1042")

_PHI_ROWS = [
    _row(
        _FakeAppointment(
            1,
            1042,
            reason="Maria Gonzalez DOB 1974-03-02 SSN 402-11-4412",
        ),
        name="Maria Gonzalez",
        mrn="M4417",
        when=datetime(2026, 8, 1, 14, 0, tzinfo=timezone.utc),
    )
]


def test_log_line_carries_no_patient_phi(caplog):
    """Adversarial: PHI is placed in every field the handler touches, including
    the free-text reason, and the log is scanned for all of it.

    ``caplog.text``, not ``record.getMessage()``. getMessage() renders
    ``msg % args`` and nothing else, so it cannot see anything arriving through
    an exception — which is precisely where the failure-path test below needs to
    look. Using the same accessor in both keeps one of them from silently
    testing less than it claims.
    """
    session = _FakeSession(_PHI_ROWS)

    with caplog.at_level(logging.INFO):
        assert _client(session).get("/schedule?date=2026-08-01").status_code == 200

    for phi in _PHI:
        assert phi not in caplog.text, f"{phi!r} reached the log"
    assert "2026-08-01" in caplog.text  # the window itself is not PHI


def test_database_failure_log_carries_no_phi(caplog):
    """The failure path logs too, and ``log.exception`` renders the traceback —
    whose frames, and whose exception message, can carry the values in flight.

    Two things this test needs that are easy to get wrong, and were wrong in the
    first cut: the scenario must actually CONTAIN PHI (a session that raises
    before returning rows has none, so every assertion holds vacuously against
    any implementation, including one that logs the whole result set), and the
    scan must read ``caplog.text``, which includes the rendered exception, not
    ``getMessage()``, which does not. Here the PHI is planted where the handler
    least expects it — inside the database driver's own error string.
    """
    session = _FakeSession(
        _PHI_ROWS,
        raises=RuntimeError(
            "connection refused while binding patient Maria Gonzalez "
            "mrn=M4417 dob=1974-03-02 ssn=402-11-4412 id=1042"
        ),
    )

    with caplog.at_level(logging.DEBUG):
        assert _client(session).get("/schedule?date=2026-08-01").status_code == 503

    for phi in _PHI:
        assert phi not in caplog.text, f"{phi!r} reached the log"
    assert "2026-08-01" in caplog.text


# --------------------------------------------------------------------------- #
# configuration: an unresolvable zone must not be a per-request failure
# --------------------------------------------------------------------------- #
def test_import_fails_when_the_configured_zone_is_unresolvable(monkeypatch):
    """Boot-time, not request-time. Deferred, a typo'd CLINIC_TIMEZONE raises
    ZoneInfoNotFoundError out of every /schedule call and surfaces at the
    gateway as a transport-shaped 502, while /healthz — which does no timezone
    work — keeps answering 200. That is the green-dashboard/dead-service shape;
    a misconfigured deploy should refuse to start instead.
    """
    # NOT a case typo: ZoneInfo resolves "America/New_york" on a case-insensitive
    # filesystem (macOS) and raises on Linux, so that input would make this test
    # pass in CI and fail on a developer's machine.
    monkeypatch.setenv("CLINIC_TIMEZONE", "Riverbend/Main_Clinic")

    with pytest.raises(RuntimeError) as excinfo:
        load_module("services/scheduling-service/config.py", "sched_config_badzone")

    assert "CLINIC_TIMEZONE" in str(excinfo.value)


def test_the_shipped_default_zone_resolves():
    """Guards the guard: a validator that rejected the default would fail every
    container, and the test above would still pass."""
    config_mod._validate_clinic_timezone(config_mod.settings.clinic_timezone)
    assert config_mod.settings.clinic_timezone == "America/New_York"
