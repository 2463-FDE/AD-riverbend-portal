# P0.4 — Wireframes

> Follows `03-key-flows.md`. Written 2026-07-28. Closes at gate **G0**.
>
> **Visual plates:** private Artifact — <https://claude.ai/code/artifact/2bf1efeb-1c4e-42a7-a71d-d470b149974c>
> Five annotated drafting plates. Republish from the same file path to update the same URL.
>
> **This file is canonical for the decisions.** The Artifact renders them; it does not own them.
> One rule, one place (CLAUDE.md §10.1) — if the two disagree, this file is behind and gets fixed,
> not overruled.

---

## 1. What a wireframe is allowed to decide here

Structure, hierarchy, what appears on screen, and what must never appear. **Not** palette, type
scale, density values, or component states — those are P0.5, and settling them inside a wireframe
would pre-empt the decision they belong to.

The plates are drawn in drafting convention: grey fill means "content region", **hatching means the
data to fill this does not exist behind any endpoint today**. Hatching rather than omission is
deliberate — a dependency you cannot see is a dependency you discover at implementation time.

## 2. Plate register

| Plate | Surface | Primary operator | Servable today |
|---|---|---|---|
| 1 | Home | front desk / registration | partly — ROI queue yes, arrivals no |
| 2 | Patient search | all roles | **yes**, `GET /patients?q=` exists unused |
| 3 | Patient chart + identity banner | clinician, nurse | yes |
| 4 | Registration (4a search-first · 4b review · 4c confirmation) | front desk | **no** — write path is broken |
| 5 | Disclosure (5a queue · 5b confirm) | ROI clerk | yes |

## 3. Annotation register

Each entry states the decision, not the drawing. `⛔` entries are prohibitions, and they are the
half of this document most likely to be eroded by a later "small" change.

### Plate 1 — Home

1. **Search holds focus on load.** Both lookup and registration begin by typing, so the keyboard
   reaches the primary task with no pointer.
2. **Arrivals queue is hatched** — spec open decision #7. A client-side fan-out to populate it would
   be the D8 N+1 pattern. Laid out now, filled when an endpoint exists.
3. **"Today" is clinic-local**, and the day strip states clinic hours so an out-of-hours slot reads
   as wrong on sight (`FE-R8`).
4. **ROI queue is the one real queue available today** (`GET /roi/requests`, `patient_id` optional).
   Sorted oldest-first: waiting time is what is at risk.
5. **No "Messages / Billing — SOON" nav entries.** Dead nav teaches operators the nav lies.
6. ⛔ **No copy addressing the operator as the patient** (`FE-R24`).

### Plate 2 — Patient search

1. `GET /patients?q=` already exists and no current screen uses it — zero backend cost.
2. **Result rows carry DOB *and* MRN.** Name alone does not disambiguate. The plate deliberately
   shows two "Maria Gonzalez" rows, same DOB, different MRN and clinic — the RIV-160 duplicate,
   surfaced rather than hidden.
3. **Empty results lead into registration carrying the typed name.** A lookup miss must not dead-end.
4. **No numeric ID entry anywhere in the product** (`FE-R6`). IDs remain in URLs; the vulnerability
   behind walkable IDs is W4's to fix, but nothing in the UI teaches the habit.
5. ⛔ **Never merge or imply a merge of two charts.** Surfacing both is honest; merging needs
   provenance and is not this rebuild's call.

### Plate 3 — Patient chart

1. **The banner is chrome, not a chart section.** It renders wherever a patient context exists and
   cannot be scrolled or collapsed away (`FE-R4`). This is the fix for two charts being visually
   indistinguishable.
2. **Encounters carry date, type and provider**, most recent first. Clinicians navigate by
   chronology; the current list shows "Dr. Patel · 1 record" with no date.
3. **Patient context survives all four patient tabs** (`FE-R25`).
4. **Two distinct allergy states, never rendered alike:** a known allergy in the banner, versus
   "not captured by the interface feed" where AL1 was dropped (D6, `FE-R5`).
5. ⛔ **Never render an empty allergy region.** Silence and "none known" are different clinical facts.

### Plate 4 — Registration

1. **Opens on a search, not a blank form.** Does not fix the missing MPI (D5) — removes the most
   common way a duplicate gets created, which is the mechanism behind RIV-160.
2. **Declaring a new person is deliberate and recorded.** Riverbend's duplicate-resolution policy is
   unknown, so the affordance exists and the policy stays an open question.
3. **Per-section edit from review**, because no update endpoint exists: correction is free before
   submit and genuinely unavailable after. No faked edit path.
4. **"Not answered", never "Declined"** (`FE-R11`), and the form collects only consents the service
   can store (`FE-R21`) — `ConsentKind` holds three values against four collected today, so a
   financial attestation is currently taken and discarded.
5. **Confirmation states what was written** — identity, MRN, patient id — plus the eligibility result
   already present in the response and currently thrown away (`FE-R1`, `FE-R20`).
6. ⛔ **Never a success message on a failed write.** A 200 carrying an error `detail` body is a
   failure (`FE-R2`); every entered field survives retry.
7. ⛔ **Never render unknown coverage as "not covered."** That turns a covered patient away.

### Plate 5 — Disclosure

1. **Name and DOB above the action, at full weight.** Today the form takes a bare numeric ID and
   never shows a name, so nothing stands between a typo and a wrong-patient disclosure.
2. **The action names the recipient** rather than saying "Submit". Every other flow optimises for
   keystrokes; this one is deliberately slow.
3. **Authorization is captured and displayed, not enforced.** Nothing checks 45 CFR 164.508 (D12);
   the queue marks what is missing so the gap is visible to the clerk.
4. ⛔ **Never label a request "authorized" because a UI field was filled.** The real check is W9's.
5. ⛔ **Never a release action on a surface without the patient's name and date of birth.**

## 4. New requirements this plate set implies

None. Every annotation traces to an existing `FE-R` requirement or to a documented debt ID. That is
the intended result — if wireframing had produced new requirements, P0.1–P0.3 would have been
incomplete.

## 5. Deliberately unresolved

- **Palette, type, density, component states** — P0.5.
- **Responsive / small-viewport behaviour.** Chrome would not resize below ~1500px during the
  walkthrough, so the current portal's narrow state was never observed. Nothing here is a mobile
  decision, and F6 (nav vanishing under 720px) still has unknown status.
- **Empty, loading and error states per surface.** Failure *paths* are specified in P0.3 §1–5; their
  *visual* treatment needs the P0.5 tokens.
- **Whether Plate 1 ships in degraded form** (P0.2 §4) — follows open decision #7.

---

**Next:** P0.5 tokens — the last artifact before gate G0.
