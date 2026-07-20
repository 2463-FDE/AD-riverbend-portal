"""
Unit tests for the ai-assistant LLM client wrapper (llm_client.py).

The Bedrock client seam (client.messages.create) is monkeypatched at module
level (same pattern as test_eligibility_check.py monkeypatching
check_mod.requests). No network, no key. The PHI-safety tests are the
load-bearing ones: prompt text must never reach a log record or an exception
message.
"""
import json
import logging
import sys
from types import SimpleNamespace

import pytest
from botocore.exceptions import (
    ClientError,
    CredentialRetrievalError,
    EndpointConnectionError,
    NoCredentialsError,
    PartialCredentialsError,
)
from pydantic import BaseModel, Field

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


@pytest.fixture(autouse=True)
def _bearer_token_env(monkeypatch):
    # The wrapper fails closed without the Bedrock bearer key (PR #5 round 3),
    # so every test runs with a fake one in the environment. It never egresses
    # — the client seam is patched everywhere. Tests proving the fail-closed
    # behavior delete it explicitly.
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-bearer-token")


class SampleOutput(BaseModel):
    title: str
    summary: str


def _response(text='{"title": "t", "summary": "s"}', in_tok=100, out_tok=50):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
        id="req_test_123",
        model="anthropic.claude-sonnet-4-6",
    )


def _client_error(code, status_code):
    return ClientError(
        {
            "Error": {"Code": code, "Message": "boom"},
            "ResponseMetadata": {"HTTPStatusCode": status_code},
        },
        "InvokeModel",
    )


class _FakeMessages:
    # count_tokens is retained purely as an EGRESS TRIPWIRE: the client no
    # longer calls it (budget is enforced against a local estimate), so tests
    # assert count_calls stays empty to prove no payload left the boundary.
    def __init__(self, count=100, response=None, create_exc=None):
        self.count = count
        self.response = response or _response()
        self.create_exc = create_exc
        self.create_calls = []
        self.count_calls = []

    def count_tokens(self, **kwargs):
        self.count_calls.append(kwargs)
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


def test_input_token_cap_refuses_before_any_sdk_call(monkeypatch):
    # Local estimate over the token cap must reject with NO egress at all —
    # not the completion call, and not count_tokens (the tripwire).
    fake = _patch_client(monkeypatch, _FakeMessages())
    monkeypatch.setattr(llm_mod.settings, "llm_max_input_tokens", 1)
    with pytest.raises(llm_mod.LLMBudgetExceeded):
        llm_mod.complete("hello world this easily exceeds one token")
    assert fake.count_calls == []
    assert fake.create_calls == []


def test_cost_cap_refuses_before_any_sdk_call(monkeypatch):
    fake = _patch_client(monkeypatch, _FakeMessages())
    monkeypatch.setattr(llm_mod.settings, "llm_max_cost_per_request_usd", 0.001)
    with pytest.raises(llm_mod.LLMBudgetExceeded):
        llm_mod.complete("hello")
    assert fake.count_calls == []
    assert fake.create_calls == []


def test_over_budget_phi_prompt_never_egresses(monkeypatch):
    # Regression (PR #2 review): a PHI-bearing prompt UNDER the gross char cap
    # but OVER the token budget must be rejected locally — it must never reach
    # count_tokens (the pre-fix egress) or create. Fails against pre-fix code,
    # where count_tokens was called before _enforce_budget.
    fake = _patch_client(monkeypatch, _FakeMessages())
    monkeypatch.setattr(llm_mod.settings, "llm_max_input_chars", 100_000)  # char gate wide open
    monkeypatch.setattr(llm_mod.settings, "llm_max_input_tokens", 1)  # token gate closed
    with pytest.raises(llm_mod.LLMBudgetExceeded) as excinfo:
        llm_mod.complete(PHI_PROMPT)
    assert fake.count_calls == []
    assert fake.create_calls == []
    assert "Jane Doe" not in str(excinfo.value)
    assert "123-45-6789" not in str(excinfo.value)


def test_max_input_tokens_never_undercounts_bytes():
    # The bound must be >= the UTF-8 byte length of the content, which is the
    # hard ceiling on real tokens for byte-level BPE. Multibyte unicode makes
    # bytes exceed the Python character (codepoint) count — the bound must
    # follow bytes, not codepoints, or it could under-count.
    text = "🔒 patient café résumé 日本語 123456"
    messages = [{"role": "user", "content": text}]
    bound = llm_mod.max_input_tokens(messages)
    assert bound >= len(text.encode("utf-8"))
    assert bound > len(text)  # bytes > codepoints for this multibyte string


# --- adversarial: dense payloads a chars/N heuristic would under-count -------
# Each of these tokenizes DENSER than prose. The pre-fix chars/3.0 estimator
# would pass them under the token cap and egress; the byte-based upper bound
# must reject them with zero SDK calls. (These fail against the chars/3.0 code.)


def test_all_digit_over_budget_never_egresses(monkeypatch):
    fake = _patch_client(monkeypatch, _FakeMessages())
    monkeypatch.setattr(llm_mod.settings, "llm_max_input_chars", 10_000_000)  # char gate wide open
    monkeypatch.setattr(llm_mod.settings, "llm_max_input_tokens", 100)
    # 250 ASCII digits: 250 bytes > 100 cap. chars/3.0 == 84, which would pass.
    with pytest.raises(llm_mod.LLMBudgetExceeded):
        llm_mod.complete("1234567890" * 25)
    assert fake.count_calls == []
    assert fake.create_calls == []


def test_multibyte_unicode_over_budget_never_egresses(monkeypatch):
    fake = _patch_client(monkeypatch, _FakeMessages())
    monkeypatch.setattr(llm_mod.settings, "llm_max_input_chars", 10_000_000)  # char gate wide open
    monkeypatch.setattr(llm_mod.settings, "llm_max_input_tokens", 100)
    # 200 emoji: 200 codepoints but 800 UTF-8 bytes > 100 cap. A codepoint-based
    # estimate (chars/3.0 == 67) would pass and egress; the byte bound rejects.
    with pytest.raises(llm_mod.LLMBudgetExceeded):
        llm_mod.complete("🔒" * 200)
    assert fake.count_calls == []
    assert fake.create_calls == []


def test_high_entropy_over_budget_never_egresses(monkeypatch):
    fake = _patch_client(monkeypatch, _FakeMessages())
    monkeypatch.setattr(llm_mod.settings, "llm_max_input_chars", 10_000_000)  # char gate wide open
    monkeypatch.setattr(llm_mod.settings, "llm_max_input_tokens", 100)
    # 270 non-word ASCII chars: 270 bytes > 100. chars/3.0 == 90 would PASS the
    # heuristic and egress; the byte bound rejects.
    with pytest.raises(llm_mod.LLMBudgetExceeded):
        llm_mod.complete("@#$%^&*()" * 30)
    assert fake.count_calls == []
    assert fake.create_calls == []


def test_char_cap_refuses_before_any_sdk_call(monkeypatch):
    # The over-budget prompt must NOT reach count_tokens (an SDK egress) or create.
    fake = _patch_client(monkeypatch, _FakeMessages())
    monkeypatch.setattr(llm_mod.settings, "llm_max_input_chars", 50)
    with pytest.raises(llm_mod.LLMBudgetExceeded):
        llm_mod.complete("x" * 500)
    assert fake.count_calls == []
    assert fake.create_calls == []


def test_char_cap_error_carries_no_prompt(monkeypatch):
    _patch_client(monkeypatch, _FakeMessages())
    monkeypatch.setattr(llm_mod.settings, "llm_max_input_chars", 10)
    with pytest.raises(llm_mod.LLMBudgetExceeded) as excinfo:
        llm_mod.complete(PHI_PROMPT)
    assert "Jane Doe" not in str(excinfo.value)
    assert "123-45-6789" not in str(excinfo.value)


def test_within_budget_proceeds_to_create_without_count_tokens(monkeypatch):
    # A within-budget prompt reaches create — and never count_tokens, which is
    # no longer part of the flow (local estimate is the only preflight).
    fake = _patch_client(monkeypatch, _FakeMessages())
    monkeypatch.setattr(llm_mod.settings, "llm_max_input_chars", 10_000)
    llm_mod.complete("short prompt")
    assert len(fake.create_calls) == 1
    assert fake.count_calls == []


def test_estimate_cost_math():
    assert llm_mod.estimate_cost(1_000_000, 0) == pytest.approx(3.00)
    assert llm_mod.estimate_cost(0, 1_000_000) == pytest.approx(15.00)
    assert llm_mod.estimate_cost(0, 0) == 0.0


# --- fail-closed model pricing (Codex review, PR #5) -------------------------
# The cost gate must price the RESOLVED model and refuse models it cannot
# price. Pre-fix code priced every request with hard-coded Sonnet constants,
# so pointing BEDROCK_MODEL_ID at a pricier model silently hollowed out
# LLM_MAX_COST_PER_REQUEST_USD.


def test_unpriced_model_refuses_before_any_egress(monkeypatch):
    # Adversarial placement: a PHI prompt plus a model absent from the pricing
    # table. The refusal must be local (no create, no count_tokens) and the
    # error must name the model — never the prompt. Fails against pre-fix code,
    # which priced the unknown model as Sonnet and called create().
    fake = _patch_client(monkeypatch, _FakeMessages())
    monkeypatch.setattr(llm_mod.settings, "bedrock_model_id", "us.acme.frontier-9000")
    with pytest.raises(llm_mod.LLMConfigError) as excinfo:
        llm_mod.complete(PHI_PROMPT)
    assert fake.create_calls == []
    assert fake.count_calls == []
    assert "us.acme.frontier-9000" in str(excinfo.value)
    assert "Jane Doe" not in str(excinfo.value)
    assert "123-45-6789" not in str(excinfo.value)


def test_unpriced_model_with_explicit_price_override_proceeds(monkeypatch):
    fake = _patch_client(monkeypatch, _FakeMessages())
    monkeypatch.setattr(llm_mod.settings, "bedrock_model_id", "us.acme.frontier-9000")
    monkeypatch.setattr(llm_mod.settings, "llm_price_per_mtok_input", 1.00)
    monkeypatch.setattr(llm_mod.settings, "llm_price_per_mtok_output", 5.00)
    result = llm_mod.complete("short prompt")
    assert len(fake.create_calls) == 1
    # cost telemetry prices at the override (100 in / 50 out from _response)
    assert result.estimated_cost_usd == pytest.approx((100 * 1.00 + 50 * 5.00) / 1_000_000)


def test_price_override_enforces_budget_at_override_prices(monkeypatch):
    # The override is a price source, not a bypass: expensive override prices
    # must trip the cost cap locally, with no egress.
    fake = _patch_client(monkeypatch, _FakeMessages())
    monkeypatch.setattr(llm_mod.settings, "bedrock_model_id", "us.acme.frontier-9000")
    monkeypatch.setattr(llm_mod.settings, "llm_price_per_mtok_input", 10_000.0)
    monkeypatch.setattr(llm_mod.settings, "llm_price_per_mtok_output", 50_000.0)
    with pytest.raises(llm_mod.LLMBudgetExceeded):
        llm_mod.complete("hello")
    assert fake.create_calls == []
    assert fake.count_calls == []


def test_half_set_price_override_refuses(monkeypatch):
    # Both-or-neither: a half-set override pair must be a config error — not a
    # silent fall-through to the table, not a default for the missing side.
    fake = _patch_client(monkeypatch, _FakeMessages())
    monkeypatch.setattr(llm_mod.settings, "llm_price_per_mtok_input", 3.00)
    with pytest.raises(llm_mod.LLMConfigError):
        llm_mod.complete("hello")
    assert fake.create_calls == []
    assert fake.count_calls == []


def test_inference_profile_prefixes_resolve_to_priced_model(monkeypatch):
    # Every region-scoped inference profile of a priced foundation model — and
    # the bare foundation id — must resolve to the same pricing entry.
    fake = _patch_client(monkeypatch, _FakeMessages())
    for model_id in (
        "anthropic.claude-sonnet-4-6",
        "eu.anthropic.claude-sonnet-4-6",
        "apac.anthropic.claude-sonnet-4-6",
        "global.anthropic.claude-sonnet-4-6",
    ):
        monkeypatch.setattr(llm_mod.settings, "bedrock_model_id", model_id)
        llm_mod.complete("short prompt")
    assert len(fake.create_calls) == 4


# --- happy paths ----------------------------------------------------------


def test_complete_happy_path(monkeypatch):
    _patch_client(monkeypatch, _FakeMessages(response=_response(text="hello world")))
    result = llm_mod.complete("say hello")
    assert result.text == "hello world"
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.estimated_cost_usd == pytest.approx(llm_mod.estimate_cost(100, 50))
    assert result.request_id == "req_test_123"
    assert result.model == "anthropic.claude-sonnet-4-6"
    assert result.latency_seconds >= 0


def test_complete_structured_happy_path(monkeypatch):
    fake = _patch_client(monkeypatch, _FakeMessages())
    result = llm_mod.complete_structured("summarize", SampleOutput)
    assert isinstance(result.parsed, SampleOutput)
    assert result.parsed.title == "t"
    # structured request carried the json_schema output format
    extra = fake.create_calls[0]["extra_body"]
    assert extra["output_config"]["format"]["type"] == "json_schema"
    # ...and the TRANSMITTED schema equals the strict schema of the output
    # model. Guard for the silent-degradation regression: a request that keeps
    # type=json_schema but sends {} (or the wrong model's schema) would still
    # pass the type assertion above while no longer constraining the output —
    # exactly the failure the W7 grounding work must be able to rule out.
    assert extra["output_config"]["format"]["schema"] == llm_mod._strict_schema(SampleOutput)


def test_structured_schema_pins_additional_properties_false(monkeypatch):
    # Regression (found by live Bedrock verification of complete_structured):
    # the structured-output API rejects any object node without an explicit
    # additionalProperties: false ("For 'object' type, 'additionalProperties'
    # must be explicitly set to false"), and Pydantic's model_json_schema()
    # never emits it. Every object node in the schema that leaves the seam —
    # top level AND nested $defs — must carry it. Fails against pre-fix code,
    # which sent the raw Pydantic schema.
    fake = _patch_client(monkeypatch, _FakeMessages())

    class Inner(BaseModel):
        note: str

    class Outer(BaseModel):
        title: str = "t"
        summary: str = "s"
        inner: Inner = Field(default_factory=lambda: Inner(note="n"))

    llm_mod.complete_structured("summarize", Outer)
    schema = fake.create_calls[0]["extra_body"]["output_config"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    for name, defn in schema.get("$defs", {}).items():
        if defn.get("type") == "object" or "properties" in defn:
            assert defn["additionalProperties"] is False, name


def test_complete_structured_invalid_json_raises(monkeypatch):
    _patch_client(monkeypatch, _FakeMessages(response=_response(text="not json at all")))
    with pytest.raises(llm_mod.LLMResponseError):
        llm_mod.complete_structured("summarize", SampleOutput)


def test_structured_schema_counted_in_token_budget(monkeypatch):
    # Regression (Codex review): complete_structured serializes the output schema
    # into extra_body, which the API counts as input. The budget gate must count
    # it too — a large schema must be rejected LOCALLY even when the prompt alone
    # is under the cap, with no egress. Fails against pre-fix code, where the
    # schema was ignored by the gate and the request reached create().
    fake = _patch_client(monkeypatch, _FakeMessages())
    monkeypatch.setattr(llm_mod.settings, "llm_max_input_chars", 10_000_000)  # char gate wide open
    monkeypatch.setattr(llm_mod.settings, "llm_max_input_tokens", 40)  # prompt alone passes

    class BigSchema(BaseModel):
        # A long field description balloons model_json_schema() well past the
        # 40-token cap; the 9-char prompt alone is ~25 tokens and would pass.
        field_one: str = Field(description="D" * 2000)

    with pytest.raises(llm_mod.LLMBudgetExceeded):
        llm_mod.complete_structured("summarize", BigSchema)
    assert fake.create_calls == []
    assert fake.count_calls == []


def test_structured_schema_counted_in_char_cap(monkeypatch):
    # The gross-size char backstop must also count the schema, not just the prompt.
    fake = _patch_client(monkeypatch, _FakeMessages())
    monkeypatch.setattr(llm_mod.settings, "llm_max_input_tokens", 10_000_000)  # token gate wide open
    monkeypatch.setattr(llm_mod.settings, "llm_max_input_chars", 200)  # tiny prompt passes

    class BigSchema(BaseModel):
        field_one: str = Field(description="D" * 2000)

    with pytest.raises(llm_mod.LLMBudgetExceeded):
        llm_mod.complete_structured("summarize", BigSchema)
    assert fake.create_calls == []
    assert fake.count_calls == []


# --- SDK exception mapping -------------------------------------------------


def test_throttling_maps_to_unavailable(monkeypatch):
    exc = _client_error("ThrottlingException", 429)
    _patch_client(monkeypatch, _FakeMessages(create_exc=exc))
    with pytest.raises(llm_mod.LLMUnavailable):
        llm_mod.complete("hello")


def test_resource_not_found_maps_to_config_error(monkeypatch):
    exc = _client_error("ResourceNotFoundException", 404)
    _patch_client(monkeypatch, _FakeMessages(create_exc=exc))
    with pytest.raises(llm_mod.LLMConfigError):
        llm_mod.complete("hello")


def test_access_denied_maps_to_config_error(monkeypatch):
    exc = _client_error("AccessDeniedException", 403)
    _patch_client(monkeypatch, _FakeMessages(create_exc=exc))
    with pytest.raises(llm_mod.LLMConfigError):
        llm_mod.complete("hello")


def test_connection_error_maps_to_unavailable(monkeypatch):
    # Genuine transport failure stays LLMUnavailable — the credential split
    # below must not swallow it (EndpointConnectionError is also a
    # BotoCoreError subclass, but not a credential error).
    exc = EndpointConnectionError(
        endpoint_url="https://bedrock-runtime.us-east-1.amazonaws.com"
    )
    _patch_client(monkeypatch, _FakeMessages(create_exc=exc))
    with pytest.raises(llm_mod.LLMUnavailable):
        llm_mod.complete("hello")


# --- bearer key is mandatory: no ambient-credential fallback (Codex, r3) -----
# boto3's default chain would sign the call with any ambient AWS identity
# (instance role, AWS_* env vars) when the bearer key is absent — a
# successful-looking call under an account with unknown BAA posture. The
# wrapper must refuse egress instead. These tests go through the REAL
# _BedrockClient/_BedrockMessages adapter down to the invoke_model seam, so
# they prove no invoke_model call is ever attempted.


def _stub_runtime_client(monkeypatch):
    calls = []
    stub = SimpleNamespace(invoke_model=lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(llm_mod, "client", llm_mod._BedrockClient(stub))
    return calls


def test_missing_bearer_token_refuses_before_any_egress(monkeypatch):
    # Adversarial: PHI prompt + no bearer key. Refusal must be local (no
    # invoke_model) and the error must carry neither the prompt nor any token.
    calls = _stub_runtime_client(monkeypatch)
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    with pytest.raises(llm_mod.LLMConfigError) as excinfo:
        llm_mod.complete(PHI_PROMPT)
    assert calls == []
    assert "AWS_BEARER_TOKEN_BEDROCK" in str(excinfo.value)
    assert "Jane Doe" not in str(excinfo.value)
    assert "123-45-6789" not in str(excinfo.value)


def test_empty_bearer_token_refuses_before_any_egress(monkeypatch):
    # Empty string is as absent as unset — must not reach the credential chain.
    calls = _stub_runtime_client(monkeypatch)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "")
    with pytest.raises(llm_mod.LLMConfigError):
        llm_mod.complete("hello")
    assert calls == []


def test_ambient_aws_creds_do_not_substitute_for_bearer_token(monkeypatch):
    # The reviewer's exact scenario: sigv4-style AWS_* credentials present,
    # bearer key absent. boto3 WOULD sign with these; the wrapper must refuse
    # with zero invoke_model attempts instead.
    calls = _stub_runtime_client(monkeypatch)
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    # Deliberately NOT an AKIA-shaped value: invoke_model is stubbed so the
    # credential shape is irrelevant to the test, and a real-looking access-key
    # id trips the CI gitleaks secret scanner (aws-access-token) on this fixture.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "fake-access-key-id-not-real")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-secret-fake-secret")
    with pytest.raises(llm_mod.LLMConfigError):
        llm_mod.complete("hello")
    assert calls == []


def test_placeholder_bearer_token_refuses_before_any_egress(monkeypatch):
    # .env.example ships AWS_BEARER_TOKEN_BEDROCK=changeme (historically) and CI
    # copies it to .env via `cp .env.example .env`; a bare non-empty presence
    # check would accept that placeholder and egress a PHI prompt before AWS
    # rejects the auth. The guard must treat the shipped sentinel as absence
    # (Codex review, PR #5 round 5). Stub returns a well-formed body so that
    # against pre-fix code the call would succeed and reach invoke_model — this
    # asserts it never does.
    calls = _stub_runtime_returning(
        monkeypatch,
        {
            "content": [{"type": "text", "text": "hi"}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "changeme")
    with pytest.raises(llm_mod.LLMConfigError):
        llm_mod.complete(PHI_PROMPT)
    assert calls == []


def test_placeholder_bearer_variants_all_refuse(monkeypatch):
    # Lock the class, not the "changeme" instance: whitespace-only, padded, and
    # differently-cased placeholders must all be treated as unset, with no
    # invoke_model attempt.
    for value in ("   ", " changeme ", "CHANGEME", "placeholder", "your-token-here"):
        calls = _stub_runtime_returning(
            monkeypatch,
            {
                "content": [{"type": "text", "text": "hi"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )
        monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", value)
        with pytest.raises(llm_mod.LLMConfigError):
            llm_mod.complete("hello")
        assert calls == [], value


# --- credential failures are config errors, not outages (Codex, PR #5 r2) ----
# botocore raises these locally, BEFORE any request reaches AWS: a missing or
# partially-set AWS_BEARER_TOKEN_BEDROCK / fallback chain is a deployment
# break that retrying can never fix. Pre-fix code let them fall through to the
# generic BotoCoreError catch and reported them as a retryable Bedrock outage.


def test_missing_credentials_map_to_config_error(monkeypatch):
    _patch_client(monkeypatch, _FakeMessages(create_exc=NoCredentialsError()))
    with pytest.raises(llm_mod.LLMConfigError):
        llm_mod.complete("hello")


def test_partial_credentials_map_to_config_error(monkeypatch):
    exc = PartialCredentialsError(provider="env", cred_var="AWS_SECRET_ACCESS_KEY")
    _patch_client(monkeypatch, _FakeMessages(create_exc=exc))
    with pytest.raises(llm_mod.LLMConfigError):
        llm_mod.complete("hello")


def test_credential_retrieval_failure_maps_to_config_error(monkeypatch):
    exc = CredentialRetrievalError(provider="custom-process", error_msg="exit 1")
    _patch_client(monkeypatch, _FakeMessages(create_exc=exc))
    with pytest.raises(llm_mod.LLMConfigError):
        llm_mod.complete("hello")


def test_credential_error_carries_no_prompt(monkeypatch):
    # Adversarial: the new mapping is an exception-message path, so it needs
    # the same PHI-silence proof as every other one (CLAUDE.md §5).
    _patch_client(monkeypatch, _FakeMessages(create_exc=NoCredentialsError()))
    with pytest.raises(llm_mod.LLMConfigError) as excinfo:
        llm_mod.complete(PHI_PROMPT)
    assert "Jane Doe" not in str(excinfo.value)
    assert "123-45-6789" not in str(excinfo.value)


def test_malformed_response_maps_to_unavailable(monkeypatch):
    # A garbled Bedrock 200 body surfaces as json.loads -> ValueError from the
    # adapter. Unlike the anthropic SDK, boto3 does not absorb it, so _call must
    # map it to a typed error (ADR 0004 Typed-failures guarantee), not let a raw
    # JSONDecodeError escape. The message must not carry response bytes.
    exc = ValueError("Expecting value: line 1 column 1 (char 0): Jane Doe 123-45-6789")
    _patch_client(monkeypatch, _FakeMessages(create_exc=exc))
    with pytest.raises(llm_mod.LLMUnavailable) as excinfo:
        llm_mod.complete("hello")
    assert "Jane Doe" not in str(excinfo.value)
    assert "123-45-6789" not in str(excinfo.value)


# NOTE: the count_tokens SDK-exception-mapping tests were removed with the
# count_tokens preflight itself (PR #2 review round 4). Budget is now enforced
# against a local estimate before any SDK call, so count_tokens is no longer in
# the request path — the only egress that can raise is invoke_model, covered above.


# --- malformed responses fail closed (Codex review, PR #5 round 4) ----------
# A malformed or schema-drifted Bedrock 200 must never become a blank but
# "successful" completion. These drive a raw invoke_model body through the REAL
# _BedrockClient/_BedrockMessages/_adapt path (not the monkeypatched facade), so
# they exercise the adapter that defaults missing content/usage — the code the
# finding is about — and assert complete() raises instead of returning text=None
# with $0 telemetry.


def _stub_runtime_returning(monkeypatch, payload):
    calls = []
    body = SimpleNamespace(read=lambda: json.dumps(payload).encode("utf-8"))
    response = {"body": body, "ResponseMetadata": {"RequestId": "req_stub_ok"}}

    def _invoke(**kwargs):
        calls.append(kwargs)
        return response

    stub = SimpleNamespace(invoke_model=_invoke)
    monkeypatch.setattr(llm_mod, "client", llm_mod._BedrockClient(stub))
    return calls


def test_missing_content_block_raises_through_adapter(monkeypatch):
    # No content at all: _adapt yields an empty block list, so text is None.
    # complete() must reject, not return a blank success.
    _stub_runtime_returning(
        monkeypatch, {"usage": {"input_tokens": 10, "output_tokens": 5}}
    )
    with pytest.raises(llm_mod.LLMResponseError):
        llm_mod.complete("hello")


def test_non_text_content_block_raises_through_adapter(monkeypatch):
    # A single non-text block (e.g. tool_use) yields no usable text — reject.
    _stub_runtime_returning(
        monkeypatch,
        {
            "content": [{"type": "tool_use", "id": "x"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
    )
    with pytest.raises(llm_mod.LLMResponseError):
        llm_mod.complete("hello")


def test_missing_usage_raises_through_adapter(monkeypatch):
    # Valid text but no usage block: a clean-looking $0 call is a false telemetry
    # signal for a PHI vendor egress. Fail closed rather than under-report.
    _stub_runtime_returning(
        monkeypatch, {"content": [{"type": "text", "text": "hi"}]}
    )
    with pytest.raises(llm_mod.LLMResponseError):
        llm_mod.complete("hello")


def test_malformed_response_error_carries_no_prompt(monkeypatch):
    # Adversarial (CLAUDE.md §5): the new raise path is an exception-message
    # path, so it must carry neither the prompt nor any PHI.
    _stub_runtime_returning(
        monkeypatch, {"usage": {"input_tokens": 10, "output_tokens": 5}}
    )
    with pytest.raises(llm_mod.LLMResponseError) as excinfo:
        llm_mod.complete(PHI_PROMPT)
    assert "Jane Doe" not in str(excinfo.value)
    assert "123-45-6789" not in str(excinfo.value)


def test_wellformed_response_succeeds_through_adapter(monkeypatch):
    # Control: a well-formed body through the same real adapter path still
    # returns a populated result — the guard rejects only malformed responses.
    _stub_runtime_returning(
        monkeypatch,
        {
            "content": [{"type": "text", "text": "hello world"}],
            "usage": {"input_tokens": 12, "output_tokens": 7},
            "id": "req_real",
            "model": "anthropic.claude-sonnet-4-6",
        },
    )
    result = llm_mod.complete("say hello")
    assert result.text == "hello world"
    assert result.input_tokens == 12
    assert result.output_tokens == 7
    assert result.request_id == "req_real"


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
    exc = _client_error("ThrottlingException", 429)
    _patch_client(monkeypatch, _FakeMessages(create_exc=exc))
    with pytest.raises(llm_mod.LLMUnavailable) as excinfo:
        llm_mod.complete(PHI_PROMPT)
    assert "Jane Doe" not in str(excinfo.value)
    assert "123-45-6789" not in str(excinfo.value)


# --- client configuration --------------------------------------------------


def test_real_client_configured_from_settings():
    # The module-level boto3 runtime (before any monkeypatching in other tests)
    # must carry the configured region + bounded-call discipline. No network.
    cfg = llm_mod._runtime.meta.config
    assert llm_mod._runtime.meta.region_name == llm_mod.settings.aws_region
    assert cfg.connect_timeout == llm_mod.settings.llm_connect_timeout_seconds
    assert cfg.read_timeout == llm_mod.settings.llm_read_timeout_seconds
    # botocore max_attempts counts the first try, so it is retries + 1. The
    # resolved client config normalizes it to total_max_attempts on some
    # versions, so accept either key.
    retries = cfg.retries or {}
    attempts = retries.get("total_max_attempts", retries.get("max_attempts"))
    assert attempts == llm_mod.settings.llm_max_retries + 1


def test_module_client_import_works_keyless():
    # boto3 resolves the bearer key lazily, so the client constructs with no
    # AWS_BEARER_TOKEN_BEDROCK set — CI's keyless import smoke passes.
    assert llm_mod.client is not None
    assert hasattr(llm_mod.client, "messages")
