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
  spawned agents in `.claude/agents/` — Edit/Write are absent from their toolsets, so
  they cannot edit or stamp through those tools; `Bash` remains for read-only checks,
  so shell read-only behavior is a behavioral rule in each agent's definition, not tool
  enforcement — `drift-gate-agent`, `impl-gate-agent`, and
  `adv-reviewer-agent` (a spec-and-diff-only reviewer the impl gate spawns in parallel;
  its findings land as their own **Adv review** rounds) — while the skills stay the
  stage owners: ceremony, rounds, and stamps. The fresh-session rule above is
  unchanged. All six stages are defined. One optional stage input is
  also defined: a spec-anchored mockup for items whose spec names the portal as a system
  element (`.claude/skills/mockup/`, decided 2026-08-07 on first reach with W3) — plan-stage
  evidence only, kept scratch outside the repo, never a tracked artifact; items without a
  UI surface skip it.
- **Artifact-shape decisions are recorded the same way.** Decided 2026-08-12 (engagement
  owner): every item from e6 onward carries all six stages in one artifact rather than the
  five-file dir. **Decided 2026-08-18 (engagement owner): from w4 onward the artifact is
  two files** — the split shape below: a durable contract file (`docs/workflow/<item>.md`)
  and a working plan file (`docs/workflow/plans/<item>.md`) deleted at delivery. Basis:
  loop residue (gate rounds, disposition decisions) grows with review pressure, not
  authoring choice — w4's authored sections held near 362 lines while nine gate and
  impl-gate rounds drove its one file to 494, and cap housekeeping consumed gate findings
  in three separate rounds. The dual-budget alternative was rejected (PR #85, closed
  unmerged 2026-08-18; branch `chore/noref-size-budget-split` is the record). Items landed
  before a shape decision stay as delivered. **Decided 2026-08-25 (engagement owner):
  three shape rules dated in place below — landing at each stamp (Landing — **`plan GATED`
  removed as a landing 2026-08-28, see Landing**), one contract with N delivery tickets
  (Tickets), and feature-slug item names (Ground rules).** The
  pipeline itself is unchanged: same six stages, same gates, same codex loop on every PR.

## Layout

Three shapes coexist; the split is by item (decisions of 2026-08-12 and 2026-08-18,
above):

```
docs/workflow/
  <item>.md        ← contract file: header + Requirements + Spec + Delivery — every item
                     from w4 onward
  plans/<item>.md  ← plan file: Decisions + Plan + Findings — same items, in flight
                     only; deleted at delivery, deletion sha recorded in the contract's
                     ## Delivery
  plans/<item>/<ticket>.md
                   ← ticket plan file (ticketed items, rule of 2026-08-25): Scope + Plan
                     + Findings; deleted at its own merge. plans/<item>.md then holds
                     Decisions + item-level Findings only
  e5b.md, e6.md    ← one-file shape (all six stages in one file) — closed records as
                     delivered, stay untouched
  wN/, eN/         ← five-file dirs (requirements / spec / plan / pr-body / findings) —
                     every item before e6 (w1–w3, e1, e2, e4, e5). Closed record, cited
                     by path, stays untouched. e2 alone is undelivered (parked at
                     requirements-DRAFT); its shape at resume is an owner call.
```

The one-file shape's rules live in this README's pre-2026-08-18 history, the five-file
shape's in its pre-2026-08-12 history (`git log -- docs/workflow/README.md`); nothing
still moving uses either.

### The split shape (`docs/workflow/<item>.md` + `docs/workflow/plans/<item>.md`)

Each stage's skill authors its section and owns that section's authoring rules — this
README owns only the shape-level rules below the tables. Both files are created together
at stage 1: req-review rounds and `req`-tagged decisions are plan-file content from the
first session.

**Contract file — `docs/workflow/<item>.md`.** Durable; outlives the item.

| Section | Content | Rules owned by |
|---|---|---|
| header | `Status:` line (decode table below) · one-line item description · `Baseline at branch:` — the **single site** for the item's suite count, filled when the impl branch is cut (ticketed items: `per ticket — see ## Delivery`; the ticket row is the single site) | this README |
| `## Requirements` | `Status: DRAFT \| AGREED <date>` · owner-decision table, `<item>-REQ-n` | `requirement-synthesis` |
| `## Spec` | `Status: DRAFT \| FROZEN <date>` · EARS table with the check column | `spec-authoring` |
| `## Delivery` | PR #, merge sha, baseline movement, deviations from the gated plan, live-run evidence, residual IDs, plan-file deletion sha · ticketed items: the ticket table first (one **ticket row** per ticket — columns and legal values in the Tickets rule below), then a **`### Per-ticket delivery records`** table, one row per ticket, carrying references only — branch / stamp / series shas, baseline movement, the test-first vs verification-covered split, traceability, residual registry IDs (**decided 2026-08-29, engagement owner**, from `eligibility-assistant` `corpus` impl-gate r1 f1: six prose records at the shape first written measured 784 lines against the 400 cap, and 418 even compressed, because a wrapped paragraph costs physical lines while a table row costs one whatever its length; deviations, the stamp-commit scope note and live-run detail move to the ticket file's `## Delivery evidence`) **Dated note 2026-08-30 (`eligibility-assistant-D-83`):** the impl-gate summary — gate and adv-review rounds, waiver bases, merge-base, gate-time baseline, `gate:` observations, residuals accepted, merge sha and codex rounds — rides that same record row. Written as its own wrapped `**Impl gate — <ticket>**` block per ticket it cost `eligibility-assistant` 41 physical lines and took the contract to 400/400 with three tickets unlanded; same physical-line argument, same resolution. | `implementation` (ticket table created by `plan-authoring`) |

**Plan file — `docs/workflow/plans/<item>.md`.** Working state; deleted at delivery.
(Ticketed items: the Tickets rule below moves `## Plan` and the per-ticket rounds into
`plans/<item>/<ticket>.md`; this file keeps `## Decisions` and the item-level rounds.)
Stage 1 creates the file with `## Decisions` only; `## Plan` and `## Findings` are each
**created by their first writing stage** — the stage that appends the first round writes
the `## Findings` heading with it, positioned after `## Plan` (or last in the file while
`## Plan` does not exist yet, as with a req-review round).

| Section | Content | Ticketed item: lives in | Rules owned by |
|---|---|---|---|
| `Scope:` / `Status:` lines | ticket file only: `Scope:` = its SPEC ids · `Status:` = plan + delivery axes, mirrored by its ticket row | `plans/<item>/<ticket>.md` | this README |
| `## Decisions` | the item's single decision register | `plans/<item>.md` | this README |
| `## Plan` | `Status: DRAFT \| GATED <date>` · deltas only | `plans/<item>/<ticket>.md` | `plan-authoring` |
| `## Findings` | round log; one `### <Stage> — round N, <date>` per round, stages in pipeline order: **Req-review** (`requirement-synthesis`) · **Gate** (`drift-gate`) · **Impl gate** (`impl-gate`) · **Adv review** (`impl-gate`, findings of its spawned `adv-reviewer-agent`) · **Review** (`implementation`) | Req-review + Spec-review rounds in `plans/<item>.md`; Gate / Impl gate / Adv review / Review rounds in `plans/<item>/<ticket>.md` | this README (round shape) · the stage skill (what it checks) |
| `## Delivery evidence` | ticketed items, written by stage 4 at `delivery DRAFT`: the deviations from the gated plan, the stamp-commit scope note and the live-run detail the contract's record cites but does not restate · uncapped, read by the impl gate and the codex round beside the diff, deleted with the file at merge behind the ticket row's `plan-file deletion sha` · nothing that must outlive the item lives only here — the README's pre-delete sweep still carries every contract-cited decision ID into `## Delivery` (**decided 2026-08-29**, with the record-table rule above) | `plans/<item>/<ticket>.md` | `implementation` |

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
  stamps its own section — the two never diverge across sessions. The header lives in the
  contract file; a stage that stamps a plan-file section (`plan DRAFT`, `plan GATED`)
  advances the contract header in that same edit — one write, two files. **Ticketed
  items:** the contract header stops at `spec FROZEN`; every plan and delivery transition
  is written, by the same stage, to the ticket file's `Status:` line and the ticket's row
  in the contract's `## Delivery` table — same one-write-two-files rule, ticket row in
  place of header.
- **Size cap (decided 2026-08-12 with the one-file shape; rescoped 2026-08-18 with the
  split).** **400 lines, contract file only, CI-enforced**: `.github/workflows/ci.yml`'s
  `workflow-doc-cap` job caps every top-level `docs/workflow/*.md` at 400 (`e5b.md`
  carries a shrink-only ratchet exemption; `docs/todo.md` TODO-68 tracks that the
  exemption list is review-enforced) and is a `needs:` dependency of the terminal gate,
  so an over-cap contract file blocks merge. This corrects in place the "advisory by
  construction" claim this bullet carried from 2026-08-12 — falsified 2026-08-15 when
  PR #80 (`e9c6009`) put the job in CI, and uncorrected until 2026-08-18. The impl gate
  re-checks the same number pre-push as early warning. Basis unchanged: e5 carried ~2,600
  artifact lines across five files; 400 is roughly an order of magnitude less plus
  headroom — a backstop, not a target to fill. The plan file (`plans/<item>.md`) is
  **outside the job's glob and uncapped by design**: rounds and register rows are
  append-only, carry no compression duty, and the file is deleted at delivery — history
  keeps it. Review pressure is never charged against an authoring cap. **Dated note 2026-08-29:** a ticketed contract carries N delivery records against the same 400, and `eligibility-assistant` measured its non-record content at 340 — so the record shape, not the cap, is what had to give; the `## Delivery` row above states the resolution. The cap was **not** raised and no exemption was added: the ratchet holds.
- **Decision register.** One per item, in the plan file, stage-tagged (`req` / `spec` /
  `plan`), IDs `<item>-D-n` allocated once and **never renumbered** — withdrawn or
  revised entries stay visible (strike-through, primes), same id discipline as
  `docs/todo.md`. Rationale that outgrows a table cell lives in the register; every other
  section — and every round disposition — cites the ID instead of restating the argument.
  The register is deleted with the plan file at delivery: **every decision ID the
  contract file cites is carried as a one-line decisions-of-record entry in `## Delivery`
  before the delete** — `noncode-merge` runs the blocking pre-delete sweep — and
  rationale that must outlive the item lands in `## Delivery` or the registries before
  the stamp. Only decisions the contract never cites resolve through the recorded
  deletion sha alone.
- **Tickets (decided 2026-08-25, engagement owner).** One contract, N delivery tickets.
  An item splits into tickets when a subset of its SPEC rows can be planned, gated,
  reviewed, and landed — dark landing allowed — without the rest (the test
  `eligibility-assistant-D-34` first applied); size alone never splits. Each ticket has
  its own plan file `plans/<item>/<ticket>.md` — a `Scope:` line naming its SPEC rows, a
  `Status:` line (plan + delivery axes), `## Plan` with its own Landmines block,
  `## Findings` (Gate · Impl gate · Adv review · Review rounds, numbered per ticket) —
  and its own gate, impl gate, branch, PR, and baseline. `plans/<item>.md` keeps the one
  `## Decisions` register (item-wide; any ticket's stage appends to it, IDs never
  renumbered) and the item-level Findings (Req-review, Spec-review). Stage 3 creates the
  ticket files and the contract's ticket table — the split is a `plan`-tagged decision
  in the register; a ticket whose SPEC rows do not exist yet is a named row in the table,
  not a file. Every frozen SPEC row is owned by exactly one ticket; the drift gate checks
  the ticket's scope rows and flags any orphan. A ticket file is deleted at its own merge,
  `plans/<item>.md` at the last ticket's; the pre-delete sweep runs per file.
  Single-ticket items keep the shape above unchanged.

  **The ticket row** — the contract's `## Delivery` ticket table, one row per ticket,
  exactly these columns; every stage that would write the contract header for a
  single-ticket item writes this row (and the ticket file's `Status:` line) instead:

  | ticket | SPEC rows | plan | baseline at branch | delivery | plan-file deletion sha |
  |---|---|---|---|---|---|
  | `corpus` | `<item>-SPEC-7–11, 38, 43` | `GATED 2026-08-27` | `1334 passed, 19 deselected, 1 xfailed` | `PUSHED PR #91` | — |

  Legal values: `plan` = `DRAFT` \| `GATED <date>`; `baseline at branch` = the measured
  counts, `—` until branch cut; `delivery` = `—` \| `DRAFT` \| `IMPLEMENTED <date>` \|
  `PUSHED PR #n` \| `MERGED <sha>`; `plan-file deletion sha` = `—` until the post-merge
  delete commit. A ticket whose rows are not yet frozen has `SPEC rows` = `pending
  <amendment>`, `plan` = `—`.
- **Stable-ID citation.** Workflow artifacts are cited by stable ID — `e6-D-2`,
  `e5-SPEC-32`, `E-3` — **never by an artifact's line numbers**, within an item, across
  items, and from the registries. Artifact lines move; IDs do not. Code is still cited
  `path:line`.
- **`E-n` evidence blocks.** A dated measurement with no durable ref (live API state,
  CI-run timings, click-ops config) is recorded **once**, as an `E-n` row in a dated table
  in whichever section it grounds; everything else cites the ID. Where a durable ref
  exists — a sha, a tracked file — cite that instead. Recording is for what git cannot
  replay.
- **Landing (rewritten 2026-08-25; `plan GATED` removed as a landing 2026-08-28; the
  2026-08-18 form is in history).** Both files land on `main` through `noncode-merge` at
  two stamps — `requirements AGREED`, `spec FROZEN` — each a small non-code PR on the
  codex loop; between stamps the edits are working tree or a `wip/` branch (shape:
  `wip/<item>-plans`, pushed after every stage-3 wave — nothing gates on it), never a
  landing. Basis: a stamped artifact on one machine is an unrecovered loss waiting to
  happen; codex reviews docs (decision of 2026-08-11); a spec finding is cheapest before a
  plan exists. The earlier "working-tree only until branch cut" rule rested on an analogy
  to `pr-body.md`, a file the split shape no longer has. **`plan GATED` is a branch cut,
  not a landing (engagement owner, 2026-08-28):** when the drift gate stamps a ticket
  `GATED`, the next act is `implementation`'s branch cut for that ticket, the first commit
  on the branch is the stamped artifacts — the ticket file, `plans/<item>.md` as it
  stands, the contract's ticket-row edit — and the branch is pushed at that commit after
  the owner's push approval (`implementation` owns the gate), together with a pushed
  `wip/<item>-plans` carrying every stamped ticket file whose branch is not yet cut; the
  two pushes are the preservation. From branch cut, both files **ride the code branch** and
  land with the code PR — **as context for the diff, never as review targets**: the review
  target of a code PR is the code against the spec; codex reads the plan as the intent the
  code is judged against (the drift gate is the plan's review by design; `adv-reviewer-agent`
  reads spec + diff with the plan withheld), and a codex finding on plan prose routes to
  stage 3 per `noncode-merge`'s table, fixed on the same code branch. Revisit if an
  impl-gate, adv-review or codex code round raises a finding a plan review would have
  caught at the design level. Post-merge, `noncode-merge` makes two commits on `main`: first delete the
  plan file that merged (`plans/<item>/<ticket>.md`, plus `plans/<item>.md` with the last
  ticket; single-ticket items: `plans/<item>.md`), then stamp `delivery MERGED
  <merge-sha>` and record the deletion sha in `## Delivery` (a commit cannot cite its own
  sha). Rounds, and plan-file decisions the contract never cites, resolve through that
  sha — the same delete-history-keeps-it rule as doc archiving. A **contract-cited**
  decision never resolves through the sha alone: it resolves through the
  decisions-of-record entry the pre-delete sweep guarantees in `## Delivery` (register
  rule above).

### State decode (one table)

The header `Status:` line carries the furthest stage reached, one line, updated in place:

```
Status: requirements DRAFT → requirements AGREED → spec FROZEN → plan DRAFT → plan GATED
        → plan GATED · delivery DRAFT → delivery IMPLEMENTED → delivery PUSHED PR #n
        → delivery MERGED <sha>
```

Round-dependent rows decode an **in-flight** item from its plan file; once
`delivery MERGED` the plan file is deleted, so a merged item decodes from the contract
header alone — its rounds live in history behind the recorded deletion sha. A ticketed
item decodes **per ticket** from the same table: the ticket's `Status:` line and the
rounds in `plans/<item>/<ticket>.md`; the contract's `## Delivery` ticket table is the
at-a-glance view, and the header stops at `spec FROZEN`.

| `Status:` line + rounds observed in `plans/<item>.md` | State |
|---|---|
| `requirements DRAFT` | stage 1 in progress; a Req-review round with empty dispositions = owner findings pending fold-in |
| `requirements AGREED` | stage 2 may start |
| `spec FROZEN` | stage 3 may start |
| `plan DRAFT`, no Gate round | gate not yet run |
| `plan DRAFT`, latest Gate round has empty dispositions | stage-3 revision pending |
| `plan DRAFT`, Gate dispositions filled | re-gate pending (full fresh re-run) |
| `plan GATED`, no delivery axis | branch cut pending — the cut is the stamp's landing |
| `delivery DRAFT`, branch complete, no Impl-gate round | impl gate not yet run |
| latest Impl-gate round has empty dispositions | stage-4 fix pending |
| Impl-gate dispositions filled, delivery still `DRAFT` | re-gate pending |
| `delivery IMPLEMENTED` | push-ready; push is human-gated |
| `delivery PUSHED PR #n`, no Review round | pushed; codex not yet run |
| latest Review round has empty dispositions | stage-4 fix pending |
| Review dispositions filled, delivery still `PUSHED` | re-review pending |
| `delivery MERGED <sha>` | delivered; the stamp + plan-file deletion are the post-merge `noncode-merge` edits |

A round with findings is a table, one row per finding:

```
| # | anchor | finding | disposition |
```

— anchor is the SPEC/REQ/decision ID, or `path:line` for code; the finding is one line;
the disposition cell is **empty when the round is written** and filled by the stage that
addresses it, **in the form that stage's skill defines** — label per
`docs/review-loop-metrics.md` §1 first, always; then the stage's own fields:
`.claude/skills/implementation/` "Addressing a round" (`fixed @<sha>` or
`declined: <clause> → <ID>`) for Impl-gate / Adv-review / Review rounds,
`.claude/skills/plan-authoring/` "Revision after a gate round" for Gate rounds (a closing
`Sites changed:` list, the basis the next gate's origin tags derive from). The decode table's "empty dispositions" rows key on exactly
that cell.

A round is numbered within its stage only (and within its ticket file, for ticketed
items). A dry round is one `checked:` line naming what
it covered — a dry round's value is knowing what it checked. A round with findings
closes with the same `checked:` line; what the line carries beyond scope (the gate's
plan-text hash and origin tally, for one) is the stage skill's to define, not this
README's. **Every gate run leaves a
round**: its findings when it has them, a dry `checked:` round when it is clean. The
decode table reads "no Gate round" as *the gate has not run*, which is only sound if a
clean run still records one. A stage that has not run has no rounds.

## Ground rules

- Requirements come fresh from the engagement owner each week; the deprecated specs are
  archive, not input.
- `eN` items are internal enablers (source: engagement team, not the client) — same
  pipeline, same artifact, numbered separately so `wN` stays client asks only.
  (Decided 2026-08-06 with `e1`; superseded for new items by the naming rule below.)
- **Item names (decided 2026-08-25, engagement owner).** A new item is named by its
  feature — a kebab-case slug of two or three words (`eligibility-assistant`), never a
  letter prefix that needs decoding; its IDs follow the name (`<item>-REQ-n`,
  `<item>-SPEC-n`, `<item>-D-n`) and its tickets are one-word slugs under it
  (`plans/eligibility-assistant/corpus.md`). Client-ask vs enabler provenance is the
  contract's `Source:` line, not the name. Items already carrying `wN`/`eN` names stay as
  delivered (archive rule).
- Repo-wide rules still bind every stage: `docs/landmines.md` (approval-gated zones,
  change safety, negative tests), `CONTRIBUTING.md` (branching, commits, PR process).
