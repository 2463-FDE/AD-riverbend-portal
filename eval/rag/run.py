"""
CLI entry point for the RAG retrieval eval (RIV-160).

    python eval/rag/run.py                     # embedding retriever (needs
                                               # eval/rag/requirements.txt)
    python eval/rag/run.py --retriever stub    # torch-free oracle run

Writes eval/rag/REPORT.md. An embed-path run writing the default location also
refreshes eval/rag/corpus.sha256 — the only writer of that file (codex r7), so
the drift gate's fingerprint can never be updated without regenerating the
report it vouches for. Corpus embeddings are cached under eval/rag/.cache/ and
reused across runs (quota guard: embed once).
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import check_drift  # noqa: E402 — corpus_fingerprint: one hash definition, not two
import data  # noqa: E402
import metrics  # noqa: E402
import report  # noqa: E402
import retriever as retriever_mod  # noqa: E402

MATCH_KEYS = ("none", "name_dob", "ssn")


def is_committed_report_location(out_path):
    """Is out_path the committed eval/rag/REPORT.md? The ONE definition both
    committed-artifact writers (corpus.sha256, GOLDSET.md) consult — two
    copies of this predicate drifting apart would let an embed run refresh
    one artifact but not its pair, red-ing the gate at the wrong layer."""
    return os.path.realpath(out_path) == os.path.realpath(
        os.path.join(HERE, "REPORT.md")
    )


def fingerprint_destination(retriever_name, out_path):
    """Where this run may write eval/rag/corpus.sha256 — or None.

    The fingerprint vouches that the committed REPORT.md was generated from
    the current input files, so it is written ONLY when this run is actually
    producing that artifact: embed retriever, default output location. A stub
    run (including check_drift.py's own temp-dir regeneration) or an --out
    elsewhere must never refresh it — either would let the sidecar bless
    inputs the committed report never saw, the codex r7 finding.
    """
    if retriever_name != "embed":
        return None
    if not is_committed_report_location(out_path):
        return None
    return check_drift.CORPUS_SHA


GOLDSET_MD = os.path.join(HERE, "GOLDSET.md")


def write_goldset_summary():
    """Render db/seed/goldset.json into eval/rag/GOLDSET.md (codex r8).

    Standalone on purpose, unlike the deleted `--write-fingerprint`: the
    summary is a pure function of goldset.json that check_drift.py re-derives
    and diffs, so this writer cannot bless anything false — a stale or forged
    GOLDSET.md goes red on the next check regardless of who wrote it. The
    fingerprint had no such re-derivation (the embed scores are
    unreproducible without the model), which is why ITS writer is gated to
    the embed run and this one need not be."""
    with open(os.path.join(REPO_ROOT, "db", "seed", "goldset.json")) as f:
        goldset = json.load(f)
    with open(GOLDSET_MD, "w") as f:
        f.write(report.render_goldset_summary(goldset))
    print("wrote eval/rag/GOLDSET.md")


def refresh_fingerprint_sidecar(dest, before):
    """Write the corpus fingerprint this run is entitled to vouch for.

    `before` is the fingerprint taken before the input files were loaded. An
    embed run is a minutes-long window on first use (model download) — long
    enough for a branch switch or a CSV edit to rewrite an input mid-run, in
    which case REPORT.md was computed from bytes that no longer exist and
    hashing the current bytes would bless exactly that divergence. Refuse and
    die unusable (exit 2, nothing written) instead; the remaining window is
    the microseconds between the pre-load hash and the loads themselves.
    """
    after = check_drift.corpus_fingerprint()
    if after != before:
        sys.stderr.write(
            "eval: the corpus files changed while this run was underway — "
            "REPORT.md was computed\nfrom inputs that no longer exist. Not "
            "writing eval/rag/corpus.sha256; rerun on the\nsettled tree.\n"
        )
        sys.exit(2)
    with open(dest, "w") as f:
        f.write(after + "\n")
    print(f"wrote {check_drift.CORPUS_SHA_SIDE} ({after})")
    print("commit it together with the regenerated REPORT.md")


def build_retriever(name: str, patients, encounters, cases):
    if name == "stub":
        return retriever_mod.StubRetriever.perfect_for(cases), "stub oracle (upper bound: answers each query with its gold citations)"
    by_id = {p.id: p for p in patients}
    corpus = {
        e.record_id: retriever_mod.encounter_document(by_id[e.patient_id].name, e)
        for e in encounters
    }
    embed = retriever_mod.EmbeddingRetriever(corpus, cache_dir=os.path.join(HERE, ".cache"))
    return embed, f"local embeddings ({retriever_mod.DEFAULT_MODEL}, cached, cosine top-k)"


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG retrieval eval (RIV-160)")
    parser.add_argument("--retriever", choices=("embed", "stub"), default="embed")
    parser.add_argument("--k", type=int, default=1, help="top-k records retrieved per query")
    parser.add_argument("--out", default=os.path.join(HERE, "REPORT.md"))
    parser.add_argument(
        "--write-goldset-summary", action="store_true",
        help="only regenerate eval/rag/GOLDSET.md from db/seed/goldset.json; "
        "touches no other file (safe standalone: check_drift re-derives it)",
    )
    args = parser.parse_args()

    if args.write_goldset_summary:
        write_goldset_summary()
        return

    seed_dir = os.path.join(REPO_ROOT, "db", "seed")
    # Hashed BEFORE the loads below: refresh_fingerprint_sidecar re-hashes at
    # write time and refuses if the inputs changed while the run was underway.
    corpus_before = check_drift.corpus_fingerprint()
    patients = data.load_patients(os.path.join(seed_dir, "patients.csv"))
    encounters = data.load_encounters(os.path.join(seed_dir, "encounters.csv"))
    cases = data.load_goldset(os.path.join(seed_dir, "goldset.json"))

    identities_by_key = {
        key: data.resolve_identities(patients, key) for key in MATCH_KEYS
    }
    dup = metrics.candidate_duplicate_rate(patients, identities_by_key["ssn"])

    gaps = []
    for identity in identities_by_key["ssn"]:
        if identity.status == "candidate":
            for chart_id in identity.patient_ids:
                gaps.append(
                    metrics.fragment_coverage_gap(
                        identity.patient_ids, encounters, chart_id
                    )
                )

    engine, label = build_retriever(args.retriever, patients, encounters, cases)
    retrieved = {c.query: engine.retrieve(c.query, args.k) for c in cases}
    scores = metrics.retrieval_scores(cases, retrieved)

    md = report.render_report(
        patients, identities_by_key, dup, gaps, scores, label, args.k
    )
    with open(args.out, "w") as f:
        f.write(md)

    print(f"wrote {args.out}")
    if is_committed_report_location(args.out):
        # Any run producing the committed report location keeps the rendered
        # goldset summary in step with it; --out elsewhere (check_drift's own
        # temp regeneration) must not touch the tree.
        write_goldset_summary()
    fingerprint_dest = fingerprint_destination(args.retriever, args.out)
    if fingerprint_dest:
        refresh_fingerprint_sidecar(fingerprint_dest, corpus_before)
    print(
        f"candidate duplicate rate: {dup.candidate_duplicate_rows}/{dup.total_rows} rows "
        f"({dup.rate:.0%}) — {dup.candidate_identities} candidate identities"
    )
    conflicts = [i for i in identities_by_key["ssn"] if i.status == "conflict"]
    if conflicts:
        rows = sorted(pid for i in conflicts for pid in i.patient_ids)
        print(f"⚠️  non-mergeable SSN conflicts (shared SSN, conflicting demographics): rows {rows}")
    ambiguous = [i for i in identities_by_key["ssn"] if i.status == "ambiguous"]
    if ambiguous:
        rows = sorted(pid for i in ambiguous for pid in i.patient_ids)
        print(f"⚠️  ambiguous SSN groups (corroborate only via a bridge row, not pairwise): rows {rows}")
    missed = sorted({a for g in gaps for a in g.missed_allergies})
    if missed:
        print(f"⚠️  allergies invisible on at least one chart: {', '.join(missed)}")
    print(
        f"gold-set macro recall {scores.macro_recall:.2f} / "
        f"precision {scores.macro_precision:.2f} ({label})"
    )


if __name__ == "__main__":
    main()
