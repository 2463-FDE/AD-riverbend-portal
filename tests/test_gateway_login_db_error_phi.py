"""
Adversarial PHI test for the gateway login DB-error path (rule 3).

The login handler logged str(e) on a users-SELECT failure; a statement-level
DBAPIError can embed the attempted username via the driver's own message
(and, pre-hide_parameters, via [parameters: (...)]). Surfaced by the pre-push
adversarial review of the intake DB-error fix and folded in on explicit
approval (auth zone, CLAUDE.md §6). Sentinel planted where a real driver
message carries free text; asserts it reaches neither a log record nor the
response. FAILS against the pre-fix code, which logged str(e).
"""
import logging
import sys

import pytest
from sqlalchemy.exc import DataError

from conftest import load_module

_PINNED = ("config", "logging_config", "db", "models", "security", "authz")
_saved = {name: sys.modules.pop(name, None) for name in _PINNED}
sys.modules["config"] = load_module("services/gateway/config.py", "gw_ldbe_config")
sys.modules["logging_config"] = load_module(
    "services/gateway/logging_config.py", "gw_ldbe_logging_config"
)
sys.modules["db"] = load_module("services/gateway/db.py", "gw_ldbe_db")
sys.modules["models"] = load_module("services/gateway/models.py", "gw_ldbe_models")
sys.modules["security"] = load_module("services/gateway/security.py", "gw_ldbe_security")
sys.modules["authz"] = load_module("services/gateway/authz.py", "gw_ldbe_authz")
gw = load_module("services/gateway/app.py", "gw_ldbe_app")
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


USERNAME = "adversarial.q.testuser"
SENTINEL = f'invalid input syntax for type text: "{USERNAME}"'


class _FailingSession:
    """Session double whose execute raises the statement-level error an
    engine produces on the users SELECT, driver message embedding the
    bound username the way Postgres renders bad input."""

    def execute(self, *args, **kwargs):
        raise DataError(
            "SELECT users.username FROM users WHERE users.username = %s",
            (USERNAME,),
            Exception(SENTINEL),
        )


def test_login_db_failure_does_not_leak_username(caplog):
    req = gw.LoginRequest(username=USERNAME, password="irrelevant")
    with caplog.at_level(logging.ERROR):
        with pytest.raises(gw.HTTPException) as exc_info:
            gw.login(req, db=_FailingSession())
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "auth backend unavailable"
    assert USERNAME not in str(exc_info.value.detail)
    # Vacuous-pass guard: the error path must have logged something.
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "login DB failure must log an ERROR record"
    for msg in errors:
        assert USERNAME not in msg
        assert "[SQL" not in msg and "[parameters" not in msg
        assert "DataError" in msg
