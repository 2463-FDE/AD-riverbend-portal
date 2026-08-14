"""
Adversarial PHI test for the intake DB-write failure path (app.py).

phi-logging-policy register (PR #33): the intake write helpers logged str(e) on
SQLAlchemyError, and a statement-level DBAPIError stringifies with
``[SQL: ...] [parameters: (...)]`` — the full bound row — unless the engine
set hide_parameters=True (before this fix, none did). So a DataError on the
patients INSERT (e.g. an oversized field) wrote name/DOB/SSN into the intake
log at ERROR. This test plants PHI literals in a simulated statement-level failure
exactly as SQLAlchemy embeds them and asserts none survive into any log record
or the raised HTTP error. It FAILS against the pre-fix code, which logged
str(e). Same shape as tests/test_intake_eligibility_phi.py (the 2026-07-08
fix this one mirrors) and the landmines §3 negative-test rule.

The three writes are now one transaction in ``_create_registration``
(E4-SPEC-4), so the three failure points are exercised through that one helper:
the patients INSERT fails at the explicit ``flush()``, the coverage and consent
INSERTs at the single ``commit()``. The consent case additionally proves the
inherited swallow is gone — that failure is now a 503, not a silent partial
registration.
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

# The now-required submission_id (e5b-SPEC-4). A valid v4 so construction reaches
# the write path under test, not a boundary rejection; not itself PHI.
SUBMISSION_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"


NEW_ID = 4242


class _FailingSession:
    """Session double whose flush or commit raises the statement-level error an
    un-hidden engine produces: DBAPIError.__str__ appends
    ``[SQL: ...] [parameters: (...)]`` with every bound value.

    ``fail_on`` picks which of the two the registration transaction dies in:
    ``flush`` is the patients INSERT (the PK assignment), ``commit`` is the
    coverage and consent INSERTs, which are only sent when the one transaction
    commits.
    """

    def __init__(
        self,
        statement: str,
        params: tuple,
        orig_message: str | None = None,
        fail_on: str = "commit",
    ):
        self._exc = DataError(
            statement,
            params,
            Exception(orig_message or "value too long for type character varying(11)"),
        )
        self._fail_on = fail_on
        self.added = []
        self.rollbacks = 0

    def add(self, obj):
        self.added.append(obj)

    def get_bind(self):
        # _create_registration checks the dialect to gate the Postgres-only
        # SET lock_timeout (e5b-D-12); this stub is a non-Postgres bind, so the
        # SET is skipped and the write path under test is unchanged.
        class _Bind:
            class dialect:
                name = "sqlite"

        return _Bind()

    def flush(self):
        if self._fail_on == "flush":
            raise self._exc
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = NEW_ID

    def commit(self):
        if self._fail_on == "commit":
            raise self._exc

    def rollback(self):
        self.rollbacks += 1


def _assert_no_phi(caplog, exc_info):
    # Guard against a vacuous pass: the PHI scan below iterates caplog.records,
    # so if intake's logger ever stops propagating to root (e.g. a future
    # `propagate = False` in logging_config), zero records would make every
    # assertion skip silently. The error path must have logged something.
    assert any(r.levelno >= logging.ERROR for r in caplog.records)
    detail = str(exc_info.value.detail)
    for value in PHI:
        assert value not in detail
        for record in caplog.records:
            assert value not in record.getMessage()


def _request(**kwargs):
    payload = {
        "submission_id": SUBMISSION_ID,
        "demographics": {"name": NAME, "dob": DOB, "ssn": SSN},
        "consents": ["npp_ack"],
    }
    payload.update(kwargs)
    return schemas_mod.IntakeRequest(**payload)


def test_patient_insert_failure_does_not_leak_row(caplog):
    db = _FailingSession(
        "INSERT INTO patients (name, dob, ssn) VALUES (%s, %s, %s)",
        (NAME, DOB, SSN),
        fail_on="flush",
    )
    with caplog.at_level(logging.ERROR):
        with pytest.raises(app_mod.HTTPException) as exc_info:
            app_mod._create_registration(db, _request(), "deadbeeffingerprint")
    assert exc_info.value.status_code == 503
    _assert_no_phi(caplog, exc_info)


def test_coverage_insert_failure_does_not_leak_member_id(caplog):
    db = _FailingSession(
        "INSERT INTO insurance_coverages (patient_id, member_id, group_number) "
        "VALUES (%s, %s, %s)",
        (1, MEMBER_ID, GROUP),
    )
    with caplog.at_level(logging.ERROR):
        with pytest.raises(app_mod.HTTPException) as exc_info:
            app_mod._create_registration(
                db,
                _request(insurance={"member_id": MEMBER_ID, "group_number": GROUP}),
                "deadbeeffingerprint",
            )
    assert exc_info.value.status_code == 503
    _assert_no_phi(caplog, exc_info)


def test_consent_insert_failure_logs_class_only(caplog):
    """The consent kind and patient_id were allowlisted in the old per-consent
    log line; what must never appear is any part of str(e) — proven with a
    sentinel planted in the driver's own message, which is where a real
    DBAPIError carries free text."""
    sentinel = "DRIVER-MSG-SENTINEL-9988"
    db = _FailingSession(
        "INSERT INTO consents (patient_id, kind) VALUES (%s, %s)",
        (1, "npp_ack"),
        orig_message=f"insert failed: {sentinel}",
    )
    with caplog.at_level(logging.ERROR):
        with pytest.raises(app_mod.HTTPException):
            app_mod._create_registration(db, _request(), "deadbeeffingerprint")
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "consent failure must log an ERROR record"
    for msg in errors:
        assert sentinel not in msg
        assert "[SQL" not in msg and "[parameters" not in msg
        assert "DataError" in msg  # the class name is the diagnostic that remains


def test_consent_insert_failure_is_no_longer_swallowed(caplog):
    """E4-SPEC-4. The consent write used to catch its own SQLAlchemyError and
    return, so a failure there left a committed patient with no consent rows
    and a 201 at the desk. The single transaction rolls back and the caller
    gets a 503 instead — nothing survives a failed registration."""
    db = _FailingSession(
        "INSERT INTO consents (patient_id, kind) VALUES (%s, %s)",
        (1, "npp_ack"),
    )
    with caplog.at_level(logging.ERROR):
        with pytest.raises(app_mod.HTTPException) as exc_info:
            app_mod._create_registration(db, _request(), "deadbeeffingerprint")
    assert exc_info.value.status_code == 503
    assert db.rollbacks == 1
