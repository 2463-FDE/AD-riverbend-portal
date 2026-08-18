---
name: impl-gate
description: Pre-push gate of the delivery workflow (docs/workflow/README.md) — fresh-context adversarial check of an implementation branch against its GATED plan (docs/workflow/plans/<item>.md) and frozen EARS spec (docs/workflow/<item>.md), before push and codex review. Stamps delivery IMPLEMENTED (the plan stamp is untouched) or returns findings to stage 4. Use when implementation is complete and the user says "run the impl gate", "pre-push review", or invokes /impl-gate.
---

# Implementation gate (pre-push)

Input: the contract file `docs/workflow/<item>.md` with `## Spec` `FROZEN`, the plan
file `docs/workflow/plans/<item>.md` with `## Plan` `GATED`, and a completed
implementation branch (unpushed, or pushed but pre-review) carrying both files.
Output: either the contract header stamped `delivery IMPLEMENTED <date>` (the plan stamp
is not touched), or an `### Impl gate — round N, <date>` round appended to the plan
file's `## Findings` and the branch back to stage 4 (spec and plan unchanged). The round
log — not chat history or session memory — carries findings between sessions.

This gate covers what codex review cannot: codex sees the diff but never the spec, the
plan, or the repo's landmine rules. The impl gate anchors the diff to those artifacts.
The fresh context is the mechanism, not a nicety — the authoring session cannot see its
own drift (same lesson as `.claude/skills/drift-gate/`).

## Two hard rules

1. **The gate never runs in the session that wrote or amended the implementation.** If
   this session wrote any of the branch's code, stop and tell the owner to invoke the
   gate in a new session.
2. **The gate session never edits code, the Requirements/Spec/Plan sections, or anything
   stage 4 wrote in `## Delivery`.** It writes exactly two things: Impl-gate rounds in
   the plan file's `## Findings`, and — on a clean run — the delivery-axis header stamp
   plus its short gate record appended to `## Delivery` (both in the contract file),
   which is this gate's only Delivery write. Fixes
   happen in stage 4; the fixed branch gets a full fresh gate run. The spawned agents
   (below) add partial enforcement: Edit/Write are absent, so they cannot edit or stamp
   through those tools — but their `Bash` can still write the tree, so shell read-only
   behavior is a behavioral rule in each agent's definition, not tool enforcement. The
   sentence stays as intent for what this session writes.

## Process

The adversarial read runs in spawned agents with no Edit/Write tools; the check
procedures live in the agent definitions, one place each. This skill owns the ceremony: input-state check,
spawns, `gate:` observations, rounds, stamp.

1. **Verify input state:** `## Spec` `FROZEN` (contract file), `## Plan` `GATED` (plan
   file), the branch complete, and hard rule 1 holds for this session.
2. **Spawn two agents in parallel** (Agent tool), each with the item name and branch
   only — no characterization of the work. The agents read the item files and the diff
   themselves; that self-read is the structural replacement for prompt-authorship bias,
   and each agent reports any characterization it does receive as a finding.
   - `impl-gate-agent` (`.claude/agents/impl-gate-agent.md`) — the full check procedure:
     mechanical half (pinned-test diff, contract-file cap, `cmd:` cells, baseline
     re-run) and
     judgment half (spec-first read, diff closure both ways, planted-defect check, idiom
     sweep, delivery evidence).
   - `adv-reviewer-agent` (`.claude/agents/adv-reviewer-agent.md`) — independent
     correctness/spec review over the frozen Spec section and the diff only, **never the
     plan** — plan-bias is the failure mode it exists to escape.
3. **Collect `gate:` observations yourself.** Hand-run assertions and click-ops state
   reads cannot run inside an agent; `impl-gate-agent` lists every `gate:` cell as
   "human observation required" and this session records each observation — quoted in
   the round or, on a clean run, noted for `## Delivery` via the stage-4 session. A
   `gate:` row with no recordable observation is a finding.
4. **Write the outcome** (below). The agents never write; rounds and the stamp are this
   session's only writes.

## Outcome

- **Any finding → no stamp** — from either agent. Gate-agent findings go in an
  `### Impl gate — round N, <date>` round; adv-reviewer findings get their own
  `### Adv review — round N, <date>` round (README owns the round format), each
  SPEC-cited where applicable, one line each, disposition column empty for stage 4.
  Branch returns to stage 4; re-gate is a full re-run, fresh session, both agents.
- **Repeat of a dispositioned class → close the class, not the instance.** When a finding
  is the same failure class as one dispositioned in an earlier round of this loop — or as
  a fix already recorded on the branch before the gate — the round entry names the match,
  and closing it is not an instance fix: the disposition records that a sweep for further
  instances ran and what scope it covered, or a guard/test that reddens on the next
  instance. An instance-only fix is not an available disposition, owner included; if class
  closure needs a plan change, that is structural → stage 3 now, not at the third instance.
  This mirrors the drift-gate class-recurrence rule (`.claude/skills/drift-gate/`); it
  exists because w4's exposure-set miss was instance-patched at impl-gate r1/r3 and forced
  a stage-3 return at r4 — the same one-site-at-a-time cost the e6 rounds-2–4 lesson names.
- **Clean → stamp** — both agents clean and every `gate:` observation recorded.
  Advance the header's **delivery axis** to `delivery IMPLEMENTED <date>` — one axis,
  never the whole line; `plan GATED` stays as the drift gate set it (README) — and
  append a short gate record in `## Delivery`: date, "impl-gated fresh-context", branch and HEAD commit,
  baseline observed, `gate:` observations, residuals accepted here. The plan stamp stays
  exactly as the drift gate set it. Close with a dry `checked:` round line. The stamp
  means push-ready; **push itself stays human-gated** per
  `.claude/skills/implementation/`.

Round numbers count this stage's rounds only. **Round-3 rule:** a third round with any
open finding stops the loop; the owner accepts as a named residual, overrules, or sends
the item back to stage 3, per finding, recorded in the disposition cell; the next gate
run honors recorded decisions rather than re-flagging them.

## Never

- Never gate a branch this session helped write.
- Never edit code or the artifact's other sections — Impl-gate rounds and the clean-run
  stamp + gate record are the only writes.
- Never stamp with an open finding, however minor — minor goes back to stage 4 cheaply.
- Never fix a finding in-line "while you're there" — analyze-and-amend in one motion
  leaves the final state never checked as a whole.
- Never hand findings off through chat or memory alone — if it isn't in the round log,
  the next session doesn't know it.
