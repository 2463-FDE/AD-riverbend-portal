"""PHI redaction helpers — copy of services/ai-assistant/redaction.py.

Copy-pasted per ADR 0001 (no shared Python lib). The ai-assistant copy is
canonical; this copy is parity-tested in tests/test_redaction.py — keep in sync.

Stdlib only, so the module drops into any service without new dependencies.
"""
import json
import re
from typing import Any

REDACTED = "[REDACTED]"

# Key names whose values are PHI or PHI-adjacent identifiers. Drawn from the
# actual intake schemas (services/intake-service/schemas.py) plus MRN.
# The internal surrogate `patient_id` is deliberately NOT listed: policy
# permits internal numeric ids in logs (scheduling relies on this).
PHI_FIELDS = frozenset(
    {
        "name",
        "dob",
        "ssn",
        "gender",
        "address",
        "phone",
        "email",
        "notes",
        "member_id",
        "group_number",
        "insurance_id",
        "mrn",
    }
)

_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b\d{9}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_RE = re.compile(r"\(?\b\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")


def redact(value: Any) -> Any:
    """Recursively replace PHI field values with REDACTED. Never mutates input.

    Two layers: (1) values under a known PHI key are fully masked; (2) EVERY
    remaining string scalar is pattern-scrubbed with ``redact_text``. Layer 2
    is what stops PHI smuggled into an unconstrained field (e.g. an SSN inside
    an ``IntakeRequest.consents`` string) from reaching the log unmasked.
    """
    if isinstance(value, dict):
        return {
            key: REDACTED if str(key).lower() in PHI_FIELDS else redact(val)
            for key, val in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(text: str) -> str:
    """Scrub SSN / email / phone patterns out of free text."""
    text = _SSN_RE.sub(REDACTED, text)
    text = _EMAIL_RE.sub(REDACTED, text)
    text = _PHONE_RE.sub(REDACTED, text)
    return text


def safe_log_payload(obj: Any) -> str:
    """Redacted JSON string of a payload — the one call sites should use.

    Accepts a Pydantic v2 model (anything with model_dump()) or plain
    dict/list structures.
    """
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump()
    return json.dumps(redact(obj), default=str)
