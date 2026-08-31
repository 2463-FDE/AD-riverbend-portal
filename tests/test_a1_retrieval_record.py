"""
eligibility-assistant `retrieval-eval` — the lookup record (SPEC-63).

Every retriever lookup leaves a `LookupRecord`: the resolved value of each filter axis
with its provenance, the pre-filter / post-filter / returned counts, the cap, and the
`truncated` / `empty` flags. The record is returned to the caller and emitted once per
call as one structured log line — the log line is the record's only emitter in this item
(eligibility-assistant-D-68).

Every test opens with the rig's identity assertions (eligibility-assistant-D-66) so the
tool under test, the index it reads and the settings the cap monkeypatches are the one
module object.
"""
import json
import logging

import pytest
from pydantic import ValidationError

from a1_corpus_rig import assert_pinned, policy_index, policy_tool, settings

# The 7-row bucket `corpus`'s test_in_process_read_only_capped already pins.
COB = ("coordination-of-benefits", "medicare", "unconfirmed", "unconfirmed")
# Legal on both filtering axes and empty on both: the seven `medicaid-managed-care` rows
# are Medicaid/CHIP publishers with state-Medicaid applicability, so no curation of
# index.json may give them payer `aetna` or product `commercial`.
EMPTY = ("medicaid-managed-care", "aetna", "commercial", "unconfirmed")
EMERGENCY_IDS = ("DOC-FED-EMTALA-CMS", "DOC-SYN-EMERGENCY")

FIELDS = frozenset(
    {
        "topic",
        "topic_provenance",
        "payer",
        "payer_provenance",
        "product",
        "product_provenance",
        "state",
        "state_provenance",
        "pre_filter_rows",
        "post_filter_rows",
        "returned_rows",
        "cap",
        "truncated",
        "empty",
    }
)
PROVENANCE = frozenset({"clerk_selection", "model_topic", "application_default"})

TOOL_PROVENANCE = {
    "topic": "model_topic",
    "payer": "clerk_selection",
    "product": "clerk_selection",
    "state": "clerk_selection",
}


def _logged(caplog):
    """The records the module emitted, parsed from its one structured log line."""
    out = []
    for rec in caplog.records:
        if rec.msg == policy_index.RECORD_LOG_MESSAGE:
            out.append(json.loads(rec.args[0] if rec.args else ""))
    return out


def test_record_fields_and_provenance(caplog, monkeypatch):
    assert_pinned()
    caplog.set_level(logging.INFO)
    total = len(policy_index._current().rows)

    # --- success + provenance: the tool-bound lookup ---------------------------
    caplog.clear()
    tool = policy_tool.make_policy_lookup(COB[1], COB[2], COB[3])
    rows = tool.invoke({"topic": COB[0]})
    assert rows, "the bucket is non-empty"
    logged = _logged(caplog)
    assert len(logged) == 1, "exactly one record per lookup"
    record = logged[0]
    assert set(record) == FIELDS
    assert (record["topic"], record["payer"], record["product"], record["state"]) == COB
    for axis, label in TOOL_PROVENANCE.items():
        assert record[axis + "_provenance"] == label
    assert record["pre_filter_rows"] == total
    assert record["post_filter_rows"] == 7
    assert record["returned_rows"] == len(rows) == settings.a1_retrieval_max_rows
    assert record["empty"] is False

    # --- by-id: no filter axes ------------------------------------------------
    caplog.clear()
    fetched, by_id = policy_index.fetch_by_id(EMERGENCY_IDS)
    assert [row.id for row in fetched] == list(EMERGENCY_IDS)
    assert _logged(caplog) == [by_id.as_dict()]
    for axis in ("topic", "payer", "product", "state"):
        assert by_id.as_dict()[axis] is None
        assert by_id.as_dict()[axis + "_provenance"] == "application_default"
    assert by_id.pre_filter_rows == total
    assert by_id.post_filter_rows == by_id.returned_rows == len(EMERGENCY_IDS)
    assert by_id.cap == settings.a1_retrieval_max_rows
    assert by_id.truncated is False
    assert by_id.empty is False

    # --- direct call: every unlabelled axis is application_default -------------
    caplog.clear()
    direct_rows, direct = policy_index.lookup(*COB)
    assert [row.id for row in direct_rows] == [row["id"] for row in rows]
    assert _logged(caplog) == [direct.as_dict()]
    for axis in ("topic", "payer", "product", "state"):
        assert direct.as_dict()[axis + "_provenance"] == "application_default"

    # --- truncated ------------------------------------------------------------
    caplog.clear()
    monkeypatch.setattr(settings, "a1_retrieval_max_rows", 1)
    cut_rows, cut = policy_index.lookup(*COB)
    assert _logged(caplog) == [cut.as_dict()]
    assert cut.truncated is True
    assert cut.returned_rows == len(cut_rows) == 1
    assert cut.post_filter_rows == 7
    assert cut.cap == 1
    assert cut.empty is False
    monkeypatch.undo()

    # --- empty: the filter's emptiness, not an empty index ---------------------
    caplog.clear()
    empty_rows, empty = policy_index.lookup(*EMPTY)
    assert empty_rows == []
    assert _logged(caplog) == [empty.as_dict()]
    assert empty.empty is True
    assert empty.post_filter_rows == 0
    assert empty.returned_rows == 0
    assert empty.truncated is False
    assert empty.pre_filter_rows == total > 0

    # every provenance label the module ever writes is from the closed set
    for entry in (record, by_id.as_dict(), direct.as_dict(), cut.as_dict(), empty.as_dict()):
        for axis in ("topic", "payer", "product", "state"):
            assert entry[axis + "_provenance"] in PROVENANCE


# The two planted strings (eligibility-assistant-SPEC-63 §3 negative). Neither can enter
# a record by any route: the ticket lands dark and reads no clerk text and no member id,
# so each is offered to the tool as `topic` and is rejected by the `PolicyLookupArgs`
# `Literal` before a record exists — then asserted absent from every record and every log
# line the three legal paths produce.
PLANTED_MEMBER_ID = "AETNA5501"
PLANTED_CLERK_SENTENCE = "is this covered today for the patient at the front desk?"


def _closed_vocabulary():
    index = policy_index._current()
    return (
        set(index.categories)
        | set(policy_index.PAYERS)
        | set(policy_index.PRODUCTS)
        | set(policy_index.STATES)
        | set(policy_index.PROVENANCE_LABELS)
    )


def test_record_metadata_only_every_path(caplog, monkeypatch):
    assert_pinned()
    caplog.set_level(logging.INFO)
    index = policy_index._current()
    vocabulary = _closed_vocabulary()

    # the plant: neither string can reach a record — the schema rejects it first
    caplog.clear()
    tool = policy_tool.make_policy_lookup(COB[1], COB[2], COB[3])
    for planted in (PLANTED_MEMBER_ID, PLANTED_CLERK_SENTENCE):
        with pytest.raises(ValidationError):
            tool.invoke({"topic": planted})
    assert _logged(caplog) == [], "a rejected call leaves no record"

    scanned = 0
    for label, call in (
        ("success", lambda: tool.invoke({"topic": COB[0]})),
        ("empty", lambda: policy_index.lookup(*EMPTY)),
        ("truncated", lambda: policy_index.lookup(*COB)),
    ):
        caplog.clear()
        with monkeypatch.context() as m:
            if label == "truncated":
                m.setattr(settings, "a1_retrieval_max_rows", 1)
            call()
        logged = _logged(caplog)
        assert len(logged) == 1, label
        record = logged[0]
        serialised = json.dumps(record)
        line = next(r.getMessage() for r in caplog.records if r.msg == policy_index.RECORD_LOG_MESSAGE)

        # (i) no key outside the fourteen-field closed set
        assert set(record) == FIELDS, label
        # (ii) every value is a closed-vocabulary member, an int, a bool or None —
        #      there is no field a free string can occupy
        for key, value in record.items():
            assert value is None or isinstance(value, (bool, int)) or value in vocabulary, (
                label,
                key,
            )
        # (iii) no document text, title, section label or path
        for row in index.rows:
            assert row.title not in serialised, (label, row.id)
            assert row.section not in serialised, (label, row.id)
            assert row.section_text[:60] not in serialised, (label, row.id)
        for entry_id in index.entries:
            assert entry_id not in serialised, (label, entry_id)
        # (iv) neither planted string, in the record or in the emitted line
        for planted in (PLANTED_MEMBER_ID, PLANTED_CLERK_SENTENCE):
            assert planted not in serialised, label
            assert planted not in line, label
        scanned += 1

    assert scanned == 3, "the success, empty and truncated paths are all scanned"
