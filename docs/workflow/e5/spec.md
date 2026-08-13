# E5 Spec (EARS)

> Status: AGREED 2026-08-11 (frozen); amended 2026-08-11 and re-frozen — E5-SPEC-8 only; amended
> again 2026-08-11 and re-frozen — D-18: E5-SPEC-30 qualified, E5-SPEC-41/42/43 added
> Source: docs/workflow/e5/requirements.md (AGREED 2026-08-10, amended 2026-08-11)
>
> **Amendment 2026-08-11 (D-12, §3).** The drift gate's first round (`findings.md` §Gate,
> finding 3) found a portal read surface with the exact defect E5-REQ-2 names, sitting outside
> E5-SPEC-8's enumeration: the patient chart read. The owner's disposition was to cover it. Only
> E5-SPEC-8's statement and Notes changed; no id was added, removed or renumbered, and no other
> statement was touched. The plan (`plan.md`, `Status: DRAFT`) must re-gate against this text.
>
> **Amendment 2026-08-11 (D-18, §3), second.** Codex review round 2 on PR #76 (`findings.md`
> §Review, round 2) found that E5-SPEC-30, unqualified on content, confirms an edited retry
> while silently discarding the edit — confirmed at runtime before amendment. Owner disposition:
> qualify the replay on content. E5-SPEC-30's statement and Notes changed; E5-SPEC-41 and
> E5-SPEC-42 (E5-REQ-11) and E5-SPEC-43 (E5-REQ-12) were added, appended last in their tables —
> ids are allocated once and never renumbered. No other statement was touched. The plan must
> re-gate against this text.
>

> One spec, two chunks (requirements D-1): §1.1 is the gateway/portal error-contract conversion
> (E5-REQ-1 … E5-REQ-9), §1.2 is registration idempotency (E5-REQ-10 … E5-REQ-13). One gate. The
> plan stage may still sequence and land the chunks separately.
>
> Behaviour contracts only. Where the requirements fixed a mechanism by decision (D-2 … D-8), the
> statement names the behaviour and its Notes cite the decision; the mechanism itself is plan work.
> Three further decisions were taken at this stage and folded in — D-9 … D-11, §3. E5-SPEC-40 was
> allocated with them and so sits last in E5-REQ-11's table; ids are allocated once and never
> renumbered.
>
> e4's frozen contract binds this spec: no statement here reopens `contracts/intake-registration.json`
> on the response side, the registration error mapping, or e4's four portal result branches
> (E4-SPEC-6, E4-SPEC-7). Chunk 2 extends the request side additively and nothing else.

## 1. Statements

### 1.1 — Chunk 1: the gateway/portal error contract

#### E5-REQ-1 — a downstream failure reaches the caller as a failure

| ID | Statement | Notes |
|----|-----------|-------|
| E5-SPEC-1 | When the gateway proxies a request to a domain service and that service answers with a rejection or a failure, the gateway shall answer the caller with a failure status | ⚠ human-gate — gateway error handling; the route set includes three release-of-information routes, so the ROI/disclosure zone is entered on the error path |
| E5-SPEC-2 | If a proxied call cannot be completed — the service is unreachable, the transport fails, or the gateway's bound expires — then the gateway shall answer with a failure status that identifies the failure as a failure to complete the call rather than as a rejection of the request | ⚠ human-gate. The distinction the portal branches on (E5-SPEC-5); carried as status class, never as exception text (E5-SPEC-10) |
| E5-SPEC-3 | The gateway shall never answer a proxied request with a success status whose body carries an error field | ⚠ human-gate. Kills the 200-with-error-body shape estate-wide; e4 killed it for registration only |
| E5-SPEC-4 | Every gateway route that proxies to a domain service shall exhibit E5-SPEC-1 … E5-SPEC-3, with no route excepted | ⚠ human-gate. The universality is the requirement — a route left behind reopens the class. Includes the interop ingest route (E5-REQ-7) |

#### E5-REQ-2 — an outage on a read surface is shown as an outage

| ID | Statement | Notes |
|----|-----------|-------|
| E5-SPEC-5 | If a portal read surface receives a failure status from the gateway, then the portal shall present the surface as failed to load and shall not present it as an empty result | The user-visible half. The in-tree pattern is the records surface landed by W2 |
| E5-SPEC-6 | If a portal read surface receives a success status whose body is not the expected shape, then the portal shall present the surface as failed to load rather than coercing the body to an empty result | The `d.items ?? []` coercion is why a converted gateway alone does not close the defect — a failure body is as non-list as an error body |
| E5-SPEC-7 | While a read surface has genuinely returned no rows, the portal shall present an empty result that a user can distinguish from a failed load | Both states must be reachable and distinct; suppressing the empty state is not a fix |
| E5-SPEC-8 | Every portal read surface that displays gateway-proxied results shall exhibit E5-SPEC-5 … E5-SPEC-7, with none excepted — the release-of-information queue, the appointments list, the bookable-slots panel, the dashboard's appointments and records panels, and the patient chart | Requirements D-8: every unchecked read surface, whether or not its route is converted. **Amended 2026-08-11 (D-12)** — the enumeration was four surfaces and is six; the patient chart was missing entirely and the slots panel was in D-8 but not in this prose. Universality is now the statement, as it is for the gateway in E5-SPEC-4, so a newly-found surface is a coverage question and not a spec change. Write surfaces stay out of scope (requirements §6) |

#### E5-REQ-3 — no exception text on any proxy path

| ID | Statement | Notes |
|----|-----------|-------|
| E5-SPEC-9 | If a proxied call fails, then the gateway shall identify the failure in its log entry by exception class only, and never by stringified exception message | ⚠ human-gate — PHI; `docs/landmines.md` §3 negative tests. The `member_id` leak class: a stringified transport exception can embed the request URL and its query parameters |
| E5-SPEC-10 | A gateway failure response shall carry no request URL, no query parameter value, and no stringified exception message | ⚠ human-gate — PHI; landmines §3 negative tests. Bounds what E5-SPEC-2 may use to convey the failure category |

#### E5-REQ-4 — the gateway bound does not preempt the downstream bound

| ID | Statement | Notes |
|----|-----------|-------|
| E5-SPEC-11 | The time limit the gateway applies to a proxied call shall not be shorter than the downstream service's own configured budget for that call | ⚠ human-gate — ADR 0010 pinning on any eligibility-reaching path; `tests/test_eligibility_budget_alignment.py` enforces it. Requirements D-4 fixes a uniform bound except where ADR 0010 binds |
| E5-SPEC-12 | While a downstream service is still within its own bounded processing of a proxied request, the gateway shall not abort the call | ⚠ human-gate. The observable form of the pinning — a gateway abort inside the downstream budget converts a slow success into a fabricated outage |

#### E5-REQ-5 — success behaviour is unchanged

| ID | Statement | Notes |
|----|-----------|-------|
| E5-SPEC-13 | When a proxied request succeeds, the gateway shall answer with the same status and the same response body it answers before the conversion | The regression floor. This is an error-path change only |
| E5-SPEC-14 | The conversion shall not change the request a route issues downstream — same service, same path, same parameters, same payload | Guards the silent second change; characterization tests first, per landmines §3 |

#### E5-REQ-6 — authorization behaviour is unchanged

| ID | Statement | Notes |
|----|-----------|-------|
| E5-SPEC-15 | Each converted route shall require the same capability it requires before the conversion, and the enforced policy shall remain equal to the declared role policy | ⚠ human-gate — RBAC; the enforced/declared equality is test-pinned |
| E5-SPEC-16 | The conversion shall introduce no route or failure path reachable without a session | ⚠ human-gate. An error path that answers before the session dependency is the failure mode |
| E5-SPEC-17 | A converted read shall disclose no record, and no field of a record, that it does not disclose before the conversion | ⚠ human-gate — four routes sit in the D11 exposure set. D11 is a documented intentional gap: e5 neither fixes nor widens it |

#### E5-REQ-7 — a rejected HL7 message is answered as a rejection

| ID | Statement | Notes |
|----|-----------|-------|
| E5-SPEC-18 | When the interop service rejects or fails to process an ingested HL7 message, the gateway shall answer the sending system with the rejection the interop service made, as a failure status rather than as an acknowledgement | ⚠ outward-facing contract change, taken deliberately (requirements D-2). The only e5 change whose blast radius leaves the estate; today every ingest is answered 200. Owner 2026-08-10 (D-9): relay interop's own status — no HL7 ACK/NAK message is constructed |
| E5-SPEC-19 | The delivery record shall name the ingest response change as an outward-facing contract change and identify external senders as the affected callers | Requirements D-2 requires it in the PR body. This route has no portal surface, so the delivery record is the only place a reader meets it |

#### E5-REQ-8 — the error-swallowing helpers cannot come back

| ID | Statement | Notes |
|----|-----------|-------|
| E5-SPEC-20 | The gateway shall retain no proxy helper that converts a downstream failure or a transport failure into a success response | Requirements D-3: deletion, not disuse. Makes CLAUDE.md §4's "do not add a fifteenth" structural rather than advisory |
| E5-SPEC-21 | The removal shall land only once no caller of the removed helpers remains anywhere in the repository | Satisfies `docs/landmines.md` §2's don't-delete-unused rule; requirements D-3 makes the zero-caller search a gate item |

#### E5-REQ-9 — the registries stop carrying this as outstanding debt

| ID | Statement | Notes |
|----|-----------|-------|
| E5-SPEC-22 | The registries shall record the estate-wide gateway error-handling conversion as delivered rather than as outstanding or deferred work | Closes the remainder of the D4 follow-up line and e4 §4's deferral record |
| E5-SPEC-23 | No durable engineering context shall state a count of inherited error-swallowing proxy routes as outstanding | CLAUDE.md §4's "fourteen inherited proxy routes", already re-measured at thirteen after e4 |

### 1.2 — Chunk 2: registration idempotency

#### E5-REQ-10 — a retried submission yields one chart

| ID | Statement | Notes |
|----|-----------|-------|
| E5-SPEC-24 | When an operator re-submits a registration whose outcome was never delivered to them, the system shall hold exactly one patient chart for that submission | ⚠ human-gate — PHI path. The operator-facing outcome; the mechanism is E5-REQ-11 |
| E5-SPEC-25 | If a registration was committed but its confirmation was lost, then a re-submission of that same attempt shall create no further coverage record and no further consent record | ⚠ human-gate — PHI; landmines §3 negative tests. A duplicate chart carries its own consents, which is what makes the duplicate a compliance artefact and not just a data-quality one |

#### E5-REQ-11 — the submission identifier and its replay

| ID | Statement | Notes |
|----|-----------|-------|
| E5-SPEC-26 | When an operator begins a registration submission attempt, the portal shall generate an identifier for that attempt and shall send the same identifier on every re-submission of the same attempt | Requirements §4: the identifier is generated at the form, because the gateway sits inside the window that is lost |
| E5-SPEC-27 | A registration request shall carry the submission identifier as a declared field of the request payload contract | ⚠ human-gate. Additive extension of the frozen request contract; requirements §6 forbids renaming, retyping or removing anything already in it |
| E5-SPEC-28 | The gateway shall forward the submission identifier unchanged, and shall neither generate, substitute nor drop one | The gateway is inside the lost window; a gateway-minted identifier would differ on the retry and close nothing |
| E5-SPEC-29 | When the intake service completes a registration, it shall record the submission identifier against the registration it produced, in the same transaction that creates the registration | ⚠ human-gate — new persisted state, so `db/schema.sql` plus a migration; recorded human approval before code. A record written outside the transaction reopens the window it exists to close |
| E5-SPEC-30 | When a registration request carries a submission identifier already recorded against a completed registration and content that matches the recorded attempt's content, the intake service shall answer with the created status and the patient identifier of that registration, and shall create no further record | Requirements D-5, qualified by D-18 (§3): a replay of the *same attempt* is indistinguishable from the original success — that is the point. Content match is decided by the recorded fingerprint (E5-SPEC-41); the mismatch path is E5-SPEC-42 |
| E5-SPEC-31 | The registration response shall carry no indication that a request was a replay, and its shape and status shall be unchanged | ⚠ human-gate adjacency — e4's frozen response contract. D-5: no fifth portal result branch |
| E5-SPEC-32 | If two registration requests carrying the same submission identifier are in flight together, then exactly one shall create the registration and the other shall wait a bounded time and answer with the created registration's result | Requirements D-6. The uniqueness of the recorded identifier decides the race; the loser replays rather than answering "duplicate" |
| E5-SPEC-33 | If the bounded wait expires before the winning request's result is available, then the intake service shall answer with a failure that the portal presents in its existing system-failure branch, and shall create no second registration | Requirements D-6, and owner 2026-08-10 (D-11): no fifth portal branch. The answer is imprecise in this edge case — the winner may have saved the registration — and the operator's next retry carries the same identifier and replays into the real confirmation (E5-SPEC-30) |
| E5-SPEC-34 | A recorded submission identifier shall be retained for the lifetime of the system, with no expiry and no pruning | Requirements D-7; the unbounded growth is accepted and recorded, not deferred. Lookup by identifier must stay cheap as the record set grows |
| E5-SPEC-40 | If a registration request carries no submission identifier, or one that is not well-formed, then the intake service shall reject the request and shall create no registration | ⚠ human-gate. Owner 2026-08-10 (D-10): the identifier is required, so no path retains the non-idempotent behaviour. Rejection is by the submitted values, so it lands in e4's correctable-at-the-desk branch (E4-SPEC-6) |
| E5-SPEC-41 | When the intake service records the submission identifier (E5-SPEC-29), it shall record with it, in the same transaction, a fingerprint of the submitted content from which no patient-identifying value can be recovered | ⚠ human-gate — new persisted state (`db/schema.sql` plus a migration) and a PHI-derived value; owner approval recorded 2026-08-11 (D-18). Non-recoverability is E5-REQ-13's discipline applied to the fingerprint: it reaches persisted state, and a plain hash of guessable fields (DOB, SSN) is dictionary-reversible. The keyed derivation is plan work |
| E5-SPEC-42 | If a registration request carries a submission identifier already recorded and content that does not match the recorded attempt's content, then the intake service shall answer with a failure that the portal presents in its existing system-failure branch, shall create no registration, and shall modify no recorded one | ⚠ human-gate — PHI path; landmines §3 negative tests. D-18: a mismatched replay is answered as a failure, never as a confirmation of content that was not saved. When E5-SPEC-43 holds this path is unreachable from the portal; it is the service-side guarantee for every other caller |

#### E5-REQ-12 — a fresh registration is never mistaken for a retry

| ID | Statement | Notes |
|----|-----------|-------|
| E5-SPEC-35 | When an operator begins a new registration rather than re-submitting an attempt, the portal shall generate a new submission identifier | The pair to E5-SPEC-26; a form that reuses an identifier turns a genuine second registration into a silent replay |
| E5-SPEC-36 | When a registration request carries a submission identifier not previously recorded, the system shall create a new patient chart, including when a patient with the same identifying values already exists | ⚠ human-gate — PHI; landmines §3 negative tests. Idempotency must not become an accidental master patient index |
| E5-SPEC-37 | Two separate registration submissions for the same person shall still be queued as a duplicate candidate pair and shall still not be merged | ⚠ human-gate. D5 is a planted defect that stays open by design (requirements §6); e5 must be shown not to have closed it |
| E5-SPEC-43 | When the operator changes any value of the registration form after a submission attempt whose outcome was a failure or was never delivered, the portal shall treat the next submission as a new attempt and shall generate a new submission identifier for it | D-18, the pair to E5-SPEC-26's "same attempt": an edited form is a different attempt, not a re-submission. If the original attempt had in fact committed, the edited submission creates a second chart and the pair is queued for human review (E5-SPEC-37) — visible, where the unqualified replay silently discarded the edit |

#### E5-REQ-13 — the identifier carries no patient-identifying value

| ID | Statement | Notes |
|----|-----------|-------|
| E5-SPEC-38 | The submission identifier shall not be derived from any patient-identifying value | ⚠ human-gate — PHI; landmines §3 negative tests. A key hashed from SSN, date of birth or name also violates E5-SPEC-36, since two genuine registrations for one person would collide |
| E5-SPEC-39 | The submission identifier shall carry no patient-identifying value, so that its appearance in a log line, a response body, or persisted state discloses nothing about the patient | ⚠ human-gate — PHI; landmines §3 negative tests. The identifier reaches all three surfaces |

## 2. Traceability

| REQ | SPECs |
|-----|-------|
| E5-REQ-1 | E5-SPEC-1, E5-SPEC-2, E5-SPEC-3, E5-SPEC-4 |
| E5-REQ-2 | E5-SPEC-5, E5-SPEC-6, E5-SPEC-7, E5-SPEC-8 |
| E5-REQ-3 | E5-SPEC-9, E5-SPEC-10 |
| E5-REQ-4 | E5-SPEC-11, E5-SPEC-12 |
| E5-REQ-5 | E5-SPEC-13, E5-SPEC-14 |
| E5-REQ-6 | E5-SPEC-15, E5-SPEC-16, E5-SPEC-17 |
| E5-REQ-7 | E5-SPEC-18, E5-SPEC-19 |
| E5-REQ-8 | E5-SPEC-20, E5-SPEC-21 |
| E5-REQ-9 | E5-SPEC-22, E5-SPEC-23 |
| E5-REQ-10 | E5-SPEC-24, E5-SPEC-25 |
| E5-REQ-11 | E5-SPEC-26, E5-SPEC-27, E5-SPEC-28, E5-SPEC-29, E5-SPEC-30, E5-SPEC-31, E5-SPEC-32, E5-SPEC-33, E5-SPEC-34, E5-SPEC-40, E5-SPEC-41, E5-SPEC-42 |
| E5-REQ-12 | E5-SPEC-35, E5-SPEC-36, E5-SPEC-37, E5-SPEC-43 |
| E5-REQ-13 | E5-SPEC-38, E5-SPEC-39 |

Both directions close: every requirement maps to ≥1 statement; every statement maps to exactly
one requirement. All thirteen requirements are in scope — e5 defers nothing.

## 3. Decisions taken at this stage

Owner, 2026-08-10 (D-9 … D-11) and 2026-08-11 (D-12) and 2026-08-11 (D-18, on review round 2), closing the questions this stage
opened or that review returned to it. Numbered on from the requirements' decision table
(D-1 … D-8), which stays the record of what stage 1 decided.

| ID | Decision | Statements |
|----|----------|------------|
| D-9 | **The HL7 rejection relays interop's own status.** No HL7 ACK/NAK message is constructed. | E5-SPEC-18. Interop already answers a bad message with a rejection status; the defect is the gateway swallowing it into 200. ACK/NAK machinery does not exist in this estate and building it is new scope, not an error-contract fix — it would need its own requirement. |
| D-10 | **The submission identifier is required.** A request without one, or with a malformed one, is rejected. | E5-SPEC-40. No path retains the non-idempotent behaviour, so the guarantee is not conditional on the caller. Consequence: the request contract extension is additive **and required** — a caller that does not send the field breaks, and today the portal is the only caller. |
| D-11 | **A bounded-wait expiry answers in e4's existing system-failure branch.** No fifth portal result branch. | E5-SPEC-33, resting on E4-SPEC-7 and requirements D-5. The answer is imprecise in that edge case — the winning request may have saved the registration — and it is accepted deliberately: the operator's next retry carries the same identifier and replays into the real confirmation. |
| D-12 | **E5-SPEC-8 covers every portal read surface of gateway-proxied results**, stated as universality rather than as a list. Taken 2026-08-11, on the drift gate's finding 3. | E5-SPEC-8. The patient chart read (`frontend/app/records/page.tsx:78`) has the defect E5-REQ-2 names — no status check, `json.encounters ?? []`, and an outage rendered as "No records found for this patient." — and its route (`proxy_records`) is one e5 converts, so excluding it would have shipped e5 with the class still visible on a PHI read surface. It was an omission, not a decision: E5-REQ-2's text was always generic, the stage-1 enumeration was measured wrong (requirements amendment 2026-08-11), and the pattern the requirements cite as the one to imitate is the sibling function twenty lines below the unchecked read. Stating it as universality rather than a longer list closes the failure mode the finding exposed — a list that a later measurement can fall outside of. |
| D-18 | **A replay must match the recorded attempt; a mismatch is answered as a failure; an edited form is a new attempt.** Taken 2026-08-11, on codex PR #76 round-2 finding 1, confirmed at runtime before the decision. | E5-SPEC-30 (qualified), E5-SPEC-41, E5-SPEC-42, E5-SPEC-43. D-5's "the replay is indistinguishable from the original success" was decided for the re-submission of identical content; unqualified, it also confirmed an *edited* retry while silently discarding the edit — the desk saw success for a correction the chart never received, and the response even echoed the edited insurance in its eligibility block. The service records a non-reversible content fingerprint beside the identifier and answers a mismatched replay in the existing system-failure branch (no fifth portal branch — D-11's precedent holds); the portal re-mints the identifier when the form is edited after a failed or unconfirmed submit, so the operator-facing path is a new attempt and the service-side rejection is defence in depth for any non-portal caller. |
