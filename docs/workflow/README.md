# Staged delivery workflow

Adopted 2026-08-06, replacing the free-form weekly specs now archived in
`docs/specs-deprecated/`. Each work item moves through a fixed pipeline; every stage
leaves a reviewable record in this tree.

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
  the implementation skill: the delivery `Status:` (PUSHED PR #n → MERGED sha) and the
  Findings round log live where the Layout section below puts them. No separate skill owns
  it. The fix-session procedure (label → cluster → route: state-touching fixes back to
  stage 3, repeat findings get the class fix, rest patched on branch) is the implementation
  skill's "Addressing a round" section — decided 2026-08-07 on first reach with e1
  PR #49, rebuilt from scratch informed by `docs/review-loop-metrics.md` §3.
  **Non-code PRs run the same loop** (decided 2026-08-11 — codex does review docs; the
  earlier skip rested on the assumption it could not): the `noncode-merge` skill owns
  their push→review→merge segment and routes artifact findings back to the owning stage —
  requirements → stage 1 re-stamp, frozen spec → owner decision then re-freeze + plan
  re-gate, plan → stage 3 + re-gate; findings about the code the docs describe are filed
  in the registries, not fixed by editing the record.
- Stage mechanisms are decided when a stage is first reached and recorded here. Currently
  defined: requirement synthesis (`.claude/skills/requirement-synthesis/`), spec
  (`.claude/skills/spec-authoring/`, decided 2026-08-06 on first reach), code plan
  (`.claude/skills/plan-authoring/`, decided 2026-08-06 on first reach with e1),
  implement (`.claude/skills/implementation/` + its inner loop `.claude/skills/tdd/`,
  decided 2026-08-07, ahead of first reach), gate (`.claude/skills/drift-gate/`, decided
  2026-08-07, codified from the e1 fresh-context prototype run of 2026-08-06), impl gate
  (`.claude/skills/impl-gate/`, decided 2026-08-07, ahead of first reach). Each gate
  runs only in a fresh session that did not author the artifact it checks: the drift
  gate stamps the plan section `GATED` (required by the implement skill at entry); the
  impl gate checks the finished branch against plan and spec pre-push and stamps the
  delivery `Status:` `IMPLEMENTED` — the plan stamp is untouched (push stays
  human-gated). Since 2026-08-15 both gate skills delegate the adversarial read to
  read-only agents in `.claude/agents/` — `drift-gate-agent`, `impl-gate-agent`, and
  `adv-reviewer-agent` (a spec-and-diff-only reviewer the impl gate spawns in parallel;
  its findings land as their own **Adv review** rounds) — while the skills stay the
  stage owners: ceremony, rounds, and stamps. The fresh-session rule above is
  unchanged. All six stages are defined. One optional stage input is
  also defined: a spec-anchored mockup for items whose spec names the portal as a system
  element (`.claude/skills/mockup/`, decided 2026-08-07 on first reach with W3) — plan-stage
  evidence only, kept scratch outside the repo, never a tracked artifact; items without a
  UI surface skip it.
- **One artifact-shape decision is recorded the same way (decided 2026-08-12, engagement
  owner): every item from e6 onward carries all six stages in a single file** — the
  one-file shape below. Items landed before it stay in the five-file shape as delivered.
  The pipeline itself is unchanged: same six stages, same gates, same codex loop on every
  PR.

## Layout

Two shapes coexist; the split is by item (decided 2026-08-12, above):

```
docs/workflow/
  <item>.md   ← one file per item, all six stages — every item from e6 onward, wN and
                eN alike
  wN/, eN/    ← five-file dirs (requirements / spec / plan / pr-body / findings) —
                every item before e6 (w1–w3, e1, e2, e4, e5). Closed record, cited by
                path, stays untouched. e2 alone is undelivered (parked at
                requirements-DRAFT); whether it converts or continues five-file is an
                owner call at resume.
```

The five-file shape's per-file rules and its three state-decode tables live in this
README's pre-2026-08-12 history (`git log -- docs/workflow/README.md`); nothing still
moving uses them.

### The one-file shape (`docs/workflow/<item>.md`)

Sections in order. Each stage's skill authors its section and owns that section's
authoring rules — this README owns only the shape-level rules below the table.

| Section | Content | Rules owned by |
|---|---|---|
| header | `Status:` line (decode table below) · one-line item description · `Baseline at branch:` — the **single site** for the item's suite count, filled when the impl branch is cut | this README |
| `## Decisions` | the item's single decision register | this README |
| `## Requirements` | `Status: DRAFT \| AGREED <date>` · owner-decision table, `<item>-REQ-n` | `requirement-synthesis` |
| `## Spec` | `Status: DRAFT \| FROZEN <date>` · EARS table with the check column | `spec-authoring` |
| `## Plan` | `Status: DRAFT \| GATED <date>` · deltas only | `plan-authoring` |
| `## Findings` | round log; one `### <Stage> — round N, <date>` per round, stages in pipeline order: **Req-review** (`requirement-synthesis`) · **Gate** (`drift-gate`) · **Impl gate** (`impl-gate`) · **Adv review** (`impl-gate`, findings of its spawned `adv-reviewer-agent`) · **Review** (`implementation`) | this README (round shape) · the stage skill (what it checks) |
| `## Delivery` | PR #, merge sha, baseline movement, deviations from the gated plan, live-run evidence, residual IDs | `implementation` |

Shape-level rules, owned here:

- **Header fields and their writers.** Three fields; each transition has exactly one
  writing stage, and no other stage edits the header.

  | Header field / transition | Written by |
  |---|---|
  | one-line item description | `requirement-synthesis`, at file creation |
  | `Baseline at branch:` | `implementation`, once, at branch cut |
  | `Status:` → `requirements DRAFT` → `requirements AGREED` | `requirement-synthesis` |
  | `Status:` → `spec FROZEN` | `spec-authoring` |
  | `Status:` → `plan DRAFT` | `plan-authoring` |
  | `Status:` → `plan GATED` | `drift-gate` |
  | `Status:` → `delivery DRAFT` → `delivery PUSHED PR #n` | `implementation` |
  | `Status:` → `delivery IMPLEMENTED` | `impl-gate` |
  | `Status:` → `delivery MERGED <sha>` | `noncode-merge` |

  Once delivery starts the line carries **both axes** (`plan GATED · delivery DRAFT`): a
  delivery transition never rolls back the plan stamp, and a section's own `Status:` and
  the header always agree. Each writing stage advances the header in the same edit that
  stamps its own section — the two never diverge across sessions.
- **Size budget (decided 2026-08-12 with the shape).** Default cap **400 lines** per
  `docs/workflow/<item>.md`, checked at the impl gate (`.claude/skills/impl-gate/`),
  raised only by a stage-tagged decision in the item's own register that says why. Basis:
  e5 carried ~2,600 artifact lines across five files and the shape targets roughly an
  order of magnitude less, so 400 is that target plus headroom — a backstop, not a target
  to fill. The authoring rules (deltas only, evidence by reference, ≤5-line notes) do the
  real work. Skill-run, so **advisory by construction** (`CLAUDE.md` §11): it fails no
  build unless the owner moves it into CI or the `Makefile`.
- **Decision register.** One per item, stage-tagged (`req` / `spec` / `plan`), IDs
  `<item>-D-n` allocated once and **never renumbered** — withdrawn or revised entries stay
  visible (strike-through, primes), same id discipline as `docs/todo.md`. Rationale that
  outgrows a table cell lives in the register; every other section — and every round
  disposition — cites the ID instead of restating the argument.
- **Stable-ID citation.** Workflow artifacts are cited by stable ID — `e6-D-2`,
  `e5-SPEC-32`, `E-3` — **never by an artifact's line numbers**, within an item, across
  items, and from the registries. Artifact lines move; IDs do not. Code is still cited
  `path:line`.
- **`E-n` evidence blocks.** A dated measurement with no durable ref (live API state,
  CI-run timings, click-ops config) is recorded **once**, as an `E-n` row in a dated table
  in whichever section it grounds; everything else cites the ID. Where a durable ref
  exists — a sha, a tracked file — cite that instead. Recording is for what git cannot
  replay.
- **Landing.** Before the impl branch is cut, the file is **working-tree only** (as
  `pr-body.md` was). From branch cut, it **rides the code branch** and lands with the code
  PR — the codex loop reviews it with the diff it describes. The post-merge status stamp
  (`delivery MERGED <sha>`) is the only `noncode-merge` edit.

### State decode (one table)

The header `Status:` line carries the furthest stage reached, one line, updated in place:

```
Status: requirements DRAFT → requirements AGREED → spec FROZEN → plan DRAFT → plan GATED
        → plan GATED · delivery DRAFT → IMPLEMENTED → PUSHED PR #n → MERGED <sha>
```

| `Status:` line + Findings rounds observed | State |
|---|---|
| `requirements DRAFT` | stage 1 in progress; a Req-review round with empty dispositions = owner findings pending fold-in |
| `requirements AGREED` | stage 2 may start |
| `spec FROZEN` | stage 3 may start |
| `plan DRAFT`, no Gate round | gate not yet run |
| `plan DRAFT`, latest Gate round has empty dispositions | stage-3 revision pending |
| `plan DRAFT`, Gate dispositions filled | re-gate pending (full fresh re-run) |
| `plan GATED`, no delivery axis | implementation not started |
| `delivery DRAFT`, branch complete, no Impl-gate round | impl gate not yet run |
| latest Impl-gate round has empty dispositions | stage-4 fix pending |
| Impl-gate dispositions filled, delivery still `DRAFT` | re-gate pending |
| `delivery IMPLEMENTED` | push-ready; push is human-gated |
| `delivery PUSHED PR #n`, no Review round | pushed; codex not yet run |
| latest Review round has empty dispositions | stage-4 fix pending |
| Review dispositions filled, delivery still `PUSHED` | re-review pending |
| `delivery MERGED <sha>` | delivered; the stamp is the post-merge `noncode-merge` edit |

A round with findings is a table, one row per finding:

```
| # | anchor | finding | disposition |
```

— anchor is the SPEC/REQ/decision ID, or `path:line` for code; the finding is one line;
the disposition cell is **empty when the round is written** and filled by the stage that
addresses it, in the form `.claude/skills/implementation/` "Addressing a round" defines
(label per `docs/review-loop-metrics.md` §1, then `fixed @<sha>` or
`declined: <clause> → <ID>`). The decode table's "empty dispositions" rows key on exactly
that cell.

A round is numbered within its stage only. A dry round is one `checked:` line naming what
it covered — a dry round's value is knowing what it checked. **Every gate run leaves a
round**: its findings when it has them, a dry `checked:` round when it is clean. The
decode table reads "no Gate round" as *the gate has not run*, which is only sound if a
clean run still records one. A stage that has not run has no rounds.

## Ground rules

- Requirements come fresh from the engagement owner each week; the deprecated specs are
  archive, not input.
- `eN` items are internal enablers (source: engagement team, not the client) — same
  pipeline, same artifact, numbered separately so `wN` stays client asks only.
  (Decided 2026-08-06 with `e1`.)
- Repo-wide rules still bind every stage: `docs/landmines.md` (approval-gated zones,
  change safety, negative tests), `CONTRIBUTING.md` (branching, commits, PR process).
