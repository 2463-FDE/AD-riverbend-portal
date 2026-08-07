---
name: drift-gate
description: Gate stage of the delivery workflow (docs/workflow/README.md) — fresh-context adversarial check of a DRAFT code plan against its frozen EARS spec. Stamps the plan GATED or returns findings to stage 3. Use when a plan draft is complete and the user says "run the gate", "gate the plan", or invokes /drift-gate.
---

# Plan/spec drift gate

Input: `docs/workflow/<item>/spec.md` with `Status: AGREED` (frozen) and
`docs/workflow/<item>/plan.md` with `Status: DRAFT`.
Output: either the plan stamped `Status: GATED <date>`, or a findings list and the plan
back to stage 3 (spec unchanged, per the pipeline).

The mechanism is codified from the e1 prototype run (2026-08-06): a fresh-context read of
the plan against the spec caught real gaps the authoring session could not see. The fresh
context is the mechanism, not a nicety.

## Two hard rules

1. **The gate never runs in the session that authored or amended the plan.** If this
   session wrote any part of the plan text, stop and tell the owner to invoke the gate in
   a new session. Authoring bias is exactly what the gate exists to remove.
2. **The gate session never edits the plan.** It reports findings; revisions happen in
   stage 3 (`.claude/skills/plan-authoring/`), and the revised plan gets a full fresh
   gate run against its final text. No stamping a plan amended mid-gate — the e1 lesson:
   analyze-and-amend in one motion leaves the final text never checked as a whole.

## Process

1. **Read the spec first, alone.** Before opening the plan, list every SPEC id and note
   what you would expect a plan to do about each. This ordering is deliberate: form
   expectations from the contract, then test the plan against them — not the reverse.
2. **Read the requirements §6 (out-of-scope)** — the plan must carry it verbatim.
3. **Read the plan and close the scope map both ways:** every SPEC id appears in the map;
   every planned change traces to a SPEC id or is named registry upkeep. An unmapped SPEC
   or an untraceable change is a finding.
4. **Spot-verify plan facts in-repo.** Sample the file paths, symbols, ports, and config
   values the plan asserts — read them from the working tree this session. Any wrong fact
   is a finding (the plan-authoring rule says verify-before-writing; the gate checks it
   held).
5. **Run the three checks** from `.claude/skills/plan-authoring/` (self-consistency, gate
   interaction, residual honesty) against the final text. They are authoring checks; the
   gate re-runs them cold.
6. **Per-SPEC verdict**, every id, one of: **satisfied** / **residual-named** (partial,
   with the residual written in Landmines/risk) / **FINDING**. A partial whose residual
   is not written down is a finding, not a residual.
7. **Check the guard sections:** Verification is numbered, SPEC-cited, and includes
   negative (break-then-revert) checks; Landmines names the `docs/landmines.md` §1 zones
   touched or "none touched", with required human approvals recorded.

## Outcome

- **Any finding → no stamp.** Report the findings list (SPEC-cited, one line each). Plan
  returns to stage 3; spec unchanged. Re-gate is a full re-run, fresh session.
- **Clean → stamp.** Set the plan header to `Status: GATED <date>` and append a short
  gate record under it: date, "gated fresh-context", and the residual-named SPECs (so
  implementation and review inherit the accepted residuals without re-deriving them).
  The stamp is what `.claude/skills/implementation/` checks at entry.

## Never

- Never gate a plan this session helped write.
- Never edit plan or spec from the gate session.
- Never stamp with an open finding, however minor — minor goes back to stage 3 cheaply.
