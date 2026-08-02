# P0.1 — Operators and task inventory

> Satisfies `FE-R18` (`docs/specs/frontend-rebuild.md`). Framework-agnostic.
> Written 2026-07-28. Closes at gate **G0** together with P0.2–P0.5.

---

## 1. Method and how to read the evidence grades

Three sources, all first-hand:

- **Driven walkthrough** of the running stack as `frontdesk` (2026-07-28) — every page, one full
  intake, two charts, appointments, ROI. Standing method for this project.
- **The system itself** — 12 seeded operator accounts (`db/seed/generate_seed.py`), the 20 gateway
  endpoints, the schema.
- **The client's own words** — `docs/handover/jira-tickets.md`, four tickets from four different
  reporters (Front Desk, Front Desk Lead, Dr. Nguyen, Billing).

Every claim below is graded, because a design doc that blurs the line becomes fiction people
later cite as research:

| Grade | Meaning |
|---|---|
| **[E]** | Evidence — observed in the running system, the schema, or a client ticket |
| **[I]** | Inference — standard clinic practice, consistent with the evidence, **not confirmed** |
| **[?]** | Unknown — needs the user or a real operator to answer (collected in §6) |

**What this is not.** These are operator archetypes derived from seeded accounts and observed
behaviour, not interview-based personas. No one at Riverbend has been interviewed. Anything
depending on real workflow detail is marked **[I]** or **[?]** and must not harden into a
requirement without confirmation.

## 2. Operator roster

12 seeded accounts, all with `role = 'staff'` **[E]**. They collapse into six archetypes:

| Archetype | Seeded accounts | Evidence for the grouping |
|---|---|---|
| **Front desk / registration** | `frontdesk`, `jpark` (Registration), `rdelgado` (Registration) | **[E]** account names; reporter of RIV-088 and RIV-141 |
| **Clinician** | `drnguyen`, `drpatel`, `drlee`, `nurse_kc` (RN) | **[E]** account names; Dr. Nguyen reports RIV-160 |
| **ROI clerk** | `roiclerk` (Dana White, ROI Clerk) | **[E]** account name; ROI is a distinct page |
| **Billing** | `billing1` (Tom Reyes, Billing) | **[E]** account name; reporter of RIV-175 |
| **Lab intake** | `labtech` (Lab Intake) | **[E]** account name; ORU/lab records exist in schema |
| **Admin / oversight** | `mokonkwo` (COO), `itadmin` (Helix Support) | **[E]** account names |

Three of the six — front desk, clinician, billing — are on record complaining about this system.
That is the strongest signal available about where to aim **[E]**.

## 3. Task inventory

Per archetype: what they arrive needing, what repeats all shift, what must never go wrong. The
**Servable today** column is the honest constraint — a task needing data no endpoint returns is a
backend dependency, not a design choice.

### 3.1 Front desk / registration

| Task | Frequency | Data required | Servable today |
|---|---|---|---|
| See who is arriving and who has checked in | **arrival, then continuously [I]** | today's appointments across all patients | **No** — `GET /appointments` **requires** `patient_id` **[E]** |
| Register a new patient | many/shift **[I]** | demographics, insurance, consents | **Broken** — every submission 422s and the UI reports success **[E]** |
| Confirm coverage is active | every registration **[E]** RIV-088 | eligibility result | **Partly** — result is already in the intake response and the UI discards it **[E]** |
| Find an existing patient | constantly **[I]** | name / DOB search | **Yes** — `GET /patients?q=` exists; **no UI uses it** **[E]** |
| Book / move / cancel an appointment | many/shift **[I]** | open slots, existing appointments | **Partly** — `GET /slots` has no date filter; times render 3–6 AM **[E]** |
| Correct a typo just entered | often **[I]** | edit path back into a submitted intake | **No** — no update endpoint; wizard has no per-step edit **[E]** |

Must never go wrong: **registering under the wrong existing patient** (creates the duplicate-chart
condition behind RIV-160) **[E]**; telling a patient they are covered when they are not **[I]**.

### 3.2 Clinician

| Task | Frequency | Data required | Servable today |
|---|---|---|---|
| Confirm the chart is the right patient | **every single chart open [I]** | name, DOB, MRN, sex | **No** — the chart displays none of these; 1042 and 1043 look alike **[E]** |
| Check allergies before prescribing | every encounter **[I]** | allergy list | **No** — AL1 dropped (D6); UI shows no allergy region at all **[E]** |
| Read the visit history in date order | every chart open **[I]** | encounters with dates | **No** — encounters render as "Dr. Patel · 1 record", no dates **[E]** |
| Trust that one patient has one chart | always **[E]** RIV-160 | MPI / merged view | **No** — no MPI (D5) **[E]** |
| See their own day's schedule | arrival **[I]** | appointments by provider | **No** — no by-provider appointment query **[E]** |

Must never go wrong: acting on **another patient's chart**, or on a chart that silently omits
allergies. RIV-160 is a clinician reporting exactly this class of confusion **[E]**.

### 3.3 ROI clerk

| Task | Frequency | Data required | Servable today |
|---|---|---|---|
| Work the queue of pending requests | continuous **[I]** | all requests, any status | **Yes** — `GET /roi/requests` takes `patient_id` **optionally** **[E]** |
| Confirm the right patient before disclosing | every request **[I]** | patient identity | **No** — form takes a bare numeric ID, shows no name **[E]** |
| Record the 164.508 authorization | every disclosure (legally) **[E]** | authorization capture | **No** — D12, no enforcement, no accounting **[E]** |
| Fulfil and track what was sent | every request **[I]** | fulfilment state, audit trail | **Partly** — `fulfill` exists; the audit table is mutable (D2) **[E]** |

Must never go wrong: **disclosing the wrong patient's records**, or disclosing without
authorization. Both are currently possible with no UI friction **[E]**.

### 3.4 Billing, lab intake, admin

Thinner, and deliberately so — no billing or lab surface exists in the portal (nav shows
**Billing — SOON** and **Messages — SOON**) **[E]**.

- **Billing** reported RIV-175 (double confirmations, two people one slot) **[E]**. That is the
  booking race (D5). Billing has no portal surface to work from at all.
- **Lab intake** — lab records exist in the schema and render as records; no lab-specific surface.
- **Admin / oversight** — COO and IT support share the same `staff` role and see the same UI as a
  clinician, including clinical notes (`roles.yaml` grants `records.read` to everyone) **[E]**.
  That is D8 stated plainly: the COO and the IT contractor have chart access by configuration.

## 4. Capability inventory — what the gateway can serve

20 endpoints **[E]**. What matters for design:

**Already available and unused by any UI:**
- `GET /patients?q=&limit=&offset=` — paginated patient search. **Directly satisfies `FE-R6` with
  zero backend work.** The ID box was never necessary.
- `GET /records/search?q=` — unscoped by patient, which is the D11 concern W4 owns.
- `GET /roi/requests` — `patient_id` optional, so a cross-patient ROI work queue is buildable now.

**Not servable — needs backend work:**
- ~~**Today's schedule / check-in queue.**~~ **Servable as of 2026-08-01: `GET /schedule`** was added
  for exactly this (frontend-rebuild §8 #7). One clinic-local day across all patients, one joined
  query, paginated, patient name and MRN included so the queue can identify who is being called.
  `GET /appointments` still requires `patient_id` and is unchanged — the new endpoint sits beside it.
- **A clinician's own day.** Still not served. `GET /schedule` shipped without a `provider_id`
  filter, and the omission is deliberate (codex PR #26 r1): appointments store only a provider
  *name*, so the only route to a provider id is `appointments.slot_id` → `slots` — a column with
  no foreign key, written by a `book()` that never checks the slot exists. Filtering through that
  join is an inner join over an unenforced reference, so an appointment with a missing or stale
  slot appears in the all-day queue and vanishes from the per-provider one, silently. A real
  by-provider view needs provider identity stored on the appointment; that is a migration and
  belongs with the RIV-175 slot/appointment work (W5).
- **Date-filtered slots.** `GET /slots` takes `provider_id` and `limit` only, no date range. Day
  views and past-slot suppression (`FE-R10`) must filter client-side over up to 200 rows.
- **Editing a submitted intake.** No update endpoint exists.

**Consequence for sequencing:** ~~P6 (queues, gate G5) has a backend dependency the spec does not
name.~~ **Closed 2026-08-01** by adding `GET /schedule` — additive, non-auth, at a seam, as this
section proposed. P6 is unblocked. Two things this section got slightly wrong and are corrected
above: the ROI queue was never blocked (`patient_id` is optional there), and descoping would have
cost new value rather than parity, since the legacy portal has no day view either.

## 5. What the walkthrough changes about the client's tickets

- **RIV-088 ("spins 4–5s, doesn't fail, just feels slow")** — the reporter's premise no longer
  holds. Registration through the portal does not merely feel slow; it never creates a patient and
  reports success. Both sides of the payload mismatch originate in the same Helix handoff commit
  `3663c4b`, so this is **inherited, not a regression from PRs #1–#17** **[E]**. Whether any patient
  was *ever* created through the portal UI is **[?]** — the 261 seeded patients come from the seed
  generator, not the UI.
- **RIV-160 (allergies differ per chart)** — has a second, purely presentational cause nobody
  filed: the chart shows no allergy region at all, so "none" and "not captured" are
  indistinguishable to a clinician **[E]**. Fixing MPI and HL7 without fixing that still leaves
  the clinician unable to tell absence from silence.
- **RIV-175 (double booking)** — untouched by frontend work; it is the check-then-insert race (D5).
  Frontend can reduce *incidence* (suppress past slots, disable the button on submit) but must not
  be presented as the fix.

## 6. Open questions for P0.2 — cannot be inferred

1. ~~Is the portal staff-only, or do patients log in too?~~ **ANSWERED 2026-07-28: staff-only,
   patients never log in.** The patient voice is a bug throughout. A patient-facing surface for
   requesting one's own records may come later and is explicitly not to be designed now.
2. Do front desk and registration (`jpark`, `rdelgado`) do the same job, or is registration a
   back-office role with a different surface?
3. Does `nurse_kc` (RN) need the clinician surface or a distinct one?
4. Should billing and lab intake get surfaces in this rebuild, or stay "SOON"?
5. Clinic timezone and hours — needed for `FE-R8` and any day view. Slots are stored such that
   they render 3–6 AM locally **[E]**; the correct clinic-local intent is unknown.
6. Is a back-office/admin surface in scope, given that COO and IT support currently see clinical
   notes?

---

**Next:** P0.2 information architecture, blocked on question 1.
