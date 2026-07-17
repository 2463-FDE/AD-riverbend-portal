# ADR 0007 — AI endpoint abuse controls: rate limiting, aggregate spend ceiling, response cache

**Status:** Accepted
**Date:** 2026-07-17
**Author:** Riverbend engagement team
**Relates to:** ADR 0003 (authentication/sessions — the "sessions never expire"
weakness this ADR mitigates in effect), ADR 0004 (ai-assistant service + PHI-safe
LLM wrapper), ADR 0005 (Bedrock provider — the paid inference path being
protected), ADR 0006 (observability). Closes the Codex PR #7 round-6 no-ship
finding: an authenticated but unthrottled paid LLM endpoint.

## Context

PR #7 added `POST /ai/intake-instructions`: the gateway authenticates the
caller, then fans out to ai-assistant, which calls paid Bedrock inference
(`llm_client.complete_structured`). The adversarial review flagged this as
no-ship:

> any valid or stale session can drive unbounded Bedrock spend and service
> saturation … no rate limit, per-user quota, idempotency key, cache, or
> concurrency guard.

The severity comes from an inherited weakness (ADR 0003): **gateway sessions
never expire** and there is a **single shared `staff` role**. So a leaked or
stale token, a bored logged-in user, or a shared front-desk login left looping
can replay the endpoint indefinitely. `require_session` proves only "is logged
in"; it is not an abuse control. The per-request cost cap already in the LLM
wrapper bounds one call, not aggregate spend or worker capacity.

Constraints that shaped the design:

- **Domain is human-paced.** Front-desk staff complete intake for one patient
  at a time. Legitimate use is a handful of calls per patient session, not
  machine throughput. Controls should gate loops/abuse, not people.
- **The gateway is the only choke point.** The portal talks only to the
  gateway; ai-assistant is not host-published and has **no Redis** of its own.
  The gateway already owns Redis (sessions) and sees the request body.
- **Closed-vocabulary request.** `InstructionsRequest` is enum/bool only (no
  free text, no PHI by construction — ADR 0004), so identical bodies map to the
  same checklist and are safe to hash and cache.
- **PHI must not leak** into logs, cache keys, or cache values.

## Decision

Three layered controls, all in the gateway (the choke point with Redis),
applied in this order on `POST /ai/intake-instructions`:

1. **Per-user request rate limit** (`security.check_ai_rate_limit`, enforced in
   the `_ai_rate_limited` dependency, before any work).
   - Fixed-window Redis counters: a **minute** window and a **per-user daily**
     window. `INCR` + `EXPIRE`-on-first-hit; keys self-clear.
   - **Keyed by the authenticated username** — the abuse unit here, because a
     leaked/stale token replays as one user (sessions never expire).
   - Over cap → **429 + `Retry-After`** (seconds to window rollover).
   - Governs **requests** (cache hits included), not spend.
   - Rejects **before** touching the shared global counter, so a user hammering
     past their own cap cannot inflate the aggregate and starve others.
   - Defaults: **10/min, 200/day** (`AI_RATE_LIMIT_PER_MINUTE/_PER_DAY`).

2. **Aggregate daily spend ceiling** (`security.consume_ai_global_budget`,
   reserved in the handler on a cache miss, before fan-out).
   - A single global day-window counter, incremented **once per paid fan-out**.
   - Bounds **total** Bedrock spend across all users — per-user caps alone are
     unbounded in user count (N × per-user).
   - Over ceiling → **429 + `Retry-After`**. `<=0` disables it.
   - Default: **2000/day** (`AI_RATE_LIMIT_GLOBAL_PER_DAY`), ≈ expected active
     staff × per-user cap.

3. **Response cache** (`security.ai_cache_*`, in the handler).
   - Key = `aicache:` + SHA-256 of the canonicalized request body. The body is
     non-PHI by schema; hashing keeps even a hypothetical smuggled value out of
     the visible keyspace. Value = the response checklist (template text, not
     PHI).
   - A **cache hit skips fan-out and does NOT consume the spend ceiling** — it
     costs nothing, so it must not count against the budget. It *does* count
     against the per-user request rate (cheap gateway self-protection).
   - **Best-effort:** any cache backend/parse error degrades to a normal paid
     call, never a request failure. Only successful responses are cached.
   - TTL bounds staleness against catalog/template deploys. Default **300s**
     (`AI_CACHE_TTL_SECONDS`); `<=0` disables.

**Fail-closed everywhere on the paid path.** If the rate-limit or global-budget
counter cannot be read (Redis fault), the request does not proceed (**503**) —
we do not spend when a guard cannot be verified. (The cache is the one
exception: it is an optimization, so its faults fail *open* to a paid call,
because the spend ceiling — not the cache — is the authoritative spend guard.)

## Alternatives considered

- **Enforce in ai-assistant instead of the gateway.** Rejected: ai-assistant
  has no Redis and is not the choke point; adding a datastore + config +
  service-to-service state there is more surface for no benefit. The gateway
  already has Redis and sees every request.
- **Sliding-window / token-bucket rate limiter.** Rejected for now (see gap 1).
  Fixed-window is ~15 lines, atomic, and precise enough for a human-paced
  endpoint. Documented as an accepted tradeoff, not an oversight.
- **Key the limit by IP, or user+IP.** Rejected as the primary key (see gap 2).
  Username is the meaningful abuse unit given non-expiring tokens; user+IP would
  *weaken* the spend bound (one token across many IPs would earn N× budget).
- **Per-request cost cap only** (already in the wrapper). Insufficient: bounds
  one call, not aggregate spend or worker saturation — exactly the review's
  point.

## How this serves the client and domain

- **Client (cost + availability):** the aggregate ceiling gives Riverbend a hard,
  tunable dollar ceiling on Bedrock per day; the cache cuts spend and latency for
  the common repeat-intake/retry case; fail-closed guarantees a Redis blip cannot
  silently uncork spend.
- **Domain fit:** limits sit far above human front-desk pace, so real staff never
  hit them; they bite only loops/abuse. `Retry-After` gives the portal a clean
  signal to back off.
- **Robustness:** fail-closed on the paid path; reject-before-global prevents a
  DoS-amplification inversion; best-effort cache cannot take the endpoint down.
- **Maintainability:** simplest correct algorithm (fixed-window), all knobs in
  env/config, all Redis-backed logic colocated in `security.py`, decisions
  captured here.
- **Scalability:** Redis `INCR` is atomic and O(1); no per-instance state, so
  gateway replicas share one view; key cardinality is bounded by staff count and
  TTL-reaped.

## Accepted tradeoffs / deferred gaps

1. **Fixed-window boundary burst (accepted).** A user can send up to 2× the
   minute cap across a window boundary (e.g. 10 at 0:59 + 10 at 1:01). Harmless
   at human pace, and the per-user daily cap + aggregate ceiling are the real
   spend bounds. Revisit with a sliding window only if abuse patterns show it
   matters.
2. **No IP dimension (accepted).** Keying by username is deliberate; adding IP
   would weaken the spend bound. If per-source throttling is ever needed it
   should be additive (a separate counter), not a change to the primary key.
3. **Shared-login blast radius (accepted, with a pointer).** Because there is one
   shared `staff` identity model, staff sharing a login share a per-user budget,
   so a per-user 429 could affect a whole desk. The correct fix is **per-staff
   logins / role segregation** — already tracked debt **D8** (§9, W4/W9), not
   this PR's scope. The aggregate ceiling is the backstop meanwhile.
4. **Concurrent single-flight / idempotency key (deferred).** The cache collapses
   *sequential* retries; two *simultaneous* in-flight identical submits can both
   miss and both fan out. Bounded by the rate limit and rare for a form submit.
   A single-flight lock (or an ai-assistant concurrency limiter) is a separate
   robustness knob to add if double-fire is observed in practice.

## Consequences

- New gateway config: `AI_RATE_LIMIT_PER_MINUTE` (10), `AI_RATE_LIMIT_PER_DAY`
  (200), `AI_RATE_LIMIT_GLOBAL_PER_DAY` (2000), `AI_CACHE_TTL_SECONDS` (300).
  All non-secret, documented in `.env.example`.
- `services/gateway/security.py` gains rate-limit, global-budget, and cache
  helpers (Redis-backed; the module now covers auth **and** Redis-backed abuse
  controls). ai-assistant is unchanged.
- Tests: `tests/test_gateway_ai_rate_limit.py` proves per-user rejection before
  fan-out, per-user isolation, the aggregate ceiling, cache collapse, that cache
  hits bypass the spend ceiling, PHI-safe (hashed) cache keys, and fail-closed on
  both counters. Regression-proven against pre-fix code.
- The controls mitigate the *effect* of non-expiring sessions on this endpoint
  but do **not** change auth behavior (ADR 0003 / §6 remains untouched).
