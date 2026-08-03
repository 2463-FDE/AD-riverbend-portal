"""
Drift check: is the committed eval/rag/REPORT.md still what db/seed/* produces?

    python3 eval/rag/check_drift.py     # exit 0 current, 1 drifted, 2 unusable

Run by `make eval` and by the CI `eval` job. Regenerates the report with the
STUB retriever (torch-free: eval/rag/retriever.py defers numpy and
sentence-transformers into EmbeddingRetriever._load, so the stub path is
standard library only and CI installs nothing) and diffs it against the
committed file.

PYTHON 3.8 COMPATIBLE ON PURPOSE. `make eval` runs this under the system
interpreter (3.8, same as `make seed-gen` / `make status`); CI runs it under
3.12. A 3.9+ idiom here breaks the local path silently while CI stays green —
so: no dict `|` merge, no `list[str]` builtin generics, no match statement,
no str.removeprefix.

WHAT IS AND IS NOT CHECKED — one tradeoff, stated in full:

The committed REPORT.md is EMBED-path output, so §4's retrieval numbers cannot
be reproduced without the model. This check masks §4's numeric content in both
texts before diffing — but only the cells that genuinely depend on the model:
in each score-table row, the `retrieved` / `recall` / `precision` cells, and
the macro line. The row itself survives, so its `query` and
`expected records` cells — goldset.json content, identical on both paths — are
compared, and so is the row COUNT: a reworded query, a changed cites_records
list, or an added/removed case all turn the gate red. Everything else — §1
headline and cluster table, §2 patient-safety gaps, §3 match-key analysis, §5
conclusion — is compared byte for byte.

Masking whole cells, rather than only the values that currently differ between
the stub and embed paths, keeps this check decoupled from score stability: a
model or hardware change must never turn the drift gate red. The cost,
accepted deliberately, is a blind spot:

  * Of goldset.json, only each case's query and cites_records reach the
    report. expected_patient_id, expected_answer and the file's description
    field appear nowhere in it, so edits to those pass unnoticed — that is
    run.py's scope, not a mask decision.
  * Of db/seed/patients.csv and encounters.csv, only rows in an SSN candidate
    cluster render into compared text at all: §1's cluster tables list only
    fragmented/conflict/ambiguous identities, and §2's gaps are built solely
    from status == "candidate" SSN identities (run.py). A non-clustered
    patient's name — or an allergy planted on their encounter — reaches the
    report only through retriever.encounter_document, i.e. only into masked
    cells, and passes unnoticed. Also run.py's rendering scope, not the
    mask's.
  * Even for cluster rows, encounters.csv's encounter_type, provider, summary
    and occurred_at columns feed only masked cells — so rewriting every
    encounter summary invalidates the committed scores and still passes.

SEPARATE FROM THE REPORT DIFF (added codex r3): db/seed/seed.sql — the file a
fresh Postgres volume and `make seed` actually load — is byte-checked against
its deterministic generator, db/seed/generate_seed.py. Without this, a
hand-edited Maria row in seed.sql changes what the running system demonstrates
while the report (which reads only the CSVs and goldset) stays green. The
remaining gap there is TODO-40's duplication: generate_seed.py and the CSVs
are two independent hardcoded copies of the same fixtures, so a generator
edit with `make seed-gen` run leaves seed.sql, the CSVs and this report
jointly stale and this check green. That closes only by deriving one from the
other (TODO-40), not by another diff.

Nothing else is masked, and the green message names exactly this scope rather
than claiming the whole seed directory.

The `Retriever:` line is deliberately NOT masked wholesale. Its label is not a
score: this script chose --retriever stub, so it knows what the committed side
must not say. Masking the line would let a report regenerated the easy way
(`run.py --retriever stub`, the invocation already in the operator's shell
history after a red run) satisfy the gate permanently — while the committed
RIV-160 deliverable would read "Macro recall 1.00" directly above the §4 prose
explaining why one query MISSES. So the label is validated, not ignored, and
the `top-k` suffix on the same line is compared, so a report committed at a
different --k also fails.

The mask is anchored, not positional: if any anchor is missing or duplicated
on either side, the check exits 2 rather than silently widening what it
ignores.
"""
import difflib
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
COMMITTED = os.path.join(HERE, "REPORT.md")
RUN_PY = os.path.join(HERE, "run.py")

def _retriever_default_model():
    """Load eval/rag/retriever.py (torch-free at import) under a unique module
    name, on demand. Not a plain `import retriever`: tests load THIS file by
    path into their own process, and a bare import would register the generic
    name `retriever` (and HERE on sys.path) for every later path-loaded module
    to silently inherit — the collision class tests/conftest.py exists to
    prevent."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "eval_rag_retriever", os.path.join(HERE, "retriever.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DEFAULT_MODEL

# `Retriever: **<label>**, top-k = <k>.` — report.py:155.
RETRIEVER_RE = re.compile(r"^Retriever: \*\*(?P<label>.*)\*\*, top-k = (?P<k>\d+)\.$")
MACRO_PREFIX = "**Macro recall "
SCORE_HEADER = "| query | expected records | retrieved | recall | precision |"

GENERATE_SEED = os.path.join(REPO_ROOT, "db", "seed", "generate_seed.py")
SEED_SQL = os.path.join(REPO_ROOT, "db", "seed", "seed.sql")

COMMITTED_SIDE = "eval/rag/REPORT.md"
REGENERATED_SIDE = "the regenerated report"

SEED_DIFF_MAX_LINES = 120

SEED_REGENERATE = (
    "rerun: make seed-gen   (python3 db/seed/generate_seed.py > db/seed/seed.sql)\n"
    "then commit db/seed/seed.sql. If the regenerated file is the wrong one, the\n"
    "edit belongs in db/seed/generate_seed.py, not in seed.sql by hand.\n"
)

REGENERATE = (
    "rerun: pip install -r eval/rag/requirements.txt && "
    "python3 eval/rag/run.py --retriever embed\n"
    "then commit eval/rag/REPORT.md. Use --retriever embed, NOT --retriever stub: "
    "the committed report\nis the embed-path one, and a stub-generated report is "
    "rejected by this check.\n"
)


def _die(message):
    sys.stderr.write(message)
    sys.exit(2)


def _regenerate():
    """Run the real CLI rather than re-implementing its pipeline here."""
    tmp_dir = tempfile.mkdtemp(prefix="eval-drift-")
    try:
        tmp_out = os.path.join(tmp_dir, "REPORT.md")
        proc = subprocess.run(
            [sys.executable, RUN_PY, "--retriever", "stub", "--out", tmp_out],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
            _die("eval drift: the eval itself failed to run (above)\n")
        with open(tmp_out, encoding="utf-8") as f:
            return f.read()
    finally:
        # The leaked file is a full RIV-160 report, and report.py's own header
        # warns it prints identifying demographics. Do not accumulate copies.
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _check_seed_sql():
    """db/seed/seed.sql is what Postgres actually loads (fresh-volume init and
    `make seed`), and its generator is deterministic — so the committed file
    must byte-match a regeneration. Catches a hand-edited or stale seed.sql,
    i.e. the running system demonstrating data this report never read. Does
    NOT catch a generator edit whose CSV twins went stale with it — see the
    header's TODO-40 bullet. Exits 1 on mismatch, 2 if the generator cannot
    run."""
    proc = subprocess.run(
        [sys.executable, GENERATE_SEED],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
        _die("eval drift: db/seed/generate_seed.py failed to run (above)\n")
    regenerated = proc.stdout

    if not os.path.exists(SEED_SQL):
        _die("eval drift: db/seed/seed.sql is missing\n%s" % SEED_REGENERATE)
    # Bytes on both sides: a text-mode read folds CRLF to LF before comparing,
    # which would bless a line-ending rewrite of the file Postgres loads.
    with open(SEED_SQL, "rb") as f:
        committed = f.read()

    if regenerated == committed:
        return

    sys.stderr.write(
        "eval drift: db/seed/seed.sql does not match db/seed/generate_seed.py\n"
    )
    diff = difflib.unified_diff(
        committed.decode("utf-8", "replace").split("\n"),
        regenerated.decode("utf-8", "replace").split("\n"),
        fromfile="db/seed/seed.sql",
        tofile="regenerated (generate_seed.py)",
        lineterm="",
    )
    shown = 0
    for line in diff:
        if shown >= SEED_DIFF_MAX_LINES:
            sys.stderr.write("... diff truncated at %d lines\n" % SEED_DIFF_MAX_LINES)
            break
        sys.stderr.write(line + "\n")
        shown += 1
    sys.stderr.write("\n" + SEED_REGENERATE)
    sys.exit(1)


def _check_committed_label(label):
    """The committed report must be embed-path output, not a stub regeneration."""
    default_model = _retriever_default_model()
    if default_model in label:
        return
    _die(
        "eval drift: %s was generated with the wrong retriever.\n"
        "  its label reads: %s\n"
        "  expected the embed-path label naming %s.\n"
        "A stub-generated report scores every query 1.00, which contradicts the "
        "§4 prose\nbeneath it and destroys what the RIV-160 report is for.\n%s"
        % (COMMITTED_SIDE, label, default_model, REGENERATE)
    )


def _count_anchors(lines):
    """Count anchors over the raw lines.

    Deliberately a separate pass from the masking: the table-body loop below
    consumes every following `|` line, which would swallow a second score
    header and report a count of 1 for a report that has two.
    """
    hits = {"retriever": 0, "macro": 0, "table": 0}
    for line in lines:
        if RETRIEVER_RE.match(line):
            hits["retriever"] += 1
        elif line.startswith(MACRO_PREFIX):
            hits["macro"] += 1
        elif line == SCORE_HEADER:
            hits["table"] += 1
    return hits


def _mask_score_row(line):
    """Blank one score-table row's model-dependent cells — `retrieved`,
    `recall`, `precision` — keeping the goldset-derived `query` and
    `expected records` cells (and the row itself) comparable. rsplit from the
    right so a query containing `|` cannot shift which cells are masked. The
    `|---|` separator row has nothing model-dependent and passes through."""
    if not line.strip("|- "):
        return line
    head = line.rstrip().rstrip("|").rsplit("|", 3)[0]
    return head + "| <masked: retrieved> | <masked: recall> | <masked: precision> |"


def _mask(text, source):
    """Blank §4's model-dependent content. Exits 2 if the anchors moved."""
    lines = text.split("\n")

    for anchor, count in sorted(_count_anchors(lines).items()):
        if count != 1:
            if source == COMMITTED_SIDE:
                remedy = (
                    "The committed report is in an unexpected shape — regenerate it "
                    "rather than editing\nthe guard.\n%s" % REGENERATE
                )
            else:
                remedy = (
                    "eval/rag/report.py changed shape. Update the mask in "
                    "eval/rag/check_drift.py; do not\nwiden it without re-reading "
                    "what it already excludes.\n"
                )
            _die(
                "eval drift: report structure changed — the '%s' anchor appears "
                "%d times in %s, expected exactly 1.\n%s"
                % (anchor, count, source, remedy)
            )

    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        match = RETRIEVER_RE.match(line)
        if match:
            if source == COMMITTED_SIDE:
                _check_committed_label(match.group("label"))
            # Label masked (stub vs embed differ legitimately); top-k compared.
            out.append("Retriever: <masked label>, top-k = %s." % match.group("k"))
            i += 1
            continue
        if line.startswith(MACRO_PREFIX):
            out.append("<masked: macro scores>")
            i += 1
            continue
        if line == SCORE_HEADER:
            out.append(line)
            i += 1
            while i < len(lines) and lines[i].startswith("|"):
                out.append(_mask_score_row(lines[i]))
                i += 1
            continue
        out.append(line)
        i += 1
    return out


def main():
    if not os.path.exists(COMMITTED):
        _die("eval drift: %s is missing\n" % COMMITTED)
    with open(COMMITTED, encoding="utf-8") as f:
        committed = f.read()

    _check_seed_sql()

    regenerated = _regenerate()

    left = _mask(committed, COMMITTED_SIDE)
    right = _mask(regenerated, REGENERATED_SIDE)

    if left == right:
        print(
            "eval: db/seed/seed.sql matches its generator, and REPORT.md "
            "matches what db/seed/*\n      renders into it — the SSN-cluster "
            "rows of patients.csv, their allergy/medication\n      columns in "
            "encounters.csv, and goldset.json's queries and cited records"
        )
        print(
            "      (unchecked: the generator's own fixture literals vs the "
            "CSVs (TODO-40),\n      non-clustered rows, the summary/provider/"
            "type/date columns, and §4's\n      retrieved/recall/precision "
            "cells — scope owned by this script's header)"
        )
        return 0

    sys.stderr.write("eval drift: eval/rag/REPORT.md is stale vs db/seed/*\n")
    diff = difflib.unified_diff(
        left, right, fromfile=COMMITTED_SIDE, tofile="regenerated (stub)", lineterm=""
    )
    for line in diff:
        sys.stderr.write(line + "\n")
    sys.stderr.write("\n" + REGENERATE)
    return 1


if __name__ == "__main__":
    # Uphold the documented exit contract: 1 means "drifted — regenerate and
    # commit" and nothing else. An unexpected crash (bad encoding, OSError)
    # must not exit 1 and send an operator regenerating a report to fix an
    # environment problem.
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback

        traceback.print_exc()
        sys.stderr.write(
            "eval drift: unexpected failure (above) — not a drift verdict; "
            "nothing needs regenerating\n"
        )
        sys.exit(2)
