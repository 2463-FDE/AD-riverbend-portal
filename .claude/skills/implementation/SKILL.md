---
name: implementation
description: Stage 4 of the delivery workflow (docs/workflow/README.md). Turn a gated plan into merged code — branch, TDD slice loop, full-suite + baseline check, PR, codex review. Use when a work item's plan has passed the gate and the user says "start implementation", "impl stage", or invokes /implementation.
---

# Implementation

Input: the plan file `docs/workflow/plans/<item>.md` — for a ticketed item, the ticket
file `docs/workflow/plans/<item>/<ticket>.md`, one branch and PR per ticket — with
`## Plan` at `Status: GATED` (contract file `docs/workflow/<item>.md` header, or the
ticket's `Status:` line and `## Delivery` table row, agrees). Refuse to start from a DRAFT
plan — the gate runs first, and starting early is how drift ships.
Output: a merged PR whose changes trace to the plan's change list, with the spec
untouched.

## Entry checklist

- Spec `FROZEN`, plan `GATED` — the contract header `Status:` line agrees (single
  ticket), or the ticket file's `Status:` line and its ticket row do (ticketed; README
  ticket row).
- Plan touches a `docs/landmines.md` §1 approval-gated zone (auth, PHI columns,
  ROI/disclosure, migrations, secrets)? Confirm the human approval is recorded in the
  plan's Landmines block before writing code. No record → stop and ask.
- Branch off `main` per `CONTRIBUTING.md`. Never implement on `main`.
- **The contract and `plans/<item>.md` are on `main` at `spec FROZEN`; the ticket file,
  and every register or contract-row edit since FROZEN, first reach `main` in this
  ticket's code PR** (README landing rule, 2026-08-28 — `plan GATED` is a branch cut, not
  a landing). From branch cut, every artifact edit — the contract, `plans/<item>.md`, the
  ticket file — rides the code branch, and every subsequent edit (round logs,
  dispositions, Delivery) is committed here, reviewed with the diff it describes.
  **First commit on the branch = the stamped artifacts** — the ticket file, `plans/<item>.md`
  as it stands, the contract's ticket-row edit — plus the header's `Baseline at branch:`
  line (ticket: the ticket's `## Delivery` table row) from a fresh measurement — that line
  is the single site for the number. **Push at that commit** (a draft PR is optional; the
  push is what preserves the stamp). **Parallel tickets:** once a ticket's branch is cut,
  its ticket file lives on that branch — a sibling ticket's stage-3 session that edits it
  cross-ticket commits onto that branch (or leaves the edit in that branch's worktree),
  never onto `main` or a `wip/` branch; the item-wide register `plans/<item>.md` rides the
  **first** cut branch with every pending register edit, and later branches rebase onto it
  after that PR merges. Stamped ticket files whose branch is not yet cut wait on
  `wip/<item>-plans`, pushed.

## Slice loop

Work the change list in order. Each slice runs the `tdd` skill's loop: one EARS row →
failing test at the plan's seam → minimal code → green → next. The test takes the name
the spec's `test:` cell planned; fill the cell with the final id as you go — the impl
gate checks the map is complete, and a **pinned test changes only by owner decision**
(the impl gate diffs for it).

Slices with no behavioural seam — CI wiring, build config, tooling — skip the TDD loop;
the plan's Verification section covers them, and Delivery says which slices ran
test-first and which didn't.

Deviation handling, per the pipeline:

- **Plan fact wrong, fix trivial** (path moved, name changed): patch, record one line in
  `## Delivery` deviations, continue.
- **Plan design wrong** (seam doesn't hold, change fights a wall): stop. Back to stage 3;
  plan revised and re-gated; spec unchanged. Do not improvise structure mid-loop.

## Evidence — by reference, never restatement

Owned here; every stage-4 record follows it:

- A claim a git object proves is cited (`fixed @<sha>`), never narrated — `git show` is
  the evidence.
- Evidence with no diff (live runs) is a command + outcome note, **≤5 lines**. Exception,
  mandatory: a live run adjacent to a `docs/landmines.md` §1 zone or any irreversible
  operation states its **isolation mechanism in one clause** ("scratch DB, real service
  stopped, compose DNS re-aliased") — that clause is the safety evidence and is never
  dropped for brevity.
- A dated measurement with no durable ref goes in an `E-n` block (README rule), cited by
  ID thereafter.
- Full reasoning is written out only where a finding is **contested** — a disputed
  premise gets the argument, once, in the decision register, and everything else cites it.

## End-of-implementation verification

1. Full suite: `make test-docker` (the claim-worthy gate) or
   `.venv/bin/python -m pytest -m "not integration" -q`.
2. Compare against the header's `Baseline at branch:` (single ticket) or the ticket
   row's `baseline at branch` cell (ticketed). Passed grows by exactly the tests
   this branch adds; **xfailed and deselected must not move**. A moved count is a finding
   to report, not a number to update.
3. `make eval` if anything under `eval/rag/` or the retrieval path changed.
4. Traceability: every `test:` cell in the frozen spec is filled with a real test id, or
   Delivery records why not.
5. Run the plan's Verification section end-to-end, including its negative
   (break-then-revert) checks; record outcomes in `## Delivery` per the evidence rule.
6. Write `## Delivery` (contract file; advance the **delivery axis** to `delivery DRAFT`
   — single ticket: the contract header; ticketed: the ticket file's `Status:` line and
   the `delivery` cell of its ticket row; every such write moves one axis and leaves
   `plan GATED` standing — README): deviations with
   rationale; slices test-first vs not; any planned slice absent from the diff and why —
   an empty result is still recorded; live-run evidence; **residuals as registry IDs
   only** (below). The impl gate checks this section; the branch is not gate-ready
   without it. Commit messages and session memory do not carry disclosures — if it isn't
   in the file, the gate and the next session don't know it.

## Residuals — registries only

Owned here: every residual gets exactly one entry where the registry contract puts it
(`docs/debt-log.md` risk / `docs/todo.md` loose end / a successor item's requirements),
filed at landing; `## Delivery` carries the ID and nothing else. No restating a residual
across the artifact, the PR body, and the registry — one home, cited.

## Landing

- Commits: format per `CONTRIBUTING.md`; no `Co-Authored-By` trailer
  (`CONTRIBUTING.md:53`).
- **Impl gate before push:** the finished branch is checked by `.claude/skills/impl-gate/`
  in a fresh session that did not write the code. Findings come back as an
  `### Impl gate` round; the delivery `Status: IMPLEMENTED` stamp is what makes the
  branch push-ready. The plan stamp stays `GATED`.
- **Ask before pushing.** Push is human-gated.
- PR body: drafted at push time from `## Delivery` and the plan's Landmines block. The
  "Risk & landmines" section is required and comes from the Landmines block verbatim.
  The dispositions-of-record section states that **the plan files in the diff are
  context, not review targets** — a codex finding on plan prose is answered from the
  round log and routed per `noncode-merge`'s table (plan design content → stage 3 +
  re-stamp), never by re-opening the plan inside the code round.
  Know what disclosure buys: it informs human readers and anchors the fix session — it
  does **not** prevent rediscovery, because the reviewer reads the diff, not the prose
  (`docs/review-loop-metrics.md` §4 carries the measurements and outranks this line if
  they diverge). The only thing that reduces the visible-residual cost is accepting fewer
  of them.
- **After push:** advance the delivery axis (single ticket: the contract header;
  ticketed: the ticket file's `Status:` line and its ticket row) to
  `delivery PUSHED PR #<n>` (the `plan GATED` half is untouched),
  commit, then comment
  `@codex-review`. Work each round per "Addressing a round"; iterate until dry. On merge,
  `noncode-merge` makes the two post-merge commits on `main`: delete the plan file that
  merged (`docs/workflow/plans/<item>.md`, or the ticket file — plus `plans/<item>.md`
  with the last ticket), then stamp `delivery MERGED <sha>` and record the
  deletion sha in `## Delivery` (README landing rule). This skill owns the push→review→merge segment; the artifact, not
  memory, carries its state.

## Addressing a round (the fix session)

The procedure for responding to a codex round. Label definitions and the measured
reasoning live in `docs/review-loop-metrics.md` (§1 labels, §3 baseline) — that file is
the why, this section is the how.

1. Append `### Review — round N, <date>` to the plan file's `## Findings`, one row per
   finding (first round's lead line names the PR # and reviewer once).
2. **Label** each finding A/B/C/E per `docs/review-loop-metrics.md` §1. A finding
   believed wrong is refuted with runtime evidence (build it, run it, hit the endpoint —
   never inference from static config) and closed with an anchored comment, no code
   change. **A finding that restates a recorded decision or accepted residual is answered
   from the record, not re-litigated:** the disposition cites the decision register ID or
   the registry entry — the argument lives there, once. Reopening is the owner's call
   only; the fix session neither re-accepts nor silently fixes it.
3. **Cluster** findings that share one root cause; fix causes, not instances.
4. **Route** each cluster:
   - The fix would introduce or alter state (counter, TTL, lock, breaker, budget,
     cache) → structural. Back to stage 3; plan revised and re-gated; spec unchanged.
     Every B round in the baseline came from improvising exactly this mid-review.
   - Labelled **C** (an earlier fix didn't close it) → fix the class and add the guard or
     regression test that proves the class is closed, not another instance patch.
   - Otherwise trivial: patch on the branch. PHI, authz, and sanitization paths take the
     negative test (`docs/landmines.md` §3).
5. **One disposition, one commit.** Each disposition is a commit whose message cites it
   (`<item> round-R finding-F`); the disposition cell is `A/B/C/E · fixed @<sha>` or
   `declined: <one clause> → <decision/registry ID>`. A genuinely multi-commit fix may
   cite a commit range — the rule is *resolvable by git command*, not single sha.
6. Re-verify: full suite plus the baseline count check (steps 1–2 above).
7. Close the round: fill dispositions, reply with the `rN:` disposition comment carrying
   the labels, append one ledger line to `docs/review-loop-metrics.md` §4, re-tag
   `@codex-review`.

Round numbers count this stage's rounds only. **Round-3 rule:** a third round with any
open finding stops the loop; the owner accepts as a named residual, overrules, or sends
the item back to stage 3, per finding, recorded in the disposition cell; the next round
honors recorded decisions rather than re-raising them.
