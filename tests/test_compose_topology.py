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
from urllib.parse import urlparse

import yaml

from conftest import load_module

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


# --- Redis is network-internal AND authenticated (Codex PR #14 round 1) --------
# debt-log D3b: this store holds session tokens (which never expire — D10) and,
# since ADR 0011, visit memory — a payer member id plus a coverage verdict. It
# used to be published on the Docker host with no password, so any process on
# the host could read or flush it and leave no application audit trail behind.
# These pin every part of the hardening, because losing any one of them quietly
# restores the old exposure: no host port, a required password, that password
# scoped like the AI secret, and a template that ships fail-closed.

REDIS_SECRET_KEY = "REDIS_PASSWORD"
REDIS_SECRET_ENV_FILE = ".env.redis"
REDIS_SECRET_HOLDERS = {"redis", "gateway"}


def _redis_command_text():
    raw = _service("redis").get("command")
    if isinstance(raw, str):
        return raw
    return "\n".join(str(part) for part in raw or [])


def test_redis_has_no_host_port_mapping():
    svc = _service("redis")
    assert "ports" not in svc, (
        "redis must not publish a host port: it holds session tokens and "
        "visit memory (member id + coverage verdict), and a published port is "
        "a credential-free read of both from anything on the Docker host "
        "(docs/debt-log.md D3b)"
    )


def test_redis_stays_reachable_inside_the_network():
    # The flip side of unpublishing. `expose` is documentation in Compose v2 —
    # same-network services reach each other regardless — so this pins intent
    # and the URL agreement, not reachability itself.
    svc = _service("redis")
    assert "6379" in [str(p) for p in svc.get("expose", [])]
    text = (COMPOSE.parent / ".env.example").read_text()
    assert re.search(r"^REDIS_URL=redis://redis:6379/", text, re.MULTILINE)


def test_redis_requires_a_password():
    assert "--requirepass" in _redis_command_text(), (
        "redis must start with authentication enabled"
    )


def test_redis_refuses_to_start_with_an_empty_password():
    # The guard is inside the container command, NOT a `${REDIS_PASSWORD:?}`
    # interpolation: compose resolves interpolations at PARSE time, so `:?`
    # would fail CI's `docker compose build` against the deliberately empty
    # template. An empty value must abort the container, never fall through to
    # `--requirepass ""` (which is an unauthenticated server).
    command = _redis_command_text()
    assert '$$REDIS_PASSWORD' in command
    assert '""|' in command, "the empty value must be one of the rejected cases"
    assert "exit 1" in command


def test_redis_refuses_the_same_placeholders_the_gateway_does():
    # Both ends must reject the same values. If only the gateway rejected
    # "changeme", redis would boot with it and report HEALTHY while every
    # request failed — the loud failure arriving silently. The compose guard is
    # shell, so the list cannot be imported; assert the mirror instead.
    security = load_module("services/gateway/security.py", "topology_gateway_security")
    command = _redis_command_text()
    for placeholder in sorted(security._PLACEHOLDER_REDIS_PASSWORDS):
        assert f"|{placeholder}" in command or f'"|{placeholder}' in command, (
            f"the redis container command must reject {placeholder!r} too — "
            "security._PLACEHOLDER_REDIS_PASSWORDS and the compose guard have drifted"
        )


def test_redis_healthcheck_authenticates():
    # An unauthenticated PING would report a passwordless server as healthy —
    # the check has to fail when the credential is wrong, since the gateway
    # waits on it.
    test = _service("redis")["healthcheck"]["test"]
    joined = test if isinstance(test, str) else " ".join(test)
    assert "-a" in joined and "REDIS_PASSWORD" in joined


def test_gateway_waits_for_a_healthy_redis():
    assert _service("gateway")["depends_on"]["redis"]["condition"] == "service_healthy"


def test_redis_password_reaches_only_redis_and_the_gateway():
    for name, svc in _all_services().items():
        holds_file = REDIS_SECRET_ENV_FILE in _env_file_paths(svc)
        holds_env = REDIS_SECRET_KEY in _environment_keys(svc)
        if name in REDIS_SECRET_HOLDERS:
            assert holds_file, (
                f"{name} must load {REDIS_SECRET_ENV_FILE}: it is either the "
                "store or its only client"
            )
        else:
            assert not holds_file and not holds_env, (
                f"{name} must not receive {REDIS_SECRET_KEY}: the credential "
                "for the session/visit-memory store belongs to redis and the "
                "gateway only"
            )


def test_shared_env_template_does_not_carry_the_redis_password():
    text = (COMPOSE.parent / ".env.example").read_text()
    assert not re.search(rf"^\s*{REDIS_SECRET_KEY}\s*=", text, re.MULTILINE), (
        f"{REDIS_SECRET_KEY} must live in {REDIS_SECRET_ENV_FILE} (template "
        f"{REDIS_SECRET_ENV_FILE}.example); the shared .env is handed to every "
        "service on the network"
    )


def test_shared_env_template_url_carries_no_embedded_credential():
    # A password inside REDIS_URL is the same widening by another route: the
    # URL lives in the shared .env template.
    text = (COMPOSE.parent / ".env.example").read_text()
    url = re.search(r"^REDIS_URL=(.+)$", text, re.MULTILINE).group(1).strip()
    assert urlparse(url).password is None


def test_redis_password_template_exists_and_ships_empty():
    # Fail-closed default deploy state: a copied template must refuse to start
    # the store rather than boot it unauthenticated (`make up` generates a real
    # random password instead of copying this file).
    text = (COMPOSE.parent / f"{REDIS_SECRET_ENV_FILE}.example").read_text()
    assert re.search(rf"^{REDIS_SECRET_KEY}=$", text, re.MULTILINE), (
        f"{REDIS_SECRET_ENV_FILE}.example must ship {REDIS_SECRET_KEY} empty"
    )


def test_ci_seeds_every_env_file_the_topology_requires():
    # Compose refuses to parse when a listed env_file is missing, so adding one
    # without seeding it in CI turns the image build red. Asserted over EVERY
    # service's env_file list rather than the two we happen to know about.
    ci = (COMPOSE.parent / ".github/workflows/ci.yml").read_text()
    required = {path for svc in _all_services().values() for path in _env_file_paths(svc)}
    for path in sorted(required):
        assert f"cp {path}.example {path}" in ci, (
            f"CI must seed {path} from its template before `docker compose build`"
        )


# --- the health probe's budget fits inside the healthcheck's (round 2) --------
# /healthz sends a real Redis PING, and the container healthcheck that polls it
# has its own timeout. If the probe can outlast that, docker gives up on the
# request before the endpoint gives up on Redis: the container still goes red,
# but by timeout, so neither the 503 nor the log line that says WHICH failure
# happened is ever produced — and the runbook tells the operator to tell those
# two causes apart by that log line.
#
# The comparison is NOT knob-vs-timeout. REDIS_PROBE_TIMEOUT_SECONDS bounds each
# blocking socket operation separately, and a cold connection makes several
# before PING is answered:
#
#   1. TCP connect                       (socket_connect_timeout)
#   2. AUTH — send + read                (socket_timeout)
#   3. SELECT, when REDIS_URL names a non-zero db
#   4. PING — send + read
#
# (`security._redis_probe` passes lib_name/lib_version=None, which switches off
# redis-py's two CLIENT SETINFO round trips; without that this would be 6.)
# So the ceiling of the reachable band times the op count must stay under the
# healthcheck timeout. Asserted at the CEILING, not the default, so raising the
# knob cannot quietly cross the line.
_PROBE_SOCKET_OPS = 4


def _healthcheck_timeout_seconds(service):
    raw = _service(service)["healthcheck"]["timeout"]
    return float(re.fullmatch(r"([0-9.]+)s", str(raw)).group(1))


def _healthcheck_interval_seconds(service):
    raw = _service(service)["healthcheck"]["interval"]
    return float(re.fullmatch(r"([0-9.]+)s", str(raw)).group(1))


def test_the_gateway_healthcheck_polls_the_endpoint_that_probes_redis():
    test_cmd = " ".join(str(part) for part in _service("gateway")["healthcheck"]["test"])
    assert "/healthz" in test_cmd, (
        "the Redis probe is only a health signal if the healthcheck polls it"
    )


def test_the_whole_redis_probe_stays_inside_the_healthcheck_timeout(monkeypatch):
    monkeypatch.setenv("REDIS_PROBE_TIMEOUT_SECONDS", "9999")
    ceiling = load_module(
        "services/gateway/config.py", "gw_probe_ceiling_config"
    ).settings.redis_probe_timeout_seconds
    outer = _healthcheck_timeout_seconds("gateway")

    assert _PROBE_SOCKET_OPS * ceiling < outer, (
        f"a cold probe makes up to {_PROBE_SOCKET_OPS} blocking socket calls, each "
        f"bounded separately by REDIS_PROBE_TIMEOUT_SECONDS, so its worst case is "
        f"{_PROBE_SOCKET_OPS} x {ceiling}s = {_PROBE_SOCKET_OPS * ceiling}s against a "
        f"{outer}s healthcheck timeout — inner budget < outer budget (ADR 0010 "
        "discipline). Comparing the knob alone to the timeout certifies the bad "
        "value instead of forbidding it."
    )


def test_the_probe_memo_expires_well_inside_the_poll_interval(monkeypatch):
    # The memo exists to collapse a burst against a public endpoint, not to soften
    # the signal: if it could outlive the poll interval, a recovered store would
    # keep reporting red — or worse, a dead one would keep reporting green.
    security = load_module("services/gateway/security.py", "gw_probe_memo_security")
    interval = _healthcheck_interval_seconds("gateway")

    assert security._PROBE_MEMO_SECONDS < interval / 2, (
        f"the probe memo ({security._PROBE_MEMO_SECONDS}s) must expire well inside "
        f"the healthcheck interval ({interval}s) so every poll gets a fresh verdict"
    )


# --- the member-id catalog must reach both ends from ONE place (round 7) -------
# The gateway now validates the ids a downstream 200 asks it to persist against
# the same closed payer-prefix catalog ai-assistant recognises them with. Two
# services reading one env var only stays consistent if the var reaches them from
# the SHARED .env: a per-service `environment:` entry (or a scoped env_file) would
# let an operator add a payer prefix at one end only, and the skew is silent —
# ai-assistant recognises the new id and the gateway 502s that turn.
CATALOG_KEY = "AI_MEMBER_ID_PREFIXES"
CATALOG_SERVICES = {"gateway", "ai-assistant"}


def test_the_member_id_catalog_is_never_set_per_service():
    for name, svc in _all_services().items():
        assert CATALOG_KEY not in _environment_keys(svc), (
            f"{name} must not pin {CATALOG_KEY} in its own `environment:` block: "
            "the gateway and ai-assistant have to hold the SAME catalog, so it "
            "belongs in the shared .env where one edit reaches both"
        )


def test_both_catalog_holders_read_the_shared_env_file():
    for name in CATALOG_SERVICES:
        assert ".env" in _env_file_paths(_service(name)), (
            f"{name} must load the shared .env: it is the single place "
            f"{CATALOG_KEY} can be overridden without skewing the two ends"
        )


def test_no_scoped_env_template_can_skew_the_catalog():
    # The other override vector, and the one the shared-.env check above does not
    # cover (pre-push review, round 7): compose lets a LATER env_file entry beat an
    # earlier one, and the two holders load different scoped files — gateway also
    # loads .env.redis. A catalog assignment in a scoped template therefore skews
    # one end alone, silently. The generated files come from these templates, so the
    # templates are where the assertion belongs.
    for template in COMPOSE.parent.glob(".env.*.example"):
        assert not re.search(rf"^\s*{CATALOG_KEY}\s*=", template.read_text(), re.MULTILINE), (
            f"{template.name} must not set {CATALOG_KEY}: a scoped env file reaches "
            "only some services, and both the gateway and ai-assistant have to hold "
            "the same catalog — it belongs in the shared .env template or nowhere"
        )
