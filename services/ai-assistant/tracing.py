"""LangSmith tracing for the ai-assistant's Bedrock calls (ADR 0006).

Additive, metadata-only observability wrapped around the single Bedrock
provider seam (``_BedrockMessages.create`` in ``llm_client``). It preserves
every guarantee ADR 0004 / 0009 make — PHI-silence above all:

* **Off by default.** With ``LANGSMITH_TRACING`` unset (CI, local, and any
  deploy that has not opted in) :func:`wrap_create` returns the underlying
  callable unchanged: no ``langsmith`` import, no network dependency, no
  behavior change. langsmith is imported only inside :func:`_langsmith`, which
  runs only when tracing is enabled, so the keyless CI import smoke never loads
  it.

* **Fail-closed for PHI, in two independent layers.** Prompt and completion
  payloads are NEVER sent to LangSmith:

  1. *code layer* — the LangSmith ``Client`` is built with
     ``hide_inputs`` / ``hide_outputs`` callables (:func:`_blank`) that discard
     their argument and return ``{}`` unconditionally;
  2. *config layer* — the service also ships ``LANGSMITH_HIDE_INPUTS=true`` /
     ``LANGSMITH_HIDE_OUTPUTS=true`` (``.env.example``), so a regression that
     drops the callables still blanks payloads, and vice-versa.

  Neither layer depends on the other — the single-config-value trust that let a
  placeholder bearer token through (PR #5 round 5) cannot recur here. Only
  scalar run metadata (model, token counts, estimated cost, request id;
  latency is timed by LangSmith itself) is attached — exactly the fields the
  wrapper already logs, and no more.

* **Fail-open for availability.** Tracing is telemetry, never on the critical
  path. Any failure setting up OR emitting a trace is swallowed and the real
  result is returned unchanged; a LangSmith outage or a missing API key must
  never block or slow a completion, and must never map to ``LLMUnavailable``.
  This is the one sanctioned place the repo's "swallow the error" pattern is
  correct, precisely because the thing swallowed is telemetry, not the result
  (ADR 0006 decision 3).
"""
import functools
import os
from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional

# Run attributes on the LangSmith trace. ``run_type="llm"`` groups these as
# model calls in the UI; the name is stable so traces are filterable.
_RUN_NAME = "bedrock.invoke_model"
_RUN_TYPE = "llm"


def _tracing_enabled() -> bool:
    """True only when ``LANGSMITH_TRACING`` is explicitly ``true`` (whitespace
    and case tolerant). Any other value — unset, empty, ``false`` — keeps
    tracing off, so the default deploy state emits nothing."""
    return (os.environ.get("LANGSMITH_TRACING") or "").strip().lower() == "true"


def _langsmith() -> Optional[SimpleNamespace]:
    """Return the langsmith symbols this module uses, or ``None`` if langsmith
    is not importable.

    Isolated behind one function so (a) the import is lazy — never at module
    load, so the keyless CI import smoke never pulls in langsmith — and (b)
    tests can inject a fake by monkeypatching this function. A missing/broken
    package degrades to a no-op passthrough rather than breaking the client."""
    try:
        from langsmith import Client, traceable
        try:
            from langsmith import get_current_run_tree
        except ImportError:  # older layout
            from langsmith.run_helpers import get_current_run_tree
    except Exception:
        return None
    return SimpleNamespace(
        Client=Client,
        traceable=traceable,
        get_current_run_tree=get_current_run_tree,
    )


def _blank(_data: Any = None) -> Dict[str, Any]:
    """A ``hide_inputs`` / ``hide_outputs`` callable that drops the payload
    unconditionally.

    Adversarial-proof by construction: it never inspects its argument, so PHI
    in any field, nesting, or type is discarded the same way. The completion
    text and the request messages/system prompt therefore never leave the
    process, regardless of the ``LANGSMITH_HIDE_*`` env vars (the second,
    independent layer)."""
    return {}


def _attach_metadata(
    ls: SimpleNamespace,
    metadata_fn: Optional[Callable[[Any, Dict[str, Any]], Dict[str, Any]]],
    response: Any,
    kwargs: Dict[str, Any],
) -> None:
    """Attach scalar run metadata to the active LangSmith run — best-effort.

    Metadata rides on the run's ``metadata`` field, which is independent of the
    ``inputs`` / ``outputs`` the ``hide_*`` layers blank, so this is how the
    non-PHI scalars (tokens, cost, model, request id) reach LangSmith while the
    payloads are dropped. Any failure is swallowed: telemetry must never affect
    the completion."""
    if metadata_fn is None:
        return
    try:
        run = ls.get_current_run_tree()
        if run is None:
            return
        metadata = metadata_fn(response, kwargs)
        if metadata:
            run.metadata.update(metadata)
    except Exception:
        pass


def wrap_create(
    create_fn: Callable[..., Any],
    metadata_fn: Optional[Callable[[Any, Dict[str, Any]], Dict[str, Any]]] = None,
) -> Callable[..., Any]:
    """Wrap a ``create(**kwargs) -> response`` callable with LangSmith tracing.

    Returns ``create_fn`` UNCHANGED when tracing is disabled or langsmith is
    unavailable — an identity passthrough with no import and no overhead. When
    enabled, returns a wrapper that traces the call metadata-only and is
    fail-open: a tracing-machinery failure after a successful completion is
    swallowed and the real response returned, while a genuine provider error
    from ``create_fn`` propagates unchanged (so ``llm_client._call`` still maps
    it to a typed error). ``create_fn`` is invoked exactly once — a trace
    failure never causes a second (PHI-bearing, billable) egress.

    ``metadata_fn(response, kwargs) -> dict`` supplies the scalar metadata to
    attach; keeping it a caller-supplied callback lets pricing/model logic stay
    in ``llm_client`` and this module stay provider-agnostic and PHI-agnostic.
    """
    if not _tracing_enabled():
        return create_fn
    ls = _langsmith()
    if ls is None:
        return create_fn
    try:
        trace_client = ls.Client(hide_inputs=_blank, hide_outputs=_blank)
        decorate = ls.traceable(run_type=_RUN_TYPE, name=_RUN_NAME, client=trace_client)
    except Exception:
        # Client / decorator construction failed — never block the real client.
        return create_fn

    @functools.wraps(create_fn)
    def _guarded(**kwargs: Any) -> Any:
        # `holder` captures the completion the instant it is produced, before
        # any telemetry runs, so the fail-open branch below can return a good
        # result even if the tracing wrapper raises afterwards.
        holder: Dict[str, Any] = {}

        def _inner(**kw: Any) -> Any:
            response = create_fn(**kw)
            holder["response"] = response
            _attach_metadata(ls, metadata_fn, response, kw)
            return response

        try:
            return decorate(_inner)(**kwargs)
        except Exception:
            # A completion was produced but the tracing machinery failed after
            # it: swallow (telemetry is not the result). No captured response
            # means `create_fn` itself failed — re-raise so the provider error
            # is mapped by the caller, never masked as a trace problem.
            if "response" in holder:
                return holder["response"]
            raise

    return _guarded
