# E4 Spec (EARS)

> Status: AGREED 2026-08-10 (frozen)
> Source: docs/workflow/e4/requirements.md (AGREED 2026-08-10)
>
> Frozen by owner decision 2026-08-10. Changes only by explicit human decision, never silently
> mid-loop; the drift gate and codex review both anchor here.
>
> Scope is every in-scope requirement — E4-REQ-1 … E4-REQ-10 plus E4-REQ-13 and E4-REQ-14,
> added at this stage per decision D-5. E4-REQ-11 and E4-REQ-12 are deferred to `e5`
> (requirements §4, decision D-3) and are deliberately not specced here; read the ids as a
> set, not a range.

## 1. Statements

### E4-REQ-1 — registration creates a patient record

| ID | Statement | Notes |
|----|-----------|-------|
| E4-SPEC-1 | When an operator submits a completed intake form through the portal, the system shall create a patient record from the submitted values | The defect itself (TODO-1); every field the form collects must survive the boundary |
| E4-SPEC-2 | When a registration submission carries insurance details, the system shall store an insurance coverage against the created patient | In scope, owner 2026-08-10. One of the four tabulated payload mismatches is an insurance field; a completed submission includes it |

### E4-REQ-2 — failure is visible, success is never faked

| ID | Statement | Notes |
|----|-----------|-------|
| E4-SPEC-5 | The portal shall present a registration success confirmation only when the system has confirmed that a patient record was created | The silent half. Success may not be inferred from a response the caller did not verify |
| E4-SPEC-6 | If a registration submission is rejected because of the submitted values, then the portal shall present a failure message identifying the registration as not saved and correctable at the desk | Owner 2026-08-10: the operator distinguishes a fixable form problem from an outage. Depends on E4-SPEC-14 |
| E4-SPEC-7 | If a registration submission fails because the system could not complete it, then the portal shall present a failure message identifying the registration as not saved and the failure as a system failure | Same decision, other branch. The operator must not retype a form against an outage |

### E4-REQ-3 — every collected consent is stored

| ID | Statement | Notes |
|----|-----------|-------|
| E4-SPEC-8 | When a registration submission carries consent selections, the system shall store every selected consent against the created patient | ⚠ human-gate — widens a documented PHI control; `docs/landmines.md` §3 negative tests. Consent storage is re-proved, not assumed inert |
| E4-SPEC-9 | The set of consent kinds the intake form offers and the set the intake service accepts shall be identical | ⚠ human-gate; landmines §3 negative tests. The equality is the contract — neither side is authoritative alone |
| E4-SPEC-10 | If a registration submission carries a consent kind the intake service does not accept, then the service shall reject the submission rather than discard that consent | ⚠ human-gate; landmines §3 negative tests. Silent discard of a consent is the failure mode this requirement exists for. Reject-the-whole-submission confirmed by owner 2026-08-10 |

### E4-REQ-4 — a downstream failure reaches the caller as a failure

| ID | Statement | Notes |
|----|-----------|-------|
| E4-SPEC-11 | When the gateway proxies a registration request and the intake service rejects it, the gateway shall answer the caller with a failure status | ⚠ human-gate — gateway error handling, open half of D4. Registration path only; the estate-wide form is deferred to `e5` |
| E4-SPEC-12 | If a registration proxy call fails in transport or the intake service is unreachable, then the gateway shall answer with a failure status | ⚠ human-gate |
| E4-SPEC-13 | The gateway shall never answer a registration request with a success status whose body carries an error field | ⚠ human-gate. This is the statement that kills the 200-with-error-body shape for this path |
| E4-SPEC-14 | A gateway failure answer on the registration path shall let the caller distinguish a rejection of the submitted values from a failure to reach or complete the call | ⚠ human-gate. The category E4-SPEC-6 and E4-SPEC-7 branch on; carried as status class, not as exception text (E4-SPEC-16) |

### E4-REQ-5 — no exception text on the registration proxy path

| ID | Statement | Notes |
|----|-----------|-------|
| E4-SPEC-15 | If a registration proxy call fails, then the gateway shall identify the failure in its log entry by exception class only, never by stringified exception message | ⚠ human-gate — PHI; landmines §3 negative tests. Same leak class PR #11 closed on the eligibility path |
| E4-SPEC-16 | A gateway failure response on the registration path shall carry no request URL, no query parameter, and no stringified exception message | ⚠ human-gate — PHI; landmines §3 negative tests. Bounds what E4-SPEC-14 may use to convey the category |

### E4-REQ-6 — the gateway bound does not preempt the downstream bound

| ID | Statement | Notes |
|----|-----------|-------|
| E4-SPEC-17 | When the gateway proxies a registration request, it shall bound the call with a configured time limit that is not shorter than the intake service's own configured budget for the registration path | ⚠ human-gate — owner 2026-08-10: pinned to intake's registration budget, leaving ADR 0010's eligibility budget as intake's internal concern. Configured values, not numbers, are the contract |
| E4-SPEC-18 | While a registration submission is still within the intake service's own bounded processing path, the gateway shall not abort the call | ⚠ human-gate — the observable form of the pinning; ADR 0010 and `tests/test_eligibility_budget_alignment.py` still bind the budget it pins to |

### E4-REQ-7 — a payload contract mismatch fails CI

| ID | Statement | Notes |
|----|-----------|-------|
| E4-SPEC-19 | The repository shall carry a single shared declaration of the registration request payload contract | The class fix. One artifact asserted from both languages — not two copies kept in step by hand |
| E4-SPEC-20 | When the CI pipeline runs, it shall assert both the payload the portal submits and the payload the intake service accepts against that shared declaration | Both suites; a single-language assertion leaves the class open |
| E4-SPEC-21 | If either side diverges from the shared declaration, then the CI pipeline shall report an overall failure | |

### E4-REQ-8 — registration is asserted at its own endpoint

| ID | Statement | Notes |
|----|-----------|-------|
| E4-SPEC-22 | The test suite shall exercise registration through the intake service's registration endpoint, not through a helper one layer inside it | TODO-55. Today no test drives that endpoint anywhere in `tests/` |
| E4-SPEC-23 | The registration behaviors this spec states of the intake service — record creation, consent storage, and rejection — shall each be asserted at that endpoint | Endpoint-level coverage of E4-SPEC-1, E4-SPEC-4, E4-SPEC-8, E4-SPEC-10 |

### E4-REQ-9 — the eligibility verdict is visible on confirmation

| ID | Statement | Notes |
|----|-----------|-------|
| E4-SPEC-24 | When registration succeeds and an eligibility verdict is available, the portal shall display that verdict on the registration confirmation | TODO-56 / decision D-2. Visibility only — persisting the verdict is out of scope (requirements §7) |
| E4-SPEC-25 | If eligibility was not checked, was degraded, or returned no verdict, then the portal shall display that state explicitly rather than omitting it or presenting it as a definite verdict | The degraded case is the one the discarding code hides today |

### E4-REQ-10 — the registries stop misdescribing this defect

| ID | Statement | Notes |
|----|-----------|-------|
| E4-SPEC-26 | The registries shall record the registration defect as delivered rather than as unscheduled work | TODO-1 and the `docs/landmines.md` §1 bullet |
| E4-SPEC-27 | The debt log shall not assert that the portal/service contract-mismatch class is unguarded for want of a JavaScript test harness | Stale since `e1` landed Vitest (ADR 0018); `docs/debt-log.md:333-336` |
| E4-SPEC-28 | The registry entries this item advances — the discarded eligibility verdict, the missing endpoint-level intake tests, and the registration half of the gateway error-handling follow-up — shall each state their post-delivery status | TODO-55, TODO-56, D4's follow-up line. What remains open must read as deferred to `e5`, not as done |

### E4-REQ-13 — a failed registration leaves nothing behind

| ID | Statement | Notes |
|----|-----------|-------|
| E4-SPEC-4 | If a registration submission is rejected, then the system shall leave no partial patient, coverage, or consent record behind | All-or-nothing, owner 2026-08-10 (D-5). Statement id kept from the draft that hung it on E4-REQ-1; ids are allocated once and never renumbered. E4-SPEC-10's rejection of an unaccepted consent kind depends on this |

### E4-REQ-14 — policy-holder identity is confirmed, not collected

| ID | Statement | Notes |
|----|-----------|-------|
| E4-SPEC-3 | The intake form shall represent policy-holder identity as a confirmation that the policy holder is the patient, and the system shall store no separate policy-holder identity | ⚠ human-gate adjacency — an insurance field on a PHI path, no column added. Inherited decision 2026-07-31, not reopened; the resulting absence is recorded as deliberate in the debt log. Statement id kept from the draft |

## 2. Traceability

| REQ | SPECs |
|-----|-------|
| E4-REQ-1 | E4-SPEC-1, E4-SPEC-2 |
| E4-REQ-2 | E4-SPEC-5, E4-SPEC-6, E4-SPEC-7 |
| E4-REQ-3 | E4-SPEC-8, E4-SPEC-9, E4-SPEC-10 |
| E4-REQ-4 | E4-SPEC-11, E4-SPEC-12, E4-SPEC-13, E4-SPEC-14 |
| E4-REQ-5 | E4-SPEC-15, E4-SPEC-16 |
| E4-REQ-6 | E4-SPEC-17, E4-SPEC-18 |
| E4-REQ-7 | E4-SPEC-19, E4-SPEC-20, E4-SPEC-21 |
| E4-REQ-8 | E4-SPEC-22, E4-SPEC-23 |
| E4-REQ-9 | E4-SPEC-24, E4-SPEC-25 |
| E4-REQ-10 | E4-SPEC-26, E4-SPEC-27, E4-SPEC-28 |
| E4-REQ-13 | E4-SPEC-4 |
| E4-REQ-14 | E4-SPEC-3 |

Both directions close: every in-scope REQ maps to ≥1 SPEC; every SPEC maps to exactly one REQ.
E4-REQ-11 and E4-REQ-12 are out of this spec's scope by decision D-3.

## 3. Decisions taken at this stage

Owner, 2026-08-10, folded into the statements above rather than left open:

| Decision | Statements |
|----------|------------|
| A rejected registration is all-or-nothing — no partial patient, coverage, or consent survives | E4-SPEC-4, backed by E4-REQ-13 (added at this stage, requirements D-5) |
| The operator distinguishes a fixable form problem from a system outage; the gateway carries the category as status class, never as exception text | E4-SPEC-6, E4-SPEC-7, E4-SPEC-14, bounded by E4-SPEC-16 |
| Insurance-coverage storage is inside e4's scope, so the shared payload declaration covers the whole form | E4-SPEC-2, E4-SPEC-19 |
| The gateway registration bound pins to intake's own registration budget; ADR 0010's eligibility budget stays intake-internal | E4-SPEC-17, E4-SPEC-18 |
| An unaccepted consent kind rejects the whole submission — never a partially-consented patient | E4-SPEC-10, resting on E4-SPEC-4 |
| The 2026-07-31 policy-holder decision is homed as a requirement rather than left in §2 prose, so its statement has a REQ to map to | E4-SPEC-3, backed by E4-REQ-14 (requirements D-5) |
