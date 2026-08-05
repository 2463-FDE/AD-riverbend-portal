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
import hashlib
import json
import os
import re
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


def _copy_eval_and_seed(tmp_path):
    """Copy the eval + seed trees into tmp_path/repo; return that root."""
    work = tmp_path / "repo"
    (work / "eval").mkdir(parents=True)
    (work / "db").mkdir(parents=True)
    shutil.copytree(os.path.join(REPO_ROOT, "eval", "rag"), str(work / "eval" / "rag"),
                    ignore=shutil.ignore_patterns(".cache", "__pycache__"))
    shutil.copytree(os.path.join(REPO_ROOT, "db", "seed"), str(work / "db" / "seed"))
    return work


def _run_in_copy(tmp_path, mutate, argv=()):
    """Copy the eval + seed into tmp_path, mutate, run the check, return the
    completed process."""
    work = _copy_eval_and_seed(tmp_path)
    mutate(work)
    return subprocess.run(
        [sys.executable, str(work / "eval" / "rag" / "check_drift.py")] + list(argv),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )


def _regen_seed(work):
    """Rerun the generator into the copy's seed.sql — the `make seed-gen` step
    an operator runs after editing a fixture CSV. Without it, a CSV edit is
    caught earlier by the seed.sql check (the generator reads the CSVs), and
    the report-diff layer these tests pin would never be reached."""
    with open(str(work / "db" / "seed" / "seed.sql"), "wb") as out:
        subprocess.run(
            [sys.executable, str(work / "db" / "seed" / "generate_seed.py")],
            stdout=out, check=True,
        )


def _inputs_fingerprint(work):
    """The copy's current-input fingerprint. Mirrors
    check_drift.corpus_fingerprint's scheme; if that scheme changes, the
    tests using this fail on the corpus layer instead of their own — noisy
    red, not silent green."""
    h = hashlib.sha256()
    for name in ("patients.csv", "encounters.csv", "goldset.json"):
        with open(str(work / "db" / "seed" / name), "rb") as f:
            h.update(b"\x00" + name.encode("utf-8") + b"\x00")
            h.update(f.read())
    return h.hexdigest()


def _forge_fingerprint(work):
    """HAND-FORGE the copy's corpus.sha256 to match its current inputs — the
    `echo <hash> > corpus.sha256` adversary, since codex r7 deleted the last
    tool that could do this (`--write-fingerprint`). The report-diff tests
    below call this so their input edit gets past the fingerprint layer (which
    fires first) and the layer each test pins is the one that goes red — which
    also proves renderable-field drift stays caught even against a forged
    sidecar."""
    with open(str(work / "eval" / "rag" / "corpus.sha256"), "w") as f:
        f.write(_inputs_fingerprint(work) + "\n")


def test_green_against_the_committed_seed(tmp_path):
    """The control. Without this, every red test above could be red by accident."""
    proc = _run_in_copy(tmp_path, lambda work: None)
    assert proc.returncode == 0, proc.stderr
    assert "REPORT.md matches" in proc.stdout


def test_red_when_a_seed_patient_changes(tmp_path):
    def mutate(work):
        csv = work / "db" / "seed" / "patients.csv"
        csv.write_text(csv.read_text().replace("Maria Gonzales,", "Maria Gonzalez,", 1))
        _regen_seed(work)
        _forge_fingerprint(work)

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 1
    assert "is stale vs db/seed" in proc.stderr
    assert "--retriever embed" in proc.stderr


def test_red_when_a_seed_allergy_changes(tmp_path):
    """§2 is the patient-safety section — the reason the report exists."""
    def mutate(work):
        csv = work / "db" / "seed" / "encounters.csv"
        csv.write_text(csv.read_text().replace("penicillin", "sulfa"))
        _regen_seed(work)
        _forge_fingerprint(work)

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
        _forge_fingerprint(work)

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 1
    assert "is stale vs db/seed" in proc.stderr


def test_red_when_goldset_cited_records_change(tmp_path):
    def mutate(work):
        def transform(goldset):
            goldset["cases"][0]["cites_records"] = [2]
        _mutate_goldset(work, transform)
        _forge_fingerprint(work)

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 1
    assert "is stale vs db/seed" in proc.stderr


def test_red_when_a_goldset_case_is_removed(tmp_path):
    """The row count is compared too, not just the surviving cells."""
    def mutate(work):
        def transform(goldset):
            goldset["cases"].pop()
        _mutate_goldset(work, transform)
        _forge_fingerprint(work)

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 1
    assert "is stale vs db/seed" in proc.stderr


# --- seed.sql must match its generator (codex r3: the file Postgres loads) ---


def test_red_when_seed_sql_is_hand_edited(tmp_path):
    """A hand-edit to seed.sql changes what the running system demonstrates
    without touching anything the report reads — the gate must go red on the
    seed check, not stay green on the report diff. The quoted needle anchors
    the mutation to Maria's 1330 encounter INSERT (the clinical row this test
    claims to pin), not the header comment that also mentions penicillin."""
    def mutate(work):
        sql = work / "db" / "seed" / "seed.sql"
        mutated = sql.read_text().replace("'penicillin'", "'sulfa'", 1)
        assert mutated != sql.read_text(), "needle missing — update this test"
        sql.write_text(mutated)

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 1
    assert "seed.sql does not match db/seed/generate_seed.py" in proc.stderr
    assert "make seed-gen" in proc.stderr


def test_seed_drift_message_never_instructs_truncating_redirect(tmp_path):
    """The remediation must say `make seed-gen` and nothing else: the direct
    `python3 db/seed/generate_seed.py > db/seed/seed.sql` form truncates the
    live seed file before the generator starts, so a mid-run failure leaves an
    empty or partial seed.sql — the exact failure the Makefile's temp-file +
    rename recipe prevents (codex r5). Regex, not exact substring: the fourth
    swept site hid from a plain-text grep behind a double space before `>`,
    and the message legitimately says `commit db/seed/seed.sql`, so the pin
    is redirection-onto-the-path, not the path itself."""
    def mutate(work):
        sql = work / "db" / "seed" / "seed.sql"
        mutated = sql.read_text().replace("'penicillin'", "'sulfa'", 1)
        assert mutated != sql.read_text(), "needle missing — update this test"
        sql.write_text(mutated)

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 1
    assert not re.search(r">\s*db/seed/seed\.sql", proc.stderr)


def test_red_when_seed_sql_line_endings_change(tmp_path):
    """The compare is bytes, not universal-newlines text: a CRLF rewrite of
    the file Postgres loads must not be blessed as 'matches its generator'."""
    def mutate(work):
        sql = work / "db" / "seed" / "seed.sql"
        sql.write_bytes(sql.read_bytes().replace(b"\n", b"\r\n"))

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 1
    assert "seed.sql does not match db/seed/generate_seed.py" in proc.stderr


def test_unexpected_failure_exits_2_not_1(tmp_path):
    """Exit 1 means 'drifted — regenerate and commit', and nothing else may
    claim it: an undecodable REPORT.md is an environment/corruption problem,
    and telling the operator to regenerate would 'fix' it by destroying the
    committed embed-path report."""
    def mutate(work):
        report = work / "eval" / "rag" / "REPORT.md"
        report.write_bytes(report.read_bytes() + b"\xff\xfe garbage")

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 2
    assert "not a drift verdict" in proc.stderr


def test_check_drift_reads_the_retriever_without_planting_a_generic_name():
    """check_drift reaches retriever.py's DEFAULT_MODEL by path under a unique
    module name, never via a bare `import retriever` — which would plant the
    generic name in sys.modules for every later path-loaded module to inherit,
    the collision class tests/conftest.py exists to prevent.

    Asserted across the call rather than as `"retriever" not in sys.modules`:
    that form is a property of whatever else the run happened to import, so it
    would go red here — pointing at an innocent check_drift.py — the day any
    test path-loads eval/rag/run.py, which does `import retriever` at import
    time."""
    generic = {"retriever", "data", "metrics", "report", "run"}
    before = set(sys.modules)
    assert drift._retriever_default_model()
    planted = set(sys.modules) - before
    assert not (planted & generic), planted


def test_red_when_generator_and_seed_sql_skew(tmp_path):
    """The other direction of the same skew: the generator changes and the
    committed seed.sql is left stale."""
    def mutate(work):
        gen = work / "db" / "seed" / "generate_seed.py"
        gen.write_text(gen.read_text().replace("penicillin", "sulfa"))

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 1
    assert "seed.sql does not match db/seed/generate_seed.py" in proc.stderr


# --- the fixture CSVs are the generator's source, not a parallel copy (codex r4) ---


def test_red_on_csv_fixture_edit_before_seed_regen(tmp_path):
    """The r4 finding closed: the generator reads its fixture rows from the
    CSVs, so a CSV edit alone must first redden the SEED check — previously
    seed.sql kept matching the generator's own untouched literal and only the
    report diff (a different message) went red."""
    def mutate(work):
        csv = work / "db" / "seed" / "patients.csv"
        csv.write_text(csv.read_text().replace("412-55-9981", "999-99-9999"))

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 1
    assert "seed.sql does not match db/seed/generate_seed.py" in proc.stderr
    assert "make seed-gen" in proc.stderr


# --- the corpus fingerprint: inputs the report never renders (codex r6) ---


def test_red_when_goldset_expected_patient_flips(tmp_path):
    """The reviewer's exact case: change which patient an answer is expected
    to come from, leave cites_records untouched. The report renders neither
    expected_patient_id nor expected_answer, so before the fingerprint this
    drifted green — the committed clinical expectation silently diverged."""
    def mutate(work):
        gs = work / "db" / "seed" / "goldset.json"
        mutated = gs.read_text().replace(
            '"expected_patient_id": 1042', '"expected_patient_id": 9999'
        )
        assert mutated != gs.read_text(), "needle missing — update this test"
        gs.write_text(mutated)

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 1
    assert "corpus changed" in proc.stderr
    assert "--retriever embed" in proc.stderr


def test_red_when_encounter_summary_rewritten(tmp_path):
    """summary reaches the report only through masked score cells, so this
    rewrite invalidates the committed §4 scores while the report diff stays
    green. Seed regenerated so the seed.sql check passes and the fingerprint
    layer is the one that goes red."""
    def mutate(work):
        csv_path = work / "db" / "seed" / "encounters.csv"
        mutated = csv_path.read_text().replace(
            "Annual physical. Unremarkable.", "Urgent cardiac workup."
        )
        assert mutated != csv_path.read_text(), "needle missing — update this test"
        csv_path.write_text(mutated)
        _regen_seed(work)

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 1
    assert "corpus changed" in proc.stderr


def test_red_when_unrendered_patient_column_edited(tmp_path):
    """address feeds no match key and renders into no report section at all —
    the deepest input blind spot. Raw-byte hashing catches it anyway; a
    fingerprint over rendered encounter documents would not (name is the only
    patient column a document embeds)."""
    def mutate(work):
        csv_path = work / "db" / "seed" / "patients.csv"
        mutated = csv_path.read_text().replace("118 Maple Ave", "999 Elm St")
        assert mutated != csv_path.read_text(), "needle missing — update this test"
        csv_path.write_text(mutated)
        _regen_seed(work)

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 1
    assert "corpus changed" in proc.stderr


def test_missing_fingerprint_dies_2(tmp_path):
    """No committed fingerprint is a broken checkout, not a drift verdict —
    exit 2, never 1, and the message says how to create it."""
    def mutate(work):
        os.remove(str(work / "eval" / "rag" / "corpus.sha256"))

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 2
    assert "corpus.sha256 is missing" in proc.stderr


def test_fingerprint_refresh_without_report_regen_stays_red(tmp_path):
    """The flip of r6's test_write_fingerprint_then_green — the codex r7
    finding. The old operator path (edit an input, regenerate the seed, run
    `--write-fingerprint`, no report regeneration) turned the gate green on
    stale §4 scores. Now the flag is gone: the refresh attempt exits 2 usage,
    touches nothing, and the full check stays red on the corpus layer."""
    def mutate(work):
        csv_path = work / "db" / "seed" / "encounters.csv"
        csv_path.write_text(
            csv_path.read_text().replace(
                "Annual physical. Unremarkable.", "Urgent cardiac workup."
            )
        )
        _regen_seed(work)
        sidecar = work / "eval" / "rag" / "corpus.sha256"
        before = sidecar.read_text()
        refresh = subprocess.run(
            [sys.executable, str(work / "eval" / "rag" / "check_drift.py"),
             "--write-fingerprint"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
        )
        assert refresh.returncode == 2
        assert "usage:" in refresh.stderr
        assert sidecar.read_text() == before, "removed flag still wrote the sidecar"

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 1
    assert "corpus changed" in proc.stderr


def test_stub_run_does_not_write_fingerprint(tmp_path):
    """run.py is now the only fingerprint writer, but only the embed path
    writing the committed REPORT.md location may do it. A stub run to the
    default location — the cheap invocation in every operator's history, and
    the shape of check_drift.py's own regeneration — must leave the sidecar
    untouched, or the gate blesses itself."""
    work = _copy_eval_and_seed(tmp_path)
    sidecar = work / "eval" / "rag" / "corpus.sha256"
    before = sidecar.read_text()

    proc = subprocess.run(
        [sys.executable, str(work / "eval" / "rag" / "run.py"),
         "--retriever", "stub"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "corpus.sha256" not in proc.stdout
    assert sidecar.read_text() == before


def _fake_embed_shim(tmp_path):
    """A PYTHONPATH dir faking sentence_transformers + numpy, so the embed
    path — the only legitimate corpus.sha256 writer — actually executes in
    tests without the real model. Vectors are all-zero: retrieval quality is
    irrelevant to what these tests pin (the write path and its mid-run
    guard). If DRIFT_TEST_MUTATE_DURING_ENCODE names a file, the first
    encode() appends to it — an input edit landing while the run is underway."""
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "numpy.py").write_text(
        "import json\n"
        "class _Vecs(list):\n"
        "    def __matmul__(self, q):\n"
        "        return [sum(a * b for a, b in zip(row, q)) for row in self]\n"
        "def save(path, arr):\n"
        "    with open(path, 'w') as f:\n"
        "        json.dump(list(arr), f)\n"
        "def load(path):\n"
        "    with open(path) as f:\n"
        "        return _Vecs(json.load(f))\n"
    )
    (shim / "sentence_transformers.py").write_text(
        "import os\n"
        "import numpy\n"
        "class SentenceTransformer:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n"
        "    def encode(self, texts, normalize_embeddings=False):\n"
        "        target = os.environ.pop('DRIFT_TEST_MUTATE_DURING_ENCODE', None)\n"
        "        if target:\n"
        "            with open(target, 'a') as f:\n"
        "                f.write('# mutated mid-run\\n')\n"
        "        return numpy._Vecs([[0.0] for _ in texts])\n"
    )
    return shim


def test_embed_run_writes_fingerprint(tmp_path):
    """The positive direction of the r7 invariant, executed for real: an
    embed-path run to the default location rewrites corpus.sha256 with the
    value the checker recomputes. Sidecar pre-poisoned so this can only pass
    if the run actually wrote it."""
    work = _copy_eval_and_seed(tmp_path)
    sidecar = work / "eval" / "rag" / "corpus.sha256"
    sidecar.write_text("0" * 64 + "\n")

    env = dict(os.environ, PYTHONPATH=str(_fake_embed_shim(tmp_path)))
    proc = subprocess.run(
        [sys.executable, str(work / "eval" / "rag" / "run.py"),
         "--retriever", "embed"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "wrote eval/rag/corpus.sha256" in proc.stdout
    assert sidecar.read_text().strip() == _inputs_fingerprint(work)


def test_mid_run_corpus_edit_refuses_fingerprint(tmp_path):
    """TOCTOU (diff-review r7 pre-push finding): an input file changes while
    the embed run is underway — here, the shim's encode() appends to
    encounters.csv mid-run. REPORT.md was then computed from bytes that no
    longer exist, so run.py must refuse the sidecar write and exit 2
    unusable, not hash the new bytes and bless the divergence."""
    work = _copy_eval_and_seed(tmp_path)
    sidecar = work / "eval" / "rag" / "corpus.sha256"
    before = sidecar.read_text()

    env = dict(
        os.environ,
        PYTHONPATH=str(_fake_embed_shim(tmp_path)),
        DRIFT_TEST_MUTATE_DURING_ENCODE=str(
            work / "db" / "seed" / "encounters.csv"
        ),
    )
    proc = subprocess.run(
        [sys.executable, str(work / "eval" / "rag" / "run.py"),
         "--retriever", "embed"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
        env=env,
    )
    assert proc.returncode == 2
    assert "changed while this run was underway" in proc.stderr
    assert sidecar.read_text() == before


def test_fingerprint_destination_gating(tmp_path):
    """The write condition itself: embed + default REPORT.md location writes
    the sidecar; a stub run or an --out elsewhere never does. Run in a
    subprocess because importing run.py registers generic module names
    (data, report, …) that path-loaded test modules must not inherit."""
    rag = os.path.join(REPO_ROOT, "eval", "rag")
    probe = (
        "import os, sys\n"
        "sys.path.insert(0, %r)\n"
        "import run\n"
        "default = os.path.join(%r, 'REPORT.md')\n"
        "print(run.fingerprint_destination('embed', default) or 'none')\n"
        "print(run.fingerprint_destination('stub', default) or 'none')\n"
        "print(run.fingerprint_destination('embed', '/tmp/elsewhere.md') or 'none')\n"
        % (rag, rag)
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )
    assert proc.returncode == 0, proc.stderr
    embed_default, stub_default, embed_elsewhere = proc.stdout.strip().split("\n")
    assert embed_default.endswith("corpus.sha256")
    assert stub_default == "none"
    assert embed_elsewhere == "none"


def test_generator_dies_when_fixture_csv_is_missing(tmp_path):
    """A missing fixture CSV must kill generation loudly — exit 2 through the
    'generator cannot run' path — never emit a partial seed.sql, and never be
    diagnosed as the eval failing (the pre-derivation behavior: the generator
    ignored the CSVs and only run.py noticed the file was gone)."""
    def mutate(work):
        os.remove(str(work / "db" / "seed" / "patients.csv"))

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 2
    assert "generate_seed.py failed to run" in proc.stderr


def test_generator_dies_when_patient_rows_are_reordered(tmp_path):
    """The seed-only columns (mrn/phone/notes…) are keyed by patient id; a
    reordered CSV must fail loudly, not attach them to the wrong patient."""
    def mutate(work):
        path = work / "db" / "seed" / "patients.csv"
        lines = path.read_text().rstrip("\n").split("\n")
        lines[1], lines[2] = lines[2], lines[1]
        path.write_text("\n".join(lines) + "\n")

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 2
    assert "row order changed" in proc.stderr


def test_generator_dies_when_encounter_rows_are_reordered(tmp_path):
    """Same guard for encounters, which are matched to their seed-only
    columns (id, reason, location, status) by row order."""
    def mutate(work):
        path = work / "db" / "seed" / "encounters.csv"
        lines = path.read_text().rstrip("\n").split("\n")
        lines[1], lines[2] = lines[2], lines[1]
        path.write_text("\n".join(lines) + "\n")

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 2
    assert "row order changed" in proc.stderr


def test_generator_dies_when_encounter_content_swaps_under_a_stable_patient_id(tmp_path):
    """patient_id alone is too weak a key for the encounter cross-check.
    Swapping two visits' clinical columns while leaving the patient_id column
    in place left the id-only guard green, so encounter id 1 / "Annual
    physical" attached to the sinus visit and the damage surfaced only as an
    exit-1 "regenerate seed.sql" — which invites the operator to bless the
    mis-attached rows. occurred_at pins each tuple to its own CSV row."""
    def mutate(work):
        path = work / "db" / "seed" / "encounters.csv"
        rows = path.read_text().rstrip("\n").split("\n")
        pid_a, rest_a = rows[1].split(",", 1)
        pid_b, rest_b = rows[2].split(",", 1)
        rows[1], rows[2] = "%s,%s" % (pid_a, rest_b), "%s,%s" % (pid_b, rest_a)
        path.write_text("\n".join(rows) + "\n")

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 2
    assert "row order changed" in proc.stderr


def test_red_when_the_eval_itself_fails(tmp_path):
    """A crash in run.py must exit 2 through its own 'eval failed to run'
    message — never exit 1, whose 'regenerate and commit' advice would have
    an operator fixing a broken eval by rewriting the committed report."""
    def mutate(work):
        runpy = work / "eval" / "rag" / "run.py"
        runpy.write_text("import sys\nsys.exit(3)\n")

    proc = _run_in_copy(tmp_path, mutate)
    assert proc.returncode == 2
    assert "the eval itself failed to run" in proc.stderr


def test_child_timeout_is_reported_as_cannot_run_not_drift(monkeypatch, capsys):
    """A wedged child process must exit 2 through the 'cannot run' path: exit
    1 would send the operator regenerating a report to fix a hang, and no
    handler at all would propagate TimeoutExpired and wedge `make eval` on
    whatever the caller's timeout is."""
    def hang(cmd, **kwargs):
        # Asserts the ARMING too, not just the handler: a fake that raises
        # unconditionally stays green after both `timeout=` kwargs are
        # deleted, which is the un-wiring that would let a wedged child run
        # to GitHub's 6-hour job kill.
        assert kwargs["timeout"] == drift.SUBPROCESS_TIMEOUT
        raise drift.subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])

    monkeypatch.setattr(drift.subprocess, "run", hang)
    for entry in (drift._regenerate, drift._check_seed_sql):
        with pytest.raises(SystemExit) as exc:
            entry()
        assert exc.value.code == 2
    assert capsys.readouterr().err.count("not a drift verdict") == 2


def test_audit_log_fixture_follows_the_patient_csv(tmp_path):
    """audit_logs' intake row logs patient 1042's name/dob/ssn — the D1
    "PHI in application logs" teaching fixture. Held as a hand-copied literal
    it went stale in silence on a fixture edit: no check reads audit_logs (not
    the eval, not the report), and the generator still byte-matched itself, so
    seed.sql would demonstrate an SSN that no patients row holds."""
    work = tmp_path / "repo"
    (work / "db").mkdir(parents=True)
    shutil.copytree(os.path.join(REPO_ROOT, "db", "seed"), str(work / "db" / "seed"))
    csv = work / "db" / "seed" / "patients.csv"
    csv.write_text(csv.read_text().replace("412-55-9981", "999-88-7777"))

    proc = subprocess.run(
        [sys.executable, str(work / "db" / "seed" / "generate_seed.py")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )

    assert proc.returncode == 0, proc.stderr
    logged = [ln for ln in proc.stdout.splitlines() if "POST /intake body=" in ln]
    assert len(logged) == 1, logged
    assert "999-88-7777" in logged[0]
    # Class-level: no copy of the old SSN survives ANYWHERE in the seed.
    assert "412-55-9981" not in proc.stdout


def test_seed_gen_does_not_destroy_seed_sql_when_the_generator_fails(tmp_path):
    """The recipe around the guards, not the guards. `make seed-gen` used to
    redirect straight onto db/seed/seed.sql, and the shell truncates the
    target BEFORE the generator runs — harmless while the generator read no
    files and could not fail, fatal now that a missing or reordered fixture
    CSV kills it. The 0-byte file left behind is what docker-compose.yml
    mounts into a fresh volume's initdb, which brings up a schema-only
    database and reports nothing."""
    work = tmp_path / "repo"
    (work / "db").mkdir(parents=True)
    shutil.copytree(os.path.join(REPO_ROOT, "db", "seed"), str(work / "db" / "seed"))
    shutil.copy(os.path.join(REPO_ROOT, "Makefile"), str(work / "Makefile"))
    seed_sql = work / "db" / "seed" / "seed.sql"
    before = seed_sql.read_bytes()
    assert before, "copied seed.sql is empty — this test would prove nothing"

    os.remove(str(work / "db" / "seed" / "patients.csv"))
    proc = subprocess.run(
        ["make", "seed-gen"], cwd=str(work),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )

    assert proc.returncode != 0, proc.stdout
    assert seed_sql.read_bytes() == before
    assert not (work / "db" / "seed" / "seed.sql.tmp").exists()
