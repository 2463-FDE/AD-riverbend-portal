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


# --- every domain service is network-internal (ADR 0016, debt-log D15) --------
# Codex PR #26 r3/r4: GET /schedule answered a clinic day of appointments —
# patient names + MRNs — on host port 8074 with no login. Not that route's bug:
# no domain service has any auth dependency (each carries Depends(get_db) and
# nothing else), so every published 807x port was an unauthenticated PHI
# read/write path that skips the gateway, the only place a session is checked.
# records-service served full charts and the unscoped /records/search;
# roi-service fulfills disclosures; interop-service ACCEPTS PHI via
# POST /hl7/ingest. Same class ai-assistant (PR #7 r3) and Redis (PR #14 r1)
# already left, now applied to the whole tier. The r4 ask for a direct-access
# rejection test is satisfied structurally here: no `ports` key means the
# container port has no host mapping to answer on.

DOMAIN_SERVICES = {
    "intake-service": "8071",
    "eligibility-service": "8072",
    "records-service": "8073",
    "scheduling-service": "8074",
    "interop-service": "8075",
    "roi-service": "8076",
}

# The full sanctioned host surface. postgres stays published for local psql
# access (ADR 0016 §6 — password-authenticated, unlike the domain services);
# the gateway is the auth boundary; the two portals are the UIs.
HOST_PUBLISHABLE = {"postgres", "gateway", "frontend", "portal"}


def test_no_domain_service_publishes_a_host_port():
    for name in DOMAIN_SERVICES:
        assert "ports" not in _service(name), (
            f"{name} must not publish a host port: domain services have no auth "
            "of their own — the gateway session check is the only auth boundary, "
            "so a host mapping is an unauthenticated PHI path that skips it "
            "(ADR 0016, docs/debt-log.md D15)"
        )


def test_host_publishing_is_a_closed_allowlist():
    # The class guard, not just the six current instances: a NEW service added
    # with a host port fails here until it is deliberately added to the
    # allowlist — publishing must be a decision, never a default.
    for name, svc in _all_services().items():
        if name not in HOST_PUBLISHABLE:
            assert "ports" not in svc, (
                f"{name} publishes a host port but is not in HOST_PUBLISHABLE. "
                "If host access is genuinely required, say why in an ADR and add "
                "it here in the same change (ADR 0016)"
            )


def test_every_domain_service_stays_reachable_where_the_gateway_expects_it():
    # The flip side of unpublishing (same shape as the ai-assistant check
    # above): the gateway still needs each service on the compose network at
    # the port its *_URL points to.
    gateway_env = _service("gateway")["environment"]
    for name, port in DOMAIN_SERVICES.items():
        assert port in [str(p) for p in _service(name).get("expose", [])], (
            f"{name} must expose {port} — it is the port the gateway's URL "
            "points at"
        )
        expected = f"http://{name}:{port}"
        assert expected in gateway_env.values(), (
            f"no gateway *_URL points at {expected} — the unpublish only works "
            "if the gateway path stays intact"
        )


def test_every_internal_url_in_compose_targets_a_port_that_service_exposes():
    # Beyond the gateway: intake and ai-assistant carry their own
    # ELIGIBILITY_URL. Any http://<service>:<port> env value anywhere in the
    # compose file must agree with that service's declared port, or a future
    # port move strands a caller silently.
    services = _all_services()
    for name, svc in services.items():
        raw = svc.get("environment") or {}
        values = raw if isinstance(raw, list) else raw.values()
        for value in values:
            m = re.fullmatch(r"(?:\w+=)?http://([\w-]+):(\d+)", str(value))
            if not m or m.group(1) not in services:
                continue
            target, port = m.group(1), m.group(2)
            declared = [str(p) for p in services[target].get("expose", [])]
            declared += [str(p).split(":")[-1] for p in services[target].get("ports", [])]
            assert port in declared, (
                f"{name} points at http://{target}:{port} but {target} declares "
                f"{declared or 'no port'} — the URL and the topology have drifted"
            )


# --- docs/tooling must not point at the removed host ports (r1) ---------------
# ADR 0016's pre-landing sweep grepped one literal spelling and missed
# docs/runbook.md twice, because both references were parameterized (an
# `807N` placeholder, and a `for p in 8071 ...` loop curling `$p`). A doc or
# tool that hits a removed port reads a healthy stack as six dead services, and
# the fix an operator reaches for is exactly the local republish the unpublish
# exists to prevent (Codex PR #27 r1). So this guards the CLASS, not the two
# instances: every loopback spelling (localhost, 127.0.0.1, 0.0.0.0, [::1]),
# the literal ports (8077/ai-assistant included — unpublished since PR #7),
# bracket globs, the N placeholder, and any `$var` port
# interpolation — over the operator docs AND the tracked executable surfaces
# (eval/, tests/) the original sweep claimed. The `$var` arm deliberately
# over-blocks parameterized PUBLISHED ports too; hardcode those in docs.
# Excluded: adr/ (quotes the removed commands as history) and this file.

DOC_SURFACES = ["Makefile", "README.md", "ARCHITECTURE.md", "CLAUDE.md"]
_HOST_PORT_REF = re.compile(
    r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]):(?:807[1-7N\[]|\$)"
)


def test_no_operator_doc_or_tool_hits_a_domain_service_host_port():
    root = COMPOSE.parent
    files = [root / p for p in DOC_SURFACES]
    files += sorted((root / "docs").rglob("*.md"))
    files += sorted((root / "eval").rglob("*.py")) + sorted((root / "tests").rglob("*.py"))
    own = Path(__file__).resolve()
    for f in files:
        if f.resolve() == own:
            continue
        for i, line in enumerate(f.read_text().splitlines(), 1):
            assert not _HOST_PORT_REF.search(line), (
                f"{f.relative_to(root)}:{i} points at a domain-service host "
                f"port, or interpolates a host port from a variable "
                f"({line.strip()!r}) — domain-service ports are unpublished "
                "(ADR 0016); probe via `make ps` or the exec valve in "
                "docs/runbook.md, and hardcode published ports in docs"
            )


# --- the SvelteKit portal's place in the topology (ADR 0012, 0015) ------------
# Two frontends run side by side until FE-R1-FE-R3 pass on the new one
# (FE-R15), which is a coexistence window with two failure modes worth holding
# structurally: the legacy portal quietly stops being built/served, or the new
# one arrives without the health surface its fail-closed startup guard needs
# (ADR 0014's Consequences — a guard with no health signal shows a green
# dashboard over a dead service).


def _published_host_ports(svc):
    return {str(p).split(":")[0] for p in svc.get("ports", [])}


def test_both_portals_stay_separately_runnable():
    frontend, portal = _service("frontend"), _service("portal")
    assert "3070" in _published_host_ports(frontend), (
        "the legacy Next.js portal must keep its own published port for the "
        "FE-R15 coexistence window — it is replaced by deletion, not by being "
        "quietly unplugged"
    )
    assert "3071" in _published_host_ports(portal)
    assert frontend["build"] != portal["build"], (
        "the two portals must build from their own directories: a SvelteKit app "
        "cannot be a route group inside the Next.js one (ADR 0012 §1)"
    )


def test_portal_has_a_health_surface():
    # ADR 0014 requires GET /healthz to report a missing/unusable cookie key,
    # and ADR 0015 the same for a missing ORIGIN. Neither guard is worth
    # anything if nothing polls it, so the healthcheck lands with the service
    # rather than with the guard.
    svc = _service("portal")
    probe = " ".join(svc["healthcheck"]["test"])
    assert "/healthz" in probe, (
        "portal needs a compose healthcheck on /healthz so a fail-closed "
        "startup shows as unhealthy in `make ps` instead of as up"
    )


def test_portal_origin_is_runtime_config_with_no_production_default():
    # FE-R31 / ADR 0015 §3: the origin is resolved from the environment, and the
    # only default anywhere is the local stack's. A hostname baked in here would
    # be the same scar as a build-time GATEWAY_URL, one variable over.
    origin = _service("portal")["environment"]["ORIGIN"]
    assert origin.startswith("${ORIGIN"), (
        "portal's ORIGIN must interpolate from the environment, not be pinned "
        "to a literal — a deployment sets it, the image does not carry it"
    )
    assert "localhost" in origin, "the only in-repo default may be the local stack's"
    for candidate in (origin, (COMPOSE.parent / ".env.example").read_text()):
        assert "riverbend.example.com" not in candidate, (
            "no production hostname belongs in a tracked default: an unset ORIGIN "
            "must fail visibly rather than resolve to a plausible-looking guess"
        )


def test_ci_starts_the_portal_image_and_polls_the_port_compose_publishes():
    # FE-R32. `docker compose build` is not evidence that anything runs, and the
    # portal is where those come apart: adapter-node bundles its runtime into
    # build/, so the runtime stage's `npm ci --omit=dev` leaves a near-empty
    # dependency tree and a working image is indistinguishable from a broken one
    # at build time. Two review rounds read that shape as a startup crash. Only a
    # started container answering the health surface separates the cases.
    #
    # The port and the path are read out of compose rather than written here, so
    # republishing the portal on another port, or moving the health surface,
    # fails this test instead of leaving CI curling an address nothing serves.
    ci = (COMPOSE.parent / ".github/workflows/ci.yml").read_text()
    assert "docker compose up -d --no-deps portal" in ci, (
        "the docker gate must START the portal image, not only build it; "
        "--no-deps keeps the gateway's Postgres/Redis chain out of an image job"
    )
    probe = " ".join(_service("portal")["healthcheck"]["test"])
    path = re.search(r"(/[\w\-/]*healthz)", probe).group(1)
    for host_port in _published_host_ports(_service("portal")):
        assert f"http://localhost:{host_port}{path}" in ci, (
            f"CI must poll http://localhost:{host_port}{path} — the port compose "
            f"publishes and the path its healthcheck probes, not a hardcoded pair "
            f"that can drift from either"
        )
