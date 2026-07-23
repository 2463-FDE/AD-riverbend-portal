"""
Adversarial PHI test for the eligibility-service handler (app.py), ADR 0010.

This is the cross-service leak the intake-side test could not catch. Pre-fix,
check_eligibility caught the payer exception and did BOTH `log.error(..., %s, e)`
(with insurance_id also logged directly) and `error=str(e)` — and because check()
let the raw requests exception (URL carrying member_id) escape, the member_id
leaked into the eligibility log AND the response body, which intake then passed
straight into the /intake response.

Post-fix the handler logs the exception CLASS only and returns a generic error
literal. This plants a member_id inside the raised exception message and asserts
it survives nowhere. RED against pre-fix code.
"""
import logging
import sys

from conftest import load_module

_SIBLINGS = ("config", "breaker", "check", "logging_config", "schemas")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/eligibility-service/config.py", "elig_config_phi")
sys.modules["breaker"] = load_module("services/eligibility-service/breaker.py", "elig_breaker_phi")
sys.modules["check"] = load_module("services/eligibility-service/check.py", "elig_check_phi")
sys.modules["logging_config"] = load_module(
    "services/eligibility-service/logging_config.py", "elig_logging_config_phi"
)
sys.modules["schemas"] = load_module("services/eligibility-service/schemas.py", "elig_schemas_phi")
app_mod = load_module("services/eligibility-service/app.py", "elig_app_phi")
breaker_mod = sys.modules["breaker"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

MEMBER_ID = "BCBS4471"


def test_handler_does_not_leak_member_id_on_payer_failure(monkeypatch, caplog):
    def _raise_with_id(insurance_id):
        # Even if a payer exception message were to embed the member_id, the
        # handler must not stringify it into the log or the response.
        raise breaker_mod.PayerTimeout(
            "timeout: /v1/eligibility?member_id=%s" % MEMBER_ID
        )

    monkeypatch.setattr(app_mod, "check", _raise_with_id)

    with caplog.at_level(logging.ERROR):
        response = app_mod.check_eligibility(MEMBER_ID)

    assert response.active is False
    assert response.status == "unknown"
    assert response.error == "eligibility check failed"
    # The response object flows outward (and into /intake) — no member_id anywhere.
    assert MEMBER_ID not in response.error
    # No log record may carry the id (pre-fix logged both insurance_id and str(e)).
    for record in caplog.records:
        assert MEMBER_ID not in record.getMessage()
