"""
Regression test for the intake freeze (RIV-088 / RIV-141, ADR 0010).

Two defects made a slow payer freeze /intake: (1) a seeded time.sleep(4.2) that
blocked every registration unconditionally, and (2) an eligibility call with no
timeout. This proves both are gone: with an instant eligibility response the
call returns well under a second (no 4.2s sleep), and the outbound call passes a
bounded timeout equal to the configured cap.

RED against pre-fix code: the 4.2s sleep blows the sub-second bound, and the
call passed no timeout= kwarg. NOTE: time.sleep is deliberately NOT monkeypatched
here — the sleep removal is exactly what this test guards.
"""
import sys
import time

from conftest import load_module

_SIBLINGS = ("config", "db", "logging_config", "models", "schemas")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/intake-service/config.py", "intake_config_freeze")
sys.modules["db"] = load_module("services/intake-service/db.py", "intake_db_freeze")
sys.modules["logging_config"] = load_module(
    "services/intake-service/logging_config.py", "intake_logging_config_freeze"
)
sys.modules["models"] = load_module("services/intake-service/models.py", "intake_models_freeze")
sys.modules["schemas"] = load_module("services/intake-service/schemas.py", "intake_schemas_freeze")
app_mod = load_module("services/intake-service/app.py", "intake_app_freeze")
schemas_mod = sys.modules["schemas"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

MEMBER_ID = "BCBS4471"


class _FakeResp:
    status_code = 200

    def json(self):
        return {"insurance_id": MEMBER_ID, "active": True, "status": "active", "raw_status": 200}


def test_intake_does_not_block_and_bounds_the_call(monkeypatch):
    seen = {}

    def _instant(*args, **kwargs):
        seen.update(kwargs)
        return _FakeResp()

    monkeypatch.setattr(app_mod.httpx, "get", _instant)
    ins = schemas_mod.Insurance(member_id=MEMBER_ID)

    started = time.perf_counter()
    result = app_mod._verify_eligibility(ins)
    elapsed = time.perf_counter() - started

    # No seeded 4.2s block anymore.
    assert elapsed < 1.0, f"eligibility verification blocked for {elapsed:.2f}s"
    # The outbound call is bounded by the configured timeout (the RIV-141 guard).
    assert "timeout" in seen
    assert seen["timeout"] == app_mod.settings.eligibility_timeout_seconds
    assert result["active"] is True
