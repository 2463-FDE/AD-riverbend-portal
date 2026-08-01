# P0.3 — Key flows

> Follows `02-information-architecture.md`. Framework-agnostic. Written 2026-07-28.
> Closes at gate **G0**. Evidence grades: **[E]** observed, **[I]** inferred, **[?]** unknown.

---

## 0. Standing context

- **Staff-only**, patients never log in (settled 2026-07-28).
- **Clinic hours 08:00–17:00, `America/New_York`** (given 2026-07-28). "Today" and every day view
  are defined against that, not against the workstation clock.
- Patient context is set by **search only**; the identity banner is chrome (P0.2 §3).

Each flow below names its **failure paths explicitly.** That is the point of the exercise: the
defect that triggered this rebuild was a success message on a failed write, and it survived because
nobody had written down what failure looks like. A flow without failure paths is half a flow.

### Notation

`▸` operator action · `→` system response · `✗` failure path · `⛔` must never happen silently

---

## 1. Register a new patient  *(front desk · many per shift **[I]** · currently broken **[E]**)*

| # | Step | Data | Endpoint |
|---|---|---|---|
| 1 | ▸ Search first, to avoid creating a duplicate | name, DOB | `GET /patients?q=` |
| 2 | → Show possible matches before offering "create new" | name, DOB, MRN | — |
| 3 | ▸ Enter demographics | name, DOB, sex, SSN, phone, email, address | — |
| 4 | ▸ Enter insurance | payer, member id, group, plan, holder | — |
| 5 | ▸ Capture consents | the set the backend can store (see ✗c) | — |
| 6 | ▸ Review, with per-section edit | everything above | — |
| 7 | ▸ Submit | full payload | `POST /intake` |
| 8 | → Confirm **what was created**: patient identity + eligibility result, and that no MRN was assigned (see ✗f) | `patient_id`, `eligibility` | already in the response **[E]** |
| 9 | → Hand off into the patient surface | — | `/patients/:id` |

**Step 1 is new and is the point.** Today registration begins with a blank form **[E]**, which is
the duplicate-patient generator behind RIV-160 (D5, no MPI). Search-first does not fix MPI; it
removes the most common way a duplicate gets created.

**Failure paths**

- `✗a` **Write rejected.** `POST /intake` returns non-2xx, *or* 200 with an error `detail` body —
  the current live defect **[E]**. Present as failed, preserve every entered field, offer retry.
  ⛔ Never a success message. ⛔ Never a cleared form. (`FE-R1`, `FE-R2`)
- `✗b` **Eligibility unknown.** ADR 0010 returns `pending`/`unknown` on payer trouble, never a false
  `inactive` **[E]** (my probe returned `status: unknown` **[E]**). Show it as unknown with a
  re-check affordance. ⛔ Never render unknown as "not covered" — that turns a covered patient away.
  The re-check **reads without recording**: `_create_coverage` writes no `status`/`verified_at` and
  nothing updates them afterwards, so `insurance_coverages.status` keeps its `'unknown'` default even
  once the payer answers **[E]** (D4b). The answer is therefore true only on the screen showing it —
  no later shift, and nothing downstream, can see that coverage was confirmed.
- `✗c` **Consent not storable.** `ConsentKind` accepts three values; the form collects four **[E]**.
  Until the enum is widened, the form must not collect what cannot be stored (`FE-R21`).
  ⛔ Never accept a financial-responsibility attestation and discard it.
- `✗d` **Typo found after submit.** No update endpoint exists **[E]**. Pre-submit correction must be
  free (step 6). Post-submit is honestly unavailable — say so; do not fake an edit affordance.
- `✗e` **Duplicate suspected at step 2.** Operator needs a deliberate "this is a different person"
  action, recorded. **[?]** whether Riverbend has a duplicate-resolution policy.
- `✗f` **No MRN exists to confirm.** `_create_patient` never sets `mrn` and `IntakeResponse` carries
  no MRN field **[E]**; the only generator in the repo seeds existing rows (`db/seed/generate_seed.py:118`,
  format `M####`). Step 8 must state the absence, not omit the row — a front desk that expects an MRN
  needs to know one is not coming. ⛔ Never show a fabricated MRN on the confirmation. Steps 2 and
  flow 2 are unaffected: those patients are already registered and do have MRNs. **[?]** whether intake
  should mint one — entangled with RIV-160, since an MRN per registration numbers duplicates rather
  than preventing them.
- `✗g` **Consents partially written.** `_record_consents` commits one row per consent in its own
  transaction and swallows each failure, and the 201 is returned regardless **[E]** — a partial write
  is indistinguishable from a complete one. Step 8's count must come from the service response, never
  from submitted form state (`FE-R33`). ⛔ Never report a consent accepted on the strength of the form
  alone — that is `✗a`'s defect class one layer in.

---

## 2. Find a patient and open the chart  *(all clinical roles · constantly **[I]**)*

| # | Step | Data | Endpoint |
|---|---|---|---|
| 1 | ▸ Type a name or DOB into global search | query text | `GET /patients?q=` **[E]** exists, unused |
| 2 | → Result rows carrying enough to disambiguate: name, DOB, MRN, sex | — | — |
| 3 | ▸ Select a patient | — | — |
| 4 | → Identity banner pins; chart opens on encounters in date order | name, DOB, MRN, sex, allergy status | `GET /patients/:id`, `/patients/:id/records` |

**Failure paths**

- `✗a` **Two patients look identical in results.** Rows must carry DOB *and* MRN; name alone is not
  disambiguating (RIV-160 is literally a clinician confused between charts for one person **[E]**).
- `✗b` **Allergy data absent.** Render "not captured", never an empty region (`FE-R5`). AL1 is
  dropped upstream (D6) **[E]** — the clinician must be able to tell silence from "none".
- `✗c` **Wrong patient opened.** The banner is the only guard; it cannot be scrollable or collapsible
  (`FE-R4`). ⛔ Never a chart surface with no identity on screen — today's actual behaviour **[E]**.
- `✗d` **Search returns nothing.** Offer registration as the next step, carrying the typed name.

---

## 3. Book or move an appointment  *(front desk · many per shift **[I]**)*

| # | Step | Data | Endpoint |
|---|---|---|---|
| 1 | (patient context already set — never an ID box) | — | — |
| 2 | ▸ View this patient's existing appointments | date, time, provider, location, status | `GET /appointments?patient_id=` |
| 3 | ▸ Pick a slot within clinic hours | slots, filtered to future, rendered in clinic tz | `GET /slots` |
| 4 | ▸ Confirm | slot id, reason | `POST /appointments` |
| 5 | → Show the booked appointment with date and time | — | — |

**Failure paths**

- `✗a` **Slot taken between load and confirm.** Check-then-insert race, no UNIQUE on `slot_id`, no
  idempotency key (D5, RIV-175) **[E]**. The frontend must disable the action on submit and re-read
  after, and must present a conflict honestly. ⛔ Never present frontend guards as the fix for
  RIV-175 — that is a backend invariant (W5).
- `✗b` **Slot is in the past.** No booking action offered (`FE-R10`). Filtering is client-side:
  `GET /slots` takes only `provider_id` and `limit`, no date range **[E]**.
- `✗c` **Times are wrong.** Two independent defects, spec open decision #9 **[E]**: instants are
  stored as clinic wall-clock in a UTC column (`08:00Z` for 8:00 AM ET), and rendering uses the
  viewer's zone. Render in `America/New_York` (`FE-R8`); ⛔ never apply a compensating offset in the
  frontend (`FE-R26`) — that hides a data bug and breaks the day the data is fixed.
- `✗d` **Appointment has no time.** Every row shows date and start time (`FE-R9`); rows currently
  render "—" **[E]**.
- `✗e` **Cancel is destructive** and needs confirmation naming patient, date and time. `POST
  /appointments/:id/cancel` **[E]**; today the Cancel button sits inline with no confirmation step.

---

## 4. Disclose records  *(ROI clerk · queue-driven · the highest-consequence flow)*

| # | Step | Data | Endpoint |
|---|---|---|---|
| 1 | ▸ Open the pending queue, oldest first | all requests, any patient | `GET /roi/requests` **[E]** servable today |
| 2 | ▸ Select a request | recipient, purpose, date range, status | — |
| 3 | → **Confirm the patient by name and DOB**, not by ID | identity | `GET /patients/:id` |
| 4 | ▸ Record the 45 CFR 164.508 authorization | authorization evidence | **none exists** — D12 **[E]** |
| 5 | ▸ Fulfil | — | `POST /roi/requests/:id/fulfill` |
| 6 | → Show what was disclosed, to whom, when | accounting of disclosures | mutable table, D2 **[E]** |

**Failure paths**

- `✗a` **Wrong patient disclosed.** Step 3 is the whole mitigation. Today the form takes a bare
  numeric ID and never shows a name **[E]**. ⛔ Never a fulfil action on a surface that does not
  display the patient's name and DOB.
- `✗b` **No authorization on file.** D12 means nothing enforces this **[E]**. The UI must make the
  gap visible — capture the authorization reference and mark requests lacking one — and must not
  imply enforcement it does not have. The actual check is W9's. ⛔ Never label a request "authorized"
  because a UI field was filled.
- `✗c` **Fulfil pressed twice.** Disclosure is irreversible; the action needs confirmation naming
  patient + recipient, and must disable on submit.

**Deliberate friction.** This is the one flow where speed is not the goal. Every other flow in this
document optimises for keystrokes; step 3 exists to slow the operator down.

---

## 5. Clinician reviews a patient  *(clinician · every encounter **[I]**)*

| # | Step | Data | Endpoint |
|---|---|---|---|
| 1 | ▸ Arrive at own day's panel | today's appointments by provider | **not servable** — open decision #7 **[E]** |
| 2 | ▸ Open a chart (or reach it via search) | — | `GET /patients/:id/records` |
| 3 | → Banner: name, DOB, MRN, sex, allergy status | — | — |
| 4 | → Encounters in reverse date order, each with date, type, provider, location | — | — |
| 5 | ▸ Open an encounter to read records and notes | records, notes | — |

**Failure paths**

- `✗a` **No dates on encounters.** Today they render "Dr. Patel · 1 record" **[E]** — unusable for a
  clinician, who navigates by chronology **[I]**. Date is not optional metadata here.
- `✗b` **Second chart for the same person.** No MPI (D5) **[E]**, the direct cause of RIV-160. The
  frontend cannot merge charts; it can surface "other possible records for this person" from search.
  ⛔ Never merge or imply a merge in the UI (W4/W6 territory, and it needs provenance).
- `✗c` **Panel unavailable** until decision #7 resolves. Degraded entry is search (P0.2 §4).

---

## 6. Cross-flow rules

Extracted so they are not re-decided per screen:

1. **Every write shows what it wrote.** Identity, ids, and the consequential result — never a bare
   "success". Origin of the rule: the live intake defect.
2. **A 200 is not proof.** Any surface consuming a gateway response treats a `detail` body or a
   missing expected field as failure (`FE-R2`). This mirrors `_VisitChatDownstream`'s existing
   discipline in ADR 0011 — a downstream 200 proves nothing about shape.
3. **Destructive and irreversible actions confirm, naming the subject.** Cancel, fulfil, and any
   future delete. Confirmations name the patient, not the row id.
4. **Never invent authority.** Where the backend does not enforce something (ROI authorization,
   per-action authz), the UI records and displays; it does not claim.
5. **All clinical times in clinic time.** `America/New_York`, explicit, never viewer-local
   (`FE-R8`), and no frontend compensation for bad stored instants (`FE-R26`).
6. **Preserve operator input across failure.** No cleared forms, no lost fields on retry.

## 7. Still unknown

- **[?]** Duplicate-resolution policy (flow 1 `✗e`) — who decides two records are one person.
- **[?]** Whether registration staff (`jpark`, `rdelgado`) run flow 1 differently from front desk.
- **[?]** Whether `nurse_kc` uses flow 5 or a distinct one.
- **[?]** Whether an operator may act across both clinic locations in one session, which affects
  what "today's panel" means for a multi-site provider.

---

**Next:** P0.4 wireframes for the five flows above, then P0.5 tokens. G0 closes on the set.
