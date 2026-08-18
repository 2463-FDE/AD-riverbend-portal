---
name: mockup
description: Optional plan-stage input of the delivery workflow (docs/workflow/README.md). Build a static, spec-anchored HTML mockup of a portal surface to inform plan-stage decisions. Use only when a work item's frozen spec names the portal as a system element and the user says "build the mockup", "mockup the surface", or invokes /mockup.
---

# Spec-anchored mockup (optional plan-stage input)

Input: the item's `## Spec` at `Status: FROZEN` (`docs/workflow/<item>.md`). Refuse to start from
a DRAFT — a mockup built against an unfrozen spec fills the spec's silence with invented
UI and then reports its own inventions as spec gaps (observed on W3, 2026-08-07: four of
five "open questions" turned out to be invented requirements).
Output: a static mockup **outside the repo** (scratch, e.g.
`~/Documents/Work/mockups/<item>/`), plus plan-decision candidates. The mockup is
**evidence, not contract**: never tracked, never cited as normative by plan or gate. What
it teaches lands as `plan`-tagged decisions in the item's register; anything the
plan asserts from it becomes a plan fact the drift gate spot-verifies in-repo as usual.

This skill supersedes the generic frontend-design skill for portal mockups here:
alignment to the frozen spec and the existing design system beats distinctiveness.

## Rules

1. **CSS anchor:** the stylesheet prefix is byte-identical to
   `git show HEAD:frontend/app/globals.css` — committed HEAD, never the working tree.
   Additions append after the prefix, so a diff shows exactly what the surface adds to
   the design system.
2. **Vocabulary:** every user-visible string is copied from backend source (templates,
   `app.py` response bodies), never invented. No lorem, no paraphrase.
3. **One fixture per SPEC state.** Every unwanted-behavior SPEC on the surface gets its
   own fixture, and visually adjacent states must stay distinguishable. The W3 lesson:
   reusing a shared component's tone map rendered a genuine denial *quieter* than a
   failed check — the natural reuse move can silently break a SPEC.
4. **Trace table closes both ways:** every fixture names its SPEC ids; every surface SPEC
   has ≥1 fixture. The table lives in the mockup's own README, next to the fixtures.
5. **Exposure rule:** render only what responses already carry. Wanting a value the
   backend does not serve is a spec/plan question to raise, never a frontend hardcode.
6. **Silence rule:** spec silence is plan freedom, not a gap. Where the spec does not
   constrain the UI, record the choice as a plan-decision candidate; do not report the
   silence as a spec finding.
7. **Static only:** plain HTML/CSS/JS fixtures, no build step, no new dependencies.

## Never

- Never build a mockup against a DRAFT spec.
- Never track the mockup in the repo or cite it as a source of truth — the plan text is.
- Never restyle from the working tree; anchor to committed `main`.
