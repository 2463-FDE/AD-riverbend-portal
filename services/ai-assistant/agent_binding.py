"""agent_binding — the agent framework's model binding, on the invoke_model seam.

`SeamChatModel` is a `langchain_core` chat model whose ONLY egress is
`llm_client._call` (eligibility-assistant SPEC-24, ADR 0019). The framework never
constructs a provider client of its own, so the four PRE-egress controls that sit
on `_call` — the gross-size char cap, the token/cost budget gate, the bearer
fail-closed guard, and the typed-error mapping — apply to the bytes an agent run
actually emits, tool definitions and tool results included. A Converse-style
client would have been gated on a payload that is not the egress payload.

`_call` does not reach `_result_from_response`, so the two POST-egress controls
ADR 0004 names (`adr/0004:38-40`, `:57`) do not come for free here: this module
carries a TWIN of them — the same fail-closed check on a malformed 200 and the
same metadata-only `llm call` line — pinned equal to `complete()`'s by
`tests/test_llm_client.py::test_a1_binding_guard_parity`. The twin admits a
`tool_use`-only turn, which is a valid answer on the agent path and is exactly
why `_result_from_response` (text-required) cannot simply be reused.

`_stream` is deliberately unimplemented and raises (SPEC-30): LangSmith's
`hide_inputs` / `hide_outputs` redaction, the two-layer hide ADR 0006 relies on
to keep trace payloads metadata-only, is bypassed on streamed payloads. A binding
that CANNOT stream removes that bypass by construction rather than by asking
callers not to use it.
"""
import time
from typing import Any, Dict, Iterator, List, Optional, Sequence

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.utils.function_calling import convert_to_openai_tool

from config import settings
from logging_config import configure
import llm_client

log = configure(settings.service_name)


def _anthropic_tool(tool: Any) -> Dict[str, Any]:
    """One tool definition in the Anthropic body shape.

    `langchain_core` ships no Anthropic converter, only the OpenAI one; that
    helper normalizes every accepted input (BaseTool, pydantic model, callable,
    raw dict) into name/description/parameters, so the Anthropic shape is a
    rename of `parameters` to `input_schema` rather than a second walk over the
    tool object."""
    function = convert_to_openai_tool(tool)["function"]
    definition: Dict[str, Any] = {
        "name": function["name"],
        "input_schema": function.get("parameters", {}),
    }
    description = function.get("description")
    if description:
        definition["description"] = description
    return definition


def _content_blocks(message: BaseMessage) -> List[Dict[str, Any]]:
    """The Anthropic content blocks for one non-system message.

    A `ToolMessage` becomes a `tool_result` block carrying its `tool_call_id`
    (Anthropic puts tool results inside a USER turn, not a role of their own).
    An `AIMessage` becomes its text, then one `tool_use` block per tool call —
    the mirror of what `_generate` read off the response, so a second `invoke`
    can replay the model's own turn."""
    if isinstance(message, ToolMessage):
        return [
            {
                "type": "tool_result",
                "tool_use_id": message.tool_call_id,
                "content": message.content
                if isinstance(message.content, str)
                else str(message.content),
            }
        ]
    blocks: List[Dict[str, Any]] = []
    text = message.content if isinstance(message.content, str) else str(message.content)
    if text:
        blocks.append({"type": "text", "text": text})
    for call in getattr(message, "tool_calls", None) or []:
        blocks.append(
            {
                "type": "tool_use",
                "id": call["id"],
                "name": call["name"],
                "input": call.get("args", {}),
            }
        )
    return blocks


def _role_of(message: BaseMessage) -> str:
    # Tool results ride a user turn; everything the model said is assistant.
    if isinstance(message, AIMessage):
        return "assistant"
    return "user"


def _to_bedrock(messages: Sequence[BaseMessage]) -> List[Dict[str, Any]]:
    """Framework messages → the Anthropic `messages` array, roles alternating.

    Consecutive same-role messages are folded into ONE turn: the API rejects a
    body whose roles do not alternate, and an agent loop routinely produces two
    adjacent user messages (a human turn followed by a tool result)."""
    turns: List[Dict[str, Any]] = []
    for message in messages:
        role = _role_of(message)
        blocks = _content_blocks(message)
        if not blocks:
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"].extend(blocks)
        else:
            turns.append({"role": role, "content": blocks})
    return turns


class SeamChatModel(BaseChatModel):
    """A chat model whose single egress is `llm_client._call`."""

    @property
    def _llm_type(self) -> str:
        return "riverbend-invoke-model-seam"

    def bind_tools(
        self,
        tools: Sequence[Any],
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, BaseMessage]:
        """Bind tool definitions so they ride `_call`'s `extra_body`.

        `extra_body` is what `_BedrockMessages.create` merges into the request
        body top level, and `_enforce_char_cap` / `max_input_tokens` both count
        it — so the tool surface is inside the budget gate, not beside it."""
        return self.bind(tools=[_anthropic_tool(tool) for tool in tools], **kwargs)

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        if stop is not None:
            # A framework knob with no seam equivalent. Honouring it would mean
            # a request shape _call never gated; dropping it silently would
            # mean a caller believing in a stop sequence that does not exist.
            raise ValueError(
                "SeamChatModel does not support `stop`: the invoke_model seam "
                "has no equivalent and the request must not egress ungated"
            )
        system, conversation = _split_system(messages)
        tools = kwargs.get("tools")
        extra_body = {"tools": tools} if tools else None

        started = time.monotonic()
        response = llm_client._call(
            _to_bedrock(conversation),
            system,
            # Never a framework kwarg: the output cap is the same config value
            # complete() spends (llm_client.py:650, config.py's
            # llm_max_output_tokens), so an agent run cannot widen it.
            settings.llm_max_output_tokens,
            extra_body,
        )
        message = _guarded_message(response, started)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        # SPEC-30. Structural, not a policy line — see the module docstring.
        raise NotImplementedError(
            "SeamChatModel cannot stream: LangSmith's hide_inputs/hide_outputs "
            "redaction is bypassed on streamed payloads (ADR 0006, ADR 0019)"
        )


def _split_system(messages: Sequence[BaseMessage]) -> tuple:
    """Peel the leading `SystemMessage` off as `_call`'s `system` argument.

    The system prompt is a body key of its own (`body["system"]`,
    `llm_client.py:244`) that `max_input_tokens` counts on its own line
    (`:368`) — it is never smuggled into a `user` turn."""
    system_positions = [
        index for index, message in enumerate(messages)
        if isinstance(message, SystemMessage)
    ]
    if system_positions not in ([], [0]):
        # Refused BEFORE _call, so nothing egresses. Anything else would have to
        # either fold the system prompt into a `user` turn — the exact smuggling
        # the byte gate's separate system line exists to prevent — or drop it.
        raise ValueError(
            "SeamChatModel takes at most one SystemMessage and only as the "
            "leading message (found %d at positions %s)"
            % (len(system_positions), system_positions)
        )
    if system_positions == [0]:
        head = messages[0]
        text = head.content if isinstance(head.content, str) else str(head.content)
        return text, list(messages[1:])
    return None, list(messages)


def _guarded_message(response: Any, started: float) -> AIMessage:
    """The post-egress twin of `_result_from_response`'s two controls.

    `_call` returns the adapted response without applying them, because
    `_result_from_response` is `complete()`'s tail and this path does not go
    through it. The checks are the ADR 0004 names (`:38-40`, `:57`) applied to
    this path's response shape, with ONE deliberate difference: a `tool_use` block satisfies the
    content check beside `text`, because a tool-only turn is the agent path's
    valid answer. Everything else — fail closed on a malformed 200, require
    explicit integer usage, carry only the request id on the error, emit the
    same metadata-only `llm call` line — is identical, and
    `test_a1_binding_guard_parity` pins the two equal.

    THREE controls, not two: the receive half reads more fields off the
    response than `_result_from_response` does (`id` / `name` / `input` on a
    `tool_use` block, which `_adapt` defaults to `None` when the body omits
    them), so their shapes are checked here as well. Without that check a
    malformed 200 leaves this function as a pydantic `ValidationError` raised
    inside `_message_from_response` — untyped, so a caller mapping `LLMError`
    to a fallback misses it, and payload-bearing, because pydantic embeds the
    offending value in its message."""
    request_id = getattr(response, "id", None)
    blocks = getattr(response, "content", []) or []
    if not any(getattr(block, "type", None) in ("text", "tool_use") for block in blocks):
        raise llm_client.LLMResponseError(
            "no text or tool_use block in response (request_id=%s)" % request_id,
            request_id=request_id,
        )
    for block in blocks:
        # Field names only in the message — a fixed vocabulary, never the
        # response bytes the field carries.
        block_type = getattr(block, "type", None)
        if block_type == "text":
            fields = (("text", str),)
        elif block_type == "tool_use":
            fields = (("id", str), ("name", str), ("input", dict))
        else:
            continue
        for field, expected in fields:
            if not isinstance(getattr(block, field, None), expected):
                raise llm_client.LLMResponseError(
                    "malformed %s block: %s (request_id=%s)"
                    % (block_type, field, request_id),
                    request_id=request_id,
                )
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        raise llm_client.LLMResponseError(
            "response missing token usage (request_id=%s)" % request_id,
            request_id=request_id,
        )
    # Metadata only — never a message, a tool argument or a completion.
    log.info(
        "llm call model=%s in_tokens=%d out_tokens=%d cost=$%.4f latency=%.2fs request_id=%s",
        getattr(response, "model", settings.bedrock_model_id),
        input_tokens,
        output_tokens,
        llm_client.estimate_cost(input_tokens, output_tokens),
        time.monotonic() - started,
        request_id,
    )
    return _message_from_response(response)


def _message_from_response(response: Any) -> AIMessage:
    """The adapted response → one `AIMessage`, every carried field named.

    `content` is the response's `text` blocks joined in order — `""` on a
    tool-only turn, which is the agent path's valid answer and the string the
    turn's parser reads. `tool_calls` are the `tool_use` blocks' id / name /
    input; note the package REBUILDS each entry through `tool_call()` and adds
    its own `type: "tool_call"` key, so callers assert per field. `usage` is
    consumed by the guard and the log line only and is deliberately NOT placed
    on the message: spend is `_call`'s pre-egress gate, never a post-hoc count.
    `id` and `model` reach the log line only."""
    texts = []
    tool_calls = []
    for block in getattr(response, "content", []) or []:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            texts.append(block.text or "")
        elif block_type == "tool_use":
            tool_calls.append(
                {"id": block.id, "name": block.name, "args": block.input}
            )
    return AIMessage(
        content="".join(texts),
        tool_calls=tool_calls,
        response_metadata={"stop_reason": getattr(response, "stop_reason", None)},
    )
