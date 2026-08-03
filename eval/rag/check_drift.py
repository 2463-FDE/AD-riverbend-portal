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
texts before diffing: the score table body and the macro line. Everything else
— §1 headline and cluster table, §2 patient-safety gaps, §3 match-key
analysis, §5 conclusion — is compared byte for byte.

Masking the WHOLE table body, rather than only the rows that currently differ
between the stub and embed paths, keeps this check decoupled from score
stability: a model or hardware change must never turn the drift gate red. The
cost, accepted deliberately, is a blind spot, and it is wider than the scores
themselves:

  * db/seed/goldset.json feeds §4 alone, so a goldset edit — reworded query,
    changed expected record ids, an added or removed case — passes unnoticed.
  * Of db/seed/encounters.csv, only patient_id, allergies and medications
    reach the compared text (via §2). encounter_type, provider, summary and
    occurred_at reach the report only through retriever.encounter_document,
    i.e. only into masked §4 — so rewriting every encounter summary invalidates
    the committed scores and still passes.

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

if HERE not in sys.path:
    sys.path.insert(0, HERE)

import retriever as retriever_mod  # noqa: E402  (module import is torch-free)

# `Retriever: **<label>**, top-k = <k>.` — report.py:155.
RETRIEVER_RE = re.compile(r"^Retriever: \*\*(?P<label>.*)\*\*, top-k = (?P<k>\d+)\.$")
MACRO_PREFIX = "**Macro recall "
SCORE_HEADER = "| query | expected records | retrieved | recall | precision |"

COMMITTED_SIDE = "eval/rag/REPORT.md"
REGENERATED_SIDE = "the regenerated report"

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
        with open(tmp_out) as f:
            return f.read()
    finally:
        # The leaked file is a full RIV-160 report, and report.py's own header
        # warns it prints identifying demographics. Do not accumulate copies.
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _check_committed_label(label):
    """The committed report must be embed-path output, not a stub regeneration."""
    if retriever_mod.DEFAULT_MODEL in label:
        return
    _die(
        "eval drift: %s was generated with the wrong retriever.\n"
        "  its label reads: %s\n"
        "  expected the embed-path label naming %s.\n"
        "A stub-generated report scores every query 1.00, which contradicts the "
        "§4 prose\nbeneath it and destroys what the RIV-160 report is for.\n%s"
        % (COMMITTED_SIDE, label, retriever_mod.DEFAULT_MODEL, REGENERATE)
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


def _mask(text, source):
    """Blank §4's numeric content. Exits 2 if the anchors moved."""
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
            out.append("<masked: score table body>")
            while i < len(lines) and lines[i].startswith("|"):
                i += 1
            continue
        out.append(line)
        i += 1
    return out


def main():
    if not os.path.exists(COMMITTED):
        _die("eval drift: %s is missing\n" % COMMITTED)
    with open(COMMITTED) as f:
        committed = f.read()

    regenerated = _regenerate()

    left = _mask(committed, COMMITTED_SIDE)
    right = _mask(regenerated, REGENERATED_SIDE)

    if left == right:
        print(
            "eval: REPORT.md matches db/seed/patients.csv and the "
            "allergy/medication columns of encounters.csv"
        )
        print(
            "      (masked: §4 retrieval scores — so goldset.json and the "
            "summary/provider/type/date columns are unchecked)"
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
    sys.exit(main())
