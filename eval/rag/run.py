"""
CLI entry point for the RAG retrieval eval (RIV-160).

    python eval/rag/run.py                     # embedding retriever (needs
                                               # eval/rag/requirements.txt)
    python eval/rag/run.py --retriever stub    # torch-free oracle run

Writes eval/rag/REPORT.md. Corpus embeddings are cached under
eval/rag/.cache/ and reused across runs (quota guard: embed once).
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import data  # noqa: E402
import metrics  # noqa: E402
import report  # noqa: E402
import retriever as retriever_mod  # noqa: E402

MATCH_KEYS = ("none", "name_dob", "ssn")


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
    args = parser.parse_args()

    seed_dir = os.path.join(REPO_ROOT, "db", "seed")
    patients = data.load_patients(os.path.join(seed_dir, "patients.csv"))
    encounters = data.load_encounters(os.path.join(seed_dir, "encounters.csv"))
    cases = data.load_goldset(os.path.join(seed_dir, "goldset.json"))

    identities_by_key = {
        key: data.resolve_identities(patients, key) for key in MATCH_KEYS
    }
    dup = metrics.duplicate_rate(patients, identities_by_key["ssn"])

    gaps = []
    for identity in identities_by_key["ssn"]:
        if len(identity.patient_ids) > 1:
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
    print(
        f"duplicate rate: {dup.duplicate_rows}/{dup.total_rows} rows "
        f"({dup.rate:.0%}) — {dup.distinct_humans} humans"
    )
    missed = sorted({a for g in gaps for a in g.missed_allergies})
    if missed:
        print(f"⚠️  allergies invisible on at least one chart: {', '.join(missed)}")
    print(
        f"gold-set macro recall {scores.macro_recall:.2f} / "
        f"precision {scores.macro_precision:.2f} ({label})"
    )


if __name__ == "__main__":
    main()
