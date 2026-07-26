# ADR 0010 — Eligibility resilience: bound the payer call, decouple it from intake

**Status:** Accepted
**Date:** 2026-07-23
**Author:** Riverbend engagement team
**Debt:** D4 / RIV-088 / RIV-141

## Context

Front desk reports registration "spins" for 4–5 seconds on every save (RIV-088),
and on Tuesday 09:02–09:21 the **entire** intake screen froze — nobody could
register any patient, not just eligibility — recovering on its own at 09:21
(RIV-141). The payer's own status page (`docs/handover/payer-status-page.md`)
records an ACME clearinghouse eligibility-endpoint degradation over the exact
same 19-minute window, and the portal's `/intake` p95 spiked past 30s only then.

The COO framed this as "eligibility gets slow now and then but sorts itself out."
It is not a transient blip. There are two independent **unbounded blocking
points** on the synchronous `/intake` worker thread:

1. **intake → eligibility** — `intake-service/app.py` `_verify_eligibility`
   calls `httpx.get(...)` with no `timeout=`.
2. **eligibility → payer** — `eligibility-service/check.py` calls
   `requests.get(...)` with no timeout, retry, circuit breaker, or cache.

`/intake` is a synchronous FastAPI handler, so each in-flight request pins one
worker thread. During the payer degradation every intake thread parked on (2),
the pool drained, and all intake froze — the RIV-141 mechanism. A seeded
`time.sleep(4.2)` in `_verify_eligibility` stands in for the clearinghouse
round-trip and produces the RIV-088 "spin" unconditionally.

While tracing the fix we found a **cross-service PHI leak** on the same path.
`eligibility-service/app.py` catches the payer exception and both logs `str(e)`
and returns `error=str(e)` in `EligibilityResponse`. Because `check()` lets the
raw `requests` exception escape and the request URL carries
`?member_id=<insurance_id>`, the member id leaks into the eligibility log **and**
the response body. intake calls that endpoint and passes the body into the
`/intake` response, so the id reaches `/intake` even though intake's own
`except` branch is already PHI-safe (`docs/phi-logging-policy.md` rule 3). The
existing adversarial test (`tests/test_intake_eligibility_phi.py`) cannot catch
it — it monkeypatches `httpx.get` to *raise*, so it never exercises the real
200-with-error passthrough.

Constraints: services share code by copy-paste, no shared library (ADR 0001);
eligibility-service has no datastore (pure payer passthrough); Redis is currently
gateway-only. Auth is out of scope (ADR 0003). The bounded-outbound-call pattern
already exists in `ai-assistant/llm_client.py` and the gateway's `_post_checked`
— this ADR applies the same discipline to the eligibility path.

## Decision

- **Bound the payer call at its own seam (eligibility-service), not in intake.**
  The payer call only exists in `check.py`; payer-specific timeout / retry /
  breaker semantics belong there, and it keeps intake ignorant of payer
  internals. Intake gets a separate, simpler bound (below).

- **Timeout + bounded retry in `check.py`.** `requests.get` gains a
  `(connect, read)` timeout. Retries cover only `Timeout` / `ConnectionError` /
  5xx — a 4xx is **never** retried (a 404 is a legitimate "inactive coverage"
  answer, not a failure). Retry count and timeouts are config-driven.

- **In-process circuit breaker (`breaker.py`), not Redis-shared.** A ~40-line
  per-worker `CircuitBreaker` (closed → open → half-open) with an injectable
  time source so tests never sleep. Rationale: zero new infrastructure and **no
  redis dependency** in a service that currently has none; fully reversible.
  Cost: across *N* workers up to `N × threshold` failed calls can occur before
  every worker opens — but each such call is already timeout-bounded, so the
  burst is small and capped. Redis-shared breaker state would be globally
  accurate but adds the first cross-service redis dependency and a new failure
  mode (breaker store down); it is noted as the scale-up path only and would get
  its own ADR.

- **Typed payer exceptions.** `check()` raises `PayerTimeout` / `PayerUnavailable`
  / `PayerBreakerOpen` (subclasses of `PayerError`) instead of letting raw
  `requests` exceptions escape — mirroring `llm_client`'s typed-failure
  discipline. The exceptions carry **state only** (e.g. `"open"`), never
  `str(e)` and never the member id; the breaker keys nothing on the member.

- **Close the PHI leak in `eligibility-service/app.py`.** Log the exception
  **class only** (`type(e).__name__`) and set `EligibilityResponse.error` to a
  **generic literal** (`"eligibility check failed"`) — never `str(e)`. This is
  required regardless of the resilience work; it is the actual member-id leak.

- **A second, intake-side breaker on the intake → eligibility hop
  (adversarial review r4).** A per-request timeout bounds *one* registration's
  worker-hold; it does not bound the **sustained** cost. While eligibility or the
  payer stays wedged, every front-desk save still pays the full
  `ELIGIBILITY_TIMEOUT_SECONDS`, so concurrent registrations keep occupying
  intake workers — the RIV-141 mechanism, slowed but not removed. intake
  therefore gets its own copy of the breaker (`intake-service/breaker.py`;
  copy-paste, per ADR 0001): after
  `ELIGIBILITY_BREAKER_FAIL_THRESHOLD` consecutive unusable answers,
  `_verify_eligibility` returns `{"active": None, "status": "pending",
  "reason": "verification deferred"}` with **no outbound call**, until
  `ELIGIBILITY_BREAKER_RESET_SECONDS` elapse and one half-open probe is admitted.
  What counts as a breaker failure is a **dependency** verdict, never a coverage
  verdict: timeout, transport error, 5xx, and unparseable bodies count; a
  definitive `active`/`inactive` does not, whatever it cost (the per-call timeout
  already caps that, and suppressing correct verdicts helps nobody).
  A **4xx from eligibility-service does not count either** (adversarial review r5
  follow-up): it means eligibility rejected *this* request — a 422 on a blank or
  malformed `member_id`, say — which reports nothing about the dependency's
  health. The breaker is shared by every patient, so caller-driven input must not
  drive it: a botched batch import or a scanner emitting whitespace would
  otherwise open the circuit and strip verification from everyone else for the
  reset window. 408/429 are excluded from the carve-out, matching `check.py`'s
  transient/non-transient split.

- **A verdict is a boolean, not a word (adversarial review r5 follow-up).**
  `active` is the authoritative tri-state; `status` is derived detail, so intake
  computes `status` from `active` rather than trusting whatever string arrived.
  r3 established the rule in one direction (a dependency outage must never read
  as `inactive`). The mirror was still open: a body carrying `{"status":
  "active"}` with no `active` key — a captive portal, a proxy, a future
  responder — was reported to the front desk as covered, and after r5 it also
  held the circuit closed while every registration paid full latency.

- **A degraded eligibility answer counts against the intake breaker when it was
  slow, not when it was free (adversarial review r5).** eligibility-service
  returns HTTP 200 `{"active": null, "status": "unknown"}` for *both* of its
  degraded modes: its payer breaker short-circuiting (milliseconds — costs intake
  nothing) and a payer that hung until the whole payer budget burned (seconds —
  the sustained cost RIV-088 is about). r4 classified every shaped 2xx as healthy,
  so during the primary outage mode intake's breaker reset on every registration
  and never opened: the guard was bypassed exactly when it was needed. intake
  therefore judges a degraded answer by **what it cost this worker** — the thing
  the breaker exists to bound — counting it as a failure at or over
  `ELIGIBILITY_DEGRADED_SLOW_SECONDS` and as healthy under it. Latency is measured
  intake-side, so no new cross-service contract is needed and a downstream change
  cannot mis-signal it. Rejected alternatives: (a) count *all* degraded answers as
  failures — simpler, but it suppresses a free call and delays noticing the payer's
  recovery, since intake's circuit would then have to time out after
  eligibility's; (b) have eligibility-service emit a distinct degradation signal
  (non-2xx or metadata) — an API-contract change across two services to convey
  something intake can already observe directly.
  **Invariant:** `0.1s <= ELIGIBILITY_DEGRADED_SLOW_SECONDS <=
  PAYER_CONNECT_TIMEOUT_SECONDS`. The upper bound is the floor cost of a payer
  attempt that fails *by timing out*, so a hanging payer lands on the slow side;
  the lower bound clears one local HTTP round trip, so eligibility's free
  short-circuit lands on the fast side (`> 0` would be decorative — 1 ms sits
  below the round trip itself and would make every free short-circuit a failure).
  Guarded by `tests/test_eligibility_budget_alignment.py`, against both the
  `config.py` defaults **and** the `.env.example` values a fresh deploy seeds.
  **Cost is the whole rule, so some outage modes read as free — deliberately.** A
  payer refusing connections, returning a hard 401, or 5xx-ing instantly all reach
  intake as a *fast* `unknown` and stay healthy. They pin no worker, so they are
  not the RIV-141 mechanism; eligibility-service's own breaker and its logs are
  what surface them. (An earlier draft of this ADR claimed a real payer round trip
  *always* lands on the slow side. That is false for these modes, and the true
  rule is simpler: intake acts on cost, and only on cost.) A transport error
  reaching intake still counts as a failure whatever its latency — that means
  eligibility-service itself is unreachable, so there is nothing left to ask.
  **Honest limits:**
  - State is per-worker, so with *W* workers up to `W × threshold` slow calls can
    still land before every circuit opens, and concurrent in-flight calls are not
    retroactively cancelled — the breaker bounds the steady state of an outage,
    not its first burst.
  - **A slow-but-answering payer is never bounded in aggregate.** A clearinghouse
    that degrades without going dark (one attempt read-times-out, the retry
    answers) returns a definitive verdict after ~4–6s, every time, forever: the
    circuit stays closed by design, and the sustained cost is bounded only by the
    per-call timeout. This is the RIV-088 "4–5 second spin" in its partial-outage
    form, and it is *not* closed by this ADR. The trade is deliberate — tripping
    here would throw away correct coverage answers the payer is still giving —
    but the complete fix is true deferral below, not a bigger breaker.
  - **The breaker counts *consecutive* failures, so a mixed stream keeps resetting
    it.** In the canonical outage's steady state — eligibility's payer breaker
    open, answering free `unknown`s, with one slow half-open probe every
    `PAYER_BREAKER_RESET_SECONDS` — intake's circuit essentially never opens. That
    is the correct outcome (total cost is one payer budget per reset window, and
    what preserves intake capacity there is *eligibility's* breaker, not intake's),
    but it means intake's breaker earns its keep in the burst and in the
    eligibility-unreachable case, not in the steady state.
  - The timeouts bound each network *phase*, not total wall time: `requests`' read
    timeout is the gap between bytes and its connect timeout does not cover
    `getaddrinfo`, and `httpx.Timeout(8)` applies 8s to connect/read/write/pool
    separately. A payer trickling bytes or a hanging resolver can therefore exceed
    the nominal worst case. Classification stays correct (they land on the slow
    side); the numbers below are the design budget, not a hard ceiling.

  This narrows the RIV-141 window; it is not a substitute for true deferral below.

- **Decouple intake with a bounded best-effort call now; full out-of-band
  re-verification is a follow-up.** `_verify_eligibility` gets an explicit
  `timeout=` (a hard cap on intake worker-hold — the real RIV-141 guard), and
  the seeded `time.sleep(4.2)` is removed (a synthetic block no timeout can
  bound; it precedes the network call). A timeout returns a `pending` result; a
  transport error returns `unknown`; success is stamped `active`/`inactive`.
  Registration already commits the patient before eligibility runs, so this only
  changes what the eligibility *field* reports, never whether the patient is
  saved. Register-first-verify-later (instant 201 + async re-verify) is the
  complete D4 fix and is tracked as a follow-up, because it needs a job/result
  store — either the new redis dependency or new columns + a migration + a
  retrieval endpoint — i.e. schema / API-contract surface a bounded Week-3 change
  should avoid.

- **`active` is tri-state; `active=False` never means "unknown".** `active`
  becomes `Optional[bool]`: `True` = active, `False` = **definitively** inactive
  (the payer answered — a 2xx or a 404), `None` = unknown (timeout / breaker open
  / non-2xx / transport failure). A degraded result returns `active=None`, not
  `False`, so a caller reading only the boolean can never mistake a dependency
  outage for a coverage denial (adversarial review r3). `status`
  (`active`/`inactive`/`unknown`/`pending`) carries the finer detail. No code
  consumer branches on `active` today (the gateway proxies the JSON through), so
  making it nullable breaks nothing; `IntakeResponse.eligibility` stays
  `Optional[dict]`.
- **Budget invariant: inner < outer.** eligibility-service's worst-case payer
  budget `(connect + read) × (max_retries + 1)` must stay strictly below intake's
  `ELIGIBILITY_TIMEOUT_SECONDS`, with margin, so intake receives eligibility's
  graceful degraded answer instead of timing out first and abandoning a
  still-running downstream call (which wastes a retry and pins a worker —
  adversarial review r3). Guarded by `tests/test_eligibility_budget_alignment.py`.

- **Config defaults (SRE/ops calls, pending the real clearinghouse SLA):**
  eligibility `PAYER_CONNECT_TIMEOUT_SECONDS=1`, `PAYER_READ_TIMEOUT_SECONDS=2`,
  `PAYER_MAX_RETRIES=1`, `PAYER_BREAKER_FAIL_THRESHOLD=5`,
  `PAYER_BREAKER_RESET_SECONDS=30`; intake `ELIGIBILITY_TIMEOUT_SECONDS=8`,
  `ELIGIBILITY_BREAKER_FAIL_THRESHOLD=3`, `ELIGIBILITY_BREAKER_RESET_SECONDS=30`,
  `ELIGIBILITY_DEGRADED_SLOW_SECONDS=1` (intake's threshold of 3 is below the
  payer breaker's 5 because a failed call costs intake the whole payer budget it
  waited through — 6s, or 8s when eligibility itself is unreachable — where the
  payer path pays one attempt).
  Worst-case closed-breaker payer latency = `(1+2) × (1+1) = 6s`, under intake's
  8s cap (the budget invariant above; a design budget, not a hard ceiling — see
  the phase-timeout limit in the honest limits). During a sustained outage what
  collapses the per-registration cost to ~0 is normally *eligibility's* breaker
  short-circuiting; intake's own circuit carries the burst before that happens and
  the case where eligibility-service is unreachable outright.

## Consequences

- A payer outage no longer freezes intake: calls are bounded at both hops, both
  breakers open under sustained failure, and intake returns a bounded 201 with
  `status="pending"` instead of hanging. Worst case per registration is now
  `ELIGIBILITY_TIMEOUT_SECONDS` while the intake circuit is closed and ~0 once
  either circuit is open, versus unbounded before. RIV-088's spin is capped for a
  payer that stops answering (and the synthetic 4.2s block removed); a payer that
  keeps answering slowly still costs its latency on every save — see the honest
  limits.
- **What this does NOT do:** eligibility verification still runs on the `/intake`
  request thread, so registration is *delayed* by a bad payer, not immune to it.
  RIV-141's freeze mechanism is bounded rather than eliminated; closing it
  outright needs the register-first + async re-verification below. Code comments
  and `docs/debt-log.md` state the blocking behaviour plainly — an earlier
  revision of this branch claimed verification "never blocks the 201", which was
  not true (adversarial review r4).
- The member-id PHI leak on the eligibility failure path is closed, and a new
  end-to-end test exercises the real 200-with-error passthrough the old test
  missed.
- No new pip dependency (breaker hand-rolled on `requests`/`httpx` exceptions);
  eligibility-service stays datastore-free. Per-service `python -c "import app"`
  import smoke still passes (new env vars have defaults; nothing egresses at
  import).
- New env vars are added to `.env.example` with safe defaults, and reach the
  services through compose's existing `env_file: .env` — `docker-compose.yml`
  itself lists only per-service URLs and needs no change.
- **Out of scope / follow-ups:** full register-first async re-verification (the
  complete D4 fix), which is also what would close the slow-but-answering-payer
  limit above; a total-elapsed budget rather than per-phase timeouts (the
  trickling-payer / hanging-resolver limit); normalising `member_id` at the
  `schemas.Insurance` seam so blank/whitespace ids never reach the wire at all
  (the 4xx carve-out already stops them driving the breaker); the gateway
  `proxy_intake` path still uses the legacy `_post` (timeout=30, swallows errors
  into 200 + `str(e)`) and should move to `_post_checked`; the eligibility
  **agent + visit memory** the COO asked for lands in a second PR (ADR 0011) on
  top of this foundation.
