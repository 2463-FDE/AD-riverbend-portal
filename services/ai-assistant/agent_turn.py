"""
agent_turn — the agent path: model₁ → retriever → [payer] → model₂, executed by the
LangChain v1 agent runtime (eligibility-assistant SPEC-21).

What lives here is the turn's BOUNDS, not its reasoning. The framework selects the
tool, runs it, and asks model₂ for the decision; this module gives it a state object
that counts what it has spent, a middleware that runs the payer call between the two
model calls and injects the status model₂ is entitled to see, a once-guard that keeps
the payer call at most one per turn whatever the agent step does (SPEC-51), and a
`run_agent_path` that maps every way the step can end onto the closed
eligibility-assistant-D-19 reason enum.

Three bounds, all of them structural rather than instructions to the model
(SPEC-22): exactly one tool call, exactly two model calls, and — because both model
calls go through `llm_client._call` — the per-request budget preflight in front of
each of them (SPEC-23).

`llm_client` and `eligibility_client` are imported as MODULES, never
``from … import check_coverage``: both are resolved as attributes at call time so a
test rig patching the module attribute is what the turn actually calls
(eligibility-assistant-D-66 note 2). The same rule is why `agent_binding` is imported
as a module — the seam a turn egresses through must be the one the rig pinned.

The five members `run_agent_path` returns are five DIFFERENT facts about the turn and
none is derivable from another (eligibility-assistant-D-71):

  * ``decision`` / ``reason`` — what model₂ chose, or why the step ended without it;
  * ``llm_egress`` — spend: did any payload cross the vendor boundary;
  * ``model_calls`` — how many, which the trace and the log line report;
  * ``rows`` — the turn's retrieved set, which SPEC-5/13 validate citations against;
  * ``degraded`` — HEALTH: did an ``llm_client.LLMError`` escape the agent step.
    Exactly the predicate of the pre-eligibility-assistant ``except LLMError`` branch,
    carried here because `_reply_items` is retired. It is not the egress flag and it
    is not ``mode == "fallback"``: a rejected model selection is a fallback on a
    HEALTHY assistant that DID egress, and a `spend_stop` at model₁ is a fallback on a
    degraded one that did not.
"""
import json
from typing import Any, Dict, List, NamedTuple, Optional

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage

import agent_binding
import eligibility_client
import llm_client
import outcome
import policy_index
import policy_tool
import schemas
from config import settings
from logging_config import configure

log = configure(settings.service_name)

# SPEC-22's two numbers, named rather than spelled inline so the bound and the reason
# it produces cannot drift apart.
MAX_TOOL_CALLS = 1
MAX_MODEL_CALLS = 2


class PayerGate:
    """The turn's ONE payer call, wherever it is asked for (SPEC-51).

    Shared by the agent step's ``before_model`` hook and by the fallback path, so
    "at most once per turn" holds across a step that ended anywhere — a `spend_stop`
    at model₁ included, where the hook never ran and the fallback path has to make
    the call the turn is still owed.

    The eligibility decision itself is unchanged and stays deterministic: whether to
    call is a function of the derived intent and the held id (``app.py``'s existing
    gate), never of model output or of what the free text asked for (SPEC-19).
    """

    def __init__(
        self,
        insurance_id: Optional[str],
        eligible: bool,
        remembered: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._insurance_id = insurance_id
        self._eligible = eligible and bool(insurance_id)
        self.called = False
        self.verdict: Optional[Dict[str, Any]] = None
        # What the VISIT already knows. A turn that does not buy a lookup is still
        # entitled to answer from it — that is what `last_eligibility` is for — and so
        # is model₂, which SPEC-50 says receives the payer status for the turn.
        self.remembered = remembered

    @property
    def status_verdict(self) -> Optional[Dict[str, Any]]:
        """The verdict this turn speaks from: the fresh one, else the visit's."""
        return self.verdict if self.called else self.remembered

    def run(self) -> Optional[Dict[str, Any]]:
        """Call the payer at most once. A second call returns the first answer."""
        if self.called or not self._eligible:
            return self.verdict
        self.called = True
        # Read as a module attribute at call time — never bound at import — so the
        # call site the rig patches is the one that runs.
        self.verdict = eligibility_client.check_coverage(self._insurance_id)
        return self.verdict


class TurnState:
    """What one agent step has spent and produced. One instance per turn."""

    def __init__(self) -> None:
        self.model_calls = 0
        self.tool_calls = 0
        self.llm_egress = False
        self.rows: List[Any] = []
        self.reason: Optional[str] = None
        self.status: str = ""

    def bound_out(self, reason: str) -> None:
        """Record the first reason the step was bounded out for, never a later one."""
        if self.reason is None:
            self.reason = reason


class TurnMiddleware(AgentMiddleware):
    """The payer hook, the status injection, and the loop bounds.

    ``before_model`` is where the payer call runs, which puts it between the two
    model calls exactly as eligibility-assistant-D-18 orders them — after the
    retriever has returned and before model₂ is asked. Model₁ is deliberately NOT
    given the status (SPEC-50): it chooses a topic, and a coverage verdict is not an
    input to that choice.

    ``after_model`` carries SPEC-22's bounds. They are enforced here, on the
    framework's own state, rather than asked for in the prompt: an instruction is not
    an enforcement layer, and this repo's whole visit-chat design turns on that
    distinction.
    """

    def __init__(self, turn_state: "TurnState", payer_gate: "PayerGate", model2_message) -> None:
        super().__init__()
        self.turn_state = turn_state
        self.payer_gate = payer_gate
        self._model2_message = model2_message

    def before_model(self, state, runtime=None):  # noqa: ARG002 - framework signature
        if self.turn_state.model_calls >= MAX_MODEL_CALLS:
            # A third model call would be a third paid request for a turn whose
            # answer is already bounded — reject rather than spend (SPEC-22).
            self.turn_state.bound_out(outcome.Reason.validation_reject.value)
            return {"jump_to": "end"}
        if self.turn_state.model_calls == 1:
            self.payer_gate.run()
            self.turn_state.status = (self.payer_gate.status_verdict or {}).get("status") or ""
            return {
                "messages": [
                    HumanMessage(
                        content=self._model2_message(
                            self.turn_state.status, self.turn_state.rows
                        )
                    )
                ]
            }
        return None

    def after_model(self, state, runtime=None):  # noqa: ARG002 - framework signature
        self.turn_state.model_calls += 1
        self.turn_state.llm_egress = True
        message = state["messages"][-1]
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls:
            self.turn_state.tool_calls += len(tool_calls)
            if self.turn_state.tool_calls > MAX_TOOL_CALLS:
                # A second retrieval is out of the vocabulary this turn was bounded
                # to, and is rejected the same way an out-of-catalog id is.
                self.turn_state.bound_out(outcome.Reason.validation_reject.value)
                return {"jump_to": "end"}
            return None
        if self.turn_state.model_calls == 1:
            # Model₁ answered without calling the retriever, so there is nothing for
            # model₂ to cite and no second call worth paying for (SPEC-22).
            self.turn_state.bound_out(outcome.Reason.no_retrieval.value)
            return {"jump_to": "end"}
        return None


def _rows_from_tool_result(content: Any) -> List[Any]:
    """Rebuild the retrieved rows from what the tool actually returned.

    Deliberately reconstructed from the tool RESULT rather than re-fetched by id: the
    turn's retrieved set is what egressed to model₂, and re-fetching would both emit
    a second lookup record (`retrieval-eval`'s log line) and open a gap between what
    the model saw and what SPEC-5/13 validate its citations against.
    """
    try:
        payload = json.loads(content) if isinstance(content, str) else content
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    rows = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                policy_index.Row(
                    id=item["id"],
                    title=item["title"],
                    section=item["section"],
                    version=item["version"],
                    retrieval_date=item["retrieval_date"],
                    section_text=item["section-text"],
                )
            )
        except KeyError:
            continue
    return rows


def build_graph(*, payer: str, product: str, state: str, middleware=()):
    """Compile the agent for one turn's clerk selections.

    The tool is built by `policy_tool` with payer/product/state ALREADY BOUND, so the
    model's whole argument surface is `topic` and the application's three axes are not
    reachable from the model's side of the call (SPEC-1/9).
    """
    return create_agent(
        model=agent_binding.SeamChatModel(),
        tools=[policy_tool.make_policy_lookup(payer, product, state)],
        system_prompt=SYSTEM_PROMPT,
        middleware=tuple(middleware),
    )


SYSTEM_PROMPT = (
    "You help a front-desk clerk answer an insurance eligibility question using ONLY "
    "the clinic's approved policy documents. First call `policy_lookup` once with the "
    "topic that fits the question. Then, from the documents it returns and the "
    "eligibility status you are given, reply with a JSON object with exactly two keys: "
    "`citation_ids`, the document ids you are relying on, taken only from the "
    "documents you were shown; and `action_ids`, the action ids to show the clerk, "
    "taken only from the ids you were given. Do not write advice text, do not state a "
    "coverage decision, and do not use any id you were not given."
)


class AgentResult(NamedTuple):
    """The five facts one agent step produced. See the module docstring for why five."""

    decision: Optional[schemas.AgentDecision]
    reason: Optional[str]
    llm_egress: bool
    model_calls: int
    rows: List[Any]
    degraded: bool


def run_agent_path(
    *,
    payer: str,
    product: str,
    state: str,
    model1_message: str,
    model2_message,
    payer_gate: "PayerGate",
) -> "AgentResult":
    """Run one agent step and map every way it can end onto the closed reason enum.

    The two error mappings are the eligibility-assistant-D-37 ones and they are read
    off the EXCEPTION TYPE, not off anything the model said: ``LLMBudgetExceeded`` is
    the per-request preflight refusing before egress, which is `spend_stop`; every
    other ``LLMError`` is a provider or response fault, which is `model_failure`.

    ``degraded`` is set on exactly the ``LLMError`` branch — the predicate the
    pre-eligibility-assistant ``except llm_client.LLMError`` branch used, carried here
    unchanged. A validation reject is NOT degraded: the assistant worked, the model's
    answer did not fit, and the fallback is the designed response to that
    (eligibility-assistant-D-71).
    """
    turn_state = TurnState()
    middleware = TurnMiddleware(turn_state, payer_gate, model2_message)
    graph = build_graph(payer=payer, product=product, state=state, middleware=[middleware])
    try:
        result = graph.invoke({"messages": [HumanMessage(content=model1_message)]})
    except llm_client.LLMBudgetExceeded:
        # Local refusal: the preflight ran before any egress on THIS call, so the
        # turn's egress flag is whatever earlier calls already set it to.
        log.error("visit-chat agent step stopped on budget (LLMBudgetExceeded)")
        return AgentResult(
            None, outcome.Reason.spend_stop.value, turn_state.llm_egress,
            turn_state.model_calls, turn_state.rows, True,
        )
    except llm_client.LLMError as e:
        # Class name only, plus the provider's own request id where there is one —
        # never the message (docs/phi-logging-policy.md rule 5; W1-SPEC-13).
        log.error(
            "visit-chat agent step failed (%s, egressed=%s, request_id=%s)",
            type(e).__name__,
            getattr(e, "egressed", True),
            getattr(e, "request_id", None),
        )
        return AgentResult(
            None, outcome.Reason.model_failure.value,
            turn_state.llm_egress or getattr(e, "egressed", True),
            turn_state.model_calls, turn_state.rows, True,
        )

    messages = result.get("messages", [])
    for message in messages:
        if getattr(message, "type", "") == "tool":
            turn_state.rows = _rows_from_tool_result(message.content)
            break

    if turn_state.reason is not None:
        return AgentResult(
            None, turn_state.reason, turn_state.llm_egress,
            turn_state.model_calls, turn_state.rows, False,
        )

    decision = _parse_decision(messages)
    if decision is None:
        # An unparseable decision is the model failing to answer in the shape it was
        # given, which is a validation reject and NOT a health fault — the assistant
        # is fine, the answer is not (SPEC-13).
        turn_state.bound_out(outcome.Reason.validation_reject.value)
        return AgentResult(
            None, turn_state.reason, turn_state.llm_egress,
            turn_state.model_calls, turn_state.rows, False,
        )
    return AgentResult(
        decision, None, turn_state.llm_egress,
        turn_state.model_calls, turn_state.rows, False,
    )


def _parse_decision(messages) -> Optional[schemas.AgentDecision]:
    """Model₂'s decision, or None if it did not answer in the shape it was given.

    A validated JSON text block rather than provider structured output: the second
    call already carries a tool definition, and `tool_choice: none` beside structured
    output is an unmeasured combination on this seam (eligibility-assistant-D-37). A
    parse miss lands HERE, as a reject the fallback path handles, rather than as an
    ``LLMResponseError`` that would bypass it.
    """
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        text = message.text() if callable(getattr(message, "text", None)) else message.content
        if not isinstance(text, str) or not text.strip():
            return None
        try:
            return schemas.AgentDecision.model_validate_json(text)
        except Exception:
            return None
    return None
