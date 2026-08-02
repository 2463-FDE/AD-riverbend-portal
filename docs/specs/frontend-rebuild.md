# Frontend rebuild — staff-first portal, design-led

> Spec, not a plan-of-record for code yet. Written from `_template.md`. Prefix `FE`.
> Not a curriculum week: user-initiated scope, running alongside the W4–W10 arc.
> Started 2026-07-28.

---

## 1. Context

Not a client ticket. The trainer has given explicit leeway for large changes provided client
needs are still met and nothing regresses. The user wants the frontend rebuilt from the ground
up, design-first, and wants frontend capability to be the showcase of this engagement.

The trigger for treating it as more than a restyle is a walkthrough of the running stack on
2026-07-28 (method now standing policy — drive the app, do not read the source first):

- **Patient intake is completely broken on `main` and the portal reports success.**
  `intake-service` returns 422; the gateway relays it as HTTP 200; the portal prints
  "Intake submitted successfully." No patient row is created. Three payload mismatches
  (`first_name`/`last_name` vs `name`; `consents` object vs `list[ConsentKind]`;
  `insurance.carrier` vs `payer_name`). It shipped green past `npm run build` and 730
  passing pytest tests because nothing asserts the two sides of that payload.
- The dashboard is patient-voiced to staff users ("summary of **your** care", "**Your** care
  team", "Good day, Front").
- The chart shows no patient identity: load patient 1042 vs 1043 and the screens are near
  identical — no name, DOB, MRN, or allergies anywhere.
- Records, Appointments and ROI are all driven by a raw numeric Patient ID box. `/api/records/search`
  exists and no UI uses it. The ID box also teaches the D11 ID-walk.
- Appointment rows render time as "—"; open slots read 3:00–6:00 AM (UTC rendered as local) and
  are dated in the past with a live Book button.
- DOB picker opens on the current year with no typed entry; reaching 1900–1960 means dropdown
  hunting, and keyboard-only means month-by-month traversal.
- SSN field is `type="password"`, so the browser password manager offers to store an SSN.

**None of these are React's fault.** Every one is design or contract. That bounds what a
framework change can be justified on (see §8 #2).

## 2. Scope

**In scope:** a new staff-facing frontend, authored design-first; the design system behind it;
the intake payload contract and its test; the identity/search/time/consent-labelling defects
above; a frontend test harness with its ADR.

**Out of scope, and someone will try to pull each in:**

- **The IDOR fix itself** (D11) — binding session identity to `patient_id` is an auth-boundary
  change, W4's job, and CLAUDE.md §6 approval-gated. This spec builds name search, which is a
  read-path affordance, not an authz change. `FE-R6` must not be read as licence to touch authz.
- **The role model** (D8) — see `FE-R14` and §8 #3. Gated at G4.
- **Moving eligibility off the request thread** (D4 remainder) — register-first needs a job store;
  approval-gated. This spec surfaces the eligibility result that is *already* on the wire.
- **ROI authorization enforcement** (D12) — W9. This spec fixes the disclosure *UI*
  (name confirmation, action weight), not the missing 164.508 check.
- **A patient-facing portal.** Decided 2026-07-28: this product is **staff-only** and patients never
  log in. A separate patient surface (e.g. requesting one's own records) may come later and is
  explicitly **not** to be designed for now — no speculative abstractions, no dual-audience
  components. The one forward-compatibility cost worth paying: keep design tokens and primitives
  audience-neutral so a future patient app can reuse them, which costs nothing today.
  **Amended 2026-07-31:** a patient surface is now a live question, tracked as §8 #16. It remains
  out of scope for P2 and the no-speculative-abstraction rule stands unchanged; what changed is that
  its prerequisite is named — **D11 session binding**, not any amount of frontend work.
- **The AI feature surfaces — out of scope for P0–P6, and scheduled as P7 (§8 #17).** Two LLM
  features were built for W1 and W3 and one of them has never had a UI: `POST /ai/intake-instructions`
  (W1's patient-friendly checklist, surfaced only in the legacy portal at
  `frontend/app/intake/page.tsx:141`) and `POST /ai/visit-chat` (W3's eligibility assistant with
  visit-scoped memory, `services/gateway/app.py:938`, **no frontend route in either portal**).
  **Named here 2026-08-01 because silence is exactly how they went missing:** every other deliberate
  omission in this rebuild was written into this list, these two were not, and the result was a plan
  that would retire `frontend/` and delete the only shipped UI of a client ask. This list is the
  mechanism; it failed once and the entry is the repair.
- Backend redesign of any kind. The portal → gateway → service invariant holds (CLAUDE.md §1).

## 3. Definitions

- **Operator** — the signed-in staff member. Four are seeded: `frontdesk`, `drnguyen`
  (clinician), `roiclerk`, `mokonkwo`. All currently share the single `staff` role.
- **Identity banner** — persistent patient header: name, DOB, MRN, sex, allergy status.
- **Contract fixture** — one payload example in the repo, asserted by both a pytest test and a
  JS test, so the two sides of `/intake` cannot drift silently again.
- **Original portal** — the existing Next.js app at `frontend/`, kept runnable per `FE-R15`.

## 4. Deliverables

1. `docs/design/` — operator/task inventory, information architecture, key flows, wireframes,
   design tokens. Framework-agnostic. Shareable version published as a private Artifact.
2. **ADR: frontend framework choice** — scores at least two candidate stacks against §5's P0
   requirements and states the continuity cost of replacing Next.js. Partially supersedes ADR 0001.
3. **ADR: frontend test harness** — written *after* the framework ADR, not before.
   **Done 2026-07-30: `adr/0013-frontend-test-harness.md`** (Vitest, two projects — real-browser
   component tests and Node contract tests; no E2E suite adopted, so the `driven repro` rows below
   stay human-verified). It fixes where the `FE-R3` fixture lives — `tests/contracts/intake_payload.json`,
   outside both frontends — and adds a `FE-R21` set-equality assertion over `ConsentKind`.
4. The new frontend itself, phased per §6.
5. A superseding note on ADR 0008 if `react-day-picker` is dropped.
6. `docs/debt-log.md` entry for the intake contract break.
7. **ADR: portal origin + audience separation** — added 2026-07-31, not in the original deliverable
   list. **Done: `adr/0015-portal-origin-and-audience-separation.md`.** Two origins, host-only cookies
   (`FE-R30`), `ORIGIN` as runtime config (`FE-R31`). It exists because ADR 0014 §1's `Secure` flag and
   §2's `csrf.checkOrigin` both depend on an origin no document had stated.
8. **P7 — surfaces for the AI features already built** (added 2026-08-01, §8 #17): W1's
   intake-instructions checklist, currently legacy-only, and a first-ever UI for W3's `visit-chat`
   eligibility assistant. Sequenced after G5 so it never competes with parity work.

## 5. Requirements (EARS)

Phase column maps to §6. `insp.` = verified by inspection/documented repro, stated deliberately.

| ID | Requirement | Verification | Debt | Gate |
|---|---|---|---|---|
| `FE-R1` | WHEN a valid intake payload is submitted, the portal shall display the `patient_id` returned by the service. | contract test + driven repro | — | G2 |
| `FE-R2` | IF an upstream response carries a non-2xx status, **or** a body containing an error `detail`, **or** a body containing an `error` key, THEN the portal shall present the operation as failed and shall not display a success message. **[wording corrected 2026-07-31 — see §8.5]** | JS test, all three branches | D4 | G2 |
| `FE-R3` | The repository shall contain one shared intake payload fixture asserted by both a pytest test and a JS test. | CI, both jobs | — | G2 |
| `FE-R4` | WHEN a chart is displayed, the portal shall show the patient's name, DOB, and MRN in a persistent header. | component test + driven repro | — | G3 |
| `FE-R5` | IF allergy data is unavailable for a displayed patient, THEN the header shall state that it is unavailable rather than rendering an empty or absent region. | component test | D6 | G3 |
| `FE-R6` | The portal shall offer patient selection by name and date of birth; raw ID entry shall not be the only selection path. | driven repro | D11 (read path only) | G3 |
| `FE-R7` | WHEN a date of birth is entered, the portal shall accept a typed date, and any year from 1900 shall be reachable without month-by-month traversal. | component test | — | G3 |
| `FE-R8` | The portal shall render every appointment and slot time in the clinic's timezone (`America/New_York`), and shall not render them in the viewer's timezone. | unit test on the formatter, run under a non-clinic `TZ` | — | G5 |
| `FE-R26` | IF stored appointment or slot instants are known to be incorrect, THEN the portal shall not apply a compensating offset; the correction belongs to the data. | insp. + code review | — | G5 |
| `FE-R9` | Every appointment row shall display its date and start time. | component test | — | G5 |
| `FE-R10` | IF a slot's start time is in the past, THEN the portal shall not offer a booking action for it. | component test | D5 (adjacent) | G5 |
| `FE-R11` | WHERE a consent has not been answered, the portal shall render it as not answered and shall not render it as declined. | component test | — | G3 |
| `FE-R12` | The portal shall not use an `input` of type `password` for SSN entry. | insp. + lint rule | D3 (adjacent) | G3 |
| `FE-R13` | WHILE a staff operator is signed in, the portal shall not address that operator as the patient. | insp. against a copy checklist in `docs/design/` | D8 (surface of) | G3 |
| `FE-R14` | WHERE a per-operator role is present in the session, the portal shall render a role-specific home surface. | driven repro per role | D8 | **G4** |
| `FE-R15` | The repository shall retain the original portal as a separately runnable service until the new portal reaches feature parity at **G5**. **[Condition widened 2026-08-01.** It read "until `FE-R1`–`FE-R3` pass", which close at **G2** — login plus the minimum intake path. Records land at G3 and the appointment/ROI queues at G5, so the original wording released the old portal three gates before anything replaced what it does. Phrased as a floor it forced no premature deletion, but it was the only stated condition and reads as permission.**]** | `make config` + both services up, re-checked at each gate from G2 through G5 | — | G2 |
| `FE-R16` | IF an error is surfaced to the operator, THEN the message shall not contain PHI. | adversarial test (CLAUDE.md §5 negative-test rule) | D1 | G2 |
| `FE-R17` | The build shall fail when a **button or link** lacks an accessible name. **[scope narrowed 2026-07-31 to what the gate measurably enforces — see §8.5; form-control names are NOT gated, ADR 0013 gap #9. Narrowed once more the same day, measured at implementation: a button or link whose only child is `<img alt="">` is NOT caught either — ADR 0012 §Implementation-round corrections]** | CI job | — | G3 |
| `FE-R18` | The design phase shall produce, for each seeded operator role, the tasks performed per shift and the data each task requires. | `docs/design/` review | — | G0 |
| `FE-R19` | The framework decision shall be recorded in an ADR scoring at least two candidate stacks against `FE-R18`'s output, stating the continuity cost of replacing Next.js. | ADR review | — | G1 |
| `FE-R20` | WHEN an intake is submitted successfully, the portal shall display the eligibility result already present in the service response. | component test + driven repro | D4 | G3 |
| `FE-R21` | Every consent the intake form collects shall be persistable by intake-service; the portal shall not collect a consent that cannot be stored. | contract test: the fixture's consent set is a **subset** of `ConsentKind` (ADR 0013 §3 assertion 3a), plus a pinned-literal assertion that the enum's members are exactly the five documented values (3b) **[was "set equality", which was unsatisfiable — §8.5]** | — | G2 |
| `FE-R22` | IF a consent identifier outside the accepted closed set is submitted, THEN intake-service shall reject the request at the boundary. | existing adversarial test, re-proven to discriminate after the set is widened | D1 | G2 |
| `FE-R23` | WHERE role-driven navigation is derived from `users.role` without gateway enforcement, the portal shall present it as navigation only, and the absence of per-action authorization shall remain recorded in `docs/debt-log.md`. | insp. + debt-log entry | D8 | G3 |
| `FE-R24` | The portal shall refer to the patient in the third person; no copy shall address the signed-in operator as the patient. | copy checklist in `docs/design/`, applied at review | D8 (surface of) | G3 |
| `FE-R25` | WHILE a patient is selected, the portal shall retain that patient as context across chart, appointment and ROI surfaces without re-entry. | driven repro | — | G3 |
| `FE-R27` | The portal shall not expose the gateway session token to client-side JavaScript; the token shall be held by the portal's own server layer and reach the browser only as an `httpOnly`, `Secure`, `SameSite` cookie. | **driven at the gate, recorded** (needs a login, so the harness cannot run it — ADR 0013 §2's 2026-07-31 amendment): after login, assert the token appears in neither `document.cookie` nor any web-storage value | D10 | G2 |
| `FE-R28` | WHILE an operator session is active, IF no operator interaction occurs for 10 minutes, THEN the portal shall invalidate the session server-side and return the operator to the login surface — enforced from a `last_seen` value the browser cannot forge, not by a client timer alone (ADR 0014 §4). | **CI:** unit test on the timer and on the `last_seen` staleness check, both pure functions. **Driven at the gate:** a request made after the timeout is rejected with a 401 — the proof is the rejection, not the redirect | D10 | G2 |
| `FE-R29` | The portal shall not persist patient data to `localStorage`, `sessionStorage` or IndexedDB. | **CI:** a component fed fixture patient data writes nothing to any storage (no server, no network). **Driven at the gate:** after a name search and a chart view, no storage key or value contains patient-shaped data | D1, D3 | G2 |
| `FE-R30` | The portal shall set no cookie carrying a `Domain` attribute; every cookie it sets shall be host-only. | assertion on the `Set-Cookie` header, with the mutation proof (add a `Domain`, confirm the test fails) | — | G2 |
| `FE-R31` | The portal shall resolve its own public origin from the runtime environment (`ORIGIN`), and shall not embed an origin as a build-time constant. | insp. + one container check that a non-default `ORIGIN` is honoured at runtime | — | G2 |
| `FE-R32` | The portal's production image shall answer `GET /healthz` with 200 when started from the built image, proven in CI rather than inferred from the image building. | **CI:** `docker compose up -d --no-deps portal` in the `docker-build` job, wait for the container healthcheck to report `healthy`, then `curl -fsS http://localhost:3071/healthz`. Added 2026-07-31 after two review rounds inferred a startup crash from static config — the image builds and the runtime dependency tree is near-empty, both true, and the container serves anyway because adapter-node bundles its runtime | — | G2 |
| `FE-R33` | WHEN an intake is submitted successfully, intake-service shall report which consents were committed, and the portal shall render the confirmation's consent count from that report and not from the submitted payload. | **CI:** a unit test in which one consent insert raises and the response reports the surviving set, not the submitted set — the mutation proof is that a test asserting the submitted set passes today and must fail after the change. Plus a JS test that the confirmation renders the response field, fed a fixture where the two sets differ | — | G2 |

## 6. Checkpoints / gates

Phases are sequential; **G2 blocks everything after it.**

| Gate | Phase it closes | Blocks | Artifact | Verified how | Signed by |
|---|---|---|---|---|---|
| **G0** | P0 Design: operators, tasks, IA, flows, wireframes, tokens | framework choice | `docs/design/` + Artifact | user review of the design set | user |
| **G1** | P1 Framework decision | all implementation | framework ADR (+ harness ADR after it) | ADR review; Next.js must be a genuine option that loses on stated criteria | user |
| **G2** | P2 Contract truth + harness | **every later phase** | contract fixture, both test jobs green, `FE-R1`–`R3`, `R15`, `R16`, `R21`, `R22`, `R27`–`R33` | `make test-docker` **and** driving the app; a 200 proves nothing here. **From 2026-07-31 the split is explicit per requirement in §5:** `FE-R27` and the 401/post-search halves of `FE-R28`/`FE-R29` are **driven and recorded**, not CI-proven, so G2's signature rests on a written record of what was driven (ADR 0013 gap #3) | user |
| **G3** | P3 Design system + P4 identity/search/forms | queue work | primitives + patient banner + name search | driven repro per `FE-R4`–`R7`, `R11`–`R13`, `R17`, `R20` | user |
| **G4** | P5 Role-aware shell | — | role model decision | **explicit human approval for an auth change (CLAUDE.md §6)**; needs `config/roles.yaml` + `users` + session + gateway enforcement, and both `db/schema.sql` and a new hand-synced migration | user, explicitly |
| **G5** | P6 Appointments/ROI queues | P7 | queue surfaces, tz fix | driven repro per `FE-R8`–`R10` | user |
| **G6** | P7 AI feature surfaces (§8 #17) | — | W1's intake-instructions checklist re-homed on the new portal; a UI for W3's `visit-chat` assistant, which has never had one | design-first like every phase before it: flows + wireframes, then requirements, then build. **Also a PHI-boundary review** — `/ai/*` is the only vendor-egress path (CLAUDE.md §6) and D13/D14 are open | user |

Per-phase discipline, not repeated per gate: each phase is its own PR with its own ADR where a
non-trivial decision was made; `/verify-stack` before every push; `/security-review` on any diff
touching auth/PHI/ROI; commits carry no `Co-Authored-By` trailer.

## 7. Relevant landmines

- ⚠️ **Auth / sessions** — never change auth behaviour without explicit human approval. `FE-R14` is
  behind G4 for exactly this reason.
- ⚠️ **IDOR on chart reads** — sessions are not bound to `{patient_id}`; IDs are sequential and
  walkable. `FE-R6` replaces the ID box in the UI; it does **not** close the vuln.
- ⚠️ **ROI has no authorization enforcement** — no 164.508 record, no accounting of disclosures.
- ⚠️ **PHI handling** — plaintext `ssn`/`notes`; intake logs full bodies at INFO. `FE-R16` applies.
- ⚠️ **Inline eligibility call** — bounded by ADR 0010, still on the request thread. Do not widen a
  timeout or loosen a breaker threshold; the values are pinned to each other and
  `tests/test_eligibility_budget_alignment.py` enforces it.
- ⚠️ **Schema/migrations are hand-synced** — relevant only if G4 opens.
- The gateway `_post` → `_post_checked` change implied by `FE-R2` is the open half of D4 and is
  approval-gated. `FE-R2` is satisfiable **frontend-side** (treat a `detail` body as failure)
  without touching the gateway; do that first and raise the gateway half separately.

## 8. Open decisions

| # | Decision | Blocks | Unblocked by |
|---|---|---|---|
| 1 | ~~Intake contract break: own fix PR now, or folded into P2?~~ **RESOLVED 2026-07-30: folded into P2**, and `ConsentKind` is **widened by two values** (§8.1). No separate fix PR; the Next.js portal is deliberately **not** patched in the interim. No new spec file and no gate re-staging — `FE-R1`, `R2`, `R3`, `R15`, `R16`, `R21`, `R22` already specify the fix and all seven already sit at G2. Two accepted costs, named so they are not re-argued: (a) the live defect survives on `main` until G2 — `FE-R15` keeps the old portal runnable, not correct; (b) widening the enum is a deliberate touch to a documented PHI control (CLAUDE.md §6), carrying the `FE-R22` re-proof. Mismatch is **inherited** from handoff commit `3663c4b`, not introduced by PRs #1–#21. | — | resolved |
| 2 | ~~Framework: SvelteKit vs stay on Next.js.~~ **RESOLVED 2026-07-30: SvelteKit**, recorded in `adr/0012-frontend-framework-sveltekit.md` — scored against the discriminating requirements only, with Next.js as a genuine option that loses on `FE-R17` and form ergonomics and wins on continuity. Bundle size and "React caused the defects" are recorded there as **rejected** arguments. G1 still needs the ADR review. | — | resolved |
| 3 | Does the trainer's leeway extend to the role model (D8)? Three tiers, costed in §8.3 below. Tier 2 needs no auth approval and no migration. **Standing open by user decision 2026-07-28: deferred past G0, because P0 decides which role-specific surfaces exist and therefore which tier is needed.** | G4 / `FE-R14`, `FE-R23` | G0 output, then user call; tier 3 only, explicit auth approval |
| 9 | **Slot/appointment instants are stored wrong, so `FE-R8` cannot be satisfied frontend-side alone.** `db/seed/generate_seed.py:159,163,166` builds correct clinic wall-clock times (`08:00`, 8 per day) and emits them as bare strings into `timestamptz` with the Postgres session at `Etc/UTC` — so 8:00 AM ET is stored as `08:00Z` instead of `12:00Z` (EDT, UTC−4). Rendering then uses `toLocaleTimeString(undefined, …)`, i.e. the **viewer's** zone, which is why slots read 03:00 on a CDT machine. Two separate fixes: correct the seed/ingest conversion (data, backend) and render in clinic time (`FE-R8`). `FE-R26` forbids the tempting frontend offset hack. | `FE-R8`, any day view | user call on who owns the data fix |
| 7 | ~~**Queue surfaces have an unnamed backend dependency.**~~ **RESOLVED 2026-08-01: endpoint added.** `GET /schedule?date=&limit=&offset=` on scheduling-service (`services/scheduling-service/app.py`), proxied at `services/gateway/app.py`. One clinic day across all patients in a single joined query, so the day view no longer needs a per-patient fan-out (the D8 N+1 pattern). The calendar day is resolved in the clinic's own zone (`CLINIC_TIMEZONE`, default `America/New_York`) because `appointments.scheduled_for` is `TIMESTAMPTZ` and a date is not a range until a zone is named; `tests/test_schedule_day_view.py` pins the two DST changeover days at 23h and 25h, mutation-proven against the UTC-arithmetic version. Authorization is unchanged — `require_session` only, D11 still open and still W4's. **Two corrections to this row's original framing, both measured:** (a) it said "the queues", but `GET /roi/requests` takes `patient_id` as *optional*, so the ROI work queue was always buildable — only the appointment day view was blocked; (b) descoping would **not** have cost parity, because legacy has no day view either (`frontend/app/appointments/page.tsx:20` is a typed patient-ID box defaulting to 1042). The risk was to new value, not to `FE-R15`. The gateway route uses a checked GET helper (`_get_checked`), so scheduling's 422 and 503 arrive as 422 and 503 rather than as the inherited `_get`'s 200-with-an-error-body — a front desk sees an outage, not an empty day (codex r1). The visit time is `COALESCE(appointments.scheduled_for, slots.start_at)` over an **outer** join, not the raw column: the booking UI never posts a time and the column has no default, so filtering on it alone returned nothing but seeded rows — right in dev, empty in production (found by r1's pre-push pass; write-path fix is `docs/todo.md` TODO-34). The response carries `has_more`, so a day longer than one page cannot render as a complete-looking list. Still open and unaddressed: there is **no** by-provider appointment query at all — a `provider_id` filter was cut in r1 because the only path to a provider id is the FK-less `appointments.slot_id` → `slots` join, which drops slotless appointments silently (W5, with RIV-175); and `GET /slots` has no date range, so `FE-R10`'s past-slot suppression still filters client-side over up to 200 rows. Detail in `docs/design/01-operators-and-tasks.md` §4. | nothing — P6/G5 unblocked | resolved |
| 8 | ~~Is the portal staff-only, or do patients log in too?~~ **RESOLVED 2026-07-28: staff-only. Patients never log in. The patient voice is a bug throughout, not an audience.** A patient-facing portal for requesting personal records may be added later; it is explicitly not to be designed for now. See §2. | — | resolved |
| 4 | ~~New frontend as a second compose service vs a route group behind a flag.~~ **RESOLVED 2026-07-30 by implication of #2: second compose service** (port 3071). A route group inside the existing Next.js app cannot host a SvelteKit application, so the option ceased to exist rather than losing on merit. ADR 0012 §1. | — | resolved |
| 5 | Component gallery: Claude Design (`claude.ai/design`, needs the `/design-sync` skill which is not installed here, and is a second non-git source of truth) vs in-repo Histoire/Storybook (handoff-deliverable). Deferred until real primitives exist. ADR 0013 §7 notes Storybook's Vitest integration would reuse the harness rather than replace it, so deferring costs nothing. | P3 | after G1 |
| 10 | **E2E coverage for the five `driven repro` requirements** (`FE-R1`, `R6`, `R14`, `R20`, `R25`). ADR 0013 §2 adopts no E2E suite: against a stub it proves less than the contract fixture, and against a live stack it puts patient-shaped data into CI traces/screenshots — a PHI-boundary call, not a tooling one. **Decided twice on 2026-07-30**: deferral overturned by the user ("E2E will be essential"), then re-deferred by the user on recalling the artifact PHI surface. Not rejected on merit — E2E is the only level that sees a composition defect, which is exactly the intake break's shape — so this stays open with the triggers ADR 0013 §2 names. | nothing today; the gates absorb it | a P6 multi-step flow, or the driven-repro list outgrowing a reviewer; needs its own ADR for artifact retention |
| 6 | Responsive behaviour is unverified — Chrome `resize_window` would not shrink below ~1500px this session, so F6 (mobile nav vanishing <720px) has unknown status. | P0 wireframes | re-test by another method |

**Pre-code decision set (added 2026-07-30).** Decisions #11–#15 below were being made implicitly at
implementation time; they are registered so P2 does not start on unstated choices. Together with #1 they
are the set that must close **before any frontend code is written** — the user's instruction, 2026-07-30:
hold docs out of upstream until every pre-code decision is made. **The set is CLOSED: #1 on 2026-07-30,
#12 then #11/#13/#14/#15 on 2026-07-31.** #12 produced three new requirements (`FE-R27`–`R29`), a new
ADR (0014), an amendment to ADR 0012 §3, and a newly reopened decision **#16** (patient surface) that
blocks nothing in P2. #3, #5, #6, #7, #9, #10 and #16 block their own later phase, not P2.

| # | Decision | Blocks | Unblocked by |
|---|---|---|---|
| 11 | ~~SvelteKit adapter and Dockerfile shape.~~ **RESOLVED 2026-07-31: `adapter-node`, multi-stage Dockerfile.** Build stage runs `npm ci` + build; runtime stage installs with `npm ci --omit=dev` and copies only `build/`, so neither Vitest nor the Chromium binary reaches the shipped image — the promise ADR 0013's Consequences already made. `adapter-node` is now forced rather than presumptive: §8 #12's server-held session needs a Node server at runtime. The existing `frontend/Dockerfile` (bare `npm install`, devDependencies shipped) is **not** the template. | — | resolved |
| 12 | ~~Auth token storage in the new app.~~ **RESOLVED 2026-07-31: the token is held by the portal's server layer and reaches the browser only in an `httpOnly` cookie** (`FE-R27`), with a 10-minute idle automatic logoff (`FE-R28`). Recorded in `adr/0014-frontend-session-and-automatic-logoff.md`. **This row previously said cookies were not an option — that exclusion was over-broad and is withdrawn.** ADR 0012 §3's stated reason is `require_session` *accepting* a cookie; that is the gateway hop, which still receives `Authorization: Bearer` unchanged. A cookie between the browser and our own BFF touches no auth boundary. §8.4 holds the reasoning; ADR 0012 §3 is amended. | — | resolved |
| 13 | ~~New app's directory name, compose service name and Makefile targets.~~ **RESOLVED 2026-07-31: `portal`.** Directory `portal/`, compose service `portal` on 3071, Makefile target `make portal-dev`. Chosen because CLAUDE.md §1/§8 already calls this product "the portal", so `frontend` keeps meaning the legacy Next.js app for as long as both exist and no path is ambiguous. | — | resolved |
| 14 | ~~What P2 actually builds.~~ **RESOLVED 2026-07-31: login plus the minimum intake path** — `FE-R1`–`R3`, `R15`, `R16`, `R21`, `R22`, and the new `FE-R27`–`R29`. Not the four-step wizard: G2 is contract truth and harness, and wizard UI decided before the P3 design system exists is UI built twice. **Sub-question answered separately 2026-07-31, having been orphaned when this row closed: `insurance.policy_holder`** — §8.1 routed it here and this resolution never mentioned it. **The new form drops the free-text field and collects `policy_holder_is_self` as a checkbox**; reasoning and the measurement behind it are in §8.1. | — | resolved |
| 15 | ~~Lint gate: `svelte-check` alone, or eslint as well.~~ **RESOLVED 2026-07-31: both.** `svelte-check` for types and template correctness, eslint for what a compiler does not cover (unused bindings, import hygiene, the a11y rules the Svelte compiler does not emit). ADR 0012 scored `FE-R17` partly on compiler-level a11y; eslint is what makes `FE-R17` a gate rather than a subset of it. **CORRECTED same day by measurement (§8.5): the last clause is false.** `eslint-plugin-svelte@3.22.0` ships 85 rules and **zero** a11y rules — its `valid-compile` rule only re-surfaces the same compiler warnings — so eslint cannot widen `FE-R17`, and the subset stays the subset. The decision to run both **stands** on its other grounds (unused bindings, import hygiene, `no-at-html-tags`, which matters for ADR 0014 gap #3); only its a11y justification is withdrawn. The accessible-name gap goes to ADR 0013 gap #9. | — | resolved, one premise corrected |
| 16 | **Patient-facing surface — reopened 2026-07-31 by user, having been settled staff-only on 2026-07-28.** Not a re-litigation: the driver is a possible near-term client commitment, which is new information. The binding constraint is **not** frontend — it is **D11**. `GET /patients/{id}/records` checks only "is logged in" and IDs are sequential, so a patient account reads every other patient's chart; patient login therefore cannot ship before session→`patient_id` binding, which is W4 auth work behind CLAUDE.md §6 approval and G4. Three further consequences: unmanaged/family-shared devices make `FE-R28`'s automatic logoff non-negotiable rather than prudent; a shared origin means an XSS in the patient surface reaches staff credentials, which `FE-R27` contains and a separate origin would contain better; and "patient" is a different **principal class**, not a staff role, so §8.3's three tiers do not describe it and `config/roles.yaml` would gain a non-staff principal. §2's out-of-scope bullet is amended accordingly. **The origin half is now DECIDED (2026-07-31): two origins, `adr/0015-portal-origin-and-audience-separation.md`** — separate hostnames, host-only cookies (`FE-R30`), `ORIGIN` from runtime env (`FE-R31`), and the patient surface kept out of the staff app's route tree. Patient **authentication** stays blocked on D11; ADR 0015 §4 is explicit that nothing in it makes a patient login safe to ship. | nothing in P2 — `FE-R27`–`R29` already survive it, and `FE-R30`/`R31` are P2 work | D11 session binding (W4/G4), then a user call on the real hostnames and who terminates TLS |
| 17 | **AI feature surfaces — RESOLVED 2026-08-01 (user): build them as P7, immediately after G5.** Found while checking the P2 mockups against W1–W3. Three client asks were LLM-shaped; the UI status is one built, one never built, one deliberately not built. **W1** — "a little assistant that drafts a patient-friendly version of our intake instructions… *get something on the screen this week*". Backend `POST /ai/intake-instructions`; UI exists **only** in the legacy portal (`frontend/app/intake/page.tsx:141`). **W3** — "a little **chat assistant** that checks a patient's eligibility and keeps track of the visit context". Backend `POST /ai/visit-chat` + ADR 0011 visit memory; **no UI has ever existed** — `frontend/app/api/ai/` contains one directory. The client asked for a screen and the deliverable shipped headless. **W2** — "a retrieval helper that surfaces the most relevant past records the moment they open a chart". Correctly redirected: the decoded finding was duplicate/fragmented charts, so `w2.md` §4 delivers an eval harness plus an MPI ADR. The ask stays unmet **by decision**, and P7 does not revive it. **How this stayed invisible:** neither `w1.md` nor `w3.md` §4 lists a UI deliverable — "frontend", "portal", "UI" and "screen" appear across W1–W3 exactly once, inside W1's verbatim client quote — and `visit-chat`/`intake-instructions` appear in **zero** files under `docs/todo.md`, `docs/debt-log.md` and `docs/status/`. The client's own Jira export holds four tickets, all workflow defects, none AI, so no client-side artifact would ever surface the gap. **P7 scope:** re-home W1's checklist on the new portal and build W3's assistant a surface for the first time. Requirements are written when P7 is designed, not here — this spec is design-first and specifying unscreened UI would break its own discipline. Note `/ai/*` is the only vendor-egress path (CLAUDE.md §6, D13) and W8's de-identification gap (D14) is open, so P7 inherits a PHI-boundary review that P0–P6 do not carry. | P7 / G6 | resolved — scheduled, not yet designed |

### 8.1 Why the intake fix is not frontend-only (verified 2026-07-28, extended 2026-07-30)

Two of the three mismatches are frontend-only: concatenate `name`, rename `carrier` → `payer_name`.
`FE-R2`'s `detail`-body guard is frontend-only as well.

`consents` is not. `ConsentKind` is a closed three-value enum — `npp_ack`, `treatment_consent`,
`roi_consent` — and the form collects four consents. **Financial responsibility** and
**electronic communications** have no representation, so a frontend-only fix clears the 422 by
silently discarding two consents, one of them a financial attestation. Current behaviour is worse
than the `FE-R11` label bug: the form collects that attestation, mislabels unanswered as
"Declined", and throws it away.

The enum is closed as a **PHI control**, not as validation — its docstring records that an open
string list allowed `"Jane Doe DOB 1985-03-12"` to reach the intake log, which pattern redaction
does not scrub. Widening it is therefore a deliberate touch to a documented PHI boundary, but a
cheap one:

- Add two values to `ConsentKind`; update the `consents.kind` comment in `db/schema.sql`.
- **No migration.** `consents.kind` is plain `TEXT`; `schema.sql` contains no `CHECK` constraint.
- Enum-referencing tests: `tests/test_intake_schemas.py`, `tests/test_redaction.py`. `FE-R22`
  exists because the thing to prove after widening is that the rejection test still
  *discriminates* — a widened set that quietly accepts free text reopens the leak.

The strictly-frontend alternative is to stop collecting those two consents until the backend can
store them. Preferred: widen the enum rather than delete a legal attestation from the form.

**CHOSEN 2026-07-30 (§8 #1): widen the enum.** The two new values, spelled here as the single
source the code, the debt log and the fixture must all match:

```
financial_responsibility_ack
communications_opt_in
```

Giving `ConsentKind` five members: `npp_ack`, `treatment_consent`, `roi_consent`,
`financial_responsibility_ack`, `communications_opt_in`. Facts recorded so they are not
re-derived under implementation pressure:

- **No migration, confirmed against the code**, not assumed: `db/schema.sql:121` declares
  `kind TEXT` with no `CHECK`, and `services/intake-service/models.py:44` mirrors it as
  `Column(Text)`. Both carry a trailing comment listing the accepted kinds; **both must be
  updated**, or the next reader trusts whichever is stale.
- The enum docstring must still read as a PHI control after widening. The closed-set *reason* is
  unchanged; only the set grew.
- `FE-R22` is a **re-proof, not a re-run**: mutate `ConsentKind` to a bare `str` locally and
  confirm `tests/test_intake_schemas.py:46` (`test_consents_reject_free_text_phi`) and `:54`
  (`test_consents_reject_unknown_identifier`) both fail. A green suite against a widened set
  proves nothing on its own. `tests/test_redaction.py:134` carries a note about the enum — check
  it still reads true.
- Whether the widening gets its own ADR or a section in P2's ADR is decided when that PR is
  written (§6 requires an ADR per phase where a non-trivial decision was made).

**A fourth mismatch, found 2026-07-30 and not in the table above.** `insurance.policy_holder` is
collected and sent by the current form but has **no schema field and no DB column**
(`services/intake-service/models.py`, `InsuranceCoverage`), so it is silently dropped — same class
as the two consents, but not a consent.

**RESOLVED 2026-07-31 (user): the new form drops the free-text field and collects the bit
directly** — a "Policy holder is the patient" checkbox supplying `policy_holder_is_self`. What made
this cheap, measured rather than assumed: the *only* consumer of the field is
`frontend/app/intake/page.tsx:147`, `policy_holder_is_self: !ins.policy_holder` — a **boolean
derived from emptiness**. The name string itself reaches nothing but the Review-step display at
`:366`; everything downstream (`services/ai-assistant/schemas.py:66`, `templates.py:92`,
`services/gateway/app.py:446`) only ever sees the bool. So the AI checklist needs one bit, not a
name, and dropping the field costs it nothing.

Grounds: `FE-R21`'s principle — shall not collect what cannot be stored — generalises, and the
field is PHI-shaped free text, so not collecting it is strictly better under D1/D3. Unlike the
financial-responsibility consent, nothing legal is lost, so there is no reason to widen the
backend for it. **Accepted cost:** the Review step no longer shows a policy-holder name, and a
future "policy holder differs from the patient — who?" requirement needs both the field and a
column. Recorded in `docs/debt-log.md` rather than left implicit. Reversible: the checkbox stays
and the name returns beside it if a column is ever added.

**No new requirement for this, by decision (user, 2026-07-31).** `FE-R21` covers consents only, and
nothing in §5 generalises it to non-consent fields — deliberately. The **fixture is the
enforcement**: a `policy_holder` key in the payload fails `FE-R3`'s shared assertion, which is a
tighter gate than a prose requirement would be. Do not re-open this as a missing `FE-R`.

Superseded pointer: this question was routed to **decision #14**, which closed on a different
question (what P2 builds) without covering it.

**Consents recording, worth knowing before the form is built.** `_record_consents`
(`services/intake-service/app.py:158`) inserts one row per accepted kind, and the `consents` table
has **no status column** — so "declined" and "never asked" are indistinguishable in the data by
construction. Presence plus `signed_at` is the entire record. That is adequate for an attestation
and is the second reason no migration is needed; it is also why `FE-R11` is a UI obligation the
data cannot help with. The current Review step gets this wrong at
`frontend/app/intake/page.tsx:372-373`. Adding a `status` column is **out of scope** for P2.

### 8.2 Reserved

### 8.3 Role model — what already exists (verified 2026-07-28)

Role plumbing is already complete end to end, and **nothing branches on the value**:

```
users.role TEXT NOT NULL DEFAULT 'staff'      db/schema.sql:19
  → create_session(user.username, user.role)  services/gateway/app.py:187
  → Redis session hash {username, role}       services/gateway/security.py:278
  → /login response user.role                 services/gateway/app.py:192
  → PortalUser.role                           frontend/app/lib/types.ts:6
  → rendered as the header badge              frontend/app/components/AppShell.tsx:188
```

All 12 seeded users are `staff`. `config/roles.yaml` defines one role granting everyone
`records.read` (clinical notes included) and `disclosures.read`. The only service-side use of the
value is `create_session`; there is no `role == "staff"` comparison anywhere, so changing role
values breaks nothing.

| Tier | What it is | Cost | Gate |
|---|---|---|---|
| 1 | Neutral copy — stop addressing staff as the patient | none beyond copy | G3 (`FE-R13`) |
| 2 | **Real role values in `users.role` + role-driven navigation.** Seed generator emits distinct roles, `roles.yaml` gains definitions, frontend branches on the role it already receives. No auth change, no migration, no gateway touch. | small | G3 (`FE-R14`, `FE-R23`) |
| 3 | Per-action enforcement in the gateway. W9's work pulled forward. | auth boundary | **G4** |

Tier 2 is legitimate and is **not** the client-side-inference antipattern; the distinction is
provenance — the role is real server data, not a username→role map invented in the browser. The
condition is honesty about what it is: `require_session` still only checks "is logged in", so any
signed-in user can still reach any endpoint directly. `FE-R23` requires that be labelled
navigation-only and kept on the debt register. Tier 2 does not close D8.

### 8.4 Session handling — why the cookie exclusion was withdrawn (2026-07-31)

The reasoning behind §8 #12 lives in `adr/0014-frontend-session-and-automatic-logoff.md`. Two things
recorded here because they are corrections to this document rather than ADR content:

**The exclusion was a conflation, not a judgement call.** §8 #12 and ADR 0012 §3 both ruled out
`httpOnly` cookies as "auth behaviour → §6 approval + G4". ADR 0012 §3's own stated reason is
`require_session` **accepting** a cookie. There are two hops, and only one of them is the auth
boundary:

```
browser  ──httpOnly cookie──▶  portal (SvelteKit server)  ──Authorization: Bearer──▶  gateway
         ^^^^^^^^^^^^^^^^^^                                ^^^^^^^^^^^^^^^^^^^^^^^
         our own BFF; no auth boundary                     unchanged; require_session untouched
```

The gateway contract is byte-for-byte what it is today. Only the browser↔BFF hop changes, and the
portal→gateway invariant (CLAUDE.md §1) already guarantees the browser never talks to the gateway,
which is precisely what makes a server-held token possible. Cookies carrying auth to our own server
introduce CSRF, which SvelteKit's `csrf.checkOrigin` covers by default — do not disable it.

**What the external convention actually is,** so it is not re-searched: automatic logoff is
45 CFR 164.312(a)(2)(iii), *addressable* — implement it or document an equivalent, with a risk-based
interval and no mandated number (2–5 min shared screens, 10–15 min private offices is the practised
range). Epic MyChart logs out at 10–15 minutes idle depending on the health system, which is the
number an auditor anchors on; `FE-R28` picks **10**. OWASP's Authentication Cheat Sheet warns against
session identifiers in `localStorage` (there is no `httpOnly` equivalent), and SMART on FHIR guidance
for browser apps is explicit: short-lived tokens, never browser local storage, use `httpOnly` cookies
or server-side session storage. Today's portal (`frontend/app/lib/session.ts:29`) does the named
antipattern.

**Two things `FE-R27`/`FE-R28` do not close.** D10 stays open: the Redis session still has no TTL, so
`FE-R28` bounds the credential's life only for operators who go idle inside this app — a token
captured before the timer fires is still valid forever, and only the gateway can fix that. And
`FE-R27` moves the credential out of JavaScript's reach without making XSS harmless: script on the
origin can still *use* the cookie by making requests.

**One consequence for the role model.** `session.ts:30` currently caches `PortalUser` — role
included — in `localStorage`, and `AppShell.tsx:188` renders the badge from that cache. Under
`FE-R27` the new portal persists **no** authorization-relevant value client-side; role is read from
`GET /me` (`services/gateway/app.py:202`), which returns it from the Redis session. This matters at
§8.3 tier 2: a storage-cached role is operator-editable, so role-driven navigation derived from it
would be the provenance antipathy §8.3 warns about wearing server clothes.

### 8.5 Pre-P2 audit corrections (2026-07-31)

An adversarial audit of ADRs 0012–0014 and this spec, run before any frontend code exists, framed as a
postmortem of a rebuild that had gone badly. Nine findings changed a document; four were measured rather
than argued. The ADRs carry the reasoning in their own `Audit-round corrections` sections — recorded
here only where this file's own text changed, so there is one copy of each correction.

**What was measured, so it is not re-derived.** Probe on `svelte@5.56.8` + `svelte-check@4.7.4`,
13 cases, `--fail-on-warnings` (exit 1 with the flag, 0 without, so the flag is load-bearing):

- **Caught:** icon-only `<button>` and `<a>` with no accessible name (`a11y_consider_explicit_label`);
  `<label>` not associated with a control; missing `alt`; click handlers on static elements.
- **Silent:** `<input>`, `<textarea>`, `<select>` with no accessible name; `<button {...rest}>` (spread
  defeats the check); `aria-label={maybeUndefined}` (presence satisfies it, the value is never
  evaluated); `<div role="button">` with no name.
- `eslint-plugin-svelte@3.22.0`: **85 rules, zero a11y rules.**
- Harness deps on Node 22: `vitest@4.1.10` (`^20 || ^22 || >=24`), `playwright@1.62.1` (`>=20`),
  `svelte-check@4.7.4` (`>=18`) — all fine, but `@vitest/browser` peers `vitest` at an **exact**
  version, so the trio must be bumped together.

**Changes to this file:**

1. **`FE-R2`'s wording missed the shape the gateway actually returns on a transport failure.** Verified:
   `_post`/`_get` (`services/gateway/app.py:1152-1167`) return `r.json()` at HTTP 200 regardless of
   downstream status, so a downstream 422 arrives as 200 + `{"detail": …}` — which the original wording
   caught — but a transport failure arrives as 200 + `{"error": str(e)}`, with no `detail` and a 2xx
   status, which it did **not**. The `error` branch is now named. Note for whoever writes the test: this
   branch is **not** reachable by a slow payer (`ELIGIBILITY_TIMEOUT_SECONDS` defaults to 8s against
   `_post`'s 30s httpx timeout, so ADR 0010 returns `pending`); it is reachable when intake is
   down or restarting. The fixture is "intake unreachable", not "payer slow".
2. **`FE-R17`'s scope is narrowed to buttons and links** — what the gate measurably enforces. The
   requirement previously said "an interactive element", which the mechanism does not deliver, and an
   unenforceable requirement at a gate is worse than a smaller honest one. The uncovered surface (form
   controls, spread attributes, `role="button"`) is ADR 0013 gap #9, whose closer is `axe-core` decided
   at P3 against real primitives. **`FE-R17` must not be cited as accessible-name coverage for form
   controls.**
3. **`FE-R21`'s verification changes from set equality to a subset plus a pinned enum.** Set equality
   was unsatisfiable: the form collects four consents and the widened `ConsentKind` has five, because
   `roi_consent` is collected by no UI at all. Subset is the correct operator for "shall not collect a
   consent that cannot be stored"; the enum-pinning assertion is what protects the PHI control the enum
   *is* (§8.1). ADR 0013 §3 carries both.
4. **`FE-R27`–`FE-R29` state which half is CI-proven and which is driven at the gate.** ADR 0013's
   harness runs component tests with no server, no database and no network, so a requirement verified
   "after login" cannot run in it — a contradiction between ADR 0013 §7 and ADR 0014's Consequences,
   written a day apart. E2E is **not** adopted to close it (ADR 0013 §2's PHI-boundary reason is
   unchanged); the evidence is split per requirement and the driven halves must be **recorded** at G2.
5. **`FE-R30` and `FE-R31` are new**, from ADR 0015: host-only cookies and a runtime-resolved origin.
   Both sit at G2 because both are properties of the login surface P2 builds.
6. **§8 #15's a11y justification is withdrawn** (the decision to run eslint stands on other grounds).
7. **§8 #16's origin half is decided** by ADR 0015; patient authentication remains blocked on D11.

**Not changed, and deliberately so:** the gate order, G2's blocking position, the fixture's location,
the two-project harness split, the 10-minute interval, and every scope exclusion in §2. The audit found
no reason to move any of them.

## 9. Traceability

- **D4** (eligibility/error-swallow): `FE-R2`, `FE-R20`, and the gateway half flagged in §7.
- **D6** (HL7 AL1/RXA dropped): `FE-R5` — makes the gap visible instead of indistinguishable
  from "no allergies", which is the patient-safety half of that debt.
- **D8** (single role): `FE-R13` treats the symptom; `FE-R14` + `FE-R23` deliver role-driven
  navigation without closing the debt; only tier 3 (§8.3) closes it, gated at G4.
- **D11** (IDOR): `FE-R6` read-path affordance only. The fix is W4's.
- **D1/D3** (PHI in logs, plaintext PHI): `FE-R16`, `FE-R12`, and `FE-R29` — PHI cached in web
  storage is PHI at rest on a shared clinic workstation, a surface neither debt entry covers.
- **D10** (no session expiry): `FE-R27` removes the credential from JavaScript's reach; `FE-R28`
  bounds it for an idle operator. Neither closes D10 — the Redis session still has no TTL, which is
  the gateway's to fix. See §8.4.
- **D1** (PHI in logs): `FE-R16`, and `FE-R22` — the consent enum is a PHI control, so widening it
  must not weaken the boundary that keeps free text out of the intake log.
- **D11 (IDOR), second entry:** `FE-R30`/`FE-R31` do not touch it, but ADR 0015's origin split is
  justified *by* it — a staff credential borrowed by script on a shared origin reads every chart
  precisely because IDs are walkable and sessions never expire. The fix is still W4's.
- No debt ID: `FE-R1`, `FE-R3`, `FE-R7`–`R9`, `FE-R11`, `FE-R15`, `FE-R17`–`R19`, `FE-R21`, `FE-R30`,
  `FE-R31`, `FE-R32`, `FE-R33` — new scope or process requirements, not previously documented gaps. `FE-R33`
  is the newest: the swallowed-consent-insert defect behind it was found on 2026-08-01 while checking the
  P2 mockups against the code, and is recorded in `docs/design/03-key-flows.md` flow 1 `✗g` rather than
  as its own D-number. `FE-R1`/`FE-R3` cover a
  defect that was never in the register; §4 deliverable 6 adds it.
