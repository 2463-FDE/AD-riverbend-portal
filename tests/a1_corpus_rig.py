"""
Module-level pin rig for the eligibility-assistant corpus tests (eligibility-assistant-D-66).

There is no shared package (ADR 0001) and ``tests/conftest.py::load_module`` executes a
file under a *unique* module name, so two test files that each load ``policy_index.py``
would get two module objects with their own ``_INDEX`` / ``MAX_ROW_BYTES`` — while
``app.py``'s ``import policy_index`` and its dark ``import policy_tool`` resolve by *bare*
name. This module runs the house idiom (``tests/test_ai_visit_chat.py``) exactly once:
save and pop the bare names, pin ai-assistant's copies by path — all eight names that
file pins (corpus Landmines residual (e)) plus ``policy_index`` and ``policy_tool`` —
load ``app`` so its imports bind the pinned objects, restore.

Every test in ``test_a1_corpus.py`` / ``test_a1_retriever.py`` / ``test_a1_conflict.py``
opens with the identity assertions below, so an unpinned second copy reddens before any
``load``, ``lookup`` or ``TestClient``. Loading ``app`` here is keyless and offline; it
reads and sha-verifies the vendored corpus (``policy_tool`` builds its ``topic`` enum at
import through ``policy_index.load()``), which is what publishes ``_INDEX`` /
``MAX_ROW_BYTES`` before any test runs.
"""
import sys

from conftest import load_module

_PINNED = (
    "config",
    "logging_config",
    "schemas",
    "llm_client",
    "templates",
    "visit_templates",
    "breaker",
    "eligibility_client",
    "policy_index",
    "policy_tool",
)
_saved = {name: sys.modules.pop(name, None) for name in _PINNED}
sys.modules["config"] = load_module("services/ai-assistant/config.py", "a1c_config")
sys.modules["logging_config"] = load_module(
    "services/ai-assistant/logging_config.py", "a1c_logging_config"
)
sys.modules["schemas"] = load_module("services/ai-assistant/schemas.py", "a1c_schemas")
sys.modules["llm_client"] = load_module("services/ai-assistant/llm_client.py", "a1c_llm_client")
sys.modules["templates"] = load_module("services/ai-assistant/templates.py", "a1c_templates")
sys.modules["visit_templates"] = load_module(
    "services/ai-assistant/visit_templates.py", "a1c_visit_templates"
)
sys.modules["breaker"] = load_module("services/ai-assistant/breaker.py", "a1c_breaker")
sys.modules["eligibility_client"] = load_module(
    "services/ai-assistant/eligibility_client.py", "a1c_eligibility_client"
)
policy_index = sys.modules["policy_index"] = load_module(
    "services/ai-assistant/policy_index.py", "a1_policy_index"
)
policy_tool = sys.modules["policy_tool"] = load_module(
    "services/ai-assistant/policy_tool.py", "a1_policy_tool"
)
app_mod = load_module("services/ai-assistant/app.py", "a1_corpus_app")
settings = sys.modules["config"].settings
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)


def assert_pinned(*, with_app: bool = False) -> None:
    """The identity assertions every corpus test opens with (eligibility-assistant-D-66)."""
    assert policy_tool.policy_index is policy_index
    assert policy_index.settings is app_mod.settings
    if with_app:
        assert app_mod.policy_index is policy_index
        assert app_mod.policy_tool is policy_tool


__all__ = ["policy_index", "policy_tool", "app_mod", "settings", "assert_pinned"]
