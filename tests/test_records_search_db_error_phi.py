"""
Adversarial PHI test for the records search failure path (app.py).

Class sweep of Codex review r1 on PR #34: search_records binds the caller's
free-text query — in practice a typed patient name, a rule-2 never-loggable
value — into an ILIKE pattern, and the pre-fix handler used log.exception on
SQLAlchemyError, so a statement-level failure put the query into the log via
the traceback (SQLAlchemy's ``[parameters: (...)]`` rendering and/or the
driver's own message). This test raises a DataError carrying a sentinel query
in both places and asserts none of it survives into any log record — including
exc_info-formatted traceback text — or the HTTP error. FAILS pre-fix
(landmines §3 negative-test rule).
"""
import logging
import sys

import pytest
from sqlalchemy.exc import DataError

from conftest import load_module

_SIBLINGS = ("config", "db", "logging_config", "models", "schemas")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/records-service/config.py", "records_config_dberr")
sys.modules["db"] = load_module("services/records-service/db.py", "records_db_dberr")
sys.modules["logging_config"] = load_module(
    "services/records-service/logging_config.py", "records_logging_config_dberr"
)
sys.modules["models"] = load_module("services/records-service/models.py", "records_models_dberr")
sys.modules["schemas"] = load_module("services/records-service/schemas.py", "records_schemas_dberr")
app_mod = load_module("services/records-service/app.py", "records_app_dberr")
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


QUERY = "Quentin Sentinelson SEARCHQ-9931"


class _FailingSession:
    """Session double whose execute raises the statement-level error an
    un-hidden engine produces, with the bound query in both the SQLAlchemy
    rendering and the driver message."""

    def __init__(self):
        self._exc = DataError(
            "SELECT records.id FROM records WHERE records.body ILIKE %s",
            (f"%{QUERY}%",),
            Exception(f'invalid input syntax for type tsquery: "{QUERY}"'),
        )

    def execute(self, stmt):
        raise self._exc


def _formatted(record):
    # log.exception leaks via the traceback, not getMessage() — format the
    # record the way a real handler would so exc_info text is scanned too.
    return logging.Formatter().format(record)


def test_search_failure_does_not_leak_query(caplog):
    with caplog.at_level(logging.ERROR):
        with pytest.raises(app_mod.HTTPException) as exc_info:
            app_mod.search_records(q=QUERY, db=_FailingSession())

    assert exc_info.value.status_code == 503
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "search failure must log an ERROR record"
    detail = str(exc_info.value.detail)
    for leak in (QUERY, "Sentinelson", "SEARCHQ-9931", "[SQL", "[parameters"):
        assert leak not in detail
        for record in errors:
            assert leak not in _formatted(record)
    assert any("DataError" in _formatted(r) for r in errors)
