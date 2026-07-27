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
  * the error mapping splits on EGRESS, because the gateway's spend-refund rule
    keys on the status: pre-egress refusals 503 (refundable), post-egress
    failures degrade to a deterministic 200 that keeps the charge.

The LLM is faked at the complete_structured seam (no network, no key), mirroring
the real seam's parse step. The eligibility client is faked at the module seam.
"""
import json
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from conftest import load_module

_PINNED = (
    "config",
    "logging_config",
    "schemas",
    "llm_client",
    "templates",
    "visit_templates",
    "breaker",
    "eligibility_client",
)
_saved = {name: sys.modules.pop(name, None) for name in _PINNED}
sys.modules["config"] = load_module("services/ai-assistant/config.py", "vc_config")
sys.modules["logging_config"] = load_module(
    "services/ai-assistant/logging_config.py", "vc_logging_config"
)
schemas = sys.modules["schemas"] = load_module(
    "services/ai-assistant/schemas.py", "vc_schemas"
)
sys.modules["llm_client"] = load_module("services/ai-assistant/llm_client.py", "vc_llm_client")
sys.modules["templates"] = load_module("services/ai-assistant/templates.py", "vc_templates")
visit_templates = sys.modules["visit_templates"] = load_module(
    "services/ai-assistant/visit_templates.py", "vc_visit_templates"
)
sys.modules["breaker"] = load_module("services/ai-assistant/breaker.py", "vc_breaker")
sys.modules["eligibility_client"] = load_module(
    "services/ai-assistant/eligibility_client.py", "vc_eligibility_client"
)
app_mod = load_module("services/ai-assistant/app.py", "visit_chat_app")
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

TEST_INTERNAL_SECRET = "test-internal-secret"
app_mod.settings.ai_proxy_shared_secret = TEST_INTERNAL_SECRET
client = TestClient(
    app_mod.app,
    raise_server_exceptions=False,
    headers={"X-Internal-Auth": TEST_INTERNAL_SECRET},
)

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


class _Recorder(list):
    """A list that also carries the test's control handles (a bare list cannot
    take attributes)."""


def _seam_parse(ids):
    """Mirror complete_structured's parse step exactly (llm_client.py):
    model_validate_json on the wire JSON, ValidationError → LLMResponseError."""
    try:
        parsed = schemas.VisitReplyPlan.model_validate_json(
            json.dumps({"template_ids": ids})
        )
    except ValidationError:
        raise app_mod.llm_client.LLMResponseError(
            "response failed VisitReplyPlan validation (request_id=fake)"
        ) from None
    return SimpleNamespace(parsed=parsed)


@pytest.fixture()
def fake_llm(monkeypatch):
    """Capture prompts and return whatever the test queues as model output.

    Default output is the deterministic required set for the status, so a test
    that cares about routing does not also have to care about selection.
    """
    calls = _Recorder()
    queued = {"ids": None}

    def _fake(prompt, output_model, system=None, max_tokens=None):
        calls.append({"prompt": prompt, "system": system, "output_model": output_model})
        if queued["ids"] is not None:
            return _seam_parse(queued["ids"])
        # Echo the required ids named in the prompt back as a valid selection.
        required = [
            key for key in visit_templates.CATALOG if f"- {key}:" in prompt.split("Optional")[0]
        ]
        return _seam_parse(required)

    monkeypatch.setattr(app_mod.llm_client, "complete_structured", _fake)
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


def _post(message, turns=None, facts=None, **kwargs):
    body = {"message": message}
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

    prompt = fake_llm[0]["prompt"]
    for fragment in ("Jane Doe", "1985-03-12", "123-45-6789", MEMBER_ID, "patient Jane"):
        assert fragment not in prompt
    # What it DOES contain is closed vocabulary only.
    assert "check_eligibility" in prompt
    assert "active" in prompt


def test_prompt_carries_only_the_ids_the_status_justifies(fake_llm, fake_eligibility):
    fake_eligibility.set_verdict(dict(UNKNOWN_VERDICT))

    _post(f"check {MEMBER_ID}")

    prompt = fake_llm[0]["prompt"]
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
    assert "selection gate" in caplog.text


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


# --- error mapping splits on egress ---------------------------------------
def test_pre_egress_config_refusal_is_a_refundable_503(monkeypatch, fake_eligibility):
    def _raise(**kwargs):
        raise app_mod.llm_client.LLMConfigError("no credentials")

    monkeypatch.setattr(app_mod.llm_client, "complete_structured", _raise)

    r = _post(f"check {MEMBER_ID}")

    assert r.status_code == 503


def test_pre_egress_budget_refusal_is_a_refundable_503(monkeypatch, fake_eligibility):
    # Must precede the LLMError catch — LLMBudgetExceeded subclasses it. A 500
    # here would make the gateway KEEP a charge for a call that never happened.
    def _raise(**kwargs):
        raise app_mod.llm_client.LLMBudgetExceeded("cap too low")

    monkeypatch.setattr(app_mod.llm_client, "complete_structured", _raise)

    r = _post(f"check {MEMBER_ID}")

    assert r.status_code == 503


@pytest.mark.parametrize("error_name", ["LLMUnavailable", "LLMResponseError"])
def test_post_egress_failure_degrades_to_a_deterministic_200(
    monkeypatch, fake_eligibility, error_name
):
    # The verdict was computed BEFORE the model call and does not depend on it, so
    # the clerk still gets the answer. 200 keeps the spend charge, exactly as the
    # 502 /intake-instructions returns would (ADR 0011 §7).
    def _raise(**kwargs):
        raise getattr(app_mod.llm_client, error_name)("provider down")

    monkeypatch.setattr(app_mod.llm_client, "complete_structured", _raise)

    r = _post(f"check {MEMBER_ID}")

    assert r.status_code == 200
    body = r.json()
    assert body["eligibility"]["status"] == "active"
    for item in visit_templates.render(visit_templates.default_selection("active")):
        assert item in body["reply"]


def test_unexpected_llm_error_keeps_the_charge_with_a_500(monkeypatch, fake_eligibility):
    def _raise(**kwargs):
        raise app_mod.llm_client.LLMError("something new")

    monkeypatch.setattr(app_mod.llm_client, "complete_structured", _raise)

    assert _post(f"check {MEMBER_ID}").status_code == 500


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


@pytest.mark.parametrize("status", ["active", "inactive", "unknown", "pending"])
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


def test_an_id_that_contradicts_the_visits_confirmed_id_asks_first(
    fake_llm, fake_eligibility
):
    # Silently switching subjects mid-visit would re-attribute every later turn.
    facts = {"insurance_id": MEMBER_ID, "last_eligibility": dict(ACTIVE_VERDICT)}

    r = _post("actually try BCBS4471", facts=facts)

    assert fake_eligibility == []
    body = r.json()
    assert body["status"] == "ambiguous_id"
    # The stored verdict describes a DIFFERENT subject and must not be restated.
    verdict_sentence = body["reply"].split("\n")[0]
    assert "ACTIVE" not in verdict_sentence.upper()
    assert "Confirm which member ID" in body["reply"]
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
