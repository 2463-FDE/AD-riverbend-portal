# Staged delivery workflow

Adopted 2026-08-06, replacing the free-form weekly specs now archived in
`docs/specs-deprecated/`. Each work item (organized by week number) moves through a fixed
pipeline; every stage leaves a reviewable artifact in this tree.

## Pipeline

```
requirement synthesis → spec (EARS) → code plan
        → GATE: plan/spec drift check
        → implement
        → GATE: impl/plan check (pre-push, fresh context)
        → push → codex review (@codex-review PR loop)
        → approve? → merge to main
             └─ trivial fix → patch impl, re-review
             └─ structural  → back to code plan (spec unchanged)
```

- The **spec is the frozen contract** once agreed. The drift gate and the review both anchor
  against it. It changes only by explicit human decision, never silently mid-loop.
- **Codex review** is the existing PR loop: comment `@codex-review`, answer each round with
  an `rN:` disposition comment (A/B/C/E labels, defined in `docs/review-loop-metrics.md`
  §1), iterate until dry. The push→review→merge segment is artifact-backed and owned by
  the implementation skill: `pr-body.md` carries the delivery `Status:` (PUSHED PR #n →
  MERGED sha) and `review-findings.md` is the round log. No separate skill owns it. The
  fix-session procedure (label → cluster → route: state-touching fixes back to stage 3,
  repeat findings get the class fix, rest patched on branch) is the implementation
  skill's "Addressing a round" section — decided 2026-08-07 on first reach with e1
  PR #49, rebuilt from scratch informed by `docs/review-loop-metrics.md` §3.
- Stage mechanisms are decided when a stage is first reached and recorded here. Currently
  defined: requirement synthesis (`.claude/skills/requirement-synthesis/`), spec
  (`.claude/skills/spec-authoring/`, decided 2026-08-06 on first reach), code plan
  (`.claude/skills/plan-authoring/`, decided 2026-08-06 on first reach with e1),
  implement (`.claude/skills/implementation/` + its inner loop `.claude/skills/tdd/`,
  decided 2026-08-07, ahead of first reach), gate (`.claude/skills/drift-gate/`, decided
  2026-08-07, codified from the e1 fresh-context prototype run of 2026-08-06), impl gate
  (`.claude/skills/impl-gate/`, decided 2026-08-07, ahead of first reach). Each gate
  runs only in a fresh session that did not author the artifact it checks: the drift
  gate stamps the plan `Status: GATED` (required by the implement skill at entry); the impl
  gate checks the finished branch against plan and spec pre-push and stamps `pr-body.md`
  `Status: IMPLEMENTED` — the plan header stays `GATED`, delivery state lives on `pr-body.md`
  (push stays human-gated). All six stages are now defined.

## Layout

```
docs/workflow/
  wN/
    requirements.md   ← requirement synthesis output
    spec.md           ← EARS spec (contract)
    plan.md           ← code plan. Status: DRAFT | GATED — plan maturity ONLY, never
                        delivery state.
    gate-findings.md  ← gate round log (created on first finding; owned by the
                        drift-gate skill, dispositions filled in stage 3)
    pr-body.md        ← delivery artifact + PR-body draft (working-tree, not committed on
                        the code branch; lands on main via noncode-merge). Carries the
                        delivery Status: header (DRAFT → IMPLEMENTED → PUSHED → MERGED);
                        deviations, test-first split, residuals, Risk & landmines.
    impl-findings.md  ← impl-gate round log (created on first finding; owned by the
                        impl-gate skill, dispositions filled in stage 4)
    review-findings.md ← codex review round log (created on first finding; owned by the
                        implementation skill, dispositions filled by the stage-4 fix session)
```

Workflow state is derivable from these files alone — no session memory required:
**plan `Status:`** (plan maturity: DRAFT | GATED) + **`pr-body.md` `Status:`** (delivery
lifecycle: DRAFT → IMPLEMENTED → PUSHED PR #n → MERGED sha) + the **three round logs**
(`gate-findings.md`, `impl-findings.md`, `review-findings.md`). The decode tables are
below.

## State decode tables

The cold-handover entry point: from these tables plus the artifacts above, derive any
item's exact state without `gh` or session memory. Three stages, three tables.

**Gate stage** (`gate-findings.md`, plan `Status:`):

| Observation | State |
|---|---|
| plan `DRAFT`, no `gate-findings.md` | gate not yet run |
| latest round has findings with empty dispositions | stage-3 revision pending |
| dispositions filled, plan still `DRAFT` | re-gate pending |
| plan `GATED` | plan gated; round log closed |

**Impl-gate stage** (`impl-findings.md`, plan `Status:`, `pr-body.md` `Status:`):

| Observation | State |
|---|---|
| plan `GATED`, no branch diff | implementation not started |
| plan `GATED`, branch complete, no `impl-findings.md` | impl gate not yet run |
| latest round has findings with empty dispositions | stage-4 fix pending |
| dispositions filled, `pr-body.md` still `DRAFT` | re-gate pending |
| `pr-body.md` `IMPLEMENTED` | push-ready; round log closed |

**Review stage** (`review-findings.md`, `pr-body.md` `Status:`):

| Observation | State |
|---|---|
| `pr-body.md` `IMPLEMENTED`, not pushed | awaiting human push gate |
| `pr-body.md` `PUSHED PR #n`, no `review-findings.md` | pushed; codex not yet run |
| latest round has findings with empty dispositions | stage-4 fix pending |
| dispositions filled, `pr-body.md` still `PUSHED` | re-review pending |
| `pr-body.md` `MERGED <sha>` | delivered; round logs closed |

## Ground rules

- Requirements come fresh from the engagement owner each week; the deprecated specs are
  archive, not input.
- `eN` items are internal enablers (source: engagement team, not the client) — same
  pipeline, same artifacts, numbered separately so `wN` stays client asks only.
  (Decided 2026-08-06 with `e1`.)
- Repo-wide rules still bind every stage: `docs/landmines.md` (approval-gated zones,
  change safety, negative tests), `CONTRIBUTING.md` (branching, commits, PR process).
