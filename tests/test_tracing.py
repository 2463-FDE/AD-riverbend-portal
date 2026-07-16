"""
Unit tests for the ai-assistant LangSmith tracing wrapper (tracing.py).

The load-bearing guarantees, all of which these tests exercise WITHOUT real
langsmith (a fake is injected through the single ``tracing._langsmith`` seam):

  * OFF BY DEFAULT — with LANGSMITH_TRACING unset/false, wrap_create returns
    the original callable unchanged (identity passthrough).
  * PHI-SILENT — the request messages/system and the completion text NEVER
    appear in what would be sent to LangSmith; only scalar metadata is
    attached. This is the adversarial end-to-end scan the negative-test rule
    (CLAUDE.md §5) requires for anything on a PHI egress path.
  * FAIL-OPEN — a tracing-machinery failure after a successful completion is
    swallowed and the real response returned; a genuine provider error from
    the wrapped call propagates unchanged; the wrapped call runs exactly once.

tracing.py imports only the standard library at module load (langsmith is
imported lazily inside _langsmith), so it loads directly with no sys.modules
dance.
"""
import functools
from types import SimpleNamespace

import pytest

from conftest import load_module

tracing = load_module("services/ai-assistant/tracing.py", "ai_tracing")


# --- PHI fixtures ----------------------------------------------------------
# Distinctive tokens planted in every field a trace could conceivably capture:
# the user message, the system prompt, and the completion text. If any survives
# into the simulated outbound payload the scan below fails.
PHI_NAME = "Jane Q. Patient"
PHI_DOB = "1983-07-04"
PHI_SSN = "123-45-6789"
PHI_MRN = "MRN-00042"
PHI_COMPLETION = "Diagnosis for Jane Q. Patient: continue metformin 500mg"
PHI_STRINGS = [PHI_NAME, PHI_DOB, PHI_SSN, PHI_MRN, PHI_COMPLETION]


def _phi_kwargs():
    """The kwargs the wrapper receives — every one carries PHI."""
    return {
        "model": "us.anthropic.claude-sonnet-4-6",
        "max_tokens": 256,
        "messages": [
            {"role": "user", "content": f"Patient {PHI_NAME} dob {PHI_DOB} ssn {PHI_SSN}"}
        ],
        "system": f"You are assisting with {PHI_NAME} ({PHI_MRN}).",
        "extra_body": {"note": f"{PHI_SSN}"},
    }


def _phi_response():
    """An adapted Bedrock response whose completion text carries PHI, plus the
    scalar usage/id/model the metadata builder reads."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=PHI_COMPLETION)],
        usage=SimpleNamespace(input_tokens=120, output_tokens=64),
        id="req_abc_123",
        model="anthropic.claude-sonnet-4-6",
    )


def _scalar_metadata(response, _kwargs):
    """Stand-in for llm_client._trace_metadata: scalar, non-PHI fields only."""
    return {
        "model": response.model,
        "request_id": response.id,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "estimated_cost_usd": 0.00132,
    }


# --- fake langsmith --------------------------------------------------------
class _FakeRunTree:
    def __init__(self):
        self.metadata = {}


class _FakeClient:
    """Records the hide callables it was built with — the code-layer PHI guard.
    A real langsmith Client applies these before a run leaves the process."""

    def __init__(self, hide_inputs=None, hide_outputs=None, **_ignored):
        self.hide_inputs = hide_inputs
        self.hide_outputs = hide_outputs


class _FakeLangSmith:
    """Simulates just the langsmith surface tracing.py touches, and records the
    payload a run WOULD carry off-box so a test can scan it for PHI.

    The fake ``traceable`` mirrors real langsmith ordering: it captures the
    call inputs, runs the wrapped fn (which sets run metadata), captures the
    outputs, then applies the Client's hide callables to inputs/outputs — the
    exact transform that decides what egresses. ``sent`` holds the result."""

    def __init__(self, fail_on_emit=False):
        self.fail_on_emit = fail_on_emit
        self.run = _FakeRunTree()
        self.client = None
        self.sent = []

    def Client(self, **kwargs):
        self.client = _FakeClient(**kwargs)
        return self.client

    def get_current_run_tree(self):
        return self.run

    def traceable(self, **_config):
        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(**kwargs):
                self.run.metadata = {}
                result = fn(**kwargs)  # runs create_fn + sets run.metadata
                hide_in = self.client.hide_inputs if self.client else None
                hide_out = self.client.hide_outputs if self.client else None
                self.sent.append(
                    {
                        "inputs": hide_in(kwargs) if hide_in else kwargs,
                        "outputs": hide_out(result) if hide_out else result,
                        "metadata": dict(self.run.metadata),
                    }
                )
                if self.fail_on_emit:
                    raise RuntimeError("simulated LangSmith submission failure")
                return result
            return wrapper
        return decorator


def _use_fake(monkeypatch, fake):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setattr(tracing, "_langsmith", lambda: fake)


# --- off by default --------------------------------------------------------
def test_disabled_returns_identity_passthrough(monkeypatch):
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)

    def create(**kwargs):
        return "R"

    assert tracing.wrap_create(create, _scalar_metadata) is create


@pytest.mark.parametrize("value", ["false", "", "0", "TrueX", "no"])
def test_non_true_values_keep_tracing_off(monkeypatch, value):
    monkeypatch.setenv("LANGSMITH_TRACING", value)

    def create(**kwargs):
        return "R"

    assert tracing.wrap_create(create) is create


def test_true_is_case_and_whitespace_tolerant(monkeypatch):
    fake = _FakeLangSmith()
    monkeypatch.setattr(tracing, "_langsmith", lambda: fake)
    monkeypatch.setenv("LANGSMITH_TRACING", "  TRUE  ")

    def create(**kwargs):
        return _phi_response()

    wrapped = tracing.wrap_create(create, _scalar_metadata)
    assert wrapped is not create  # tracing engaged


def test_langsmith_unavailable_is_passthrough(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setattr(tracing, "_langsmith", lambda: None)

    def create(**kwargs):
        return "R"

    assert tracing.wrap_create(create, _scalar_metadata) is create


# --- PHI silence (adversarial end-to-end scan) -----------------------------
def test_no_phi_in_outbound_trace_any_field(monkeypatch):
    # Plants PHI in every request field AND the completion text, drives the
    # traced path, and asserts NONE of it survives into the simulated outbound
    # run (inputs, outputs, or metadata). This is the scan the `consents` leak
    # (PR #2) taught us to write for anything on a PHI egress path.
    fake = _FakeLangSmith()
    _use_fake(monkeypatch, fake)

    def create(**kwargs):
        return _phi_response()

    wrapped = tracing.wrap_create(create, _scalar_metadata)
    wrapped(**_phi_kwargs())

    assert len(fake.sent) == 1
    payload = fake.sent[0]
    # Both payloads dropped wholesale by the hide callables.
    assert payload["inputs"] == {}
    assert payload["outputs"] == {}
    # Nothing PHI-bearing anywhere in the run, including metadata.
    blob = repr(payload)
    for phi in PHI_STRINGS:
        assert phi not in blob, f"PHI leaked into trace: {phi!r}"
    # Metadata is the expected scalar-only set.
    assert payload["metadata"] == {
        "model": "anthropic.claude-sonnet-4-6",
        "request_id": "req_abc_123",
        "input_tokens": 120,
        "output_tokens": 64,
        "estimated_cost_usd": 0.00132,
    }


def test_blank_drops_payload_regardless_of_shape():
    # The hide callable must never inspect its argument — PHI in a dict, a
    # nested list, a bare string, or None all reduce to {}.
    for payload in (
        {"messages": [{"content": PHI_SSN}], "system": PHI_NAME},
        [PHI_SSN, {"dob": PHI_DOB}],
        PHI_COMPLETION,
        None,
    ):
        assert tracing._blank(payload) == {}


def test_result_is_unchanged_when_tracing_enabled(monkeypatch):
    fake = _FakeLangSmith()
    _use_fake(monkeypatch, fake)
    response = _phi_response()

    def create(**kwargs):
        return response

    wrapped = tracing.wrap_create(create, _scalar_metadata)
    assert wrapped(**_phi_kwargs()) is response  # exact object, untouched


# --- fail-open -------------------------------------------------------------
def test_trace_emission_failure_is_swallowed(monkeypatch):
    # A LangSmith submission failure AFTER a successful completion must not
    # surface: the real response is still returned, unchanged (ADR 0006 dec 3).
    fake = _FakeLangSmith(fail_on_emit=True)
    _use_fake(monkeypatch, fake)
    response = _phi_response()

    def create(**kwargs):
        return response

    wrapped = tracing.wrap_create(create, _scalar_metadata)
    assert wrapped(**_phi_kwargs()) is response


def test_metadata_attach_failure_is_swallowed(monkeypatch):
    # If building/attaching metadata raises, the completion is still returned.
    fake = _FakeLangSmith()
    _use_fake(monkeypatch, fake)
    response = _phi_response()

    def boom_metadata(_resp, _kw):
        raise ValueError("metadata build failed")

    def create(**kwargs):
        return response

    wrapped = tracing.wrap_create(create, boom_metadata)
    assert wrapped(**_phi_kwargs()) is response


def test_provider_error_propagates_unchanged(monkeypatch):
    # When create_fn itself fails, no response was produced — the error must
    # propagate (so llm_client._call maps it to a typed error), never be masked
    # as a trace failure.
    fake = _FakeLangSmith()
    _use_fake(monkeypatch, fake)

    class Boom(Exception):
        pass

    def create(**kwargs):
        raise Boom("bedrock exploded")

    wrapped = tracing.wrap_create(create, _scalar_metadata)
    with pytest.raises(Boom):
        wrapped(**_phi_kwargs())


def test_create_fn_invoked_exactly_once(monkeypatch):
    # A trace failure must never cause a second (billable, PHI-bearing) egress.
    fake = _FakeLangSmith(fail_on_emit=True)
    _use_fake(monkeypatch, fake)
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return _phi_response()

    wrapped = tracing.wrap_create(create, _scalar_metadata)
    wrapped(**_phi_kwargs())
    assert len(calls) == 1
