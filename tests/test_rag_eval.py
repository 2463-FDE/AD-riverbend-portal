"""
Tests for the RAG retrieval eval harness (eval/rag/, RIV-160).

Torch-free on purpose: the graded logic (identity resolution, duplicate rate,
fragment coverage, recall/precision) and the StubRetriever run on the standard
library. The EmbeddingRetriever's heavy dependencies are never imported here.

These are characterization tests against the real fixtures in db/seed/: they
pin the fragmentation the harness must surface (three charts for one Maria,
penicillin visible only on chart 1330), not a future fixed state.
"""
import hashlib
import json
import math
import os
import re
import sys
import types

import pytest
from conftest import REPO_ROOT, load_module

rag_data = load_module("eval/rag/data.py", "rag_data")
rag_metrics = load_module("eval/rag/metrics.py", "rag_metrics")
rag_retriever = load_module("eval/rag/retriever.py", "rag_retriever")
rag_report = load_module("eval/rag/report.py", "rag_report")

SEED = os.path.join(REPO_ROOT, "db", "seed")
PATIENTS = rag_data.load_patients(os.path.join(SEED, "patients.csv"))
ENCOUNTERS = rag_data.load_encounters(os.path.join(SEED, "encounters.csv"))
GOLDSET = rag_data.load_goldset(os.path.join(SEED, "goldset.json"))

MARIA_IDS = [1042, 1330, 1588]


# ---------------------------------------------------------------- parsing

def test_normalize_ssn_strips_formatting():
    assert rag_data.normalize_ssn("412-55-9981") == "412559981"
    assert rag_data.normalize_ssn("412 55 9981") == "412559981"
    assert rag_data.normalize_ssn("") == ""


def test_is_valid_ssn_rejects_missing_malformed_and_placeholders():
    assert rag_data.is_valid_ssn("412-55-9981")
    assert rag_data.is_valid_ssn("412559981")
    # Missing / malformed
    assert not rag_data.is_valid_ssn("")
    assert not rag_data.is_valid_ssn(None)
    assert not rag_data.is_valid_ssn("not-an-ssn")
    assert not rag_data.is_valid_ssn("12345")  # too short
    assert not rag_data.is_valid_ssn("4125599810")  # too long
    # Structurally never-issued (SSA rules) — the classic shared placeholders
    assert not rag_data.is_valid_ssn("000-00-0000")
    assert not rag_data.is_valid_ssn("000-55-9981")  # area 000
    assert not rag_data.is_valid_ssn("666-55-9981")  # area 666
    assert not rag_data.is_valid_ssn("900-55-9981")  # area 9xx
    assert not rag_data.is_valid_ssn("412-00-9981")  # group 00
    assert not rag_data.is_valid_ssn("412-55-0000")  # serial 0000


def test_none_known_is_not_an_allergy():
    # 1601's allergies cell reads "none known" — an assessed-empty sentinel,
    # not an allergen. It must not survive parsing as a phantom allergy.
    assert rag_data.parse_clinical_list("none known") == frozenset()
    khan = [e for e in ENCOUNTERS if e.patient_id == 1601]
    assert all(e.allergies == frozenset() for e in khan)


def test_encounter_record_ids_match_goldset_numbering():
    # cites_records in goldset.json are 1-based encounters.csv row indexes.
    assert [e.record_id for e in ENCOUNTERS] == [1, 2, 3, 4, 5]
    assert ENCOUNTERS[1].patient_id == 1330
    assert "penicillin" in ENCOUNTERS[1].allergies


# --------------------------------------------------- identity resolution

def test_match_key_none_mirrors_current_intake():
    identities = rag_data.resolve_identities(PATIENTS, "none")
    assert len(identities) == 5  # every row its own "human" — intake today


def test_match_key_ssn_collapses_all_three_marias_as_candidates():
    # The three Maria rows share an SSN AND corroborating demographics
    # (similar names, same/transposed DOB, identical address) — they cluster,
    # but as a *candidate* match for human review, never a resolved identity.
    identities = rag_data.resolve_identities(PATIENTS, "ssn")
    assert len(identities) == 3
    clusters = {tuple(i.patient_ids): i.status for i in identities}
    assert clusters[tuple(MARIA_IDS)] == "candidate"


def test_invalid_ssns_never_merge_patients():
    # Adversarial input the harness will meet in real intake data (ADR 0005:
    # self-service SSN is optional and mistyped): blank, non-numeric, and a
    # shared placeholder. A common junk value must not become a shared match
    # key — otherwise unrelated patients merge into one fake human and the
    # duplicate rate the report headlines is fabricated.
    rows = [
        rag_data.Patient(id=1, name="Ana Ruiz", dob="1990-01-01",
                         ssn="", address="1 A St", created_via="self_service"),
        rag_data.Patient(id=2, name="Ben Cole", dob="1991-02-02",
                         ssn="", address="2 B St", created_via="self_service"),
        rag_data.Patient(id=3, name="Cy Dunn", dob="1992-03-03",
                         ssn="not-an-ssn", address="3 C St", created_via="self_service"),
        rag_data.Patient(id=4, name="Dee Eng", dob="1993-04-04",
                         ssn="000-00-0000", address="4 D St", created_via="self_service"),
        rag_data.Patient(id=5, name="Ed Fox", dob="1994-05-05",
                         ssn="000-00-0000", address="5 E St", created_via="self_service"),
    ]
    identities = rag_data.resolve_identities(rows, "ssn")
    assert len(identities) == 5  # every row its own identity — nothing merged
    assert {tuple(i.patient_ids) for i in identities} == {(1,), (2,), (3,), (4,), (5,)}
    dup = rag_metrics.candidate_duplicate_rate(rows, identities)
    assert dup.candidate_duplicate_rows == 0
    assert dup.rate == 0.0


def test_shared_valid_ssn_with_conflicting_demographics_never_merges():
    # Codex round-2 finding: a structurally VALID SSN can still be shared,
    # mistyped, or fraudulent (ADR 0005 says so itself). Two unrelated people
    # who differ on name, DOB, and address must not become one "human" just
    # because one SSN appears on both rows — that fabricates the headline
    # rate and, downstream, a merge that cross-contaminates two real charts.
    rows = [
        rag_data.Patient(id=1, name="Ana Ruiz", dob="1990-01-01",
                         ssn="412-55-9981", address="1 A St", created_via="self_service"),
        rag_data.Patient(id=2, name="Ben Cole", dob="1962-09-30",
                         ssn="412-55-9981", address="77 Z Blvd", created_via="self_service"),
    ]
    identities = rag_data.resolve_identities(rows, "ssn")
    assert {tuple(i.patient_ids) for i in identities} == {(1,), (2,)}
    assert all(i.status == "conflict" for i in identities)
    dup = rag_metrics.candidate_duplicate_rate(rows, identities)
    assert dup.candidate_duplicate_rows == 0
    assert dup.rate == 0.0


def test_shared_ssn_plus_address_alone_is_not_corroboration():
    # Family members can share an address and (via fraud or data entry) an
    # SSN while being two different people. One agreeing signal out of three
    # (name, DOB, address) must not merge them.
    rows = [
        rag_data.Patient(id=1, name="Ana Ruiz", dob="1990-01-01",
                         ssn="412-55-9981", address="1 A St", created_via="self_service"),
        rag_data.Patient(id=2, name="Ben Cole", dob="1962-09-30",
                         ssn="412-55-9981", address="1 A St", created_via="self_service"),
    ]
    identities = rag_data.resolve_identities(rows, "ssn")
    assert {tuple(i.patient_ids) for i in identities} == {(1,), (2,)}
    assert all(i.status == "conflict" for i in identities)


def test_bridge_rows_never_form_one_candidate_cluster():
    # Codex round-3 finding: connected-component clustering lets a bridge row
    # weld two pairwise-conflicting people into one candidate. A corroborates
    # B (name + DOB), B corroborates C (DOB + address), but A and C conflict
    # (DOB only — one signal). Corroboration is a similarity relation, not an
    # equivalence: it does not chain. A cluster containing a conflicting pair
    # must never ship as a candidate — it is ambiguous, for human review,
    # and contributes nothing to the candidate duplicate rate.
    rows = [
        rag_data.Patient(id=1, name="Ana Ruiz", dob="1990-01-01",
                         ssn="412-55-9981", address="1 A St", created_via="self_service"),
        rag_data.Patient(id=2, name="Ana Ruis", dob="1990-01-01",
                         ssn="412-55-9981", address="9 Q Blvd", created_via="self_service"),
        rag_data.Patient(id=3, name="Zed Kane", dob="1990-01-01",
                         ssn="412-55-9981", address="9 Q Blvd", created_via="self_service"),
    ]
    identities = rag_data.resolve_identities(rows, "ssn")
    assert {tuple(i.patient_ids) for i in identities} == {(1,), (2,), (3,)}
    assert all(i.status == "ambiguous" for i in identities)
    dup = rag_metrics.candidate_duplicate_rate(rows, identities)
    assert dup.candidate_duplicate_rows == 0
    assert dup.rate == 0.0


def test_every_candidate_cluster_is_pairwise_corroborated():
    # The invariant the round-2 fix claimed but did not enforce: no emitted
    # candidate cluster may contain ANY pair of rows whose demographics fail
    # to corroborate. Checked over a topology zoo — a true clique, a bridge
    # chain, a star (hub corroborates all spokes, spokes mutually conflict),
    # and two disjoint corroborating pairs under one SSN — so the assertion
    # covers the class of counterexamples, not one anecdote.
    def p(pid, name, dob, addr, ssn):
        return rag_data.Patient(id=pid, name=name, dob=dob, ssn=ssn,
                                address=addr, created_via="self_service")

    rows = [
        # clique of three (the Maria shape) — must still cluster
        p(1, "Maria Gonzalez", "1971-02-03", "12 Elm St", "412-55-9981"),
        p(2, "Maria Gonzales", "1971-02-03", "12 Elm St", "412-55-9981"),
        p(3, "M. Gonzalez", "1971-03-02", "12 Elm St", "412-55-9981"),
        # bridge chain: 4~5 (name+DOB), 5~6 (DOB+address), 4/6 conflict
        p(4, "Ana Ruiz", "1990-01-01", "1 A St", "587-33-1204"),
        p(5, "Ana Ruis", "1990-01-01", "9 Q Blvd", "587-33-1204"),
        p(6, "Zed Kane", "1990-01-01", "9 Q Blvd", "587-33-1204"),
        # star: hub 7 corroborates 8 (name+DOB) and 9 (DOB+address);
        # 8 and 9 conflict with each other (DOB only)
        p(7, "Lee Park", "1985-06-07", "3 Oak Ave", "231-44-7788"),
        p(8, "Lea Park", "1985-06-07", "88 Pine Rd", "231-44-7788"),
        p(9, "Rob Diaz", "1985-06-07", "3 Oak Ave", "231-44-7788"),
        # two disjoint corroborating pairs under one SSN
        p(10, "Ivy Chen", "1979-11-12", "5 Fir Ln", "354-22-6611"),
        p(11, "Ivy Chan", "1979-11-12", "5 Fir Ln", "354-22-6611"),
        p(12, "Sam Hale", "1966-04-09", "7 Ash Ct", "354-22-6611"),
        p(13, "Sam Hale", "1966-04-09", "7 Ash Ct", "354-22-6611"),
    ]
    by_id = {r.id: r for r in rows}
    identities = rag_data.resolve_identities(rows, "ssn")

    # The universal invariant: every pair inside every multi-row identity
    # corroborates. No topology may smuggle a conflicting pair past it.
    for identity in identities:
        members = [by_id[pid] for pid in identity.patient_ids]
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                assert rag_data._demographics_corroborate(a, b), (
                    f"identity {identity.patient_ids} contains "
                    f"non-corroborating pair ({a.id}, {b.id})"
                )
        assert identity.status in {"unmatched", "candidate", "conflict", "ambiguous"}

    clusters = {tuple(i.patient_ids): i.status for i in identities}
    assert clusters[(1, 2, 3)] == "candidate"          # clique survives intact
    assert clusters[(10, 11)] == "candidate"           # disjoint pairs both
    assert clusters[(12, 13)] == "candidate"           #   cluster separately
    for pid in (4, 5, 6, 7, 8, 9):                     # chain + star: per-row
        assert clusters[(pid,)] == "ambiguous"

    # Ambiguous rows must not inflate the headline rate: only the clique
    # (2 extra rows) and the two pairs (1 extra row each) count.
    dup = rag_metrics.candidate_duplicate_rate(rows, identities)
    assert dup.candidate_duplicate_rows == 4


def test_mistyped_ssn_keeps_same_person_split_known_limitation():
    # The mistype direction: the SAME person registered twice with one digit
    # of the SSN wrong stays two identities under exact-SSN grouping. The
    # harness must not silently paper over this — it is the documented reason
    # ADR 0005 tier 2 adds a fuzzy name+DOB fallback at intake.
    rows = [
        rag_data.Patient(id=1, name="Ana Ruiz", dob="1990-01-01",
                         ssn="412-55-9981", address="1 A St", created_via="self_service"),
        rag_data.Patient(id=2, name="Ana Ruiz", dob="1990-01-01",
                         ssn="412-55-9982", address="1 A St", created_via="self_service"),
    ]
    identities = rag_data.resolve_identities(rows, "ssn")
    assert {tuple(i.patient_ids) for i in identities} == {(1,), (2,)}
    assert all(i.status == "unmatched" for i in identities)


def test_valid_ssns_still_merge_alongside_invalid_rows():
    # The guard must not break real matching: two rows sharing a valid SSN
    # still collapse while the blank-SSN row stays unmatched.
    rows = [
        rag_data.Patient(id=1, name="Ana Ruiz", dob="1990-01-01",
                         ssn="412-55-9981", address="1 A St", created_via="self_service"),
        rag_data.Patient(id=2, name="Ana Ruis", dob="1990-01-01",
                         ssn="412 55 9981", address="1 A St", created_via="self_service"),
        rag_data.Patient(id=3, name="Ben Cole", dob="1991-02-02",
                         ssn="", address="2 B St", created_via="self_service"),
    ]
    identities = rag_data.resolve_identities(rows, "ssn")
    assert {tuple(i.patient_ids) for i in identities} == {(1, 2), (3,)}


def test_match_key_name_dob_catches_zero_duplicates():
    # Spelling drift (Gonzalez/Gonzales), an initialized name (M. Gonzalez),
    # and a transposed DOB each defeat exact name+dob matching — the concrete
    # reason ADR 0005 anchors on SSN.
    identities = rag_data.resolve_identities(PATIENTS, "name_dob")
    assert len(identities) == 5


# ----------------------------------------------------------------- metrics

def test_candidate_duplicate_rate_is_40_percent():
    identities = rag_data.resolve_identities(PATIENTS, "ssn")
    dup = rag_metrics.candidate_duplicate_rate(PATIENTS, identities)
    assert dup.total_rows == 5
    assert dup.candidate_identities == 3
    assert dup.candidate_duplicate_rows == 2
    assert dup.rate == 0.4


def test_goldset_expected_chart_is_allergy_blind():
    # The harm: gold case 1 sends the clinician to chart 1042 ("No known
    # allergies on file") while the same person's penicillin allergy is
    # recorded only under chart 1330.
    gap = rag_metrics.fragment_coverage_gap(MARIA_IDS, ENCOUNTERS, chart_id=1042)
    assert gap.union_allergies == frozenset({"penicillin"})
    assert gap.chart_allergies == frozenset()
    assert gap.missed_allergies == frozenset({"penicillin"})
    assert gap.union_medications == frozenset({"lisinopril", "amoxicillin"})
    assert not gap.is_complete


def test_only_chart_1330_sees_the_penicillin_allergy():
    complete = [
        chart_id
        for chart_id in MARIA_IDS
        if not rag_metrics.fragment_coverage_gap(
            MARIA_IDS, ENCOUNTERS, chart_id
        ).missed_allergies
    ]
    assert complete == [1330]


# --------------------------------------------------------------- retrieval

def test_perfect_stub_scores_full_marks_on_goldset():
    # The foil: an oracle retriever passes the contractor's gold-set with
    # recall/precision 1.0 while the underlying record stays fragmented.
    stub = rag_retriever.StubRetriever.perfect_for(GOLDSET)
    retrieved = {c.query: stub.retrieve(c.query, k=1) for c in GOLDSET}
    scores = rag_metrics.retrieval_scores(GOLDSET, retrieved)
    assert scores.macro_recall == 1.0
    assert scores.macro_precision == 1.0


def test_retrieval_scores_penalize_misses():
    wrong = {c.query: [99] for c in GOLDSET}  # record id cited by no case
    scores = rag_metrics.retrieval_scores(GOLDSET, wrong)
    assert scores.macro_recall == 0.0
    assert scores.macro_precision == 0.0


# ------------------------------------------- embedding retriever (faked)
# The real model needs torch; these tests exercise EmbeddingRetriever's own
# logic (cache create/reuse, corpus-hash keying, cosine ranking) by injecting
# a fake numpy + sentence_transformers into sys.modules. The fake embedding
# is a stable bag-of-words hash, so ranking is deterministic.

class _FakeMatrix(list):
    """List of row vectors supporting `matrix @ vector` like an ndarray."""

    def __matmul__(self, vec):
        return [sum(a * b for a, b in zip(row, vec)) for row in self]


def _fake_vec(text):
    dims = [0.0] * 64
    for word in re.findall(r"\w+", text.lower()):
        d = int(hashlib.md5(word.encode()).hexdigest(), 16) % 64
        dims[d] += 1.0
    norm = math.sqrt(sum(x * x for x in dims)) or 1.0
    return [x / norm for x in dims]


def _install_fake_embedding_stack(monkeypatch):
    """Returns a log of encode batch sizes ([3, 1] = corpus then one query)."""
    encode_log = []

    class FakeSentenceTransformer:
        def __init__(self, model_name):
            self.model_name = model_name

        def encode(self, texts, normalize_embeddings=True):
            encode_log.append(len(texts))
            return _FakeMatrix(_fake_vec(t) for t in texts)

    fake_st = types.ModuleType("sentence_transformers")
    fake_st.SentenceTransformer = FakeSentenceTransformer

    fake_np = types.ModuleType("numpy")

    def _save(path, arr):
        with open(path, "w") as f:
            json.dump([list(row) for row in arr], f)

    def _load(path):
        with open(path) as f:
            return _FakeMatrix(json.load(f))

    fake_np.save = _save
    fake_np.load = _load

    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st)
    monkeypatch.setitem(sys.modules, "numpy", fake_np)
    return encode_log


FAKE_CORPUS = {
    1: "sinus infection penicillin allergy amoxicillin",
    2: "annual physical lisinopril unremarkable",
    3: "cbc lab panel normal limits",
}


def test_embedding_cache_created_then_reused_across_instances(tmp_path, monkeypatch):
    encode_log = _install_fake_embedding_stack(monkeypatch)
    cache_dir = str(tmp_path)

    first = rag_retriever.EmbeddingRetriever(FAKE_CORPUS, cache_dir=cache_dir)
    first.retrieve("penicillin", k=1)
    # one corpus batch (3 docs) + one query batch
    assert encode_log == [3, 1]
    cached = sorted(os.listdir(cache_dir))
    assert [os.path.splitext(f)[1] for f in cached] == [".json", ".npy"]

    # A fresh instance (fresh process, in real life) must reuse the cache:
    # only the query gets encoded, never the corpus again.
    second = rag_retriever.EmbeddingRetriever(FAKE_CORPUS, cache_dir=cache_dir)
    assert second.retrieve("lab panel", k=1) == [3]
    assert encode_log == [3, 1, 1]


def test_embedding_ranks_matching_document_first(tmp_path, monkeypatch):
    _install_fake_embedding_stack(monkeypatch)
    r = rag_retriever.EmbeddingRetriever(FAKE_CORPUS, cache_dir=str(tmp_path))
    assert r.retrieve("penicillin allergy", k=1) == [1]
    assert r.retrieve("lisinopril physical", k=1) == [2]
    assert r.retrieve("cbc lab", k=3)[0] == 3


def test_corpus_hash_keys_on_content_and_model():
    base = rag_retriever.EmbeddingRetriever(FAKE_CORPUS, cache_dir="unused")
    same = rag_retriever.EmbeddingRetriever(dict(FAKE_CORPUS), cache_dir="elsewhere")
    changed = rag_retriever.EmbeddingRetriever(
        {**FAKE_CORPUS, 3: "different text"}, cache_dir="unused"
    )
    other_model = rag_retriever.EmbeddingRetriever(
        FAKE_CORPUS, cache_dir="unused", model_name="some-other-model"
    )
    assert base._corpus_hash() == same._corpus_hash()
    assert base._corpus_hash() != changed._corpus_hash()
    assert base._corpus_hash() != other_model._corpus_hash()


def test_missing_embedding_deps_give_actionable_error(tmp_path, monkeypatch):
    # sys.modules[name] = None makes `import name` raise ImportError even
    # when the package is installed.
    monkeypatch.setitem(sys.modules, "numpy", None)
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    r = rag_retriever.EmbeddingRetriever(FAKE_CORPUS, cache_dir=str(tmp_path))
    with pytest.raises(RuntimeError, match="requirements.txt"):
        r.retrieve("anything", k=1)


# ------------------------------------------------------------------ report

def _render_full_report():
    identities_by_key = {
        key: rag_data.resolve_identities(PATIENTS, key)
        for key in ("none", "name_dob", "ssn")
    }
    dup = rag_metrics.candidate_duplicate_rate(PATIENTS, identities_by_key["ssn"])
    gaps = [
        rag_metrics.fragment_coverage_gap(MARIA_IDS, ENCOUNTERS, chart_id)
        for chart_id in MARIA_IDS
    ]
    stub = rag_retriever.StubRetriever.perfect_for(GOLDSET)
    retrieved = {c.query: stub.retrieve(c.query, k=1) for c in GOLDSET}
    scores = rag_metrics.retrieval_scores(GOLDSET, retrieved)
    return rag_report.render_report(
        PATIENTS, identities_by_key, dup, gaps, scores, "stub oracle", k=1
    )


def test_report_leads_with_fragmentation_not_retrieval():
    md = _render_full_report()
    assert md.index("multiple charts") < md.index("Retrieval scores")
    assert md.index("penicillin") < md.index("Retrieval scores")


def test_report_names_the_harm_and_the_root_cause():
    md = _render_full_report()
    dup = rag_metrics.candidate_duplicate_rate(
        PATIENTS, rag_data.resolve_identities(PATIENTS, "ssn")
    )
    assert f"{dup.rate:.0%} candidate duplicate rate" in md  # computed, not hardcoded
    assert "penicillin" in md
    assert "match_key: none" in md
    assert "0005" in md  # points at the ADR


def test_report_calls_clusters_candidates_not_resolved_facts():
    # Round-2 language finding: a reader must not mistake a guess for a fact.
    # The report may only speak of candidate matches pending review — never
    # of "distinct humans" resolved by the match key.
    md = _render_full_report()
    assert "candidate identities" in md
    assert "never auto-merge" in md
    assert "distinct humans" not in md
    assert "non-mergeable" in md  # the conflict rule is stated even when empty
    assert "ambiguous" in md  # ...and so is the bridge-row rule (round 3)


def test_report_lists_ambiguous_rows_in_their_own_section():
    # The report's ambiguous branch must actually render when bridged rows
    # exist — the seed fixture has none, so without this test the whole
    # section is dead code under green tests.
    rows = [
        rag_data.Patient(id=1, name="Ana Ruiz", dob="1990-01-01",
                         ssn="412-55-9981", address="1 A St", created_via="self_service"),
        rag_data.Patient(id=2, name="Ana Ruis", dob="1990-01-01",
                         ssn="412-55-9981", address="9 Q Blvd", created_via="self_service"),
        rag_data.Patient(id=3, name="Zed Kane", dob="1990-01-01",
                         ssn="412-55-9981", address="9 Q Blvd", created_via="self_service"),
    ]
    identities_by_key = {
        key: rag_data.resolve_identities(rows, key)
        for key in ("none", "name_dob", "ssn")
    }
    dup = rag_metrics.candidate_duplicate_rate(rows, identities_by_key["ssn"])
    scores = rag_metrics.retrieval_scores([], {})
    md = rag_report.render_report(
        rows, identities_by_key, dup, [], scores, "stub oracle", k=1
    )
    assert "bridge row" in md
    assert "flagged **ambiguous**" in md
    # every bridged row is listed in the ambiguous table
    for name in ("Ana Ruiz", "Ana Ruis", "Zed Kane"):
        assert name in md
    # and none of them appears as a candidate duplicate cluster
    assert "Candidate duplicate cluster" not in md
