"""Production LLM client wrapper for the Anthropic API.

Contract (see ADR 0004):
  * every call is bounded — connect/read timeouts and SDK-managed retries
    with exponential backoff (the opposite of the D4 no-timeout pattern);
  * a token/cost budget is enforced BEFORE any request is sent;
  * structured output is validated against a Pydantic model;
  * failures raise typed exceptions — never the repo's
    ``{"error": str(e)}`` 200-OK anti-pattern;
  * prompt and completion bodies are NEVER logged or embedded in exception
    messages. Metadata only. See docs/phi-logging-policy.md.

Note on SDK pin: anthropic==0.72.0 (newest release compatible with the local
Python 3.8 toolchain) predates ``client.messages.parse``; structured output is
requested via ``extra_body={"output_config": {"format": ...}}`` and validated
manually. When the toolchain moves to 3.9+, upgrade the pin and switch to
``messages.parse``.
"""
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

import anthropic
import httpx
from pydantic import BaseModel, ValidationError

from config import settings
from logging_config import configure

log = configure(settings.service_name)

# claude-opus-4-8 pricing, USD per million tokens.
PRICE_PER_MTOK_INPUT = 5.00
PRICE_PER_MTOK_OUTPUT = 25.00


class LLMError(Exception):
    """Base class. Messages carry metadata only — never prompt/response text."""


class LLMBudgetExceeded(LLMError):
    """Pre-flight token or cost budget check failed; no request was sent."""


class LLMUnavailable(LLMError):
    """Rate limited, connection failure, or upstream 5xx after SDK retries."""


class LLMConfigError(LLMError):
    """Bad model name or credentials."""


class LLMResponseError(LLMError):
    """Response did not match the requested structure."""


@dataclass
class LLMResult:
    text: Optional[str] = None
    parsed: Optional[BaseModel] = None
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_seconds: float = 0.0
    request_id: Optional[str] = None
    model: str = field(default_factory=lambda: settings.anthropic_model)


# Module-level client so tests can monkeypatch it (same pattern as
# tests/test_eligibility_check.py monkeypatching check_mod.requests).
# The "not-set" fallback keeps `import llm_client` working in CI's keyless
# import smoke test; real calls without a key fail as LLMConfigError.
client = anthropic.Anthropic(
    api_key=settings.anthropic_api_key or "not-set",
    timeout=httpx.Timeout(
        settings.llm_read_timeout_seconds,
        connect=settings.llm_connect_timeout_seconds,
    ),
    max_retries=settings.llm_max_retries,
)


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens * PRICE_PER_MTOK_INPUT + output_tokens * PRICE_PER_MTOK_OUTPUT
    ) / 1_000_000


def count_input_tokens(messages: List[Dict[str, Any]], system: Optional[str] = None) -> int:
    kwargs: Dict[str, Any] = {"model": settings.anthropic_model, "messages": messages}
    if system is not None:
        kwargs["system"] = system
    return client.messages.count_tokens(**kwargs).input_tokens


def _input_char_count(messages: List[Dict[str, Any]], system: Optional[str]) -> int:
    total = len(system or "")
    for message in messages:
        content = message.get("content", "")
        total += len(content) if isinstance(content, str) else len(str(content))
    return total


def _enforce_char_cap(messages: List[Dict[str, Any]], system: Optional[str]) -> None:
    """Local preflight — no network. Rejects grossly oversized prompts BEFORE any
    SDK call, so an over-budget (possibly PHI-bearing) payload never egresses via
    count_tokens. The exact token cap is still enforced downstream by
    _enforce_budget for prompts that pass this gate."""
    chars = _input_char_count(messages, system)
    if chars > settings.llm_max_input_chars:
        raise LLMBudgetExceeded(
            "input %d chars exceeds local cap %d — no upstream call made"
            % (chars, settings.llm_max_input_chars)
        )


def _enforce_budget(input_tokens: int, max_tokens: int) -> None:
    if input_tokens > settings.llm_max_input_tokens:
        raise LLMBudgetExceeded(
            "input tokens %d exceed cap %d" % (input_tokens, settings.llm_max_input_tokens)
        )
    worst_case = estimate_cost(input_tokens, max_tokens)
    if worst_case > settings.llm_max_cost_per_request_usd:
        raise LLMBudgetExceeded(
            "worst-case cost $%.4f exceeds cap $%.2f (in=%d, max_out=%d)"
            % (worst_case, settings.llm_max_cost_per_request_usd, input_tokens, max_tokens)
        )


def _call(
    messages: List[Dict[str, Any]],
    system: Optional[str],
    max_tokens: int,
    extra_body: Optional[Dict[str, Any]] = None,
) -> "anthropic.types.Message":
    """Pre-flight budget check, then one bounded, retried API call.

    Maps SDK exceptions to this module's typed errors, most specific first.
    Exception messages carry status/request metadata only.

    Both the token-count call and the completion call are SDK requests that can
    fail with auth/rate-limit/5xx/connection errors, so BOTH sit inside the
    mapping ``try``. ``_enforce_budget`` runs between them and raises
    ``LLMBudgetExceeded`` — an ``LLMError``, not an ``anthropic.*`` type, so it
    passes through the except clauses below untouched.

    ``_enforce_char_cap`` runs FIRST, before the ``try`` and before any SDK
    call: ``count_tokens`` is itself a network request that would egress the
    payload, so a grossly oversized prompt must be rejected locally.
    """
    _enforce_char_cap(messages, system)

    kwargs: Dict[str, Any] = {
        "model": settings.anthropic_model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system is not None:
        kwargs["system"] = system
    if extra_body is not None:
        kwargs["extra_body"] = extra_body

    try:
        input_tokens = count_input_tokens(messages, system=system)
        _enforce_budget(input_tokens, max_tokens)
        return client.messages.create(**kwargs)
    except (anthropic.NotFoundError, anthropic.AuthenticationError) as exc:
        raise LLMConfigError(
            "model/auth error (status=%s)" % getattr(exc, "status_code", "?")
        ) from None
    except anthropic.RateLimitError as exc:
        raise LLMUnavailable(
            "rate limited after retries (status=%s)" % getattr(exc, "status_code", "?")
        ) from None
    except anthropic.APIStatusError as exc:
        raise LLMUnavailable(
            "upstream error (status=%s)" % getattr(exc, "status_code", "?")
        ) from None
    except anthropic.APIConnectionError:
        raise LLMUnavailable("connection error after retries") from None


def _result_from_response(response: Any, started: float) -> LLMResult:
    text = None
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text = block.text
            break
    usage = response.usage
    result = LLMResult(
        text=text,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        estimated_cost_usd=estimate_cost(usage.input_tokens, usage.output_tokens),
        latency_seconds=time.monotonic() - started,
        request_id=getattr(response, "id", None),
        model=getattr(response, "model", settings.anthropic_model),
    )
    # Metadata only — never the prompt or the completion.
    log.info(
        "llm call model=%s in_tokens=%d out_tokens=%d cost=$%.4f latency=%.2fs request_id=%s",
        result.model,
        result.input_tokens,
        result.output_tokens,
        result.estimated_cost_usd,
        result.latency_seconds,
        result.request_id,
    )
    return result


def complete(
    prompt: str,
    system: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> LLMResult:
    """Bounded, budgeted text completion."""
    max_tokens = max_tokens or settings.llm_max_output_tokens
    started = time.monotonic()
    messages = [{"role": "user", "content": prompt}]
    response = _call(messages, system, max_tokens)
    return _result_from_response(response, started)


def complete_structured(
    prompt: str,
    output_model: Type[BaseModel],
    system: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> LLMResult:
    """Completion constrained to a JSON schema, validated into output_model."""
    max_tokens = max_tokens or settings.llm_max_output_tokens
    started = time.monotonic()
    messages = [{"role": "user", "content": prompt}]
    extra_body = {
        "output_config": {
            "format": {
                "type": "json_schema",
                "schema": output_model.model_json_schema(),
            }
        }
    }
    response = _call(messages, system, max_tokens, extra_body=extra_body)
    result = _result_from_response(response, started)
    if result.text is None:
        raise LLMResponseError(
            "no text block in response (request_id=%s)" % result.request_id
        )
    try:
        result.parsed = output_model.model_validate_json(result.text)
    except (ValidationError, json.JSONDecodeError):
        # Deliberately does not include the model output in the message.
        raise LLMResponseError(
            "response failed %s validation (request_id=%s)"
            % (output_model.__name__, result.request_id)
        ) from None
    return result
