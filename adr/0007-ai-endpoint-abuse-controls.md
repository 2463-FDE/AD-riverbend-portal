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
     window. `INCR` + first-hit `EXPIRE` run as **one atomic Lua step**
     (`_incr_fixed_window`), so a counter can never be created without its TTL
     and every window self-clears — two separate round-trips could crash between
     them and strand a never-resetting quota key (a permanent lockout; Codex
     PR #7 round 12).
   - **Keyed by the authenticated username** — the abuse unit here, because a
     leaked/stale token replays as one user (sessions never expire).
   - Over cap → **429 + `Retry-After`** (seconds to window rollover).
   - Governs **requests** (cache hits included), not spend.
   - Rejects **before** touching the shared global counter, so a user hammering
     past their own cap cannot inflate the aggregate and starve others.
   - Defaults: **10/min, 200/day** (`AI_RATE_LIMIT_PER_MINUTE/_PER_DAY`).

2. **Aggregate daily spend ceiling** (`security.consume_ai_global_budget`,
   reserved by the single-flight **winner** on a cache miss, *after* request
   validation and immediately before fan-out — see controls 4 and 5).
   - A single global day-window counter, incremented **once per paid fan-out**.
   - Bounds **total** Bedrock spend across all users — per-user caps alone are
     unbounded in user count (N × per-user).
   - Over ceiling → **429 + `Retry-After`**. `<=0` disables it.
   - **Over-limit rejects are undone, not charged (Codex PR #7 round 11).** The
     counter is incremented before the cap comparison (a fixed-window `INCR` is
     the atomic read), but a request that lands over the ceiling is rejected
     *before any fan-out* — it makes no paid call — so its increment is rolled
     back immediately (`DECR`, with the same delete-if-`<=0` guard as the
     refund). Otherwise rejected over-limit retries would permanently inflate the
     counter above real paid usage, and the reserve-then-refund path (which only
     claws back paid-path 401/422/503s) could never bring it down — 429-ing valid
     callers until the day window rolls over. This preserves the invariant that
     the counter reflects paid fan-outs only. (Concurrent over-limit callers can
     transiently `INCR` past the cap before each `DECR`s back, but the excess is
     self-healing and bounded by concurrency — the same accepted fixed-window
     transient as gap 1, never a permanent inflation.)
   - Default: **2000/day** (`AI_RATE_LIMIT_GLOBAL_PER_DAY`), ≈ expected active
     staff × per-user cap.
   - **Only genuine paid fan-outs are charged.** The counter is reserved *after*
     the gateway has validated the request (control 4) and won the single-flight
     slot (control 5), so a body that ai-assistant would 422, and a duplicate
     concurrent miss, never charge the ceiling (Codex PR #7 round 7).
   - **Reserve-then-refund** (`security.release_ai_global_budget`, Codex PR #7
     round 8). The reservation is provisional: it is taken before the fan-out
     (so it still caps concurrent spend and fails closed), but **refunded** when
     the downstream response proves *no paid Bedrock call occurred* — a
     **401** (bad service-to-service auth), **422** (rejected at the boundary),
     or **503** (ai-assistant refused *before egress*: "assistant is not
     configured" — blank `AI_PROXY_SHARED_SECRET`, missing/placeholder Bedrock
     credentials, an unpriced model, or a **local budget-cap refusal**
     (`LLMBudgetExceeded`, whose token/char/cost caps are all enforced locally
     before any Bedrock call — Codex PR #7 round 10; it previously fell through
     to a keep-charge 500, so a cap set too low burned the ceiling on every
     request)). This is what makes the counter track paid calls *only*: without
     it, a blank secret or missing Bedrock config
     returns 503 on every authenticated retry, and a retry storm during that
     misconfiguration walks the shared counter to its cap — 429-ing every valid
     caller until the Redis window rolls over, *even after the config is fixed*.
   - **The refund split turns on egress, not on a bare status (Codex PR #7
     round 9).** A refund must fire only for a *pre-egress* refusal. ai-assistant
     originally mapped its *post-egress* provider failure (`LLMUnavailable` —
     throttle / upstream 5xx / connection error raised only *after* the Bedrock
     call was attempted) to **503** as well, so a genuine Bedrock outage looked
     identical to a config 503 and every retry was refunded — the ceiling stopped
     bounding vendor fan-out precisely when a retry storm made that bounding
     matter. Fixed by mapping `LLMUnavailable` to **502** (bad gateway = upstream
     provider failed), joining `LLMResponseError`. So now **502/504/500 keep the
     charge** (the provider path was entered — Bedrock may have been
     contacted/billed; gateway→service transport failures also land here), and
     **503 is unambiguously pre-egress**. The refund is best-effort: a lost
     refund only slightly over-counts (fails toward the ceiling, never past it),
     and it clears the counter to zero cleanly rather than resurrecting an
     expired window as a negative.

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

4. **Gateway request validation → canonical facts** (`_validate_ai_request`,
   before the cache key and the spend ceiling — Codex PR #7 rounds 7, 10).
   - The gateway parses the body with a **mirror of ai-assistant's
     `InstructionsRequest`** (`extra="forbid"` + the insurance-consistency rule)
     and returns a **no-echo 422** on failure, *before* deriving the cache key or
     reserving the budget.
   - On success it returns the **normalized `model_dump(mode="json")`**, and the
     cache key, single-flight lock, and fan-out payload all derive from that
     canonical fact vector — not the raw body (Codex PR #7 round 10). Otherwise
     `{}`, a body spelling out the schema defaults, and coerced booleans
     (`"true"` vs `true`) hash to different keys for the *same* facts, letting a
     caller bypass duplicate-collapse (control 3 / control 5) and spend repeated
     Bedrock calls for one fact vector. `extra="forbid"` means the dump carries
     only closed-vocabulary fields, so nothing smuggled rides into the fan-out.
   - Closes the round-7 **high**: without it, a logged-in caller could send many
     distinct invalid bodies (unknown fields, contradictory insurance facts),
     each a cache miss that charged `ratelimit:ai:global` and was only rejected
     downstream — a cheap tenant-wide denial of the paid assistant.
   - ai-assistant remains the **authoritative** validator; this is a budget
     pre-filter. If the mirror ever drifts looser, the only cost is that the
     gap bodies reach the fan-out and 422 there (today's behavior, narrower) —
     never a wrong checklist. Kept in sync like `PlanType` ↔ the portal select.
   - No-echo mirrors ai-assistant's `validation_error_no_echo`: a rejected value
     is exactly where PHI could be smuggled, so neither the value nor the parse
     error is logged or echoed.

5. **Single-flight coalescing of concurrent misses** (`security.ai_singleflight_*`,
   in the handler on a cache miss — Codex PR #7 round 7, closes gap #4 below).
   - The cache collapses *sequential* retries; this collapses *simultaneous*
     ones. A Redis `SET NX EX` lock keyed off the cache key elects **one winner**
     to reserve budget and fan out; concurrent duplicate misses (a double-click,
     a browser retry, many staff submitting the same closed-vocabulary facts at
     once) **wait briefly** (`AI_SINGLEFLIGHT_WAIT_SECONDS`, polling every
     `AI_SINGLEFLIGHT_POLL_SECONDS`) for the winner's cached result, then return
     a **controlled 429** rather than a second paid call.
   - Closes the round-7 **medium**: previously every request that observed the
     initial miss reserved budget and made its own paid call before the first
     response cached.
   - The winner **releases** the slot in a `finally` (even if the fan-out
     raised), and the lock **TTL** (`AI_SINGLEFLIGHT_LOCK_TTL_SECONDS`, default
     just above the AI read timeout) bounds a crashed winner, so the key can
     never wedge.
   - **Best-effort / fail-OPEN:** a Redis fault on the lock returns "winner"
     (degrades to an uncoalesced paid call, today's behavior), because the
     authoritative spend guard is the fail-CLOSED budget ceiling (control 2), not
     the lock — failing the lock closed would turn a Redis blip into an outage.

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
- **Scalability:** the fixed-window `INCR`+`EXPIRE` is one atomic O(1) Lua call;
  no per-instance state, so gateway replicas share one view; key cardinality is
  bounded by staff count and TTL-reaped (and the TTL is bound atomically at
  creation, so reaping can never be defeated by a partial write).

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
4. **Concurrent single-flight (RESOLVED in Codex PR #7 round 7 — see control 5).**
   Originally deferred: the cache collapsed only *sequential* retries, so two
   *simultaneous* identical submits could both miss and both fan out. Now closed
   by the `SET NX` single-flight lock (control 5) — one winner fans out, losers
   coalesce onto its result or get a controlled 429. Idempotency keys remain
   unneeded: the closed-vocabulary body hashes to a stable key, so the lock keys
   itself off the request identity directly.

## Consequences

- New gateway config: `AI_RATE_LIMIT_PER_MINUTE` (10), `AI_RATE_LIMIT_PER_DAY`
  (200), `AI_RATE_LIMIT_GLOBAL_PER_DAY` (2000), `AI_CACHE_TTL_SECONDS` (300), and
  (round 7) `AI_SINGLEFLIGHT_WAIT_SECONDS` (2.0), `AI_SINGLEFLIGHT_POLL_SECONDS`
  (0.1), `AI_SINGLEFLIGHT_LOCK_TTL_SECONDS` (≈ read timeout + 15). All
  non-secret, documented in `.env.example`.
- `services/gateway/security.py` gains rate-limit, global-budget (with a round-8
  `release_ai_global_budget` refund counterpart), cache, and (round 7)
  single-flight lock helpers (Redis-backed; the module now covers auth **and**
  Redis-backed abuse controls). `services/gateway/app.py` gains the gateway-side
  request-validation pre-filter, (round 8) the reserve-then-refund wiring
  around the fan-out, and (round 10) canonicalization of the cache/single-flight/
  fan-out key via the validated `model_dump`. ai-assistant changed only in its
  error-status mapping: (round 9) `LLMUnavailable` returns **502** (post-egress
  provider failure, keep charge) and (round 10) `LLMBudgetExceeded` returns
  **503** (pre-egress local cap refusal, refund) instead of the keep-charge 500 —
  both so the gateway's status-based refund split correctly tells a pre-egress
  refusal (refund) from a call that may have reached Bedrock (keep charge).
- Tests: `tests/test_gateway_ai_rate_limit.py` proves per-user rejection before
  fan-out, per-user isolation, the aggregate ceiling, cache collapse, that cache
  hits bypass the spend ceiling, PHI-safe (hashed) cache keys, fail-closed on
  both counters, (round 7) that invalid bodies are rejected before the spend
  ceiling is charged and that concurrent identical misses coalesce to one paid
  call, (round 8) that a downstream 503 refunds the reserved slot so
  repeated config failures past the cap do not block a later success, and
  (round 9) that a post-egress provider **502** is *kept charged* so an outage
  retry storm stays bounded by the ceiling, with `test_ai_intake_instructions`
  pinning `LLMUnavailable → 502` (a status the gateway does not refund), and
  (round 10) that a local budget refusal maps to a *refundable* **503** (pinning
  `LLMBudgetExceeded → 503`, a gateway-refunded status) and that requests
  spelled differently (`{}` vs explicit defaults vs coerced booleans) collapse
  to one cached paid call, and (round 11) that an over-limit 429 leaves the
  global counter unchanged (no stray increment) and that — modelling a
  concurrent in-flight reservation — an over-limit reject followed by a
  refundable 503 lets a subsequent valid request succeed instead of staying
  429'd on an inflated counter, and (round 12) that a counter's TTL is bound
  atomically on its first write (a stubbed-unavailable separate `EXPIRE` cannot
  strand a no-TTL key) and that every quota key — minute, per-user day, and
  global — is created with a TTL. Regression-proven against pre-fix code.
- The controls mitigate the *effect* of non-expiring sessions on this endpoint
  but do **not** change auth behavior (ADR 0003 / §6 remains untouched).
