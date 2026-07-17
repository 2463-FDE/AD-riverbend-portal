"""Compose-topology guard for the ai-assistant service (Codex PR #7 round 3).

The gateway session check is the ai-assistant's auth boundary, and every
request spends paid Bedrock capacity. Publishing the service on a host port
would let callers skip the gateway, so the compose file must keep it
network-internal; the X-Internal-Auth shared secret (app._require_internal_auth)
is the defense-in-depth layer BEHIND this topology, not a replacement for it.
This is a structural assertion on docker-compose.yml (parsed, not
string-scanned) so a future edit — or a copy of the neighboring services'
pre-existing host-published dev topology — cannot quietly reopen the
gateway-bypassing path.
"""
import re
from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parent.parent / "docker-compose.yml"


def _service(name):
    with COMPOSE.open() as f:
        return yaml.safe_load(f)["services"][name]


def _all_services():
    with COMPOSE.open() as f:
        return yaml.safe_load(f)["services"]


def test_ai_assistant_has_no_host_port_mapping():
    svc = _service("ai-assistant")
    assert "ports" not in svc, (
        "ai-assistant must not publish a host port: it has no auth of its own "
        "and each request spends paid LLM capacity — the gateway is the only "
        "sanctioned path (compose-network access via expose)"
    )


def test_ai_assistant_stays_reachable_inside_the_network():
    # The flip side of unpublishing: the gateway still needs the service on
    # the compose network at the port its AI_ASSISTANT_URL points to.
    svc = _service("ai-assistant")
    assert "8077" in [str(p) for p in svc.get("expose", [])]
    gateway = _service("gateway")
    assert gateway["environment"]["AI_ASSISTANT_URL"] == "http://ai-assistant:8077"


# --- shared-secret scoping (Codex PR #7 round 4) -------------------------------
# X-Internal-Auth only authenticates the gateway if the gateway is the ONLY
# service holding the secret. Loading it through the shared .env hands it to
# every container on the compose network, so any of them could call the paid
# LLM path directly. The secret therefore lives in its own env file
# (.env.ai-proxy) loaded by exactly gateway + ai-assistant, and the shared
# template must never re-grow the key.

AI_SECRET_KEY = "AI_PROXY_SHARED_SECRET"
AI_SECRET_ENV_FILE = ".env.ai-proxy"
AI_SECRET_HOLDERS = {"gateway", "ai-assistant"}


def _env_file_paths(svc):
    """Normalize compose env_file: string | list of string-or-{path: ...}."""
    raw = svc.get("env_file", [])
    if isinstance(raw, str):
        raw = [raw]
    return [entry["path"] if isinstance(entry, dict) else entry for entry in raw]


def _environment_keys(svc):
    """Normalize compose environment: mapping | list of KEY=VALUE strings."""
    raw = svc.get("environment") or {}
    if isinstance(raw, list):
        return {entry.split("=", 1)[0] for entry in raw}
    return set(raw)


def test_ai_proxy_secret_reaches_only_gateway_and_ai_assistant():
    for name, svc in _all_services().items():
        holds_file = AI_SECRET_ENV_FILE in _env_file_paths(svc)
        holds_env = AI_SECRET_KEY in _environment_keys(svc)
        if name in AI_SECRET_HOLDERS:
            assert holds_file, (
                f"{name} must load {AI_SECRET_ENV_FILE}: it is one end of the "
                "gateway->ai-assistant auth boundary"
            )
        else:
            assert not holds_file and not holds_env, (
                f"{name} must not receive {AI_SECRET_KEY}: any holder of the "
                "secret can bypass the gateway session check and spend paid "
                "LLM capacity"
            )


def test_shared_env_template_does_not_carry_ai_proxy_secret():
    # .env itself is local/untracked; the committed template is what seeds it.
    # An assignment here would put the secret back into every service via the
    # shared env_file, silently re-widening the trust boundary.
    text = (COMPOSE.parent / ".env.example").read_text()
    assert not re.search(rf"^\s*{AI_SECRET_KEY}\s*=", text, re.MULTILINE), (
        f"{AI_SECRET_KEY} must live in {AI_SECRET_ENV_FILE} (template "
        f"{AI_SECRET_ENV_FILE}.example), never in the shared .env template"
    )


def test_ai_proxy_secret_template_exists_and_ships_empty():
    # Fail-closed default deploy state: a copied template must refuse every AI
    # call (empty secret -> 503) until a real value is generated.
    text = (COMPOSE.parent / f"{AI_SECRET_ENV_FILE}.example").read_text()
    assert re.search(rf"^{AI_SECRET_KEY}=$", text, re.MULTILINE), (
        f"{AI_SECRET_ENV_FILE}.example must ship {AI_SECRET_KEY} with an "
        "empty value"
    )
