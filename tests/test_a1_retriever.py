"""
eligibility-assistant `corpus` — the retriever tool, the index and the cap
(SPEC-9 / SPEC-10 / SPEC-11).

Every test opens with the rig's identity assertions (eligibility-assistant-D-66) so the
tool under test and the index it reads are the objects the cap monkeypatches and the
`_INDEX` reads act on.
"""
import builtins
import hashlib
import itertools
import json
import os
import socket
import subprocess
import typing

import pytest
from pydantic import ValidationError

from a1_corpus_rig import app_mod, assert_pinned, policy_index, policy_tool, settings

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(REPO_ROOT, "services", "ai-assistant", "policy_corpus")
FIXTURES = os.path.join(REPO_ROOT, "tests", "fixtures", "a1")
EVAL_JSONL = os.path.join(FIXTURES, "eligibility-assistant-evaluations.jsonl")
CASE_SELECTIONS = os.path.join(FIXTURES, "case_selections.json")


def _manifest() -> list:
    with open(os.path.join(CORPUS, "document-manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)["documents"]


def _index_json() -> list:
    with open(os.path.join(CORPUS, "index.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _cases() -> dict:
    with open(EVAL_JSONL, encoding="utf-8") as fh:
        return {json.loads(line)["id"]: json.loads(line) for line in fh if line.strip()}


def _corpus_digest() -> str:
    h = hashlib.sha256()
    for dirpath, _dirs, files in os.walk(CORPUS):
        for name in sorted(files):
            path = os.path.join(dirpath, name)
            h.update(os.path.relpath(path, CORPUS).encode("utf-8"))
            with open(path, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


def _empty_record(topic, payer, product, state, provenance):
    """The record a stubbed lookup leaves — same shape as the module's own."""
    labels = {axis: (provenance or {}).get(axis, "application_default") for axis in
              ("topic", "payer", "product", "state")}
    return policy_index.LookupRecord(
        topic=topic,
        topic_provenance=labels["topic"],
        payer=payer,
        payer_provenance=labels["payer"],
        product=product,
        product_provenance=labels["product"],
        state=state,
        state_provenance=labels["state"],
        pre_filter_rows=0,
        post_filter_rows=0,
        returned_rows=0,
        cap=settings.a1_retrieval_max_rows,
        truncated=False,
        empty=True,
    )


def _recording_lookup(monkeypatch):
    calls = []

    def _lookup(topic, payer, product, state, *, provenance=None):
        calls.append((topic, payer, product, state))
        return [], _empty_record(topic, payer, product, state, provenance)

    monkeypatch.setattr(policy_index, "lookup", _lookup)
    return calls


# --- SPEC-9 ---------------------------------------------------------------------


def test_tool_arg_topic_only_app_binds_rest(monkeypatch):
    assert_pinned()
    calls = _recording_lookup(monkeypatch)
    tool = policy_tool.make_policy_lookup("aetna", "commercial", "CA")
    # exactly one model-facing argument
    assert list(tool.args.keys()) == ["topic"]
    assert set(tool.args_schema.model_fields) == {"topic"}
    tool.invoke({"topic": "no-coverage-invention"})
    # payer / product / state are the application's, bound at construction
    assert calls == [("no-coverage-invention", "aetna", "commercial", "CA")]
    # the binding is per tool: a second construction carries its own selections
    other = policy_tool.make_policy_lookup("medicare", "original_medicare", "unconfirmed")
    other.invoke({"topic": "coordination-of-benefits"})
    assert calls[-1] == ("coordination-of-benefits", "medicare", "original_medicare", "unconfirmed")
    # the application-bound axes are validated as enum members at construction
    with pytest.raises(ValueError):
        policy_tool.make_policy_lookup("*", "commercial", "CA")
    with pytest.raises(ValueError):
        policy_tool.make_policy_lookup("aetna", "ppo", "CA")


def test_tool_rejects_extra_keys(monkeypatch):
    assert_pinned()
    calls = _recording_lookup(monkeypatch)
    tool = policy_tool.make_policy_lookup("aetna", "commercial", "CA")
    # the explicit schema is what makes an extra key a rejection, not a silent drop
    assert tool.args_schema is policy_tool.PolicyLookupArgs
    assert tool.args_schema.model_config["extra"] == "forbid"
    with pytest.raises(ValidationError):
        tool.invoke({"topic": "no-coverage-invention", "payer": "aetna"})
    # a document id offered as the topic
    with pytest.raises(ValidationError):
        tool.invoke({"topic": "DOC-SYN-EMERGENCY"})
    # free text offered as the topic
    with pytest.raises(ValidationError):
        tool.invoke({"topic": "is this covered today?"})
    assert calls == [], "a rejected call must never reach policy_index.lookup"


def test_topic_enum_equals_manifest_categories():
    assert_pinned()
    literal = set(typing.get_args(policy_tool.PolicyLookupArgs.model_fields["topic"].annotation))
    manifest = {row["category"] for row in _manifest()}
    index_topics = set()
    for entry in _index_json():
        index_topics.update(entry["topics"])
    assert literal == manifest == index_topics
    assert len(literal) == 25
    assert tuple(sorted(literal)) == policy_index.categories()


# --- SPEC-10 --------------------------------------------------------------------


def _forbid(*_args, **_kwargs):
    raise AssertionError("forbidden during a lookup")


def test_in_process_read_only_capped(monkeypatch):
    assert_pinned()
    real_open = builtins.open

    def _read_only_open(file, mode="r", *args, **kwargs):
        if any(flag in str(mode) for flag in ("w", "a", "x", "+")):
            raise AssertionError(f"write-mode open during a lookup: {mode}")
        return real_open(file, mode, *args, **kwargs)

    before = _corpus_digest()
    legal = ("coordination-of-benefits", "medicare", "unconfirmed", "unconfirmed")
    expected_order = [
        row.id for row in policy_index.rank(list(policy_index._filter(*legal)))
    ]
    assert len(expected_order) == 7
    assert set(expected_order) == {
        "DOC-FED-COB-GETTING-STARTED",
        "DOC-FED-COB-OVERVIEW",
        "DOC-FED-COB-PROVIDER-SERVICES",
        "DOC-FED-COB-RECOVERY-OVERVIEW",
        "DOC-FED-MSP-CRS",
        "DOC-FED-MEDIGAP",
        "DOC-SYN-COB-FRONT-DESK",
    }
    with monkeypatch.context() as m:
        m.setattr(socket, "socket", _forbid)  # no network
        m.setattr(subprocess, "Popen", _forbid)  # in-process
        m.setattr(os, "fork", _forbid, raising=False)
        m.setattr(builtins, "open", _read_only_open)  # read-only
        # capped: a legal call with more candidates than the cap
        assert settings.a1_retrieval_max_rows == 5
        rows, record = policy_index.lookup(*legal)
        assert (record.post_filter_rows, record.returned_rows) == (7, 5)
        assert len(rows) == 5
        assert [row.id for row in rows] == expected_order[:5]
        m.setattr(settings, "a1_retrieval_max_rows", 7)
        assert [row.id for row in policy_index.lookup(*legal)[0]] == expected_order
        m.setattr(settings, "a1_retrieval_max_rows", 1)
        assert [row.id for row in policy_index.lookup(*legal)[0]] == expected_order[:1]
        # the by-id application entry under the same guards
        fetched, _by_id = policy_index.fetch_by_id(["DOC-SYN-EMERGENCY", "DOC-FED-EMTALA-CMS"])
        assert [row.id for row in fetched] == ["DOC-SYN-EMERGENCY", "DOC-FED-EMTALA-CMS"]
        # `*` is an index-row value, never a query value
        with pytest.raises(ValueError):
            policy_index.lookup("coordination-of-benefits", "*", "unconfirmed", "unconfirmed")
        with pytest.raises(ValueError):
            policy_index.lookup("coordination-of-benefits", "medicare", "*", "unconfirmed")
        with pytest.raises(ValueError):
            policy_index.lookup("coordination-of-benefits", "medicare", "unconfirmed", "*")
        with pytest.raises(ValueError):
            policy_index.lookup("*", "medicare", "unconfirmed", "unconfirmed")
    assert _corpus_digest() == before


def test_cap_binds_on_a_legal_call():
    assert_pinned()
    # (i) the sizing rule, recomputed from the vendored manifest and files
    recomputed = 0
    for row in _manifest():
        with open(os.path.join(CORPUS, row["path"]), encoding="utf-8") as fh:
            text = fh.read()
        total = sum(
            len(value.encode("utf-8"))
            for value in (
                row["document_id"],
                row["title"],
                row["section_labels"],
                row["version_effective"],
                row["retrieval_date"],
                text,
            )
        )
        recomputed = max(recomputed, total)
    assert recomputed == policy_index.MAX_ROW_BYTES == 2789
    assert policy_index.PROMPT_RESERVE_BYTES == 5000
    cap = settings.a1_retrieval_max_rows
    assert cap >= 1
    assert cap * policy_index.MAX_ROW_BYTES + policy_index.PROMPT_RESERVE_BYTES <= (
        settings.llm_max_input_tokens
    )
    # (ii) the cap has a legal exercise: driven over the loaded index, never a re-parse
    index = policy_index._INDEX
    assert index is not None
    largest = 0
    for topic, payer, product, state in itertools.product(
        index.categories, policy_index.PAYERS, policy_index.PRODUCTS, policy_index.STATES
    ):
        largest = max(largest, len(list(policy_index._filter(topic, payer, product, state))))
    assert largest > cap


@pytest.mark.parametrize("case_id", ["EVAL-023"])
def test_unconfirmed_axis_non_filtering(case_id):
    assert_pinned()
    case = _cases()[case_id]
    assert "DOC-PAY-UHC-ELIG-REFERRALS" in case["expected_source_ids"]
    entry = next(e for e in _index_json() if e["document_id"] == "DOC-PAY-UHC-ELIG-REFERRALS")
    assert entry["needs_product_confirmation"] is True
    topic = "payer-eligibility-public"
    # `unconfirmed` on product and state does not filter: the citation-only row is returned
    ids = [r.id for r in policy_index.lookup(topic, "unitedhealthcare", "unconfirmed", "unconfirmed")[0]]
    assert "DOC-PAY-UHC-ELIG-REFERRALS" in ids
    # ... and neither does a confirmed value the row carries
    ids = [r.id for r in policy_index.lookup(topic, "unitedhealthcare", "commercial", "other_us")[0]]
    assert "DOC-PAY-UHC-ELIG-REFERRALS" in ids
    # a confirmed value the row does not carry DOES filter — that is what makes
    # `unconfirmed` an absence of a filter rather than a wildcard the row must match
    ids = [r.id for r in policy_index.lookup(topic, "unitedhealthcare", "medicaid_mco", "other_us")[0]]
    assert "DOC-PAY-UHC-ELIG-REFERRALS" not in ids
    # the state axis, on the one California-only public page
    assert "DOC-PAY-ANTHEM-CA-ELIG" in [
        r.id for r in policy_index._filter(topic, "anthem_blue", "unconfirmed", "unconfirmed")
    ]
    assert "DOC-PAY-ANTHEM-CA-ELIG" in [
        r.id for r in policy_index._filter(topic, "anthem_blue", "unconfirmed", "CA")
    ]
    assert "DOC-PAY-ANTHEM-CA-ELIG" not in [
        r.id for r in policy_index._filter(topic, "anthem_blue", "unconfirmed", "other_us")
    ]
    # the empty result on a foreign payer is a filter outcome, not a mismatch verdict
    empty_rows, empty_record = policy_index.lookup(
        "medicaid-managed-care", "aetna", "commercial", "unconfirmed"
    )
    assert empty_rows == []
    assert empty_record.empty is True


# --- SPEC-11 --------------------------------------------------------------------


def test_index_covers_every_row():
    assert_pinned()
    manifest = {row["document_id"]: row for row in _manifest()}
    entries = {entry["document_id"]: entry for entry in _index_json()}
    assert set(entries) == set(manifest), "index.json and the manifest name the same rows"
    index = policy_index._INDEX
    assert len(index.rows) == 87
    rows = {row.id: row for row in index.rows}
    assert set(rows) == set(manifest)
    for doc_id, m in manifest.items():
        row = rows[doc_id]
        # the row shape of eligibility-assistant-D-61: one row per document, verbatim fields
        assert row.title == m["title"]
        assert row.section == m["section_labels"]
        assert row.version == m["version_effective"]
        assert row.retrieval_date == m["retrieval_date"]
        with open(os.path.join(CORPUS, m["path"]), encoding="utf-8") as fh:
            assert row.section_text == fh.read()
        assert row["section-text"] == row.section_text and row["id"] == doc_id
        # indexed under at least one argument set
        entry = entries[doc_id]
        assert m["category"] in entry["topics"]
        assert entry["sections"] == m["section_labels"].split("|")
        payer = policy_index.PAYERS[0] if entry["payers"] == "*" else entry["payers"][0]
        product = "unconfirmed" if entry["products"] == "*" else entry["products"][0]
        state = "unconfirmed" if entry["states"] == "*" else entry["states"][0]
        found = [r.id for r in policy_index._filter(m["category"], payer, product, state)]
        assert doc_id in found, doc_id
    # the two curation obligations carried for later tickets, asserted where the artifact lands
    assert entries["DOC-SYN-NEVER-STATE"]["payers"] == "*"
    assert entries["DOC-SYN-NEVER-STATE"]["products"] == "*"
    assert entries["DOC-SYN-NEVER-STATE"]["states"] == "*"
    for payer in policy_index.PAYERS:
        assert [
            r.id
            for r in policy_index.lookup("front-desk-scripts", payer, "unconfirmed", "unconfirmed")[0]
        ] == [
            "DOC-SYN-NEVER-STATE"
        ]


def test_case_selections_closed():
    assert_pinned()
    cases = _cases()
    manifest_ids = {row["document_id"] for row in _manifest()}
    categories = set(policy_index.categories())
    retrievable = {
        case_id
        for case_id, case in cases.items()
        if any(src in manifest_ids or src.startswith("procedures/") for src in case["expected_source_ids"])
    }
    assert len(retrievable) == 27
    with open(CASE_SELECTIONS, encoding="utf-8") as fh:
        selections = json.load(fh)
    assert set(selections) == retrievable
    for case_id, sel in selections.items():
        assert set(sel) == {"question_type", "payer", "product", "state", "topic"}, case_id
        assert sel["question_type"] in policy_index.QUESTION_TYPES, case_id
        assert sel["payer"] in policy_index.PAYERS, case_id
        assert sel["product"] in policy_index.PRODUCTS, case_id
        assert sel["state"] in policy_index.STATES, case_id
        assert sel["topic"] in categories, case_id
