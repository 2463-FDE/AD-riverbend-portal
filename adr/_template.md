# ADR template

> Copy to `adr/000N-<short-slug>.md`, take the next free number, delete the guidance
> blockquotes. Numbers are allocated once and never reused; a reversed decision gets a
> **new** ADR that supersedes the old one, and the old one stays with `Status: Superseded
> by ADR 00M`. Never rewrite history in place — the point of the register is that you can
> read what we believed at the time.
>
> **When an ADR is required.** Any non-trivial design decision, not just ones that ship
> code (project memory `document-design-decisions`). The test: if a future review round
> could reasonably re-open this, it needs an ADR, because the ADR is what turns
> "re-argue it" into "read it." The rule to apply: **a fix that is a decision rather than
> an edit needs a decision record to point at** — if you are about to answer a review
> finding by choosing between designs, write the ADR instead of arguing in the thread.
> Until 2026-08-06 that rule was enforced by the prior engagement's `address-review`
> design gate; that tooling is not adopted and the name is dead on `main` (`CLAUDE.md`
> §11), so **nothing enforces this automatically today** — the review round in
> `.claude/skills/implementation/` "Addressing a round" is where the judgment now sits,
> and it is a human one.
>
> **Section discipline.** Context / Decision / Consequences are mandatory. The rest are
> earned: include a section when this repo has been bitten by leaving it out, and delete
> the heading entirely when it does not apply — an empty section reads as "we checked and
> there was nothing," which is a lie if you simply skipped it.

---

# ADR 000N — <the decision, not the topic>

> Title states what was decided, not the area under discussion. "Eligibility resilience:
> bound the payer call, decouple it from intake" — not "Eligibility". A reader scanning
> `adr/` should learn the decisions without opening the files.

**Status:** Proposed | Accepted | Superseded by ADR 00M
**Date:** YYYY-MM-DD
**Author:** Riverbend engagement team
**Debt:** D<n> / RIV-<n>

> `Debt:` ties the ADR to `docs/debt-log.md` and the ticket in
> `docs/handover/jira-tickets.md`. A decision with no debt ID is either new scope — say so
> — or a gap someone forgot to register. Keep `Status: Proposed` until the code lands;
> ADR 0005 has sat at `Decision (proposed)` honestly for weeks, which is the right
> behaviour, not an oversight to tidy up.

## Context

> The forces, stated so that the decision looks inevitable by the end. Include the
> observed symptom with its evidence — the timestamps, the log line, the ticket quote,
> the measured number. ADR 0010 opens with "front desk reports registration spins for
> 4–5 seconds on every save (RIV-088), and on Tuesday 09:02–09:21 the entire intake
> screen froze", which is why nobody has re-litigated it.
>
> No solutioning here. If a sentence contains the answer, it belongs in Decision.
>
> **Cite, do not restate, the landmines.** Where `docs/landmines.md` §1 already describes the
> hazard, quote it verbatim and link it. Paraphrasing a landmine into something softer is
> how the constraint gets lost.

## Decision

> What we are doing, in enough detail that someone could implement it without asking a
> follow-up. Use numbered `###` subsections once this passes roughly 50 lines — ADR 0011
> splits into eight, and the numbers become the thing review rounds cite.
>
> State the **invariants**, not just the mechanism. "Inner timeout < outer timeout" is an
> invariant; "timeout is 3 seconds" is a value. Values drift, invariants are what a test
> can pin — and where two numbers are pinned to each other, name the test that enforces
> it (`tests/test_eligibility_budget_alignment.py` is the standing example). Every knob a
> reader might widen later needs the reason it cannot be widened alone, or someone will
> widen it alone.
>
> For anything fail-closed, say what the failure **looks like from outside**: what the
> health endpoint reports, what a caller receives, what shows on a dashboard. A guard that
> raises with no handler and no health signal presents as a green dashboard over a dead
> service (project memory `fail-closed-guards-must-be-observable`).

## Alternatives considered

> One subsection or row per alternative: what it was, and the specific reason it lost.
> "Rejected — more complex" is not a reason and will not survive a review round; "rejected
> — the retry budget multiplies with the breaker's half-open probe, so an outage costs
> `workers × 3` slow calls instead of bounding them" is.
>
> Include the alternative you actually liked. An ADR that only lists strawmen tells a
> future reader nothing about the real tradeoff space.
>
> Where the choice was between technologies, judge them **strictly against the criteria
> stated in the spec or by the requester** — not on general merit or personal preference,
> which has already had to be walked back once here. If the criteria are missing, that is
> an open decision, not a licence to pick.

## How this serves the client and domain

> Optional, and worth it whenever the decision costs money, latency, or scope. Two lines:
> what Riverbend gets (cost ceiling, availability, audit posture) and what the clinical or
> front-desk workflow gets. This is the section that makes the ADR usable in a client
> conversation instead of only in a code review.

## Accepted tradeoffs / deferred gaps

> Numbered. Every gap this decision knowingly leaves open, each with **why it is
> acceptable now** and **what closes it**. This is the highest-value section in the file:
> it is what stops a later review round from re-reporting a known, priced gap as a fresh
> defect, and it is where an auditor's question gets answered honestly.
>
> A gap that is acceptable only until a specific event — a BAA, real PHI, a second worker
> — must name that event. Where the gap is bounded rather than closed, say what bounds it
> and what the residual exposure is (ADR 0010: breaker state is per worker, so
> `workers × 3` slow calls still land at the start of an outage).

## Consequences

> What changes because of this: new files and services, new config and its default, new
> failure modes, what future work is now easier and what is now harder. Include the
> **default a fresh deploy actually seeds** — not just the value in the example config —
> because the fresh-deploy default is the one that has shipped wrong here before (project
> memory `fail-closed-guard-test-the-default-deploy-state`).
>
> Name the tests that now hold the line, so a future reader knows which failures are
> regressions of this decision rather than new bugs.

## Future: <the trigger> — what changes

> Optional. Use when the decision is explicitly provisional on an external event (a signed
> BAA, real PHI, production traffic). List what gets revisited when it happens, so the
> revisit is a checklist rather than a re-derivation. ADRs 0006 and 0009 both carry one.

## Round N corrections (YYYY-MM-DD)

> Append-only. When an automated review round changes what this ADR says, add a section
> here rather than editing the Decision in place — the diff between what we decided and
> what survived review is the most instructive thing in the register, and ADR 0011 carries
> six rounds of it.
>
> One entry per correction: the finding, what changed, and the test that now proves it.
> Label the round with the A/B/C scheme defined in `docs/review-loop-metrics.md` §1 and
> applied by `.claude/skills/implementation/` "Addressing a round", so §4 of that file can
> be appended to without re-deriving the baseline. (The scheme predates the current
> process — it was `address-review`'s, a dead name on `main`, `CLAUDE.md` §11 — but the
> labels and the measured baseline carry over unchanged.)
