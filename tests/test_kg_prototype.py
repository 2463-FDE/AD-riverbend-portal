"""
Tests for the w4 knowledge-graph retrieval prototype (eval/kg/).

The prototype is a self-contained sample substrate, not a view onto the
production records tables (w4-D-1): everything here runs on the in-memory
corpus that eval/kg/corpus.py builds, and the self-containment test below is
what keeps that structural rather than advisory.

Pinned test ids (w4 Spec check column): kg-schema-shape · kg-self-contained ·
assemble-full-view · assemble-complete · bounded-retrieval-count ·
bounded-at-scale.
"""
import ast
import dataclasses
import glob
import os
import sys

import pytest
from conftest import REPO_ROOT, load_module

kg_schema = load_module("eval/kg/schema.py", "kg_schema")
# eval/kg modules import their siblings by bare name (the eval/rag idiom). Pin
# the already-loaded module under that name before loading anything that
# imports it, so the node dataclasses have ONE identity across the package —
# two copies of `schema` would make every isinstance/equality check here lie.
sys.modules["schema"] = kg_schema
kg_corpus = load_module("eval/kg/corpus.py", "kg_corpus")
sys.modules["corpus"] = kg_corpus
kg_assemble = load_module("eval/kg/assemble.py", "kg_assemble")

KG_DIR = os.path.join(REPO_ROOT, "eval", "kg")


@pytest.fixture
def store():
    return kg_assemble.GraphStore(kg_corpus.build_corpus())


def _fields(node_type):
    return {f.name for f in dataclasses.fields(node_type)}


# --- kg-schema-shape (w4-SPEC-1) -------------------------------------------


def test_kg_schema_shape():
    """The schema models patient → encounter → provider → record with enough
    fields to assemble one patient's labs and visit summaries."""
    assert set(kg_schema.NODE_TYPES) == {
        kg_schema.Patient,
        kg_schema.Encounter,
        kg_schema.Provider,
        kg_schema.Record,
    }

    edges = {e.name: e for e in kg_schema.EDGES}
    assert (edges["has_encounter"].source, edges["has_encounter"].target) == (
        kg_schema.Patient,
        kg_schema.Encounter,
    )
    assert (edges["seen_by"].source, edges["seen_by"].target) == (
        kg_schema.Encounter,
        kg_schema.Provider,
    )
    assert (edges["produced"].source, edges["produced"].target) == (
        kg_schema.Encounter,
        kg_schema.Record,
    )

    # every edge's foreign key is a real field on the node that carries it —
    # the chain is traversable, not just declared
    for edge in kg_schema.EDGES:
        assert edge.fk_attr in _fields(edge.fk_on), edge.name

    # the two payloads the ask names: visit summaries on the encounter, labs
    # on the record
    assert "summary" in _fields(kg_schema.Encounter)
    assert {"kind", "title", "body"} <= _fields(kg_schema.Record)
    assert kg_schema.LAB_KIND in kg_schema.RECORD_KINDS


# --- kg-self-contained (w4-SPEC-2) -----------------------------------------

FORBIDDEN_SOURCE = "import os\nimport sqlalchemy\nfrom services.records import app\n"


def _top_level_imports(source):
    """Top-level module names imported by `source`, by AST — a grep would miss
    a re-formatted import and match one inside a string."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def _foreign_imports(source):
    """Imports that are neither stdlib nor a sibling eval/kg module."""
    siblings = {
        os.path.splitext(os.path.basename(p))[0]
        for p in glob.glob(os.path.join(KG_DIR, "*.py"))
    }
    allowed = sys.stdlib_module_names | siblings
    return {n for n in _top_level_imports(source) if n not in allowed}


def test_kg_self_contained():
    """No eval/kg module reaches a DB driver, an HTTP client, or a service —
    the corpus is the only source of nodes (w4-D-1, w4-D-11)."""
    modules = sorted(glob.glob(os.path.join(KG_DIR, "*.py")))
    assert modules, "no eval/kg modules found to scan"

    for path in modules:
        with open(path, encoding="utf-8") as fh:
            foreign = _foreign_imports(fh.read())
        assert foreign == set(), f"{os.path.relpath(path, REPO_ROOT)}: {sorted(foreign)}"


def test_kg_self_contained_positive_control():
    """The scanner reddens on a forbidden import — otherwise the test above
    passes because the check is broken, not because the tree is clean."""
    assert _foreign_imports(FORBIDDEN_SOURCE) == {"sqlalchemy", "services"}


# --- assemble-full-view (w4-SPEC-3) ----------------------------------------


def test_assemble_full_view(store):
    """One authorized call returns the patient's labs and visit summaries as a
    single assembled result."""
    pid = kg_corpus.FIXTURE_PATIENT_ID
    view = kg_assemble.assemble_patient_view(
        store, kg_assemble.Principal.for_patient(pid), pid
    )

    assert view.patient_id == pid
    assert len(view.encounters) == kg_corpus.FIXTURE_ENCOUNTER_COUNT

    # every assembled encounter carries its visit summary and its provider
    for assembled in view.encounters:
        assert assembled.encounter.summary
        assert isinstance(assembled.provider, kg_schema.Provider)
        assert assembled.provider.id == assembled.encounter.provider_id

    assert len(view.visit_summaries()) == len(view.encounters)
    labs = view.labs()
    assert labs, "fixture patient has no lab records to assemble"
    assert all(r.kind == kg_schema.LAB_KIND for r in labs)


# --- assemble-complete (w4-SPEC-4) -----------------------------------------


def test_assemble_complete(store):
    """No encounter of the patient is dropped, and nothing belonging to
    another patient is picked up."""
    pid = kg_corpus.FIXTURE_PATIENT_ID
    corpus = kg_corpus.build_corpus()
    expected_encounters = {e.id for e in corpus.encounters if e.patient_id == pid}
    expected_records = {r.id for r in corpus.records if r.patient_id == pid}

    view = kg_assemble.assemble_patient_view(
        store, kg_assemble.Principal.for_patient(pid), pid
    )

    assert {a.encounter.id for a in view.encounters} == expected_encounters
    assert {r.id for a in view.encounters for r in a.records} == expected_records
    assert all(a.encounter.patient_id == pid for a in view.encounters)
    assert all(r.patient_id == pid for a in view.encounters for r in a.records)


# --- batch read is a set read (impl-gate r2 finding 1; no Spec row) --------


def test_records_for_encounters_dedupes(store):
    """A repeated encounter id yields its records once, in first-seen order:
    the batch accessor reads a set of encounters, it does not concatenate the
    id list it is handed."""
    pid = kg_corpus.FIXTURE_PATIENT_ID
    enc_ids = [e.id for e in store.encounters_for_patient(pid)][:3]
    assert len(enc_ids) == 3, "fixture patient has fewer than three encounters"

    once = store.records_for_encounters(enc_ids)
    assert once, "fixture encounters carry no records"
    repeated = store.records_for_encounters(enc_ids + enc_ids)

    assert [r.id for r in repeated] == [r.id for r in once]


# --- unmodelled provider (impl-gate r3 finding 2; no Spec row) --------------


def test_assemble_unmodelled_provider_raises_typed_error():
    """An encounter whose provider the corpus does not model is a corpus
    defect, and assembly says so — it does not KeyError out of the middle of
    the merge. The accessor drops ids it cannot resolve (it always has), so
    the merge is where the gap becomes visible and where it gets named."""
    corpus = kg_corpus.build_corpus()
    pid = kg_corpus.FIXTURE_PATIENT_ID
    expected = {e.provider_id for e in corpus.encounters if e.patient_id == pid}
    assert expected, "fixture patient has no encounters"

    store = kg_assemble.GraphStore(dataclasses.replace(corpus, providers=()))

    with pytest.raises(kg_assemble.IncompleteCorpus) as excinfo:
        kg_assemble.assemble_patient_view(
            store, kg_assemble.Principal.for_patient(pid), pid
        )

    assert excinfo.value.provider_id in expected


# --- bounded-retrieval-count (w4-SPEC-15) ----------------------------------

EXPECTED_RETRIEVALS = 3  # encounters-for-patient · records-for-encounters · providers-by-id


def _retrievals_to_assemble(store, patient_id):
    store.reset_retrievals()
    kg_assemble.assemble_patient_view(
        store, kg_assemble.Principal.for_patient(patient_id), patient_id
    )
    return store.retrievals


def test_bounded_retrieval_count(store):
    """The retrieval count does not move with the encounter count: a
    2-encounter chart and a 53-encounter chart cost the same three reads."""
    small = _retrievals_to_assemble(store, kg_corpus.SIBLING_PATIENT_ID)
    large = _retrievals_to_assemble(store, kg_corpus.FIXTURE_PATIENT_ID)

    assert kg_corpus.SIBLING_ENCOUNTER_COUNT == 2
    assert small == large == EXPECTED_RETRIEVALS


# --- bounded-at-scale (w4-SPEC-16) -----------------------------------------

# The query log the owner handed over: one records query per encounter, 37 for
# the captured chart (docs/research/w4-findings.md, N+1 note).
CAPTURED_PER_ENCOUNTER_QUERIES = 37


def test_bounded_at_scale(store):
    """On a 50+-encounter chart the assembly stays at three reads — not the
    one-per-encounter pattern it replaces."""
    encounters = kg_corpus.FIXTURE_ENCOUNTER_COUNT
    assert encounters >= 50, "fixture is no longer the 50+-encounter chart"

    count = _retrievals_to_assemble(store, kg_corpus.FIXTURE_PATIENT_ID)

    assert count == EXPECTED_RETRIEVALS
    assert count < CAPTURED_PER_ENCOUNTER_QUERIES
    # what the production per-encounter pattern would have cost on this chart
    assert count < encounters
