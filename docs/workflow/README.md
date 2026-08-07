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
  (`.claude/skills/spec-authoring/`, decided 2026-08-06 on first reach), code plan
  (`.claude/skills/plan-authoring/`, decided 2026-08-06 on first reach with e1),
  implement (`.claude/skills/implementation/` + its inner loop `.claude/skills/tdd/`,
  decided 2026-08-07, ahead of first reach), gate (`.claude/skills/drift-gate/`, decided
  2026-08-07, codified from the e1 fresh-context prototype run of 2026-08-06). The gate
  runs only in a session that did not author the plan and stamps `Status: GATED`, which
  the implement skill requires at entry. All five stages are now defined.

## Layout

```
docs/workflow/
  wN/
    requirements.md   ← requirement synthesis output
    spec.md           ← EARS spec (contract)
    plan.md           ← code plan
    gate-findings.md  ← gate round log (created on first finding; owned by the
                        drift-gate skill, dispositions filled in stage 3)
```

Workflow state is derivable from these files alone — plan `Status:` header plus the
round log; no session memory required. The decode table lives in
`.claude/skills/drift-gate/`.

## Ground rules

- Requirements come fresh from the engagement owner each week; the deprecated specs are
  archive, not input.
- `eN` items are internal enablers (source: engagement team, not the client) — same
  pipeline, same artifacts, numbered separately so `wN` stays client asks only.
  (Decided 2026-08-06 with `e1`.)
- Repo-wide rules still bind every stage: `docs/landmines.md` (approval-gated zones,
  change safety, negative tests), `CONTRIBUTING.md` (branching, commits, PR process).
