# Staged delivery workflow

Adopted 2026-08-06, replacing the free-form weekly specs now archived in
`docs/specs-deprecated/`. Each work item (organized by week number) moves through a fixed
pipeline; every stage leaves a reviewable artifact in this tree.

## Pipeline

```
requirement synthesis → spec (EARS) → code plan
        → GATE: plan/spec drift check
        → implement → codex review (@codex-review PR loop)
        → approve? → merge to main
             └─ trivial fix → patch impl, re-review
             └─ structural  → back to code plan (spec unchanged)
```

- The **spec is the frozen contract** once agreed. The drift gate and the review both anchor
  against it. It changes only by explicit human decision, never silently mid-loop.
- **Codex review** is the existing PR loop: comment `@codex-review`, answer each round with
  an `rN:` disposition comment (A/B/C labels), iterate until dry.
- Stage mechanisms are decided when a stage is first reached and recorded here. Currently
  defined: requirement synthesis (`.claude/skills/requirement-synthesis/`), spec
  (`.claude/skills/spec-authoring/`, decided 2026-08-06 on first reach). Plan, gate, and
  implement stages: not yet defined.

## Layout

```
docs/workflow/
  wN/
    requirements.md   ← requirement synthesis output
    spec.md           ← EARS spec (contract)
    plan.md           ← code plan
```

## Ground rules

- Requirements come fresh from the engagement owner each week; the deprecated specs are
  archive, not input.
- Repo-wide rules still bind every stage: `docs/landmines.md` (approval-gated zones,
  change safety, negative tests), `CONTRIBUTING.md` (branching, commits, PR process).
