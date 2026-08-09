# E4 Requirements

> Status: DRAFT
> Source: engagement owner ask, 2026-08-08

## 1. Raw ask (verbatim)

> With my no-reverable-decision rule in mind and we plan out abc as a chunk then how does it
> fit in?

and, on the same thread:

> e3: create a draft

Preceding context in the same session — the owner asked, in order, what TODO-1 is, whether the
repo has a bugfix track, why it could not fold into W1, how large the fix is, and how it slots
against outstanding work. "abc" refers to the three tiers the sizing answer named:

> **A** — make registration work (consent enum + portal payload shape).
> **B** — the class fix (one intake payload fixture asserted by both pytest and Vitest).
> **C** — the silent-success amplifier (gateway `proxy_intake` off the error-swallowing `_post`).

The governing rule the ask invokes, stated by the owner earlier in the engagement:

> Take the complete solution over the cheap one that needs reversing later; chunk delivery,
> never narrow scope.

**Numbering.** The ask said `e3`. `e3` is already reserved by e2's held DRAFT for the CI routing
chunk (`docs/workflow/e2/requirements.md` D-8, owner decision 2026-08-08, plus five further
references). Owner picked `e4` for this item on 2026-08-08 rather than renumber a paused artifact.

## 2. Context

**The defect.** Patient registration through the portal is completely non-functional on `main`
and the UI displays success. No patient row is created. Inherited from handoff commit `3663c4b`,
not introduced by any PR in this engagement. Full analysis in `docs/debt-log.md` "Intake contract
break"; tracked as `docs/todo.md` TODO-1, which calls it the highest-value unscheduled item in
that file. Also carried as a `docs/landmines.md` §1 bullet.

It presents as success because four layers compound, three of them backend:

1. `intake-service` returns **422** on payload shape.
2. Gateway `proxy_intake` (`services/gateway/app.py:253`) uses the inherited `_post`, which
   collapses every failure into a **200 OK** `{"error": str(e)}` body (`app.py:1243-1249`).
3. The BFF (`frontend/app/lib/gateway.ts`) relays status and body verbatim.
4. `frontend/app/intake/page.tsx:108` guards on `!res.ok || data?.error`; a 422 body carries
   `detail`, which is neither, so the success branch runs and prints a fallback string.

**Four payload mismatches** are tabulated in `docs/debt-log.md`: `first_name`/`last_name` vs
`name`, a `consents` object vs `list[ConsentKind]`, `insurance.carrier` vs `payer_name`, and
`insurance.policy_holder`, which has no schema field and no column.

**Why "abc as a chunk" rather than "a, then maybe c".** `page.tsx:108`'s `data?.error` branch is
live *only* because the gateway returns 200-with-error-body. Moving `proxy_intake` to
`_post_checked` makes `!res.ok` the live branch and `data?.error` dead. Fixing the payload alone
would therefore mean writing a frontend error contract against behaviour a later gateway change
inverts — the reversal the owner's rule forbids. The error contract is **one decision**, and both
halves depend on it, so it is settled in this document and built against from the first line of
code.

**The chunking that follows from that.** Deciding once does not require shipping fourteen routes
at once. Thirteen further inherited `_post`/`_get` call sites exist (`app.py:260, 303, 308, 315,
331, 343, 350, 355, 362, 373, 378, 385`, and `proxy_hl7`). They carry no *design* decisions once
this document freezes the contract, so §4 defers them to a named follow-on item. This mirrors
e2/e3: one requirements document, complete decision, split delivery.

**Correction to this document's first draft, 2026-08-08.** That draft justified the deferral by
claiming the deferred routes are backend-only, because no portal surface except intake consumes
the swallowed-error body. The first half is true — only `intake/page.tsx:108-109` parses
`.error` — but the conclusion was wrong. The portal's read surfaces do not check response status
at all: `roi/page.tsx:50-52` and `appointments/page.tsx:31-33, 42-45` parse the body and coerce
anything non-list to `d.items ?? []`, so a downstream outage renders today as "you have none",
and still would after the gateway is converted (`{"detail": …}` is equally non-list). **`e5`
therefore carries a portal half, not a backend-only conversion.** The deferral still holds — the
contract decision is here and the symptom is there — but it is deferred work, not cheap work.

**What already exists and does not need building.** `_post_checked` and `_get_checked`
(`app.py:1261`, `:1295`) are written, documented, and in production use on the two `/ai` routes.
CLAUDE.md §4 names them the standard for new code. Vitest + RTL + jsdom landed with `e1`
(ADR 0018); `npm test` runs in CI. `docs/debt-log.md:333-336` still asserts "there is no
JavaScript test harness in this repository, so the class is currently unguarded" — **that claim
is stale** and is itself a finding this item closes.

**Prior decisions this item inherits, not reopens.**

- The consent enum widens by `financial_responsibility_ack` and `communications_opt_in`
  (resolved 2026-07-30). `consents.kind` is plain `TEXT` with no `CHECK` (`db/schema.sql:121`),
  so no migration — but it is a deliberate touch to a **documented PHI control**
  (`services/intake-service/schemas.py:9-24`), so consent storage gets re-proved rather than
  assumed inert.
- `insurance.policy_holder`: the form drops the free-text field for a "policy holder is the
  patient" checkbox (resolved 2026-07-31). No column is added; the resulting absence of
  policy-holder identity is already recorded as deliberate in the debt log.
- Gateway timeouts are pinned to intake's own eligibility budget (ADR 0010,
  `tests/test_eligibility_budget_alignment.py`); `docs/landmines.md` §1 forbids widening or
  loosening either without re-reading that ADR.

**Adjacent registry entries this item touches:** TODO-1 (the defect), TODO-55 (nothing tests
`POST /intake` as an endpoint — every intake test drives `_verify_eligibility` directly),
TODO-56 (the wizard discards the eligibility verdict at the exact lines the payload fix
rewrites), D4's open half (the gateway conversion), and the stale debt-log paragraph above.

**Approval-gated zones touched** (`docs/landmines.md` §1): gateway error handling (the open half
of D4), and the `ConsentKind` PHI control. Neither is auth, PHI columns, ROI logic, migrations,
or secrets — but the landmines bullet for this defect states it is approval-gated and
"deliberately not patched piecemeal", so the gated-zone entry is explicit, not incidental.

## 3. Requirements

| ID | Requirement | Notes |
|----|-------------|-------|
| E4-REQ-1 | Patient / front desk: submitting a completed intake form creates a patient record | the defect itself; TODO-1 |
| E4-REQ-2 | Patient / front desk: when registration does not succeed, the operator is told it failed and is not shown a success message | the silent half — the reason the loss is invisible at the desk |
| E4-REQ-3 | System: every consent the intake form collects is stored against the patient; none is discarded at the service boundary | ⚠ human-gate — widens a documented PHI control (`ConsentKind`); `docs/landmines.md` §3 negative tests required, and consent storage is re-proved, not assumed inert |
| E4-REQ-4 | System: on the registration path, a downstream service failure or rejection reaches the caller as a failure, not as a success response carrying an error body | ⚠ human-gate — gateway error handling, the open half of D4. Scoped to registration; the estate-wide form is E4-REQ-11, deferred per §4. The contract this freezes governs both |
| E4-REQ-5 | System: no gateway proxy log line or response body on the registration path carries exception text that can embed a request URL or its query parameters | ⚠ human-gate — PHI. This is the `member_id` leak class PR #11 closed on the eligibility path; the inherited `_post`/`_get` still log `str(e)` |
| E4-REQ-6 | System: bounding a gateway call does not preempt a downstream service's own bounded path — a registration intake is still legitimately processing is not cut off at the gateway | ⚠ human-gate — ADR 0010 budget pinning, enforced by `tests/test_eligibility_budget_alignment.py`; `_post_checked` takes an explicit timeout where `_post` hardcoded 30s |
| E4-REQ-7 | Engineering org: a payload contract mismatch between the portal and intake-service fails CI rather than reaching production | the class fix. One shared fixture asserted from both languages; the artifact the debt log says is impossible and no longer is |
| E4-REQ-8 | Engineering org: the behavioural claims about registration are asserted against the registration endpoint itself, not against a helper one layer inside it | TODO-55. Today no `TestClient` over intake-service exists anywhere in `tests/` |
| E4-REQ-9 | Front desk: the eligibility verdict the backend already produces is visible on the registration confirmation, including when it is explicitly degraded or unchecked | TODO-56; same lines as E4-REQ-2. Visibility only — persisting the verdict is out of scope (§7). In scope per D-2 |
| E4-REQ-10 | Engagement owner: the registries stop describing this defect as unscheduled and stop asserting the contract-mismatch class is unguarded | TODO-1, TODO-55, TODO-56, the D4 follow-up line, the `docs/landmines.md` §1 bullet, and the stale `docs/debt-log.md:333-336` JS-harness claim |

**UI surface.** The client-visible surface is the registration confirmation, covered by
E4-REQ-2 and E4-REQ-9. Recorded explicitly per the lesson of TODO-44 (closed) rather than left
implicit.

## 4. Deferred to `e5` (gateway estate chunk)

Per D-3 below these are **not** in e4's scope and the e4 spec must not freeze them. Recorded
here so nothing is lost between items; IDs are re-homed when `e5`'s requirements are
synthesized. Mechanism and wording follow `docs/workflow/e2/requirements.md` §4.3, which
established it on 2026-08-08.

| ID | Requirement | Why it waits |
|----|-------------|--------------|
| E4-REQ-11 | System: **every** gateway proxy route surfaces a downstream failure or rejection as a failure, and puts no exception text in any log or response body | The generalization of E4-REQ-4 and E4-REQ-5 from the registration path to the remaining thirteen inherited call sites. Carries no design decisions once e4 freezes the contract, but is thirteen route contracts changing at once, each needing its own timeout value and its own test |
| E4-REQ-12 | Front desk / patient: a downstream outage on a read surface is shown as an outage, not as an empty result | Added by the §2 correction. `roi/page.tsx:50-52` and `appointments/page.tsx:31-33, 42-45` check no status and coerce any non-list body to `[]`, so an outage reads as "you have none" — and converting the gateway alone does not change that. This is the read-side twin of E4-REQ-2 and belongs with the routes it affects |

`e5` also inherits the costs that belong to the estate conversion rather than to registration:
each converted route needs an explicit timeout where `_post`/`_get` hardcoded 30s, and every
such value on a path that reaches eligibility is pinned by ADR 0010 and
`tests/test_eligibility_budget_alignment.py`. Converting `proxy_hl7` additionally changes what
an interop sender sees on a bad message, which is an external-facing contract with no portal
surface at all.

**`e5` is the next free item number as of 2026-08-08** (`e3` is the CI routing chunk). Re-check
it when `e5`'s requirements are synthesized — the same collision that moved this item off `e3`
can recur.

## 5. Assumptions

- This is inherited breakage, not a seeded teaching artifact. It carries no `D<n>` marker, the
  debt log files it as a defect with no D-number, and TODO-1 asks for it to be fixed. Fixing it
  therefore burns no curriculum exercise. Challengeable: if the intent was to preserve it as an
  exercise, this whole item is wrong.
- The consent enum widening needs no migration — `consents.kind` is plain `TEXT` with no `CHECK`
  (`db/schema.sql:121`, verified this session). If that is wrong, migrations are an approval-gated
  zone and the scope changes.
- Only the intake surface *parses* the swallowed-error body. Measured this session:
  `frontend/app/intake/page.tsx:108-109` is the sole consumer of `.error`; `login/page.tsx:43`
  reads gateway's own `/login`, which already raises a real 401. This does **not** mean other
  surfaces are unaffected — see the correction in §2 and E4-REQ-11's scope in §4.
- The 2026-07-30 consent-enum shape and the 2026-07-31 `policy_holder` checkbox decision both
  still stand. Their measurement lives on branch `alt/sveltekit-portal`; the decisions do not
  depend on the descoped rebuild.
- Splitting delivery per §4 reverses nothing, because the error contract is decided in E4-REQ-4
  and the remaining routes apply it without further decisions.

## 6. Decisions

Owner decisions, 2026-08-08, resolving this document's open questions. Recorded rather than
deleted so the reasoning does not have to be re-derived.

| ID | Decision | Basis |
|----|----------|-------|
| D-1 | **The `proxy_intake` gateway conversion rides in e4**, not a follow-on. E4-REQ-4 and E4-REQ-5 are in scope for this item's delivery. | Owner approval of an approval-gated touch (`docs/landmines.md` §1, D4's open half). Without it E4-REQ-2 is not true end-to-end and E4-REQ-4 is a contract nothing exercises |
| D-2 | **E4-REQ-9 (TODO-56, the discarded eligibility verdict) is in scope.** | It lives on the lines E4-REQ-2 rewrites; excluding it means deliberately re-discarding `data.eligibility` in a function under edit, and booking a second visit to the same code |
| D-3 | **The estate conversion is deferred to a named item now, not at pickup: `e5`.** Its requirement is E4-REQ-11 in §4. | Naming it now is what the e2 §4.3 mechanism does. Not naming it is how TODO-1 sat unscheduled after the 2026-08-05 descope took its plan and left the defect |
| D-4 | **Vocabulary stays `item` + `chunk`; "ticket" is not adopted.** | "Ticket" already denotes the client's `RIV-nnn` namespace (RIV-088, RIV-141, RIV-160, RIV-175) throughout `docs/debt-log.md` and `docs/landmines.md`. A second meaning for one word is `CLAUDE.md` §10's named failure |

## 7. Out of scope

- **The other thirteen inherited gateway proxy call sites** — deferred to `e5` per D-3, with the
  requirement recorded as E4-REQ-11 in §4 rather than dropped. They inherit e4's frozen contract
  and carry no further decisions, and no portal surface consumes their error bodies, so the
  deferral is chunked delivery rather than narrowed scope. This is the rest of D4's follow-up
  line.
- **Persisting the eligibility verdict to `insurance_coverages.status`** — D4 residual 3. The
  verdict reaching a screen (E4-REQ-9) and the verdict reaching the database are separate needs;
  the second is a storage change on a PHI path with its own gate.
- **Register-first / out-of-band eligibility re-verification** — D4's named remaining follow-up
  (instant 201 + async verify). It is what fully closes RIV-141; it is a request-path
  architecture change, not a contract fix.
- **Capturing policy-holder identity** — the 2026-07-31 decision removes the field rather than
  storing it. Naming a non-patient policy holder needs a new `InsuranceCoverage` column plus a
  hand-synced migration; recorded in the debt log as deliberate absence.
- **D11 / IDOR and unbounded search** — adjacent PHI exposure on the records path, sized against
  its own whole set per `docs/landmines.md` §1. Nothing here touches it.
- **CI check routing** — `e3`'s chunk, untouched (`docs/workflow/e2/requirements.md` §4.3).
- **Correcting the README compliance claim** — TODO-12, human-gated by scenario design.
- **The seeded `staff`-role capability grant, the booking race, and the HL7 AL1/RXA gap** — named
  in the same landmines section and unrelated to this path.
