"""
Shared rig for the eligibility-assistant `turn` tests (eligibility-assistant-D-66).

One module set, not two. ``a1_corpus_rig`` already ran the house pin idiom
(``tests/test_ai_visit_chat.py``) — save the bare names, load ai-assistant's copies
by path, load ``app`` so its imports bind them, restore — so this rig **imports that
module and re-exports its objects** rather than loading a second copy. A rig that
called ``load_module`` again would hand the tests a ``policy_index`` / ``llm_client``
that the wired turn never touches, and every patch would land on a module nothing
calls.

Patch targets follow from that. After the corpus rig's restore ``sys.modules`` holds
no bare ``llm_client`` or ``eligibility_client``, and the only handles on the copies
the wired turn calls are ``app_mod.llm_client`` and ``app_mod.eligibility_client``:

  * the scripted Bedrock queue replaces ``app_mod.llm_client.client`` — an object
    exposing ``.messages.create``. ``llm_client._call`` resolves that attribute at
    call time (``llm_client.py:723-724``), so the replacement is what runs while
    ``_enforce_char_cap`` / ``_enforce_budget`` / ``_require_bearer_token`` stay live
    in front of it under this rig's non-placeholder bearer (eligibility-assistant-D-40);
  * the payer fake replaces ``app_mod.eligibility_client.check_coverage``
    (``eligibility_client.py:98``). Both callers — ``app.py`` and ``agent_turn``'s
    ``PayerGate`` — read it as a module attribute at call time, never
    ``from eligibility_client import check_coverage``, which would bind early and miss
    the patch.

Every file seamed onto this rig opens with ``assert_pinned()``.
"""
import json
import os
import sys

from fastapi.testclient import TestClient

from a1_corpus_rig import app_mod, policy_index, policy_tool, settings

llm_client = app_mod.llm_client
eligibility_client = app_mod.eligibility_client
# ``app.py`` imports NAMES from schemas, not the module, so the module object is
# reached through ``outcome``, which imports it the module way its neighbours do —
# the pinned copy by construction, never a second one a fresh ``load_module`` would
# create (``conftest.load_module`` does not register the unique name in sys.modules).
outcome = app_mod.outcome
schemas = outcome.schemas
agent_turn = app_mod.agent_turn

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(REPO_ROOT, "tests", "fixtures", "a1")

with open(os.path.join(FIXTURES, "case_selections.json"), encoding="utf-8") as _fh:
    CASE_SELECTIONS = json.load(_fh)


TEST_INTERNAL_SECRET = "test-internal-secret"
app_mod.settings.ai_proxy_shared_secret = TEST_INTERNAL_SECRET
client = TestClient(
    app_mod.app,
    raise_server_exceptions=False,
    headers={"X-Internal-Auth": TEST_INTERNAL_SECRET},
)

MEMBER_ID = "AETN1224"


def turn(case_id: str, message: str = "Is this patient covered today?", **overrides) -> dict:
    """One request body: the case's four selections plus the caller's overrides."""
    body = {"message": message, "turns": [], "facts": {}, "emergency": False}
    body.update(selections(case_id))
    body.update(overrides)
    return body


def post(body: dict, *, correlation_id: str = "") -> object:
    """POST one turn, with the correlation header the portal mints (SPEC-25/26)."""
    headers = {"X-Correlation-Id": correlation_id} if correlation_id else {}
    return client.post("/visit-chat", json=body, headers=headers)


def assert_pinned() -> None:
    """The identity assertions every rig-seamed test opens with.

    A rig that patched a fresh ``load_module`` copy reddens HERE, before any turn
    runs, so nothing reaches the real ``_BedrockClient``.
    """
    assert app_mod.policy_index is policy_index
    assert app_mod.VisitChatRequest is schemas.VisitChatRequest
    assert app_mod.policy_tool is policy_tool
    assert app_mod.agent_binding.llm_client is app_mod.llm_client
    assert app_mod.agent_turn.llm_client is app_mod.llm_client
    assert app_mod.agent_turn.eligibility_client is app_mod.eligibility_client


class ScriptedBedrock:
    """A queue of Bedrock response BODIES, standing in for the runtime's HTTP leg.

    Deliberately scripted at ``client.messages.create``, not above it: everything
    ``_call`` does before egress — the gross-size char cap, the token/cost budget
    gate, the bearer fail-closed guard — stays live in front of this object, and
    ``llm_client._adapt`` still runs on the body, so a test drives the same typed
    errors and the same response shape a real 200 would produce
    (eligibility-assistant-D-40).

    ``calls`` records the kwargs of every create, which is what the prompt-boundary
    scan (SPEC-12) reads: the captured bodies ARE what left the process.
    """

    def __init__(self, bodies) -> None:
        self._bodies = list(bodies)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._bodies:
            raise AssertionError(
                "the scripted Bedrock queue is empty: the turn made %d model calls, "
                "more than the script allows" % len(self.calls)
            )
        body = self._bodies.pop(0)
        if isinstance(body, Exception):
            raise body
        return llm_client._adapt(body, "req-scripted-%d" % len(self.calls))

    @property
    def remaining(self) -> int:
        return len(self._bodies)


def text_body(text: str, *, input_tokens: int = 100, output_tokens: int = 20) -> dict:
    """A Bedrock body carrying one text block — model₂'s answer shape."""
    return {
        "id": "msg-text",
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "stop_reason": "end_turn",
    }


def tool_use_body(name: str, arguments: dict, *, block_id: str = "toolu-1") -> dict:
    """A Bedrock body carrying one `tool_use` block — model₁'s retriever call."""
    return {
        "id": "msg-tool",
        "content": [{"type": "tool_use", "id": block_id, "name": name, "input": arguments}],
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "stop_reason": "tool_use",
    }


def install_model(monkeypatch, *bodies) -> ScriptedBedrock:
    """Replace the wired turn's Bedrock client with a scripted queue."""
    scripted = ScriptedBedrock(bodies)
    monkeypatch.setattr(app_mod.llm_client, "client", scripted)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "rig-bearer-not-a-placeholder")
    return scripted


class PayerFake:
    """A recording stand-in for ``eligibility_client.check_coverage``.

    ``calls`` is the list of member ids it was asked about — the once-guard proof
    (SPEC-51) and the "no payer call" proof (SPEC-45/49) both read it.
    """

    def __init__(self, verdict) -> None:
        self._verdict = verdict
        self.calls = []

    def __call__(self, insurance_id):
        self.calls.append(insurance_id)
        verdict = self._verdict
        return verdict(insurance_id) if callable(verdict) else dict(verdict)


def install_payer(monkeypatch, verdict) -> PayerFake:
    """Replace the wired turn's payer call. Both call sites read the module
    attribute at call time, so this patch is what actually runs."""
    fake = PayerFake(verdict)
    monkeypatch.setattr(app_mod.eligibility_client, "check_coverage", fake)
    return fake


def verdict(status: str, *, payer: str = "Aetna", active=None) -> dict:
    """One projected payer verdict in the shape ``eligibility_client`` returns."""
    return {
        "status": status,
        "active": active,
        "payer": payer,
        "checked_at": "2026-08-31T09:00:00+00:00",
        "observed_at": "2026-08-31T09:00:00+00:00",
    }


def selections(case_id: str) -> dict:
    """The four clerk menu selections for an acceptance case (`corpus` fixture)."""
    row = CASE_SELECTIONS[case_id]
    return {key: row[key] for key in ("question_type", "payer", "product", "state")}


def topic(case_id: str) -> str:
    """The topic the case's model₁ is scripted to choose."""
    return CASE_SELECTIONS[case_id]["topic"]


def retrieved_ids(case_id: str) -> list:
    """The ids the retriever actually returns for this case's argument set.

    Derived, never hard-coded: a citation the model offers is legal only if the turn
    RETRIEVED it (SPEC-5), so a test that names an id by hand is asserting against a
    set the turn may not have, and would drift the day a curation changes.
    """
    row = CASE_SELECTIONS[case_id]
    rows, _record = policy_index.lookup(
        row["topic"], row["payer"], row["product"], row["state"]
    )
    return [item.id for item in rows]


__all__ = [
    "app_mod",
    "policy_index",
    "policy_tool",
    "settings",
    "llm_client",
    "schemas",
    "outcome",
    "agent_turn",
    "eligibility_client",
    "assert_pinned",
    "client",
    "turn",
    "post",
    "MEMBER_ID",
    "ScriptedBedrock",
    "install_model",
    "install_payer",
    "text_body",
    "tool_use_body",
    "verdict",
    "selections",
    "topic",
    "retrieved_ids",
    "CASE_SELECTIONS",
]
