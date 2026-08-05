"""
Adversarial PHI test for the ROI create failure path (app.py).

Codex review r1 on PR #34: create_roi_request writes open string fields
(requested_by, recipient, purpose) and the pre-fix handler used log.exception
on SQLAlchemyError. hide_parameters=True only suppresses SQLAlchemy's
``[SQL: ...] [parameters: (...)]`` rendering; the driver's own message
(``DETAIL: Failing row contains (...)``) passes through, so an insert failure
put ROI recipient/purpose into the log via the traceback. This test raises a
statement-level DataError carrying sentinel values in both the SQLAlchemy
rendering and the driver message and asserts none survive into any log record
— including exc_info-formatted traceback text — or the HTTP error. FAILS
pre-fix (landmines §3 negative-test rule).

Log-line-only fix; no ROI/disclosure logic touched (approval 2026-08-05).
"""
import logging
import sys

import pytest
from sqlalchemy.exc import DataError

from conftest import load_module

_SIBLINGS = ("config", "db", "logging_config", "models", "schemas")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/roi-service/config.py", "roi_config_dberr")
sys.modules["db"] = load_module("services/roi-service/db.py", "roi_db_dberr")
sys.modules["logging_config"] = load_module(
    "services/roi-service/logging_config.py", "roi_logging_config_dberr"
)
sys.modules["models"] = load_module("services/roi-service/models.py", "roi_models_dberr")
sys.modules["schemas"] = load_module("services/roi-service/schemas.py", "roi_schemas_dberr")
app_mod = load_module("services/roi-service/app.py", "roi_app_dberr")
schemas_mod = sys.modules["schemas"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


RECIPIENT = "Atty. Sandra Voss, Voss & Klein LLP RECIPIENT-SENTINEL-8812"
PURPOSE = "records for HIV disability claim PURPOSE-SENTINEL-3307"
REQUESTED_BY = "patient spouse Jordan Ellis"


class _Patient:
    id = 1


class _FailingSession:
    """Session double whose commit raises the statement-level error a real
    insert failure produces: SQLAlchemy rendering AND a driver message that
    embeds the failing row."""

    def __init__(self):
        self._exc = DataError(
            "INSERT INTO roi_requests (patient_id, requested_by, recipient, purpose) "
            "VALUES (%s, %s, %s, %s)",
            (1, REQUESTED_BY, RECIPIENT, PURPOSE),
            Exception(
                f"DETAIL:  Failing row contains (9, 1, {REQUESTED_BY}, {RECIPIENT}, "
                f"attorney, {PURPOSE}, null, null, pending)."
            ),
        )

    def get(self, model, pk):
        return _Patient()

    def add(self, obj):
        pass

    def commit(self):
        raise self._exc

    def rollback(self):
        pass


def _formatted(record):
    # log.exception leaks via the traceback, not getMessage() — format the
    # record the way a real handler would so exc_info text is scanned too.
    return logging.Formatter().format(record)


def test_roi_create_failure_does_not_leak_request_fields(caplog):
    payload = schemas_mod.RoiRequestCreate(
        patient_id=1,
        requested_by=REQUESTED_BY,
        recipient=RECIPIENT,
        recipient_type="attorney",
        purpose=PURPOSE,
    )

    with caplog.at_level(logging.ERROR):
        with pytest.raises(app_mod.HTTPException) as exc_info:
            app_mod.create_roi_request(payload, db=_FailingSession())

    assert exc_info.value.status_code == 503
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "ROI create failure must log an ERROR record"
    detail = str(exc_info.value.detail)
    for leak in (RECIPIENT, PURPOSE, REQUESTED_BY, "Failing row", "[SQL", "[parameters"):
        assert leak not in detail
        for record in errors:
            assert leak not in _formatted(record)
    assert any("DataError" in _formatted(r) for r in errors)
