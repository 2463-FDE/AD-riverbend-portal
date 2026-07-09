"""Validation tests for the multi-step intake payload (intake-service/schemas.py)."""
import json

from conftest import load_module
import pytest
from pydantic import ValidationError

schemas = load_module("services/intake-service/schemas.py", "intake_schemas")


def test_minimal_valid_intake():
    req = schemas.IntakeRequest(demographics={"name": "Jane Roe"})
    assert req.demographics.name == "Jane Roe"
    assert req.demographics.created_via == "self_service"
    # default consents applied
    assert req.consents == ["npp_ack", "treatment_consent"]


def test_full_intake_with_insurance():
    req = schemas.IntakeRequest(
        demographics={"name": "John Doe", "dob": "1980-01-01", "ssn": "111-22-3333"},
        insurance={"payer_name": "Aetna", "member_id": "AET123", "plan_type": "PPO"},
        consents=["npp_ack"],
    )
    assert req.insurance.payer_name == "Aetna"
    assert req.consents == ["npp_ack"]


def test_blank_name_rejected():
    with pytest.raises(ValidationError):
        schemas.IntakeRequest(demographics={"name": "   "})


def test_missing_demographics_rejected():
    with pytest.raises(ValidationError):
        schemas.IntakeRequest(consents=["npp_ack"])


# --- consents is a closed enum: PHI can't be smuggled through it (Codex review) --
# Regression for D1: consents used to be an open list[str], so a name/DOB placed
# in it survived into the intake log (pattern redaction only scrubs SSN/email/
# phone). It is now a ConsentKind enum, rejected at the boundary. These tests
# FAIL against the pre-fix list[str] schema (which accepts any string).


def test_consents_reject_free_text_phi():
    with pytest.raises(ValidationError):
        schemas.IntakeRequest(
            demographics={"name": "Jane Roe"},
            consents=["npp_ack", "Jane Doe DOB 1985-03-12"],
        )


def test_consents_reject_unknown_identifier():
    with pytest.raises(ValidationError):
        schemas.IntakeRequest(
            demographics={"name": "Jane Roe"},
            consents=["not_a_real_consent"],
        )


def test_all_known_consent_kinds_accepted():
    req = schemas.IntakeRequest(
        demographics={"name": "Jane Roe"},
        consents=["npp_ack", "treatment_consent", "roi_consent"],
    )
    # use_enum_values → plain strings after validation
    assert req.consents == ["npp_ack", "treatment_consent", "roi_consent"]


# --- log_metadata emits only allowlisted, non-PHI facts (the D1 log fix) --------
# The intake log line is now schemas.log_metadata(req), not the request body.
# Plant PHI in every demographic + insurance field and assert none of it appears
# in the logged metadata. FAILS against a body-logging path (even a redacted one,
# which would still echo the name and DOB).


def test_log_metadata_contains_no_phi():
    req = schemas.IntakeRequest(
        demographics={
            "name": "Jane Doe",
            "dob": "1985-03-12",
            "ssn": "123-45-6789",
            "email": "jane@example.com",
            "phone": "555-867-5309",
            "address": "42 Elm St",
            "notes": "allergic to penicillin",
        },
        insurance={"member_id": "BCBS4471", "group_number": "GRP-9"},
        consents=["npp_ack"],
    )
    blob = json.dumps(schemas.log_metadata(req))
    for phi in (
        "Jane Doe", "1985-03-12", "123-45-6789", "jane@example.com",
        "555-867-5309", "42 Elm St", "penicillin", "BCBS4471", "GRP-9",
    ):
        assert phi not in blob


def test_log_metadata_reports_allowlisted_structure():
    req = schemas.IntakeRequest(
        demographics={"name": "Jane Roe", "ssn": "111-22-3333"},
        consents=["npp_ack"],
    )
    meta = schemas.log_metadata(req)
    assert meta["consents"] == ["npp_ack"]
    assert meta["has_ssn"] is True
    assert meta["has_insurance"] is False
    assert meta["has_notes"] is False
    assert meta["self_service"] is True


# NOTE (coverage gap, deliberate): nothing here asserts SSN format, that DOB is
# a real date, or that duplicate patients are prevented — the service does none
# of those (no input normalization, no MPI/match key). See SEEDED-DEBT.
