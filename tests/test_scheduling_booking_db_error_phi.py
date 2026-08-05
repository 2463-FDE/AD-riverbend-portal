"""
Adversarial PHI test for the scheduling booking failure path (app.py).

Codex review r1 on PR #34: create_appointment delegates to book(), which is raw
psycopg2 — the engine-level hide_parameters backstop never sees it — and the
pre-fix handler used log.exception, so the driver's message (which can embed
the bound row via ``DETAIL: Failing row contains (...)``) landed in the log via
the traceback. BookingRequest.reason is open free text (a clerk types why the
patient is coming in), so that row detail is PHI. This test raises a simulated
driver error carrying sentinel row text and asserts none of it survives into
any log record — including the exc_info-formatted traceback, which is where
log.exception put it — or the raised HTTP error. FAILS pre-fix (landmines §3
negative-test rule).
"""
import logging
import sys

import pytest
from sqlalchemy.exc import DataError

from conftest import load_module

# Pin scheduling's sibling modules while app.py imports, then restore (same
# technique as tests/test_intake_db_error_phi.py).
_SIBLINGS = ("config", "db", "logging_config", "models", "schemas", "book")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/scheduling-service/config.py", "sched_config_dberr")
sys.modules["db"] = load_module("services/scheduling-service/db.py", "sched_db_dberr")
sys.modules["logging_config"] = load_module(
    "services/scheduling-service/logging_config.py", "sched_logging_config_dberr"
)
sys.modules["models"] = load_module("services/scheduling-service/models.py", "sched_models_dberr")
sys.modules["schemas"] = load_module("services/scheduling-service/schemas.py", "sched_schemas_dberr")
sys.modules["book"] = load_module("services/scheduling-service/book.py", "sched_book_dberr")
app_mod = load_module("services/scheduling-service/app.py", "sched_app_dberr")
schemas_mod = sys.modules["schemas"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


REASON = "follow-up for HIV medication adjustment REASON-SENTINEL-4471"
PROVIDER = "Dr. Nguyen"


class FakeCheckViolation(Exception):
    """Stands in for a psycopg2 driver error: the handler catches bare
    Exception, and what matters is the message shape — Postgres embeds the
    whole bound row in DETAIL for entire error classes."""


def _formatted(record):
    # log.exception leaks via the traceback, not getMessage() — format the
    # record the way a real handler would so exc_info text is scanned too.
    return logging.Formatter().format(record)


def test_booking_failure_does_not_leak_driver_row(caplog, monkeypatch):
    def _failing_book(*args, **kwargs):
        raise FakeCheckViolation(
            'new row for relation "appointments" violates check constraint '
            '"appointments_status_check"\n'
            f"DETAIL:  Failing row contains (12, 7, {PROVIDER}, {REASON}, "
            "Clinic A, null, confirmed)."
        )

    monkeypatch.setattr(app_mod, "book", _failing_book)
    req = schemas_mod.BookingRequest(patient_id=12, slot_id=7, reason=REASON)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(app_mod.HTTPException) as exc_info:
            app_mod.create_appointment(req)

    assert exc_info.value.status_code == 503
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "booking failure must log an ERROR record"
    detail = str(exc_info.value.detail)
    for leak in (REASON, "REASON-SENTINEL-4471", PROVIDER, "Failing row"):
        assert leak not in detail
        for record in errors:
            assert leak not in _formatted(record)
    # the class name is the diagnostic that remains
    assert any("FakeCheckViolation" in _formatted(r) for r in errors)


CANCEL_SENTINEL = "CANCEL-DRIVER-SENTINEL-5520"


class _FailingGetSession:
    """Session double whose get() raises a statement-level error. Pre-fix,
    cancel_appointment ran db.get OUTSIDE its try block (diff-reviewer r1 on
    PR #34), so this propagated unhandled: a 500 with the driver's message in
    the ASGI traceback instead of a 503 with a class-only log line."""

    def __init__(self):
        self._exc = DataError(
            "SELECT appointments.id FROM appointments WHERE appointments.id = %s",
            (7,),
            Exception(f"connection lost: {CANCEL_SENTINEL}"),
        )

    def get(self, model, pk):
        raise self._exc

    def rollback(self):
        pass


def test_cancel_lookup_failure_is_handled_and_leak_free(caplog):
    with caplog.at_level(logging.ERROR):
        with pytest.raises(app_mod.HTTPException) as exc_info:
            app_mod.cancel_appointment(7, db=_FailingGetSession())

    assert exc_info.value.status_code == 503
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "cancel lookup failure must log an ERROR record"
    detail = str(exc_info.value.detail)
    for leak in (CANCEL_SENTINEL, "[SQL", "[parameters"):
        assert leak not in detail
        for record in errors:
            assert leak not in _formatted(record)
    assert any("DataError" in _formatted(r) for r in errors)
