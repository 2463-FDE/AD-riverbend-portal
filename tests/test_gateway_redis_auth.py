"""The gateway refuses an unauthenticated Redis (Codex PR #14 round 1, D3b).

The compose topology no longer publishes 6379 and starts the store with
`--requirepass`, but topology is not the whole boundary: a deploy that is not
ours, a stale REDIS_URL, or a copied template can still point this service at
an open instance. Redis holds session tokens — which never expire (D10) — and,
since ADR 0011, visit memory: a payer member id plus a coverage verdict. So the
client refuses to connect without a credential rather than silently downgrade.

These are adversarial by construction (CLAUDE.md §5): the credential is planted
where the guard does not expect it (inside the URL), given values that LOOK set
but are not (placeholders, whitespace, case variants), and the refusal itself is
checked for the failure it must not cause — a cached half-built client.
"""
import logging
import pathlib
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from conftest import load_module

security = load_module("services/gateway/security.py", "gateway_redis_auth")

# Deliberately low-entropy and self-describing: CI's gitleaks job scans the
# TRACKED tree (`--no-git --exit-code 1`), and a realistic 32-hex fixture trips
# its generic-api-key rule and blocks the pipeline. Any non-empty value outside
# _PLACEHOLDER_REDIS_PASSWORDS exercises the same branches.
REAL_PASSWORD = "unit-test-redis-credential"


@pytest.fixture(autouse=True)
def clean_client(monkeypatch):
    """Reset the module singleton and capture what the client is built with."""
    monkeypatch.setattr(security, "_redis_client", None)
    monkeypatch.setattr(security, "_redis_probe_client", None)
    monkeypatch.setattr(security.settings, "redis_url", "redis://redis:6379/0")
    monkeypatch.setattr(security.settings, "redis_password", "")
    calls = []

    def _fake_from_url(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return f"client:{len(calls)}"

    monkeypatch.setattr(security.redis_lib, "from_url", _fake_from_url)
    return calls


def test_no_credential_anywhere_refuses_to_connect(clean_client):
    with pytest.raises(security.RedisUnauthenticated):
        security._redis()
    assert clean_client == [], "no client may be built against an open store"


@pytest.mark.parametrize(
    "password",
    ["changeme", "CHANGEME", "Change-Me", "placeholder", "password", "redis", "secret", "todo", "xxx"],
)
def test_placeholder_passwords_count_as_absent(clean_client, monkeypatch, password):
    # The value a hurried operator (or a copied template) leaves behind must not
    # satisfy a bare presence check — the PR #5 round-5 lesson, applied to the
    # credential rather than to the bearer token.
    monkeypatch.setattr(security.settings, "redis_password", password)

    with pytest.raises(security.RedisUnauthenticated):
        security._redis()
    assert clean_client == []


@pytest.mark.parametrize("password", ["   ", "\t", "\n", " changeme "])
def test_whitespace_only_or_padded_placeholders_are_refused(
    clean_client, monkeypatch, password
):
    monkeypatch.setattr(security.settings, "redis_password", password)

    with pytest.raises(security.RedisUnauthenticated):
        security._redis()
    assert clean_client == []


def test_a_placeholder_hidden_in_the_url_is_still_refused(clean_client, monkeypatch):
    # The credential planted where the guard does not read it from by default.
    monkeypatch.setattr(security.settings, "redis_url", "redis://:changeme@redis:6379/0")

    with pytest.raises(security.RedisUnauthenticated):
        security._redis()
    assert clean_client == []


def test_a_real_password_is_passed_to_the_client(clean_client, monkeypatch):
    monkeypatch.setattr(security.settings, "redis_password", REAL_PASSWORD)

    client = security._redis()

    assert client == "client:1"
    assert clean_client == [
        {
            "url": "redis://redis:6379/0",
            "decode_responses": True,
            "password": REAL_PASSWORD,
        }
    ]


def test_a_credential_embedded_in_the_url_is_accepted(clean_client, monkeypatch):
    # An operator may legitimately deploy with the credential in the URL; the
    # guard is about "is there one", not about which knob carries it.
    monkeypatch.setattr(
        security.settings, "redis_url", f"redis://:{REAL_PASSWORD}@redis:6379/0"
    )

    security._redis()

    assert clean_client[0]["password"] == REAL_PASSWORD


def test_refusal_leaves_no_cached_client_behind(clean_client, monkeypatch):
    # A refusal must not poison the singleton: fixing the config and retrying
    # has to connect, or one bad boot would wedge the process until a restart.
    with pytest.raises(security.RedisUnauthenticated):
        security._redis()

    monkeypatch.setattr(security.settings, "redis_password", REAL_PASSWORD)
    assert security._redis() == "client:1"
    assert clean_client[0]["password"] == REAL_PASSWORD


def test_the_client_is_built_once_and_reused(clean_client, monkeypatch):
    monkeypatch.setattr(security.settings, "redis_password", REAL_PASSWORD)

    assert security._redis() is security._redis()
    assert len(clean_client) == 1


def test_session_writes_cannot_reach_an_unauthenticated_store(clean_client):
    # The guard is only worth anything if the callers inherit it. create_session
    # is the first thing a login does, so a misconfigured deploy fails there
    # rather than quietly issuing tokens into an open store.
    with pytest.raises(security.RedisUnauthenticated):
        security.create_session("frontdesk", "staff")
    assert clean_client == []


def test_visit_memory_writes_cannot_reach_an_unauthenticated_store(clean_client):
    # visit_memory_save swallows write FAULTS by design (a lost turn beats a
    # failed request the clerk already got value from), but a configuration
    # refusal is not a fault — swallowed, it would let a misconfigured gateway
    # serve on with PHI-adjacent state silently unsaved. It propagates, and no
    # client is built against the open store.
    with pytest.raises(security.RedisUnauthenticated):
        security.visit_memory_save(
            visit_id="11111111111111111111111111111111",
            owner="frontdesk",
            facts={"insurance_id": "AETN1224"},
            turns=[],
            ttl_seconds=1800,
            max_turns=12,
        )

    assert clean_client == []


# --- the refusal must reach the caller, not a swallow (review round 2) --------
# Seven helpers wrap _redis() in a bare `except Exception` so a Redis BLIP does
# not become an outage — two of them (the single-flight locks) deliberately fail
# OPEN and hand back a token. A configuration refusal is a different animal: if
# it is swallowed, a gateway pointed at an unauthenticated store keeps serving,
# spends Bedrock budget, and loses mutual exclusion, with nothing logged. Today
# no unauthenticated route reaches these, but that is dependency ordering, not a
# guarantee — so assert the property directly, over the whole class of helpers.
_BEST_EFFORT_CALLS = [
    ("ai_cache_get", lambda s: s.ai_cache_get("k")),
    ("ai_cache_set", lambda s: s.ai_cache_set("k", {"a": 1}, 300)),
    ("ai_singleflight_acquire", lambda s: s.ai_singleflight_acquire("k", 75)),
    ("ai_singleflight_release", lambda s: s.ai_singleflight_release("k", "token")),
    ("visit_memory_get", lambda s: s.visit_memory_get("v" * 32, "frontdesk")),
    (
        "visit_memory_save",
        lambda s: s.visit_memory_save(
            visit_id="v" * 32,
            owner="frontdesk",
            facts={},
            turns=[],
            ttl_seconds=1800,
            max_turns=12,
        ),
    ),
    ("visit_lock_acquire", lambda s: s.visit_lock_acquire("v" * 32, 75)),
    ("visit_lock_release", lambda s: s.visit_lock_release("v" * 32, "token")),
]


@pytest.mark.parametrize("name,call", _BEST_EFFORT_CALLS, ids=[n for n, _ in _BEST_EFFORT_CALLS])
def test_best_effort_helpers_re_raise_the_config_refusal(clean_client, name, call):
    with pytest.raises(security.RedisUnauthenticated):
        call(security)
    assert clean_client == []


def test_every_redis_swallow_site_re_raises_the_refusal():
    # The quantifier, not the anecdote: a helper added later with a bare
    # `except Exception` around a Redis call would fail closed on a blip and
    # OPEN on a misconfiguration. Every catch-all in the module must sit behind
    # a RedisUnauthenticated re-raise in the same try block.
    source = (
        pathlib.Path(__file__).resolve().parent.parent / "services/gateway/security.py"
    ).read_text().splitlines()

    unguarded = []
    for i, line in enumerate(source):
        if not line.strip().startswith("except Exception"):
            continue
        start = max(j for j in range(i) if source[j].strip() == "try:")
        block = source[start:i]
        if not any(l.strip() == "except RedisUnauthenticated:" for l in block):
            unguarded.append(i + 1)

    assert not unguarded, (
        f"security.py lines {unguarded}: a bare `except Exception` around a Redis "
        "call must re-raise RedisUnauthenticated first — a configuration refusal "
        "is not the transient fault these swallows exist for"
    )


def test_the_credential_is_passed_verbatim_not_stripped(clean_client, monkeypatch):
    # redis-server is started with the SAME env value, quoted and unstripped, so
    # stripping here would authenticate with a different string than the server
    # was configured with — and the server's own healthcheck would still be green.
    padded = f"{REAL_PASSWORD} "
    monkeypatch.setattr(security.settings, "redis_password", padded)

    security._redis()

    assert clean_client[0]["password"] == padded


# --- the refusal is visible at the edge (review round 2) ----------------------
# Fail-closed is only useful if the operator can SEE it. Before this, a gateway
# that refused the store answered 500 with a traceback while /healthz stayed
# 200 — so `docker compose ps` reported the stack healthy with the portal fully
# down, and no orchestrator would restart or drain it.
_GW_PINNED = ("config", "logging_config", "db", "models", "security")
_gw_saved = {name: sys.modules.pop(name, None) for name in _GW_PINNED}
sys.modules["config"] = load_module("services/gateway/config.py", "gw_redis_auth_config")
sys.modules["logging_config"] = load_module(
    "services/gateway/logging_config.py", "gw_redis_auth_logging_config"
)
sys.modules["db"] = load_module("services/gateway/db.py", "gw_redis_auth_db")
sys.modules["models"] = load_module("services/gateway/models.py", "gw_redis_auth_models")
gw_security = sys.modules["security"] = load_module(
    "services/gateway/security.py", "gw_redis_auth_security"
)
gw = load_module("services/gateway/app.py", "gw_redis_auth_app")
for _name, _module in _gw_saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

gw_client = TestClient(gw.app, raise_server_exceptions=False)


@pytest.fixture()
def refusing_gateway(monkeypatch):
    """Point the app's own security module at an unauthenticated store."""
    monkeypatch.setattr(gw_security.settings, "redis_password", "")
    monkeypatch.setattr(gw_security.settings, "redis_url", "redis://redis:6379/0")
    monkeypatch.setattr(gw_security, "_redis_client", None)
    monkeypatch.setattr(gw_security, "_redis_probe_client", None)


def test_healthz_goes_red_when_the_store_is_refused(refusing_gateway):
    r = gw_client.get("/healthz")

    assert r.status_code == 503, (
        "a gateway that cannot use its session store must report unhealthy, or "
        "the container health status hides a fully-down portal"
    )
    assert "REDIS_PASSWORD" not in r.text, "the refusal detail belongs in the log"


def test_an_authenticated_route_answers_503_not_500(refusing_gateway):
    # require_session -> get_session -> _redis() raises. Unhandled that was a
    # 500 + traceback; the DB-down sibling path already answers 503.
    r = gw_client.get("/me", headers={"Authorization": "Bearer anything"})

    assert r.status_code == 503
    assert r.json() == {"detail": "auth backend unavailable"}


def test_login_answers_503_not_500_when_the_store_is_refused(refusing_gateway):
    # Reaches create_session (so the DB-down 503 cannot be what we are seeing —
    # the commit is asserted): the store refusal must answer with the same
    # dependency-outage shape rather than a 500 with a traceback.
    committed = []

    class _FakeResult:
        def scalar_one_or_none(self):
            return SimpleNamespace(
                username="frontdesk",
                role="staff",
                full_name="Front Desk",
                is_active=True,
                password_hash=gw_security.hash_password("portal123"),
                last_login_at=None,
            )

    class _FakeDb:
        def execute(self, *a, **k):
            return _FakeResult()

        def commit(self):
            committed.append(True)

    gw.app.dependency_overrides[gw.get_db] = lambda: _FakeDb()
    try:
        r = gw_client.post(
            "/login", json={"username": "frontdesk", "password": "portal123"}
        )
    finally:
        gw.app.dependency_overrides.pop(gw.get_db, None)

    assert committed, "the test must get past the DB, or it proves the DB-down path"
    assert r.status_code == 503
    assert r.json() == {"detail": "auth backend unavailable"}
    assert "traceback" not in r.text.lower()


# --- the probe must PROVE the store answers (review round 2) -------------------
# Round 1's check built the client and sent no command, so it caught only the
# failure it was written for. A credential Redis rejects, a store that died after
# boot, or a stale connection all left /healthz at 200 with every session-backed
# route failing — the same green-dashboard-dead-service shape the check exists to
# prevent, one layer in. These tests therefore assert on the COMMAND, not just
# the status code, and cover both "not configured" and "configured but refused".


class _FakeProbe:
    def __init__(self, exc=None):
        self.exc = exc            # settable: a store can recover mid-test
        self.pings = 0

    def ping(self):
        self.pings += 1
        if self.exc is not None:
            raise self.exc
        return True


@pytest.fixture()
def clock(monkeypatch):
    """Drive the probe memo's clock, so a "burst" and a "poll" are distinguishable."""
    holder = {"now": 0.0}
    monkeypatch.setattr(gw_security.time, "monotonic", lambda: holder["now"])
    return SimpleNamespace(set=lambda t: holder.update(now=t))


@pytest.fixture()
def probing_gateway(monkeypatch):
    """A properly-credentialed gateway whose probe client is under our control."""
    monkeypatch.setattr(gw_security.settings, "redis_password", REAL_PASSWORD)
    monkeypatch.setattr(gw_security.settings, "redis_url", "redis://redis:6379/0")
    monkeypatch.setattr(gw_security, "_redis_client", None)
    monkeypatch.setattr(gw_security, "_redis_probe_client", None)
    monkeypatch.setattr(gw_security, "_probe_verdict", None)
    built = []

    def _install(exc=None):
        probe = _FakeProbe(exc)

        def _fake_from_url(url, **kwargs):
            built.append(kwargs)
            return probe

        monkeypatch.setattr(gw_security.redis_lib, "from_url", _fake_from_url)
        return probe

    return SimpleNamespace(install=_install, built=built)


def _logged(caplog):
    return "\n".join(record.getMessage() for record in caplog.records)


def test_healthz_is_green_only_after_the_store_answers(probing_gateway):
    probe = probing_gateway.install()

    r = gw_client.get("/healthz")

    assert r.status_code == 200
    assert probe.pings == 1, (
        "a health check that issues no command cannot tell a usable store from an "
        "unreachable one — that was the round-1 gap"
    )


def test_healthz_goes_red_when_the_store_does_not_answer(probing_gateway):
    probing_gateway.install(ConnectionError("connection refused"))

    r = gw_client.get("/healthz")

    assert r.status_code == 503
    assert r.json() == {"detail": "session store unavailable"}


def test_healthz_goes_red_when_the_credential_is_rejected(probing_gateway, caplog):
    # The failure the config-only probe structurally could not see: the value is
    # present and not a placeholder, and the server rejects it (the gateway's
    # REDIS_PASSWORD drifting from the server's --requirepass). Redis answers
    # this at command time, so only a command finds it.
    rejected = gw_security.redis_lib.exceptions.AuthenticationError(
        f"WRONGPASS invalid username-password pair, sent {REAL_PASSWORD}"
    )
    probing_gateway.install(rejected)

    with caplog.at_level(logging.ERROR):
        r = gw_client.get("/healthz")

    assert r.status_code == 503
    assert r.json() == {"detail": "session store unavailable"}
    # The LOG is the half that matters here: the body is a fixed literal, so
    # asserting on it cannot catch a regression to raising str(exc) — the
    # server's message is free to quote what was sent, and this one does.
    logged = _logged(caplog)
    assert "AuthenticationError WRONGPASS" in logged, "the operator needs the cause"
    assert REAL_PASSWORD not in logged, "but never the credential"
    assert "username-password pair" not in logged, "nor the rest of the message"


def test_an_open_store_is_distinguishable_from_a_down_one(probing_gateway, caplog):
    # A store started WITHOUT --requirepass answers AUTH with a plain
    # ResponseError. Reported as just the class name it reads as "Redis is
    # down", and the runbook sends the operator to check whether Redis is up —
    # while the actual finding is that sessions and visit memory are on an open
    # store. Redis error codes are a closed vocabulary, so the code is kept.
    open_store = gw_security.redis_lib.exceptions.ResponseError(
        "ERR Client sent AUTH, but no password is set"
    )
    probing_gateway.install(open_store)

    with caplog.at_level(logging.ERROR):
        r = gw_client.get("/healthz")

    assert r.status_code == 503
    logged = _logged(caplog)
    assert "ResponseError ERR" in logged
    assert "no password is set" not in logged, "the code, not the message"


@pytest.mark.parametrize(
    "message",
    [
        f"{REAL_PASSWORD} was rejected",          # the credential in first position
        "Custom-Error the credential was X",      # a token that is not a Redis code
        "wrongpass lower case is not a code",
        f"{REAL_PASSWORD.upper()} SHOUTED",       # uppercase, still not a code
    ],
)
def test_only_known_redis_error_codes_reach_the_log(probing_gateway, caplog, message):
    # The quantifier behind the two tests above. A shape test ("first token, if it
    # looks like a code") would admit any of these; the catalog admits none. The
    # first case is the one that matters: a server whose error text begins with
    # the value we sent.
    probing_gateway.install(gw_security.redis_lib.exceptions.ResponseError(message))

    with caplog.at_level(logging.ERROR):
        gw_client.get("/healthz")

    logged = _logged(caplog)
    assert "ResponseError" in logged
    assert logged.strip().endswith("ResponseError"), (
        f"nothing from {message!r} may be appended — it carries no known error code"
    )


def test_the_probe_client_carries_the_configured_timeouts(probing_gateway, monkeypatch):
    # A distinct value, not the default: the connect and read bounds are two
    # knobs fed from one setting, so asserting the default would pass even if one
    # of them were never wired up.
    monkeypatch.setattr(gw_security.settings, "redis_probe_timeout_seconds", 0.37)
    probing_gateway.install()

    gw_client.get("/healthz")

    kwargs = probing_gateway.built[0]
    assert kwargs["socket_timeout"] == 0.37
    assert kwargs["socket_connect_timeout"] == 0.37


def test_the_probe_client_bounds_its_pool_and_skips_the_setinfo_handshake(probing_gateway):
    # Both are cost bounds on a public, session-less endpoint: one connection per
    # in-flight request against a slow store, and two extra blocking round trips
    # per connect (redis-py registers its own lib name/version by default) that
    # the probe's budget arithmetic cannot afford.
    probing_gateway.install()

    gw_client.get("/healthz")

    kwargs = probing_gateway.built[0]
    assert kwargs["max_connections"] == 1
    assert kwargs["lib_name"] is None and kwargs["lib_version"] is None


def test_the_probe_client_is_built_once_across_polls(probing_gateway, clock):
    probe = probing_gateway.install()

    for tick in (0.0, 10.0, 20.0):   # the healthcheck's own interval
        clock.set(tick)
        gw_client.get("/healthz")

    assert len(probing_gateway.built) == 1, "a 10s poll must not open a pool per call"
    assert probe.pings == 3, "but every poll must still send a command"


# --- the verdict memo: collapse a burst, never soften the signal ---------------
# /healthz takes no session and is published on the host port, and it now does
# Redis I/O on a sync (threadpool) handler. Without a memo, N concurrent callers
# hold N threadpool workers for the full probe budget each — with a slow store
# that queues every other sync route, including /login. The memo must therefore
# cover the FAILURE case too, and must expire well inside the poll interval or it
# turns a recovered store into a stale red (and a dead one into a stale green).


def test_a_burst_of_polls_collapses_to_one_command(probing_gateway, clock):
    probe = probing_gateway.install()
    clock.set(0.0)

    for _ in range(5):
        assert gw_client.get("/healthz").status_code == 200

    assert probe.pings == 1


def test_a_burst_against_a_failing_store_also_collapses(probing_gateway, clock):
    probe = probing_gateway.install(ConnectionError("connection refused"))
    clock.set(0.0)

    for _ in range(5):
        assert gw_client.get("/healthz").status_code == 503

    assert probe.pings == 1, (
        "the slow/failing store is exactly the case a burst must not repeat — "
        "memoizing only successes leaves the expensive path unbounded"
    )


def test_the_memo_expires_before_the_next_poll(probing_gateway, clock):
    probe = probing_gateway.install()
    clock.set(0.0)
    gw_client.get("/healthz")

    clock.set(gw_security._PROBE_MEMO_SECONDS)

    gw_client.get("/healthz")
    assert probe.pings == 2


def test_a_recovered_store_is_seen_on_the_next_poll(probing_gateway, clock):
    probe = probing_gateway.install(ConnectionError("connection refused"))
    clock.set(0.0)
    assert gw_client.get("/healthz").status_code == 503

    probe.exc = None
    clock.set(gw_security._PROBE_MEMO_SECONDS)

    assert gw_client.get("/healthz").status_code == 200, (
        "a memo that outlives the outage is the stale-green failure this PR closed"
    )


def test_a_config_refusal_is_not_stored_in_the_memo(probing_gateway, clock, monkeypatch):
    # The refusal itself does no I/O, so there is nothing to amortise: it is
    # re-evaluated on every miss and never written to the memo. (A memoized
    # SUCCESS does suppress it for the window — harmless, because the credential
    # cannot change inside a running process; it comes from the environment.)
    probe = probing_gateway.install()
    clock.set(0.0)
    assert gw_client.get("/healthz").status_code == 200

    monkeypatch.setattr(gw_security.settings, "redis_password", "")
    monkeypatch.setattr(gw_security, "_redis_probe_client", None)
    clock.set(gw_security._PROBE_MEMO_SECONDS)

    for _ in range(3):
        assert gw_client.get("/healthz").json() == {"detail": "session store not configured"}
    assert probe.pings == 1, "no command is needed to refuse an unconfigured store"


def test_a_refused_credential_leaves_no_cached_probe_behind(monkeypatch):
    # Same property the session client has: a half-built client cached during a
    # refusal would answer later polls without ever having authenticated.
    monkeypatch.setattr(gw_security.settings, "redis_password", "")
    monkeypatch.setattr(gw_security, "_redis_probe_client", None)

    with pytest.raises(gw_security.RedisUnauthenticated):
        gw_security.check_redis_usable()

    assert gw_security._redis_probe_client is None


@pytest.mark.parametrize(
    "configured,expected",
    [("0.5", 0.5), ("0", 0.1), ("-5", 0.1), ("0.01", 0.1), ("99", 0.7)],
)
def test_the_probe_timeout_is_clamped_to_a_usable_band(monkeypatch, configured, expected):
    # Both ends of the band are reachable by hand and both defeat the probe: 0
    # means "wait forever" to redis-py (the hang this bound exists to prevent),
    # and too large means docker kills the healthcheck request before the endpoint
    # answers, so neither the 503 nor the log line that names the cause appears.
    # The ceiling is NOT the healthcheck timeout: the value bounds each socket
    # operation separately and a cold connect makes several before PING —
    # tests/test_compose_topology.py asserts that arithmetic.
    monkeypatch.setenv("REDIS_PROBE_TIMEOUT_SECONDS", configured)

    fresh = load_module("services/gateway/config.py", f"gw_probe_clamp_{configured}")

    assert fresh.settings.redis_probe_timeout_seconds == expected


def test_the_session_client_is_not_given_the_probe_timeouts(clean_client, monkeypatch):
    # The probe needs to give up fast; the auth path must keep the blocking
    # behaviour it shipped with (CLAUDE.md §6 — session reads are not a place to
    # change failure timing as a side effect of a health check).
    monkeypatch.setattr(security.settings, "redis_password", REAL_PASSWORD)

    security._redis()

    assert clean_client[0].keys() == {"url", "decode_responses", "password"}
