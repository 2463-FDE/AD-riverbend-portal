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


def consume_ai_global_budget(per_day: int) -> int:
    """Aggregate daily ceiling over *paid* AI fan-outs (ADR 0007).

    A single global day-window counter, incremented once per paid call
    (callers invoke this only on a cache MISS, just before fan-out). Returns a
    Retry-After hint in seconds if the aggregate cap is now exceeded, else 0.
    ``per_day <= 0`` disables the ceiling (returns 0 without touching Redis).
    Per-user caps bound one user; this bounds total spend across all users
    (N * per-user is otherwise unbounded in N). Callers must fail closed if
    this raises — do not spend when the ceiling cannot be verified.
    """
    if per_day <= 0:
        return 0
    now = int(time.time())
    count = _incr_fixed_window(f"ratelimit:ai:global:{now // 86400}", 86400)
    if count > per_day:
        return 86400 - (now % 86400)
    return 0


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
