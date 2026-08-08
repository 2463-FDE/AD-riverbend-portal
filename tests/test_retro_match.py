"""
Tests for the retroactive match pass (W2-SPEC-29, 30, 31).

The pass exists because flagging duplicates at chart-create only helps charts
created from now on; the Maria cluster and everything like it is already in the
table (ADR 0005 decision 4). Three properties are pinned here:

  * it queues every candidate pair it finds, including the Maria trio;
  * it is **read-only over patients** — a pass that could touch a patient row
    would be a merge by another name, and merges are a manual HIM procedure;
  * a re-run inserts nothing, because operators will re-run it.

It is also the only reader of ``match_evaluation_failures``. Without that, the
table is write-only — the D2 failure mode inverted (audit_logs has no writers)
— and "the failure is recorded" would mean "visible in psql to whoever thinks
to look".
"""
import sys

from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Insert

from conftest import REPO_ROOT, load_module

_SIBLINGS = ("config", "db", "logging_config", "models", "schemas", "matching")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/intake-service/config.py", "intake_config_retro")
sys.modules["db"] = load_module("services/intake-service/db.py", "intake_db_retro")
sys.modules["logging_config"] = load_module(
    "services/intake-service/logging_config.py", "intake_logging_config_retro"
)
sys.modules["models"] = load_module("services/intake-service/models.py", "intake_models_retro")
sys.modules["matching"] = load_module(
    "services/intake-service/matching.py", "intake_matching_retro"
)
retro = load_module("services/intake-service/retro_match.py", "intake_retro_match")
models_mod = sys.modules["models"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


import os  # noqa: E402  (after the sibling pinning above)

rag_data = load_module("eval/rag/data.py", "rag_data_retro")
SEED = os.path.join(REPO_ROOT, "db", "seed")
SEED_PATIENTS = rag_data.load_patients(os.path.join(SEED, "patients.csv"))
MARIA_IDS = [1042, 1330, 1588]


def _row(p):
    return {"id": p.id, "name": p.name, "dob": p.dob, "ssn": p.ssn, "address": p.address}


class _StubResult:
    def __init__(self, rows, rowcount=0):
        self._rows = rows
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)


class _StubSession:
    """Models the queue's UNIQUE constraint so a second pass really does insert
    nothing, rather than passing on a stub that tolerates duplicates."""

    def __init__(self, patients, failures=()):
        self._patients = [_row(p) if not isinstance(p, dict) else p for p in patients]
        self._failures = list(failures)
        self.queue = []
        self.added = []
        self.deleted = []
        self.commits = 0

    # -- Session surface ---------------------------------------------------
    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass

    def execute(self, statement, params=None):
        if isinstance(statement, Insert):
            compiled = statement.compile(dialect=postgresql.dialect())
            values = compiled.params
            pair = (values["patient_id_a"], values["patient_id_b"])
            assert "ON CONFLICT" in str(compiled).upper(), (
                "the retroactive pass must be re-runnable; its queue insert has to "
                "carry ON CONFLICT DO NOTHING"
            )
            if any(q[:2] == pair for q in self.queue):
                return _StubResult([], rowcount=0)
            self.queue.append((*pair, values["source"]))
            return _StubResult([], rowcount=1)

        # SELECTs are distinguished by the entity the caller asked for.
        target = str(statement).lower()
        if "match_evaluation_failures" in target:
            return _StubResult(self._failures)
        return _StubResult(self._patients)


def test_maria_trio_is_queued_as_three_pairs():
    db = _StubSession(SEED_PATIENTS)
    summary = retro.run(db)
    assert [(a, b) for a, b, _ in db.queue] == [
        (1042, 1330), (1042, 1588), (1330, 1588),
    ]
    assert all(source == "retroactive" for _, _, source in db.queue)
    assert summary["candidate_pairs"] == 3
    assert summary["queued"] == 3
    assert summary["patients_scanned"] == len(SEED_PATIENTS)


def test_second_pass_inserts_nothing():
    db = _StubSession(SEED_PATIENTS)
    retro.run(db)
    summary = retro.run(db)
    assert summary["candidate_pairs"] == 3     # still found
    assert summary["queued"] == 0              # ...and absorbed by the constraint
    assert len(db.queue) == 3


def test_pass_never_writes_a_patient_row():
    db = _StubSession(SEED_PATIENTS)
    retro.run(db)
    assert db.added == [], "the retroactive pass must not add rows via the ORM"
    assert db.deleted == []


def test_ambiguous_rows_yield_no_pairs():
    rows = [
        {"id": 1, "name": "Ana Ruiz", "dob": "1990-01-01",
         "ssn": "412-55-9981", "address": "1 A St"},
        {"id": 2, "name": "Ana Ruis", "dob": "1990-01-01",
         "ssn": "412-55-9981", "address": "9 Q Blvd"},
        {"id": 3, "name": "Zed Kane", "dob": "1990-01-01",
         "ssn": "412-55-9981", "address": "9 Q Blvd"},
    ]
    db = _StubSession(rows)
    summary = retro.run(db)
    assert db.queue == []
    assert summary["candidate_pairs"] == 0


def test_rows_without_a_usable_ssn_are_reported_as_unevaluable():
    """Tier 2 is deferred, so these rows are not merely "no match found" — the
    match key could not be applied to them at all. The summary says so rather
    than reporting a clean pass over them."""
    rows = [
        {"id": 1, "name": "Ana Ruiz", "dob": "1990-01-01", "ssn": "", "address": "1 A St"},
        {"id": 2, "name": "Ana Ruiz", "dob": "1990-01-01",
         "ssn": "000-00-0000", "address": "1 A St"},
        {"id": 3, "name": "Ben Cole", "dob": "1991-02-02",
         "ssn": "587-33-1204", "address": "2 B St"},
    ]
    db = _StubSession(rows)
    summary = retro.run(db)
    assert summary["without_usable_ssn"] == 2
    assert summary["ssn_groups"] == 1


def test_recorded_match_failures_are_reported_and_their_patients_re_evaluated():
    failures = [
        {"patient_id": 1042, "error_class": "OperationalError"},
        {"patient_id": 1330, "error_class": "OperationalError"},
        {"patient_id": 4242, "error_class": "TimeoutError"},
    ]
    db = _StubSession(SEED_PATIENTS, failures=failures)
    summary = retro.run(db)
    assert summary["failure_counts"] == {"OperationalError": 2, "TimeoutError": 1}
    # 1042 and 1330 are in the seed and carry a usable SSN, so this pass has
    # just re-evaluated them. 4242 is not in the table at all.
    assert summary["failures_re_evaluated"] == 2
    assert summary["failures_still_unevaluated"] == 1


def test_summary_render_carries_ids_and_counts_only():
    """The printed block is operator-facing output from a service that handles
    PHI. patient_id is the allowlisted identifier (PHI policy rule 2); a name,
    DOB, address, or SSN appearing here would be a disclosure to whoever runs
    the pass and to wherever the output is captured."""
    db = _StubSession(SEED_PATIENTS, failures=[{"patient_id": 1042,
                                                "error_class": "OperationalError"}])
    text_out = retro.render(retro.run(db))
    for patient in SEED_PATIENTS:
        assert patient.name not in text_out
        assert patient.ssn not in text_out
        if patient.ssn:
            assert retro.matching.normalize_ssn(patient.ssn) not in text_out
        assert patient.address not in text_out
        if patient.dob:
            assert patient.dob not in text_out
    assert "1042" in text_out          # ids are what an operator acts on
    assert "OperationalError" in text_out
