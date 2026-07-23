"""
Adversarial PHI test for the intake eligibility failure path (app.py).

Codex review: _verify_eligibility sends insurance_id=<member_id> as a query
param, and on a payer connect/timeout/DNS failure httpx embeds the failing URL
in its exception message. Stringifying that exception (str(e)) would leak the
member_id into both logs/intake-service.log and the /intake response. This test
plants a member_id inside a simulated httpx failure message and asserts it never
reaches the returned body or a log record. It FAILS against the pre-fix code,
which returned/logged str(e).
"""
import logging
import sys

from conftest import load_module

# intake-service has its own config/db/logging_config/models/schemas; load_module
# puts each service dir on sys.path, so bare sibling names are ambiguous across
# services by the time this loads. Pin intake's copies while app.py imports, then
# restore (same technique as test_llm_client.py).
_SIBLINGS = ("config", "db", "logging_config", "models", "schemas")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/intake-service/config.py", "intake_config_elig")
sys.modules["db"] = load_module("services/intake-service/db.py", "intake_db_elig")
sys.modules["logging_config"] = load_module(
    "services/intake-service/logging_config.py", "intake_logging_config_elig"
)
sys.modules["models"] = load_module("services/intake-service/models.py", "intake_models_elig")
sys.modules["schemas"] = load_module("services/intake-service/schemas.py", "intake_schemas_elig")
app_mod = load_module("services/intake-service/app.py", "intake_app_elig")
schemas_mod = sys.modules["schemas"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


MEMBER_ID = "BCBS4471"


def _raise_with_url(*args, **kwargs):
    # Mimic httpx embedding the failing URL (with the insurance_id query param)
    # in its exception message on a connect/timeout/DNS failure.
    raise ConnectionError(
        "failed to connect to "
        "http://eligibility-service:8072/eligibility?insurance_id=%s" % MEMBER_ID
    )


def test_eligibility_failure_does_not_leak_member_id(monkeypatch, caplog):
    monkeypatch.setattr(app_mod.time, "sleep", lambda *a, **k: None)  # skip the 4.2s block
    monkeypatch.setattr(app_mod.httpx, "get", _raise_with_url)
    ins = schemas_mod.Insurance(member_id=MEMBER_ID)

    with caplog.at_level(logging.ERROR):
        result = app_mod._verify_eligibility(ins)

    # The returned body flows into the /intake response — it must carry no member_id.
    assert MEMBER_ID not in str(result)
    assert result == {"active": None, "status": "unknown", "reason": "eligibility check failed"}
    # Nor may any log record carry it (the URL/query-param leak vector).
    for record in caplog.records:
        assert MEMBER_ID not in record.getMessage()
