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
from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parent.parent / "docker-compose.yml"


def _service(name):
    with COMPOSE.open() as f:
        return yaml.safe_load(f)["services"][name]


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
