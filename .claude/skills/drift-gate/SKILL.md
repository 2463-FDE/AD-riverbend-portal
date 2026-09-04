---
name: drift-gate
description: Gate stage of the delivery workflow (docs/workflow/README.md) — fresh-context adversarial check of a DRAFT plan (docs/workflow/plans/<item>.md, or a ticket's docs/workflow/plans/<item>/<ticket>.md) against its frozen EARS spec (docs/workflow/<item>.md). Stamps the Plan section GATED or returns findings to stage 3. Use when a plan draft is complete and the user says "run the gate", "gate the plan", or invokes /drift-gate.
---

# Plan/spec drift gate

Input: the contract file `docs/workflow/<item>.md` with `## Spec` at `Status: FROZEN`
and the plan file `docs/workflow/plans/<item>.md` — for a ticketed item, the ticket file
`docs/workflow/plans/<item>/<ticket>.md` — with `## Plan` at `Status: DRAFT`.
Output: either the Plan section stamped `Status: GATED <date>` (contract-file header
`Status:` line advanced to match; ticketed item: the ticket's `Status:` line and its
`## Delivery` table row instead — README Tickets rule), or a `### Gate — round N, <date>`
round appended to that plan file's `## Findings` and the plan back to stage 3 (spec
unchanged, per the pipeline). A ticket gate checks the SPEC rows its `Scope:` line
names, plus that every frozen row is owned by some ticket. Rounds count per ticket file. The round log — not chat history or session memory — carries findings between
sessions; item state must always be derivable from the two files alone.

The mechanism is codified from the e1 prototype run (`docs/workflow/e1/`, 2026-08-06): a
fresh-context read of the plan against the spec caught real gaps the authoring session
could not see. The fresh context is the mechanism, not a nicety.

## Two hard rules

1. **The gate never runs in the session that authored or amended the plan.** If this
   session wrote any part of the Plan section, stop and tell the owner to invoke the gate
   in a new session.
2. **The gate session never edits the Requirements, Spec, or Plan content.** It writes
   exactly two things: Gate rounds in the plan file's `## Findings`, and — on a clean
   run — the Plan `Status:` stamp in the plan file plus the matching contract header
   line (single ticket) or the ticket file's `Status:` line and its ticket row
   (ticketed; README). Revisions happen in stage 3
   (`.claude/skills/plan-authoring/`), and the revised plan gets a full fresh gate run
   against its final text. No stamping a plan amended mid-gate — analyze-and-amend in one
   motion leaves the final text never checked as a whole (the e1 lesson). The spawned
   agent (below) adds partial enforcement: Edit/Write are absent, so it cannot edit or
   stamp through those tools — but its `Bash` can still write the tree, so shell
   read-only behavior is a behavioral rule in the agent's definition, not tool
   enforcement. The sentence stays as intent for what this session writes.

## Process

The adversarial read runs in a spawned agent with no Edit/Write tools —
`.claude/agents/drift-gate-agent.md` owns the check procedure (mechanical and judgment
halves), one place. This skill owns the ceremony: input-state check, spawn, rounds,
stamp.

1. **Verify input state:** `## Spec` at `FROZEN`, `## Plan` at `DRAFT`, and hard rule 1
   holds for this session.
2. **Spawn `drift-gate-agent`** (Agent tool). The spawning prompt is the item name (and
   ticket name, for a ticketed item) only — no characterization of the work. The agent reads both item files and the tree itself;
   that self-read is the structural replacement for prompt-authorship bias, and the agent
   reports any characterization it does receive as a finding.
3. **Receive the report:** findings as round-ready rows, per-SPEC verdicts, and the
   `checked:` scope line.
4. **Write the outcome** (below). The agent never writes; rounds and the stamp are this
   session's only writes.

## Outcome

- **Any finding → no stamp.** Append `### Gate — round N, <date>` to the plan file's
  `## Findings` (README owns the round format), findings SPEC-cited, one line each,
  disposition column empty for stage 3. Plan returns to stage 3; spec unchanged. Re-gate is a full re-run,
  fresh session. Every finding cell opens with the agent's **origin tag** — `new`
  (the anchored text is on a `Sites changed:` list of a disposition since the previous
  round, the round is round 1, or the tag cannot be settled from the record: a
  regression, or a finding that fails toward escalation), `pre-existing` (the record
  proves the text was in place when an earlier round read it and it was not raised:
  the gate widened), or `class-repeat` (below) — derived by the agent from two durable
  records, never from recall: the previous round's `checked:` line carries the
  **plan-text hash** it read (`git hash-object <plan file>`), and every disposition cell
  ends in a `Sites changed:` list (`.claude/skills/plan-authoring/`). A finding round,
  like a dry one, **closes with a `checked:` line** — the README's one defined field —
  which carries the plan-text hash this round read and the origin tally
  (`origin: N new · N pre-existing · N class-repeat`), so the owner reads convergence,
  not a raw count. The tag rides inside the cell and the tally inside the `checked:`
  line; the README round shape gains nothing new.
- **Repeat of a dispositioned class → the class goes back, not the instance.** When a
  finding is the same failure class as one dispositioned in an earlier round — **the same
  kind of wrong and the same kind of site, both** (the agent's definition, below; a match at
  the abstraction "a claim the tree falsifies" is not a class, and a finding on text the
  previous disposition wrote is `new`) — the round
  entry names the match, and stage 3 must close the class: the disposition cell
  **enumerates the sites the sweep checked — file and row, each with its outcome** — not
  just the cited site's fix; a scope phrase ("every clause of every row") is a declared
  sweep, not a run one, and the gate reads it as the class still open (one rule, stated
  in `.claude/skills/plan-authoring/`, which owns the sweep mechanics). A disposition
  that fixes only the instance leaves the class open for the next round to hunt one site
  at a time — the e6 rounds-2–4 lesson (`docs/workflow/e6.md` § Findings, "Gate — round 2"
  through "round 4").
- **Clean → stamp.** Set the Plan section to `Status: GATED <date>`, advance the
  contract-file header `Status:` line (ticket: its `Status:` line + table row), and close
  with a dry round: one `checked:` line naming the scope
  covered (ids checked, map state, ⚠ coverage) — a dry round's value is knowing what it
  checked. The stamped files ride the ticket's branch — `implementation` cuts it at the
  stamp and, after owner push approval, pushes the first commit (README landing rule,
  2026-08-28); no plan-only PR.

Round numbers count this stage's rounds only. **Round-3 rule:** a third round with any
open `new` or `class-repeat` finding stops the loop. Report to the owner, who decides per
finding: accept as a named residual, overrule, or change the spec (stage 2, explicit
decision). Each call is recorded in that finding's disposition cell; the next gate run
honors recorded owner decisions rather than re-flagging them. A third (or later) round
whose open findings are all `pre-existing` is an ordinary round — back to stage 3, no
owner adjudication — because the plan did not regress, the read widened (2026-08-27,
eligibility-assistant `corpus` / `llm-seam` gate rounds, ticket files deleted at delivery:
`git show a93f7c4^:docs/workflow/plans/eligibility-assistant/corpus.md`,
`git show 8fa44ee^:docs/workflow/plans/eligibility-assistant/llm-seam.md` — the rule as
first written fired on rounds where most open findings had been in the text since
round 1). The origin tag is the agent's derivation from the record, not stage 3's call —
and where the record cannot settle it, the tag is `new` and the rule fires: the stop
condition fails toward escalation, never toward silence.

## Never

- Never gate a plan this session helped write.
- Never edit Requirements/Spec/Plan content from the gate session — Gate rounds and the
  clean-run stamp are the only writes.
- Never stamp with an open finding, however minor — minor goes back to stage 3 cheaply.
- Never hand findings off through chat or memory alone — if it isn't in the round log,
  the next session doesn't know it.
