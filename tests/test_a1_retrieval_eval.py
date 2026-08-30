"""
eligibility-assistant `retrieval-eval` — the recall baseline and the ranking unit
(SPEC-64 / SPEC-66).

`test_recall_at_cap_per_case_min_headline` reports, for every acceptance case that names
a retrievable source, the recall of those sources within the configured row cap, and the
minimum as the headline; it asserts no floor (eligibility-assistant-D-49). The numbers it
prints are the SPEC-65 delivery record.

`test_ranking_isolated_from_filtering` drives `_filter` and then `rank`, never `lookup`,
so the cap cannot truncate the set SPEC-66 speaks of: substituting the ranking unit
changes the order of the filtered set and never its membership.

Every test opens with the rig's identity assertions (eligibility-assistant-D-66).
"""
import json
import os

from a1_corpus_rig import assert_pinned, policy_index, settings

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(REPO_ROOT, "services", "ai-assistant", "policy_corpus")
FIXTURES = os.path.join(REPO_ROOT, "tests", "fixtures", "a1")

# Three named buckets, each ≥ 2 rows before any comparison so a reordering can be
# observed at all. No legal bucket mixes a tier-5 row with any other tier — tier 5 is the
# category `payer-training-summary` alone and a bucket's topic *is* one category.
RANKING_BUCKETS = (
    ("coordination-of-benefits", "medicare", "unconfirmed", "unconfirmed"),
    ("medicaid-managed-care", "medicaid", "unconfirmed", "unconfirmed"),
    ("payer-eligibility-public", "humana", "unconfirmed", "unconfirmed"),
)


# The deterministic turns (eligibility-assistant-D-19): no model chooses their citations,
# so their sources are fetched by id from the reason table, not looked up. The `emergency`
# row adds the cheat sheet when the turn's question type is `emergency`.
REASON_CITATIONS = {
    "EVAL-012": ("DOC-SYN-PRIVACY-FD",),
    "EVAL-014": ("DOC-SYN-NO-INVENTION",),
    "EVAL-016": ("DOC-FED-EMTALA-CMS", "DOC-SYN-EMERGENCY"),
    "EVAL-017": ("DOC-SYN-SPEND-STOP",),
    "EVAL-018": ("DOC-SYN-MODEL-FAILURE",),
    "EVAL-024": ("DOC-FED-EMTALA-CMS", "DOC-SYN-EMERGENCY"),
}
CHEAT_SHEET = "DOC-COVERAGE-QUESTION-CHEAT-SHEET"


def _manifest_by_path():
    with open(os.path.join(CORPUS, "document-manifest.json"), encoding="utf-8") as fh:
        documents = json.load(fh)["documents"]
    return {doc["path"]: doc["document_id"] for doc in documents}


def _cases():
    path = os.path.join(FIXTURES, "eligibility-assistant-evaluations.jsonl")
    with open(path, encoding="utf-8") as fh:
        return {json.loads(line)["id"]: json.loads(line) for line in fh if line.strip()}


def _selections():
    with open(os.path.join(FIXTURES, "case_selections.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _retrievable(expected_source_ids, by_path):
    """The expected sources that are retrievable (eligibility-assistant-D-12).

    A manifest `DOC-*` id is retrieved and cited; a `procedures/*.md` path is the manifest
    row it is vendored as and is asserted the same way; a `policies/*.md` path governs
    behaviour and is asserted as the outcome, never as a citation; `evaluations/…` is the
    corpus gate. Only the first two have a recall.
    """
    out = []
    for source in expected_source_ids:
        if source.startswith("DOC-"):
            out.append(source)
        elif source in by_path:
            out.append(by_path[source])
    return out


def test_recall_at_cap_per_case_min_headline(capsys):
    assert_pinned()
    by_path = _manifest_by_path()
    cases = _cases()
    selections = _selections()
    cap = settings.a1_retrieval_max_rows

    # SPEC-64 is measured over the acceptance cases that name a retrievable source: the
    # five the harness assigns to the gateway suite and the corpus gate (EVAL-010/011/
    # 029/030 name `policies/access-control-matrix.md` only, EVAL-031 the fixtures README)
    # have no recall to report and carry no selections.
    assert set(selections) <= set(cases)
    assert len(selections) == 27
    assert sorted(set(cases) - set(selections)) == [
        "EVAL-010",
        "EVAL-011",
        "EVAL-029",
        "EVAL-030",
        "EVAL-031",
    ]

    table = []
    for case_id in sorted(selections):
        expected = _retrievable(cases[case_id]["expected_source_ids"], by_path)
        assert expected, case_id

        if case_id in REASON_CITATIONS:
            citations = list(REASON_CITATIONS[case_id])
            if selections[case_id]["question_type"] == "emergency":
                citations.append(CHEAT_SHEET)
            rows, _record = policy_index.fetch_by_id(citations)
            path = "by-id"
        else:
            selection = selections[case_id]
            rows, _record = policy_index.lookup(
                selection["topic"],
                selection["payer"],
                selection["product"],
                selection["state"],
            )
            path = "lookup"

        returned = {row.id for row in rows}
        hit = sorted(set(expected) & returned)
        recall = len(hit) / len(expected)
        assert 0.0 <= recall <= 1.0, case_id
        table.append((case_id, path, len(expected), len(hit), recall))

    headline_recall = min(row[4] for row in table)
    headline_case = min((row for row in table if row[4] == headline_recall), key=lambda r: r[0])[0]
    assert headline_recall == min(row[4] for row in table)
    assert any(row[4] == headline_recall for row in table)

    print("")
    print(f"recall@{cap} over {len(table)} acceptance cases naming a retrievable source")
    print(f"{'case':<10} {'path':<7} {'expected':>8} {'hit':>4} {'recall':>7}")
    for case_id, path, n_expected, n_hit, recall in table:
        print(f"{case_id:<10} {path:<7} {n_expected:>8} {n_hit:>4} {recall:>7.2f}")
    print(f"min recall@{cap} = {headline_recall:.2f} ({headline_case})")
    # no floor is asserted (eligibility-assistant-D-49): the number is the baseline a
    # follow-on item cites, not a gate this suite enforces.


def test_ranking_isolated_from_filtering():
    assert_pinned()
    for bucket in RANKING_BUCKETS:
        rows = list(policy_index._filter(*bucket))
        assert len(rows) >= 2, bucket

        default_order = [row.id for row in policy_index.rank(rows)]

        # The substituted unit orders the rows itself and never delegates to the default:
        # a ranker defined as "the default, reversed" would move with a broken default and
        # could not show a membership change at all.
        def _by_id_desc(candidates):
            return sorted(candidates, key=lambda row: row.id, reverse=True)

        substituted_order = [row.id for row in policy_index.rank(rows, ranker=_by_id_desc)]

        # membership never moves ...
        assert set(substituted_order) == set(default_order), bucket
        assert len(substituted_order) == len(default_order), bucket
        # ... and the order does
        assert substituted_order != default_order, bucket

        # the default unit is still the eligibility-assistant-D-62 key — tier rank asc,
        # `retrieval_date` desc, `document_id` asc — recomputed here from row fields, so
        # filtering is not what ordered these rows and `ranker=None` is the same unit
        entries = policy_index._current().entries
        expected_order = [
            row.id
            for row in sorted(
                rows,
                key=lambda row: (
                    entries[row.id].tier,
                    tuple(-ord(ch) for ch in row.retrieval_date),
                    row.id,
                ),
            )
        ]
        assert default_order == expected_order, bucket
        assert default_order == [row.id for row in policy_index.rank(rows, ranker=None)], bucket
