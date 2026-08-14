"""Validation tests for the multi-step intake payload (intake-service/schemas.py)."""
import json

from conftest import load_module
import pytest
from pydantic import ValidationError

schemas = load_module("services/intake-service/schemas.py", "intake_schemas")

# A canonical version-4 UUID for the now-required submission_id (e5b-SPEC-4).
# The existing cases below carry it so each still fails for its intended field,
# never merely for the missing id.
VALID_SUBMISSION_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"


def test_minimal_valid_intake():
    req = schemas.IntakeRequest(
        submission_id=VALID_SUBMISSION_ID, demographics={"name": "Jane Roe"}
    )
    assert req.demographics.name == "Jane Roe"
    assert req.demographics.created_via == "self_service"
    # default consents applied
    assert req.consents == ["npp_ack", "treatment_consent"]


def test_full_intake_with_insurance():
    req = schemas.IntakeRequest(
        submission_id=VALID_SUBMISSION_ID,
        demographics={"name": "John Doe", "dob": "1980-01-01", "ssn": "111-22-3333"},
        insurance={"payer_name": "Aetna", "member_id": "AET123", "plan_type": "PPO"},
        consents=["npp_ack"],
    )
    assert req.insurance.payer_name == "Aetna"
    assert req.consents == ["npp_ack"]


def test_blank_name_rejected():
    with pytest.raises(ValidationError):
        schemas.IntakeRequest(
            submission_id=VALID_SUBMISSION_ID, demographics={"name": "   "}
        )


def test_missing_demographics_rejected():
    with pytest.raises(ValidationError):
        schemas.IntakeRequest(submission_id=VALID_SUBMISSION_ID, consents=["npp_ack"])


# --- consents is a closed enum: PHI can't be smuggled through it (Codex review) --
# Regression for D1: consents used to be an open list[str], so a name/DOB placed
# in it survived into the intake log (pattern redaction only scrubs SSN/email/
# phone). It is now a ConsentKind enum, rejected at the boundary. These tests
# FAIL against the pre-fix list[str] schema (which accepts any string).


def test_consents_reject_free_text_phi():
    with pytest.raises(ValidationError):
        schemas.IntakeRequest(
            submission_id=VALID_SUBMISSION_ID,
            demographics={"name": "Jane Roe"},
            consents=["npp_ack", "Jane Doe DOB 1985-03-12"],
        )


def test_consents_reject_unknown_identifier():
    with pytest.raises(ValidationError):
        schemas.IntakeRequest(
            submission_id=VALID_SUBMISSION_ID,
            demographics={"name": "Jane Roe"},
            consents=["not_a_real_consent"],
        )


def test_all_known_consent_kinds_accepted():
    req = schemas.IntakeRequest(
        submission_id=VALID_SUBMISSION_ID,
        demographics={"name": "Jane Roe"},
        consents=[
            "npp_ack",
            "treatment_consent",
            "roi_consent",
            "financial_responsibility_ack",
            "communications_opt_in",
        ],
    )
    # use_enum_values → plain strings after validation
    assert req.consents == [
        "npp_ack",
        "treatment_consent",
        "roi_consent",
        "financial_responsibility_ack",
        "communications_opt_in",
    ]


def test_consent_kind_members_are_pinned_to_five_literals():
    """E4-SPEC-9: the accepted vocabulary is a closed five, named here.

    The enum is a PHI control, not a convenience type (see its docstring), and
    the intake form now offers exactly these five. Pinning the members as
    literals is what makes a silent sixth member — or a widening back to a bare
    ``str`` — a failing test rather than an invisible loosening of the boundary
    that keeps free-text PHI out of the log and the database.
    """
    assert {k.value for k in schemas.ConsentKind} == {
        "npp_ack",
        "treatment_consent",
        "roi_consent",
        "financial_responsibility_ack",
        "communications_opt_in",
    }


# --- log_metadata emits only allowlisted, non-PHI facts (the D1 log fix) --------
# The intake log line is now schemas.log_metadata(req), not the request body.
# Plant PHI in every demographic + insurance field and assert none of it appears
# in the logged metadata. FAILS against a body-logging path (even a redacted one,
# which would still echo the name and DOB).


def test_log_metadata_contains_no_phi():
    req = schemas.IntakeRequest(
        submission_id=VALID_SUBMISSION_ID,
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
        submission_id=VALID_SUBMISSION_ID,
        demographics={"name": "Jane Roe", "ssn": "111-22-3333"},
        consents=["npp_ack"],
    )
    meta = schemas.log_metadata(req)
    assert meta["submission_id"] == VALID_SUBMISSION_ID
    assert meta["consents"] == ["npp_ack"]
    assert meta["has_ssn"] is True
    assert meta["has_insurance"] is False
    assert meta["has_notes"] is False
    assert meta["self_service"] is True


# --- submission_id is a required, version-4-only identifier (e5b-SPEC-4/11/19) ---
# The portal always sends one, so these guard the boundary the residual accepts:
# a missing or malformed id is a correctable-input rejection, never absorbed.


def test_submission_id_is_required():
    """e5b-SPEC-4/11: the field is required, so an omitted id fails validation
    (surfaced as the correctable-input branch at the route)."""
    with pytest.raises(ValidationError) as exc:
        schemas.IntakeRequest(demographics={"name": "Jane Roe"})
    assert "submission_id" in str(exc.value)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not-a-uuid",
        "3f2504e0-4f89-41d3-9a0c",                     # too short
        "3f2504e0-4f89-11d3-9a0c-0305e82c3301",        # version 1, not 4
        "3f2504e0-4f89-41d3-1a0c-0305e82c3301",        # bad variant nibble
        "00000000-0000-0000-0000-000000000000",        # nil UUID
    ],
)
def test_submission_id_rejects_non_v4(bad):
    """e5b-SPEC-19: only a version-4 UUID (with pinned variant bits) is accepted;
    the check narrows accidental derivation, it does not prove randomness."""
    with pytest.raises(ValidationError):
        schemas.IntakeRequest(submission_id=bad, demographics={"name": "Jane Roe"})


def test_submission_id_accepted_and_canonicalized_to_lowercase():
    """e5b-SPEC-19/D-11: a valid v4 is accepted; an uppercased-but-valid one is
    stored lowercase so a replay never misses on case alone."""
    upper = VALID_SUBMISSION_ID.upper()
    req = schemas.IntakeRequest(submission_id=upper, demographics={"name": "Jane Roe"})
    assert req.submission_id == VALID_SUBMISSION_ID


# NOTE (coverage gap, deliberate): nothing here asserts SSN format or that DOB
# is a real date — the service does no input normalization. See SEEDED-DEBT.
# Duplicate patients are no longer un-checked: intake evaluates the ADR 0005
# tier-1 match key and flags candidate pairs (tests/test_intake_match_key.py).
# It still PREVENTS nothing — the chart is created either way, by design.
