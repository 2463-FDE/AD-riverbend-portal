"""
Unit tests for the PHI redaction helper.

Two copies exist per ADR 0001 (no shared package): the canonical copy in
ai-assistant and the copy-paste in intake-service. The parity tests here are
the guard against the copies drifting apart.
"""
from conftest import load_module

# redaction.py is stdlib-only in both copies, so no sibling-import pinning is
# needed here (unlike test_llm_client.py).
ai_redaction = load_module("services/ai-assistant/redaction.py", "ai_redaction")
intake_redaction = load_module("services/intake-service/redaction.py", "intake_redaction")
intake_schemas = load_module("services/intake-service/schemas.py", "intake_schemas_redaction_test")

SAMPLE = {
    "demographics": {
        "name": "Jane Doe",
        "dob": "1985-03-12",
        "ssn": "123-45-6789",
        "phone": "555-867-5309",
        "email": "jane@example.com",
        "notes": "allergic to penicillin",
        "created_via": "self_service",
    },
    "insurance": {
        "payer_name": "BCBS",
        "member_id": "BCBS4471",
        "group_number": "GRP-9",
        "plan_type": "PPO",
    },
    "patient_id": 42,
    "consents": ["npp_ack"],
}


def test_redact_scrubs_phi_fields():
    out = ai_redaction.redact(SAMPLE)
    demo = out["demographics"]
    for key in ("name", "dob", "ssn", "phone", "email", "notes"):
        assert demo[key] == ai_redaction.REDACTED
    assert out["insurance"]["member_id"] == ai_redaction.REDACTED
    assert out["insurance"]["group_number"] == ai_redaction.REDACTED


def test_redact_preserves_non_phi():
    out = ai_redaction.redact(SAMPLE)
    assert out["patient_id"] == 42
    assert out["consents"] == ["npp_ack"]
    assert out["demographics"]["created_via"] == "self_service"
    assert out["insurance"]["plan_type"] == "PPO"
    assert out["insurance"]["payer_name"] == "BCBS"


def test_redact_handles_nested_lists_and_does_not_mutate():
    nested = {"records": [{"ssn": "111223333", "visit": 1}], "count": 1}
    out = ai_redaction.redact(nested)
    assert out["records"][0]["ssn"] == ai_redaction.REDACTED
    assert out["records"][0]["visit"] == 1
    # original untouched
    assert nested["records"][0]["ssn"] == "111223333"


def test_redact_is_idempotent():
    once = ai_redaction.redact(SAMPLE)
    twice = ai_redaction.redact(once)
    assert once == twice


def test_redact_text_scrubs_patterns():
    text = "SSN 123-45-6789, call (555) 867-5309 or mail jane@example.com today"
    out = ai_redaction.redact_text(text)
    assert "123-45-6789" not in out
    assert "867-5309" not in out
    assert "jane@example.com" not in out
    assert "today" in out


def test_redact_text_leaves_clean_text_alone():
    text = "patient checked in at front desk"
    assert ai_redaction.redact_text(text) == text


def test_safe_log_payload_with_real_intake_request():
    req = intake_schemas.IntakeRequest(
        demographics=intake_schemas.Demographics(
            name="Jane Doe", dob="1985-03-12", ssn="123-45-6789"
        ),
        insurance=intake_schemas.Insurance(member_id="BCBS4471"),
    )
    logged = ai_redaction.safe_log_payload(req)
    assert "Jane Doe" not in logged
    assert "123-45-6789" not in logged
    assert "BCBS4471" not in logged
    assert ai_redaction.REDACTED in logged


def test_copies_have_identical_phi_fields():
    assert ai_redaction.PHI_FIELDS == intake_redaction.PHI_FIELDS


def test_copies_produce_identical_output():
    assert ai_redaction.redact(SAMPLE) == intake_redaction.redact(SAMPLE)
    assert ai_redaction.safe_log_payload(SAMPLE) == intake_redaction.safe_log_payload(SAMPLE)
