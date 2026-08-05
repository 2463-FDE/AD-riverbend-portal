"""
Wiring proof for the hide_parameters engine backstop (phi-logging-policy rule 3).

The log-idiom fix in intake app.py stops today's known str(e) sites; this pins
the engine-level backstop that protects any future one: with
hide_parameters=True a DBAPIError renders ``[SQL: ...] [parameters hidden due
to hide_parameters=True]`` instead of the bound row. SQLAlchemy's own suite
covers that rendering; what is ours to prove is that every service's engine
actually carries the flag — a check that has never fired is not wired, so this
is mutation-proven by removing the flag from one db.py and watching that
service's case go red.

eligibility-service and interop-service have no db.py/engine (no DB access).
"""
import sys

import pytest

from conftest import load_module

# Every service with a SQLAlchemy engine. gateway/intake build it at import;
# records/roi/scheduling defer it behind get_engine().
SERVICES = [
    "gateway",
    "intake-service",
    "records-service",
    "roi-service",
    "scheduling-service",
]


@pytest.mark.parametrize("service", SERVICES)
def test_engine_hides_parameters(service):
    slug = service.replace("-", "_")
    saved = {n: sys.modules.pop(n, None) for n in ("config", "db")}
    try:
        sys.modules["config"] = load_module(
            f"services/{service}/config.py", f"{slug}_config_hidep"
        )
        db_mod = load_module(f"services/{service}/db.py", f"{slug}_db_hidep")
        engine = db_mod.engine if hasattr(db_mod, "engine") else db_mod.get_engine()
        assert engine.hide_parameters is True
    finally:
        for name, module in saved.items():
            if module is not None:
                sys.modules[name] = module
            else:
                sys.modules.pop(name, None)
