"""
Bounded, metacharacter-safe records search (e6-SPEC-1/2/5).

Three properties, all planted-defect fixes on a PHI read path
(docs/landmines.md §1 IDOR zone, §3 negative-test rule):

  * the response carries at most a configured number of hits, so a single call
    can no longer pull the whole record corpus (e6-SPEC-1, E6-REQ-1);
  * LIKE metacharacters in the query are matched as literal characters — a bare
    `%` is a literal percent sign, not "match every row" (e6-SPEC-2 — the
    negative case that FAILS against the pre-fix raw `f"%{q}%"`);
  * a capped response is distinguishable from an exhausted one via `truncated`,
    so "no more matches" cannot be confused with "matches withheld" (e6-SPEC-5).

Plus the producer half of contracts/records-search.json (e6-D-16): the response
model must declare exactly the contract's fields, mirroring
tests/test_intake_payload_contract.py.
"""
import json
import pathlib
import sys

from conftest import load_module

_SIBLINGS = ("config", "db", "logging_config", "models", "schemas")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/records-service/config.py", "records_config_bounds")
sys.modules["db"] = load_module("services/records-service/db.py", "records_db_bounds")
sys.modules["logging_config"] = load_module(
    "services/records-service/logging_config.py", "records_logging_config_bounds"
)
sys.modules["models"] = load_module("services/records-service/models.py", "records_models_bounds")
sys.modules["schemas"] = load_module(
    "services/records-service/schemas.py", "records_schemas_bounds"
)
app_mod = load_module("services/records-service/app.py", "records_app_bounds")
config_mod = sys.modules["config"]
models_mod = sys.modules["models"]
schemas_mod = sys.modules["schemas"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


CONTRACT = json.loads(
    (
        pathlib.Path(__file__).resolve().parent.parent
        / "contracts"
        / "records-search.json"
    ).read_text()
)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _StubSession:
    """Records the statements it is handed and returns a fixed row list. The
    row list stands in for what the DB returns *after* the route's own
    ``LIMIT max_hits + 1`` — so handing it max_hits+1 rows exercises the
    truncation branch exactly as a real over-fetch would."""

    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append(statement)
        return _Rows(self.rows)

    def close(self):
        pass


def _record(rid, body="result body", patient_id=1042):
    return models_mod.Record(
        id=rid, encounter_id=1, patient_id=patient_id,
        kind="progress_note", title="note", body=body, status="final",
    )


# --------------------------------------------------------------- SPEC-1 / SPEC-5

def test_result_set_is_capped_and_flagged_truncated(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "records_search_max_hits", 3, raising=False)
    # A real over-fetch of LIMIT 4 on a corpus with more than 3 matches returns 4.
    session = _StubSession([_record(i) for i in range(4)])
    result = app_mod.search_records(q="body", db=session)
    assert len(result.hits) == 3
    assert result.truncated is True


def test_exact_fill_is_not_truncated(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "records_search_max_hits", 3, raising=False)
    session = _StubSession([_record(i) for i in range(3)])
    result = app_mod.search_records(q="body", db=session)
    assert len(result.hits) == 3
    assert result.truncated is False


def test_under_fill_is_not_truncated(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "records_search_max_hits", 3, raising=False)
    session = _StubSession([_record(i) for i in range(2)])
    result = app_mod.search_records(q="body", db=session)
    assert len(result.hits) == 2
    assert result.truncated is False


# ------------------------------------------------------------------- SPEC-2

def test_like_metacharacters_are_escaped_to_literals():
    """The negative case: `q=%` must be a literal percent sign, not a wildcard
    that matches every row. FAILS against the pre-fix raw ``f"%{q}%"`` (no
    escape), which is the whole-corpus vector E6-REQ-1 closes."""
    session = _StubSession([])
    app_mod.search_records(q="%", db=session)
    compiled = session.statements[0].compile()
    # the wildcard `%...%` surrounds the *escaped* literal `%` (\%)
    assert any(v == "%\\%%" for v in compiled.params.values()), compiled.params
    assert "ESCAPE" in str(compiled).upper()


def test_escape_helper_neutralizes_all_three_metacharacters():
    assert app_mod._escape_like("%") == "\\%"
    assert app_mod._escape_like("a_b") == "a\\_b"
    assert app_mod._escape_like("a\\b") == "a\\\\b"
    # backslash escaped first, so an incoming `\%` becomes `\\\%` not `\\%`
    assert app_mod._escape_like("\\%") == "\\\\\\%"


# ----------------------------------------------------------- contract (producer)

def test_response_model_declares_exactly_the_contract_fields():
    assert set(CONTRACT["response_fields"]["root"]) == set(schemas_mod.RecordSearch.model_fields)
    assert set(CONTRACT["response_fields"]["hit"]) == set(schemas_mod.RecordSearchHit.model_fields)


def test_sample_response_validates_against_the_model():
    parsed = schemas_mod.RecordSearch.model_validate(CONTRACT["sample_response"])
    assert parsed.truncated is False
    assert parsed.hits[0].patient_id == 1042
