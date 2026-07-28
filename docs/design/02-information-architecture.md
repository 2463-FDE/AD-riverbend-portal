# P0.2 — Information architecture

> Follows `01-operators-and-tasks.md`. Framework-agnostic. Written 2026-07-28.
> Closes at gate **G0**. Evidence grades as in P0.1: **[E]** observed, **[I]** inferred, **[?]** unknown.

---

## 1. Settled premises

- **Staff-only.** Patients never log in. Decided 2026-07-28. The patient voice throughout the
  current portal is a bug, not an audience. A future patient-facing surface is out of scope and
  must not be designed for now (spec §2).
- **Multi-clinic, one tenant.** Riverbend Main and Riverbend North both appear in seeded data **[E]**.
- **The portal talks only to the gateway.** Non-negotiable (CLAUDE.md §1).
- **20 gateway endpoints**, with the gaps named in P0.1 §4 **[E]**.

Consequence of staff-only, stated once so it does not need re-deriving: the portal is an
**operational tool for a workstation**, not a consumer app. That decides density (high), primary
input (keyboard), and copy register (third-person clinical). It also removes the whole
"reassure the user" surface — no "Thank you", no "Here's a summary of your care".

## 2. The structural defect in today's IA

Not styling. Each page owns its **own** patient identity, independently:

| Surface | Patient selection | Observed **[E]** |
|---|---|---|
| Records | its own `Patient ID` box, defaults to 1042 | ✔ |
| Appointments | its own `Patient ID` box, defaults to 1042 | ✔ |
| ROI | its own `Patient ID` field, defaults to 1042 | ✔ |
| Dashboard | none — shows the *operator's* own care | ✔ |

So an operator working one patient re-enters that patient's numeric ID on every surface, and
nothing anywhere confirms which human those digits refer to. Two separate failures fall out of
one missing concept:

1. **No shared patient context** → repetitive re-entry, and drift between surfaces.
2. **No patient identity display** → wrong-patient work has nothing to catch it.

The fix is a single IA primitive, not three page fixes.

## 3. The spine: two work modes, one patient context

Staff work is either **queue-driven** ("what needs doing?") or **patient-driven** ("everything
about this person"). Every task in P0.1 §3 fits one or the other. The IA is those two axes joined
by a persistent patient context.

```
┌─ Home (queue-driven) ──────────────── role-shaped, degrades to task list
│    what needs doing now
│
├─ Patient search ───────────────────── global, keyboard-first, always reachable
│    GET /patients?q=            [E] exists, unused today
│
└─ Patient context (patient-driven) ── set once, persists across the surfaces below
     ├─ Identity banner ──────────────  name · DOB · MRN · sex · allergy status  [persistent]
     ├─ Chart          encounters in date order, records, notes
     ├─ Appointments   this patient's upcoming/past, book, cancel
     ├─ Insurance      coverage + eligibility state
     └─ Disclosures    this patient's ROI requests
```

Rules that make this an architecture rather than a menu:

- **Patient context is set exactly one way: by search.** No numeric ID box anywhere in the UI.
  (`FE-R6`. The IDOR vuln behind walkable IDs stays W4's to fix — this only stops the UI teaching it.)
- **The identity banner is chrome, not content.** It renders wherever a patient context exists and
  cannot be scrolled away (`FE-R4`). Allergy status is part of identity, not a chart section, and
  says "not captured" rather than rendering empty (`FE-R5`).
- **Patient context survives navigation** (`FE-R25`). Switching from chart to disclosures keeps the
  patient; switching patients is deliberate and visible.
- **Queues never require a patient context**, and patient surfaces never require a queue.

## 4. Home surfaces per role

Home answers "what needs doing now" for that operator. This is where role matters — and where the
D8 constraint bites: with one role, everyone gets the same home.

| Role | Home content | Servable today |
|---|---|---|
| Front desk / registration | arrivals + check-in queue, registrations in progress, coverage needing attention | **No** — needs a cross-patient appointment read (open decision #7) **[E]** |
| Clinician | today's panel, charts recently opened | **No** — no by-provider appointment query **[E]** |
| ROI clerk | pending requests queue, oldest first | **Yes** — `GET /roi/requests` with `patient_id` optional **[E]** |
| Billing, lab, admin | out of scope this rebuild (P0.1 §3.4) | — |

**Degraded home, if decision #7 lands as "descope".** Home becomes: patient search as the primary
action, plus the ROI queue (the one real queue that is servable), plus recently-viewed patients.
Honest and useful, and notably still better than a dashboard about the operator's own care. Design
the day-view slot in the layout now; fill it when the endpoint exists.

## 5. Navigation model

Two levels, no more. Depth is what makes operational tools slow **[I]**.

- **Primary (persistent):** Home · Patient search · Registration · Disclosures. Role-filtered per
  `FE-R14`/`FE-R23`; identical for everyone until role data lands.
- **Secondary (within patient context):** Chart · Appointments · Insurance · Disclosures.
  Only present when a patient is selected.

Retired from the current nav: **Messages — SOON** and **Billing — SOON** **[E]**. Dead items that
consume primary nav space and teach operators the nav lies. They return when they do something.

## 6. Routes

Deep-linkable, because operators share links and use browser history **[I]**.

| Route | Surface | Notes |
|---|---|---|
| `/` | Home | role-shaped |
| `/patients?q=` | Search results | `q` in the URL; **no PHI** in query strings beyond the operator's own typed term |
| `/patients/:id` | Chart (default patient surface) | banner + encounters |
| `/patients/:id/appointments` | Appointments for the patient | |
| `/patients/:id/insurance` | Coverage + eligibility | |
| `/patients/:id/disclosures` | ROI for the patient | |
| `/register` | New-patient registration | ends by handing off into `/patients/:id` |
| `/disclosures` | ROI work queue | cross-patient; no patient context needed |
| `/login` | Sign-in | see §8 |

`:id` in the URL is unavoidable and is not what makes IDOR exploitable — the missing session-to-patient
bind is (W4). What the IA removes is the **ID-entry affordance** that invites walking them.

## 7. Registration flow placement

Registration is queue-driven work that *creates* a patient context, so it sits in primary nav and
terminates by entering the patient surface. Two IA-level requirements fall out of P0.1:

- It must end by showing **what was created** — patient identity plus the eligibility result that
  is already in the response and currently discarded (`FE-R20`, `FE-R1`) **[E]**.
- It must support **correcting a just-entered field** without restarting. No update endpoint exists
  **[E]**, so pre-submit correction must be free (per-step edit from review) and post-submit
  correction is honestly out of reach until one does. Do not fake it.

## 8. Sign-in

Out of the patient/queue structure, one note: the login page prints working credentials
(`frontdesk` / `portal123`) on screen **[E]**. Correct for a training demo, wrong for anything
resembling production. Keep it, but behind an explicit demo affordance rather than as body copy —
and the subtitle "Access your appointments, records, and forms" is patient voice (`FE-R24`).

## 9. What this IA does not decide

- Visual design, density values, type scale — P0.4/P0.5.
- Whether role-shaped homes ship as tier 2 or tier 3 (spec §8.3, open decision #3). The IA works
  either way: with one role, every operator gets the same home.
- Whether the day-view endpoint gets added (open decision #7). §4 gives the degraded form.
- Timezone and clinic hours (P0.1 §6 q5) — needed before a day view can be laid out, since
  "today" is undefined without them.

---

**Next:** P0.3 key flows — registration→coverage→chart, find→verify→chart, disclose. Then P0.4
wireframes, P0.5 tokens.
