---
name: drift-gate
description: Gate stage of the delivery workflow (docs/workflow/README.md) — fresh-context adversarial check of a DRAFT code plan against its frozen EARS spec. Stamps the plan GATED or returns findings to stage 3. Use when a plan draft is complete and the user says "run the gate", "gate the plan", or invokes /drift-gate.
---

# Plan/spec drift gate

Input: `docs/workflow/<item>/spec.md` with `Status: AGREED` (frozen) and
`docs/workflow/<item>/plan.md` with `Status: DRAFT`.
Output: either the plan stamped `Status: GATED <date>`, or a findings round appended to
`docs/workflow/<item>/gate-findings.md` and the plan back to stage 3 (spec unchanged,
per the pipeline). The round log — not chat history or session memory — is what carries
findings between sessions; workflow state must always be derivable from the docs alone.

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

- **Any finding → no stamp.** Append a round to `docs/workflow/<item>/gate-findings.md`
  (create the file on the first-ever finding; template below), findings SPEC-cited, one
  line each. Plan returns to stage 3; spec unchanged. Re-gate is a full re-run, fresh
  session.
- **Clean → stamp.** Set the plan header to `Status: GATED <date>` and append a short
  gate record under it: date, "gated fresh-context", and the residual-named SPECs (so
  implementation and review inherit the accepted residuals without re-deriving them).
  If `gate-findings.md` exists, close it with a final `## Round N — <date>` reading
  `Clean — stamped.` so the round log agrees with the plan header.
  The stamp is what `.claude/skills/implementation/` checks at entry.

## Round log (`gate-findings.md`)

Gate sessions append rounds; the stage-3 revision session fills dispositions. The round
number is the last round in the file plus one (1 for a new file). The gate-stage state
decode table lives in `docs/workflow/README.md` ("State decode tables"), next to the
files it decodes.

Template:

```markdown
# <item> gate findings

> Round log for the drift gate (see `.claude/skills/drift-gate/`). Gate sessions append
> rounds; the stage-3 revision session fills dispositions. Plan status lives in plan.md.

## Round 1 — <date>

<n> findings, no stamp.

| # | SPEC | Finding | Disposition (stage 3) |
|---|------|---------|-----------------------|
| 1 | <id> | <one line> | |
```

**Round-3 rule:** a third round with any open finding stops the loop. Report to the
owner, who decides per finding: accept it as a named residual, overrule it, or change
the spec (stage 2, explicit decision). Record each decision in that finding's
disposition cell; the next gate run honors recorded owner decisions rather than
re-flagging them.

## Never

- Never gate a plan this session helped write.
- Never edit plan or spec from the gate session — the round log and the stamp are the
  only files a gate session writes.
- Never stamp with an open finding, however minor — minor goes back to stage 3 cheaply.
- Never hand findings off through chat or memory alone — if it isn't in the round log,
  the next session doesn't know it.
