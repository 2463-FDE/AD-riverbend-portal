# ADR 0011 — Eligibility agent endpoint and visit-scoped memory

**Status:** Accepted (implementation lands in PR-B; the three approval-gated calls
below were decided with the engagement lead on 2026-07-26 — see Consequences)
**Date:** 2026-07-26
**Author:** Riverbend engagement team
**Relates to:** ADR 0004 (ai-assistant service + PHI-safe LLM wrapper — the wrapper
this endpoint reuses), ADR 0007 (AI endpoint abuse controls — the gateway control
stack this endpoint joins), ADR 0009 (Bedrock provider — the paid inference path),
ADR 0006 (metadata-only observability), ADR 0010 (eligibility resilience — the
bounded payer path this agent consumes), ADR 0003 (authentication/sessions —
deliberately untouched), ADR 0001 (no shared library; copy-paste service layout).
Second half of the Week-3 deliverable (`docs/specs/w3.md` §4, items 1 and 3):
PR #11 shipped resilience, this ships the assistant and its visit memory.

## Context

The client ask (Dr. Okonkwo, COO, verbatim in `docs/specs/w3.md` §1):

> Can you build them a little chat assistant that checks a patient's eligibility
> and keeps track of the visit context as they go?

PR #11 (ADR 0010) made the eligibility path safe to consume: the payer call is
bounded by a timeout, a retry budget, and an in-process circuit breaker, and its
result is a tri-state (`active` / `inactive` / `unknown`, with intake stamping
`pending` when its own hop times out). An outage now reads as "unknown", never as
a false denial. That contract is the foundation this ADR builds on — the agent's
job is to surface that verdict conversationally without ever converting an
"unknown" into a "not covered".

Four constraints shape every decision below.

1. **The vendor boundary is not cleared for PHI.** Debt **D13 / #5** (CLAUDE.md
   §9): Bedrock is used on standard SaaS terms with **no BAA**.
   ADR 0004 kept `/intake-instructions` safe by construction — its request is
   closed vocabulary (enum/bool only), so nothing PHI-shaped can reach the prompt.
   A free-text chat box is the obvious way to break that invariant, and W8 — the
   week that establishes the BAA and a real Safe-Harbor scrub — is **Pending**.
   Anything this ADR ships must hold the boundary W8 has not yet moved.
2. **Redis is the only available store, and it is not hardened.** The gateway owns
   Redis (sessions, ADR-0007 counters and cache); no other service has a client.
   In `docker-compose.yml` the `redis:7` service publishes **port 6379 to the
   host** and sets **no `requirepass`**, with no named volume (default RDB
   snapshots stay container-local). Sessions living there today carry a username
   and a role. Visit memory would put an **insurance/member id** there — a
   different exposure class.
3. **The gateway is a load-bearing wall.** `services/gateway/app.py` owns auth for
   the entire portal (CLAUDE.md §6). Domain orchestration does not belong in it;
   new behavior should land at a seam — a new endpoint in a service, wired in one
   place.
4. **Ungrounded model output is already known debt.** CLAUDE.md §9 "AI output
   guardrail": an LLM summary elsewhere in the estate hallucinated clinical
   content ("continue metformin" for a no-meds patient). A coverage verdict is a
   financial and access-to-care fact; a model must not be the thing that asserts
   it.

## Decision

### 1. A new stateless endpoint in ai-assistant: `POST /visit-chat`

The agent lives in `ai-assistant`, behind the existing `_require_internal_auth`
dependency, and reuses `llm_client.complete_structured` — the same bounded,
budget-gated, typed-error wrapper `/intake-instructions` uses.

The endpoint is a **pure function of its arguments**: it holds no state, takes the
conversation so far as an argument, and returns the updated facts for the caller to
persist. `visit_id` never crosses this boundary, so the identifier that keys the
memory cannot appear in an ai-assistant log line.

*Rejected alternatives.* A **new agent service** would copy-paste the
safety-critical LLM wrapper (ADR 0001 mandates copy-paste for the service
skeleton, but duplicating 640 lines of budget/redaction/retry logic multiplies the
places a PHI guard can drift). **Calling Bedrock from the gateway** would put paid
egress inside the auth owner and defeat the ADR-0007 topology, in which the
gateway is the *choke point* and ai-assistant is the only egress point. Putting
the agent in **intake-service** would re-couple registration to a slow dependency,
which is the exact defect PR #11 just bounded.

### 2. The vendor never sees free text (the D13 gate)

Free text crosses **portal → gateway → ai-assistant** (internal, the same trust
boundary intake→eligibility has always had). It does **not** cross ai-assistant →
Bedrock.

Per turn, ai-assistant:

1. **Understands deterministically.** A closed `VisitIntent` enum is derived from
   the message by server-side code — member-id recognition plus keyword
   classification. No model call, so no free text and no PHI leaves the process
   for this step.

   Member ids are matched against a **closed payer-prefix catalog**
   (`AI_MEMBER_ID_PREFIXES`), never a generic letters-then-digits pattern.
   *(Amended 2026-07-26 after the pre-push adversarial review.* The first cut used
   `[A-Z]{3,6}\d{3,9}` and claimed a false positive was safe because "the lookup
   returns unknown, never a denial". That was wrong in the direction that hurts
   patients: eligibility-service maps a payer **404 to a definitive
   `{"active": false}`**, so a mis-extracted token — a prior-auth number, an
   account ref — renders as "the payer reports NO ACTIVE COVERAGE" for a patient
   whose coverage is fine. An outage degrades safely; a confident answer about the
   **wrong subject** does not, and nothing downstream can detect it. Ids here are
   payer-prefix + 4 digits, so a catalog is both possible and the rule this ADR
   already applies to model output.)*

   Two ambiguity rules follow from the same reasoning, because a wrong id is worse
   than a question: **more than one candidate** in a message, or a candidate that
   **contradicts the id already confirmed for this visit**, yields
   `clarify_member_id` and asks the clerk. No lookup runs, and the stored verdict
   is not restated — it describes a different subject.
2. **Acts deterministically.** If an id is present in the message (or already in
   the visit facts, for a re-check), it calls eligibility — bounded, see §4. The
   decision to make an outbound call is never a function of model output.
3. **Grounds, then phrases from a catalog.** The verdict is rendered
   **server-side** from a fixed template catalog keyed by the ADR-0010 status
   (`active` / `inactive` / `unknown` / `pending` / no-id). The LLM's only input is
   **closed vocabulary** — the intent enum, the status enum, the turn count, and
   the candidate template ids — and its only output is a **list of template ids**,
   gated by `required <= selection <= allowed` exactly as
   `app._select_items` already does for `/intake-instructions`. Any violation
   discards the whole selection for the deterministic default.

So the model's real freedom is *which pre-reviewed follow-up lines accompany a
verdict it did not author*. That is a smaller assistant than "a chat bot", and the
smallness is the point: **it makes W3 shippable without waiting on W8.** The
upgrade path — model-authored phrasing behind a grounding checker, once a BAA and
a real scrub exist — is deferred, not designed away (see Deferred gaps 1).

*Rejected alternative.* **Send the redacted message to Bedrock.** Best-effort
masking catches id- and SSN-shaped tokens but not names, and a patient name in a
free-text sentence is PHI. Sending "mostly redacted" PHI to a vendor with no BAA
is the same self-asserted-compliance posture ADR 0002 already flags. Rejected on
the PR #7 lesson recorded in project memory: prefer a closed catalog to a regex
filter when the regex is the only thing standing between a defect and a patient.

### 3. Visit memory lives in the gateway, keyed opaquely and owner-bound

New helpers in `services/gateway/security.py` (where every Redis-backed control
already lives): `visit_memory_get` / `visit_memory_save` / `visit_lock_acquire` /
`visit_lock_release`.

- **Key:** `visit:{uuid4().hex}` — 128 bits, opaque, minted by the gateway on the
  first turn. Deliberately the opposite of the D11 chart-read defect (sequential
  integer `patient_id`, walkable): a visit id cannot be enumerated, and it is
  never derived from the member id.
- **Owner binding:** the stored value carries `owner` = the authenticated session
  username. A load whose `owner` does not match the caller returns **404 "visit
  not found"**, never 403 — a 403 would confirm the id exists. This is *not* an
  auth change (ADR 0003 stands): `require_session` still proves only "logged in",
  and because there is one shared `staff` role (**D8**), staff sharing a login
  share visit access. Owner binding narrows cross-user access; it does not
  establish per-patient authorization, which is W4/W9 work.
- **Value:** `owner`, `created_at`, `updated_at`, `facts`, `turns`.
  - `facts` = `insurance_id` plus a **structured** `last_eligibility`
    (`active`, `status`, `payer`, `raw_status`, `checked_at`). Structured, so a
    later turn answers "is it still active?" from typed state rather than from
    re-parsed prose.
  - `turns` = a bounded rolling window recording **what happened, never what was
    said**: `{role, intent, status}` per turn, no text. *(Amended 2026-07-26,
    during implementation. The original draft said the transcript would be stored
    "redacted", via a copy of `redaction.py`. Writing the adversarial test made
    two things obvious: `redact_text` matches SSN / email / phone patterns and
    cannot mask a typed patient NAME, so "redacted transcript" would have been a
    false claim; and nothing in this feature ever reads the text back — the
    deterministic logic works off `facts`, and the model is told only the turn
    COUNT. Storing it would have been unmaskable PHI at rest with no consumer.
    Dropping the field removes the exposure by construction instead of mitigating
    it, and takes the gateway `redaction.py` copy with it.)* The only identifier
    anywhere in visit memory is `facts.insurance_id`. A future chat UI that wants
    to replay prose is a NEW PHI-at-rest decision needing its own approval.
  - **Never stored:** the eligibility `error` string (ADR 0010 closed a leak in
    exactly that field), the member id inside the *key*, or anything from a
    rejected request body.
- **Sliding TTL:** `AI_VISIT_TTL_SECONDS` = 1800. Every save is a single
  `SET key value EX ttl`, which is atomic — the "counter created without its TTL"
  class (ADR 0007 round 12) cannot arise here, so no Lua script is needed.
- **Bounded growth:** `AI_VISIT_MAX_TURNS` = 12 (oldest evicted) and
  `AI_VISIT_MAX_MESSAGE_CHARS` = 1000 (enforced at the gateway edge). A visit is
  therefore ~12 KB worst case; key cardinality is bounded by the per-user daily
  request cap and TTL-reaped. This is a PHI bound, not just a memory bound: an
  unbounded transcript in Redis is a PHI dump with a retention policy of "never".
- **Per-visit serialization:** `visitlock:{visit_id}`, `SET NX EX` with a unique
  owner token released by owner-checked compare-and-delete — the ADR-0007 control-5
  pattern, repurposed. It collapses concurrent turns in one visit (a double-submit
  would otherwise read-modify-write the same blob and silently drop a turn, and
  would make two paid calls). A held lock returns a controlled **429 +
  `Retry-After`**. Fail **open** on a Redis fault, consistent with the
  single-flight precedent: the authoritative spend guard is the fail-closed budget
  ceiling, and a lost turn is benign where an outage is not.
- **Memory-load faults fail CLOSED (503).** *(Amended 2026-07-26 during
  implementation; the draft said they would fail soft to a fresh visit.) A
  backend or parse fault cannot distinguish "no such visit" from "somebody
  else's visit", so continuing would wave through a turn whose ownership was
  never verified — an authorization bypass reachable by making Redis flap. Only a
  turn that supplies NO `visit_id` starts fresh, and that path reads nothing.
  An unknown `visit_id` is a 404, not a fresh visit, so a client cannot choose
  its own visit ids. Write faults still fail soft (the turn is already answered;
  losing continuity beats 500-ing).*

*Rejected alternative.* **Agent-local memory in ai-assistant** (in-process dict or
a new Redis client there). Rejected: ai-assistant is horizontally scalable and
stateless by design, in-process state breaks under replicas, and adding a
datastore to the egress service is the same "more surface, no benefit" trade ADR
0007 already rejected. This also answers `docs/specs/w3.md` open question 2 —
Redis, gateway-held.

### 4. ai-assistant → eligibility-service is bounded like every other hop

A new `services/ai-assistant/eligibility_client.py` calls
`GET /eligibility?insurance_id=…` with an explicit timeout and a copy of the
ADR-0010 in-process breaker (`AI_ELIGIBILITY_TIMEOUT_SECONDS`,
`AI_ELIGIBILITY_BREAKER_FAIL_THRESHOLD`, `AI_ELIGIBILITY_BREAKER_RESET_SECONDS`).
The D4 lesson applies to the new caller, not only the old one: an unbounded call
would let a payer outage pin ai-assistant's workers, and a chat endpoint invites
retries. It logs the exception **class** only, never `str(e)` and never
`insurance_id` (`docs/phi-logging-policy.md` rules 2–3) — the payer URL embeds the
member id, which is how the PR #11 leak happened.

This gives ai-assistant its first PHI-bearing outbound call. Accepted as the price
of keeping the gateway thin (constraint 3); flagged for human approval below.

### 5. The verdict contract: unknown is never a denial

Verdict templates are keyed by the ADR-0010 status:

| status | what the reply says |
|---|---|
| `active` | coverage confirmed, with `checked_at` |
| `inactive` | payer definitively reports no active coverage |
| `unknown` | **could not confirm** — try again shortly; do not treat as uninsured |
| `pending` | verification still outstanding (intake's timeout path) |
| no id yet | ask for the member id |

`unknown` and `pending` render *unconfirmed*, never *not covered*. This is the
same tri-state discipline PR #11 established in code, carried to the words a human
reads — the failure mode being designed against is a front-desk clerk turning a
patient away during a clearinghouse outage. A stored `last_eligibility` is always
rendered with its `checked_at`, so a reused verdict is visibly a past observation,
never restated as current.

### 6. ADR-0007 controls: which apply, and one that must not

- **Per-user rate limit — yes, in its own namespace.** `ratelimit:aichat:*` with
  its own knobs (`AI_CHAT_RATE_LIMIT_PER_MINUTE` = 20,
  `AI_CHAT_RATE_LIMIT_PER_DAY` = 400 — a conversation is many turns where an
  intake checklist is one shot). A separate namespace so chat turns cannot exhaust
  the quota for `/intake-instructions` or vice versa. `check_ai_rate_limit` gains
  an additive namespace parameter defaulted to today's value, so the existing
  endpoint's keys and behavior are unchanged.
- **Aggregate spend ceiling — yes, shared.** Both endpoints charge the same
  `ratelimit:ai:global` counter: it exists to bound *dollars per tenant per day*,
  and splitting it would raise the real ceiling silently. Reserve-then-refund and
  the egress-based refund split are reused verbatim.
- **Response cache — NO, deliberately.** A reply depends on visit memory and on a
  *live* coverage verdict, so it is neither idempotent nor safely shareable, and
  the cache key would have to be derived from PHI-bearing free text. Caching a
  coverage answer is how a stale or cross-patient verdict reaches a clerk. This
  exclusion is a decision, not an omission — `AI_CACHE_TTL_SECONDS` is not
  consulted on this path.
- **Single-flight — repurposed** as the per-visit lock (§3), keyed by visit rather
  than by body hash: identical *bodies* in a conversation are legitimate ("still
  active?"), identical *turns in one visit* are not.
- **Fail-closed on the paid path** is preserved: an unreadable rate-limit or
  budget counter returns **503** and no LLM call happens.

### 7. Error mapping: the turn never fails on the LLM, and spend is reported separately

*(Rewritten in round 3 — see "Round 3 corrections". The original mapping is
preserved there, because the reasoning that made it wrong is the useful part.)*

Boundary rejections keep ADR-0007's contract unchanged: a bad internal auth →
**401**, a rejected body → **422**, an empty member-id catalog → **503**. All
three are refunded by `_NON_PAID_DOWNSTREAM_STATUS`, and all three happen
*before* any payer call.

Everything past that point is different, because by then the deterministic act
step may already have spent an outbound PHI-bearing eligibility call and written
its verdict into the visit's facts. **No LLM failure fails the turn.** Action
selection is the last and least important step — it chooses *which* fixed
follow-up lines to show, never whether the patient has coverage — so every
failure branch renders `visit_templates.default_selection(status)` and answers
200 with the verdict intact.

That breaks the assumption the gateway's refund rule rested on: a 200 no longer
proves a paid Bedrock call happened. The spend verdict therefore travels as data
rather than as a status code, in `VisitChatResponse.llm_egress`.
`proxy_visit_chat` refunds the reserved slot when the flag is explicitly `False`;
anything absent or ambiguous keeps the charge, which over-counts toward the
ceiling rather than refunding spend that really occurred.

**The flag is set by the raiser, not inferred from the exception type**, and that
distinction is load-bearing rather than stylistic. The first cut of this change
read "`LLMConfigError` ⇒ nothing egressed", which is false:
`llm_client._call` maps Bedrock's own `ClientError` — `AccessDeniedException`,
`UnrecognizedClientException`, `ValidationException`, `ResourceNotFoundException`
— onto `LLMConfigError`, and those arrive *after* the full request crossed the
vendor boundary. Under a rotated key or a mistyped model id that reading would
have refunded every turn, so the aggregate ceiling ADR 0007 built to bound
vendor fan-out would never have advanced, while each turn still shipped a
request. `LLMError` now carries an `egressed` attribute, defaulting to `True`,
which only the four genuinely local gates (the two pricing refusals, the
bearer-token gate, and botocore's credential-chain failure) and
`LLMBudgetExceeded` set to `False`. `_reply_items` reads the attribute in a
single `except LLMError`, so there is no longer an exception-ordering hazard to
get wrong either.

Because a fault now looks like a success from the outside, health travels
separately from spend: `VisitChatResponse.assistant` is `ok` or `degraded`, and
the gateway forwards it as `ok` / `degraded` / `unknown` alongside
`visit_memory`. The two booleans are independent — a post-egress failure is
billable *and* degraded; a local refusal is neither — so collapsing them into
one field would have made a dead Bedrock configuration invisible on every
channel an operator watches.

This also settles the divergence from `/intake-instructions` that the original
mapping only half-owned. `/visit-chat` degrades and answers for *all* LLM faults;
`/intake-instructions` still returns 502 on a post-egress failure, and that is
defensible for a different reason — a checklist has no already-computed result to
preserve, so failing loudly costs nothing. Aligning the two remains a candidate
follow-up, not a claim of principle.

### 8. Non-goals

- **No auth change.** ADR 0003 stands; sessions still never expire and there is
  still one role. Owner binding is per-*visit* access control on a new resource,
  not a change to `require_session`.
- **No records or chart data.** The agent sees an insurance id and a coverage
  verdict. Assembling a patient view is W4 (D11/D8).
- **No clinical content of any kind**, and no patient-facing language: the reply
  catalog is administrative, staff-facing, and carries a fixed server-appended
  disclaimer. The W7 guardrail debt is not re-litigated here because no clinical
  claim is generated in the first place.
- **No cross-visit or long-term memory**, no async job store (that is ADR 0010's
  register-first follow-up), and no new pip dependency.

## Alternatives considered

- **Model-driven tool calling** (expose an `eligibility_lookup` tool and let the
  model orchestrate). Rejected: it makes an outbound PHI-bearing call a function
  of model output and of attacker-controllable free text, and it would send that
  free text to the vendor. The deterministic act step is what makes prompt
  injection unable to cause a payer call, a coverage claim, or an egress.
- **Gateway-orchestrated agent** (gateway extracts the id, calls eligibility,
  passes only the verdict to ai-assistant). Genuinely tempting — it keeps
  ai-assistant free of PHI-bearing outbound calls. Rejected because it puts
  domain orchestration and free-text parsing inside the auth owner (constraint 3);
  the ADR-0007 split of "gateway = auth + abuse controls + Redis, service =
  domain" is worth more than removing one outbound dependency.
- **Store the transcript at all** (raw, or pattern-redacted). Rejected during
  implementation: constraint 2 (unhardened Redis) plus PHI minimisation, and
  decisively the fact that nothing reads it back. Pattern redaction would also
  have been a false comfort — it cannot mask a typed patient name. Continuity
  comes from typed `facts`; the turn log is metadata only.
- **Do not store `insurance_id` at all** (re-ask every turn). Rejected as the
  default because "keeps track of the visit context" is the client ask, and
  re-asking a member id each turn is the friction the assistant exists to remove.
  The mitigations are the TTL, the opaque key, owner binding, and the Redis
  hardening flagged below. If approval for PHI-at-rest is withheld, this is the
  fallback design and the endpoint still works, one question longer.

## New abuse and PHI surfaces (multi-turn is not one-shot)

| Surface | Mitigation |
|---|---|
| Unbounded token spend across turns | turn window (12), per-message char cap (1000), the LLM sees closed vocabulary only, one paid call per turn, chat rate namespace + shared ceiling |
| Prompt injection in free text | free text never reaches the vendor; model output is a closed id list gated server-side; the act step is deterministic; no tools exposed |
| PHI in free text reaching logs | the message is never logged and never stored; chat logs are a metadata allowlist (intent, status, turn count) per the `log_metadata` precedent |
| PHI at rest in Redis | minimal fields, sliding 1800s TTL, opaque key, no id in keys or logs, error strings never persisted — **plus the Redis hardening flagged below** |
| `visit_id` IDOR / enumeration | 128-bit opaque uuid4, owner binding, 404-not-403 on mismatch, `visit_id` never crosses to ai-assistant |
| Visit fan-out (minting many visits) | bounded by the per-user daily chat cap × TTL; every key TTL-reaped |
| Payer outage pinning chat workers | bounded timeout + in-process breaker on the new hop (§4) |
| Stale verdict read as current | `checked_at` always rendered; no response cache on this path |

## How this serves the client and domain

- **Client:** front desk gets the assistant they asked for, and it keeps visit
  context across turns, without waiting on the BAA work that gates W8.
- **Patient safety / access to care:** a clearinghouse outage can never render as
  "not covered", in code (PR #11) and now in words.
- **Robustness:** every outbound call on the new path is bounded and breakered;
  the paid path fails closed; the model path degrades to deterministic output
  instead of failing the turn.
- **Maintainability:** one new endpoint, one new client module, one new catalog,
  and Redis helpers colocated where every other Redis control already lives.
  Patterns are reused, not reinvented — the selection gate, the owner-checked
  lock, the metadata-only log projection, the breaker.

## Accepted tradeoffs / deferred gaps

1. **The assistant does not author prose (accepted, revisit after W8).** Replies
   are catalog-rendered, so phrasing is fixed and the conversation is narrower
   than a general chat bot. This is what keeps free-text PHI inside the trust
   boundary while D13 (no BAA) is open. Revisit when W8 lands a BAA and a real
   Safe-Harbor scrub; the upgrade is model-authored phrasing behind a grounding
   checker, with the verdict still server-rendered.
2. **Redis hardening — CLOSED in this PR (2026-07-27), was "flagged, not fixed".**
   The original decision (2026-07-26) was to keep PR-B feature-scoped and land the
   hardening separately, accepting a member id at rest on a host-published,
   passwordless store under the §3 mitigations. The adversarial review round 1 on
   PR #14 called that the shipping blocker, and the engagement lead reversed the
   scoping call: the precondition ships **with** the feature rather than after it.
   What landed — `docker-compose.yml` drops the `6379:6379` publish for `expose`
   and starts Redis with `--requirepass`, refusing to boot on an empty password;
   the credential lives in a scoped `.env.redis` (redis + gateway only, the same
   containment as `.env.ai-proxy`), generated per machine by `make up`; and
   `security._redis()` refuses to connect when no credential (or a placeholder
   one) is configured, so a deploy whose topology is not ours still cannot put
   sessions or a member id on an open store. Residual, still **D3b** in
   `docs/debt-log.md`: no TLS in transit, one shared credential rather than
   per-consumer ACL users, no named volume (RDB snapshots stay container-local
   and unencrypted), and no audit trail of reads.
3. **Deterministic intent classification is shallow (accepted).** Keyword +
   pattern matching will miss unusual phrasings, degrading to the `other` intent,
   which asks a clarifying question. A gated `complete_structured` intent
   classifier over closed *output* is the upgrade — but its *input* would be free
   text, so it is blocked by the same D13 gate as gap 1.
4. **Shared-login blast radius (accepted, pointer).** One `staff` identity model
   means owner binding cannot distinguish two clerks sharing a login; they share
   visits and a chat quota. The fix is per-staff logins / role segregation —
   debt **D8**, W4/W9 — not this PR.
5. **Post-egress behavior differs across the two AI endpoints (accepted, §7).**
   Aligning `/intake-instructions` is a follow-up.
6. **A pre-egress LLM refusal discards an already-computed verdict — CLOSED in
   this PR (round 3), was "accepted".** The gap was accepted on a false
   constraint (that answering would mean keeping an unearned charge). See
   "Round 3 corrections". **Its second symptom is now closed too (round 4)** —
   a repeat of the member id no longer spends another payer call while the visit
   holds a fresh definitive verdict for that id. See "Round 4 corrections".
7. **No stale-verdict cache when the breaker is open (decided; scope narrowed in
   round 4).** This answers `docs/specs/w3.md` open question 1: when eligibility
   is degraded the agent reports *unconfirmed* rather than serving a
   stale-but-usable cached verdict. A cached coverage answer is a financial fact
   with an expiry we cannot see, and caching it would put PHI-derived state in a
   shared keyspace for a marginal latency win. Within a visit,
   `last_eligibility` is reused only with its `checked_at`, never restated as
   current.

   What this decision rules out is a **shared, cross-visit** verdict cache, and
   in particular serving a stale verdict *in place of* an attempt that failed.
   Both still hold: a degraded `unknown`/`pending` verdict is never reusable
   however fresh it is, so an outage still reports unconfirmed and still
   re-attempts. Round 4's per-visit freshness window is not that cache — it
   reuses only state the visit already carries, in the visit's own owner-bound
   record, for definitive verdicts only.

## Round 2 corrections (2026-07-27)

Adversarial review round 2 on PR #14 found both of round 1's Redis-hardening
mechanisms reporting success they had not earned. Neither is a change to auth
behaviour; both are changes to how a failure is *reported*.

1. **`/healthz` sends a real authenticated PING, bounded by
   `REDIS_PROBE_TIMEOUT_SECONDS` (default 0.5s, clamped to 0.1–0.7s).** Round 1
   made the check a *config* probe on the argument that issuing no command could
   not flap on a Redis blip. True, and the cost of that property was too high: a
   credential the server rejects (the gateway's `REDIS_PASSWORD` drifting from
   the server's `--requirepass`), a store that died after boot, and a stale
   client all left the endpoint at 200 while every session-backed route failed —
   the same green-dashboard-dead-service shape the check was added to prevent,
   one layer in. An accurate red beats a stable lie here: nothing in the topology
   drains or restarts on this signal (the portal's `depends_on` carries no health
   condition), so the cost of flapping is a red status during a real outage,
   which is the intended reading. The probe gets its **own** client, because the
   shared session client is deliberately built with no socket timeouts and
   retuning it would change how every session read fails — a §6 change made as a
   side effect of a health check.

   Four properties make the probe affordable on a public, session-less endpoint
   that now does I/O (all four came out of the pre-push review of this change):

   - **The budget is per socket operation, not per probe.** redis-py applies the
     timeout to each blocking call separately, and a cold connection makes
     several before PING (connect, AUTH, an optional SELECT for a non-zero db).
     So the *ceiling* is the healthcheck timeout divided by that op count, not
     the timeout itself: a 2.5s clamp against `timeout: 3s` could spend ~10s and
     be killed by docker, which reports red *by timeout* — no 503, no log line,
     nothing for the runbook's two-cause table to read.
     `tests/test_compose_topology.py` asserts `ops × ceiling < timeout`, because
     comparing one knob to the timeout certifies the bad value instead of
     forbidding it.
   - **`lib_name`/`lib_version` off**, which switches off redis-py's two
     `CLIENT SETINFO` round trips per connect — pure overhead for a probe, and
     two more timed operations inside the tightest part of the budget.
   - **`max_connections=1`**, so a burst cannot grow the pool one connection per
     in-flight request.
   - **The verdict, success *and* failure, is memoized for 2s** (`<` the
     healthcheck's `interval: 10s`, asserted against compose). Without it, N
     concurrent callers each hold an anyio threadpool worker for the full probe
     budget against a slow store, and sync routes — `/login` included — queue
     behind them. Memoizing only successes would leave exactly the expensive case
     unbounded. Verified live: 10 rapid `/healthz` calls produce **1** Redis PING.
   - **What is logged is the exception class plus a Redis error code from a closed
     allowlist** (`ERR`, `WRONGPASS`, `NOAUTH`, `OOM`…), never `str(exc)` — an
     AuthenticationError message can quote the credential that was sent. A
     catalog rather than a "looks like a code" shape test, for the reason PR #7's
     member-id prefix catalog exists. The code is what distinguishes a store that
     is *down* from one started **without** `--requirepass` (`ERR Client sent
     AUTH, but no password is set`) — a green-to-the-eye Redis holding sessions
     on an open port.
2. **`visit_memory_save()` reports whether the write landed, and the route stops
   handing out visit ids that resolve to nothing.** The swallow itself was right
   — a turn that has been answered and paid for is not failed over a lost write —
   but returning `None` either way meant the response still carried a `visit_id`
   for a record that was never stored, so the clerk's next message answered 404
   "visit not found" with nothing logged. The helper now returns a bool and the
   route reports one of three states, because whether the id is still usable
   depends on which turn this is:

   | state | when | `visit_id` |
   |-------|------|-----------|
   | `ok` | the write landed | the visit |
   | `stale` | the write failed on a **later** turn — the record was loaded at the top of this request, so it is still in Redis and still loadable; only this turn's append was lost | the visit |
   | `unavailable` | the write failed on the **first** turn — the id was minted here and nothing was stored, so it resolves to nothing | `null` |

   The `stale` case is the one a blanket "null the id on any failed write" gets
   wrong: it would discard retrievable context, and under a *persistent* write
   fault (Redis at `maxmemory` with `noeviction`) it would do so on every turn,
   resetting the conversation per message rather than degrading once. Both failure
   states log (no identifier — visit ids are opaque, the facts behind them are
   not). The field is additive on a contract with no client yet (`frontend/` does
   not call this endpoint), so nothing downstream breaks.

## Round 3 corrections (2026-07-27)

Adversarial review round 3 on PR #14 rejected deferred gap 6 rather than the code
that implemented it, and it was right to.

1. **No LLM failure may discard a completed eligibility result (§7 rewritten).**
   The original mapping raised **503** on `LLMConfigError` / `LLMBudgetExceeded`
   so the gateway would refund the reservation. But the eligibility lookup runs
   *before* the model call: by the time that 503 was raised, an outbound
   PHI-bearing payer call had already been made and its verdict written into
   `facts.last_eligibility`. Raising discarded all of it — the gateway got an
   error, never persisted the visit, and the clerk saw a failure instead of the
   coverage answer that had just been obtained on their behalf. Under a
   *persistent* Bedrock misconfiguration (a blank credential, an unpriced model,
   an exhausted local cap) this repeats: every retry spends another payer call
   and returns nothing.

   The ADR accepted this on the argument that "answering 200 for a call that
   never happened would keep a charge the tenant did not incur." That constraint
   was self-imposed. It only holds while the HTTP status is the *only* channel
   carrying the spend verdict. `VisitChatResponse.llm_egress` gives it its own
   channel, and the two facts — *did the turn succeed* and *were we billed* —
   stop having to share one number. `_reply_items` now returns
   `(items, llm_egress)`, every LLM branch degrades to the deterministic
   selection, and `proxy_visit_chat` refunds on `llm_egress is False`. Accounting
   is strictly more accurate than before, not less: local refusals refund exactly
   as they did, and the clerk keeps the verdict.

   The general lesson, and the reason this is worth recording: **an "accepted
   tradeoff" is only accepted if the constraint that forces it is real.** This one
   was an artifact of an encoding choice one layer down.

2. **The member-id recogniser reads what a human types.** `config.py` upper-cases
   the catalog and `_build_insurance_id_re` compiled without `re.IGNORECASE`, so
   `aetn1224` matched nothing: no lookup ran and the assistant asked the clerk for
   the id they had just supplied. The pattern is now case-insensitive and
   `_extract_insurance_ids` folds each match to upper case *before*
   de-duplicating, so "AETN1224 — sorry, aetn1224" stays one candidate instead of
   tripping the ambiguity branch. `VisitFacts.insurance_id` folds at the schema
   boundary too, because the contradiction rule compares a new id against the
   stored one — case-folding only the message would have made every case variant
   look like a different subject and stranded the visit in "confirm which member
   ID" forever.

   This does not widen the catalog: the recognised token set is the same payer
   prefixes, case-folded. The round-1 property still holds — a miss is safe, a
   wrong match is not — and `test_case_folding_does_not_widen_the_catalog` pins
   it.

## Round 4 corrections (2026-07-27)

Adversarial review round 4 on PR #14 found one finding, and — like round 3 — it
was a rejection of a *deferred gap* rather than of the code implementing it. The
ADR's own text (gap 6) was cited as the evidence, which is the argument for
writing these gaps down honestly.

1. **A repeat of the member id no longer re-spends a payer call (gap 6's second
   symptom, CLOSED).** `_derive_intent` routed *every* message containing a
   member id to `check_eligibility`, so a clerk restating or re-pasting the id
   they had just supplied — ordinary front-desk behaviour — spent another
   PHI-bearing payer lookup each turn, while the answer sat unread in
   `facts.last_eligibility`. The breaker and the per-user chat quota *bounded*
   that; they did not stop it, because the expensive path was the **default** for
   a common input. Both bounds are also global, so the cost showed up as everyone
   else's degraded service rather than as anything attributable to the repeat.

   A repeat of the id **on file** now routes to `ask_status` — answered from the
   stored verdict, stamped with its `checked_at`, no egress — while that verdict
   is *reusable*. `AI_ELIGIBILITY_REUSE_SECONDS` (default 300s, clamped to
   0–1800s) is the window; 0 disables reuse and restores "always call the payer",
   and the ceiling is the visit's own retention window, because reuse must never
   outlive the record holding the verdict.

   Reusable is deliberately narrow, and each clause is a test
   (`tests/test_ai_visit_chat.py`):

   - **definitive only.** `active` is exactly `True`/`False` *and* `status`
     agrees. A degraded `unknown`/`pending` is re-checked however fresh it is —
     that is what keeps gap 7 intact — and `{"status": "active", "active": null}`
     is the r5 covered-by-mistake shape arriving through the `facts` door instead
     of off the wire, so it is not reusable either.
   - **for the id on file.** A candidate that contradicts the visit's confirmed
     id is still ambiguous, however fresh the stored verdict is, and a verdict
     with no id beside it cannot answer for an id the clerk just typed.
   - **observed by us.** Freshness is measured against a new `observed_at` field
     stamped by `eligibility_client` from *this* service's clock, never against
     `checked_at`. `checked_at` is downstream **content** — from another host's
     clock, and a value this module otherwise refuses to trust for anything that
     controls behaviour — so skew or a crafted body could silently extend the
     window. `checked_at` remains what a clerk reads. Absent, non-string,
     unparseable, timezone-naive, and future stamps are all "not fresh", which
     costs one payer call rather than a stale answer; that is also what makes a
     rolling deploy safe, since verdicts written before this change simply are
     not reusable.
   - **overridable.** An explicit retry request re-checks regardless of
     freshness, tested *before* the window.

   A repeat runs the **same keyword ladder** as a turn with no id in it — retry,
   then question-about-the-past, then request-a-check — so repeating the id cannot
   change what a turn *means*, and freshness decides only the turn the ladder does
   not classify: the bare restatement ("member AETN1224"), which is what "clerks
   restate or re-paste the id" actually looks like. Two consequences are
   deliberate. A question about the past never pays, even when the stored verdict
   is degraded and freshness cannot answer — the same question without the id has
   always been free, and pasting the id must not make it expensive during the very
   outage that produced the degraded verdict. And an imperative check verb
   ("verify AETN1224", "coverage changed — check AETN1224") *is* honoured against a
   fresh verdict: this is the one place the design spends rather than saves,
   because a clerk asking for a check has a reason we cannot see (a new card for
   the same member id being the concrete one), and freshness must not become a
   cache they cannot get past.

3. **A failed re-check no longer destroys a confirmed verdict.** Found by the
   pre-push adversarial pass on the round-4 fix, and pre-existing rather than new:
   the lookup's result was written into `facts.last_eligibility` unconditionally,
   and the gateway persists exactly that. So one degraded re-check during a payer
   outage erased the only copy of a definitive ACTIVE — the reply flipped to
   "could not confirm" for a patient the payer had confirmed, and because a
   degraded verdict is not reusable, every later turn re-paid for a lookup that
   could not succeed while the circuit was open. `_remembered_verdict` now keeps
   the definitive observation when a re-check for the *same* member id comes back
   degraded. The turn still reports the degraded outcome — the reply is rendered
   from the fresh dict — so nothing restates the old answer as current; what
   survives is the visit's memory of the last real observation, with its own
   stamp. A new *definitive* answer always wins, including a change of answer, and
   a verdict with no id beside it is not inherited by a newly supplied id.

4. **The reply's timestamp no longer depends on downstream supplying one.**
   `verdict_line` rendered `(checked …)` only from `checked_at`, which is
   downstream content — and `_query` accepts any shaped 2xx, so a verdict can
   arrive with no timestamp at all. That dropped the parenthetical entirely, and a
   reused five-minute-old verdict then read as an unqualified present-tense
   coverage assertion, breaking §5's promise on exactly the path reuse makes
   common. The stamp now falls back to `observed_at`, which this service always
   writes.

5. **Two accounting/pinning gaps closed with it.** `visit_chat_log_metadata`
   gained a non-PHI `checked` boolean, because `ask_status` stopped implying
   "no payer call" once a fresh verdict could answer a repeated id — two
   materially different turns (a question answered from memory, a re-verification
   declined as unnecessary) otherwise logged identically, which is not good enough
   while D2/D12 are open. And `tests/test_eligibility_budget_alignment.py` now
   pins ai-assistant's reuse ceiling against the gateway's
   `AI_VISIT_TTL_SECONDS`, for both code defaults and `.env.example`: the ceiling
   is a hardcoded mirror of another service's default, and an unpinned mirror is
   the stale-copy failure that file exists to prevent.

2. **The retry keyword list became a control, so it had to cover the phrasing.**
   Before the window existed, a retry phrasing the keyword list missed was
   harmless: the id in the message re-checked anyway. With reuse in place, a
   missed phrasing is *absorbed* by the window and the clerk has no way to force
   a lookup — the same dead-control failure PR #11 r6 shipped in latency-threshold
   form (a bound the values could never reach). The
   substring list missed exactly the forms where the id sits between the verb and
   the adverb ("check AETN1224 again", "run that again"), so it is now a list
   *plus* a `\b(check|run|verify|try)\b.*\bagain\b` pattern. A question about the
   past ("what was the status of AETN1224 again?") deliberately does **not**
   match: widening to the bare adverb would flip every status question into a
   lookup, and during an outage a spurious re-check can turn a confirmed ACTIVE
   into "could not confirm".

## Round 5 corrections (2026-07-27)

Adversarial review round 5 on PR #14 found one finding, and it is the same shape
as round 4's: an expensive call on the path a common input makes the default.

1. **A turn where the model has no choice no longer buys a model call.**
   `_reply_items` consulted Bedrock on every turn. For the two no-lookup
   pseudo-statuses (`awaiting_id`, `ambiguous_id`) `allowed_selection` returns
   exactly `default_selection` — round 1 removed the "neutral" optional ids there,
   because "record the coverage result" presupposes a result — so the selection
   gate could only ever accept the one selection the deterministic default already
   renders. The request bought nothing: same reply, every time, at the price of a
   vendor request and a slot of ADR 0007's shared daily ceiling.

   That is not merely wasteful, it is the cheapest waste in the feature to
   provoke. The turns with no freedom are exactly the turns that need no member
   id — "can you check this patient's coverage?" repeated — so one clerk, or one
   never-expiring session (CLAUDE.md §6, D10), walks the *global* counter to its
   cap and the visible symptom is everyone else's AI features going dark. The
   per-user chat quota bounds the rate, not the direction.

   `_reply_items` now returns the deterministic render directly when
   `allowed_selection(status) - set(default_selection(status))` is empty, with
   `llm_egress=False` so `proxy_visit_chat` refunds the slot it reserved before
   the call that never happened (§7's flag doing exactly the job it was added
   for), and `degraded=False`, because this is the designed path for those
   statuses and health must not start firing on a saving.

   The condition is derived from the two sets, **not** tested against
   `NO_LOOKUP_STATUSES`. The property that matters is "the model has no freedom
   here", so a future status whose optional ids are narrowed away inherits the
   short-circuit instead of quietly re-introducing the spend. Tested as an
   invariant across every reachable status — a vendor request happens *if and only
   if* the status justifies an id the default does not already contain — so the
   short-circuit cannot silently widen to statuses where the model does have
   something to add.

   The mirror endpoint does not have this hole: `templates.OPTIONAL_IDS`
   (`billing_questions`, `save_clinic_number`) is disjoint from every
   `default_selection` a request shape can produce, so `/intake-instructions`
   always leaves the model a real choice.

   A second benefit was not the motivation but is worth recording against D13:
   an `ambiguous_id` turn no longer crosses the vendor boundary at all, so the
   turn class most likely to contain a clerk fumbling with several ids is now
   one the vendor never sees any derivative of.

2. **The admission slot is still spent on a free turn (accepted gap, found by
   the pre-push adversarial pass).** The fix above is on the refund side only.
   `_reserve_ai_budget` runs in the gateway *before* the fan-out, and whether a
   turn needs the vendor is derived downstream from the message, the visit's
   facts, and the payer's answer — so admission cannot know. A no-lookup turn
   therefore reserves a slot and gets it back milliseconds later, and while the
   ceiling is exhausted it is refused with 429 even though answering it would
   have cost nothing. Because a first turn has no member id, `awaiting_id` is
   the entry point of *every* visit: at the ceiling, the feature cannot be
   started, only continued.

   Accepted rather than fixed, and the alternatives are why. Reserving *after*
   the fan-out inverts the control — the ceiling exists to bound egress, and a
   ceiling checked after the request has gone is not one. Telling ai-assistant
   "the budget is exhausted, answer only if free" moves a spend decision into
   the service that is supposed to be stateless about spend, and hands a caller
   a flag that changes what the endpoint will do. Deriving the status in the
   gateway duplicates `_derive_intent` across a service boundary, which is the
   cross-layer duplication §1 of this ADR exists to avoid. The residual is a
   *fail-closed availability* cost on an exhausted ceiling, which is the safe
   direction; the counter itself stays accurate at rest. `_reserve_ai_budget`'s
   docstring, which claimed the counter tracks only genuinely paid fan-outs, was
   corrected rather than left to read as an invariant this change had broken.

3. **The saving is logged, because it is an accounting event with no other
   witness.** Skipping the vendor makes reserve-then-refund the *common* path
   rather than a rare failure branch, and the refund side is silent by
   construction (`_refund_ai_budget` logs only when the Redis release fails).
   Nothing else in either service distinguishes a 200 that paid from a 200 that
   did not, so a double-credit — a retry, or a later refactor — would walk the
   shared counter downward with no evidence before the vendor invoice. The
   short-circuit now emits one allowlisted metadata line
   (`eligibility_status`, `model_consulted`), same D1 discipline as the request
   line. This is the round-1 "a control with no observable signal reads as a
   green dashboard" lesson, applied to a saving rather than to a guard.

## Round 6 corrections (2026-07-27)

Adversarial review round 6 found one finding, and it is the trust boundary the
previous five rounds kept circling from the other side: what ai-assistant may
believe about eligibility-service's answer (rounds 3–5) applies equally to what
the gateway may believe about ai-assistant's.

1. **A malformed downstream 200 could erase the visit's only copy of the payer
   verdict.** `_post_checked` proves one thing — a non-error status with a JSON
   body. It cannot prove the body came from our renderer. `proxy_visit_chat`
   then trusted it: `result.get("facts") or {}` was written straight into the
   visit record, so a 200 missing `facts` — a misroute, an intermediary, a
   rolling deploy serving an older or newer shape — wrote `{}` over a confirmed
   `insurance_id` and the stored verdict. Those live nowhere else, so the next
   turn asked the patient for an id they had already produced and re-spent a
   PHI-bearing payer call to answer a question already answered. `reply` had the
   same shape of hole, coerced to `""`, handing the clerk a blank turn with a
   200.

   `_VisitChatDownstream` now validates the body before anything is refunded,
   answered, or written, and an invalid one is a **502 with the visit record
   untouched** — so a retry resumes the conversation rather than restarting it.
   Nothing is refunded on that path: an unparseable body says nothing about
   whether Bedrock was called, and over-counting toward the ADR 0007 ceiling is
   the safe direction. Neither the body nor the parse error is logged, only the
   field NAMES that failed, which are ours; a `reply` legitimately carries a
   payer name and a coverage verdict, and the premise of the whole branch is
   that we do not know what produced the rest.

   Four choices inside it are load-bearing:

   - **`facts`' two fields are required and nullable.** A `response_model`
     serialisation always carries both keys, explicitly null when unset, so `{}`
     is not "an empty visit" — it is drift, and reading it as state is the
     erasure itself. A partial `{"insurance_id": …}` erases `last_eligibility`
     just as effectively, so neither key may be optional here even though both
     are optional at ai-assistant's end.
   - **`extra="ignore"`, deliberately asymmetric with `VisitFacts`' own
     `extra="forbid"`.** Forbidding would 502 every turn of a rolling deploy in
     which a newer ai-assistant adds a fact. Passing an unknown key *through* is
     worse than dropping it: the gateway echoes stored facts back on the next
     turn, and ai-assistant's `forbid` would 422 that turn and every one after
     it — a visit bricked until its TTL. Dropping costs the new field for the
     length of the deploy and nothing after. It is logged (a count, never keys),
     because a silently dropped fact is a feature quietly not working.
   - **`intent`/`status` are constrained by SHAPE, not by a copy of the enums.**
     `^[a-z_]{1,32}$` cannot go stale when a new intent is added, and free text a
     clerk typed cannot satisfy it — which is the property the metadata-only
     transcript's no-PHI-at-rest guarantee actually needs. A duplicated enum
     would have been a second unpinned mirror of another service's constants,
     the exact failure round 4 had to fix in `test_eligibility_budget_alignment.py`.
   - **`llm_egress` and `assistant` are deliberately NOT validated**, against the
     reviewer's recommendation. Both are our own accounting and health
     reporting, and both already degrade conservatively: an ambiguous spend flag
     keeps the charge (`is False` and nothing else refunds), an unrecognised
     health value reads `unknown`. Failing a turn over either would discard a
     coverage verdict a payer call already paid for — the mistake round 3
     existed to fix — and the existing tests that pin `["false", 0, "", "no"]` to
     *200 plus keep-the-charge* encode that decision. A field that can neither
     corrupt state nor mislead a clerk is not worth a 502. `eligibility` is in
     that same category — answer-only, never persisted, and the verdict it
     reports is already in `reply` as server-rendered text — so it is validated
     but degrades to null rather than failing the turn.

2. **Mirroring a field name is not mirroring its constraint (found by the
   pre-push pass, on the fix above).** The first cut declared
   `insurance_id: Optional[str]` and called itself a mirror of `VisitFacts`. It
   was not: `VisitFacts` carries a validator that upper-cases and rejects
   non-ASCII, and its docstring says why — a stored id is used *directly* for a
   payer lookup on a later turn, without passing back through the recogniser. So
   the first cut closed the unknown-KEY door on `facts` and left the
   invalid-VALUE door open on the same field, with a worse outcome than the bug
   it was fixing: `AETN1224K` (U+212A, which survives `.upper()`) would have been
   persisted, then 422'd by ai-assistant on *every* later turn, and since the 422
   path never writes, nothing repairs the record — the visit is dead until its
   TTL. The mirror now carries a shape (`^[A-Z0-9-]+$`, ≤64) that accepts every
   id the recogniser can produce and nothing a human typed.

3. **The two unbounded fields were the persisted one and the echoed one.** Every
   scalar got a bound in the first cut; `last_eligibility` and `eligibility`
   stayed bare `dict`. That is an unbounded `SET visit:<id> … EX ttl` into the
   store that also holds **sessions** — the request side of this feature is
   bounded (`ai_visit_max_message_chars`, `ai_visit_max_turns`) and the response
   side was not, which is the asymmetry that matters under the very threat model
   the round was addressing. It was also a PHI hole: `VisitFacts`' `extra="forbid"`
   closes the fact KEYS, but a name nested inside an unvalidated verdict was
   persisted at rest regardless, and `tests/test_visit_chat_phi.py` structurally
   cannot catch that because it drives the one renderer guaranteed not to do it.

   `_VisitChatVerdict` now closes the verdict at the boundary, declaring exactly
   the keys something reads — `active`/`status` decide reuse, `payer`/
   `checked_at`/`observed_at` are rendered or measured — and dropping the rest.
   `raw_status` and `reason` are written by `eligibility_client` and read by
   nothing, so they stop being carried into a PHI store; that is the same
   projection rule that already keeps the downstream `error` string out. Every
   field is optional, because a verdict legitimately arrives without
   `observed_at` (an older ai-assistant wrote it — round 4 makes that "not
   reusable", which is the safe answer) and failing a turn over it would be
   worse than the absence the design already handles.

4. **The un-refunded 502 needed attribution, not a refund.** Under a version skew
   every turn takes the reject branch, so the shared daily ceiling drains at full
   rate and the operator symptom is `/ai/intake-instructions` 429-ing for the
   rest of the day with no visible cause. Refunding on the body's own
   `llm_egress` was rejected: a body we refuse to parse cannot be trusted about
   our spend either. The error line now names the kept charge explicitly, so the
   drain is attributable in the logs even though it is deliberate.

## Round 7 corrections (2026-07-27)

Adversarial review round 7 found two findings. Both are the same mistake in
different clothing: a control copied from a neighbouring path kept the
neighbour's failure policy, when this path's failure had a different cost.

1. **The per-visit lock failed OPEN, on the exact state it exists to protect.**
   `visit_lock_acquire` was written as the ADR-0007 single-flight pattern
   re-keyed to a visit, and it inherited single-flight's Redis-fault behaviour —
   hand back a synthetic token and continue — with the same justification copied
   into its docstring. That justification does not transfer. Single-flight only
   dedupes *paid* work and sits in front of the fail-CLOSED budget ceiling, so
   failing it open costs at most one duplicate call. This lock is the only guard
   on the visit record, and nothing sits behind it: two turns that both believe
   they hold it read the same record, both fan out to a PHI-bearing payer
   lookup, and whichever save lands second silently drops the other's appended
   turns and facts — the confirmed member id and the payer verdict, which live
   nowhere else. A double-click or a client retry is enough.

   It was also wrong to assume the fault that broke the lock had already stopped
   the damaging write. The realistic shape is Redis at `maxmemory` with
   `noeviction`: `GET` succeeds — so the record loads and ownership *is*
   verified — while every `SET` fails. A blip that clears between the lock and
   the save leaves both writers live.

   `visit_lock_acquire` now raises a typed `VisitLockUnavailable` on a Redis
   fault, and the **route** decides, because it is the only caller that knows
   which turn this is:

   - **existing visit → 503**, record untouched, so a retry resumes the
     conversation. 503 and not 429, because nothing is processing this visit —
     our guard is down. It is raised before `_reserve_ai_budget`, so there is no
     spend to refund and a store fault cannot walk the shared ceiling.
   - **first turn → proceed unlocked.** The id was minted microseconds earlier
     inside that request and no client has ever seen it, so there is nothing to
     serialise against; failing closed there would turn a blip into an outage
     for new visits and buy no state safety. Logged at warning, since the guard
     is absent even though the turn is safe.

   The asymmetry is the design, so it is pinned in both directions: the
   fail-closed tests are red against the returned-token version, and the
   first-turn test is red against an unconditional fail-closed route.

2. **The gateway accepted member ids the recogniser could never have produced.**
   Round 6 closed the unknown-KEY door and the invalid-VALUE door on
   `facts.insurance_id` — but only as far as ai-assistant's *storage* validator
   (upper-case, ASCII). The recogniser is stricter than that by design: it
   matches a **closed payer-prefix catalog**, because a false positive is not
   safe (eligibility-service maps a payer 404 onto a definitive `active: false`,
   §5). An upper-case shape check accepted `ABC1234`, the gateway persisted it,
   and ai-assistant then uses a *stored* `VisitFacts.insurance_id` directly for a
   `recheck` lookup **without** passing back through `_extract_insurance_ids` —
   so the catalog control was bypassed and a token nobody recognised could come
   back as a confident "no active coverage".

   The gateway now validates a persisted id against the catalog itself
   (`AI_MEMBER_ID_PREFIXES`, the same env var and default ai-assistant reads),
   as a full match with no `IGNORECASE` and with `re.ASCII` — the single
   canonical form the recogniser emits, and nothing else. A hyphen is no longer
   accepted either; the recogniser cannot emit one.

   Two consequences accepted deliberately:

   - **A second copy of a default is a mirror**, which is the round-4 failure if
     left unpinned. Three controls hold it: `test_eligibility_budget_alignment.py`
     asserts the two defaults are equal, `test_compose_topology.py` asserts
     neither service pins the var in its own `environment:` block (so an
     operator override lands in the shared `.env` and reaches both ends at
     once), and both services read that shared file. `.env.example` deliberately
     does **not** set the var — a third copy of the value would be a third thing
     to keep in sync.
   - **A gateway that has not learned a prefix ai-assistant knows 502s that
     turn**, record untouched, and the turn succeeds once the config matches.
     That is the fail-closed direction for a value that is used on a payer call,
     and it is a louder failure than persisting an id whose subject we cannot
     attribute.

   An **empty** catalog at the gateway refuses `/ai/visit-chat` with 503 —
   mirroring ai-assistant's `_require_member_id_catalog`, and for the same reason
   the empty catalog is not clamped to a default anywhere: joining zero prefixes
   yields `^(?:)\d{3,9}$`, which accepts any run of digits. There is no safest
   catalog, only no catalog, and that state has to be loud.

   **What a skew costs, traced rather than asserted.** The 502 takes round 6's
   keep-the-charge path, so a catalogued-prefix skew *spends*: five turns at a
   `AI_RATE_LIMIT_GLOBAL_PER_DAY` of 5 exhaust the tenant's shared daily AI
   ceiling and `/ai/intake-instructions` then 429s for the rest of the day.
   Keeping the charge is still right — ai-assistant ran the whole turn, so a
   Bedrock call really did happen, and refunding real spend is the r3/r5 mistake —
   but the exposure is worth stating plainly, because two ordinary ops actions
   open it: both services compile the catalog **at import**, so onboarding a payer
   prefix leaves a skew window until both containers have restarted, and
   *removing* a prefix makes every in-flight visit holding such an id 502 on every
   turn until its `AI_VISIT_TTL_SECONDS` expires the record. The r6 error line
   names the failing field (`facts`) and the kept charge, so the drain is
   attributable in the logs; there is no cheaper mitigation that does not either
   erase a confirmed id or persist one whose subject we cannot attribute. Roll a
   catalog change with both services restarted together.

### Pre-push review of the round-7 fix (four findings, all closed here)

The adversarial pass on our own fix found four, and the first was a **regression
introduced by the fix**, which is the reason that pass exists:

1. **Raising the lock error threw the token away.** The pre-fix fail-open path
   returned the token it had just sent, so the route's `finally` compare-and-delete
   cleaned up whenever the `SET` had actually landed. The first cut of this fix
   raised without it — and "the write did not land" is only one of the two faults
   here. A reset connection, a read timeout, or a failover can leave the `SET`
   **applied** with its reply lost, and the orphaned key then wedges the visit for
   the whole 75s lock TTL: every retry answers 429 "already processing" against a
   lock nobody holds, which falsifies the 503's own promise that a retry resumes
   the conversation. `VisitLockUnavailable` now carries the token, the existing-visit
   branch releases it before the 503, and the first-turn branch carries it into the
   `finally`. Compare-and-delete makes that safe in both cases: it clears the key
   only if our own write is what landed.
2. **`re.ASCII` does not make a non-ASCII PREFIX safe.** The flag constrains `\d`
   and `\b`; a literal `MÉDI` in an operator catalog still matches `MÉDI1224`, a
   value the *old* shape check rejected — so on that config the fix was a strict
   widening, and ai-assistant's `VisitFacts` rejects non-ASCII, so the stored id
   would 422 every later turn until the TTL. The validator now carries the same
   explicit ASCII belt `_extract_insurance_ids` does.
3. **The catalog guard ran before body validation**, so during a misconfiguration
   every malformed request was reported as `503 assistant is not configured`
   instead of the no-echo 422. A client error costs nothing to reject and should be
   named as the client's; the guard moved after validation.
4. **Two of the new pins could not fail on the drift they claimed to catch.** The
   catalog tuples being equal says nothing about the `\d{3,9}` bound each service
   compiles around them — widen one side and the recogniser emits an id the other
   502s, with every test green. And the compose pin checked per-service
   `environment:` blocks while compose also lets a *scoped* `env_file` override the
   shared one (the gateway loads `.env.redis`, ai-assistant does not). Added: a
   source pin on the digit bound at both ends, explicit boundary cases (2/3/9/10)
   on the gateway pattern, and a template pin that no `.env.*.example` may set the
   catalog. A fifth, smaller one: an `assert MEMBER_ID not in caplog.text` on the
   lock path could not fail — no log statement there has the facts in scope — and
   was removed rather than kept as decoration.

## Consequences

- **New endpoints.** `POST /ai/visit-chat` on the gateway
  (`{visit_id?, message}` → `{visit_id, visit_memory, reply, disclaimer,
  eligibility?}`, where `visit_memory` is `ok` / `stale` / `unavailable` and
  `visit_id` is null in the last of those — see Round 2 corrections) and
  `POST /visit-chat` on ai-assistant (`{message, turns, facts}` →
  `{reply, intent, status, facts, eligibility?, disclaimer, llm_egress}`,
  internal-auth only, no `visit_id`; `intent`/`status` are echoed so the gateway
  can record a metadata-only turn without handling the clerk's text again, and
  `llm_egress` carries the spend verdict the status code can no longer imply —
  see Round 3 corrections. It is consumed by the gateway and not forwarded to
  the portal).
  Both additive; no existing contract changes.
- **New files.** `services/ai-assistant/eligibility_client.py`,
  `services/ai-assistant/breaker.py` (copy of the ADR-0010 pattern), and
  `services/ai-assistant/visit_templates.py`. No gateway `redaction.py` copy —
  the metadata-only transcript left it with nothing to redact.
- **Changed files.** `ai-assistant/app.py` (the endpoint, intent derivation,
  selection gate, catalog rendering, metadata-only chat log), `ai-assistant/schemas.py`
  (`VisitChatRequest`/`VisitChatResponse`, the metadata-only `VisitTurn`, the closed
  `VisitReplyPlan` output model, a chat `log_metadata`), `ai-assistant/config.py`
  (eligibility URL, timeout, breaker knobs, latency thresholds, turn/char caps),
  `gateway/security.py` (visit-memory helpers, visit lock, namespaced rate limit),
  `gateway/app.py` (the new route),
  `gateway/config.py` (chat rate knobs, visit TTL/turns/char cap),
  `docker-compose.yml` (`ELIGIBILITY_URL` for ai-assistant), `.env.example`,
  `docs/phi-logging-policy.md` (chat free-text + visit-memory rules).
- **New config, all non-secret and documented in `.env.example`:**
  `AI_VISIT_TTL_SECONDS` (1800), `AI_VISIT_MAX_TURNS` (12),
  `AI_VISIT_MAX_MESSAGE_CHARS` (1000), `AI_CHAT_RATE_LIMIT_PER_MINUTE` (20),
  `AI_CHAT_RATE_LIMIT_PER_DAY` (400), `AI_ELIGIBILITY_TIMEOUT_SECONDS`,
  `AI_ELIGIBILITY_BREAKER_FAIL_THRESHOLD`, `AI_ELIGIBILITY_BREAKER_RESET_SECONDS`.
  Defaults are engineering starting points; the rate and TTL numbers are an
  ops/compliance call (retention of a PHI-bearing transcript) pending review.
- **Tests** (`tests/`, run in the python:3.12 container; every regression test
  proven RED against pre-change code first): `test_ai_visit_chat.py` (turn flow,
  intent derivation, the selection gate falling back, error-status mapping,
  post-egress degradation to 200), `test_visit_memory.py` (round-trip, atomic
  set+TTL, sliding refresh, turn eviction, owner binding → 404, load-fault →
  fresh visit), `test_visit_chat_phi.py` (**adversarial**, per CLAUDE.md §5:
  member id / name / SSN planted in free text → nothing raw in any log, no PHI in
  the prompt sent to the wrapper, opaque key, error string never persisted,
  no cross-visit read), `test_gateway_ai_chat_controls.py` (rate limit before
  fan-out and in its own namespace, shared ceiling reserve/refund, no cache
  consulted, per-visit lock serialization, fail-closed on counter faults),
  `test_ai_eligibility_client.py` (timeout bound, breaker opens, degrades to
  `unknown`, no id and no `str(e)` in logs).
- **Human approval (CLAUDE.md §6/§7).** Decided with the engagement lead on
  2026-07-26: (a) **PHI at rest in Redis is approved** for `facts.insurance_id`
  under the §3 mitigations — the no-store fallback in Alternatives is not taken;
  (b) the Redis hardening is **flagged, not bundled** (gap 2 / debt-log D3b) —
  **superseded 2026-07-27**: after adversarial round 1 named the unauthenticated
  host-published store the blocker, the lead approved bundling the hardening into
  this PR (no host port, `requirepass`, scoped credential, gateway-side
  fail-closed guard). This is a §6 change to the session store, taken with
  explicit approval; no other auth behaviour moved;
  (c) replies stay **catalog-rendered** — no free text to the vendor while D13 is
  open. Still to confirm at the PR approval gate: the new API contract, the
  `docs/phi-logging-policy.md` edit, ai-assistant's new PHI-bearing outbound
  dependency, and the additive namespace parameter on the shared
  `check_ai_rate_limit`. **No auth change is proposed.**
- **`/security-review` gate applies** (PHI paths) before the PR is opened, per the
  `pr-open` skill.
