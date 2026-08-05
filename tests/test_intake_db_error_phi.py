"""
Adversarial PHI test for the intake DB-write failure paths (app.py).

phi-logging-policy register (PR #33): _create_patient / _create_coverage log
str(e) on SQLAlchemyError, and a statement-level DBAPIError stringifies with
``[SQL: ...] [parameters: (...)]`` — the full bound row — unless the engine
sets hide_parameters=True (db.py does not). So a DataError on the patients
INSERT (e.g. an oversized field) would write name/DOB/SSN into the intake log
at ERROR. This test plants PHI literals in a simulated statement-level failure
exactly as SQLAlchemy embeds them and asserts none survive into any log record
or the raised HTTP error. It FAILS against the pre-fix code, which logged
str(e). Same shape as tests/test_intake_eligibility_phi.py (the 2026-07-08
fix this one mirrors) and the landmines §3 negative-test rule.
"""
import logging
import sys

import pytest
from sqlalchemy.exc import DataError

from conftest import load_module

# intake-service has its own config/db/logging_config/models/schemas; load_module
# puts each service dir on sys.path, so bare sibling names are ambiguous across
# services by the time this loads. Pin intake's copies while app.py imports, then
# restore (same technique as test_intake_eligibility_phi.py).
_SIBLINGS = ("config", "db", "logging_config", "models", "schemas", "breaker")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/intake-service/config.py", "intake_config_dberr")
sys.modules["db"] = load_module("services/intake-service/db.py", "intake_db_dberr")
sys.modules["logging_config"] = load_module(
    "services/intake-service/logging_config.py", "intake_logging_config_dberr"
)
sys.modules["models"] = load_module("services/intake-service/models.py", "intake_models_dberr")
sys.modules["schemas"] = load_module("services/intake-service/schemas.py", "intake_schemas_dberr")
sys.modules["breaker"] = load_module("services/intake-service/breaker.py", "intake_breaker_dberr")
app_mod = load_module("services/intake-service/app.py", "intake_app_dberr")
schemas_mod = sys.modules["schemas"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


NAME = "Adversarial Q Testpatient"
DOB = "1990-01-31"
SSN = "123-45-6789"
MEMBER_ID = "BCBS4471"
GROUP = "GRP-77812"
PHI = (NAME, DOB, SSN, MEMBER_ID, GROUP)


class _FailingSession:
    """Session double whose commit raises the statement-level error an
    un-hidden engine produces: DBAPIError.__str__ appends
    ``[SQL: ...] [parameters: (...)]`` with every bound value."""

    def __init__(self, statement: str, params: tuple):
        self._exc = DataError(
            statement,
            params,
            Exception("value too long for type character varying(11)"),
        )

    def add(self, obj):
        pass

    def commit(self):
        raise self._exc

    def rollback(self):
        pass


def _assert_no_phi(caplog, exc_info):
    detail = str(exc_info.value.detail)
    for value in PHI:
        assert value not in detail
        for record in caplog.records:
            assert value not in record.getMessage()


def test_patient_insert_failure_does_not_leak_row(caplog):
    demo = schemas_mod.Demographics(name=NAME, dob=DOB, ssn=SSN)
    db = _FailingSession(
        "INSERT INTO patients (name, dob, ssn) VALUES (%s, %s, %s)",
        (NAME, DOB, SSN),
    )
    with caplog.at_level(logging.ERROR):
        with pytest.raises(app_mod.HTTPException) as exc_info:
            app_mod._create_patient(db, demo)
    assert exc_info.value.status_code == 503
    _assert_no_phi(caplog, exc_info)


def test_coverage_insert_failure_does_not_leak_member_id(caplog):
    ins = schemas_mod.Insurance(member_id=MEMBER_ID, group_number=GROUP)
    db = _FailingSession(
        "INSERT INTO insurance_coverages (patient_id, member_id, group_number) "
        "VALUES (%s, %s, %s)",
        (1, MEMBER_ID, GROUP),
    )
    with caplog.at_level(logging.ERROR):
        with pytest.raises(app_mod.HTTPException) as exc_info:
            app_mod._create_coverage(db, 1, ins)
    assert exc_info.value.status_code == 503
    _assert_no_phi(caplog, exc_info)
