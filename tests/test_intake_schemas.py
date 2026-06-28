"""Validation tests for the multi-step intake payload (intake-service/schemas.py)."""
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


# NOTE (coverage gap, deliberate): nothing here asserts SSN format, that DOB is
# a real date, or that duplicate patients are prevented — the service does none
# of those (no input normalization, no MPI/match key). See SEEDED-DEBT.
