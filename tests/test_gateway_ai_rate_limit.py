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
    """Minimal INCR/EXPIRE + GET/SET/DEL — enough for the limiter, the cache,
    and the single-flight lock (SET NX)."""

    def __init__(self):
        self.counts = {}
        self.store = {}

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def decr(self, key):
        self.counts[key] = self.counts.get(key, 0) - 1
        return self.counts[key]

    def expire(self, key, seconds):
        return True

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, nx=False, ex=None):
        # SET NX: only set if absent; return None when the key already exists so
        # the caller (single-flight acquire) sees it lost the race.
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def delete(self, key):
        # One keyspace in real Redis; the fake splits counters (INCR/DECR) from
        # values (GET/SET), so delete clears the key from both.
        self.counts.pop(key, None)
        self.store.pop(key, None)
        return 1


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


def _global_budget_keys():
    return [k for k in security._redis_client.counts if k.startswith("ratelimit:ai:global")]


def test_invalid_unknown_field_rejected_before_global_budget(monkeypatch, fan_out_calls):
    # Codex PR #7 round 7 (high): a logged-in caller sending junk bodies (here an
    # unknown field) must be rejected at the gateway BEFORE the shared spend
    # ceiling is touched — otherwise many distinct invalid bodies each miss the
    # cache, increment ratelimit:ai:global, and are only 422'd downstream, a
    # cheap tenant-wide denial of the paid assistant.
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_minute", 1000)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 5)

    r = client.post(
        "/ai/intake-instructions",
        json={"has_insurance": True, "evil_field": "SSN 123-45-6789 smuggled here"},
    )

    assert r.status_code == 422
    assert len(fan_out_calls) == 0  # never reached the paid path
    assert _global_budget_keys() == []  # the aggregate ceiling was NOT charged
    # No-echo: the rejected value (a place PHI could be smuggled) is not echoed.
    assert "123-45-6789" not in r.text


def test_contradictory_insurance_rejected_before_global_budget(monkeypatch, fan_out_calls):
    # The other invalid class the review named: a body whose insurance facts
    # contradict each other (insured + Self-pay). Same invariant — no paid call,
    # no aggregate-budget charge.
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_minute", 1000)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 5)

    r = client.post(
        "/ai/intake-instructions",
        json={"has_insurance": True, "plan_type": "Self-pay"},
    )

    assert r.status_code == 422
    assert len(fan_out_calls) == 0
    assert _global_budget_keys() == []


def test_concurrent_identical_miss_loser_returns_winner_result_no_second_paid_call(
    monkeypatch, fan_out_calls
):
    # Codex PR #7 round 7 (medium): two simultaneous identical submits must not
    # both fan out. Simulate the loser — the single-flight lock is already held
    # by an in-flight winner for this body's key — and the winner publishes its
    # result partway through the loser's wait. The loser returns that result with
    # NO second paid call and NO second budget charge.
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_minute", 1000)
    monkeypatch.setattr(gw.settings, "ai_singleflight_wait_seconds", 0.5)
    monkeypatch.setattr(gw.settings, "ai_singleflight_poll_seconds", 0.1)
    monkeypatch.setattr(gw.time, "sleep", lambda s: None)

    body = {"has_insurance": True}
    # Key off the CANONICAL facts, exactly as the handler does (round 10) — the
    # single-flight lock is derived from the normalized dump, not the raw body.
    key = security.ai_cache_key(gw._validate_ai_request(body))
    # A winner already holds the slot for this key.
    security._redis_client.set(security._flight_key(key), "1", nx=True, ex=90)

    winner_result = {"items": ["Bring a photo ID."], "disclaimer": "d"}
    seen = {"n": 0}

    def _staged_get(k):
        # Initial handler check misses; the winner's result appears mid-wait.
        seen["n"] += 1
        return winner_result if seen["n"] >= 2 else None

    monkeypatch.setattr(gw, "ai_cache_get", _staged_get)

    r = client.post("/ai/intake-instructions", json=body)

    assert r.status_code == 200
    assert r.json()["items"] == ["Bring a photo ID."]
    assert len(fan_out_calls) == 0  # the loser made no paid call
    assert _global_budget_keys() == []  # and did not consume the spend ceiling


def test_concurrent_identical_miss_loser_times_out_controlled_retry(monkeypatch, fan_out_calls):
    # If the winner does not publish within the wait budget, the loser returns a
    # controlled 429 retry rather than making its own paid call.
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_minute", 1000)
    monkeypatch.setattr(gw.settings, "ai_singleflight_wait_seconds", 0.3)
    monkeypatch.setattr(gw.settings, "ai_singleflight_poll_seconds", 0.1)
    monkeypatch.setattr(gw.time, "sleep", lambda s: None)
    monkeypatch.setattr(gw, "ai_cache_get", lambda k: None)  # winner never publishes in time

    body = {"has_insurance": True}
    # Key off the CANONICAL facts, exactly as the handler does (round 10).
    key = security.ai_cache_key(gw._validate_ai_request(body))
    security._redis_client.set(security._flight_key(key), "1", nx=True, ex=90)

    r = client.post("/ai/intake-instructions", json=body)

    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 0  # a controlled retry hint
    assert len(fan_out_calls) == 0
    assert _global_budget_keys() == []


@pytest.fixture
def downstream(monkeypatch):
    """Drive the downstream response status/body per call so a test can make the
    fan-out fail (no paid Bedrock call) or succeed. Returns the recorded modes."""
    calls = []
    state = {"status": 503, "body": {"detail": "assistant is not configured"}}

    class _Resp:
        def __init__(self, status_code, body):
            self.status_code = status_code
            self._body = body

        def json(self):
            return self._body

    def _fake_post(url, json=None, timeout=None, headers=None):
        calls.append(state["status"])
        return _Resp(state["status"], state["body"])

    monkeypatch.setattr(gw.httpx, "post", _fake_post)
    return state, calls


def test_downstream_config_503_refunds_the_global_budget(monkeypatch, downstream):
    # Codex PR #7 round 8 (high): a downstream failure that never reaches Bedrock
    # (here "assistant is not configured" → 503) must NOT keep the reserved slot
    # of the tenant-wide spend ceiling — the counter tracks paid fan-outs only.
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_minute", 1000)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 3)
    state, calls = downstream
    state["status"], state["body"] = 503, {"detail": "assistant is not configured"}

    r = client.post("/ai/intake-instructions", json={"has_insurance": True})

    assert r.status_code == 503  # the failure is still surfaced to the caller
    assert len(calls) == 1  # the fan-out was attempted...
    # ...but made no paid call, so the reservation was refunded to zero.
    assert _global_budget_keys() == [] or all(
        security._redis_client.counts.get(k, 0) == 0 for k in _global_budget_keys()
    )


def test_repeated_config_503_does_not_exhaust_budget_for_a_later_success(monkeypatch, downstream):
    # The scenario the review named: a misconfiguration produces repeated 503s
    # past the daily cap. With reserve-then-refund, none of them consume budget,
    # so once the config is fixed a real call is NOT 429'd by stale consumption.
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_minute", 1000)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 2)
    state, calls = downstream

    # Five misconfigured retries (> the cap of 2), each a non-paid 503.
    state["status"], state["body"] = 503, {"detail": "assistant is not configured"}
    for _ in range(5):
        assert client.post("/ai/intake-instructions", json={"has_insurance": True}).status_code == 503

    # Config fixed → a genuine paid call succeeds instead of hitting a stale cap.
    state["status"], state["body"] = 200, {"items": ["Bring a photo ID."], "disclaimer": "d"}
    r = client.post("/ai/intake-instructions", json={"has_insurance": True})

    assert r.status_code == 200
    assert r.json()["items"] == ["Bring a photo ID."]


def test_downstream_provider_502_keeps_the_budget_charged(monkeypatch, downstream):
    # Codex PR #7 round 9 (high): a Bedrock outage/throttle reaches the provider
    # and surfaces as a downstream 502 (ai-assistant maps LLMUnavailable -> 502).
    # Unlike the pre-egress 503 (test above), this is a PAID attempt and must NOT
    # be refunded — otherwise every outage retry gives its slot back and the
    # aggregate ceiling stops bounding vendor fan-out.
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_minute", 1000)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 3)
    state, calls = downstream
    state["status"], state["body"] = 502, {"detail": "assistant is temporarily unavailable"}

    r = client.post("/ai/intake-instructions", json={"has_insurance": True})

    assert r.status_code == 502  # the outage is surfaced to the caller
    assert len(calls) == 1  # the fan-out was attempted (provider path entered)...
    # ...and the reserved slot was KEPT (not refunded): the counter still reads 1.
    assert [security._redis_client.counts.get(k, 0) for k in _global_budget_keys()] == [1]


def test_provider_502_retry_storm_is_bounded_by_the_ceiling(monkeypatch, downstream):
    # The outage-path invariant the round-9 review asked for: with provider 502s
    # kept charged, a retry storm during a Bedrock outage cannot exceed the daily
    # ceiling — once the cap is reached the gateway 429s further attempts BEFORE
    # fan-out, so vendor fan-out stays bounded even while every call fails.
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_minute", 1000)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 2)
    state, calls = downstream
    state["status"], state["body"] = 502, {"detail": "assistant is temporarily unavailable"}

    # First two attempts reserve the two slots and fan out (each a paid attempt).
    for _ in range(2):
        assert client.post("/ai/intake-instructions", json={"has_insurance": True}).status_code == 502
    # The third is refused at the ceiling — 429, no additional fan-out.
    r = client.post("/ai/intake-instructions", json={"has_insurance": True})
    assert r.status_code == 429
    assert len(calls) == 2  # the storm did not reach Bedrock a third time


def test_requests_spelled_differently_share_one_cached_paid_call(monkeypatch, fan_out_calls):
    # Codex PR #7 round 10 (medium): the cache/single-flight key derives from the
    # NORMALIZED fact vector (model_dump), not the raw body. All three variants
    # below describe the SAME facts — an empty body (all schema defaults), the
    # defaults spelled out, and a string-coerced boolean — so they must collapse
    # to ONE paid fan-out. Keying off the raw JSON would give three distinct keys
    # and three paid Bedrock calls for one fact vector (duplicate-collapse bypass).
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_minute", 1000)
    monkeypatch.setattr(gw.settings, "ai_cache_ttl_seconds", 300)
    variants = [
        {},
        {
            "has_insurance": False,
            "plan_type": None,
            "policy_holder_is_self": True,
            "communications_opt_in": False,
            "financial_ack": False,
        },
        {"has_insurance": "false"},  # coerced to the same bool by the mirror schema
    ]

    statuses = [client.post("/ai/intake-instructions", json=v).status_code for v in variants]

    assert statuses == [200, 200, 200]
    assert len(fan_out_calls) == 1  # canonical key → first fans out, rest cache-hit


def test_downstream_local_budget_503_refunds_the_global_budget(monkeypatch, downstream):
    # Codex PR #7 round 10 (high): a local budget-cap refusal in ai-assistant is
    # PRE-egress (llm_client enforces the caps before any Bedrock call) and now
    # surfaces as 503 (was a keep-charge 500). At the gateway boundary that 503 is
    # refunded like any other pre-egress failure — same mechanism as the round-8
    # config-503 test, exercised here for the budget-misconfig path the review
    # named — so a low-cap misconfig cannot walk the shared ceiling to its cap.
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_minute", 1000)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 3)
    state, calls = downstream
    state["status"], state["body"] = 503, {"detail": "assistant is not configured"}

    r = client.post("/ai/intake-instructions", json={"has_insurance": True})

    assert r.status_code == 503
    assert len(calls) == 1  # fan-out attempted, but made no paid call...
    # ...so the reserved slot was refunded to zero.
    assert _global_budget_keys() == [] or all(
        security._redis_client.counts.get(k, 0) == 0 for k in _global_budget_keys()
    )


def test_over_limit_global_reject_does_not_consume_budget(monkeypatch, fan_out_calls):
    # Codex PR #7 round 11 (high): consume_ai_global_budget must only ever reflect
    # PAID fan-outs. A request rejected AT the ceiling makes no paid call, so it
    # must leave the counter unchanged — otherwise rejected over-limit retries
    # permanently inflate it above real usage, and the reserve-then-refund path
    # (which only claws back paid 401/422/503s) can never bring it down, 429-ing
    # valid callers until the day window rolls over.
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_minute", 1000)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 1)

    # One paid call fills the single global slot.
    assert client.post("/ai/intake-instructions", json={"has_insurance": True}).status_code == 200
    # A second, different body is rejected at the ceiling (429) before any fan-out.
    r = client.post("/ai/intake-instructions", json={"has_insurance": False})
    assert r.status_code == 429
    assert len(fan_out_calls) == 1  # only the first call was paid
    # The rejected attempt did NOT inflate the counter: it still reads exactly the
    # one real paid fan-out (pre-fix it climbed to 2).
    assert [security._redis_client.counts.get(k, 0) for k in _global_budget_keys()] == [1]


def test_over_limit_reject_then_refund_lets_a_valid_request_succeed(monkeypatch, fan_out_calls):
    # Codex PR #7 round 11 (high): the reviewer's named sequence. A synchronous
    # fake cannot truly overlap two requests, so an in-flight paid reservation is
    # modelled by pre-seeding the global counter at the cap. Then an over-limit
    # attempt is rejected (429); the in-flight call finishes with a refundable 503
    # (modelled by the refund the handler performs on 401/422/503), returning its
    # slot; and a fresh valid request must then succeed. Pre-fix, the rejected
    # attempt's stray increment survives the refund and 429s the valid caller.
    monkeypatch.setattr(gw.settings, "ai_rate_limit_per_minute", 1000)
    monkeypatch.setattr(gw.settings, "ai_rate_limit_global_per_day", 1)

    # An in-flight paid call already holds the single slot (concurrent reservation).
    security._redis_client.counts[security._global_budget_key(1_000_000)] = 1

    # (1) An over-limit attempt is rejected before any fan-out.
    r1 = client.post("/ai/intake-instructions", json={"has_insurance": True})
    assert r1.status_code == 429
    assert len(fan_out_calls) == 0

    # (2) The in-flight call finishes with a refundable downstream 503 — it made no
    # paid Bedrock call, so it returns its slot.
    gw._refund_ai_budget()

    # (3) A fresh valid request must now succeed: the refund freed the only slot,
    # and the rejected over-limit attempt must not have consumed it.
    r2 = client.post("/ai/intake-instructions", json={"has_insurance": False})
    assert r2.status_code == 200
    assert len(fan_out_calls) == 1


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
