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
def _compiled(session):
    compiled = session.stmt.compile()
    return str(compiled).lower(), compiled.params


def _branches(sql):
    """The two UNION ALL halves of the compiled statement (ADR 0018).

    The subquery is inlined into FROM, so everything before the UNION ALL is
    the outer select plus the scheduled-for branch, and everything after it
    opens with the slot branch. That containment is exactly what the callers
    assert against, so the split is the right tool despite being textual.
    """
    assert "union all" in sql, f"day query is not the two-branch shape: {sql}"
    scheduled, from_slot = sql.split("union all", 1)
    return scheduled, from_slot


def _bound_to(fragment, column, operator):
    """The bind parameter name ``column`` is compared to by ``operator``.
    Resolved from the SQL rather than hardcoded, because SQLAlchemy names
    anonymous binds after the column they belong to and those names shift when
    the expression does."""
    m = re.search(re.escape(column) + r"\s*" + re.escape(operator) + r"\s*:(\w+)", fragment)
    assert m, f"no {operator!r} comparison against {column} in: {fragment}"
    return m.group(1)


def test_the_window_bounds_each_side_of_the_right_operator():
    """Wiring proof, per branch. The weaker version of this test asserted only
    that both datetimes appeared *somewhere* in the bind parameters, which is
    satisfied by a statement that swaps them (``>= end AND < start``) and
    returns zero rows for every day, forever. So the assertion is on which
    value sits on which side of which comparison, in **each** UNION ALL branch
    — a branch with a swapped or missing bound silently loses only the rows
    that take that branch — and on the interval being half-open.
    """
    session = _FakeSession()
    assert _client(session).get("/schedule?date=2026-08-01").status_code == 200

    sql, params = _compiled(session)
    scheduled, from_slot = _branches(sql)
    start = datetime(2026, 8, 1, 4, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 2, 4, 0, tzinfo=timezone.utc)

    assert params[_bound_to(scheduled, "appointments.scheduled_for", ">=")] == start
    assert params[_bound_to(scheduled, "appointments.scheduled_for", "<")] == end
    assert params[_bound_to(from_slot, "slots.start_at", ">=")] == start
    assert params[_bound_to(from_slot, "slots.start_at", "<")] == end
    # Half-open everywhere: an inclusive upper edge would put the next day's
    # midnight appointment in both days' queues.
    assert "<=" not in sql


def test_the_visit_time_falls_back_to_the_slot_start():
    """The defect this closes: ``appointments.scheduled_for`` is nullable with no
    default and the write path never sets it — the booking UI posts only
    {patient_id, slot_id, provider, reason} (frontend/app/appointments/page.tsx:62)
    and insert_appointment writes the NULL. ``NULL >= x`` is NULL in SQL, so
    filtering on that column alone returns nothing but seeded rows: a day queue
    that looks right in dev and is empty in production.

    Since ADR 0018 the fallback is the UNION ALL's second branch: it selects
    the slot's start_at as the visit time and joins slots to get it. Asserted
    on the compiled statement because the filter runs in Postgres, not in
    Python — the fake session cannot evaluate a predicate.
    """
    session = _FakeSession()
    assert _client(session).get("/schedule?date=2026-08-01").status_code == 200

    sql, _ = _compiled(session)
    _, from_slot = _branches(sql)
    assert "slots.start_at as visit_at" in from_slot
    assert "join slots" in from_slot
    # Membership in a branch is what selects the row; the same subquery column
    # must carry the time out to the sort and the response, or a row is
    # selected by one time and ordered/rendered by another.
    assert "day.appointment_id = appointments.id" in sql
    assert "day.visit_at" in sql


def test_the_branches_are_disjoint_so_no_row_pages_twice():
    """The slot branch admits only rows with no ``scheduled_for`` of their own.
    Without that guard an appointment with both times inside the window comes
    back from both branches — the same visit rendered twice, and under
    LIMIT/OFFSET a duplicate that pushes a real row off the page entirely.
    """
    session = _FakeSession()
    assert _client(session).get("/schedule?date=2026-08-01").status_code == 200

    sql, _ = _compiled(session)
    _, from_slot = _branches(sql)
    assert "appointments.scheduled_for is null" in from_slot


def test_membership_join_is_inner_so_the_day_bounds_the_result():
    """The subquery decides membership only if the join back to appointments is
    INNER. Outer-joined, every non-cancelled appointment in the table comes
    back with a NULL visit time — sorted last, so page one still looks right
    and the leak surfaces on deep pages: a whole-table cross-patient export
    from the endpoint whose scope argument is "one clinic day". This is the
    single join type in the statement the other tests cannot see (the pre-push
    pass proved the isouter mutation survived all of them).
    """
    session = _FakeSession()
    assert _client(session).get("/schedule?date=2026-08-01").status_code == 200

    sql, _ = _compiled(session)
    assert "from appointments join (select" in sql
    assert "left outer join (select" not in sql


def test_a_stale_slot_cannot_drop_a_row_with_its_own_time():
    """Codex r1's silent-drop invariant, restated for the two-branch shape.
    ``appointments.slot_id`` has no FK and book() writes any positive id, so a
    row must never lose its place in the queue to slot state it does not need:
    the scheduled-for branch touches ``slots`` not at all. The slot branch's
    inner join is the predicate itself — a row it drops is one whose visit time
    does not exist, which the old outer-join-plus-COALESCE excluded
    identically. ``patients`` stays an outer join: an orphaned patient_id
    blanks the name, never hides the visit.
    """
    session = _FakeSession()
    assert _client(session).get("/schedule?date=2026-08-01").status_code == 200

    sql, _ = _compiled(session)
    scheduled, _ = _branches(sql)
    assert "slots" not in scheduled
    assert "left outer join patients" in sql


def test_cancelled_visits_are_excluded_from_the_queue():
    """FE-R34. A cancelled visit is not someone coming to the clinic today, so
    leaving it in means the front desk checks in a patient who cancelled — and
    means name, MRN and reason are rendered for a visit that should no longer be
    active (codex r2).

    Asserted on the compiled statement, like the window: the predicate runs in
    Postgres and the fake session cannot evaluate one.

    This one pins the `!=` form on purpose, so it is the test that fails if the
    predicate is rewritten as an equivalent `notin_` — update this line, it is not
    a defect. The form-independent invariant is the next test's job.
    """
    session = _FakeSession()
    assert _client(session).get("/schedule?date=2026-08-01").status_code == 200

    sql, params = _compiled(session)

    binds = re.findall(r"appointments\.status\s*!=\s*:(\w+)", sql)
    assert binds, f"no status exclusion against the day query in: {sql}"
    # Exactly one site, on the outer query — a copy per UNION ALL branch is two
    # predicates that can drift apart, which is the r2 spelling-drift failure
    # reintroduced inside a single statement. Outer means after the subquery
    # CLOSES, not merely after the union all — anchoring on "union all" alone
    # passes when the single copy sits inside the slot branch, filtering only
    # the rows that take that branch (the pre-push pass caught exactly that).
    assert len(binds) == 1, sql
    assert sql.index(") as day") < re.search(r"appointments\.status\s*!=", sql).start(), sql
    # Both, and they are different assertions. The literal pins the value against
    # the rows already in the database — which no constant rename migrates. The
    # constant pins the reader to the writer, and without it the two halves are
    # coupled only by the same string being typed into two files.
    assert params[binds[0]] == "cancelled"
    assert params[binds[0]] == app_mod.CANCELLED_STATUS


def test_no_status_but_the_cancelled_one_constrains_the_day_query():
    """FE-R34's second clause: no visit is omitted for having a status the query
    does not recognise.

    Asserted on the bind VALUES rather than on the compiled SQL's syntax, and the
    difference matters. A syntax assertion (`"status in (" not in where`) pins the
    operator SQLAlchemy happens to emit, so it fails an equivalent refactor —
    `status.notin_([CANCELLED_STATUS])` and `not_(status == CANCELLED_STATUS)` are
    the same query here, `status` being NOT NULL — while still passing anything
    that constrains status some other way. The invariant is about which status
    values the query is allowed to know about, and that is what this reads.

    It fails in both wrong directions: an allowlist binds 'confirmed'/'completed'
    and the set no longer equals {cancelled}; dropping the predicate empties it.
    """
    session = _FakeSession()
    assert _client(session).get("/schedule?date=2026-08-01").status_code == 200

    _, params = _compiled(session)

    # Every status value this codebase's writers produce (book.py, the cancel
    # route, the seed generator), plus the ones the endpoint's comment names as
    # plausible later additions and the spelling the legacy UI defends against.
    known_statuses = {
        "confirmed",
        "completed",
        "cancelled",
        "canceled",
        "checked_in",
        "arrived",
        "no_show",
    }
    # Flattened, because an IN/NOT IN predicate binds its values as one list
    # parameter rather than as separate scalars — reading only the scalars would
    # make this test silently blind to exactly the allowlist it exists to reject.
    bound = []
    for value in params.values():
        bound.extend(value if isinstance(value, (list, tuple)) else [value])
    bound_statuses = {v for v in bound if isinstance(v, str) and v in known_statuses}

    assert bound_statuses == {app_mod.CANCELLED_STATUS}, bound_statuses


def test_the_excluded_status_is_the_literal_the_cancel_path_writes():
    """Drift proof. The exclusion is only correct while the value the cancel path
    STORES equals the value the day query EXCLUDES — a cancel that wrote
    'canceled' (the spelling the legacy UI defends against,
    frontend/app/appointments/page.tsx:96) would silently put the visit back in
    the front-desk queue with no error anywhere.

    What this pins is those two values matching, not that the writer imports the
    constant — an equal literal is equally correct and this test cannot, and need
    not, tell them apart. Mutation-proven by changing the stored spelling.
    """

    class _FakeCancelSession:
        def __init__(self, appointment):
            self.appointment = appointment
            self.committed = False

        def get(self, _model, _pk):
            return self.appointment

        def commit(self):
            self.committed = True

    appointment = _FakeAppointment(1, 1042)
    session = _FakeCancelSession(appointment)

    body = _client(session).post("/appointments/1/cancel").json()

    assert appointment.status == app_mod.CANCELLED_STATUS
    assert body["status"] == app_mod.CANCELLED_STATUS
    assert session.committed


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
    # The visit time leads and comes from the same subquery column that
    # selected the row; the id breaks the tie.
    assert order_by.strip().startswith("day.visit_at")
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
    gone; the slot branch's join recovers a time and drops nothing a COALESCE
    kept (see test_a_stale_slot_cannot_drop_a_row_with_its_own_time).

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
    assert "providers" not in sql


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
