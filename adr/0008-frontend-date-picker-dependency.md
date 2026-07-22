# ADR 0008 — Frontend date entry: adopt `react-day-picker`

**Status:** Accepted
**Date:** 2026-07-20
**Author:** Riverbend engagement team
**Relates to:** ADR 0001 (monorepo & stack — "frontend has zero UI/form
dependencies; plain global CSS"). This ADR records the deliberate first break of
that zero-UI-dependency posture. Surfaced by the frontend UX audit (2026-07,
`docs/ux-audit-2026-07.md`, finding **F3**).

## Context

The portal collects three dates through raw `<input type="date">` controls:

- **Intake — date of birth** (`app/intake/page.tsx`, inside the shared `Field`).
- **ROI — "records from" / "records to"** range (`app/roi/page.tsx`).

The native control is functional but, per the UX audit, HIGH-severity for our
users:

1. **DOB is unreachable in practice.** The native picker opens on the current
   month; reaching a 1950s birth year is dozens of clicks (or defeated entirely
   on browsers whose native picker has no year jump). Our population skews older
   patients self-registering — this is the single worst entry field in the app.
2. **Rendering is inconsistent** across Chrome / Firefox / Safari / mobile — we
   cannot style the calendar, the placeholder, or the locale, so the control
   clashes with the `rb-`-prefixed design system and behaves differently per
   browser.
3. **No shared abstraction.** DOB and the ROI range are three hand-wired inputs
   with no common validation seam (min/max, "to after from"), so per-field
   validation (audit F7) has nowhere to hang.

The frontend has, by ADR 0001, **zero runtime UI dependencies** — every widget
so far is hand-rolled against `globals.css`. Fixing F3 well means either
hand-rolling a calendar (a large, a11y-heavy surface: grid semantics, roving
tabindex, month/year navigation, keyboard, localization) or taking the first UI
dependency. This ADR decides that, and sets the bar the dependency must clear.

## Decision

Adopt **`react-day-picker` v9** as the portal's date-entry primitive, wrapped in
a single shared **`DateField`** component (`app/components/DateField.tsx`).

- **`DateField` is the only consumer** of `react-day-picker`. Pages never import
  the library directly — they use `DateField`, exactly as they already use the
  local `Field` / `SelectField` helpers. This keeps the dependency at one seam;
  swapping or removing it later touches one file.
- **The wire contract does not change.** `DateField` holds and emits a
  `YYYY-MM-DD` string — byte-for-byte what `<input type="date">` produced — so
  the intake and ROI payloads to the gateway are unchanged. This is a
  presentation-layer change only; no service, schema, or API contract moves.
- **Local-time conversion is mandatory.** ISO⇄`Date` conversion is done with
  local calendar fields (`new Date(y, m-1, d)` / manual `YYYY-MM-DD` from local
  getters), never `new Date("2020-01-15")` (which parses as UTC midnight and can
  shift the day across a timezone boundary). A DOB that silently moves by one
  day is a data-integrity bug, so the conversion is centralized in `DateField`
  and covered by the audit's follow-up test harness.
- **DOB uses `captionLayout="dropdown"`** with a bounded `startMonth`/`endMonth`
  (year 1900 → today) so a birth year is one dropdown selection, and future
  dates are `disabled`. The ROI range uses the same component and the same 1900
  floor. `DateField` defaults `fromYear` to **1900** precisely so this floor is
  never omitted by accident: with `captionLayout="dropdown"` an unset
  `startMonth` makes react-day-picker v9 collapse the year dropdown to a rolling
  ~100-year window (`today−100y .. today`) — a *hidden* lower wall stricter than
  the native `<input type="date">` it replaced, which would block pre-~1926 ROI
  record dates (migrated charts, lifetime/legal history). 1900 reaches past any
  living patient's earliest record; callers needing further back pass a smaller
  `fromYear`. (Corrected 2026-07-22 after PR #9 review — the original plan to
  run ROI "without the 1900 floor" wrongly assumed an unset floor meant *no*
  bound rather than the 100-year default.)
- **Styling:** import the library's base stylesheet (`react-day-picker/style.css`)
  once, then override its CSS custom properties (`--rdp-*`) in `globals.css` to
  match the `rb-` palette. No inline styles, no CSS-in-JS — consistent with the
  existing stylesheet-only approach.

### Why `react-day-picker` specifically

- **React-only peer dependency** (`react >=16.8`). It bundles its date math
  (date-fns v4) internally — no `date-fns` peer for us to manage, no separate
  calendar-math dependency.
- **Accessibility is built in** (ARIA grid, keyboard navigation, focus
  management) — the exact surface most likely to be wrong if hand-rolled, and
  the reason not to hand-roll.
- **Native year navigation** via dropdown caption — directly fixes the #1 DOB
  complaint.
- **Styleable via CSS variables and class names**, so it can be made to look
  like the rest of the portal rather than bolted on.
- Widely used, actively maintained, MIT-licensed, small transitive footprint.

## Alternatives considered

- **Keep native `<input type="date">` (do nothing).** Zero dependency, but does
  not fix the HIGH-severity DOB reachability problem — the reason the audit
  raised F3. Rejected.
- **Hand-roll a calendar** against `globals.css`. Keeps the zero-dependency
  posture, but re-implements a large, high-risk a11y surface (grid semantics,
  keyboard, focus, i18n) that a mature library already gets right. For a HIPAA
  portal where DOB accuracy matters, "write our own calendar" is exactly the
  kind of load-bearing wall the brownfield discipline says to avoid. Rejected.
- **A heavier form/date suite** (MUI, react-datepicker + date-fns peer, a full
  component kit). More surface, more transitive dependencies, and it would
  impose a second styling paradigm on top of `globals.css`. Over-scoped for one
  widget. Rejected.
- **A `<input type="text">` with a manual mask** (like the F2 SSN mask). Works
  for a format but gives no calendar and no year navigation — no better than
  native for the DOB reachability problem. Rejected.

## Consequences

- **The zero-UI-dependency posture ends here, deliberately and narrowly.** One
  library, one wrapping component, one documented reason. Any future UI
  dependency should clear the same bar (fixes a real audit finding, wrapped at a
  single seam, does not fork the styling model) and get its own ADR.
- **Bundle grows** by `react-day-picker` + its bundled date math. Acceptable for
  the UX gain; the frontend already ships a full Next.js runtime.
- **Supply-chain surface grows.** `react-day-picker` adds transitive packages;
  the pre-existing CI gap (no dependency/image scanning — CLAUDE.md §9, D9/#12)
  now covers frontend `node_modules` too. Flagged, not fixed here — it is
  tracked debt, and this ADR does not widen or narrow it beyond noting the new
  packages. (The `npm audit` warnings observed at install time are pre-existing
  `next` / `postcss` advisories, unrelated to this change; bumping `next` is out
  of scope and would move a config default.)
- **A shared `DateField` seam now exists**, giving per-field date validation
  (audit F7) a single home when that work lands.
- **Follow-up:** the local-time ISO⇄`Date` conversion is the kind of pure logic
  the repo currently cannot unit-test (no JS test harness — tracked follow-up
  from PR #8). When that harness lands, the conversion round-trip and the
  "to after from" guard are its first tests.
