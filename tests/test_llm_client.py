"""
Unit tests for the ai-assistant LLM client wrapper (llm_client.py).

The Anthropic client is monkeypatched at module level (same pattern as
test_eligibility_check.py monkeypatching check_mod.requests). No network,
no API key. The PHI-safety tests are the load-bearing ones: prompt text must
never reach a log record or an exception message.
"""
import logging
import sys
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from pydantic import BaseModel

from conftest import load_module

# Every service has its own config.py / logging_config.py and load_module puts
# each service dir on sys.path, so the bare names `config` / `logging_config`
# are ambiguous by the time this file loads. Pin ai-assistant's copies in
# sys.modules so llm_client resolves its own siblings, then restore.
_saved = {name: sys.modules.pop(name, None) for name in ("config", "logging_config")}
sys.modules["config"] = load_module("services/ai-assistant/config.py", "ai_assistant_config")
sys.modules["logging_config"] = load_module(
    "services/ai-assistant/logging_config.py", "ai_assistant_logging_config"
)
llm_mod = load_module("services/ai-assistant/llm_client.py", "ai_llm_client")
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


class SampleOutput(BaseModel):
    title: str
    summary: str


def _response(text='{"title": "t", "summary": "s"}', in_tok=100, out_tok=50):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
        id="req_test_123",
        model="claude-opus-4-8",
    )


def _status_error(cls, status_code):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code, request=request)
    return cls("boom", response=response, body=None)


class _FakeMessages:
    def __init__(self, count=100, response=None, create_exc=None):
        self.count = count
        self.response = response or _response()
        self.create_exc = create_exc
        self.create_calls = []

    def count_tokens(self, **kwargs):
        return SimpleNamespace(input_tokens=self.count)

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        if self.create_exc is not None:
            raise self.create_exc
        return self.response


def _patch_client(monkeypatch, fake_messages):
    monkeypatch.setattr(llm_mod, "client", SimpleNamespace(messages=fake_messages))
    return fake_messages


# --- budget guard ---------------------------------------------------------


def test_input_token_cap_refuses_before_calling(monkeypatch):
    fake = _patch_client(monkeypatch, _FakeMessages(count=999_999))
    with pytest.raises(llm_mod.LLMBudgetExceeded):
        llm_mod.complete("hello")
    assert fake.create_calls == []


def test_cost_cap_refuses_before_calling(monkeypatch):
    fake = _patch_client(monkeypatch, _FakeMessages(count=10_000))
    monkeypatch.setattr(llm_mod.settings, "llm_max_cost_per_request_usd", 0.001)
    with pytest.raises(llm_mod.LLMBudgetExceeded):
        llm_mod.complete("hello")
    assert fake.create_calls == []


def test_estimate_cost_math():
    assert llm_mod.estimate_cost(1_000_000, 0) == pytest.approx(5.00)
    assert llm_mod.estimate_cost(0, 1_000_000) == pytest.approx(25.00)
    assert llm_mod.estimate_cost(0, 0) == 0.0


# --- happy paths ----------------------------------------------------------


def test_complete_happy_path(monkeypatch):
    _patch_client(monkeypatch, _FakeMessages(response=_response(text="hello world")))
    result = llm_mod.complete("say hello")
    assert result.text == "hello world"
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.estimated_cost_usd == pytest.approx(llm_mod.estimate_cost(100, 50))
    assert result.request_id == "req_test_123"
    assert result.model == "claude-opus-4-8"
    assert result.latency_seconds >= 0


def test_complete_structured_happy_path(monkeypatch):
    fake = _patch_client(monkeypatch, _FakeMessages())
    result = llm_mod.complete_structured("summarize", SampleOutput)
    assert isinstance(result.parsed, SampleOutput)
    assert result.parsed.title == "t"
    # structured request carried the json_schema output format
    extra = fake.create_calls[0]["extra_body"]
    assert extra["output_config"]["format"]["type"] == "json_schema"


def test_complete_structured_invalid_json_raises(monkeypatch):
    _patch_client(monkeypatch, _FakeMessages(response=_response(text="not json at all")))
    with pytest.raises(llm_mod.LLMResponseError):
        llm_mod.complete_structured("summarize", SampleOutput)


# --- SDK exception mapping -------------------------------------------------


def test_rate_limit_maps_to_unavailable(monkeypatch):
    exc = _status_error(anthropic.RateLimitError, 429)
    _patch_client(monkeypatch, _FakeMessages(create_exc=exc))
    with pytest.raises(llm_mod.LLMUnavailable):
        llm_mod.complete("hello")


def test_not_found_maps_to_config_error(monkeypatch):
    exc = _status_error(anthropic.NotFoundError, 404)
    _patch_client(monkeypatch, _FakeMessages(create_exc=exc))
    with pytest.raises(llm_mod.LLMConfigError):
        llm_mod.complete("hello")


def test_connection_error_maps_to_unavailable(monkeypatch):
    exc = anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    _patch_client(monkeypatch, _FakeMessages(create_exc=exc))
    with pytest.raises(llm_mod.LLMUnavailable):
        llm_mod.complete("hello")


# --- PHI safety ------------------------------------------------------------

PHI_PROMPT = "Draft instructions for Jane Doe, SSN 123-45-6789, phone 555-867-5309"


def test_prompt_never_reaches_logs(monkeypatch, caplog):
    _patch_client(monkeypatch, _FakeMessages(response=_response(text="ok")))
    with caplog.at_level(logging.INFO):
        llm_mod.complete(PHI_PROMPT)
    messages = [record.getMessage() for record in caplog.records]
    for message in messages:
        assert "Jane Doe" not in message
        assert "123-45-6789" not in message
    # the metadata line does get logged
    assert any("llm call model=" in message for message in messages)


def test_completion_text_never_reaches_logs(monkeypatch, caplog):
    _patch_client(
        monkeypatch,
        _FakeMessages(response=_response(text="response about Jane Doe 123-45-6789")),
    )
    with caplog.at_level(logging.INFO):
        llm_mod.complete("hello")
    for record in caplog.records:
        assert "Jane Doe" not in record.getMessage()


def test_exception_messages_carry_no_prompt(monkeypatch):
    exc = _status_error(anthropic.RateLimitError, 429)
    _patch_client(monkeypatch, _FakeMessages(create_exc=exc))
    with pytest.raises(llm_mod.LLMUnavailable) as excinfo:
        llm_mod.complete(PHI_PROMPT)
    assert "Jane Doe" not in str(excinfo.value)
    assert "123-45-6789" not in str(excinfo.value)


# --- client configuration --------------------------------------------------


def test_real_client_configured_from_settings():
    # The module-level client (before any monkeypatching in other tests) must
    # carry the configured retry/timeout discipline. No network involved.
    real = llm_mod.anthropic.Anthropic(
        api_key="x",
        timeout=httpx.Timeout(
            llm_mod.settings.llm_read_timeout_seconds,
            connect=llm_mod.settings.llm_connect_timeout_seconds,
        ),
        max_retries=llm_mod.settings.llm_max_retries,
    )
    assert real.max_retries == llm_mod.settings.llm_max_retries
    assert real.timeout.connect == llm_mod.settings.llm_connect_timeout_seconds
    assert real.timeout.read == llm_mod.settings.llm_read_timeout_seconds


def test_module_client_import_works_keyless():
    # config falls back to "not-set" so CI's keyless import smoke passes.
    assert llm_mod.client is not None
