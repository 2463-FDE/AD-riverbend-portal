"""Production LLM client wrapper for Claude on AWS Bedrock.

Contract (see ADR 0004, provider superseded by ADR 0005):
  * every call is bounded — connect/read timeouts and SDK-managed retries
    with exponential backoff (the opposite of the D4 no-timeout pattern);
  * a token/cost budget is enforced BEFORE any request is sent, using a
    guaranteed LOCAL upper bound on the token count (UTF-8 byte length, which
    a byte-level BPE tokenizer can never exceed) — no vendor call (not even
    count_tokens) participates in the preflight gate, and the bound cannot
    under-count, so an over-budget, possibly PHI-bearing payload never crosses
    the trust boundary. The only egress is the completion call itself, whose
    usage is post-approval telemetry;
  * structured output is validated against a Pydantic model;
  * failures raise typed exceptions — never the repo's
    ``{"error": str(e)}`` 200-OK anti-pattern;
  * prompt and completion bodies are NEVER logged or embedded in exception
    messages. Metadata only. See docs/phi-logging-policy.md.

Provider: Claude on Amazon Bedrock via boto3 ``bedrock-runtime.invoke_model``.
Auth is a Bedrock bearer API key, which botocore reads from the
``AWS_BEARER_TOKEN_BEDROCK`` environment variable; no AWS credential ever
passes through this module. The wrapper FAILS CLOSED when that variable is
absent (``_require_bearer_token``, checked before the sole egress) — it never
falls back to boto3's ambient credential chain (instance role, ECS task role,
stray ``AWS_*`` env vars), which would sign PHI-bearing calls under an AWS
identity whose BAA posture this service knows nothing about. The boto3 call is placed behind a thin adapter
(``_BedrockClient``) that exposes the same ``client.messages.create(**kwargs)``
seam the wrapper was built around, so the budget gate, PHI-silent logging, and
structured-output path are unchanged. Structured output is still requested via
``extra_body={"output_config": {"format": ...}}`` (folded into the Bedrock
request body) and validated manually with Pydantic.
"""
import json
import os
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Type

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    CredentialRetrievalError,
    NoCredentialsError,
    PartialCredentialsError,
)
from pydantic import BaseModel, ValidationError

from config import settings
from logging_config import configure

log = configure(settings.service_name)

# Bedrock pricing, USD per million tokens, keyed by FOUNDATION-MODEL id (a
# region-scoped inference-profile prefix — us./eu./apac./global. — is stripped
# before lookup, so every regional profile of a priced model resolves). The
# worst-case-cost budget gate and the cost telemetry both derive from this
# table, and it FAILS CLOSED: a BEDROCK_MODEL_ID with no entry here and no
# explicit LLM_PRICE_PER_MTOK_INPUT/OUTPUT override refuses the call
# (LLMConfigError) before anything egresses — an unpriced model must never
# slip past the budget gate at whatever price we guessed (Codex review, PR #5).
_MODEL_PRICING = {
    "anthropic.claude-sonnet-4-6": (3.00, 15.00),
}
_INFERENCE_PROFILE_PREFIXES = ("us.", "eu.", "apac.", "global.")

# Constant Bedrock requires in the request body for Anthropic models.
_BEDROCK_ANTHROPIC_VERSION = "bedrock-2023-05-31"

# Bedrock/botocore error codes that mean "the request or credentials are wrong"
# (not retryable) vs. "temporarily unavailable" (already retried by botocore).
# Note: Bedrock also raises ValidationException for model-side "input too long".
# Mapping that to LLMConfigError (not LLMBudgetExceeded) is deliberate: the
# local char cap + byte-based token gate cannot under-count, so a payload that
# trips the model-side limit means the local caps are misconfigured relative to
# the model — a config problem, not a runtime budget breach.
_CONFIG_ERROR_CODES = frozenset({
    "AccessDeniedException",
    "UnrecognizedClientException",
    "ValidationException",
    "ResourceNotFoundException",
})
_THROTTLE_CODES = frozenset({
    "ThrottlingException",
    "TooManyRequestsException",
    "ServiceQuotaExceededException",
})


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
    model: str = field(default_factory=lambda: settings.bedrock_model_id)


def _adapt(payload: Dict[str, Any], request_id: Optional[str]) -> SimpleNamespace:
    """Shape a Bedrock invoke_model JSON body like the anthropic Message object
    the rest of this module expects: ``.content[].type/.text``, ``.usage``,
    ``.id``, ``.model``. Keeps _result_from_response provider-agnostic.

    Structural absence is PRESERVED, not masked: a missing ``content`` becomes an
    empty block list and a missing ``usage`` becomes ``None`` token counts, so
    _result_from_response can fail the call closed (LLMResponseError) on a
    malformed / schema-drifted 200 instead of emitting a blank completion with
    $0 telemetry that reads as a clean success (Codex review, PR #5 round 4).
    Bedrock always returns both in practice; their absence is a defect signal,
    not a case to degrade past."""
    content = [
        SimpleNamespace(type=block.get("type"), text=block.get("text"))
        for block in payload.get("content", []) or []
    ]
    usage = payload.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    return SimpleNamespace(
        content=content,
        usage=SimpleNamespace(
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        ),
        id=payload.get("id") or request_id,
        model=payload.get("model", settings.bedrock_model_id),
    )


class _BedrockMessages:
    """Exposes ``create(**kwargs)`` over Bedrock ``invoke_model`` so the wrapper
    keeps a single provider seam. Botocore exceptions propagate to ``_call``,
    which maps them to this module's typed errors."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        extra_body: Optional[Dict[str, Any]] = None,
    ) -> SimpleNamespace:
        body: Dict[str, Any] = {
            "anthropic_version": _BEDROCK_ANTHROPIC_VERSION,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system is not None:
            body["system"] = system
        if extra_body:
            # Structured-output config (output_config) rides at the top level of
            # the Bedrock body, same as it would on the first-party API.
            body.update(extra_body)
        response = self._runtime.invoke_model(
            modelId=model,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )
        payload = json.loads(response["body"].read())
        request_id = response.get("ResponseMetadata", {}).get("RequestId")
        return _adapt(payload, request_id)


class _BedrockClient:
    """anthropic-SDK-shaped facade: ``client.messages.create(...)``."""

    def __init__(self, runtime: Any) -> None:
        self.messages = _BedrockMessages(runtime)


# Module-level boto3 runtime + client so tests can monkeypatch `client` (same
# pattern as tests/test_eligibility_check.py monkeypatching check_mod.requests).
# boto3 resolves credentials (the AWS_BEARER_TOKEN_BEDROCK bearer key) lazily on
# the first call, so construction needs no key — CI's keyless import smoke still
# passes; a real call without a key fails as LLMConfigError. Retries/timeouts
# are the botocore equivalent of ADR 0004's bounded-call discipline. botocore's
# retries.max_attempts is the retry count (resolved total_max_attempts =
# max_attempts + 1), so it maps directly onto llm_max_retries.
_runtime = boto3.client(
    "bedrock-runtime",
    region_name=settings.aws_region,
    config=Config(
        connect_timeout=settings.llm_connect_timeout_seconds,
        read_timeout=settings.llm_read_timeout_seconds,
        retries={"max_attempts": settings.llm_max_retries, "mode": "standard"},
    ),
)
client = _BedrockClient(_runtime)


def _resolve_pricing() -> tuple:
    """(input, output) USD-per-MTok for the RESOLVED model — fail closed.

    Resolution order: the explicit LLM_PRICE_PER_MTOK_INPUT/OUTPUT env pair
    (both or neither — a half-set override is a config error, not a default),
    then _MODEL_PRICING keyed by settings.bedrock_model_id with any
    inference-profile region prefix stripped. No match raises LLMConfigError:
    the cost gate must refuse a model it cannot price, not price it as Sonnet.
    Runs per call (inside the preflight, before any egress) so a
    misconfigured model refuses requests rather than failing import — CI's
    keyless import smoke stays green."""
    override_input = settings.llm_price_per_mtok_input
    override_output = settings.llm_price_per_mtok_output
    if (override_input is None) != (override_output is None):
        raise LLMConfigError(
            "LLM_PRICE_PER_MTOK_INPUT and LLM_PRICE_PER_MTOK_OUTPUT must be set together"
        )
    if override_input is not None:
        return override_input, override_output
    model_id = settings.bedrock_model_id
    base = model_id
    for prefix in _INFERENCE_PROFILE_PREFIXES:
        if base.startswith(prefix):
            base = base[len(prefix):]
            break
    pricing = _MODEL_PRICING.get(base)
    if pricing is None:
        raise LLMConfigError(
            "no pricing entry for model %s — the cost gate cannot price it; "
            "add it to _MODEL_PRICING or set LLM_PRICE_PER_MTOK_INPUT/OUTPUT" % model_id
        )
    return pricing


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    price_input, price_output = _resolve_pricing()
    return (input_tokens * price_input + output_tokens * price_output) / 1_000_000


# Claude's tokenizer is byte-level BPE: all 256 single-byte tokens are in the
# vocabulary, so no input can ever produce more tokens than it has UTF-8 bytes.
# The UTF-8 byte length is therefore a GUARANTEED upper bound on the real input
# token count for ANY input — high-entropy, all-digit, or multibyte-unicode
# payloads that tokenize denser than prose included. This is a hard ceiling,
# not a heuristic, and there is no env knob to loosen it. Plus a small fixed
# allowance for the role/structure tokens the API counts around the system
# prompt and each message.
_BASE_TOKEN_OVERHEAD = 8
_PER_MESSAGE_TOKEN_OVERHEAD = 8


def _extra_body_text(extra_body: Optional[Dict[str, Any]]) -> str:
    """Deterministic serialization of extra_body for budget accounting.

    extra_body carries the structured-output JSON schema (and any other tooling
    payload). The API counts it as input, so it MUST be inside the budget gate —
    otherwise a large/nested schema egresses unbounded (Codex review). Serialized
    with the same default=str fallback used for logging so non-JSON-native values
    never raise here."""
    return "" if extra_body is None else json.dumps(extra_body, default=str, sort_keys=True)


def max_input_tokens(
    messages: List[Dict[str, Any]],
    system: Optional[str] = None,
    extra_body: Optional[Dict[str, Any]] = None,
) -> int:
    """Guaranteed LOCAL upper bound on input tokens — NO network call, and it
    can only over-count, never under-count.

    The budget gate runs against this, never against the vendor's count_tokens
    (itself an SDK egress of the full payload). Because it cannot under-count, a
    prompt that passes the token cap here is guaranteed under the real cap, so
    no over-budget — possibly PHI-bearing — payload can egress. The exact token
    count arrives on the completion response as post-approval telemetry.

    extra_body (the structured-output schema) is bounded by its serialized byte
    length so it cannot bypass the gate.
    """
    total = _BASE_TOKEN_OVERHEAD + len((system or "").encode("utf-8"))
    for message in messages:
        content = message.get("content", "")
        text = content if isinstance(content, str) else str(content)
        total += _PER_MESSAGE_TOKEN_OVERHEAD + len(text.encode("utf-8"))
    extra_text = _extra_body_text(extra_body)
    if extra_text:
        total += _PER_MESSAGE_TOKEN_OVERHEAD + len(extra_text.encode("utf-8"))
    return total


def _input_char_count(
    messages: List[Dict[str, Any]],
    system: Optional[str],
    extra_body: Optional[Dict[str, Any]] = None,
) -> int:
    total = len(system or "")
    for message in messages:
        content = message.get("content", "")
        total += len(content) if isinstance(content, str) else len(str(content))
    total += len(_extra_body_text(extra_body))
    return total


def _enforce_char_cap(
    messages: List[Dict[str, Any]],
    system: Optional[str],
    extra_body: Optional[Dict[str, Any]] = None,
) -> None:
    """Local gross-size backstop — no network. Rejects grossly oversized prompts
    BEFORE any SDK call. The token/cost budget is enforced separately and also
    locally by _enforce_budget (against max_input_tokens, a guaranteed byte-based
    upper bound); this char cap is a cheap independent defense-in-depth stop, not
    the token gate. extra_body counts toward the cap so an oversized schema is
    rejected here too."""
    chars = _input_char_count(messages, system, extra_body)
    if chars > settings.llm_max_input_chars:
        raise LLMBudgetExceeded(
            "input %d chars exceeds local cap %d — no upstream call made"
            % (chars, settings.llm_max_input_chars)
        )


# Non-empty placeholder values that templates ship and CI seeds via
# `cp .env.example .env`. A bare presence check would accept them and let a
# deploy that never set a real key egress PHI before AWS rejects the auth
# (Codex review, PR #5 round 5), so they are treated exactly like absence.
# Matched case-insensitively after stripping surrounding whitespace.
_PLACEHOLDER_BEARER_TOKENS = frozenset({
    "changeme",
    "change-me",
    "change_me",
    "placeholder",
    "your-bedrock-bearer-token",
    "your-token-here",
    "todo",
    "xxx",
})


def _require_bearer_token() -> None:
    """Refuse egress unless the Bedrock bearer key is explicitly configured.

    boto3's default credential chain would otherwise sign the call with any
    ambient AWS identity available (instance role, ECS task role, stray AWS_*
    env vars) and the request would SUCCEED under an account whose BAA posture
    this service knows nothing about (Codex review, PR #5 round 3). When the
    variable IS set to a real value, botocore's documented precedence uses
    bearer auth for bedrock-runtime ahead of any sigv4 credentials, so ambient
    identities cannot sign this service's calls (live-verified: call succeeds
    via bearer with garbage AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY planted in
    the environment).

    Absence, an empty/whitespace-only value, AND known placeholder sentinels
    (the ``changeme`` that .env.example ships and CI copies into .env) are all
    treated as "not configured" — a non-empty placeholder must NOT satisfy the
    guard, or a deploy that forgot to swap the placeholder would egress PHI
    before AWS ever rejected the auth (Codex review, PR #5 round 5). The value
    is only compared, never read into app state, logged, or embedded in the
    error. Checked per call, not at import — CI's keyless import smoke must keep
    passing (same rationale as the pricing gate)."""
    token = (os.environ.get("AWS_BEARER_TOKEN_BEDROCK") or "").strip()
    if not token or token.lower() in _PLACEHOLDER_BEARER_TOKENS:
        raise LLMConfigError(
            "AWS_BEARER_TOKEN_BEDROCK is not set to a real value — refusing to "
            "fall back to ambient AWS credentials"
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
) -> SimpleNamespace:
    """Fully-local pre-flight budget check, then one bounded, retried API call.

    The ENTIRE budget gate runs before the ``try`` and before any SDK call:
    ``_enforce_char_cap`` (gross-size backstop) and ``_enforce_budget`` (token +
    cost caps) both check a deterministic LOCAL estimate. No vendor request —
    not even ``count_tokens`` — participates in the gate, because such a request
    would egress the full (possibly PHI-bearing, possibly over-budget) payload
    across the trust boundary. ``_require_bearer_token`` then refuses egress
    entirely when the Bedrock bearer key is absent, so the call can never be
    signed by ambient AWS credentials. The completion ``create`` call is the
    sole egress; its ``usage`` is post-approval telemetry consumed downstream.

    The ``try`` maps botocore exceptions from that one call to this module's
    typed errors, most specific first. Exception messages carry Bedrock error
    code / HTTP status metadata only — never prompt or response text.
    """
    _enforce_char_cap(messages, system, extra_body)
    input_tokens = max_input_tokens(messages, system=system, extra_body=extra_body)
    _enforce_budget(input_tokens, max_tokens)
    _require_bearer_token()

    kwargs: Dict[str, Any] = {
        "model": settings.bedrock_model_id,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system is not None:
        kwargs["system"] = system
    if extra_body is not None:
        kwargs["extra_body"] = extra_body

    try:
        return client.messages.create(**kwargs)
    except ClientError as exc:
        error = exc.response.get("Error", {})
        code = error.get("Code", "?")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        # Bad model, bad request shape, or auth/permission → config error;
        # throttling / capacity / 5xx (after botocore retries) → unavailable.
        if code in _CONFIG_ERROR_CODES or status in (401, 403, 404):
            raise LLMConfigError(
                "model/auth error (code=%s status=%s)" % (code, status)
            ) from None
        if code in _THROTTLE_CODES or status == 429:
            raise LLMUnavailable(
                "throttled after retries (code=%s)" % code
            ) from None
        raise LLMUnavailable(
            "upstream error (code=%s status=%s)" % (code, status)
        ) from None
    except (NoCredentialsError, PartialCredentialsError, CredentialRetrievalError) as exc:
        # Local credential-chain failure — botocore raises these BEFORE any
        # request reaches AWS (missing/partial AWS_BEARER_TOKEN_BEDROCK or a
        # broken fallback provider). A deployment/config break, not an outage:
        # retrying can never succeed, so it must NOT surface as LLMUnavailable
        # (Codex review, PR #5 round 2). Must precede the BotoCoreError catch —
        # all three subclass it. Message names the exception type only.
        raise LLMConfigError(
            "credential configuration error (%s)" % type(exc).__name__
        ) from None
    except BotoCoreError as exc:
        # Connect/read timeout or endpoint connection failure, after retries.
        raise LLMUnavailable(
            "connection error after retries (%s)" % type(exc).__name__
        ) from None
    except (ValueError, KeyError) as exc:
        # A malformed/empty Bedrock 200 body (json.loads → ValueError, or a
        # missing "body" key). The anthropic SDK absorbed this internally; boto3
        # does not, so map it here to keep ADR 0004's Typed-failures guarantee.
        # Message names the exception type only — never the response bytes.
        raise LLMUnavailable(
            "malformed upstream response (%s)" % type(exc).__name__
        ) from None


def _result_from_response(response: Any, started: float) -> LLMResult:
    text = None
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text = block.text
            break
    request_id = getattr(response, "id", None)
    # Fail closed on a malformed / schema-drifted 200. A response with no usable
    # text block would otherwise become a blank but "successful" completion —
    # e.g. empty patient intake instructions returned to a clinician while the
    # caller sees no error (Codex review, PR #5 round 4). Both complete() and
    # complete_structured() flow through here, so the guard lives here once.
    # Messages carry the request id only — never the prompt or response bytes.
    if not text:
        raise LLMResponseError("no text block in response (request_id=%s)" % request_id)
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    # Usage is post-approval telemetry, but its ABSENCE signals a malformed /
    # drifted response (Bedrock always returns it): defaulting to 0 would log a
    # clean $0 call for a real PHI vendor egress, under-reporting what crossed
    # the boundary. Require explicit integer counts; fail closed otherwise.
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        raise LLMResponseError("response missing token usage (request_id=%s)" % request_id)
    result = LLMResult(
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=estimate_cost(input_tokens, output_tokens),
        latency_seconds=time.monotonic() - started,
        request_id=request_id,
        model=getattr(response, "model", settings.bedrock_model_id),
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


def _trace_metadata(response: Any, _kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Scalar-only run metadata for a LangSmith trace of one Bedrock call.

    Reads ONLY non-PHI scalar fields off the adapted response — never the
    completion text, never the request kwargs (``_kwargs`` is accepted for the
    tracing callback signature and deliberately ignored, since ``messages`` /
    ``system`` carry PHI). These are exactly the fields ``_result_from_response``
    already logs. Token usage is included only when present as integers, so a
    malformed response never fabricates a $0 cost in the trace. Called only
    from tracing.wrap_create, whose caller swallows any exception — pricing
    here (estimate_cost) has already resolved in the preflight, so it will not
    raise on the served path, but a failure would be non-fatal regardless."""
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    metadata: Dict[str, Any] = {
        "model": getattr(response, "model", settings.bedrock_model_id),
        "request_id": getattr(response, "id", None),
    }
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        metadata["input_tokens"] = input_tokens
        metadata["output_tokens"] = output_tokens
        metadata["estimated_cost_usd"] = round(estimate_cost(input_tokens, output_tokens), 6)
    return metadata


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


def _strict_schema(output_model: Type[BaseModel]) -> Dict[str, Any]:
    """Pydantic's ``model_json_schema()`` omits ``additionalProperties``, but the
    structured-output API requires every object node to set it to ``false``
    explicitly — the request is otherwise rejected with ValidationException
    ("For 'object' type, 'additionalProperties' must be explicitly set to
    false"; found by live Bedrock verification, but the first-party API has the
    same rule). Walk the whole schema (nested ``$defs``, ``anyOf``, ``items``,
    ...) and pin it on each object node. ``setdefault`` so a model that
    explicitly set something else still surfaces as a typed upstream rejection
    instead of being silently rewritten."""
    schema = output_model.model_json_schema()

    def pin(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                node.setdefault("additionalProperties", False)
            for value in node.values():
                pin(value)
        elif isinstance(node, list):
            for item in node:
                pin(item)

    pin(schema)
    return schema


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
                "schema": _strict_schema(output_model),
            }
        }
    }
    response = _call(messages, system, max_tokens, extra_body=extra_body)
    # _result_from_response has already failed closed on an absent text block or
    # usage; here result.text is guaranteed present and only its JSON shape is
    # still unverified.
    result = _result_from_response(response, started)
    try:
        result.parsed = output_model.model_validate_json(result.text)
    except (ValidationError, json.JSONDecodeError):
        # Deliberately does not include the model output in the message.
        raise LLMResponseError(
            "response failed %s validation (request_id=%s)"
            % (output_model.__name__, result.request_id)
        ) from None
    return result


# --- observability (ADR 0006) --------------------------------------------
# Wrap the single Bedrock provider seam with LangSmith tracing. This is a NO-OP
# passthrough unless LANGSMITH_TRACING=true (see tracing.wrap_create): metadata
# only, PHI-silent (payloads blanked in two independent layers), and best-effort
# (a tracing failure never blocks or slows a completion). Applied at import end
# so it decorates the constructed `client`; _call resolves client.messages.create
# at call time, so the wrapped callable is what actually runs in production.
# Guarded because tracing must never break client construction or the import
# smoke — any failure leaves the plain Bedrock seam in place.
try:
    import tracing

    client.messages.create = tracing.wrap_create(client.messages.create, _trace_metadata)
except Exception:  # pragma: no cover - defensive: tracing is strictly additive
    log.debug("langsmith tracing wrap skipped")
