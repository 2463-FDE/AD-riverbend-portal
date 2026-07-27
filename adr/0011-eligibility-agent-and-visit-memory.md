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
   §9, `docs/specs/w8.md`): Bedrock is used on standard SaaS terms with **no BAA**.
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

### 7. Error mapping, and one deliberate divergence

Pre-egress refusals keep ADR-0007's contract: `LLMConfigError` and
`LLMBudgetExceeded` → **503** (the gateway refunds the reserved slot, since no
paid call occurred), a bad internal auth → **401**, a rejected body → **422**.

There is a known asymmetry here, raised by the adversarial review and accepted
for now: the eligibility lookup runs *before* the model call, so a pre-egress 503
discards a verdict that was already computed and does not depend on the LLM, and
each retry under a persistent Bedrock misconfiguration makes a fresh payer call.
The budget accounting stays correct (503 is refunded; no Bedrock call occurred),
and the eligibility breaker bounds the repeated payer cost. Making the turn return
the verdict anyway would mean answering 200 for a call that never happened, which
would keep a charge the tenant did not incur — so the fix is to persist the facts
before raising, and it is deferred rather than bolted on here (gap 7).

Post-egress failures (`LLMUnavailable`, `LLMResponseError`) **diverge** from
`/intake-instructions`, which returns 502. `/visit-chat` returns **200 with the
deterministic template selection**, because the thing the clerk actually needs —
the coverage verdict — was computed *before* the model call and does not depend on
it. Accounting stays correct: 200 is not in `_NON_PAID_DOWNSTREAM_STATUS`, so the
charge is kept, exactly as the 502 would have been. The honest caveat is that this
leaves two AI endpoints with different post-egress behavior; aligning
`/intake-instructions` onto the same degrade-don't-fail rule is a candidate
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
6. **A pre-egress LLM refusal discards an already-computed verdict (accepted).**
   See §7. Under a persistent Bedrock misconfiguration every retry re-runs the
   payer call for no user-visible value. Bounded by the eligibility breaker and
   the chat rate limit; the clean fix is to persist facts before raising the 503.
7. **No stale-verdict cache when the breaker is open (decided).** This answers
   `docs/specs/w3.md` open question 1: when eligibility is degraded the agent
   reports *unconfirmed* rather than serving a stale-but-usable cached verdict.
   A cached coverage answer is a financial fact with an expiry we cannot see, and
   caching it would put PHI-derived state in a shared keyspace for a marginal
   latency win. Within a visit, `last_eligibility` is reused only with its
   `checked_at`, never restated as current.

## Consequences

- **New endpoints.** `POST /ai/visit-chat` on the gateway
  (`{visit_id?, message}` → `{visit_id, reply, disclaimer, eligibility?}`) and
  `POST /visit-chat` on ai-assistant (`{message, turns, facts}` →
  `{reply, intent, status, facts, eligibility?, disclaimer}`, internal-auth only,
  no `visit_id`; `intent`/`status` are echoed so the gateway can record a
  metadata-only turn without handling the clerk's text again).
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
