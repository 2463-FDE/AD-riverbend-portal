"""
eligibility-assistant `corpus` — the five-tier rule and the ranking key (SPEC-43),
the 1a half of the conflict tests. The EVAL-007/013/020/023 turn tests join in `turn`.

Every test opens with the rig's identity assertions (eligibility-assistant-D-66) so
`tier` and `rank` are the pinned module's.
"""
import collections
import json
import os

from a1_corpus_rig import assert_pinned, policy_index

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(REPO_ROOT, "services", "ai-assistant", "policy_corpus")

TIER_1_IDS = {
    "DOC-FED-EMTALA-CMS",
    "DOC-FED-EMTALA-ER-RIGHTS",
    "DOC-FED-EMTALA-42CFR-489-24",
    "DOC-FED-EMTALA-CRS",
    "DOC-FED-EMTALA-OIG",
    "DOC-FED-HIPAA-164-502-MIN-NEC",
    "DOC-FED-HIPAA-164-514",
    "DOC-FED-HIPAA-164-506-TPO",
    "DOC-FED-HIPAA-164-508-AUTH",
}


def _manifest() -> list:
    with open(os.path.join(CORPUS, "document-manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)["documents"]


def test_tier_rank_in_code():
    assert_pinned()
    manifest = _manifest()
    assert len(manifest) == 87
    # the tier function reads license_disposition prefix × category, over the whole manifest
    tiers = {row["document_id"]: policy_index.tier(row) for row in manifest}
    partition = collections.Counter(tiers.values())
    assert partition == {1: 9, 2: 32, 3: 16, 4: 23, 5: 7}
    assert {doc_id for doc_id, t in tiers.items() if t == 1} == TIER_1_IDS
    assert tiers["DOC-FED-EMTALA-CMS"] == 1  # no id fragment — the rule is license × category
    assert tiers["DOC-FED-42CFR-435-POINTER"] == 2  # bare `42CFR` fragment, medicaid category
    assert tiers["DOC-FED-42CFR-438-POINTER"] == 2
    assert tiers["DOC-SYN-EMERGENCY"] == 4
    assert tiers["DOC-SYN-PRIVACY-FD"] == 4
    assert tiers["DOC-COVERAGE-QUESTION-CHEAT-SHEET"] == 4
    # EVAL-006's stale set is tier-4-only: the recency note is original synthetic, not a summary
    assert tiers["DOC-SYN-CITATION-RECENCY"] == 4
    assert {doc_id for doc_id, t in tiers.items() if t == 5} == {
        row["document_id"] for row in manifest if row["category"] == "payer-training-summary"
    }
    # the by-id form resolves through the loaded index
    assert policy_index.tier("DOC-FED-EMTALA-CMS") == 1
    assert policy_index.tier("DOC-SYN-UHC-TRAINING-SUMMARY") == 5

    # rank: reversed manifest order in, eligibility-assistant-D-62's key out
    index = policy_index._INDEX
    by_id = {row.id: row for row in index.rows}
    rows_in = [by_id[row["document_id"]] for row in reversed(manifest)]
    ranked = policy_index.rank(rows_in)
    assert len(ranked) == 87 and {r.id for r in ranked} == set(by_id)
    keys = [(tiers[r.id], r.retrieval_date, r.id) for r in ranked]
    for (t1, d1, id1), (t2, d2, id2) in zip(keys, keys[1:]):
        assert (t1, d1, id1) != (t2, d2, id2)
        assert t1 <= t2
        if t1 == t2:
            assert d1 >= d2  # newest retrieval_date first
            if d1 == d2:
                assert id1 < id2  # then document_id ascending
    # one same-tier pair whose input order is the reverse of the key
    pair = policy_index.rank([by_id["DOC-FED-HIPAA-164-514"], by_id["DOC-FED-EMTALA-CMS"]])
    assert [r.id for r in pair] == ["DOC-FED-EMTALA-CMS", "DOC-FED-HIPAA-164-514"]
    # rank does not mutate or drop
    assert [r.id for r in rows_in] == [row["document_id"] for row in reversed(manifest)]
    # EVAL-024: the regulation ranks above the cheat sheet, whatever the input order
    order = [
        r.id
        for r in policy_index.rank(
            [by_id["DOC-COVERAGE-QUESTION-CHEAT-SHEET"], by_id["DOC-FED-EMTALA-CMS"]]
        )
    ]
    assert order == ["DOC-FED-EMTALA-CMS", "DOC-COVERAGE-QUESTION-CHEAT-SHEET"]
    # a lower-tier source never overrides a higher-tier one: the ordering site is `rank`
    # and `lookup` applies it before the cap
    emergency, _record = policy_index.lookup(
        "emergency-care-boundary", "aetna", "commercial", "unconfirmed"
    )
    emergency_tiers = [tiers[r.id] for r in emergency]
    assert emergency_tiers == sorted(emergency_tiers)
    assert emergency_tiers[0] == 1


# --------------------------------------------------------------------------- #
# eligibility-assistant `turn` — the 1c half: the wired conflict/insufficiency
# outcomes (SPEC-42, EVAL-007/020/013/023). The tier function above is `corpus`'s
# half; what lands here is the turn that consumes it.
# --------------------------------------------------------------------------- #
import json as _json

import pytest


@pytest.mark.parametrize(
    "case_id", ["EVAL-007", "EVAL-020", "EVAL-013", "EVAL-023"]
)
def test_eval_007_020_013_023(case_id, monkeypatch):
    """SPEC-42 — conflicting sources are cited, stated through the catalog
    template, refused a definitive answer and routed to a person; a question no
    approved applicable document (or only citation-only pages on unconfirmed
    axes) can answer refuses definitively. Conflicting sources are never
    blended: the reply's coverage line is a catalog template, not a synthesis.
    """
    from a1_rig import (
        MEMBER_ID,
        install_model,
        install_payer,
        post,
        retrieved_ids,
        text_body,
        tool_use_body,
        topic,
        turn,
        verdict,
    )

    assert_pinned()

    def decision(citation_ids, action_ids):
        return text_body(
            _json.dumps(
                {"citation_ids": list(citation_ids), "action_ids": list(action_ids)}
            )
        )

    if case_id in ("EVAL-007", "EVAL-020"):
        # Conflict detection is model₂'s bounded choice of `state_conflict`; the
        # consequences are code. EVAL-007's second "source" (the clinic
        # procedure) is outside the corpus, so its citation set is the whole
        # retrieved set — one row; EVAL-020 cites two of its five.
        cited = retrieved_ids(case_id)[: (1 if case_id == "EVAL-007" else 2)]
        install_model(
            monkeypatch,
            tool_use_body("policy_lookup", {"topic": topic(case_id)}),
            decision(cited, ["state_conflict", "escalate"]),
        )
        install_payer(monkeypatch, verdict("active", payer="Payer"))
        body = post(turn(case_id, facts={"insurance_id": MEMBER_ID})).json()
        assert body["outcome"] == "conflict"
        assert [c["document_id"] for c in body["citations"]] == cited
        # Stated through the catalog template, never blended into a verdict.
        assert "DISAGREE" in body["reply"].split("\n")[0].upper()
        assert "ACTIVE" not in body["reply"].split("\n")[0].upper()
        assert "escalate" in _json.dumps(body["reply"]).lower() or "supervisor" in body["reply"].lower()
        return

    # EVAL-013 / EVAL-023 — the in-code applicability check on a turn with no
    # payer verdict: no tier-1..3 row (013), or only needs-product-confirmation
    # citation-only pages on unconfirmed axes (023) -> refuse_definitive.
    install_model(
        monkeypatch,
        tool_use_body("policy_lookup", {"topic": topic(case_id)}),
        decision(retrieved_ids(case_id)[:1], ["escalate"]),
    )
    payer = install_payer(monkeypatch, verdict("active", payer="Payer"))
    # A question about a product, not a member: no id, no payer call. The visit
    # holds an id (the agent path requires one) but the intent buys no lookup.
    body = post(
        turn(
            case_id,
            message="does this plan cover out-of-state visits?",
            facts={"insurance_id": MEMBER_ID},
        )
    ).json()
    assert payer.calls == []
    assert body["outcome"] == "refuse_definitive"
    first_line = body["reply"].split("\n")[0].upper()
    assert "ACTIVE" not in first_line
    assert "escalate" in _json.dumps(body["reply"]).lower() or "supervisor" in body["reply"].lower()
