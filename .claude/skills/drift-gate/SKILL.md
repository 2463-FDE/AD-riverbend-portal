---
name: drift-gate
description: Gate stage of the delivery workflow (docs/workflow/README.md) — fresh-context adversarial check of a DRAFT plan against its frozen EARS spec, both sections of docs/workflow/<item>.md. Stamps the Plan section GATED or returns findings to stage 3. Use when a plan draft is complete and the user says "run the gate", "gate the plan", or invokes /drift-gate.
---

# Plan/spec drift gate

Input: `docs/workflow/<item>.md` with `## Spec` at `Status: FROZEN` and `## Plan` at
`Status: DRAFT`.
Output: either the Plan section stamped `Status: GATED <date>` (header `Status:` line
advanced to match), or a `### Gate — round N, <date>` round appended to `## Findings`
and the plan back to stage 3 (spec unchanged, per the pipeline). The round log — not
chat history or session memory — carries findings between sessions; item state must
always be derivable from the file alone.

The mechanism is codified from the e1 prototype run (2026-08-06): a fresh-context read of
the plan against the spec caught real gaps the authoring session could not see. The fresh
context is the mechanism, not a nicety.

## Two hard rules

1. **The gate never runs in the session that authored or amended the plan.** If this
   session wrote any part of the Plan section, stop and tell the owner to invoke the gate
   in a new session.
2. **The gate session never edits the Requirements, Spec, or Plan content.** It writes
   exactly two things: Gate rounds in `## Findings`, and — on a clean run — the Plan
   `Status:` stamp (plus the matching header line). Revisions happen in stage 3
   (`.claude/skills/plan-authoring/`), and the revised plan gets a full fresh gate run
   against its final text. No stamping a plan amended mid-gate — analyze-and-amend in one
   motion leaves the final text never checked as a whole (the e1 lesson).

## Process

**Mechanical half** (each check is a lookup, scriptable later):

1. **Check map complete:** every SPEC row carries exactly one `test:` / `cmd:` / `gate:`
   mechanism (`.claude/skills/spec-authoring/` owns the column's rules).
2. **⚠ coverage:** every ⚠ row is covered by an approval recorded in the plan's
   Landmines block, citing a decision ID (`.claude/skills/plan-authoring/` owns the
   block's rules). A zone entered with no recorded approval is a finding, always.
3. **Freeze scope:** the frozen set contains no SPEC rows for requirements marked
   `DEFERRED → <item>`.
4. **Cites resolve:** every SPEC and decision ID the plan cites exists in this file;
   spot-verify the plan's in-repo facts (paths, symbols, config values) against the
   working tree — a wrong fact is a finding.

**Judgment half:**

5. **Read the Spec section first, alone.** List every SPEC id and note what you would
   expect a plan to do about each — expectations from the contract, then the plan tested
   against them, not the reverse.
6. **Close the change list both ways:** every SPEC id is served by a change (or by an
   existing behavior the plan names); every change traces to a SPEC id, a decision ID, or
   named registry upkeep. Unmapped either way is a finding.
7. **Run the three checks** from `.claude/skills/plan-authoring/` (self-consistency, gate
   interaction, residual honesty) against the final text, cold.
8. **Per-SPEC verdict**, every id: **satisfied** / **residual-named** (partial, residual
   written in the Landmines block) / **FINDING**. A partial whose residual is not written
   down is a finding, not a residual.
9. **Verification is runnable:** numbered commands with expected output, SPEC-cited,
   including negative (break-then-revert) checks.

## Outcome

- **Any finding → no stamp.** Append `### Gate — round N, <date>` to `## Findings`
  (README owns the round format), findings SPEC-cited, one line each, disposition column
  empty for stage 3. Plan returns to stage 3; spec unchanged. Re-gate is a full re-run,
  fresh session.
- **Clean → stamp.** Set the Plan section to `Status: GATED <date>`, advance the header
  `Status:` line, and close with a dry round: one `checked:` line naming the scope
  covered (ids checked, map state, ⚠ coverage) — a dry round's value is knowing what it
  checked.

Round numbers count this stage's rounds only. **Round-3 rule:** a third round with any
open finding stops the loop. Report to the owner, who decides per finding: accept as a
named residual, overrule, or change the spec (stage 2, explicit decision). Each call is
recorded in that finding's disposition cell; the next gate run honors recorded owner
decisions rather than re-flagging them.

## Never

- Never gate a plan this session helped write.
- Never edit Requirements/Spec/Plan content from the gate session — Gate rounds and the
  clean-run stamp are the only writes.
- Never stamp with an open finding, however minor — minor goes back to stage 3 cheaply.
- Never hand findings off through chat or memory alone — if it isn't in the round log,
  the next session doesn't know it.
