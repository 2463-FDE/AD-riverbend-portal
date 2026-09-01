"""
agent_turn — the agent path: model₁ → retriever → [payer] → model₂, run by the
LangChain v1 agent runtime (SPEC-21).

This module owns the turn's BOUNDS, not its reasoning: a state object that counts
spend, a middleware that runs the payer call between the two model calls, a
once-guard on that call (SPEC-51), and `run_agent_path`, which maps every way the
step can end onto the closed eligibility-assistant-D-19 reason enum. The bounds are
structural, never prompt instructions (SPEC-22/23).

`llm_client`, `eligibility_client` and `agent_binding` are imported as MODULES and
resolved as attributes at call time, so a test rig patching the module attribute is
what the turn actually calls (eligibility-assistant-D-66 note 2).

`AgentResult`'s members are independent facts (eligibility-assistant-D-71):
``degraded`` is health (an ``llm_client.LLMError`` escaped), ``llm_egress`` is
spend, and neither is ``mode == "fallback"``.
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
    "at most once per turn" holds even when the step ended before the hook ran.
    Whether to call is a function of intent and held id, never of model output
    (SPEC-19).
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
        # The visit's remembered verdict: a turn that buys no lookup answers from
        # it, and so does model₂ (SPEC-50).
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

    ``before_model`` runs the payer call between the two model calls
    (eligibility-assistant-D-18); model₁ never sees the status (SPEC-50).
    ``after_model`` enforces SPEC-22's bounds on the framework's own state.
    """

    def __init__(self, turn_state: "TurnState", payer_gate: "PayerGate", model2_message) -> None:
        super().__init__()
        self.turn_state = turn_state
        self.payer_gate = payer_gate
        # ``(status, verdict, rows) -> str``. The verdict rides beside the normalised
        # status because the action-id vocabulary keys on the ABSENCE of a verdict,
        # which no status string distinguishes from an empty one.
        self._model2_message = model2_message

    def before_model(self, state, runtime=None):  # noqa: ARG002 - framework signature
        if self.turn_state.model_calls >= MAX_MODEL_CALLS:
            # A third model call is a third paid request for a bounded turn (SPEC-22).
            self.turn_state.bound_out(outcome.Reason.validation_reject.value)
            return {"jump_to": "end"}
        if self.turn_state.model_calls == 1:
            # Rows are rebuilt HERE, off the framework's tool result, because this
            # message is where model₂ is told which ids it may cite; the post-invoke
            # scan runs too late for that.
            self.turn_state.rows = _rows_from_messages(state["messages"])
            self.payer_gate.run()
            status_verdict = self.payer_gate.status_verdict
            status = (status_verdict or {}).get("status") or ""
            # SPEC-53: a degraded verdict — eligibility_client never reached the
            # payer, recognisable by the missing payer name — reaches model₂ as
            # `unavailable`, the outage word, never as a status the payer said.
            if status_verdict is not None and status_verdict.get("payer") is None:
                status = "unavailable"
            self.turn_state.status = status
            return {
                "messages": [
                    HumanMessage(
                        content=self._model2_message(
                            self.turn_state.status, status_verdict, self.turn_state.rows
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

    From the tool RESULT, not re-fetched by id: re-fetching would emit a second
    lookup record and open a gap between what the model saw and what SPEC-5/13
    validate against.
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


def _rows_from_messages(messages) -> List[Any]:
    """The turn's retrieved rows, from the first tool result in the thread.

    One reader for both call sites, so the rows model₂ may cite and the rows the
    citation gate validates against cannot come apart.
    """
    for message in messages:
        if getattr(message, "type", "") == "tool":
            return _rows_from_tool_result(message.content)
    return []


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

    Reasons are read off the EXCEPTION TYPE (eligibility-assistant-D-37):
    ``LLMBudgetExceeded`` is `spend_stop`, any other ``LLMError`` is
    `model_failure`. Only the ``LLMError`` branches set ``degraded``; a validation
    reject is a healthy assistant whose answer did not fit (D-71).
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
    turn_state.rows = _rows_from_messages(messages)

    if turn_state.reason is not None:
        return AgentResult(
            None, turn_state.reason, turn_state.llm_egress,
            turn_state.model_calls, turn_state.rows, False,
        )

    decision = _parse_decision(messages)
    if decision is None:
        # An unparseable decision is a validation reject, not a health fault (SPEC-13).
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

    A validated JSON text block rather than provider structured output: `tool_choice:
    none` beside structured output is unmeasured on this seam
    (eligibility-assistant-D-37), and a parse miss must land as a reject the fallback
    handles, not an ``LLMResponseError`` that bypasses it.
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
