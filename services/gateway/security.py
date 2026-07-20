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
# INCR the counter and, on the FIRST hit of a window, bind its TTL — as ONE
# atomic server-side step. Running INCR and EXPIRE as two round-trips (the prior
# implementation) could crash / lose Redis connectivity between them and strand a
# counter with NO expiry, which never resets at the window boundary. That is a
# permanent lockout: a per-user key wedges one user, and ratelimit:ai:global:*
# wedges the WHOLE tenant out of the paid assistant until Redis is cleared by
# hand — a blip turned into an outage (Codex PR #7 round 12). A Lua script runs
# atomically on the server, so the TTL is bound to the counter's first write with
# no interleaving window; a partial (INCR-without-EXPIRE) write is impossible.
_INCR_FIXED_WINDOW_LUA = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


def _incr_fixed_window(key: str, window_seconds: int) -> int:
    """Atomically increment a fixed-window counter and bind its TTL on first hit.

    The increment and the first-hit expiry are a single server-side Lua execution
    so the counter can never be created without an expiry — see
    ``_INCR_FIXED_WINDOW_LUA`` for why a two-call INCR-then-EXPIRE was an outage
    risk (a stranded, never-resetting quota key)."""
    return int(_redis().eval(_INCR_FIXED_WINDOW_LUA, 1, key, window_seconds))


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


# Give back one budget slot: DECR and, if the counter is now exhausted (<= 0),
# DELETE it — as ONE atomic server-side step. Running DECR and DELETE as two
# round-trips is check-then-act: a concurrent reserve can INCR the key to 1 in
# the gap after a refund's DECR read 0, and the refund's trailing DELETE then
# wipes that legitimate fresh reservation (and its TTL). A crash between the two
# calls likewise strands a no-TTL negative key. Same reasoning as
# _INCR_FIXED_WINDOW_LUA (Codex PR #7 round 12): the read and the write it
# justifies must not interleave with other clients.
_DECR_AND_CLEAR_LUA = """
local remaining = redis.call('DECR', KEYS[1])
if remaining <= 0 then
    redis.call('DEL', KEYS[1])
end
return remaining
"""


def _decr_and_clear(key: str) -> int:
    """Atomically decrement a budget counter and delete it once exhausted.

    Shared by the refund path (release_ai_global_budget) and the over-limit
    undo (consume_ai_global_budget) — the two places a reserved increment is
    given back. See ``_DECR_AND_CLEAR_LUA`` for why the decrement and the
    exhausted-key cleanup must be one server-side step."""
    return int(_redis().eval(_DECR_AND_CLEAR_LUA, 1, key))


def _global_budget_key(now: int) -> str:
    """Day-window key for the aggregate spend counter. Derived ONLY at reserve
    time (consume_ai_global_budget); a refund receives the reserved key back
    verbatim rather than re-deriving it, so the two can never disagree on the
    bucket across a day rollover (Codex PR #7 round 14)."""
    return f"ratelimit:ai:global:{now // 86400}"


def consume_ai_global_budget(per_day: int) -> tuple[int, str | None]:
    """Aggregate daily ceiling over *paid* AI fan-outs (ADR 0007).

    A single global day-window counter, incremented once per paid call
    (callers invoke this only on a cache MISS, just before fan-out). Returns
    ``(retry_after, reservation_key)``: ``retry_after`` is a Retry-After hint in
    seconds if the aggregate cap is now exceeded (else 0), and
    ``reservation_key`` is the EXACT bucket that was charged — the value a
    refund must pass back to release_ai_global_budget. It is ``None`` when
    nothing was reserved (ceiling disabled, or the attempt was rejected and its
    increment already undone here). ``per_day <= 0`` disables the ceiling
    (returns ``(0, None)`` without touching Redis). Per-user caps bound one
    user; this bounds total spend across all users (N * per-user is otherwise
    unbounded in N). Callers must fail closed if this raises — do not spend
    when the ceiling cannot be verified.

    A reservation is provisional: the counter tracks fan-outs that reach the
    paid path, so a caller whose fan-out turns out to make NO paid Bedrock call
    (a downstream config/auth/validation rejection) must give the slot back with
    release_ai_global_budget — passing the returned key, never a recomputed
    one. A fan-out reserved just before the UTC midnight rollover can refund
    after it; recomputing the bucket from refund time would credit the NEW
    day's counter, silently erasing part of that day's real paid count and
    letting the ceiling over-admit (Codex PR #7 round 14).

    An OVER-LIMIT attempt is undone immediately. The counter is incremented
    before the cap comparison (a fixed-window INCR is the atomic read), but a
    request that lands over the ceiling is rejected here BEFORE any fan-out — it
    makes no paid call — so its increment is rolled back on the spot. Without the
    rollback, rejected over-limit retries would permanently inflate the counter
    above real paid usage; the reserve-then-refund path only claws back paid-path
    401/422/503s, so it could never bring the inflated count down, and valid
    callers would stay 429'd until the day window rolls over (Codex PR #7
    round 11). The undo shares release_ai_global_budget's atomic
    decrement-and-clear (``_decr_and_clear``), so an expired-window edge cannot
    strand a lingering negative and a concurrent reservation cannot be wiped by
    the cleanup.
    """
    if per_day <= 0:
        return 0, None
    now = int(time.time())
    key = _global_budget_key(now)
    count = _incr_fixed_window(key, 86400)
    if count > per_day:
        _decr_and_clear(key)
        return 86400 - (now % 86400), None
    return 0, key


def release_ai_global_budget(reservation_key: str | None) -> None:
    """Refund one slot reserved by consume_ai_global_budget (ADR 0007).

    ``reservation_key`` is the exact bucket consume_ai_global_budget charged and
    returned — never a key recomputed from the current clock. A reservation
    taken just before the UTC midnight rollover refunds AFTER it; a recomputed
    key would land the credit on the new day's counter, quietly erasing part of
    the new day's real paid count and letting more Bedrock calls through than
    the ceiling permits (Codex PR #7 round 14). ``None`` means nothing was
    reserved (ceiling disabled or the attempt was rejected) — a no-op.

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

    Decrements the reserved bucket and clears it once it hits zero — as one
    atomic server-side step (``_decr_and_clear``): a DECR on a missing key (the
    old day's counter already expired between reserve and refund) would
    otherwise resurrect it as a lingering negative with no TTL, and a separate
    trailing DELETE could race a concurrent reservation's INCR and wipe a
    legitimate fresh charge.
    """
    if not reservation_key:
        return
    _decr_and_clear(reservation_key)


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


# Compare-and-delete: remove the lock ONLY if its stored value is still our own
# owner token. A blind DELETE lets a winner that outran the lock TTL delete a
# SECOND winner's still-valid lock (the first winner's slot expired, a second
# acquired the same key), after which a third identical request would acquire and
# make another paid fan-out — defeating the guard during the exact latency stress
# it exists for (Codex PR #7 round 13). Running the check and the delete in one
# server-side script keeps them atomic (no check-then-delete race).
_SINGLEFLIGHT_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


def ai_singleflight_acquire(cache_key: str, lock_ttl_seconds: int) -> str | None:
    """Elect a single winner to make the paid fan-out for a cache-miss key.

    Atomic ``SET NX EX`` of a UNIQUE owner token: returns that token to exactly
    one concurrent caller (the winner, which must fan out and then release the
    slot with the SAME token), and ``None`` to any other caller that finds the
    slot already held — a duplicate concurrent miss (double-click, browser retry,
    or many staff submitting the same closed-vocabulary facts at once). The token
    is what makes release owner-checked: a winner can only ever delete the lock
    it still owns (see ``_SINGLEFLIGHT_RELEASE_LUA``). The TTL bounds how long a
    crashed winner can hold the slot, so the key can never wedge permanently.

    Best-effort like the cache: a Redis fault returns a token anyway (fail OPEN
    to a paid call — the later owner-checked release simply finds no matching
    key and no-ops). The authoritative spend guard is the aggregate budget
    ceiling (``consume_ai_global_budget``, which itself fails CLOSED), so failing
    the lock closed here would only turn a Redis blip into an outage for no
    spend-safety gain — the coalescing is a spend/latency optimization, not the
    ceiling.
    """
    token = uuid.uuid4().hex
    try:
        got = _redis().set(_flight_key(cache_key), token, nx=True, ex=max(1, lock_ttl_seconds))
        return token if got else None
    except Exception:
        return token


def ai_singleflight_release(cache_key: str, token: str | None) -> None:
    """Release a single-flight slot after the winner's fan-out (best-effort).

    Owner-checked compare-and-delete (``_SINGLEFLIGHT_RELEASE_LUA``): deletes the
    lock only if it still holds ``token``, so a winner that outran the lock TTL
    cannot delete a newer winner's valid lock. ``token`` of ``None`` (a loser
    that never acquired) is a no-op. A failure is harmless — the lock's TTL
    clears it either way — so a Redis fault here must not fail the request whose
    response we already have."""
    if not token:
        return
    try:
        _redis().eval(_SINGLEFLIGHT_RELEASE_LUA, 1, _flight_key(cache_key), token)
    except Exception:
        pass
