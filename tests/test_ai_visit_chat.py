"""Tests for the ai-assistant /visit-chat endpoint (ADR 0011).

This endpoint is the one free-text surface in the service, so the boundary tests
are the load-bearing ones (CLAUDE.md §5). The invariants, in order of harm if
they regressed:

  * the LLM decides NOTHING that matters. It never sees the clerk's message, it
    cannot cause an outbound PHI-bearing call, and it cannot author or revise a
    coverage verdict — its whole output is a list of catalog ids, gated
    server-side against the ids the status justifies;
  * an unconfirmed check never renders as a denial (ADR 0010's tri-state, carried
    into the words a clerk reads);
  * no LLM fault can destroy a coverage verdict that already cost a payer call.
    Every failure degrades to the deterministic action list and answers 200. The
    two facts the status code used to carry are now separate fields, because a
    fault looks like a success from outside: ``llm_egress`` is SPEND (the
    gateway's refund signal) and ``assistant`` is HEALTH. Neither is inferred
    from the exception class — ``llm_client.LLMError.egressed`` is set at the
    raise site, since ``LLMConfigError`` is raised both by local gates and by
    Bedrock's own rejection of a request that already crossed the boundary;
  * the member-id recogniser accepts any CASE a human types and nothing else.
    Case-folding across Unicode would widen an ASCII catalog into homoglyphs,
    which is a wrong match, and a wrong match is the unsafe direction.

The LLM is faked at the complete_structured seam (no network, no key), mirroring
the real seam's parse step. The eligibility client is faked at the module seam.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

# eligibility-assistant re-seam (eligibility-assistant-D-66): this file no longer
# loads its own `app`. It shares the ONE module set `tests/a1_rig.py` publishes, for
# the reason that rig exists — `agent_binding` and `agent_turn` are bare-name imports
# that neither preamble pinned, so two app copies silently shared whichever loaded
# first, and a fake installed on one copy's `llm_client` was not the object the other
# copy's binding egressed through. One set, one seam, one place to patch.
import conftest  # noqa: F401  (kept: tests below reach conftest.load_module)
from conftest import load_module
from a1_rig import (  # noqa: F401
    TEST_INTERNAL_SECRET,
    app_mod,
    assert_pinned,
    client,
    schemas,
)

visit_templates = app_mod.visit_templates

MEMBER_ID = "AETN1224"
ACTIVE_VERDICT = {
    "active": True,
    "status": "active",
    "payer": "edi.example.com",
    "raw_status": "1",
    "checked_at": "2026-07-26T10:00:00Z",
    "reason": None,
}
UNKNOWN_VERDICT = {
    "active": None,
    "status": "unknown",
    "payer": "edi.example.com",
    "raw_status": None,
    "checked_at": "2026-07-26T10:00:00Z",
    "reason": "eligibility check failed",
}
# NOTE neither constant above carries `observed_at`. That is deliberate and load
# bearing: a verdict with no observation stamp of OUR OWN is not reusable (an
# older ai-assistant wrote it, or a caller hand-built the facts), so every test
# that expects a lookup keeps expecting one. Reuse is opted into per test with
# `_observed`, which is the only thing that makes a verdict fresh.


def _observed(verdict, age_seconds=0.0):
    """A copy of `verdict` stamped as observed `age_seconds` ago by this service."""
    stamp = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return {**verdict, "observed_at": stamp.isoformat()}


class _Recorder(list):
    """A list that also carries the test's control handles (a bare list cannot
    take attributes)."""


# eligibility-assistant: the model seam moved. The visit-chat turn no longer calls
# `complete_structured` — it runs the agent path, whose only egress is
# `llm_client._call`, which resolves `client.messages.create` at call time. So the
# fake is a scripted BEDROCK client, and the whole pre-egress stack (`_enforce_char
# _cap`, `_enforce_budget`, `_require_bearer_token`) stays live in front of it. What
# a test controls is what the model ANSWERS, exactly as before.
A1_DEFAULT_TOPIC = "eligibility-verification"


def _tool_use_body(topic):
    return {
        "id": "msg-tool",
        "content": [
            {"type": "tool_use", "id": "toolu-1", "name": "policy_lookup", "input": {"topic": topic}}
        ],
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "stop_reason": "tool_use",
    }


def _decision_body(citation_ids, action_ids):
    return {
        "id": "msg-text",
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {"citation_ids": list(citation_ids), "action_ids": list(action_ids)}
                ),
            }
        ],
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "stop_reason": "end_turn",
    }


_OFFERED_DOC_RE = re.compile(r"^- (DOC-[A-Z0-9-]+)$", re.MULTILINE)
_STATUS_RE = re.compile(r"Eligibility status from the payer for this turn: (\S+)")


@pytest.fixture()
def fake_llm(monkeypatch):
    """Capture the bodies that egress and answer with whatever the test queues.

    Default answer is the deterministic required set for the turn's outcome, so a
    test that cares about routing does not also have to care about selection — the
    same contract the pre-eligibility-assistant fixture had, read off model₂'s own
    message instead of off the single prompt.
    """
    calls = _Recorder()
    queued = {"ids": None}

    class _Scripted:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            calls.append({"prompt": json.dumps(kwargs["messages"]), "system": kwargs.get("system"),
                          "kwargs": kwargs})
            # Which call this is, read off the CONVERSATION rather than off a
            # counter: the fixture serves more than one turn, and a counter would make
            # the second turn's model₁ look like the first turn's model₂.
            has_tool_result = any(
                isinstance(block, dict) and block.get("type") == "tool_result"
                for entry in kwargs["messages"]
                for block in (entry["content"] if isinstance(entry["content"], list) else [])
            )
            if not has_tool_result:
                return app_mod.llm_client._adapt(_tool_use_body(A1_DEFAULT_TOPIC), "req-1")
            message = "\n".join(
                block.get("text", "")
                for entry in kwargs["messages"]
                for block in (entry["content"] if isinstance(entry["content"], list) else [])
                if isinstance(block, dict)
            )
            offered_docs = _OFFERED_DOC_RE.findall(message)
            status_match = _STATUS_RE.search(message)
            status = status_match.group(1) if status_match else "unknown"
            concluded = app_mod.outcome.payer_outcome({"status": status, "payer": "edi.example.com"})
            actions = queued["ids"]
            if actions is None:
                actions = visit_templates.a1_default_selection(concluded.value, "covered_today")
            citations = offered_docs[:1]
            return app_mod.llm_client._adapt(_decision_body(citations, actions), "req-2")

    monkeypatch.setattr(app_mod.llm_client, "client", _Scripted())
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-bearer-not-a-placeholder")
    calls.queue = lambda ids: queued.update(ids=ids)
    return calls


@pytest.fixture()
def fake_eligibility(monkeypatch):
    """Capture eligibility lookups; return a queued verdict."""
    calls = _Recorder()
    verdict = {"value": dict(ACTIVE_VERDICT)}

    def _fake(insurance_id):
        calls.append(insurance_id)
        return dict(verdict["value"])

    monkeypatch.setattr(app_mod.eligibility_client, "check_coverage", _fake)
    calls.set_verdict = lambda v: verdict.update(value=v)
    return calls


# eligibility-assistant: the four clerk menu selections are REQUIRED on every turn
# (SPEC-54/55), so every body this file posts carries them. One neutral set, because
# nothing in this file is about the selections — the tests that are live in
# tests/test_a1_prompt_boundary.py and tests/test_a1_harness.py.
A1_SELECTIONS = {
    "question_type": "covered_today",
    "payer": "aetna",
    "product": "commercial",
    "state": "unconfirmed",
}


def _post(message, turns=None, facts=None, **kwargs):
    body = {"message": message, **A1_SELECTIONS}
    if turns is not None:
        body["turns"] = turns
    if facts is not None:
        body["facts"] = facts
    return client.post("/visit-chat", json=body, **kwargs)


# --- intent derivation is deterministic ------------------------------------
def test_member_id_in_the_message_triggers_a_lookup(fake_llm, fake_eligibility):
    r = _post(f"can you check {MEMBER_ID} please")

    assert r.status_code == 200
    assert fake_eligibility == [MEMBER_ID]
    body = r.json()
    assert body["eligibility"]["status"] == "active"
    assert body["facts"]["insurance_id"] == MEMBER_ID
    assert body["facts"]["last_eligibility"]["status"] == "active"
    assert "ACTIVE" in body["reply"]
    assert body["disclaimer"]


def test_asking_for_a_check_with_no_id_on_file_asks_for_one(fake_llm, fake_eligibility):
    r = _post("can you check this patient's coverage?")

    assert r.status_code == 200
    assert fake_eligibility == []  # nothing to look up with
    assert "member ID" in r.json()["reply"]


def test_status_question_answers_from_stored_facts_without_a_new_lookup(
    fake_llm, fake_eligibility
):
    # The second turn of a visit: "is it still active?" must not re-ask for the id
    # and must not spend another payer call.
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": dict(ACTIVE_VERDICT)}

    r = _post(
        "is it still active?",
        turns=[{"role": "user", "intent": "check_eligibility"}],
        facts=facts,
    )

    assert r.status_code == 200
    assert fake_eligibility == []
    reply = r.json()["reply"]
    assert "ACTIVE" in reply
    # A reused verdict is stamped with when it was observed, never restated as if
    # it were fresh.
    assert ACTIVE_VERDICT["checked_at"] in reply


def test_recheck_uses_the_stored_id(fake_llm, fake_eligibility):
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": dict(ACTIVE_VERDICT)}

    r = _post("can you check again?", facts=facts)

    assert r.status_code == 200
    assert fake_eligibility == [MEMBER_ID]


def test_unrecognised_turn_does_not_call_the_payer(fake_llm, fake_eligibility):
    r = _post("thanks, that's all for now")

    assert r.status_code == 200
    assert fake_eligibility == []


# --- the vendor never sees the message -------------------------------------
def test_the_prompt_contains_no_free_text_from_the_clerk(fake_llm, fake_eligibility):
    message = f"patient Jane Doe, dob 1985-03-12, ssn 123-45-6789, member {MEMBER_ID}"

    _post(message)

    # eligibility-assistant: the turn makes TWO model calls, so the property is
    # asserted over both captured bodies rather than over one prompt — a stronger
    # form of the same rule (SPEC-12).
    prompts = [call["prompt"] for call in fake_llm]
    assert len(prompts) == 2
    for prompt in prompts:
        for fragment in ("Jane Doe", "1985-03-12", "123-45-6789", MEMBER_ID, "patient Jane"):
            assert fragment not in prompt
    # What they DO contain is closed vocabulary only, and the split is deliberate:
    # model₁ gets the derived intent and chooses a topic, model₂ gets the payer status
    # (SPEC-50 — a coverage verdict is not an input to a topic choice).
    assert "check_eligibility" in prompts[0]
    assert "active" not in prompts[0]
    assert "active" in prompts[1]


def test_prompt_carries_only_the_ids_the_status_justifies(fake_llm, fake_eligibility):
    fake_eligibility.set_verdict(dict(UNKNOWN_VERDICT))

    _post(f"check {MEMBER_ID}")

    # The id vocabulary rides model₂'s message now, not model₁'s: model₁ chooses a
    # topic and is offered no action ids at all.
    prompt = fake_llm[1]["prompt"]
    assert "retry_shortly" in prompt
    # self_pay_options belongs to a definitive `inactive`, never to a failed check.
    assert "self_pay_options" not in prompt


# --- the selection gate ----------------------------------------------------
def test_off_catalog_selection_falls_back_deterministically(fake_llm, fake_eligibility):
    fake_llm.queue(["definitely not a template id", "call the patient's doctor"])

    r = _post(f"check {MEMBER_ID}")

    assert r.status_code == 200
    expected = visit_templates.render(visit_templates.default_selection("active"))
    for item in expected:
        assert item in r.json()["reply"]
    assert "doctor" not in r.json()["reply"]


def test_status_unjustified_id_is_rejected_whole(fake_llm, fake_eligibility):
    # self_pay_options is a REAL catalog id and the wrong thing to say after a
    # check that failed — catalog membership alone is not enough.
    fake_eligibility.set_verdict(dict(UNKNOWN_VERDICT))
    fake_llm.queue(["retry_shortly", "proceed_per_policy", "self_pay_options"])

    r = _post(f"check {MEMBER_ID}")

    reply = r.json()["reply"]
    assert "self-pay" not in reply.lower()
    assert "Try the check again" in reply


def test_missing_required_id_is_rejected_whole(fake_llm, fake_eligibility):
    fake_eligibility.set_verdict(dict(UNKNOWN_VERDICT))
    fake_llm.queue(["retry_shortly"])  # proceed_per_policy missing

    r = _post(f"check {MEMBER_ID}")

    assert "Follow the clinic's policy" in r.json()["reply"]


def test_empty_selection_falls_back(fake_llm, fake_eligibility):
    fake_llm.queue([])

    r = _post(f"check {MEMBER_ID}")

    assert r.status_code == 200
    assert r.json()["reply"].count("- ") >= visit_templates.MIN_ITEMS


def test_a_valid_optional_id_is_allowed_through(fake_llm, fake_eligibility):
    fake_llm.queue(["note_coverage_result", "collect_secondary"])

    r = _post(f"check {MEMBER_ID}")

    assert "secondary coverage" in r.json()["reply"]


def test_invalid_ids_never_reach_a_log_record(fake_llm, fake_eligibility, caplog):
    # An invalid "id" is model free text; only indexes and counts may be logged.
    fake_llm.queue(["Jane Doe has no coverage, tell her to pay cash"])

    with caplog.at_level("DEBUG"):
        _post(f"check {MEMBER_ID}")

    assert "Jane Doe" not in caplog.text
    assert "pay cash" not in caplog.text
    assert "decision gate" in caplog.text


# --- an unconfirmed check is never a denial --------------------------------
@pytest.mark.parametrize("status", ["unknown", "pending"])
def test_degraded_status_never_renders_as_no_coverage(fake_llm, fake_eligibility, status):
    verdict = dict(UNKNOWN_VERDICT)
    verdict["status"] = status
    fake_eligibility.set_verdict(verdict)

    reply = _post(f"check {MEMBER_ID}").json()["reply"]

    assert "NO ACTIVE COVERAGE" not in reply
    assert "not a denial" in reply
    assert "uninsured" not in reply.split("Do not tell")[0]


def test_definitive_inactive_does_say_no_coverage(fake_llm, fake_eligibility):
    # The other side of the same rule: a real verdict must not be softened into
    # mush, or the feature is useless at the front desk.
    verdict = dict(ACTIVE_VERDICT)
    verdict.update(active=False, status="inactive")
    fake_eligibility.set_verdict(verdict)

    reply = _post(f"check {MEMBER_ID}").json()["reply"]

    assert "NO ACTIVE COVERAGE" in reply


# --- nothing free-text comes back out --------------------------------------
def test_the_response_echoes_no_free_text(fake_llm, fake_eligibility):
    # The caller persists what it gets back, so the response must carry no prose
    # the clerk typed — only the closed values needed to record a turn.
    message = f"please check {MEMBER_ID} for Jane Doe"

    body = _post(message).json()

    # No prose the clerk typed comes back in any field...
    for fragment in ("Jane Doe", "please check", "for Jane"):
        assert fragment not in json.dumps(body)
    # ...and the member id appears ONLY as the structured fact the gateway is
    # approved to persist, never inside reply text.
    assert MEMBER_ID not in body["reply"]
    assert body["facts"]["insurance_id"] == MEMBER_ID


def test_the_response_echoes_the_turn_metadata_to_be_stored(fake_llm, fake_eligibility):
    body = _post(f"check {MEMBER_ID}").json()

    assert body["intent"] == "check_eligibility"
    assert body["status"] == "active"


# --- no LLM fault may destroy a completed eligibility result ----------------
# Codex PR #14 round 3. The lookup runs BEFORE the model call and mutates the
# visit's facts. Raising afterwards discarded a verdict the payer had already
# answered, left the gateway with nothing to persist, and made every retry spend
# a fresh PHI-bearing payer call. The turn now always answers; only the SPEND
# verdict (`llm_egress`) differs between branches.
_LLM_FAILURES = [
    # (error class name, egressed= kwarg or None for the default, expected billable)
    # NOTE the two LLMConfigError rows. The type does NOT determine the answer:
    # llm_client raises it from four local gates AND from Bedrock's own
    # ClientError rejection (AccessDenied / UnrecognizedClient / Validation /
    # ResourceNotFound), which arrives only after the request crossed the vendor
    # boundary. Faking at the complete_structured seam erases that distinction
    # unless the test sets it explicitly, which is how the first cut of this
    # change shipped a refund for calls that really happened.
    ("LLMConfigError", False, False),   # local: unpriced model, blank token, no creds
    ("LLMConfigError", True, True),     # Bedrock said AccessDenied — already billable
    ("LLMConfigError", None, True),     # unspecified -> inherits the billable default
    ("LLMBudgetExceeded", None, False),  # local caps only, pre-egress by construction
    ("LLMUnavailable", None, True),
    ("LLMResponseError", None, True),
    ("LLMError", None, True),
]
_LLM_FAILURE_IDS = [
    f"{name}-egressed={egressed}" for name, egressed, _ in _LLM_FAILURES
]


def _raiser(error_name, egressed):
    """Fail the turn AT THE EGRESS SEAM.

    eligibility-assistant re-seam: the visit-chat turn no longer calls
    `complete_structured`, so the fault is injected at `llm_client._call` — the one
    place both the agent binding and every other caller egress through, and the
    place `run_agent_path`'s `except llm_client.LLMError` branch reads. The failure
    contract these tests assert is unchanged.
    """
    cls = getattr(app_mod.llm_client, error_name)

    def _raise(*args, **kwargs):
        if egressed is None:
            raise cls("failure detail")
        raise cls("failure detail", egressed=egressed)

    return _raise


@pytest.mark.parametrize(
    "error_name,egressed,billable", _LLM_FAILURES, ids=_LLM_FAILURE_IDS
)
def test_no_llm_failure_discards_a_completed_eligibility_result(
    monkeypatch, fake_eligibility, error_name, egressed, billable
):
    monkeypatch.setattr(
        app_mod.llm_client, "_call", _raiser(error_name, egressed)
    )

    r = _post(f"check {MEMBER_ID}")

    assert r.status_code == 200, f"{error_name} must not fail a turn that already checked"
    body = r.json()
    if error_name == "LLMBudgetExceeded":
        # eligibility-assistant-D-26 (owner-amended at spec review): the budget
        # preflight concludes `stop`. The verdict the payer call paid for still
        # survives — persisted in FACTS for the next turn — but is deliberately
        # NOT rendered beside a stop, because restating a coverage answer there
        # would claim the turn finished. The invariant this test was written for
        # (no LLM fault destroys a paid verdict) holds through the facts.
        assert body["facts"]["last_eligibility"]["status"] == "active"
        assert body["eligibility"] is None
        assert "ACTIVE" not in body["reply"].split("\n")[0].upper()
        assert body["outcome"] == "stop"
    else:
        # The verdict the payer gave us survives, in all three places the caller
        # reads it: the turn's result, the reply text, and the facts to persist.
        assert body["eligibility"]["status"] == "active"
        assert body["facts"]["last_eligibility"]["status"] == "active"
        assert "ACTIVE" in body["reply"].split("\n")[0].upper()
        for item in visit_templates.render(visit_templates.default_selection("active")):
            assert item in body["reply"]
    # ...and exactly one payer call was spent to get it.
    assert fake_eligibility == [MEMBER_ID]


@pytest.mark.parametrize(
    "error_name,egressed,billable", _LLM_FAILURES, ids=_LLM_FAILURE_IDS
)
def test_the_spend_flag_reports_whether_bedrock_could_have_been_billed(
    monkeypatch, fake_eligibility, error_name, egressed, billable
):
    # The flag replaces the HTTP status as the gateway's refund signal: a 200 can
    # now mean "answered without spending". It is read off the exception, never
    # inferred from its class, so a post-egress LLMConfigError keeps the charge.
    monkeypatch.setattr(
        app_mod.llm_client, "_call", _raiser(error_name, egressed)
    )

    assert _post(f"check {MEMBER_ID}").json()["llm_egress"] is billable


@pytest.mark.parametrize(
    "error_name,egressed,billable", _LLM_FAILURES, ids=_LLM_FAILURE_IDS
)
def test_every_llm_failure_is_reported_as_degraded(
    monkeypatch, fake_eligibility, error_name, egressed, billable
):
    # Health is a SEPARATE channel from spend. A local refusal is not billable
    # but IS degraded; a post-egress failure is both. Collapsing the two would
    # leave a dead Bedrock config invisible: it produces a normal-looking 200 and
    # (correctly) refunds the spend counter, so neither of the two things an
    # operator watches would move.
    monkeypatch.setattr(
        app_mod.llm_client, "_call", _raiser(error_name, egressed)
    )

    assert _post(f"check {MEMBER_ID}").json()["assistant"] == "degraded"


def test_a_successful_model_call_is_charged_and_healthy(fake_llm, fake_eligibility):
    body = _post(f"check {MEMBER_ID}").json()

    assert body["llm_egress"] is True
    assert body["assistant"] == "ok"


# eligibility-assistant SPEC-56: the agent path makes TWO model calls per turn, and
# `llm_egress` must answer for BOTH of them — "did any payload cross the vendor
# boundary this turn", not "did the last call". A local refusal before the first
# call spent nothing; the same refusal before the SECOND call comes after a paid
# first call, and reporting False there would refund a request Bedrock billed.
@pytest.mark.parametrize(
    "failure,expected_egress",
    [
        ("budget-at-model1", False),
        ("bearer-fail-closed", False),
        ("budget-at-model2", True),
    ],
    ids=["stop-at-model1-False", "bearer-fail-closed-False", "stop-at-model2-True"],
)
def test_a1_llm_egress_covers_both_calls(
    fake_llm, fake_eligibility, monkeypatch, failure, expected_egress
):
    if failure == "bearer-fail-closed":
        # A placeholder bearer refuses egress locally (`_require_bearer_token`,
        # fail-closed): zero calls crossed, so zero spend — and it IS a health
        # fault, unlike the designed budget stop's healthy sibling paths.
        monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "placeholder")
    else:
        stop_at = 1 if failure == "budget-at-model1" else 2
        real_call = app_mod.llm_client._call
        seen = {"n": 0}

        def gated(*args, **kwargs):
            seen["n"] += 1
            if seen["n"] == stop_at:
                raise app_mod.llm_client.LLMBudgetExceeded("per-request cap")
            return real_call(*args, **kwargs)

        monkeypatch.setattr(app_mod.llm_client, "_call", gated)

    body = _post(f"check {MEMBER_ID}").json()

    assert body["llm_egress"] is expected_egress
    if failure == "bearer-fail-closed":
        assert body["reason"] == "model_failure"
    else:
        assert body["reason"] == "spend_stop"
    assert body["assistant"] == "degraded"


# --- a turn with nothing to decide does not buy a model call ----------------
# Codex PR #14 round 5. On the no-lookup statuses allowed_selection collapses
# onto the required core, so the model's "choice" has exactly one legal outcome
# — and those are the cheapest turns in the feature to provoke (send a message
# with no member id in it). Paying Bedrock and a slot of the shared daily
# ceiling for them is drainable waste, so the call is skipped and the reserved
# slot refunded via llm_egress=False.
def _verdict_for(status):
    """The file's canonical verdict fixture, restated for `status`.

    Built from the two constants above rather than hand-assembled, so no row
    asserts against a shape `eligibility_client` could not emit — an `unknown`
    carrying the payer's ACTIVE raw code and no reason is not a verdict that
    exists, and inventing one here is how a second, divergent notion of
    "degraded verdict" gets inherited by the next test.
    """
    if status == "active":
        return dict(ACTIVE_VERDICT)
    if status == "inactive":
        return {**ACTIVE_VERDICT, "active": False, "status": "inactive"}
    return {**UNKNOWN_VERDICT, "status": status}


# (status, message that reaches it, verdict the payer returns or None for no
#  lookup, whether the model must be consulted). The last column is HARDCODED on
# purpose: deriving it from allowed_selection - default_selection would restate
# the production predicate, and a test that recomputes the code under test
# cannot fail when that code changes — narrowing allowed_selection to the
# default for every status would kill the model step entirely and still pass.
_STATUS_TURNS = [
    ("awaiting_id", "can you check this patient's coverage?", None, False),
    ("ambiguous_id", f"policy BCBS4471 or maybe {MEMBER_ID}, not sure which", None, False),
    ("active", f"check {MEMBER_ID}", "active", True),
    ("inactive", f"check {MEMBER_ID}", "inactive", True),
    ("unknown", f"check {MEMBER_ID}", "unknown", True),
    ("pending", f"check {MEMBER_ID}", "pending", True),
]


@pytest.mark.parametrize(
    "status,message,verdict_status,expect_model_call",
    _STATUS_TURNS,
    ids=[row[0] for row in _STATUS_TURNS],
)
def test_the_model_is_called_exactly_when_the_status_leaves_it_a_choice(
    fake_llm, fake_eligibility, status, message, verdict_status, expect_model_call
):
    # The invariant, not the two anecdotes: for EVERY reachable status, a vendor
    # request happens if and only if that status justifies an id the
    # deterministic default does not already contain. Asserting both directions
    # is what stops the short-circuit from silently swallowing the statuses where
    # the model does have something to add.
    if verdict_status:
        fake_eligibility.set_verdict(_verdict_for(verdict_status))

    body = _post(message).json()

    assert body["status"] == status
    # Exact counts, not "not any": the agent path pays exactly TWO model calls per
    # turn (model₁ picks the topic, model₂ the selection — SPEC-22's bound), so
    # three for one turn is a defect and so is one. Re-pinned from 1 with the seam
    # (eligibility-assistant-D-40: the single-prompt assertions re-pin the two-call
    # payloads).
    assert len(fake_llm) == (2 if expect_model_call else 0), (
        f"{status}: wrong number of model calls"
    )
    assert body["llm_egress"] is expect_model_call
    # Skipping a pointless call is not a fault: health stays separate from spend.
    assert body["assistant"] == "ok"


@pytest.mark.parametrize(
    "status,message",
    [(row[0], row[1]) for row in _STATUS_TURNS if not row[3]],
    ids=["awaiting_id", "ambiguous_id"],
)
def test_a_no_lookup_turn_still_answers_in_full_without_the_model(
    fake_llm, fake_eligibility, status, message
):
    # The clerk must not pay for the saving: the short-circuited reply carries the
    # same verdict line and the same action list the model path would have
    # rendered, since the gate could only ever have accepted this one selection.
    body = _post(message).json()

    assert fake_llm == []
    assert fake_eligibility == []
    assert body["llm_egress"] is False
    assert body["reply"].startswith(visit_templates.verdict_line(status))
    for item in visit_templates.render(visit_templates.default_selection(status)):
        assert item in body["reply"]
    assert body["eligibility"] is None


def test_the_skipped_model_call_is_recorded_and_carries_no_phi(
    fake_llm, fake_eligibility, caplog
):
    # A reserve-then-refund is now the COMMON accounting path, and it is the one
    # path where a 200 charges the shared ceiling and credits it straight back.
    # With no record of it, a drifting counter has no evidence trail before the
    # vendor invoice. The line is still allowlisted closed values only.
    with caplog.at_level("INFO"):
        _post("checking coverage for Jane Doe, dob 1985-03-12")

    assert "model_consulted" in caplog.text
    assert '"eligibility_status": "awaiting_id"' in caplog.text
    for fragment in ("Jane Doe", "1985-03-12", "checking coverage for"):
        assert fragment not in caplog.text


def test_a_rejected_model_selection_is_not_a_degraded_assistant(
    fake_llm, fake_eligibility
):
    # The selection gate firing means the model answered and we discarded its
    # choice — the vendor path is healthy. Reporting that as "degraded" would
    # make the signal fire on model noise and stop meaning anything.
    fake_llm.queue(["not_a_catalog_id"])

    body = _post(f"check {MEMBER_ID}").json()

    assert body["assistant"] == "ok"
    for item in visit_templates.render(visit_templates.default_selection("active")):
        assert item in body["reply"]


def test_a_local_refusal_does_not_re_spend_the_payer_on_retry_of_a_known_id(
    monkeypatch, fake_eligibility
):
    # The clerk's next turn is a status question, not a re-check. Because the
    # first turn ANSWERED (rather than 503-ing and losing its facts), the visit
    # carries the verdict forward and no second payer call is made — the
    # repeated-PHI-call symptom the old mapping produced under a persistent
    # Bedrock misconfiguration.
    monkeypatch.setattr(
        app_mod.llm_client, "_call", _raiser("LLMConfigError", False)
    )

    first = _post(f"check {MEMBER_ID}").json()
    second = _post("what was the status again?", facts=first["facts"]).json()

    assert fake_eligibility == [MEMBER_ID], "the second turn must not re-spend a payer call"
    assert second["status"] == "active"
    assert second["llm_egress"] is False


# --- service-to-service auth ----------------------------------------------
def test_missing_internal_auth_is_rejected_before_any_work(fake_llm, fake_eligibility):
    bare = TestClient(app_mod.app, raise_server_exceptions=False)

    r = bare.post("/visit-chat", json={"message": f"check {MEMBER_ID}"})

    assert r.status_code == 401
    assert fake_llm == []
    assert fake_eligibility == []


def test_blank_shared_secret_refuses_every_call(monkeypatch, fake_llm, fake_eligibility):
    # Fail-closed configuration: an unset secret must refuse, never disable the
    # check (the PR #5 round-5 lesson about the default deploy state).
    monkeypatch.setattr(app_mod.settings, "ai_proxy_shared_secret", "")

    r = _post(f"check {MEMBER_ID}")

    assert r.status_code == 503
    assert fake_llm == []


def test_placeholder_shared_secret_refuses_every_call(monkeypatch, fake_llm):
    monkeypatch.setattr(app_mod.settings, "ai_proxy_shared_secret", "changeme")

    assert _post(f"check {MEMBER_ID}").status_code == 503


# --- request bounds -------------------------------------------------------
def test_over_long_message_is_rejected_without_echo(fake_llm, fake_eligibility):
    huge = "x" * (app_mod.settings.ai_visit_max_message_chars + 1)

    r = _post(huge)

    assert r.status_code == 422
    assert huge not in r.text
    assert fake_llm == []


def test_empty_message_is_rejected(fake_llm):
    assert _post("").status_code == 422


def test_unknown_field_is_rejected(fake_llm):
    r = client.post(
        "/visit-chat", json={"message": "hello", "patient_ssn": "123-45-6789"}
    )

    assert r.status_code == 422
    assert "123-45-6789" not in r.text


def test_over_long_transcript_is_rejected(fake_llm):
    turns = [{"role": "user"} for _ in range(app_mod.settings.ai_visit_max_turns + 1)]

    assert _post("hello", turns=turns).status_code == 422


def test_turns_cannot_carry_text(fake_llm):
    # The store is metadata-only by construction (schemas.VisitTurn). A caller
    # that tries to park prose in the transcript is rejected at the edge rather
    # than quietly persisting PHI at rest.
    r = _post("hello", turns=[{"role": "user", "text": "patient Jane Doe, ssn 123-45-6789"}])

    assert r.status_code == 422
    assert "Jane Doe" not in r.text


def test_facts_cannot_smuggle_extra_state(fake_llm):
    # facts is what the gateway persists into Redis, so its shape is closed: a
    # smuggled name or note must be rejected rather than parked in visit memory.
    r = _post("hello", facts={"insurance_id": MEMBER_ID, "patient_name": "Jane Doe"})

    assert r.status_code == 422
    assert "Jane Doe" not in r.text


# --- logging --------------------------------------------------------------
def test_chat_log_is_metadata_only(fake_llm, fake_eligibility, caplog):
    with caplog.at_level("INFO"):
        _post(f"check {MEMBER_ID} for Jane Doe")

    assert MEMBER_ID not in caplog.text
    assert "Jane Doe" not in caplog.text
    assert "intent" in caplog.text
    assert "eligibility_status" in caplog.text


# --- the catalog stays administrative ------------------------------------
@pytest.mark.parametrize("key", list(visit_templates.CATALOG))
def test_catalog_copy_is_clinical_term_free(key):
    # Same screen the intake-instructions catalog is linted against: a future edit
    # must not smuggle clinical guidance into administrative copy.
    instructions_tests = load_module(
        "tests/test_ai_intake_instructions.py", "instructions_tests_for_screen"
    )
    assert not instructions_tests._CLINICAL_TERMS.search(visit_templates.CATALOG[key])


@pytest.mark.parametrize(
    "status",
    [
        "active",
        "inactive",
        "unknown",
        "pending",
        # eligibility-assistant: the six outcome-keyed sentences the turn added
        # (SPEC-13/15/16/42) go through the same screen as the original four.
        "unavailable",
        "conflict",
        "refuse_definitive",
        "refuse",
        "stop",
        "care_first",
    ],
)
def test_every_verdict_line_is_clinical_term_free(status):
    instructions_tests = load_module(
        "tests/test_ai_intake_instructions.py", "instructions_tests_for_screen2"
    )
    line = visit_templates.verdict_line(status, {"payer": "edi.example.com"})
    assert not instructions_tests._CLINICAL_TERMS.search(line)


# --- member-id recognition is a closed catalog (adversarial review) ---------
# The first cut matched a generic [A-Z]{3,6}\d{3,9} and carried the comment "a
# false positive is safe, the lookup returns unknown, never a denial". That was
# false in the direction that hurts patients: eligibility-service maps a payer
# 404 to a DEFINITIVE {"active": false}, so a mis-extracted token renders as
# "NO ACTIVE COVERAGE" for a patient whose coverage is fine. These tests pin the
# catalog and the ambiguity rules that replaced it.


@pytest.mark.parametrize(
    "token",
    [
        "SSN123456789",   # a labelled SSN
        "DOB01021980",    # a labelled date of birth
        "MRN0042719",     # a labelled medical record number
        "AUTH12345",      # a prior-authorisation number
        "GRP123456",      # a group number
        "NPI1234567",     # a provider identifier
        "REF00123",       # an internal reference
    ],
)
def test_non_payer_tokens_are_never_looked_up(fake_llm, fake_eligibility, token):
    r = _post(f"checking coverage for {token}")

    assert r.status_code == 200
    assert fake_eligibility == [], f"{token} must not be sent to a payer"
    assert r.json()["facts"]["insurance_id"] is None
    # ...and the reply asks for a real member id rather than asserting anything.
    assert "member ID" in r.json()["reply"]
    assert "NO ACTIVE COVERAGE" not in r.json()["reply"]


@pytest.mark.parametrize("member_id", ["AETN1224", "BCBS4471", "UNIT8080", "AETNA9920"])
def test_real_payer_prefixed_ids_are_recognised(fake_llm, fake_eligibility, member_id):
    r = _post(f"member {member_id}")

    assert r.status_code == 200
    assert fake_eligibility == [member_id]


def test_two_ids_in_one_message_are_never_guessed_between(fake_llm, fake_eligibility):
    # A clerk reading off a card types several id-shaped tokens. Picking the
    # leftmost is how a group number becomes the subject of a coverage verdict.
    r = _post(f"policy BCBS4471 or maybe {MEMBER_ID}, not sure which")

    assert r.status_code == 200
    assert fake_eligibility == []
    body = r.json()
    assert body["intent"] == "clarify_member_id"
    assert body["status"] == "ambiguous_id"
    assert "Confirm which member ID" in body["reply"]
    # Explicitly not a coverage answer of any kind.
    assert "NO ACTIVE COVERAGE" not in body["reply"]
    assert body["eligibility"] is None


def test_an_id_that_contradicts_the_visits_confirmed_id_is_refused(
    fake_llm, fake_eligibility
):
    # Silently switching subjects mid-visit would re-attribute every later turn.
    # Re-pointed with its subject (eligibility-assistant-D-73, owner 2026-08-27):
    # under eligibility-assistant-D-50 a recognised id that differs from the visit's
    # confirmed one is a cross-patient REFUSAL decided before intent derivation, not
    # an "ambiguous, ask" turn. Renamed because the old name stated the replaced rule.
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": dict(ACTIVE_VERDICT)}

    r = _post("actually try BCBS4471", facts=facts)

    assert fake_eligibility == []
    body = r.json()
    assert body["outcome"] == "refuse"
    assert body["reason"] == "cross_patient"
    assert body["mode"] == "refuse"
    assert [c["document_id"] for c in body["citations"]] == ["DOC-SYN-PRIVACY-FD"]
    # The stored verdict describes a DIFFERENT subject and must not be restated.
    verdict_sentence = body["reply"].split("\n")[0]
    assert "ACTIVE" not in verdict_sentence.upper()
    assert body["eligibility"] is None, "no check ran this turn"
    assert body["facts"]["insurance_id"] == MEMBER_ID  # unchanged


def test_repeating_the_same_id_is_not_ambiguous(fake_llm, fake_eligibility):
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": dict(ACTIVE_VERDICT)}

    r = _post(f"re-run {MEMBER_ID}", facts=facts)

    assert fake_eligibility == [MEMBER_ID]
    assert r.json()["status"] == "active"


def test_the_same_id_twice_in_one_message_is_not_ambiguous(fake_llm, fake_eligibility):
    r = _post(f"{MEMBER_ID} — sorry, {MEMBER_ID}")

    assert fake_eligibility == [MEMBER_ID]


# --- the recogniser reads what a human types, in any case -------------------
# Codex PR #14 round 3: the catalog is upper-cased in config.py and the pattern
# was compiled case-sensitively, so a clerk typing `aetn1224` got no lookup and
# was asked for the id they had just supplied.
@pytest.mark.parametrize(
    "typed", ["aetn1224", "Aetn1224", "AeTn1224", "aetnA9920", "bcbs4471"]
)
def test_a_member_id_is_recognised_whatever_case_it_is_typed_in(
    fake_llm, fake_eligibility, typed
):
    r = _post(f"member {typed}")

    assert r.status_code == 200
    # Looked up and stored in ONE canonical form, so every later comparison,
    # log projection, and persisted fact agrees on the subject.
    assert fake_eligibility == [typed.upper()]
    assert r.json()["facts"]["insurance_id"] == typed.upper()


def test_a_case_variant_of_the_stored_id_is_not_a_contradiction(
    fake_llm, fake_eligibility
):
    # The adversarial half of the fix: folding the MESSAGE but not the STORED id
    # would make every case-variant look like a different subject, and the visit
    # would answer "confirm which member ID" forever without ever running a check.
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": dict(ACTIVE_VERDICT)}

    # Deliberately no retry/status keyword in the message — the id itself has to
    # be what routes this turn, or the assertion passes through a path that never
    # compared the two ids at all.
    r = _post(f"the card says {MEMBER_ID.lower()}", facts=facts)

    body = r.json()
    assert body["intent"] == "check_eligibility", body["reply"]
    assert body["status"] == "active"
    assert fake_eligibility == [MEMBER_ID]
    assert body["facts"]["insurance_id"] == MEMBER_ID


def test_a_genuinely_different_id_still_contradicts_in_lower_case(
    fake_llm, fake_eligibility
):
    # Case folding must not soften the contradiction rule it runs alongside.
    # The consequence moved with its subject (eligibility-assistant-D-73): a
    # contradicting id now refuses (eligibility-assistant-D-50) instead of asking.
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": dict(ACTIVE_VERDICT)}

    body = _post("actually try bcbs4471", facts=facts).json()

    assert body["outcome"] == "refuse"
    assert body["reason"] == "cross_patient"
    assert body["mode"] == "refuse"
    assert [c["document_id"] for c in body["citations"]] == ["DOC-SYN-PRIVACY-FD"]
    assert fake_eligibility == []
    assert body["facts"]["insurance_id"] == MEMBER_ID


def test_one_id_typed_in_two_cases_is_one_candidate_not_two(
    fake_llm, fake_eligibility
):
    # De-duplication happens AFTER folding. Otherwise a clerk correcting their
    # own typing produces two "distinct" candidates and trips the ambiguity
    # branch on a message that contains no ambiguity.
    r = _post(f"{MEMBER_ID} — sorry, {MEMBER_ID.lower()}")

    assert r.json()["intent"] == "check_eligibility"
    assert fake_eligibility == [MEMBER_ID]


@pytest.mark.parametrize("token", ["ssn123456789", "grp123456", "auth12345"])
def test_case_folding_does_not_widen_the_catalog(fake_llm, fake_eligibility, token):
    # A miss is safe, a wrong match is not (round 1). IGNORECASE recognises the
    # same payer prefixes in another case — it must not recognise a new token.
    r = _post(f"checking coverage for {token}")

    assert fake_eligibility == [], f"{token} must not be sent to a payer"
    assert r.json()["facts"]["insurance_id"] is None


# The ASCII half of the same property. Bare re.IGNORECASE case-folds across all
# of Unicode, which widens a catalog built from ASCII prefixes — the ASCII-only
# tokens above cannot exercise that class at all. Each of these MATCHED the
# pattern before `re.ASCII` was added.
@pytest.mark.parametrize(
    "token,why",
    [
        ("KAIſ1234", "U+017F LONG S folds to 's' -> a DIFFERENT real id, KAIS1234"),
        ("MEDı1234", "U+0131 DOTLESS I folds to 'i' -> a different real id"),
        # A true negative kept on purpose: U+212A folds to 'k', and no shipped
        # prefix ends in K, so this one cannot reach a payer even under bare
        # IGNORECASE. It pins that the ASCII flag did not somehow ADMIT it.
        ("KAIK1234", "U+212A KELVIN SIGN folds to 'k', matching no prefix"),
        ("MEDİ1234", "U+0130 DOTTED I survives .upper() -> non-ASCII on the wire"),
        ("AETN١٢٣٤", "Arabic-Indic digits satisfy a Unicode \\d"),
    ],
)
def test_no_unicode_lookalike_is_ever_looked_up(
    fake_llm, fake_eligibility, token, why
):
    # Guard the guard. These tokens are written as \u escapes precisely because
    # the characters are visually identical to ASCII ones; an editor round-trip
    # or a careless retype that normalised them would leave a test that asserts
    # nothing while still passing.
    assert not token.isascii(), "token must actually contain a non-ASCII character"

    r = _post(f"member {token}")

    assert fake_eligibility == [], f"{why}: must never reach a payer"
    body = r.json()
    assert body["facts"]["insurance_id"] is None
    # A miss renders the ask, never a verdict about a subject nobody named.
    assert "member ID" in body["reply"]
    assert "NO ACTIVE COVERAGE" not in body["reply"]


def test_a_homoglyph_never_becomes_the_visits_canonical_id(fake_llm, fake_eligibility):
    # The specific harm behind the parametrized case above: KAIſ1234 folds to
    # KAIS1234, a well-formed id the clerk never typed. If it were accepted it
    # would be written to facts, persisted into visit memory by the gateway, and
    # every later turn in the visit would be attributed to that subject.
    body = _post("card reads KAIſ1234").json()

    assert body["facts"]["insurance_id"] is None
    assert "KAIS1234" not in json.dumps(body)


def test_a_non_ascii_id_cannot_be_smuggled_in_through_stored_facts(fake_llm, fake_eligibility):
    # The recogniser is not the only way an id reaches the payer: a recheck turn
    # uses the STORED id directly. So the schema boundary has to refuse it too,
    # or the guard above is bypassable by anything that can write facts.
    facts = {"insurance_id": "MEDİ1234", "last_eligibility": None}

    r = _post("recheck please", facts=facts)

    assert r.status_code == 422
    assert fake_eligibility == []
    # No-echo: the rejected value must not come back in the error body.
    assert "İ" not in r.text


def test_stored_facts_are_normalised_even_when_the_caller_supplies_lower_case(
    fake_llm, fake_eligibility
):
    # Visit memory is the gateway's, and it round-trips whatever we last echoed.
    # Folding at the schema boundary means a record written before this fix (or
    # by any other caller) still compares equal to a freshly recognised id.
    facts = {"insurance_id": MEMBER_ID.lower(), "last_eligibility": None}

    body = _post(f"check {MEMBER_ID}", facts=facts).json()

    assert body["facts"]["insurance_id"] == MEMBER_ID
    assert body["status"] == "active"
    assert fake_eligibility == [MEMBER_ID]


def test_no_optional_ids_are_offered_before_a_check_has_run(fake_llm, fake_eligibility):
    # "Record the coverage result" presupposes a result. A valid model selection
    # must not be able to say it when nothing ran.
    fake_llm.queue(["ask_member_id", "note_coverage_result"])

    r = _post("can you check coverage?")

    assert "Record the coverage result" not in r.json()["reply"]
    assert "member ID" in r.json()["reply"]


# --- an EMPTY catalog recognises nothing (Codex PR #14 round 1) -------------
# A closed catalog is only a safety control while it is closed. Joining zero
# prefixes builds `\b(?:)\d{3,9}\b` — an empty alternation matching EVERY 3-9
# digit token — so blanking the config silently restores the generic pattern the
# catalog replaced, with DOB fragments, ZIPs and group numbers as payer lookups.
# Empty must mean "recognise nothing", and it must be loud.
_GENERIC_DIGIT_TOKENS = ["19850312", "94110", "4471", "123456789", "0042719"]


@pytest.fixture()
def blank_catalog(monkeypatch):
    """Rebuild the recogniser as a fresh process would with the env var blank."""
    monkeypatch.setenv("AI_MEMBER_ID_PREFIXES", "")
    blank_config = load_module("services/ai-assistant/config.py", "vc_config_blank")
    assert blank_config.settings.ai_member_id_prefixes == ()
    pattern = app_mod._build_insurance_id_re(blank_config.settings.ai_member_id_prefixes)
    monkeypatch.setattr(app_mod, "_INSURANCE_ID_RE", pattern)
    return pattern


def test_blank_prefix_config_compiles_no_pattern(blank_catalog):
    assert blank_catalog is None


@pytest.mark.parametrize("token", _GENERIC_DIGIT_TOKENS)
def test_blank_prefix_config_recognises_no_generic_digits(blank_catalog, token):
    assert app_mod._extract_insurance_ids(f"patient says {token}") == []


@pytest.mark.parametrize("token", _GENERIC_DIGIT_TOKENS)
def test_visit_chat_refuses_when_the_catalog_is_empty(
    blank_catalog, fake_llm, fake_eligibility, token
):
    r = _post(f"check coverage for {token}")

    assert r.status_code == 503
    assert fake_eligibility == [], f"{token} must never reach a payer"
    assert fake_llm == [], "a config refusal is pre-egress and must not spend budget"
    assert token not in r.text, "the refusal must not echo the clerk's text"


def test_an_unauthenticated_caller_learns_nothing_about_the_config(blank_catalog):
    # The catalog check is ordered AFTER the auth dependency on purpose: a
    # caller without the shared secret must get the same 401 whether or not the
    # service is misconfigured. Reordering the dependencies list would flip this
    # to 503 and leak config state to an unauthenticated caller.
    r = client.post(
        "/visit-chat",
        json={"message": "check coverage for 19850312"},
        headers={"X-Internal-Auth": "wrong-secret"},
    )

    assert r.status_code == 401


def test_catalog_prefixes_are_escaped_not_interpreted_as_regex(monkeypatch):
    # The catalog is operator input. An unescaped metacharacter WIDENS the
    # pattern instead of failing loudly, which is the same wrong-subject failure
    # arriving through a typo rather than a deletion.
    monkeypatch.setattr(app_mod, "_INSURANCE_ID_RE", app_mod._build_insurance_id_re(("A.C",)))

    assert app_mod._extract_insurance_ids("card says ABC1234") == []
    assert app_mod._extract_insurance_ids("card says A.C1234") == ["A.C1234"]


def test_the_shipped_default_catalog_is_not_empty():
    # The fail-closed branch must be reachable only by an operator deleting the
    # value — never the state a fresh `cp .env.example .env` deploy boots into
    # (PR #5 round-5 lesson: test the default deploy state, not just the state
    # you designed the guard for).
    assert app_mod.settings.ai_member_id_prefixes
    assert app_mod._build_insurance_id_re(app_mod.settings.ai_member_id_prefixes)


# --- intent ordering --------------------------------------------------------
def test_a_question_about_the_past_does_not_re_spend_a_payer_call(
    fake_llm, fake_eligibility
):
    # "what was the status again?" is a question, not a retry request. During an
    # outage a spurious re-check can flip a confirmed ACTIVE into "could not
    # confirm", which is worse than answering from memory.
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": dict(ACTIVE_VERDICT)}

    r = _post("what was the status again?", facts=facts)

    assert fake_eligibility == []
    assert r.json()["intent"] == "ask_status"


@pytest.mark.parametrize("phrasing", ["is it active?", "is it still active?"])
def test_status_questions_answer_from_memory_consistently(
    fake_llm, fake_eligibility, phrasing
):
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": dict(ACTIVE_VERDICT)}

    r = _post(phrasing, facts=facts)

    assert fake_eligibility == [], f"{phrasing!r} should not re-spend a payer call"
    assert r.json()["intent"] == "ask_status"


@pytest.mark.parametrize("phrasing", ["recheck it", "please retry", "check again"])
def test_explicit_retry_verbs_do_re_check(fake_llm, fake_eligibility, phrasing):
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": dict(ACTIVE_VERDICT)}

    r = _post(phrasing, facts=facts)

    assert fake_eligibility == [MEMBER_ID]
    assert r.json()["intent"] == "recheck_eligibility"


# --- a repeat of the same id does not re-spend a payer call ------------------
# Codex PR #14 round 4. `_derive_intent` routed EVERY message containing a member
# id to check_eligibility, so a clerk restating or re-pasting the id they just
# gave — normal front-desk behaviour — spent another PHI-bearing payer call each
# turn while the answer sat unread in `last_eligibility`. The breaker and the
# per-user chat quota bounded that; they did not stop it, because the expensive
# path was the DEFAULT for a common input.
#
# What makes a repeat reusable is narrow, and each clause below is a test: a
# DEFINITIVE verdict, for the id ON FILE, observed by THIS service, inside the
# window. Everything else still calls the payer, because a wrong reuse hands a
# clerk a coverage fact that may no longer hold.
REUSE_WINDOW = app_mod.settings.ai_eligibility_reuse_seconds


def test_repeating_a_fresh_verdicts_own_id_spends_no_payer_call(
    fake_llm, fake_eligibility
):
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": _observed(ACTIVE_VERDICT)}

    # No retry verb and no status word — the ID ITSELF has to be what routes this
    # turn, or the assertion passes through a path that never consulted freshness.
    r = _post(f"member {MEMBER_ID}", facts=facts)

    assert r.status_code == 200
    assert fake_eligibility == [], "a repeat of a fresh verdict's own id must not re-check"
    body = r.json()
    assert body["intent"] == "ask_status"
    assert body["status"] == "active"
    # Answered from memory, and visibly a past observation (ADR 0011 §5).
    assert "ACTIVE" in body["reply"]
    assert ACTIVE_VERDICT["checked_at"] in body["reply"]


def test_a_reused_verdict_is_handed_back_unchanged_for_the_gateway_to_persist(
    fake_llm, fake_eligibility
):
    # The turn answers from facts, so it must not quietly rewrite them: the
    # gateway persists whatever comes back, and a re-stamped verdict would slide
    # the reuse window forward on every repeat and never expire.
    stored = _observed(ACTIVE_VERDICT)
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": stored}

    body = _post(f"member {MEMBER_ID}", facts=facts).json()

    assert fake_eligibility == []
    assert body["facts"]["insurance_id"] == MEMBER_ID
    assert body["facts"]["last_eligibility"] == stored
    assert body["eligibility"]["status"] == "active"


def test_a_fresh_definitive_inactive_is_reused_too(fake_llm, fake_eligibility):
    # Both definitive statuses are reusable, and reuse must not soften the answer
    # into mush — an `inactive` still reads as no active coverage.
    inactive = dict(ACTIVE_VERDICT, active=False, status="inactive")
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": _observed(inactive)}

    body = _post(f"member {MEMBER_ID}", facts=facts).json()

    assert fake_eligibility == []
    assert "NO ACTIVE COVERAGE" in body["reply"]


def test_a_repeat_outside_the_reuse_window_is_re_checked(fake_llm, fake_eligibility):
    facts = {
        "insurance_id": MEMBER_ID,
        "last_eligibility": _observed(ACTIVE_VERDICT, age_seconds=REUSE_WINDOW + 1),
    }

    body = _post(f"member {MEMBER_ID}", facts=facts).json()

    assert fake_eligibility == [MEMBER_ID], "an expired verdict must not answer a repeat"
    assert body["intent"] == "check_eligibility"


def test_a_zero_reuse_window_always_calls_the_payer(
    monkeypatch, fake_llm, fake_eligibility
):
    # 0 is the strictest setting for this knob (config.py), so it must mean "never
    # reuse" — not "reuse forever", which is what an unclamped comparison against
    # a zero window would do for a stamp from the same instant.
    monkeypatch.setattr(app_mod.settings, "ai_eligibility_reuse_seconds", 0)
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": _observed(ACTIVE_VERDICT)}

    _post(f"member {MEMBER_ID}", facts=facts)

    assert fake_eligibility == [MEMBER_ID]


@pytest.mark.parametrize(
    "phrasing",
    [
        "recheck {id}",
        "please retry {id}",
        "refresh {id}",
        # The id lands BETWEEN the verb and the adverb, which no substring in
        # _RETRY_WORDS can match. Harmless before the reuse window existed (any id
        # re-checked); with it, these are exactly the turns that would be answered
        # from memory while the clerk waits for a lookup that never runs.
        "check {id} again",
        "run {id} again",
        "verify {id} again please",
        "re-run {id}",
        "check\n{id}\nagain",
    ],
)
def test_an_explicit_retry_request_re_checks_even_a_fresh_verdict(
    fake_llm, fake_eligibility, phrasing
):
    # Freshness is a default, not a lock. An explicit retry asks for a NEW
    # observation, so it is tested BEFORE the window — otherwise the clerk has no
    # way to force a check and the feature ships a dead control.
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": _observed(ACTIVE_VERDICT)}

    body = _post(phrasing.format(id=MEMBER_ID), facts=facts).json()

    assert fake_eligibility == [MEMBER_ID], f"{phrasing!r} is a retry request"
    assert body["intent"] == "recheck_eligibility"


@pytest.mark.parametrize(
    "phrasing",
    [
        "what was the status of {id} again?",
        "is {id} still active?",
        "{id} — that's confirmed active, right?",
    ],
)
def test_a_question_that_repeats_the_id_is_still_answered_from_memory(
    fake_llm, fake_eligibility, phrasing
):
    # The other side of the retry pattern: "again" inside a QUESTION about the past
    # must not spend a payer call. Widening retry detection to the bare adverb
    # would flip every one of these into a lookup — and during an outage a spurious
    # re-check can turn a confirmed ACTIVE into "could not confirm".
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": _observed(ACTIVE_VERDICT)}

    body = _post(phrasing.format(id=MEMBER_ID), facts=facts).json()

    assert fake_eligibility == [], f"{phrasing!r} is a question, not a retry"
    assert body["intent"] == "ask_status"
    assert "ACTIVE" in body["reply"]


@pytest.mark.parametrize("status", ["unknown", "pending"])
def test_a_fresh_degraded_verdict_is_never_reused(fake_llm, fake_eligibility, status):
    # ADR 0011 gap 7 stands: an unconfirmed check is re-attempted, never served in
    # place of a real attempt. Reusing a fresh `pending` would answer "still
    # pending" forever and the visit could never reach a verdict.
    stored = dict(UNKNOWN_VERDICT, status=status)
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": _observed(stored)}

    _post(f"member {MEMBER_ID}", facts=facts)

    assert fake_eligibility == [MEMBER_ID], f"a fresh {status} verdict must still re-check"


# The adversarial half (CLAUDE.md §5): the stamp arrives inside `facts`, which is
# caller-supplied and open by design, so every unusable shape has to fail toward
# a real lookup rather than toward reuse.
@pytest.mark.parametrize(
    "observed_at,why",
    [
        (None, "explicit null"),
        ("", "empty string"),
        ("not a timestamp", "unparseable"),
        ("2026-07-26T10:00:00", "NAIVE — no offset, so its instant is a guess"),
        (1_800_000_000, "an epoch int, not the ISO string this service writes"),
        (["2026-07-26T10:00:00Z"], "a list smuggled where a string belongs"),
    ],
)
def test_an_unusable_observation_stamp_is_not_freshness(
    fake_llm, fake_eligibility, observed_at, why
):
    stored = dict(ACTIVE_VERDICT, observed_at=observed_at)
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": stored}

    r = _post(f"member {MEMBER_ID}", facts=facts)

    assert r.status_code == 200, why
    assert fake_eligibility == [MEMBER_ID], f"{why}: must not be treated as fresh"


def test_a_missing_observation_stamp_is_not_freshness(fake_llm, fake_eligibility):
    # The rolling-deploy case: a verdict written by the previous version of this
    # service carries `checked_at` but no `observed_at`. Absent must mean "cannot
    # prove freshness", never "assume fresh".
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": dict(ACTIVE_VERDICT)}
    assert "observed_at" not in facts["last_eligibility"]

    _post(f"member {MEMBER_ID}", facts=facts)

    assert fake_eligibility == [MEMBER_ID]


def test_a_future_observation_stamp_is_not_freshness(fake_llm, fake_eligibility):
    # A stamp ahead of now is a broken clock or a crafted value, not a recent
    # observation — and treating it as fresh would keep one verdict alive for as
    # long as the skew lasts.
    facts = {
        "insurance_id": MEMBER_ID,
        "last_eligibility": _observed(ACTIVE_VERDICT, age_seconds=-3600),
    }

    _post(f"member {MEMBER_ID}", facts=facts)

    assert fake_eligibility == [MEMBER_ID]


@pytest.mark.parametrize(
    "active,why",
    [
        (None, "the r5 covered-by-mistake shape, arriving through the facts door"),
        (1, "an int that == True but is not a boolean verdict"),
        ("true", "the string a JS caller would send"),
    ],
)
def test_a_verdict_claiming_active_without_a_boolean_is_not_reused(
    fake_llm, fake_eligibility, active, why
):
    # `status` alone never establishes coverage (eligibility_client r5). The same
    # rule has to hold when the dict comes back IN through facts, or the guard is
    # bypassable by anything that can write visit memory.
    stored = _observed(dict(ACTIVE_VERDICT, active=active))
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": stored}

    _post(f"member {MEMBER_ID}", facts=facts)

    assert fake_eligibility == [MEMBER_ID], f"{why}: must not answer from memory"


def test_a_status_that_disagrees_with_active_is_not_reused(fake_llm, fake_eligibility):
    # The cross-check in the other direction: active=True with status="unknown" is
    # an incoherent dict, and reuse is not the place to decide which half is right.
    stored = _observed(dict(ACTIVE_VERDICT, status="unknown"))
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": stored}

    _post(f"member {MEMBER_ID}", facts=facts)

    assert fake_eligibility == [MEMBER_ID]


def test_a_fresh_verdict_with_no_id_on_file_does_not_suppress_the_first_lookup(
    fake_llm, fake_eligibility
):
    # A verdict with no `insurance_id` beside it cannot be attributed to a
    # subject, so it must not answer for the id the clerk just typed.
    facts = {"insurance_id": None, "last_eligibility": _observed(ACTIVE_VERDICT)}

    body = _post(f"member {MEMBER_ID}", facts=facts).json()

    assert fake_eligibility == [MEMBER_ID]
    assert body["facts"]["insurance_id"] == MEMBER_ID


def test_freshness_does_not_soften_the_contradiction_rule(fake_llm, fake_eligibility):
    # A DIFFERENT id still contradicts however fresh the stored verdict is —
    # reuse must not become a path that answers about the wrong subject. The
    # consequence moved with its subject (eligibility-assistant-D-73): refusal.
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": _observed(ACTIVE_VERDICT)}

    body = _post("actually try BCBS4471", facts=facts).json()

    assert fake_eligibility == []
    assert body["outcome"] == "refuse"
    assert body["reason"] == "cross_patient"
    assert body["mode"] == "refuse"
    assert [c["document_id"] for c in body["citations"]] == ["DOC-SYN-PRIVACY-FD"]
    # The stored ACTIVE verdict is not restated in the verdict line.
    assert "ACTIVE" not in body["reply"].split("\n")[0].upper()
    assert body["eligibility"] is None


# --- the reuse window is not a cache the clerk cannot get past ---------------
# Pre-push adversarial review of the round-4 fix. Deciding an id-bearing turn on
# FRESHNESS alone made the freshness check outrank what the clerk actually asked
# for: an imperative check verb was swallowed, and a question about the past
# started paying whenever the stored verdict was degraded. A repeat now runs the
# same keyword ladder as a turn with no id in it; freshness decides only the bare
# restatement.
@pytest.mark.parametrize(
    "phrasing",
    [
        "verify {id}",
        "coverage changed — check {id}",
        "run eligibility for {id}",
        "new card, {id}, check her insurance",
    ],
)
def test_an_imperative_check_verb_is_honoured_against_a_fresh_verdict(
    fake_llm, fake_eligibility, phrasing
):
    # The concrete harm of swallowing it: the patient hands over a new card for the
    # same member id two minutes after the first check. Serving the stamped older
    # verdict makes the clerk record coverage nobody re-verified, and the reply then
    # tells them to "record the coverage result".
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": _observed(ACTIVE_VERDICT)}

    body = _post(phrasing.format(id=MEMBER_ID), facts=facts).json()

    assert fake_eligibility == [MEMBER_ID], f"{phrasing!r} asks for a check"
    assert body["intent"] == "check_eligibility"


@pytest.mark.parametrize(
    "phrasing", ["what did {id} come back as?", "what was {id}'s status?"]
)
def test_a_past_tense_question_with_the_id_never_pays_even_when_nothing_is_reusable(
    fake_llm, fake_eligibility, phrasing
):
    # The stored verdict is DEGRADED, so freshness cannot answer — but the turn is
    # still a question, and the identical question without the id has always been
    # free. Pasting the id must not make a question expensive, least of all during
    # the outage that produced the degraded verdict in the first place.
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": _observed(UNKNOWN_VERDICT)}

    body = _post(phrasing.format(id=MEMBER_ID), facts=facts).json()

    assert fake_eligibility == [], f"{phrasing!r} is a question about the past"
    assert body["intent"] == "ask_status"
    # And it renders as the failed check it was — never as a denial.
    assert "not a denial" in body["reply"]


@pytest.mark.parametrize(
    "phrasing",
    [
        "can you check what her status was again?",
        "she'll try again tomorrow",
        "tell the patient to check with HR, then ask us again next week",
        "run the wait-list report\nfollow up with billing\nnothing else again",
    ],
)
def test_a_bounded_retry_pattern_does_not_capture_incidental_agains(
    fake_llm, fake_eligibility, phrasing
):
    # An unbounded verb-to-adverb gap (and DOTALL) read all of these as retries. The
    # cost is not cosmetic: a spurious re-check during a payer outage overwrites a
    # confirmed ACTIVE with "could not confirm".
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": _observed(ACTIVE_VERDICT)}

    body = _post(phrasing.format(id=MEMBER_ID), facts=facts).json()

    assert fake_eligibility == [], f"{phrasing!r} is not a retry request"
    assert body["intent"] != "recheck_eligibility"


def test_a_failed_recheck_does_not_destroy_the_confirmed_verdict(
    fake_llm, fake_eligibility
):
    # `facts.last_eligibility` is the ONLY place a payer's answer lives — the gateway
    # persists exactly what comes back. Overwriting a definitive verdict with a
    # degraded one lost it permanently: the visit then had no verdict at all, and
    # every later turn re-paid for a lookup that could not succeed.
    stored = _observed(ACTIVE_VERDICT)
    fake_eligibility.set_verdict(dict(UNKNOWN_VERDICT, status="pending"))

    body = _post(f"recheck {MEMBER_ID}", facts={
        "insurance_id": MEMBER_ID, "last_eligibility": stored
    }).json()

    assert fake_eligibility == [MEMBER_ID]
    # THIS turn reports the failed attempt honestly...
    assert body["status"] == "pending"
    assert "not a denial" in body["reply"]
    # ...and the visit still remembers the observation the payer really gave us.
    assert body["facts"]["last_eligibility"] == stored


def test_a_definitive_recheck_does_replace_the_stored_verdict(
    fake_llm, fake_eligibility
):
    # The other direction: preserving a definitive verdict must not become "ignore
    # the payer". A new definitive answer always wins, including a change of answer.
    fake_eligibility.set_verdict(dict(ACTIVE_VERDICT, active=False, status="inactive"))

    body = _post(f"recheck {MEMBER_ID}", facts={
        "insurance_id": MEMBER_ID, "last_eligibility": _observed(ACTIVE_VERDICT)
    }).json()

    assert body["facts"]["last_eligibility"]["status"] == "inactive"
    assert "NO ACTIVE COVERAGE" in body["reply"]


def test_a_degraded_answer_for_a_new_subject_does_not_inherit_the_old_verdict(
    fake_llm, fake_eligibility
):
    # A verdict is only worth remembering for the subject it describes. Here the
    # visit had a verdict with no id beside it and the clerk supplies one, so the
    # failed lookup's degraded answer is what the visit keeps — inheriting the
    # orphan would attribute someone else's ACTIVE to this member id.
    fake_eligibility.set_verdict(dict(UNKNOWN_VERDICT))

    body = _post(f"check {MEMBER_ID}", facts={
        "insurance_id": None, "last_eligibility": _observed(ACTIVE_VERDICT)
    }).json()

    assert body["facts"]["insurance_id"] == MEMBER_ID
    assert body["facts"]["last_eligibility"]["status"] == "unknown"


def test_a_reused_verdict_with_no_downstream_timestamp_still_says_when(
    fake_llm, fake_eligibility
):
    # `checked_at` is downstream CONTENT and `_query` accepts any shaped 2xx, so a
    # verdict can arrive with none. Dropping the parenthetical then turns a reused
    # five-minute-old observation into an unqualified present-tense claim — the ADR
    # 0011 §5 promise, broken on the path reuse makes common.
    stored = _observed(dict(ACTIVE_VERDICT, checked_at=None), age_seconds=290)
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": stored}

    body = _post(f"member {MEMBER_ID}", facts=facts).json()

    assert fake_eligibility == []
    assert "(checked " in body["reply"], "a reused verdict must say when it was observed"
    assert stored["observed_at"] in body["reply"]


def test_the_log_says_whether_a_payer_was_asked_on_this_turn(
    fake_llm, fake_eligibility, caplog
):
    # `ask_status` now covers two different events — a question answered from
    # memory, and a re-verification declined because the stored verdict was fresh.
    # Neither the reply nor the response shape distinguishes them, so the log has to
    # (D2/D12: there is no tamper-evident accounting behind this yet).
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": _observed(ACTIVE_VERDICT)}

    def _turn_meta():
        lines = [r.getMessage() for r in caplog.records if "meta=" in r.getMessage()]
        return json.loads(lines[-1].split("meta=")[1])

    with caplog.at_level("INFO"):
        _post(f"member {MEMBER_ID}", facts=facts)
        reused = _turn_meta()
        caplog.clear()
        _post(f"recheck {MEMBER_ID}", facts=facts)
        rechecked = _turn_meta()

    # eligibility-assistant: the line gains five closed values (SPEC-33 mode, the
    # D-19 reason, the outcome, the model-call count, the correlation id). The four
    # original keys and their meanings are unchanged, which is what this asserts.
    assert {key: reused[key] for key in ("intent", "eligibility_status", "turn_count", "checked")} == {
        "intent": "ask_status", "eligibility_status": "active", "turn_count": 0, "checked": False
    }
    assert reused["mode"] in ("real", "fixture")
    assert reused["model_calls"] == 2
    assert rechecked["checked"] is True
    # Still metadata only.
    assert MEMBER_ID not in caplog.text


@pytest.mark.parametrize(
    "configured,expected", [("300", 300.0), ("0", 0.0), ("-5", 0.0), ("999999", 1800.0)]
)
def test_the_reuse_window_is_clamped_at_both_ends(monkeypatch, configured, expected):
    # 0 is a legitimate operator choice here (never reuse), so the floor only has
    # to stop a negative — which would make every stamp "in the future". The
    # ceiling stops the opposite mistake: reuse must not outlive the visit that
    # holds the verdict (AI_VISIT_TTL_SECONDS, 1800s).
    monkeypatch.setenv("AI_ELIGIBILITY_REUSE_SECONDS", configured)

    fresh = load_module("services/ai-assistant/config.py", f"vc_reuse_clamp_{configured}")

    assert fresh.settings.ai_eligibility_reuse_seconds == expected


def test_a_fresh_deploy_has_reuse_switched_on():
    # The fix has to be live in the state `cp .env.example .env` actually seeds,
    # not just in the code default (the PR #5 round-5 lesson). A template value of
    # 0 would ship the finding back unfixed with every test above still green.
    template = os.path.join(conftest.REPO_ROOT, ".env.example")
    with open(template, encoding="utf-8") as f:
        seeded = dict(
            line.split("=", 1)
            for line in f.read().splitlines()
            if "=" in line and not line.startswith("#")
        )

    configured = float(seeded["AI_ELIGIBILITY_REUSE_SECONDS"])
    assert 0 < configured <= 1800


# --- a reused verdict always says when it was observed ----------------------
@pytest.mark.parametrize("status", ["unknown", "pending"])
def test_a_reused_degraded_verdict_is_stamped(fake_llm, fake_eligibility, status):
    stored = dict(UNKNOWN_VERDICT)
    stored["status"] = status
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": stored}

    reply = _post("is it confirmed yet?", facts=facts).json()["reply"]

    assert stored["checked_at"] in reply, (
        "a stale degraded verdict must read as a past observation, not a fresh check"
    )
