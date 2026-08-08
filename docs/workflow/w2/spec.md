# W2 Spec (EARS)

> Status: AGREED 2026-08-07 (frozen)
> Source: docs/workflow/w2/requirements.md (AGREED 2026-08-07)
>
> W2-REQ-7 (and the measurement half of W2-REQ-3) are backfill of record: statements are
> derived from the requirements alone, and whether the existing `main` artifacts satisfy
> them is established at the verification step after agreement — a miss there is a finding,
> not a spec change. Everything else is new build against this contract.
>
> "Candidate-duplicate cluster", "ambiguous", and "non-mergeable" are used throughout with
> the ADR 0005 corroboration meanings, defined once as behavior in W2-SPEC-19..20.

## 1. Statements

### W2-REQ-1 — relevant records on chart open

| ID | Statement | Notes |
|----|-----------|-------|
| W2-SPEC-1 | When a clinician opens a patient chart in the portal, the portal shall present the most relevant past records for that patient's chart without the clinician navigating the full history | |
| W2-SPEC-2 | If the retrieval path fails or is unavailable, then the portal shall present a deterministic non-PHI fallback and shall still allow the chart to be opened and read | retrieval is an aid, never a gate on chart access |

### W2-REQ-2 — duplicate disclosure on the surfaced view

| ID | Statement | Notes |
|----|-----------|-------|
| W2-SPEC-3 | While the opened chart is a member of a candidate-duplicate cluster, the portal shall display a disclosure stating that sibling charts may exist and that the shown record set may be incomplete, for every role able to open that chart | owner 2026-08-07: candidate clusters only — ambiguous and non-mergeable rows show no disclosure; not clinician-conditional; ⚠ human-gate adjacency: patient identity |
| W2-SPEC-4 | The surfaced record set shall contain only records of the opened chart and shall never combine records from sibling charts into one presented set | query-time unioning is rejected (ADR 0005 alternatives); negative tests (landmines §3) |
| W2-SPEC-5 | While a disclosure is displayed, the portal shall not block, delay, or restrict access to the chart or its records, and shall not offer navigation into sibling charts | owner 2026-08-07: banner only |
| W2-SPEC-6 | The portal shall never present a chart belonging to a candidate-duplicate cluster as a complete record for that person | negative tests (landmines §3) |

### W2-REQ-3 — acceptance measured per human

| ID | Statement | Notes |
|----|-----------|-------|
| W2-SPEC-7 | The acceptance measurement shall report record completeness per candidate identity — each chart's record set compared against the union of its cluster's charts — not per chart | |
| W2-SPEC-8 | Agreement with the contractor gold-set shall never on its own be reported as evidence that a clinician sees a complete record | the gold-set is the foil, not the bar |
| W2-SPEC-9 | The contractor gold-set shall be retained unaltered as the documented foil, and the measurement shall record why passing it is insufficient | assumption §4: not deleted, not silently fixed |
| W2-SPEC-10 | When the acceptance measurement runs, it shall fail if the measured values drift from the recorded baseline | existing drift gate is the acceptance artifact; owner 2026-08-07: the W2 bar is the per-human measurement gated at today's baseline — ADR 0005's 0% candidate rate is a post-merge target, and W2 executes no merges |

### W2-REQ-4 — bounded AI spend

| ID | Statement | Notes |
|----|-----------|-------|
| W2-SPEC-11 | The retrieval corpus shall be bounded to a configured maximum size | client quota constraint |
| W2-SPEC-12 | The system shall compute embeddings for a given corpus content at most once and reuse the cached result across runs and requests | |
| W2-SPEC-13 | While serving a chart-open retrieval request, the system shall issue no corpus embedding computation | per-request re-embedding is the quota failure mode named in the ask |

### W2-REQ-5 — PHI stays out of logs and off unsanctioned egress

| ID | Statement | Notes |
|----|-----------|-------|
| W2-SPEC-14 | The helper's data path shall write no PHI to logs at any level, including on error paths | ⚠ human-gate (PHI); negative tests (landmines §3) |
| W2-SPEC-15 | Where the helper sends data outside the estate, it shall do so only through the sanctioned vendor-egress path | ⚠ human-gate (PHI / vendor egress, D13/D14) |
| W2-SPEC-16 | If a payload bound for a log or for vendor egress cannot be reduced to non-PHI content, then the helper shall not emit it | ⚠ human-gate; negative tests (landmines §3) |

### W2-REQ-6 — no widening of chart-read exposure

| ID | Statement | Notes |
|----|-----------|-------|
| W2-SPEC-17 | The helper shall return records only for the patient whose chart the requesting user opened | negative tests (landmines §3) |
| W2-SPEC-18 | The helper's retrieval path shall be reachable only within an authenticated session already authorized for chart reads, introducing no new capability, no new role, and no unauthenticated path | ⚠ human-gate adjacency: auth zone; D11 must not widen |

### W2-REQ-7 — findings registered with the owner

| ID | Statement | Notes |
|----|-----------|-------|
| W2-SPEC-19 | The engagement shall maintain owner-facing registry entries recording the candidate duplicate rate, the allergy-visibility safety gap, the gold-set foil, and the intake root cause, each traceable to the measurement that produced it | backfill-verify against `main` after agreement |

### W2-REQ-8 — match key at chart create

| ID | Statement | Notes |
|----|-----------|-------|
| W2-SPEC-20 | The matcher shall classify two patient rows as a candidate match only when their normalized SSNs match and their demographics corroborate — at least two of similar name, DOB with transposition tolerance, and matching address — between every pair of rows in the group | ⚠ human-gate (patient identity); ADR 0005 consequences. Owner 2026-08-07: W2 is this SSN-corroborated tier only — ADR 0005 tier 2 (fuzzy name + DOB where SSN is missing or invalid) is deferred, so a row without a usable SSN yields no candidate match in W2 |
| W2-SPEC-21 | If rows share an SSN but corroborate only through a bridge row, then the matcher shall classify them ambiguous row-by-row; if a row's demographics conflict with all of its SSN-mates, then the matcher shall classify it non-mergeable — neither class shall be reported as a candidate duplicate | corroboration is a similarity relation, not an equivalence; negative tests (landmines §3) |
| W2-SPEC-22 | When a chart is created at intake, the system shall evaluate the match key against existing patient rows | ⚠ human-gate (intake / patient identity) |
| W2-SPEC-23 | If chart creation yields a candidate match, then the system shall queue the pair for human review and the chart creation shall still complete — no registration blocked, no chart altered or merged | ⚠ human-gate; ADR 0005 decision 3 |
| W2-SPEC-24 | While evaluating the match key, the system shall create no new stored plaintext SSN copy and shall write no SSN or SSN fragment to any log | ⚠ human-gate (PHI, D3); negative tests (landmines §3) |
| W2-SPEC-32 | If match-key evaluation fails during chart creation, then the chart creation shall still complete, the evaluation failure shall be recorded, and the row shall remain eligible for a later retroactive pass | owner 2026-08-07; matching must never become a registration dependency, and a matcher outage must not leave an untraceable window of unchecked registrations |

### W2-REQ-9 — front-desk review queue

| ID | Statement | Notes |
|----|-----------|-------|
| W2-SPEC-25 | When a front-desk user opens the review queue, the portal shall list the candidate-duplicate pairs currently pending review | |
| W2-SPEC-26 | When a front-desk user dispositions a pending pair, the system shall record the disposition with the deciding user, and the pair shall no longer be listed as pending | |
| W2-SPEC-27 | Recording a disposition shall never merge, alter, or delete any patient row or record | merge execution is out of scope — manual HIM procedure |
| W2-SPEC-28 | The review queue and its disposition action shall be reachable only within an authenticated session holding the existing front-desk capability, adding no new role | ⚠ human-gate adjacency: auth zone; negative tests (landmines §3) |

### W2-REQ-10 — retroactive pass over existing rows

| ID | Statement | Notes |
|----|-----------|-------|
| W2-SPEC-29 | When the retroactive pass runs over existing patient rows, it shall queue every candidate-duplicate pair it finds for review, including the known Maria cluster | ⚠ human-gate (patient identity); ADR 0005 decision 4 |
| W2-SPEC-30 | The retroactive pass shall not create, modify, or delete any patient row or record | read-only pass, queue only |
| W2-SPEC-31 | If a pair is already queued or already dispositioned, then a repeated pass shall not queue it again | a re-run is expected operationally |

## 2. Traceability

| REQ | SPECs |
|-----|-------|
| W2-REQ-1 | W2-SPEC-1, W2-SPEC-2 |
| W2-REQ-2 | W2-SPEC-3, W2-SPEC-4, W2-SPEC-5, W2-SPEC-6 |
| W2-REQ-3 | W2-SPEC-7, W2-SPEC-8, W2-SPEC-9, W2-SPEC-10 |
| W2-REQ-4 | W2-SPEC-11, W2-SPEC-12, W2-SPEC-13 |
| W2-REQ-5 | W2-SPEC-14, W2-SPEC-15, W2-SPEC-16 |
| W2-REQ-6 | W2-SPEC-17, W2-SPEC-18 |
| W2-REQ-7 | W2-SPEC-19 |
| W2-REQ-8 | W2-SPEC-20, W2-SPEC-21, W2-SPEC-22, W2-SPEC-23, W2-SPEC-24, W2-SPEC-32 |
| W2-REQ-9 | W2-SPEC-25, W2-SPEC-26, W2-SPEC-27, W2-SPEC-28 |
| W2-REQ-10 | W2-SPEC-29, W2-SPEC-30, W2-SPEC-31 |

## 3. Owner decisions folded in (2026-08-07)

All five spec-stage questions are answered; none remain open.

| Question | Decision | Statement |
|---|---|---|
| Which charts show the disclosure? | Candidate clusters only — ambiguous and non-mergeable rows show none | W2-SPEC-3 |
| Who sees it? | Every role able to open the chart, not clinician-only | W2-SPEC-3 |
| W2 acceptance bar | Per-human measurement gated at today's baseline; 0% candidate rate is a post-merge target | W2-SPEC-10 |
| ADR 0005 tier 2 (fuzzy name + DOB) | Deferred — W2 is the SSN-corroborated tier only | W2-SPEC-20 |
| Matcher error at chart create | Creation completes, failure recorded, row stays eligible for the retroactive pass | W2-SPEC-32 |
