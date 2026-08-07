# W3 Requirements

> Status: AGREED 2026-08-06
> Source: engagement owner ask, 2026-08-06

## 1. Raw ask (verbatim)

> W3: CLIENT MESSAGE
> Front desk is miserable doing insurance eligibility checks — it's so much manual back-and-forth with the payer. Can you build them a little chat assistant that checks a patient's eligibility and keeps track of the visit context as they go? Heads up: eligibility 'gets slow' now and then, but it usually sorts itself out. Oh — one of the front-desk leads filed a ticket about a rough morning last week; I'll forward it, probably nothing.
> — Dr. Maya Okonkwo, COO — Riverbend Community Health
>
> WHAT THEY HANDED OVER
> eligibility-service/check.py: resp = requests.get(PAYER_URL, params=...) — no timeout= argument, called inline in the request handler thread.
> Support ticket RIV-141: "Tue 9:00–9:20am the ENTIRE intake screen froze — front desk couldn't register any patient, not just eligibility."
> Payer status page PDF: "Degradation 9:02–9:21am Tuesday — 270/271 endpoint timeouts."
> p95 latency chart for /intake: flat ~600ms all week, with a single 20-minute spike past 30s Tuesday morning.
> Grep of eligibility-service: no timeout, no circuit breaker, no cache; the eligibility call sits directly on the intake request path.
>
> 🔍 QUESTIONS TO DIG INTO
> Trace what thread the payer call runs on — what else is waiting behind it when the payer is slow?
> Line up the frozen-screen ticket, the payer status PDF, and the latency spike — is it the same 20 minutes?
> If the payer is down for 20 minutes, what's the smallest blast radius you'd accept — eligibility only, or all of intake?
> What would let intake keep working through a payer outage (timeout, breaker, last-known-good cache)?
>
> CURRENT PROBLEMS (STATED / KNOWN)
> Front-desk eligibility checks are painful.
> The portal 'freezes' / is slow sometimes.
>
> THIS WEEK'S DELIVERABLE
> A single-agent eligibility assistant (one check_eligibility tool + visit-scoped memory) built on a non-blocking, timeout-bounded, circuit-breaker-guarded eligibility call + an ADR: sync→async + graceful degradation (cache last-known eligibility, let intake proceed).

## 2. Context

- **Most of the named deliverable already exists on `main`** (prior engagement; owner
  confirmed backfill run shape, see below). The bounded
  eligibility call — `(connect, read)` timeout, retry budget, in-process circuit breakers on
  both hops — is ADR 0010 / PR #11 (`services/eligibility-service/check.py` + `breaker.py`,
  `services/intake-service/breaker.py`); D4 in `docs/debt-log.md` is PARTLY CLOSED on its
  strength. The single-agent assistant — one `check_eligibility` tool, visit-scoped memory,
  grounded verdicts — is ADR 0011 (`ai-assistant` `POST /visit-chat`, gateway
  `/ai/visit-chat` at `services/gateway/app.py:938`). The handed-over evidence (no `timeout=`
  in `check.py`) describes the pre-ADR-0010 state, not current code.
- **Three named pieces were genuinely not delivered; owner ruled on each (2026-08-06):**
  1. **UI surface** — `/ai/visit-chat` has never had a screen in any portal (TODO-44,
     `docs/todo.md:67`). Owner ruled a minimal surface **in scope** — W3-REQ-9. Building it
     inherits the PHI-boundary review on `/ai/*`.
  2. **Last-known-good eligibility cache** — does not exist; degradation today reports
     `pending`/`unknown`. Owner ruled the explicit degraded status **suffices**; the cache
     is cut (§6).
  3. **"Non-blocking"** — verification still runs bounded-blocking on the `/intake` request
     thread; register-first async re-verification is ADR 0010's named open follow-up. Owner
     ruled it **remains a follow-up** (§6).
- **The forwarded ticket is already registered.** RIV-141 is D4's High ticket; the D4
  narrative already lines up the frozen screen, the payer degradation window, and the
  latency spike as one incident. The COO's "probably nothing" is scenario minimization.
- **Run shape (owner ruling, 2026-08-06):** as in W1, delivered parts (REQ-1..6, 8, 10) are
  backfill-of-record — existing artifacts verified against this document once agreed, any
  mismatch reported as a finding. Only REQ-9 is built new.
- **Separate standing defect on the same path:** registration is entirely non-functional for
  an unrelated reason (intake contract break, TODO-1, deliberately unpatched). "Intake keeps
  working through a payer outage" is scoped to the eligibility dependency, not to fixing
  TODO-1.
- **Approval-gated zones nearby** (`docs/landmines.md` §1): the pinned eligibility
  timeout/breaker values (`tests/test_eligibility_budget_alignment.py` — do not widen
  without re-reading ADR 0010); `/ai/*` as the only vendor-egress path with no BAA (D13);
  visit memory in unhardened Redis (D3b); the gateway as a load-bearing wall.

## 3. Requirements

| ID | Requirement | Notes |
|----|-------------|-------|
| W3-REQ-1 | Front desk: can ask about a patient's insurance eligibility in a chat interface and receive a coverage answer, replacing manual payer back-and-forth | today `POST /ai/visit-chat` (ADR 0011) |
| W3-REQ-2 | Front desk: the assistant retains visit context across turns within one visit; context never leaks across visits or patients | ADR 0011 visit-scoped memory; Redis exposure is D3b |
| W3-REQ-3 | System: every coverage verdict shown to the front desk originates from the payer eligibility path; the assistant never asserts coverage the payer did not return, and never converts "unknown" into a denial | ADR 0011 grounding rule; AI-output-guardrail landmine |
| W3-REQ-4 | System: every payer eligibility call completes or fails within a bounded time; no worker is held indefinitely | ⚠ human-gate adjacency — timeout/breaker values pinned (`docs/landmines.md` §1, ADR 0010) |
| W3-REQ-5 | System: a payer outage's blast radius is eligibility only — patient registration keeps working (degraded verdict, not frozen); RIV-141 cannot recur | scoped to the eligibility dependency, not TODO-1 |
| W3-REQ-6 | System: during a sustained payer outage, the system stops waiting on the payer per-request and degrades immediately until the payer recovers | today: in-process breakers, ADR 0010 |
| W3-REQ-7 | Front desk: a degraded eligibility answer is explicit — an unverified/pending status, never a false "not covered" | owner ruled `pending`/`unknown` suffices; LKG cache cut (§6) |
| W3-REQ-8 | Engineering org: an ADR records the sync→async + graceful-degradation decision and its honest limits | today ADR 0010 (+ 0011); register-first residual stays a recorded follow-up (§6) |
| W3-REQ-9 | Front desk: the chat assistant has a minimal usable surface in the portal | owner ruled in scope 2026-08-06; built new; ⚠ human-gate adjacency — `/ai/*` vendor egress, D13/D14 open |
| W3-REQ-10 | System: no PHI crosses the vendor (LLM) boundary from the chat path | ⚠ human-gate; no BAA (D13); `docs/landmines.md` §3 negative tests |

## 4. Assumptions

- The handed-over evidence describes the repo's pre-ADR-0010 state; current code controls.
  Verification checks current code against these requirements, not against the handout.
- Forwarded RIV-141 is the same incident D4 already registers and correlates; no new
  investigation is required to line up the three artifacts.
- "Single agent, one tool" bounds the assistant's shape: no additional tools or agents this
  week.
- Seeded PHI is handled as real (CLAUDE.md §0).

## 6. Out of scope

- **Last-known-good eligibility cache** — deliverable names it, owner cut it 2026-08-06:
  the explicit `pending`/`unknown` degraded status (ADR 0010) satisfies W3-REQ-7, and a
  cached verdict would put an insurance/member id in a store whose hardening is separate
  open debt (D3b).
- **Register-first async re-verification ("non-blocking")** — owner ruled it remains ADR
  0010's recorded follow-up; bounded-blocking on the request thread is the accepted state
  this week.

- **Fixing the intake contract break (TODO-1)** — registration's total failure is a separate
  deliberately-unpatched defect; this week's "intake keeps working" is about the eligibility
  dependency only.
- **Redis hardening (D3b)** — visit memory's store is known-exposed; separate debt, not a
  W3 requirement.
- **BAA / Safe-Harbor scrub** — the vendor boundary stays where ADR 0011 held it; moving it
  is W8 territory.
- **Gateway `proxy_intake` migration off `_post`** — named ADR 0010 follow-up; separate
  change on a load-bearing wall.
- **Additional agent tools or multi-agent shapes** — ask bounds it to one agent, one tool.
- **Widening pinned timeout/breaker values** — landmine; any change re-opens ADR 0010.
