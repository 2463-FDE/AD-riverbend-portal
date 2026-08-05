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
conclusion — is compared line for line after text-mode newline normalization
(the report is a markdown deliverable, so a CRLF rewrite of it is cosmetic;
seed.sql, the file Postgres loads, IS compared as raw bytes).

Masking whole cells, rather than only the values that currently differ between
the stub and embed paths, keeps this check decoupled from score stability: a
model or hardware change must never turn the drift gate red. The report diff
therefore only sees what run.py renders — goldset fields the report never
shows (expected_patient_id, expected_answer, description), CSV columns that
feed only masked score cells (summary/provider/type/date), and every
patients/encounters row outside an SSN candidate cluster would all drift
green through it.

THAT INPUT BLIND SPOT IS CLOSED BY THE CORPUS FINGERPRINT (added codex r6):
eval/rag/corpus.sha256 pins the raw bytes of patients.csv, encounters.csv and
goldset.json — every DATA file run.py reads — and this check fails when they
no longer match. Raw bytes, not rendered documents, so no column is exempt.
The eval CODE stays unfingerprinted, deliberately: a change to the scoring
definition (metrics.py) or the retriever's ranking reaches the report only
through masked cells, so the committed scores can describe a dead scoring
definition with the gate green. Fingerprinting the .py files would close that
at the cost of every comment edit demanding an embed re-run; rejected. What IS
pinned on the code side: the model (label check) and top-k (compared). The
fingerprint deliberately cannot verify the §4 SCORES against the new inputs
(nothing can without the model); its job is to make input drift loud, and the
red message states the obligation that follows: regenerate the embed-path
report, then refresh the fingerprint (`check_drift.py --write-fingerprint`),
and commit both together. An operator who refreshes the fingerprint without
regenerating the report is lying to the gate the same way hand-editing
REPORT.md would be — visible in review (the .sha256 hunk arrives without a
REPORT.md hunk), not preventable here.

SEPARATE FROM THE REPORT DIFF (added codex r3): db/seed/seed.sql — the file a
fresh Postgres volume and `make seed` actually load — is byte-checked against
its deterministic generator, db/seed/generate_seed.py. Without this, a
hand-edited Maria row in seed.sql changes what the running system demonstrates
while the report (which reads only the CSVs and goldset) stays green. Since
codex r4 the generator READS its fixture rows' shared columns from
patients.csv / encounters.csv (TODO-40's second copy deleted): a fixture edit
now lands in seed.sql and the report's inputs together, so "the patients and
encounters tables are jointly stale with the report" is no longer a reachable
state.

What that does NOT cover, and no check does: the generator's OTHER tables
paraphrase the same fixtures in prose it cannot derive. records id 2's body
("Penicillin allergy confirmed…") restates encounters.csv row 2's allergies
column, so moving that allergy to another encounter leaves the note attached
to the wrong visit with seed.sql byte-matching its generator. The eval reads
neither table, so only a human notices.

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
import hashlib
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

# The three files run.py reads (codex r6). Raw bytes, not parsed content: the
# fingerprint's question is "are these the inputs the committed §4 scores were
# computed from", and any byte difference means they are not. Hashing rendered
# encounter_document strings instead was considered and rejected — it leaves
# columns the renderer skips (a non-clustered patient's ssn/dob/address)
# invisible, which is this blind-spot class all over again.
CORPUS_INPUTS = ("patients.csv", "encounters.csv", "goldset.json")
CORPUS_SHA = os.path.join(HERE, "corpus.sha256")
CORPUS_SHA_SIDE = "eval/rag/corpus.sha256"

COMMITTED_SIDE = "eval/rag/REPORT.md"
REGENERATED_SIDE = "the regenerated report"

SEED_DIFF_MAX_LINES = 120

# Both child scripts are pure-CPU and finish in seconds; the timeout exists so
# a future blocking read added to either one wedges this gate — and the CI jobs
# behind it — for minutes, not for GitHub's 6-hour job kill.
SUBPROCESS_TIMEOUT = 300

# make seed-gen only — never the direct `... > db/seed/seed.sql` redirection,
# which truncates the live seed file before the generator runs; the Makefile
# recipe writes a temp file and renames on success for exactly that reason.
SEED_REGENERATE = (
    "rerun: make seed-gen\n"
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

FINGERPRINT_REGENERATE = (
    "rerun: pip install -r eval/rag/requirements.txt && "
    "python3 eval/rag/run.py --retriever embed\n"
    "then:  python3 eval/rag/check_drift.py --write-fingerprint\n"
    "and commit eval/rag/REPORT.md and eval/rag/corpus.sha256 together. "
    "Refreshing the\nfingerprint without regenerating the report pins the "
    "committed scores to a corpus\nthat no longer exists.\n"
)


def _die(message):
    sys.stderr.write(message)
    sys.exit(2)


def _regenerate():
    """Run the real CLI rather than re-implementing its pipeline here."""
    tmp_dir = tempfile.mkdtemp(prefix="eval-drift-")
    try:
        tmp_out = os.path.join(tmp_dir, "REPORT.md")
        try:
            proc = subprocess.run(
                [sys.executable, RUN_PY, "--retriever", "stub", "--out", tmp_out],
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=SUBPROCESS_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            _die(
                "eval drift: eval/rag/run.py exceeded %ds — not a drift "
                "verdict; nothing needs regenerating\n" % SUBPROCESS_TIMEOUT
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
    i.e. the running system demonstrating data this report never read. The
    generator reads its fixture rows from the same CSVs the report reads, so
    a fixture edit skews this check and the report diff together rather than
    leaving them jointly stale. Exits 1 on mismatch, 2 if the generator
    cannot run."""
    try:
        proc = subprocess.run(
            [sys.executable, GENERATE_SEED],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=SUBPROCESS_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        _die(
            "eval drift: db/seed/generate_seed.py exceeded %ds — not a drift "
            "verdict; nothing needs regenerating\n" % SUBPROCESS_TIMEOUT
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


def _corpus_fingerprint():
    """sha256 over the raw bytes of every file run.py reads, each prefixed by
    its name so content cannot migrate between files without a change."""
    h = hashlib.sha256()
    for name in CORPUS_INPUTS:
        with open(os.path.join(REPO_ROOT, "db", "seed", name), "rb") as f:
            h.update(b"\x00" + name.encode("utf-8") + b"\x00")
            h.update(f.read())
    return h.hexdigest()


def _check_corpus_fingerprint():
    """The report diff below only sees what run.py renders; goldset fields the
    report never shows (expected_patient_id, expected_answer) and CSV columns
    that feed only masked score cells would otherwise drift green (codex r6).
    The fingerprint makes any input-file change visible; regenerating the
    embed-path report is then the operator's obligation, stated in the
    remediation — no check can re-score §4 without the model."""
    if not os.path.exists(CORPUS_SHA):
        _die(
            "eval drift: %s is missing\n%s" % (CORPUS_SHA_SIDE, FINGERPRINT_REGENERATE)
        )
    with open(CORPUS_SHA, encoding="utf-8") as f:
        committed = f.read().strip()
    actual = _corpus_fingerprint()
    if committed == actual:
        return
    sys.stderr.write(
        "eval drift: the eval corpus changed — db/seed/patients.csv, "
        "encounters.csv or\ngoldset.json no longer match %s\n"
        "  committed: %s\n  actual:    %s\n"
        "The committed REPORT.md's §4 scores describe inputs that no longer "
        "exist.\n%s" % (CORPUS_SHA_SIDE, committed, actual, FINGERPRINT_REGENERATE)
    )
    sys.exit(1)


def _write_fingerprint():
    value = _corpus_fingerprint()
    with open(CORPUS_SHA, "w") as f:
        f.write(value + "\n")
    print("wrote %s (%s)" % (CORPUS_SHA_SIDE, value))
    print(
        "commit it only alongside a REPORT.md regenerated on the embed path — "
        "see the header\nof eval/rag/check_drift.py"
    )
    return 0


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
    _check_corpus_fingerprint()

    regenerated = _regenerate()

    left = _mask(committed, COMMITTED_SIDE)
    right = _mask(regenerated, REGENERATED_SIDE)

    if left == right:
        print(
            "eval: db/seed/seed.sql matches its generator, the corpus "
            "fingerprint pins every byte\n      of patients.csv / "
            "encounters.csv / goldset.json, and REPORT.md matches what\n"
            "      db/seed/* renders into it"
        )
        print(
            "      (unchecked: §4's retrieved/recall/precision cells — the "
            "embed-path scores\n      themselves; scope owned by this script's "
            "header)"
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
        if sys.argv[1:] == ["--write-fingerprint"]:
            sys.exit(_write_fingerprint())
        if sys.argv[1:]:
            sys.stderr.write(
                "usage: python3 eval/rag/check_drift.py [--write-fingerprint]\n"
            )
            sys.exit(2)
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
