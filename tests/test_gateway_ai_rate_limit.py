"""Tests for the gateway's per-user quota on the paid /ai fan-out (Codex PR #7
round 6).

The finding: /ai/intake-instructions accepted any authenticated session and
forwarded every POST straight to the paid Bedrock path with no rate limit, so a
leaked/stale token (sessions never expire) or a bored user could loop it and
drive unbounded spend. These tests prove that calls past the per-user cap are
rejected (429) BEFORE the fan-out (httpx.post) runs, that the daily cap bounds
aggregate volume, and that a Redis fault fails closed (503, no fan-out) rather
than disabling the guard.

No live Redis: security._redis_client is replaced with an in-memory fake and the
clock is pinned so window buckets are deterministic. require_session is
dependency-overridden so no session I/O is needed.
"""
import sys

import pytest
from fastapi.testclient import TestClient

from conftest import load_module

_PINNED = ("config", "logging_config", "db", "models", "security")
_saved = {name: sys.modules.pop(name, None) for name in _PINNED}
sys.modules["config"] = load_module("services/gateway/config.py", "gw_rl_config")
sys.modules["logging_config"] = load_module(
    "services/gateway/logging_config.py", "gw_rl_logging_config"
)
sys.modules["db"] = load_module("services/gateway/db.py", "gw_rl_db")
sys.modules["models"] = load_module("services/gateway/models.py", "gw_rl_models")
security = load_module("services/gateway/security.py", "gw_rl_security")
sys.modules["security"] = security
gw = load_module("services/gateway/app.py", "gw_rl_app")
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

gw.app.dependency_overrides[gw.require_session] = lambda: {
    "username": "frontdesk",
    "role": "staff",
}
client = TestClient(gw.app, raise_server_exceptions=False)


class _FakeRedis:
    """Minimal INCR/EXPIRE + GET/SET — enough for the limiter and the cache."""

    def __init__(self):
        self.counts = {}
        self.store = {}

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, seconds):
        return True

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value
        return True


@pytest.fixture(autouse=True)
def _fixed_redis_and_clock(monkeypatch):
    # Real per-user counting against an in-memory Redis, pinned clock so every
    # request in a test lands in the same minute/day window bucket. Default the
    # other two controls OUT of the way so per-user tests stay isolated: cache
    # off (every request is a paid fan-out) and aggregate ceiling wide open.
    # The dedicated global-cap / cache tests opt back in.
    monkeypatch.setattr(security, "_redis_client", _FakeRedis())
    monkeypatch.setattr(security.time, "time", lambda: 1_000_000.0)
    monkeypatch.setattr(gw.settings, "ai_cache_ttl_seconds", 0)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 1_000_000)


@pytest.fixture
def fan_out_calls(monkeypatch):
    """Record every downstream fan-out; the paid path == this being called."""
    calls = []

    class _Resp:
        status_code = 200

        def json(self):
            return {"items": ["Bring a photo ID."], "disclaimer": "d"}

    def _fake_post(url, json=None, timeout=None, headers=None):
        calls.append(url)
        return _Resp()

    monkeypatch.setattr(gw.httpx, "post", _fake_post)
    return calls


def test_calls_past_per_minute_limit_are_rejected_before_fan_out(monkeypatch, fan_out_calls):
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_minute", 3)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_day", 1000)

    statuses = [
        client.post("/ai/intake-instructions", json={"has_insurance": True}).status_code
        for _ in range(6)
    ]

    assert statuses == [200, 200, 200, 429, 429, 429]
    # The paid fan-out ran ONLY for the three allowed calls; rejected requests
    # were stopped in the gateway before reaching complete_structured.
    assert len(fan_out_calls) == 3


def test_rejected_call_carries_retry_after_hint(monkeypatch, fan_out_calls):
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_minute", 1)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_day", 1000)

    assert client.post("/ai/intake-instructions", json={}).status_code == 200
    r = client.post("/ai/intake-instructions", json={})
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0


def test_daily_cap_rejects_before_fan_out(monkeypatch, fan_out_calls):
    # Minute window wide open — the daily cap is the binding wall.
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_minute", 1000)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_day", 2)

    statuses = [
        client.post("/ai/intake-instructions", json={}).status_code for _ in range(4)
    ]

    assert statuses == [200, 200, 429, 429]
    assert len(fan_out_calls) == 2


def test_quota_is_per_user_not_global(monkeypatch, fan_out_calls):
    # A second user's calls must not be throttled by the first user's spend —
    # the counter is keyed by the authenticated username.
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_minute", 1)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_day", 1000)

    gw.app.dependency_overrides[gw.require_session] = lambda: {"username": "alice", "role": "staff"}
    assert client.post("/ai/intake-instructions", json={}).status_code == 200
    assert client.post("/ai/intake-instructions", json={}).status_code == 429

    gw.app.dependency_overrides[gw.require_session] = lambda: {"username": "bob", "role": "staff"}
    # bob has his own budget despite alice being over hers.
    assert client.post("/ai/intake-instructions", json={}).status_code == 200

    gw.app.dependency_overrides[gw.require_session] = lambda: {
        "username": "frontdesk",
        "role": "staff",
    }


def test_redis_fault_fails_closed_without_fan_out(monkeypatch, fan_out_calls):
    # If the quota counter cannot be consulted, the paid path must not run.
    def _boom(*a, **k):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(gw, "check_ai_rate_limit", _boom)
    r = client.post("/ai/intake-instructions", json={"has_insurance": True})
    assert r.status_code == 503
    assert len(fan_out_calls) == 0


def test_aggregate_ceiling_bounds_total_paid_calls(monkeypatch, fan_out_calls):
    # Per-user caps do not bound total spend (N users * per-user is unbounded).
    # The aggregate daily ceiling caps paid fan-outs across ALL users. Per-user
    # limits are wide open here so the global cap is the binding wall.
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_minute", 1000)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_day", 1000)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 2)

    def _as(name):
        gw.app.dependency_overrides[gw.require_session] = lambda: {"username": name, "role": "staff"}

    # Three different users, one paid call each — the third exhausts the shared
    # ceiling even though no single user is near their own cap.
    _as("alice")
    s1 = client.post("/ai/intake-instructions", json={"has_insurance": True}).status_code
    _as("bob")
    s2 = client.post("/ai/intake-instructions", json={"has_insurance": False}).status_code
    _as("carol")
    s3 = client.post("/ai/intake-instructions", json={"policy_holder_is_self": True}).status_code

    assert [s1, s2, s3] == [200, 200, 429]
    assert len(fan_out_calls) == 2  # only the two under-ceiling calls were paid

    gw.app.dependency_overrides[gw.require_session] = lambda: {
        "username": "frontdesk",
        "role": "staff",
    }


def test_identical_body_served_from_cache_one_paid_call(monkeypatch, fan_out_calls):
    # Same closed-vocabulary body -> same checklist: only the first call fans
    # out, the rest are served from cache (retry/double-click collapse).
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_minute", 1000)
    monkeypatch.setattr(gw.settings, "ai_cache_ttl_seconds", 300)

    bodies = [
        client.post("/ai/intake-instructions", json={"has_insurance": True}).json()
        for _ in range(5)
    ]

    assert len(fan_out_calls) == 1
    # Every caller got the same real checklist body.
    assert all(b["items"] == ["Bring a photo ID."] for b in bodies)


def test_cache_hits_do_not_consume_the_spend_ceiling(monkeypatch, fan_out_calls):
    # A cache hit costs nothing, so it must not count against the aggregate
    # budget. With a ceiling of 1 and caching on, five identical requests all
    # succeed: one paid call fills the cache, the rest bypass the ceiling.
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_minute", 1000)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 1)
    monkeypatch.setattr(gw.settings, "ai_cache_ttl_seconds", 300)

    statuses = [
        client.post("/ai/intake-instructions", json={"has_insurance": True}).status_code
        for _ in range(5)
    ]

    assert statuses == [200, 200, 200, 200, 200]
    assert len(fan_out_calls) == 1


def test_global_budget_backend_error_fails_closed(monkeypatch, fan_out_calls):
    # If the aggregate ceiling cannot be verified, do not spend.
    def _boom(*a, **k):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(gw, "consume_ai_global_budget", _boom)
    r = client.post("/ai/intake-instructions", json={"has_insurance": True})
    assert r.status_code == 503
    assert len(fan_out_calls) == 0


def test_cache_key_is_hashed_not_raw_payload(monkeypatch, fan_out_calls):
    # Defensive: the request body must never appear verbatim in the Redis
    # keyspace, even though the schema is non-PHI by construction.
    monkeypatch.setattr(gw.settings, "ai_cache_ttl_seconds", 300)
    client.post("/ai/intake-instructions", json={"has_insurance": True})
    keys = list(security._redis_client.store.keys())
    assert keys, "expected a cache entry to be written"
    assert all(k.startswith("aicache:") for k in keys)
    assert all("has_insurance" not in k and "True" not in k for k in keys)


def test_anonymous_rejected_before_rate_limit(monkeypatch, fan_out_calls):
    # require_session runs first: an unauthenticated caller is 401'd before any
    # counting or fan-out happens.
    def _boom(*a, **k):
        raise AssertionError("rate limit consulted before auth")

    monkeypatch.setattr(gw, "check_ai_rate_limit", _boom)
    gw.app.dependency_overrides.pop(gw.require_session)
    try:
        r = client.post("/ai/intake-instructions", json={"has_insurance": True})
        assert r.status_code == 401
        assert len(fan_out_calls) == 0
    finally:
        gw.app.dependency_overrides[gw.require_session] = lambda: {
            "username": "frontdesk",
            "role": "staff",
        }
