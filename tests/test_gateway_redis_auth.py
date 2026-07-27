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
