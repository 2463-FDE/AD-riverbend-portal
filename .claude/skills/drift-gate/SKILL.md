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
   motion leaves the final text never checked as a whole (the e1 lesson). The adversarial
   read itself gets partial tool enforcement beyond this sentence: the spawned agent
   (below) carries no Edit/Write, so file edits are structurally blocked; its Bash is
   limited to read-only checks by its own definition — instruction, not enforcement. The
   sentence stays as intent for what this session writes.

## Process

The adversarial read runs in a spawned agent with no Edit/Write tools —
`.claude/agents/drift-gate-agent.md` owns the check procedure (mechanical and judgment
halves), one place. This skill owns the ceremony: input-state check, spawn, rounds,
stamp.

1. **Verify input state:** `## Spec` at `FROZEN`, `## Plan` at `DRAFT`, and hard rule 1
   holds for this session.
2. **Spawn `drift-gate-agent`** (Agent tool). The spawning prompt is the item name only —
   no characterization of the work. The agent reads the artifact and the tree itself;
   that self-read is the structural replacement for prompt-authorship bias, and the agent
   reports any characterization it does receive as a finding.
3. **Receive the report:** findings as round-ready rows, per-SPEC verdicts, and the
   `checked:` scope line.
4. **Write the outcome** (below). The agent never writes; rounds and the stamp are this
   session's only writes.

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
