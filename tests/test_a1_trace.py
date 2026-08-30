"""
eligibility-assistant — the privacy-safe trace's structural guarantees.

Created by the `llm-seam` ticket with the never-stream check (SPEC-30); the
`trace` ticket extends this file with the rest of SPEC-27–29 / 31–32 / 39b / 40.

SPEC-30 is a ⚠ row (`docs/landmines.md` §3 negative-test rule): LangSmith's
`hide_inputs` / `hide_outputs` redaction — the two-layer hide ADR 0006 relies on
to keep trace payloads metadata-only — is bypassed on streamed payloads. So the
guarantee is enforced structurally, by a binding that CANNOT stream, and this
file pins both halves of that: no streaming API is referenced anywhere in the
service, and the binding's `_stream` raises.
"""
import os
import sys

import pytest

from conftest import load_module

SERVICE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "services",
    "ai-assistant",
)

# Same pin rig as tests/test_llm_client.py: agent_binding reaches the seam by
# the service idiom `import llm_client` (app.py:33's shape), and the bare names
# `config` / `logging_config` are ambiguous across services (ADR 0001, no shared
# package). Pin ai-assistant's copies while agent_binding loads, then restore —
# the house idiom (tests/test_ai_visit_chat.py:51-73; CLAUDE.md §6).
_saved = {
    name: sys.modules.pop(name, None)
    for name in ("config", "logging_config", "llm_client")
}
sys.modules["config"] = load_module("services/ai-assistant/config.py", "a1t_config")
sys.modules["logging_config"] = load_module(
    "services/ai-assistant/logging_config.py", "a1t_logging_config"
)
llm_mod = sys.modules["llm_client"] = load_module(
    "services/ai-assistant/llm_client.py", "a1t_llm_client"
)
agent_binding = load_module("services/ai-assistant/agent_binding.py", "a1t_agent_binding")
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


def _service_sources():
    for root, _dirs, files in os.walk(SERVICE_DIR):
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name)


def test_model_call_not_streamed():
    # SPEC-30, both halves.
    assert agent_binding.llm_client is llm_mod

    # (1) No streaming API is referenced anywhere in the service. Bedrock's
    # streaming entry point is a DIFFERENT runtime method, so its absence is
    # checkable by name rather than by behaviour.
    offenders = [
        path
        for path in _service_sources()
        if "invoke_model_with_response_stream" in open(path, encoding="utf-8").read()
    ]
    assert offenders == []

    # (2) The binding cannot stream: _stream raises rather than yielding, so a
    # caller that asks for a stream gets a failure, never an unredacted payload.
    with pytest.raises(NotImplementedError):
        list(agent_binding.SeamChatModel()._stream([]))
