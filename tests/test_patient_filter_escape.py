"""
Metacharacter-safe patient-name filter, existing bound pinned (e6-SPEC-3/4).

The patient-list `q` filter shares the search route's defect: a raw
``f"%{q}%"`` lets a bare `%` match every patient (E6-REQ-2, docs/landmines.md §1
IDOR zone). e6 escapes it with the same helper as the records search. SPEC-4
pins the list's existing limit/offset bound so the escaping change cannot
regress it — the list was already bounded (default 25, server cap 100); only the
escaping is new.
"""
import sys

from fastapi.testclient import TestClient

from conftest import load_module

_SIBLINGS = ("config", "db", "logging_config", "models", "schemas", "matching")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/records-service/config.py", "records_config_pf")
sys.modules["db"] = load_module("services/records-service/db.py", "records_db_pf")
sys.modules["logging_config"] = load_module(
    "services/records-service/logging_config.py", "records_logging_config_pf"
)
sys.modules["models"] = load_module("services/records-service/models.py", "records_models_pf")
sys.modules["schemas"] = load_module("services/records-service/schemas.py", "records_schemas_pf")
sys.modules["matching"] = load_module("services/records-service/matching.py", "records_matching_pf")
app_mod = load_module("services/records-service/app.py", "records_app_pf")
models_mod = sys.modules["models"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def scalar_one(self):
        return len(self._rows)


class _StubSession:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append(statement)
        return _Rows(self.rows)

    def close(self):
        pass


def _patient(pid, name="Maria Gonzalez"):
    return models_mod.Patient(id=pid, name=name, dob="1971-03-02", created_via="self_service")


def _client(session):
    app_mod.app.dependency_overrides[app_mod.get_db] = lambda: session
    return TestClient(app_mod.app, raise_server_exceptions=False)


def teardown_function():
    app_mod.app.dependency_overrides.clear()


# ------------------------------------------------------------------- SPEC-3

def test_name_filter_escapes_like_metacharacters():
    """`q=%` on the patient list must be a literal percent sign, not a wildcard
    matching every patient. FAILS against the pre-fix raw ``f"%{q}%"``."""
    session = _StubSession([])
    app_mod.list_patients(q="%", limit=25, offset=0, db=session)
    # both the count and the page query carry the escaped pattern
    escaped_seen = False
    for stmt in session.statements:
        compiled = stmt.compile()
        if any(v == "%\\%%" for v in compiled.params.values()):
            escaped_seen = True
            assert "ESCAPE" in str(compiled).upper()
    assert escaped_seen, [s.compile().params for s in session.statements]


# ------------------------------------------------------------------- SPEC-4

def test_caller_limit_is_applied_to_the_page_query():
    session = _StubSession([_patient(i) for i in range(3)])
    app_mod.list_patients(q="Maria", limit=5, offset=2, db=session)
    page_stmt = next(
        s for s in session.statements if "LIMIT" in str(s.compile()).upper()
    )
    compiled = page_stmt.compile()
    assert 5 in compiled.params.values()
    assert 2 in compiled.params.values()


def test_limit_is_echoed_in_the_response():
    r = _client(_StubSession([_patient(1)])).get("/patients?limit=7")
    assert r.status_code == 200
    assert r.json()["limit"] == 7


def test_limit_over_server_cap_is_rejected():
    r = _client(_StubSession([_patient(1)])).get("/patients?limit=200")
    assert r.status_code == 422


def test_limit_below_floor_is_rejected():
    r = _client(_StubSession([_patient(1)])).get("/patients?limit=0")
    assert r.status_code == 422
