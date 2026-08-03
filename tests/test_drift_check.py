"""
Tests for eval/rag/check_drift.py — the CI gate that keeps eval/rag/REPORT.md
honest against db/seed/*.

Why these exist: the gate's failure-prone part is the mask parser, not the
diff. A mask that silently stops matching turns the job green forever, which is
the exact class this repo has been burned by before (a threshold nothing could
reach). So every test here is a discrimination test — each asserts the gate goes
RED on a specific corruption, and the file ends with the green case proving the
red ones are not red for a trivial reason.

The end-to-end cases mutate a COPY of the seed CSVs under tmp_path; the real
db/seed/ is never written to.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import REPO_ROOT, load_module

drift = load_module("eval/rag/check_drift.py", "eval_check_drift")

COMMITTED_REPORT = os.path.join(REPO_ROOT, "eval", "rag", "REPORT.md")


@pytest.fixture(scope="module")
def report_text():
    with open(COMMITTED_REPORT) as f:
        return f.read()


def _mask_exit_code(text, source):
    """Run _mask, returning None when it passes or the SystemExit code."""
    try:
        drift._mask(text, source)
    except SystemExit as e:
        return e.code
    return None


# --- the label guard: a stub-generated report must never satisfy the gate ---


def test_stub_generated_report_is_rejected(report_text):
    """The whole point of not masking the label. A report regenerated the easy
    way scores 1.00 everywhere and contradicts the §4 prose beneath it."""
    stubbed = report_text.replace(
        "Retriever: **local embeddings (all-MiniLM-L6-v2, cached, cosine top-k)**",
        "Retriever: **stub oracle (upper bound: answers each query with its "
        "gold citations)**",
    )
    assert stubbed != report_text, "fixture substitution missed — update this test"
    assert _mask_exit_code(stubbed, drift.COMMITTED_SIDE) == 2


def test_regenerated_side_label_is_not_policed(report_text):
    """The regenerated side IS the stub run, so the same label must pass there."""
    stubbed = report_text.replace(
        "Retriever: **local embeddings (all-MiniLM-L6-v2, cached, cosine top-k)**",
        "Retriever: **stub oracle (upper bound: answers each query with its "
        "gold citations)**",
    )
    assert _mask_exit_code(stubbed, drift.REGENERATED_SIDE) is None


def test_top_k_survives_the_mask(report_text):
    """The label is masked but the top-k on the same line is compared, so a
    report committed at a different --k drifts rather than passing."""
    at_k3 = report_text.replace("top-k = 1.", "top-k = 3.")
    assert at_k3 != report_text
    assert drift._mask(at_k3, drift.REGENERATED_SIDE) != drift._mask(
        report_text, drift.REGENERATED_SIDE
    )


# --- the anchor guard: fail closed, and point at the right remedy ---


@pytest.mark.parametrize(
    "corruption",
    [
        pytest.param(lambda t: t.replace("Retriever: **", "Retriever was: **"),
                     id="retriever-anchor-missing"),
        pytest.param(lambda t: t.replace("**Macro recall ", "**Macro-recall "),
                     id="macro-anchor-missing"),
        pytest.param(lambda t: t.replace(drift.SCORE_HEADER, "| q | e | r | rc | p |"),
                     id="table-anchor-missing"),
        pytest.param(lambda t: t.replace(
            drift.SCORE_HEADER, drift.SCORE_HEADER + "\n" + drift.SCORE_HEADER),
            id="table-anchor-duplicated"),
    ],
)
def test_moved_anchor_fails_closed(report_text, corruption):
    """A restructured report must stop the gate, never widen what it ignores."""
    assert _mask_exit_code(corruption(report_text), drift.REGENERATED_SIDE) == 2


def test_anchor_guard_remedy_depends_on_which_side_broke(report_text, capsys):
    """A committed report in an old shape needs regenerating; a report.py shape
    change needs the mask updated. Same defect class, opposite instructions."""
    broken = report_text.replace("**Macro recall ", "**Macro-recall ")

    assert _mask_exit_code(broken, drift.COMMITTED_SIDE) == 2
    committed_err = capsys.readouterr().err
    assert "regenerate it" in committed_err

    assert _mask_exit_code(broken, drift.REGENERATED_SIDE) == 2
    regenerated_err = capsys.readouterr().err
    assert "Update the mask" in regenerated_err


# --- the mask must not reach outside §4 ---


def test_a_markdown_table_outside_section_4_is_still_compared(report_text):
    """§1's cluster table and §2's gap table are pipe tables too. If the mask
    ever consumed them, a seed change would stop being visible."""
    masked = "\n".join(drift._mask(report_text, drift.REGENERATED_SIDE))
    assert "| 1042 | Maria Gonzalez | 1971-03-02 | self_service |" in masked
    assert "| `ssn` | 3 | 2 |" in masked


def test_score_rows_keep_goldset_cells_and_lose_model_cells(report_text):
    """The mask is per-cell, not per-row: each row's query and expected
    records — goldset.json content, identical on both retriever paths — stay
    comparable, so a goldset edit drifts. Only the model-dependent cells go."""
    masked = "\n".join(drift._mask(report_text, drift.REGENERATED_SIDE))
    assert (
        "| show me Maria Gonzalez's allergies | [1] | <masked: retrieved> | "
        "<masked: recall> | <masked: precision> |"
    ) in masked
    # the committed embed-path values must not survive anywhere
    assert "| 1.00 | 1.00 |" not in masked
    assert "| 0.00 | 0.00 |" not in masked


def test_section_4_prose_survives_the_mask(report_text):
    """Only the numbers are masked. The paragraph explaining them is compared,
    so it cannot silently drift out of agreement with the table above it."""
    masked = "\n".join(drift._mask(report_text, drift.REGENERATED_SIDE))
    assert "faithfully reproduces the fragmentation" in masked
    assert "## 5. Conclusion" in masked


# --- end to end, against a mutated copy of the seed ---


def _run_in_copy(tmp_path, mutate):
    """Copy the eval + seed into tmp_path, mutate, run the check, return the
    completed process."""
    work = tmp_path / "repo"
    (work / "eval").mkdir(parents=True)
    (work / "db").mkdir(parents=True)
    shutil.copytree(os.path.join(REPO_ROOT, "eval", "rag"), str(work / "eval" / "rag"),
                    ignore=shutil.ignore_patterns(".cache", "__pycache__"))
    shutil.copytree(os.path.join(REPO_ROOT, "db", "seed"), str(work / "db" / "seed"))
    mutate(work)
    return subprocess.run(
        [sys.executable, str(work / "eval" / "rag" / "check_drift.py")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )


def test_green_against_the_committed_seed(tmp_path):
    """The control. Without this, every red test above could be red by accident."""
    proc = _run_in_copy(tmp_path, lambda work: None)
    assert proc.returncode == 0, proc.stderr
    assert "REPORT.md matches" in proc.stdout


def test_red_when_a_seed_patient_changes(tmp_path):
    def mutate(work):
        csv = work / "db" / "seed" / "patients.csv"
        csv.write_text(csv.read_text().replace("Maria Gonzales,", "Maria Gonzalez,", 1))

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 1
    assert "is stale vs db/seed" in proc.stderr
    assert "--retriever embed" in proc.stderr


def test_red_when_a_seed_allergy_changes(tmp_path):
    """§2 is the patient-safety section — the reason the report exists."""
    def mutate(work):
        csv = work / "db" / "seed" / "encounters.csv"
        csv.write_text(csv.read_text().replace("penicillin", "sulfa"))

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 1
    assert "is stale vs db/seed" in proc.stderr


# --- goldset.json edits must be observable (codex r2: the wide mask hid them) ---


def _mutate_goldset(work, transform):
    path = work / "db" / "seed" / "goldset.json"
    goldset = json.loads(path.read_text())
    transform(goldset)
    path.write_text(json.dumps(goldset, indent=2))


def test_red_when_a_goldset_query_is_reworded(tmp_path):
    def mutate(work):
        def transform(goldset):
            goldset["cases"][0]["query"] = "list Maria Gonzalez's allergies"
        _mutate_goldset(work, transform)

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 1
    assert "is stale vs db/seed" in proc.stderr


def test_red_when_goldset_cited_records_change(tmp_path):
    def mutate(work):
        def transform(goldset):
            goldset["cases"][0]["cites_records"] = [2]
        _mutate_goldset(work, transform)

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 1
    assert "is stale vs db/seed" in proc.stderr


def test_red_when_a_goldset_case_is_removed(tmp_path):
    """The row count is compared too, not just the surviving cells."""
    def mutate(work):
        def transform(goldset):
            goldset["cases"].pop()
        _mutate_goldset(work, transform)

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 1
    assert "is stale vs db/seed" in proc.stderr
