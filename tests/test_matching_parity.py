"""
Tests for the per-service duplicate matcher copies (W2-SPEC-20, 21, 24).

Two things are pinned here:

  * **Byte parity** between ``services/intake-service/matching.py`` and
    ``services/records-service/matching.py``. There is no shared library
    (ADR 0001), so the module is copy-pasted per service. ``redaction.py``
    shows where that ends up without a guard — its copies have drifted and
    are only behaviour-parity-tested (tests/test_redaction.py). Both
    ``matching.py`` files are new, so byte parity is free here and blocks
    that drift class outright.
  * **Coherence with ``eval/rag/data.py``**, which already implements the
    ADR 0005 corroboration semantics the spec cites. The eval harness is the
    measured baseline behind eval/rag/REPORT.md; a serving matcher that
    classified differently would make the report's candidate-duplicate rate
    describe a system that no longer exists.

The load-bearing case is the **mixed group**: one SSN whose rows split into a
corroborating clique *and* rows that corroborate with nobody. A single verdict
per SSN group cannot express that, and getting it wrong in either direction
either suppresses a real duplicate disclosure or asserts one over two different
humans (W2-SPEC-21).
"""
import os

from conftest import REPO_ROOT, load_module

rag_data = load_module("eval/rag/data.py", "rag_data_matching")

INTAKE_COPY = os.path.join(REPO_ROOT, "services", "intake-service", "matching.py")
RECORDS_COPY = os.path.join(REPO_ROOT, "services", "records-service", "matching.py")

matching = load_module("services/intake-service/matching.py", "intake_matching")

SEED = os.path.join(REPO_ROOT, "db", "seed")
PATIENTS = rag_data.load_patients(os.path.join(SEED, "patients.csv"))
MARIA_IDS = [1042, 1330, 1588]


def _row(p) -> dict:
    """eval Patient -> the plain-dict shape the matcher takes."""
    return {"id": p.id, "name": p.name, "dob": p.dob, "ssn": p.ssn, "address": p.address}


def _p(pid, name, dob, addr, ssn):
    return rag_data.Patient(
        id=pid, name=name, dob=dob, ssn=ssn, address=addr, created_via="self_service"
    )


# ------------------------------------------------------------- byte parity

def test_service_copies_are_byte_identical():
    with open(INTAKE_COPY, "rb") as f:
        intake_bytes = f.read()
    with open(RECORDS_COPY, "rb") as f:
        records_bytes = f.read()
    assert intake_bytes == records_bytes, (
        "matching.py has drifted between intake-service and records-service. "
        "The copies are deliberately identical (ADR 0001 per-service copy-paste); "
        "apply every edit to both."
    )


def test_records_copy_imports_and_agrees_with_intake_copy():
    """Byte parity is checked on disk; this proves both copies actually load
    and expose the same public surface, so a copy that is identical but
    broken (e.g. importing a sibling only one service has) still fails."""
    records_matching = load_module("services/records-service/matching.py", "records_matching")
    rows = [_row(p) for p in PATIENTS]
    assert records_matching.candidate_pairs(rows) == matching.candidate_pairs(rows)
    assert records_matching.status_for(rows, 1042) == matching.status_for(rows, 1042)


# ---------------------------------------------- coherence with the eval harness

def test_maria_trio_classifies_candidate_like_the_eval_harness():
    rows = [_row(p) for p in PATIENTS]
    components = matching.classify_ssn_group(rows)
    candidates = [c for c in components if c["status"] == "candidate"]
    assert [c["patient_ids"] for c in candidates] == [MARIA_IDS]
    assert matching.candidate_pairs(rows) == [(1042, 1330), (1042, 1588), (1330, 1588)]
    for pid in MARIA_IDS:
        assert matching.status_for(rows, pid) == "candidate"

    # ...and the eval harness says the same thing about the same fixtures.
    identities = rag_data.resolve_identities(PATIENTS, "ssn")
    eval_candidates = [i.patient_ids for i in identities if i.status == "candidate"]
    assert eval_candidates == [c["patient_ids"] for c in candidates]


def test_bridge_rows_are_ambiguous_and_yield_no_pair():
    # A corroborates B, B corroborates C, A and C conflict. Corroboration is a
    # similarity relation, not an equivalence — the component is not a clique,
    # so every row is ambiguous and nothing is queueable (W2-SPEC-21).
    rows = [
        _row(_p(1, "Ana Ruiz", "1990-01-01", "1 A St", "412-55-9981")),
        _row(_p(2, "Ana Ruis", "1990-01-01", "9 Q Blvd", "412-55-9981")),
        _row(_p(3, "Zed Kane", "1990-01-01", "9 Q Blvd", "412-55-9981")),
    ]
    components = matching.classify_ssn_group(rows)
    assert [(c["patient_ids"], c["status"]) for c in components] == [
        ([1], "ambiguous"),
        ([2], "ambiguous"),
        ([3], "ambiguous"),
    ]
    assert matching.candidate_pairs(rows) == []
    for pid in (1, 2, 3):
        assert matching.status_for(rows, pid) == "ambiguous"


def test_conflicting_demographics_are_non_mergeable_and_yield_no_pair():
    # A structurally valid SSN can still be shared, mistyped, or fraudulent.
    # Two rows that agree on nothing else are non-mergeable, never candidates.
    rows = [
        _row(_p(1, "Ana Ruiz", "1990-01-01", "1 A St", "412-55-9981")),
        _row(_p(2, "Ben Cole", "1962-09-30", "77 Z Blvd", "412-55-9981")),
    ]
    components = matching.classify_ssn_group(rows)
    assert [(c["patient_ids"], c["status"]) for c in components] == [
        ([1], "conflict"),
        ([2], "conflict"),
    ]
    assert matching.candidate_pairs(rows) == []
    for pid in (1, 2):
        assert matching.status_for(rows, pid) == "conflict"


def test_topology_zoo_matches_the_eval_harness_row_for_row():
    """The eval's own counterexample zoo (clique, bridge chain, star, two
    disjoint pairs under one SSN), replayed through the serving matcher. Any
    classification difference between the two implementations shows up here."""
    rows = [
        _p(1, "Maria Gonzalez", "1971-02-03", "12 Elm St", "412-55-9981"),
        _p(2, "Maria Gonzales", "1971-02-03", "12 Elm St", "412-55-9981"),
        _p(3, "M. Gonzalez", "1971-03-02", "12 Elm St", "412-55-9981"),
        _p(4, "Ana Ruiz", "1990-01-01", "1 A St", "587-33-1204"),
        _p(5, "Ana Ruis", "1990-01-01", "9 Q Blvd", "587-33-1204"),
        _p(6, "Zed Kane", "1990-01-01", "9 Q Blvd", "587-33-1204"),
        _p(7, "Lee Park", "1985-06-07", "3 Oak Ave", "231-44-7788"),
        _p(8, "Lea Park", "1985-06-07", "88 Pine Rd", "231-44-7788"),
        _p(9, "Rob Diaz", "1985-06-07", "3 Oak Ave", "231-44-7788"),
        _p(10, "Ivy Chen", "1979-11-12", "5 Fir Ln", "354-22-6611"),
        _p(11, "Ivy Chan", "1979-11-12", "5 Fir Ln", "354-22-6611"),
        _p(12, "Sam Hale", "1966-04-09", "7 Ash Ct", "354-22-6611"),
        _p(13, "Sam Hale", "1966-04-09", "7 Ash Ct", "354-22-6611"),
    ]
    dicts = [_row(p) for p in rows]

    eval_status = {}
    for identity in rag_data.resolve_identities(rows, "ssn"):
        for pid in identity.patient_ids:
            eval_status[pid] = identity.status

    for p in rows:
        expected = eval_status[p.id]
        # "unmatched" in the eval means no SSN-mate at all; the serving matcher
        # calls that "none" — there is nothing to disclose or queue either way.
        expected = "none" if expected == "unmatched" else expected
        assert matching.status_for(dicts, p.id) == expected, f"row {p.id}"

    assert matching.candidate_pairs(dicts) == [
        (1, 2), (1, 3), (2, 3),   # the clique
        (10, 11),                 # first disjoint pair
        (12, 13),                 # second disjoint pair
    ]


# ---------------------------------------------------------- the mixed group

def test_mixed_group_emits_one_candidate_pair_and_two_conflicts():
    """One SSN, four rows: 1 and 2 corroborate; 3 and 4 corroborate with
    nobody (including each other). The group is simultaneously a candidate
    duplicate AND two non-mergeable rows, so no single verdict per SSN group
    is correct (W2-SPEC-21).

    Getting this wrong in either direction is a real harm: a whole-group
    "conflict" verdict suppresses the disclosure clinicians opening 1 or 2 are
    owed, and a whole-group "candidate" verdict asserts duplicate status over
    two unrelated humans and queues them for a merge.
    """
    rows = [
        _row(_p(1, "Ana Ruiz", "1990-01-01", "1 A St", "412-55-9981")),
        _row(_p(2, "Ana Ruis", "1990-01-01", "1 A St", "412-55-9981")),
        _row(_p(3, "Zed Kane", "1975-12-25", "77 Z Blvd", "412-55-9981")),
        _row(_p(4, "Bo Frost", "1962-09-30", "5 Q Rd", "412-55-9981")),
    ]
    components = matching.classify_ssn_group(rows)
    assert [(c["patient_ids"], c["status"]) for c in components] == [
        ([1, 2], "candidate"),
        ([3], "conflict"),
        ([4], "conflict"),
    ]
    assert matching.candidate_pairs(rows) == [(1, 2)]
    assert matching.status_for(rows, 1) == "candidate"
    assert matching.status_for(rows, 2) == "candidate"
    assert matching.status_for(rows, 3) == "conflict"
    assert matching.status_for(rows, 4) == "conflict"


# --------------------------------------------------------- the "none" floor

def test_row_without_a_usable_ssn_yields_nothing():
    # Tier 2 (fuzzy name + DOB where the SSN is missing or invalid) is deferred
    # by owner decision, so W2's detection floor is the SSN-corroborated tier:
    # no usable SSN means no candidate, no disclosure, no queue entry
    # (W2-SPEC-20).
    rows = [
        _row(_p(1, "Ana Ruiz", "1990-01-01", "1 A St", "")),
        _row(_p(2, "Ana Ruiz", "1990-01-01", "1 A St", "not-an-ssn")),
        _row(_p(3, "Ana Ruiz", "1990-01-01", "1 A St", "000-00-0000")),
        _row(_p(4, "Ana Ruiz", "1990-01-01", "1 A St", "000-00-0000")),
    ]
    assert matching.classify_ssn_group(rows) == []
    assert matching.candidate_pairs(rows) == []
    for pid in (1, 2, 3, 4):
        assert matching.status_for(rows, pid) == "none"


def test_lone_row_under_its_own_ssn_yields_nothing():
    rows = [_row(_p(1, "Ana Ruiz", "1990-01-01", "1 A St", "412-55-9981"))]
    assert matching.classify_ssn_group(rows) == []
    assert matching.candidate_pairs(rows) == []
    assert matching.status_for(rows, 1) == "none"


def test_status_for_unknown_patient_is_none():
    rows = [_row(_p(1, "Ana Ruiz", "1990-01-01", "1 A St", "412-55-9981"))]
    assert matching.status_for(rows, 999) == "none"


def test_rows_from_different_ssns_never_share_a_component():
    """The callers prefilter by normalized SSN in SQL, but the matcher must not
    depend on that: handed a mixed set it classifies each SSN group
    independently, so a broken prefilter can never weld two SSN groups into one
    candidate pair."""
    rows = [
        _row(_p(1, "Ana Ruiz", "1990-01-01", "1 A St", "412-55-9981")),
        _row(_p(2, "Ana Ruiz", "1990-01-01", "1 A St", "587-33-1204")),
    ]
    assert matching.classify_ssn_group(rows) == []
    assert matching.candidate_pairs(rows) == []
    assert matching.status_for(rows, 1) == "none"


def test_accepts_orm_style_attribute_rows():
    """Callers hand it SQLAlchemy rows, tests hand it dicts — both work, so the
    unit tests exercise the same code path the services do."""
    rows = [
        _p(1, "Ana Ruiz", "1990-01-01", "1 A St", "412-55-9981"),
        _p(2, "Ana Ruis", "1990-01-01", "1 A St", "412-55-9981"),
    ]
    assert matching.candidate_pairs(rows) == [(1, 2)]
    assert matching.status_for(rows, 1) == "candidate"


# ------------------------------------------------------------------- PHI

def test_no_ssn_value_appears_in_any_returned_structure():
    """W2-SPEC-24: the matcher's outputs are ids and enums only. Components,
    pairs, and statuses all flow into log lines and API responses downstream,
    so an SSN surviving into any of them is a leak by construction."""
    ssn = "412-55-9981"
    rows = [
        _row(_p(1, "Ana Ruiz", "1990-01-01", "1 A St", ssn)),
        _row(_p(2, "Ana Ruis", "1990-01-01", "1 A St", ssn)),
    ]
    blob = repr(matching.classify_ssn_group(rows)) + repr(matching.candidate_pairs(rows))
    blob += repr(matching.status_for(rows, 1))
    for value in (ssn, "412559981", "Ana Ruiz", "1990-01-01", "1 A St"):
        assert value not in blob
