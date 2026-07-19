"""
Password hashing/verification (PBKDF2-SHA256, django-style string) and Redis
session handling.

Two deliberate weaknesses live here, by design (this is an inherited build):
  * Sessions are stored in Redis with NO TTL — once issued, a token is valid
    forever (no automatic logoff). See auth.yaml SESSION_TIMEOUT: never.
  * There is no second factor; password only.
"""
import base64
import hashlib
import hmac
import json
import os
import time
import uuid

import redis as redis_lib

from config import settings

_ITERATIONS = 260000
_ALGORITHM = "pbkdf2_sha256"


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or os.urandom(12).hex()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS)
    return f"{_ALGORITHM}${_ITERATIONS}${salt}${base64.b64encode(dk).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, b64hash = encoded.split("$", 3)
    except ValueError:
        return False
    if algorithm != _ALGORITHM:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
    expected = base64.b64encode(dk).decode()
    return hmac.compare_digest(expected, b64hash)


_redis_client = None


def _redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_lib.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def create_session(username: str, role: str) -> str:
    token = uuid.uuid4().hex
    # NOTE: no expiry / TTL is set, so sessions never expire.
    _redis().hset(f"session:{token}", mapping={"username": username, "role": role})
    return token


def get_session(token: str) -> dict | None:
    if not token:
        return None
    data = _redis().hgetall(f"session:{token}")
    return data or None


def destroy_session(token: str) -> None:
    _redis().delete(f"session:{token}")


# --------------------------------------------------------------------------- #
# paid-endpoint rate limiting (Codex PR #7 round 6)
# --------------------------------------------------------------------------- #
def _incr_fixed_window(key: str, window_seconds: int) -> int:
    """Increment a fixed-window counter, setting its TTL on first hit."""
    r = _redis()
    count = r.incr(key)
    if count == 1:
        # First request in this window — give the key a TTL so the counter
        # self-clears when the window rolls over (no unbounded key growth).
        r.expire(key, window_seconds)
    return count


def check_ai_rate_limit(username: str, per_minute: int, per_day: int) -> int:
    """Fixed-window per-user REQUEST quota for the AI endpoint.

    Increments a minute-window and a day-window counter for ``username`` in
    Redis and returns a Retry-After hint in seconds if either cap is now
    exceeded, else 0. Keyed by the authenticated username because that is the
    abuse unit here: sessions never expire, so a leaked or stale token replays
    as the same user. The minute window absorbs double-clicks and retry storms;
    the per-user day cap bounds one user's request volume. This governs
    REQUESTS (cache hits included), not spend — the aggregate spend ceiling is
    consume_ai_global_budget, counted only on paid fan-outs. Callers must fail
    closed if this raises (a Redis fault): the paid path must not run when the
    quota cannot be consulted. (ADR 0007.)
    """
    now = int(time.time())
    minute_count = _incr_fixed_window(f"ratelimit:ai:min:{username}:{now // 60}", 60)
    day_count = _incr_fixed_window(f"ratelimit:ai:day:{username}:{now // 86400}", 86400)
    # Reject BEFORE touching the shared global budget, so a user hammering past
    # their own cap cannot inflate the aggregate counter with rejected requests
    # and starve everyone else (a DoS-amplification inversion of the guard).
    if day_count > per_day:
        return 86400 - (now % 86400)
    if minute_count > per_minute:
        return 60 - (now % 60)
    return 0


def _global_budget_key(now: int) -> str:
    """Day-window key for the aggregate spend counter. Single-sourced so
    consume and release can never disagree on the bucket."""
    return f"ratelimit:ai:global:{now // 86400}"


def consume_ai_global_budget(per_day: int) -> int:
    """Aggregate daily ceiling over *paid* AI fan-outs (ADR 0007).

    A single global day-window counter, incremented once per paid call
    (callers invoke this only on a cache MISS, just before fan-out). Returns a
    Retry-After hint in seconds if the aggregate cap is now exceeded, else 0.
    ``per_day <= 0`` disables the ceiling (returns 0 without touching Redis).
    Per-user caps bound one user; this bounds total spend across all users
    (N * per-user is otherwise unbounded in N). Callers must fail closed if
    this raises — do not spend when the ceiling cannot be verified.

    A reservation is provisional: the counter tracks fan-outs that reach the
    paid path, so a caller whose fan-out turns out to make NO paid Bedrock call
    (a downstream config/auth/validation rejection) must give the slot back with
    release_ai_global_budget.
    """
    if per_day <= 0:
        return 0
    now = int(time.time())
    count = _incr_fixed_window(_global_budget_key(now), 86400)
    if count > per_day:
        return 86400 - (now % 86400)
    return 0


def release_ai_global_budget(per_day: int) -> None:
    """Refund one slot reserved by consume_ai_global_budget (ADR 0007).

    Called when a reserved fan-out proves to have made no paid Bedrock call — a
    downstream 401/422/503 (bad service-to-service auth, request rejected at the
    boundary, or "assistant is not configured": a PRE-egress refusal before any
    Bedrock call), none of which bill inference. A provider outage/throttle is a
    POST-egress 502 and is deliberately NOT refunded, so an outage retry storm
    cannot escape the tenant ceiling that bounds vendor fan-out (Codex PR #7
    round 9; see gateway _NON_PAID_DOWNSTREAM_STATUS). Without the refund those
    non-paid failures would drive
    the shared daily counter to its cap during a misconfiguration or a retry
    storm and 429 every valid caller until the Redis window rolls over — even
    after the config is fixed (Codex PR #7 round 8).

    ``per_day <= 0`` means the ceiling is disabled and nothing was reserved
    (no-op). Decrements the same day-window counter and clears it once it hits
    zero: a DECR on a missing key (the window already rolled over between
    reserve and refund) would otherwise resurrect it as a lingering negative
    with no TTL, so a non-positive result deletes the key back to a clean state.
    """
    if per_day <= 0:
        return
    r = _redis()
    key = _global_budget_key(int(time.time()))
    remaining = r.decr(key)
    if remaining <= 0:
        r.delete(key)


# --------------------------------------------------------------------------- #
# response cache for the closed-vocabulary AI endpoint (ADR 0007)
# --------------------------------------------------------------------------- #
def ai_cache_key(payload: dict) -> str:
    """Stable, PHI-safe cache key for an intake-fact body.

    The key is a hash of the canonicalized request, never the raw values: the
    intake-instructions schema is enum/bool only (no PHI by construction), and
    hashing keeps even a hypothetical smuggled value out of the visible Redis
    keyspace. Canonical form (sorted keys, tight separators) makes equal bodies
    collide regardless of field order.
    """
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "aicache:" + hashlib.sha256(canon.encode()).hexdigest()


def ai_cache_get(key: str):
    """Best-effort cache read; returns the cached value or None (on miss OR any
    backend/parse error). Caching is an optimization, so a cache fault degrades
    to a normal paid call — never to a request failure (the spend ceiling, not
    the cache, is the authoritative guard)."""
    try:
        raw = _redis().get(key)
    except Exception:
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def ai_cache_set(key: str, value, ttl_seconds: int) -> None:
    """Best-effort cache write with a TTL. ``ttl_seconds <= 0`` disables
    caching (no-op). Backend errors are swallowed — a write failure must not
    fail the request whose response we already have."""
    if ttl_seconds <= 0:
        return
    try:
        _redis().set(key, json.dumps(value), ex=ttl_seconds)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# single-flight lock for concurrent identical cache misses (Codex PR #7 round 7)
# --------------------------------------------------------------------------- #
def _flight_key(cache_key: str) -> str:
    """Derive the in-flight lock key from a cache key.

    Identical bodies share one cache key, so they share one lock — that is what
    collapses concurrent duplicate misses. A distinct prefix keeps the lock out
    of the response-cache keyspace (and, like the cache key, it is a hash, never
    raw request values)."""
    return "aiflight:" + cache_key


def ai_singleflight_acquire(cache_key: str, lock_ttl_seconds: int) -> bool:
    """Elect a single winner to make the paid fan-out for a cache-miss key.

    Atomic ``SET NX EX``: returns True to exactly one concurrent caller (the
    winner, which must fan out and then release the slot), and False to any
    other caller that finds the slot already held — a duplicate concurrent miss
    (double-click, browser retry, or many staff submitting the same
    closed-vocabulary facts at once). The TTL bounds how long a crashed winner
    can hold the slot, so the key can never wedge permanently.

    Best-effort like the cache: a Redis fault returns True (fail OPEN to a paid
    call). The authoritative spend guard is the aggregate budget ceiling
    (``consume_ai_global_budget``, which itself fails CLOSED), so failing the
    lock closed here would only turn a Redis blip into an outage for no
    spend-safety gain — the coalescing is a spend/latency optimization, not the
    ceiling.
    """
    try:
        got = _redis().set(_flight_key(cache_key), "1", nx=True, ex=max(1, lock_ttl_seconds))
        return bool(got)
    except Exception:
        return True


def ai_singleflight_release(cache_key: str) -> None:
    """Release a single-flight slot after the winner's fan-out (best-effort).

    A failure is harmless — the lock's TTL clears it either way — so a Redis
    fault here must not fail the request whose response we already have."""
    try:
        _redis().delete(_flight_key(cache_key))
    except Exception:
        pass
