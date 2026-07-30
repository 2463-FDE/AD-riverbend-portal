# P0.5 — Design tokens

> Follows `04-wireframes.md`. Framework-agnostic. Written 2026-07-30.
> Closes at gate **G0** — the last P0 artifact. Evidence grades: **[E]** observed, **[I]** inferred,
> **[?]** unknown.
>
> **Direction F, "warm and institutional", is the chosen visual register.** The seven candidates and
> the live specimen live in `05-token-directions.html`; that page stays as the record of what was
> rejected and why. This file is the proposal that survives it.
>
> **Every ratio below is measured**, by the same arithmetic the specimen page runs
> (`lum`/`ratio`/`fixInk`), not asserted. Where a measurement fails a floor, §6 says so and proposes
> the corrected value rather than rounding the number up.

---

## 0. What decided this, and how strong that evidence is

- **Direction F selected.** One healthcare worker, polled by the user, 2026-07-30. **[E]** for the
  preference, and honestly **n = 1**. That settles the question P0 could not settle from the inside —
  which register reads as a community health centre rather than a software product — and it is the
  right kind of question to answer by asking a clinician. It is **not** a usability finding, and
  **no accessibility floor in this document rests on it**. Everything in §1–§5 is either measured or
  traceable to P0.1–P0.4.
- **Status-as-chips is confirmed, and it also fixed something it was not aimed at.** The same poll
  reported that moving the status column from coloured words to filled chips remedied the difficulty
  of telling where one queue row ended and the next began. **[E]**
  - Recorded with its caveat: the chip fixed the **symptom**. The row separator itself is
    `--border` at **1.33:1** against the row background (§6.2) — below the 3:1 non-text floor — so
    what actually happened is that a high-contrast object inside the row started doing the
    separator's job. Both get fixed: keep the chips, and raise the separator. If the separator is
    left as-is, every table without a chip column (there are several in P0.2) keeps the original
    problem.
- **Unanswered by the poll, and still open:** row density, identity-strip field order, whether the
  allergy banner reads as urgent without becoming noise, and whether dark mode is ever wanted in an
  exam room. Those were four of the five questions the review page asked. §7 lists them; §3 and §4
  ship defaults that are explicitly provisional.

---

## 1. Palette

Direction F's values, as measured. `--zebra` and `--ptx-bg` are near-white on purpose: the warm paper
is the *page*, and the working surfaces sit on top of it.

| Token | Value | Role | Measured |
|---|---|---|---|
| `--bg` | `#f9f7f3` | page — the warm paper | — |
| `--surface` | `#ffffff` | cards, tables, the working area | — |
| `--zebra` | `#fdfbf8` | alternate table row | — |
| `--ptx-bg` | `#fdfcfa` | patient identity strip | — |
| `--text` | `#1a1c1c` | body, patient data | **17.12:1** on surface · 16.00:1 on bg · 16.57:1 on zebra |
| `--muted` | `#635c52` | secondary text, hints, column heads | 6.60:1 on surface · 6.17:1 on bg |
| `--accent` | `#0f6d80` | links, focus, selected nav | 5.97:1 on surface |
| `--accent-fill` | `#0d6071` | **primary button fill only** (§6.1) | **7.17:1** vs white label |
| `--accent-ink` | `#ffffff` | label on `--accent-fill` | — |
| `--chrome-bg` | `#123b44` | top bar / frame | — |
| `--chrome-text` | `#f2ece2` | text in the frame | **10.30:1** on chrome |
| `--chrome-border` | `#0c2b32` | frame edge | — |
| `--separator` | `#938e88` | table row rule, card edge (§6.2) | **3.04:1** worst of surface/zebra/bg |
| `--border-strong` | `#948c82` | input + secondary-button edge (§6.3) | **3.10:1** on surface and bg |
| `--ok` | `#1f6142` | success, released | 7.38:1 on surface |
| `--warn` | `#8a5a08` | attention — **chip fill only**, never plain text | 5.92:1 as text → forbidden |
| `--alert` | `#a02a24` | allergy banner, invalid input, declined | 7.36:1 on surface · 6.53:1 on `--alert-bg` |
| `--alert-bg` | `#fdeeec` | allergy banner ground | — |
| `--alert-border` | `#eec7c2` | allergy banner edge | — |

**Inherited, not invented.** `--accent` is Riverbend's own teal (`#0f6d80`, one step off the live
portal's `#0f7c91`), and the frame is the live portal's nav colour. A rebuild behind this palette is
recognisably the same organisation. **[E]** — the live portal's values, read from
`frontend/` and reproduced in the specimen page's "the brand colour already exists" panel.

**Contrast floors this palette is held to:**

- Body text and anything a decision is made from: **7:1** (WCAG AAA).
- Secondary text, accents, and text ≥19px bold: **4.5:1**.
- Non-text boundaries that identify a component or a state: **3:1** (WCAG 1.4.11).

`--muted` at 6.60:1 sits between the two text floors deliberately. It is secondary by definition
(hints, column heads, the "unavailable" line), it clears 4.5:1 with margin, and holding it to 7:1
would push it to `#59534a` — measurably possible, but it flattens the hierarchy the warm palette is
chosen for. **Rule: nothing a clinical decision depends on is ever rendered in `--muted`.**
If a value matters, it is `--text`.

---

## 2. Status chips

The chips are **derived from the palette by one rule**, not hand-picked per state, so they cannot
drift when a token moves. The three tiers are deliberately *unequal* — the column has one thing to
look for rather than three competing ones.

| State | Tier | Glyph | Ink | Fill | Border | Measured |
|---|---|---|---|---|---|---|
| Pending | **solid** | ● | `#ffffff` | `#754c07` | = fill | **7.52:1** |
| Released | tint | ✓ | `#1a5238` | `#dde7e3` | `#9ab8aa` | **7.20:1** |
| Declined | tint | ✕ | `#88241f` | `#f1dfde` | `#d49f9c` | **7.05:1** |
| Not answered | outline | ○ | `#3e3c37` | transparent | = ink, **dashed** | **10.66:1** (worst of plain/zebra row) |

**The rule, stated so it survives a token change:**

1. **Pending fills solid** with the attention colour, because it is the only state that needs a
   person. A block of colour is the strongest signal available.
2. **Released and Declined tint** the surface at 15%, bordered at 45%.
3. **Not answered stays unfilled and dashed**, because nothing has come back yet. Its ink is pulled
   halfway from `--muted` toward `--text` so it stops reading as disabled.
4. **The ink is then darkened until it clears 7:1 against every background it can land on** — for an
   unfilled chip that means the plain row *and* the zebra row, reported at the worse of the two.
5. **Every chip carries a glyph** as well as colour, so the column survives greyscale and every form
   of colour blindness.

**Declined is new here.** The specimen page only ever showed three states, but `FE-R11` requires a
consent that was *not answered* to be visually distinct from one that was *declined* — they are
genuinely different facts in records work. Three states cannot express four. Declined is derived on
the same rule (alert, tinted, solid border, ✕) and is distinct from Not answered in fill, border
style, glyph and hue.

Chip borders land at 2.1–2.3:1 against the surface. That is **not** a 1.4.11 failure: the state is
carried by text, glyph and fill, so the border is decorative. It is recorded because someone will
measure it and ask.

---

## 3. Type scale

Direction F's argument is the serif — so the serif has to be **rationed**, for the reason F's own
cost line gives: a warm ground lowers effective contrast in dense tables.

| Step | Size / line-height | Weight | Family |
|---|---|---|---|
| Page title | 29px / 1.15 | 700 | `--display` (serif) |
| Section | 23px / 1.2 | 650 | `--display` |
| Card heading | 19px / 1.3 | 650 | `--display` |
| Patient name (identity strip) | 18px | 650 | `--display` |
| Body | 15px / 1.5 | 400 | `--font` (sans) |
| Secondary | 13.5px / 1.5 | 400 | `--font`, `--muted` |
| Label / column head | 11px / 1.45, uppercase, `.08em` | 700 | `--font`, `--muted` |

- `--display` — `ui-serif, "Iowan Old Style", Palatino, Georgia, serif`
- `--font` — `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`
- `--numeric` — `= --font`, with `font-variant-numeric: tabular-nums`

**Rules:**

- **The serif never enters a queue row.** Headings, page titles and the patient name only.
- **Every number is tabular.** MRN, DOB, times, request IDs — columns of digits must align, and
  `1974-03-02` must not reflow as the row re-renders.
- **No web font is loaded.** Both stacks are system families. A staff workstation on a bad connection
  renders the same layout as one on a good one, and there is no FOUT on the identity strip.
  **[I]** — no observation of clinic network conditions; this is a cheap default, not a finding.

---

## 4. Density — provisional

| Token | Dense | Comfortable |
|---|---|---|
| `--row-h` | 32px | 44px |
| `--ctrl-h` | 36px | 44px |

**Shipping default: Dense.** Reason: the ROI and appointment queues are the surfaces where an
operator scans rather than reads, and Dense fits ~8 rows where Comfortable fits ~6.

**This is the weakest decision in the document.** The review page asked which one a shared
workstation should have; that answer did not come back. Comfortable is materially harder to misclick,
and a mis-click on the ROI queue is a wrong-patient disclosure path (P0.3 §4). Two consequences:

- The default is **provisional pending the answer**, and both scales ship as tokens so flipping it is
  one value, not a re-layout.
- `--ctrl-h` at 44px in Comfortable is the pointer-target size worth having. In Dense it is 36px,
  which is under the 44px comfortable-target guidance — acceptable for a keyboard-and-mouse
  workstation, **not** acceptable if any surface is ever used on a tablet. No tablet use has been
  observed either way. **[?]**

---

## 5. Component states

| State | Treatment |
|---|---|
| Focus | `0 0 0 3px rgba(15,109,128,.30)` ring **plus** `--accent` border. Never removed, never colour-only. |
| Invalid | `--alert` border, `--alert-bg` ground, `--alert` text, message in words next to the field |
| Disabled | `--dis-bg #f4f1ec` / `--dis-ink #a09788` / `--dis-border #e5ded4` — **plus** the `disabled` attribute and a non-colour cue (§6.4) |
| Primary button | `--accent-fill` ground, `--accent-ink` label, `--radius-sm` |
| Secondary button | `--surface` ground, `--border-strong` edge, `--text` label |
| Unavailable data | stated in words, italic, `--muted` — never an empty region (`FE-R5`) |

Geometry: `--radius` 10px · `--radius-sm` 6px · `--pill` 999px · `--bw` 1px ·
`--shadow` `0 1px 2px rgba(60,50,35,.07)` · `--topbar-h` 48px.

**Rules:**

- **No state is signalled by colour alone.** Focus has a ring and a border change; invalid has a
  ground, a border and prose; disabled has an attribute; every chip has a glyph.
- **`--alert` is reserved.** Allergy banner, invalid input, and the declined chip. Nothing else gets
  to be red, or the banner stops meaning anything by 10am.
- **`--warn` never appears as text.** At 5.92:1 it fails the 7:1 body floor. It exists to be a chip
  fill, where the derivation (§2) darkens it to `#754c07` and clears 7.52:1.

---

## 6. Four corrections direction F needs before it is implemented

The specimen was a visual proposal and was measured as one. Four pairings do not survive
implementation as-is. Each is fixed by a value, and the value is measured.

### 6.1 Primary button label — `5.97:1`, needs the 7:1 text floor

White on `--accent #0f6d80` measures **5.97:1**. A button label is body text and the label is the
whole control. Fix: a separate `--accent-fill #0d6071` (accent darkened 12% toward black) →
**7.17:1**. `--accent` itself stays at `#0f6d80` for links, focus rings and selected nav, where 4.5:1
is the applicable floor and the lighter value reads better.

### 6.2 Table row separator — `1.33:1`, needs 3:1

`--border #e5ded4` on `#ffffff` measures **1.33:1**. This is the row-boundary problem the poll
surfaced, in its primary form. Fix: `--separator #938e88` (border darkened 36% toward black) →
**3.04:1** against the worst of surface, zebra and page. Keep `#e5ded4` only for decorative
hairlines that separate nothing — of which, on inspection of P0.2, there are none, so `--border`
is retired rather than kept as a trap.

### 6.3 Input and secondary-button edge — `1.74:1`, needs 3:1

`--border-strong #cdc3b5` on `#ffffff` measures **1.74:1**. An input's boundary is exactly what
WCAG 1.4.11 covers: it is the only thing that says where the field is. Fix: `--border-strong
#948c82` → **3.10:1**. On the warm page ground it holds at 3.1:1, which is why it was measured
against both.

### 6.4 Disabled text — `2.56:1`, and staying there

`--dis-ink #a09788` on `--dis-bg #f4f1ec` measures **2.56:1**. WCAG exempts disabled controls, and
raising it would make disabled read as available — the same trap direction E's cost line names. So
this one is **accepted as-is and compensated**: any disabled control must also carry the `disabled`
attribute (so assistive tech announces it) and must not be the only route to an action. Where a
control is disabled for a *reason* the operator can act on, the reason is stated in words next to it
rather than left to the grey.

---

## 7. Deliberately unresolved

- **Density (§4).** Needs the Dense/Comfortable answer. Currently defaulted to Dense on a scanning
  argument, against a mis-click argument that is at least as strong on the ROI queue.
- **Identity-strip field order.** P0.2 pins name + DOB + MRN; whether that is the order a clinician
  confirms in was asked and not answered. **[?]**
- **Allergy banner urgency.** Whether `--alert` at 7.36:1 on a warm ground reads as urgent without
  becoming noise by mid-shift — the one question here that only a clinician on a real shift can
  answer. **[?]**
- **Dark counterpart.** Direction G existed to ask whether dark is ever wanted; no answer came back,
  so F ships light-only. Tokens are named by role, not by value, so a dark set is additive later.
- **Small-viewport behaviour.** Unchanged from `04-wireframes.md` §5 — Chrome would not resize below
  ~1500px, so F6 (nav vanishing under 720px) still has unknown status. Nothing here is a mobile
  decision.
- **Print.** ROI clerks produce paper. The warm ground and the tinted chips are untested on a printer
  and a tint that vanishes in greyscale would take the state with it — the glyphs are the hedge, but
  this is unverified. **[?]**

---

## 8. Traceability

Tokens discharge no `FE-R` on their own; they are `docs/specs/frontend-rebuild.md` §4 deliverable 1
and the last artifact of gate **G0** (§6). What they make satisfiable later:

| Requirement | What this file provides |
|---|---|
| `FE-R5` | `--unavail` treatment — unavailability stated in words, never an empty region |
| `FE-R11` | the **Declined** chip (§2), distinct from Not answered in fill, border, glyph and hue |
| `FE-R17` | nothing here is signalled by colour alone, so an accessible name is always available |
| `FE-R13`, `FE-R24` | no token in §1 addresses the operator; copy checklist is P3's, not P0.5's |
| `FE-R4` | `--ptx-bg`, `--fs-name`, `--display` for the persistent identity header |

Debt adjacency: none of these tokens touch D1/D4/D8/D11/D12. §6's corrections are accessibility
findings against a design proposal, not code changes.

---

**Next:** gate **G0** — user review of the P0 set (`01`–`05`). Then open decision #2, framework
(`docs/specs/frontend-rebuild.md` §8), which is what G0 unblocks.
