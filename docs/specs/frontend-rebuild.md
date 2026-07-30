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
4. The new frontend itself, phased per §6.
5. A superseding note on ADR 0008 if `react-day-picker` is dropped.
6. `docs/debt-log.md` entry for the intake contract break.

## 5. Requirements (EARS)

Phase column maps to §6. `insp.` = verified by inspection/documented repro, stated deliberately.

| ID | Requirement | Verification | Debt | Gate |
|---|---|---|---|---|
| `FE-R1` | WHEN a valid intake payload is submitted, the portal shall display the `patient_id` returned by the service. | contract test + driven repro | — | G2 |
| `FE-R2` | IF an upstream response carries a non-2xx status **or** a body containing an error `detail`, THEN the portal shall present the operation as failed and shall not display a success message. | JS test, both branches | D4 | G2 |
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
| `FE-R15` | The repository shall retain the original portal as a separately runnable service until `FE-R1`–`FE-R3` pass on the new frontend. | `make config` + both services up | — | G2 |
| `FE-R16` | IF an error is surfaced to the operator, THEN the message shall not contain PHI. | adversarial test (CLAUDE.md §5 negative-test rule) | D1 | G2 |
| `FE-R17` | The build shall fail when an interactive element lacks an accessible name. | CI job | — | G3 |
| `FE-R18` | The design phase shall produce, for each seeded operator role, the tasks performed per shift and the data each task requires. | `docs/design/` review | — | G0 |
| `FE-R19` | The framework decision shall be recorded in an ADR scoring at least two candidate stacks against `FE-R18`'s output, stating the continuity cost of replacing Next.js. | ADR review | — | G1 |
| `FE-R20` | WHEN an intake is submitted successfully, the portal shall display the eligibility result already present in the service response. | component test + driven repro | D4 | G3 |
| `FE-R21` | Every consent the intake form collects shall be persistable by intake-service; the portal shall not collect a consent that cannot be stored. | contract test over the consent set | — | G2 |
| `FE-R22` | IF a consent identifier outside the accepted closed set is submitted, THEN intake-service shall reject the request at the boundary. | existing adversarial test, re-proven to discriminate after the set is widened | D1 | G2 |
| `FE-R23` | WHERE role-driven navigation is derived from `users.role` without gateway enforcement, the portal shall present it as navigation only, and the absence of per-action authorization shall remain recorded in `docs/debt-log.md`. | insp. + debt-log entry | D8 | G3 |
| `FE-R24` | The portal shall refer to the patient in the third person; no copy shall address the signed-in operator as the patient. | copy checklist in `docs/design/`, applied at review | D8 (surface of) | G3 |
| `FE-R25` | WHILE a patient is selected, the portal shall retain that patient as context across chart, appointment and ROI surfaces without re-entry. | driven repro | — | G3 |

## 6. Checkpoints / gates

Phases are sequential; **G2 blocks everything after it.**

| Gate | Phase it closes | Blocks | Artifact | Verified how | Signed by |
|---|---|---|---|---|---|
| **G0** | P0 Design: operators, tasks, IA, flows, wireframes, tokens | framework choice | `docs/design/` + Artifact | user review of the design set | user |
| **G1** | P1 Framework decision | all implementation | framework ADR (+ harness ADR after it) | ADR review; Next.js must be a genuine option that loses on stated criteria | user |
| **G2** | P2 Contract truth + harness | **every later phase** | contract fixture, both test jobs green, `FE-R1`–`R3`, `R15`, `R16` | `make test-docker` **and** driving the app; a 200 proves nothing here | user |
| **G3** | P3 Design system + P4 identity/search/forms | queue work | primitives + patient banner + name search | driven repro per `FE-R4`–`R7`, `R11`–`R13`, `R17`, `R20` | user |
| **G4** | P5 Role-aware shell | — | role model decision | **explicit human approval for an auth change (CLAUDE.md §6)**; needs `config/roles.yaml` + `users` + session + gateway enforcement, and both `db/schema.sql` and a new hand-synced migration | user, explicitly |
| **G5** | P6 Appointments/ROI queues | — | queue surfaces, tz fix | driven repro per `FE-R8`–`R10` | user |

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
| 1 | Intake contract break: own fix PR now, or folded into P2? It is a live client-facing defect, arguably W2/W5 territory. **Not a pure frontend fix** — see §8.1 below. **Standing open by user decision 2026-07-28: deferred past G0, because P0 decides what the intake form collects and therefore the consent set.** Mismatch is **inherited** from handoff commit `3663c4b`, not introduced by PRs #1–#17. | P2 sequencing | G0 output, then user call |
| 2 | ~~Framework: SvelteKit vs stay on Next.js.~~ **RESOLVED 2026-07-30: SvelteKit**, recorded in `adr/0012-frontend-framework-sveltekit.md` — scored against the discriminating requirements only, with Next.js as a genuine option that loses on `FE-R17` and form ergonomics and wins on continuity. Bundle size and "React caused the defects" are recorded there as **rejected** arguments. G1 still needs the ADR review. | — | resolved |
| 3 | Does the trainer's leeway extend to the role model (D8)? Three tiers, costed in §8.3 below. Tier 2 needs no auth approval and no migration. **Standing open by user decision 2026-07-28: deferred past G0, because P0 decides which role-specific surfaces exist and therefore which tier is needed.** | G4 / `FE-R14`, `FE-R23` | G0 output, then user call; tier 3 only, explicit auth approval |
| 9 | **Slot/appointment instants are stored wrong, so `FE-R8` cannot be satisfied frontend-side alone.** `db/seed/generate_seed.py:159,163,166` builds correct clinic wall-clock times (`08:00`, 8 per day) and emits them as bare strings into `timestamptz` with the Postgres session at `Etc/UTC` — so 8:00 AM ET is stored as `08:00Z` instead of `12:00Z` (EDT, UTC−4). Rendering then uses `toLocaleTimeString(undefined, …)`, i.e. the **viewer's** zone, which is why slots read 03:00 on a CDT machine. Two separate fixes: correct the seed/ingest conversion (data, backend) and render in clinic time (`FE-R8`). `FE-R26` forbids the tempting frontend offset hack. | `FE-R8`, any day view | user call on who owns the data fix |
| 7 | **Queue surfaces have an unnamed backend dependency.** `GET /appointments` requires `patient_id`, so no day view / check-in queue is servable; a client-side fan-out is the D8 N+1 pattern. Either add a scoped read endpoint (additive, non-auth, at a seam) or descope the queues. Detail in `docs/design/01-operators-and-tasks.md` §4. | P6 / G5 | P0.2 IA |
| 8 | ~~Is the portal staff-only, or do patients log in too?~~ **RESOLVED 2026-07-28: staff-only. Patients never log in. The patient voice is a bug throughout, not an audience.** A patient-facing portal for requesting personal records may be added later; it is explicitly not to be designed for now. See §2. | — | resolved |
| 4 | ~~New frontend as a second compose service vs a route group behind a flag.~~ **RESOLVED 2026-07-30 by implication of #2: second compose service** (port 3071). A route group inside the existing Next.js app cannot host a SvelteKit application, so the option ceased to exist rather than losing on merit. ADR 0012 §1. | — | resolved |
| 5 | Component gallery: Claude Design (`claude.ai/design`, needs the `/design-sync` skill which is not installed here, and is a second non-git source of truth) vs in-repo Histoire/Storybook (handoff-deliverable). Deferred until real primitives exist. | P3 | after G1 |
| 6 | Responsive behaviour is unverified — Chrome `resize_window` would not shrink below ~1500px this session, so F6 (mobile nav vanishing <720px) has unknown status. | P0 wireframes | re-test by another method |

### 8.1 Why the intake fix is not frontend-only (verified 2026-07-28)

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

## 9. Traceability

- **D4** (eligibility/error-swallow): `FE-R2`, `FE-R20`, and the gateway half flagged in §7.
- **D6** (HL7 AL1/RXA dropped): `FE-R5` — makes the gap visible instead of indistinguishable
  from "no allergies", which is the patient-safety half of that debt.
- **D8** (single role): `FE-R13` treats the symptom; `FE-R14` + `FE-R23` deliver role-driven
  navigation without closing the debt; only tier 3 (§8.3) closes it, gated at G4.
- **D11** (IDOR): `FE-R6` read-path affordance only. The fix is W4's.
- **D1/D3** (PHI in logs, plaintext PHI): `FE-R16`, `FE-R12`.
- **D1** (PHI in logs): `FE-R16`, and `FE-R22` — the consent enum is a PHI control, so widening it
  must not weaken the boundary that keeps free text out of the intake log.
- No debt ID: `FE-R1`, `FE-R3`, `FE-R7`–`R9`, `FE-R11`, `FE-R15`, `FE-R17`–`R19`, `FE-R21` — new scope or
  process requirements, not previously documented gaps. `FE-R1`/`FE-R3` cover a defect that was
  never in the register; §4 deliverable 6 adds it.
