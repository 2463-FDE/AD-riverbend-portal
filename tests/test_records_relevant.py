"""
Tests for the chart-open relevant-records helper (W2-SPEC-1..6, 11-serve, 13, 17).

The helper's job is to point a clinician at the few records worth reading first.
Its risk is the opposite of its job: a helper built on fragmented charts lends
the fragmentation authority (eval/rag/REPORT.md §5). So the tests that matter
most here are negative —

  * a sibling chart's records never appear in the response, even when the opened
    chart is provably one of three for the same person (W2-SPEC-4, 17);
  * no sibling patient id appears anywhere in the payload, in any field: the
    disclosure is a bare enum precisely so the surface cannot become a
    cross-chart navigation path (W2-SPEC-5);
  * the disclosure is the status of the component containing the OPENED chart,
    not a verdict over its SSN group, so a mixed group discloses correctly for
    each of its rows (W2-SPEC-21).
"""
import logging
import sys
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.sql.elements import TextClause

from conftest import load_module

_SIBLINGS = ("config", "db", "logging_config", "models", "schemas", "matching")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
sys.modules["config"] = load_module("services/records-service/config.py", "records_config_rel")
sys.modules["db"] = load_module("services/records-service/db.py", "records_db_rel")
sys.modules["logging_config"] = load_module(
    "services/records-service/logging_config.py", "records_logging_config_rel"
)
sys.modules["models"] = load_module("services/records-service/models.py", "records_models_rel")
sys.modules["schemas"] = load_module("services/records-service/schemas.py", "records_schemas_rel")
sys.modules["matching"] = load_module(
    "services/records-service/matching.py", "records_matching_rel"
)
app_mod = load_module("services/records-service/app.py", "records_app_rel")
models_mod = sys.modules["models"]
config_mod = sys.modules["config"]
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


SSN = "412-55-9981"


def _patient(pid, name="Maria Gonzalez", dob="1971-03-02", ssn=SSN,
             address="118 Maple Ave"):
    return models_mod.Patient(id=pid, name=name, dob=dob, ssn=ssn, address=address,
                              created_via="self_service")


def _encounter(eid, patient_id, allergies=None, medications=None, day=1):
    return models_mod.Encounter(
        id=eid, patient_id=patient_id, encounter_type="office_visit", provider="Dr. Patel",
        summary="visit", allergies=allergies, medications=medications,
        occurred_at=datetime(2026, 3, day, tzinfo=timezone.utc),
    )


def _record(rid, encounter_id, patient_id, kind="lab_result", title="CBC panel"):
    return models_mod.Record(
        id=rid, encounter_id=encounter_id, patient_id=patient_id,
        kind=kind, title=title, body="result body", status="final",
    )


def _ssn_row(pid, name, dob, address, ssn=SSN):
    return {"id": pid, "name": name, "dob": dob, "ssn": ssn, "address": address}


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)


class _StubSession:
    def __init__(self, patients=(), encounters=(), records=(), ssn_rows=(), error=None):
        self.patients = {p.id: p for p in patients}
        self.encounters = list(encounters)
        self.records = list(records)
        self.ssn_rows = list(ssn_rows)
        self.record_queries = 0
        self._error = error

    def get(self, model, pk):
        if self._error is not None:
            raise self._error
        return self.patients.get(pk)

    def execute(self, statement, params=None):
        if self._error is not None:
            raise self._error
        if isinstance(statement, TextClause):
            return _Rows(self.ssn_rows)
        sql = str(statement).lower()
        if "from encounters" in sql:
            patient_id = list(statement.compile().params.values())[0]
            return _Rows(sorted(
                (e for e in self.encounters if e.patient_id == patient_id),
                key=lambda e: e.id,
            ))
        self.record_queries += 1
        encounter_id = list(statement.compile().params.values())[0]
        return _Rows(sorted(
            (r for r in self.records if r.encounter_id == encounter_id),
            key=lambda r: r.id,
        ))

    def close(self):
        pass


def _client(session):
    app_mod.app.dependency_overrides[app_mod.get_db] = lambda: session
    return TestClient(app_mod.app, raise_server_exceptions=False)


def teardown_function():
    app_mod.app.dependency_overrides.clear()


# ------------------------------------------------------------------ ranking

def _ranking_session():
    return _StubSession(
        patients=[_patient(1042)],
        encounters=[
            _encounter(1, 1042, day=1),                          # nothing notable, oldest
            _encounter(2, 1042, medications="lisinopril", day=2),
            _encounter(3, 1042, allergies="penicillin", day=3),
            _encounter(4, 1042, day=9),                          # nothing notable, newest
        ],
        records=[
            _record(10, 1, 1042, title="old note"),
            _record(20, 2, 1042, title="med review"),
            _record(30, 3, 1042, title="allergy note"),
            _record(40, 4, 1042, title="recent note"),
        ],
    )


def test_allergy_then_medication_then_recency(monkeypatch):
    r = _client(_ranking_session()).get("/patients/1042/relevant-records")
    assert r.status_code == 200
    body = r.json()
    assert [i["record_id"] for i in body["items"]] == [30, 20, 40, 10]
    assert [i["reason"] for i in body["items"]] == [
        "allergy", "medication", "recent", "recent",
    ]
    assert body["patient_id"] == 1042


def test_items_carry_titles_and_dates_not_record_bodies():
    """The panel links attention; the chart below it stays the record view. A
    body in the panel would make the helper the reading surface for records it
    ranked itself."""
    body = _client(_ranking_session()).get("/patients/1042/relevant-records").text
    assert "allergy note" in body
    assert "result body" not in body


def test_assessed_and_empty_allergy_field_is_not_an_allergy():
    """"none known" means the field was assessed and empty. Ranking it as an
    allergy would put a phantom allergy at the top of a clinician's panel — the
    same sentinel trap eval/rag/data.py::parse_clinical_list exists to avoid.
    The seed carries exactly this value (patient 1601)."""
    session = _StubSession(
        patients=[_patient(1601, name="Aisha Khan", ssn="623-41-2210")],
        encounters=[
            _encounter(1, 1601, allergies="none known", day=1),
            _encounter(2, 1601, medications="metformin", day=2),
        ],
        records=[_record(10, 1, 1601), _record(20, 2, 1601)],
    )
    items = _client(session).get("/patients/1601/relevant-records").json()["items"]
    assert {i["record_id"]: i["reason"] for i in items} == {10: "recent", 20: "medication"}


def test_returned_items_are_capped(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "relevant_records_max_items", 2, raising=False)
    session = _StubSession(
        patients=[_patient(1042)],
        encounters=[_encounter(i, 1042, day=i) for i in range(1, 6)],
        records=[_record(i * 10, i, 1042) for i in range(1, 6)],
    )
    items = _client(session).get("/patients/1042/relevant-records").json()["items"]
    assert len(items) == 2


def test_scan_is_bounded_before_ranking(monkeypatch):
    """W2-SPEC-11 serve-side bound: the helper must not read an unbounded chart
    to rank it. The bound is on records scanned, so it also stops the N+1 loop
    early — a patient with hundreds of encounters costs a fixed number of
    queries, not one per encounter."""
    monkeypatch.setattr(config_mod.settings, "relevant_records_max_scan", 3, raising=False)
    session = _StubSession(
        patients=[_patient(1042)],
        encounters=[_encounter(i, 1042, day=1) for i in range(1, 21)],
        records=[_record(i * 10, i, 1042) for i in range(1, 21)],
    )
    r = _client(session).get("/patients/1042/relevant-records")
    assert r.status_code == 200
    assert session.record_queries <= 3


# --------------------------------------------------------------- scoping

MARIA_CLUSTER = [
    _ssn_row(1042, "Maria Gonzalez", "1971-03-02", "118 Maple Ave"),
    _ssn_row(1330, "Maria Gonzales", "1971-03-02", "118 Maple Ave"),
    _ssn_row(1588, "M. Gonzalez", "1971-02-03", "118 Maple Ave"),
]


def _cluster_session():
    return _StubSession(
        patients=[_patient(1042)],
        encounters=[
            _encounter(1, 1042, day=1),
            _encounter(2, 1330, allergies="penicillin", day=5),   # the sibling's allergy
            _encounter(3, 1588, day=6),
        ],
        records=[
            _record(10, 1, 1042, title="own note"),
            _record(20, 2, 1330, title="SIBLING penicillin allergy"),
            _record(30, 3, 1588, title="SIBLING cbc"),
        ],
        ssn_rows=MARIA_CLUSTER,
    )


def test_sibling_records_never_appear_even_inside_a_candidate_cluster():
    """The whole reason query-time unioning was rejected (ADR 0005
    alternatives). 1330's penicillin allergy is the record a clinician most
    wants — and it must still not appear under 1042, because presenting it there
    would silently merge two charts no human has approved merging."""
    body = _client(_cluster_session()).get("/patients/1042/relevant-records")
    assert body.status_code == 200
    payload = body.json()
    assert [i["record_id"] for i in payload["items"]] == [10]
    text = body.text
    assert "SIBLING" not in text


def test_no_sibling_patient_id_appears_anywhere_in_the_payload():
    """Adversarial over the whole JSON, not just the items list: the disclosure
    is a bare enum so that the surface cannot become a cross-chart navigation
    path (W2-SPEC-5)."""
    text = _client(_cluster_session()).get("/patients/1042/relevant-records").text
    for sibling_id in ("1330", "1588"):
        assert sibling_id not in text
    assert "1042" in text


# ------------------------------------------------------------- disclosure

def test_candidate_cluster_member_gets_the_disclosure():
    body = _client(_cluster_session()).get("/patients/1042/relevant-records").json()
    assert body["duplicate_disclosure"] == "candidate"


def test_patient_without_a_usable_ssn_gets_no_disclosure():
    session = _StubSession(
        patients=[_patient(1042, ssn=None)],
        encounters=[_encounter(1, 1042)],
        records=[_record(10, 1, 1042)],
        ssn_rows=MARIA_CLUSTER,   # would classify candidate if it were queried
    )
    body = _client(session).get("/patients/1042/relevant-records").json()
    assert body["duplicate_disclosure"] == "none"


def test_ambiguous_and_conflicting_rows_get_no_disclosure():
    """Owner decision folded into W2-SPEC-3: candidate clusters only. An
    ambiguous or non-mergeable row is not a duplicate claim, and disclosing one
    as though it were would tell a clinician their record set is incomplete on
    no evidence."""
    ambiguous = _StubSession(
        patients=[_patient(1, name="Ana Ruiz", dob="1990-01-01", address="1 A St")],
        encounters=[_encounter(1, 1)],
        records=[_record(10, 1, 1)],
        ssn_rows=[
            _ssn_row(1, "Ana Ruiz", "1990-01-01", "1 A St"),
            _ssn_row(2, "Ana Ruis", "1990-01-01", "9 Q Blvd"),
            _ssn_row(3, "Zed Kane", "1990-01-01", "9 Q Blvd"),
        ],
    )
    assert _client(ambiguous).get("/patients/1/relevant-records").json()[
        "duplicate_disclosure"] == "none"
    teardown_function()

    conflict = _StubSession(
        patients=[_patient(1, name="Ana Ruiz", dob="1990-01-01", address="1 A St")],
        encounters=[_encounter(1, 1)],
        records=[_record(10, 1, 1)],
        ssn_rows=[
            _ssn_row(1, "Ana Ruiz", "1990-01-01", "1 A St"),
            _ssn_row(2, "Ben Cole", "1962-09-30", "77 Z Blvd"),
        ],
    )
    assert _client(conflict).get("/patients/1/relevant-records").json()[
        "duplicate_disclosure"] == "none"


def test_disclosure_is_per_row_inside_a_mixed_group():
    """One SSN carrying a corroborating pair plus a row that corroborates with
    nobody. Opening 1 must disclose; opening 3 must not. A whole-group verdict
    is wrong in one direction or the other for every mixed group."""
    mixed_rows = [
        _ssn_row(1, "Ana Ruiz", "1990-01-01", "1 A St"),
        _ssn_row(2, "Ana Ruis", "1990-01-01", "1 A St"),
        _ssn_row(3, "Zed Kane", "1975-12-25", "77 Z Blvd"),
    ]
    for pid, expected in ((1, "candidate"), (3, "none")):
        session = _StubSession(
            patients=[_patient(pid, name="x", dob="1990-01-01", address="1 A St")],
            encounters=[_encounter(1, pid)],
            records=[_record(10, 1, pid)],
            ssn_rows=mixed_rows,
        )
        body = _client(session).get(f"/patients/{pid}/relevant-records").json()
        assert body["duplicate_disclosure"] == expected, pid
        teardown_function()


def test_ssn_prefilter_is_bound_as_a_normalized_parameter():
    """W2-SPEC-24 adjacency: normalization happens in the WHERE clause, so the
    whole SSN-bearing population is never pulled into this per-chart-open path,
    and no normalized copy is stored anywhere."""
    seen = {}

    class _Watching(_StubSession):
        def execute(self, statement, params=None):
            if isinstance(statement, TextClause):
                seen["params"] = params
            return super().execute(statement, params)

    session = _Watching(
        patients=[_patient(1042)],
        encounters=[_encounter(1, 1042)],
        records=[_record(10, 1, 1042)],
        ssn_rows=MARIA_CLUSTER,
    )
    _client(session).get("/patients/1042/relevant-records")
    assert seen["params"] == {"normalized": "412559981"}


# ------------------------------------------------------------ failure paths

def test_unknown_patient_is_404():
    r = _client(_StubSession()).get("/patients/9999/relevant-records")
    assert r.status_code == 404


def test_database_error_is_503_with_class_name_only(caplog):
    boom = OperationalError(
        "SELECT * FROM encounters", {},
        Exception("connection refused; ssn 412-55-9981 in flight"),
    )
    session = _StubSession(error=boom)
    with caplog.at_level(logging.ERROR):
        r = _client(session).get("/patients/1042/relevant-records")
    assert r.status_code == 503
    errors = [rec.getMessage() for rec in caplog.records if rec.levelno >= logging.ERROR]
    assert any("OperationalError" in m for m in errors)
    for message in errors:
        assert "412-55-9981" not in message
        assert "connection refused" not in message


def test_no_phi_reaches_a_log_record_on_the_success_path(caplog):
    session = _StubSession(
        patients=[_patient(1042)],
        encounters=[_encounter(1, 1042, allergies="penicillin")],
        records=[_record(10, 1, 1042, title="allergy note")],
        ssn_rows=MARIA_CLUSTER,
    )
    with caplog.at_level(logging.DEBUG):
        _client(session).get("/patients/1042/relevant-records")
    for record in caplog.records:
        message = record.getMessage()
        for value in ("412-55-9981", "412559981", "Maria Gonzalez", "118 Maple Ave",
                      "penicillin", "allergy note", "1971-03-02"):
            assert value not in message, f"PHI leaked into a log record: {message!r}"


# ------------------------------------------------- embedding discipline (SPEC-13)

def test_records_service_imports_no_embedding_or_vendor_sdk():
    """W2-SPEC-13 by construction: the serving path contains no embedding code
    at all, so a chart open cannot issue a corpus embedding computation. Checked
    across the whole service directory — matching.py, config.py and schemas.py
    are as capable of importing one as app.py is."""
    import os
    import re

    from conftest import REPO_ROOT

    banned = re.compile(
        r"\b(sentence_transformers|torch|transformers|openai|anthropic|boto3|"
        r"bedrock|cohere|huggingface_hub)\b"
    )
    service_dir = os.path.join(REPO_ROOT, "services", "records-service")
    offenders = []
    for name in sorted(os.listdir(service_dir)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(service_dir, name)) as f:
            for lineno, line in enumerate(f, start=1):
                stripped = line.strip()
                if not (stripped.startswith("import ") or stripped.startswith("from ")):
                    continue
                if banned.search(stripped):
                    offenders.append(f"{name}:{lineno} {stripped}")
    assert offenders == []


@pytest.mark.parametrize("setting,default", [
    ("relevant_records_max_items", 10),
    ("relevant_records_max_scan", 500),
])
def test_serve_bounds_are_configured_not_hardcoded(setting, default):
    assert getattr(config_mod.settings, setting) == default
