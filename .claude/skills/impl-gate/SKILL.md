---
name: impl-gate
description: Pre-push gate of the delivery workflow (docs/workflow/README.md) — fresh-context adversarial check of an implementation branch against its GATED plan and frozen EARS spec, before push and codex review. Stamps the plan IMPLEMENTED or returns findings to stage 4. Use when implementation is complete and the user says "run the impl gate", "pre-push review", or invokes /impl-gate.
---

# Implementation gate (pre-push)

Input: `docs/workflow/<item>/spec.md` with `Status: AGREED` (frozen),
`docs/workflow/<item>/plan.md` with `Status: GATED`, and a completed implementation
branch (unpushed or pushed but pre-review).
Output: either the plan stamped `Status: IMPLEMENTED <date>`, or a findings round
appended to `docs/workflow/<item>/impl-findings.md` and the branch back to stage 4
(spec and plan unchanged). The round log — not chat history or session memory — carries
findings between sessions; workflow state must always be derivable from the docs alone.

This gate covers what codex review cannot: codex sees the diff but never the spec, the
plan, or the repo's landmine rules. The impl gate anchors the diff to those artifacts.
The fresh context is the mechanism, not a nicety — the authoring session cannot see its
own drift (same lesson as `.claude/skills/drift-gate/`).

## Two hard rules

1. **The gate never runs in the session that wrote or amended the implementation.** If
   this session wrote any of the branch's code, stop and tell the owner to invoke the
   gate in a new session.
2. **The gate session never edits code, plan, or spec.** It reports findings; fixes
   happen in stage 4 (`.claude/skills/implementation/`), and the fixed branch gets a
   full fresh gate run. The round log and the stamp are the only files a gate session
   writes.

## Process

1. **Read the spec first, alone.** List every SPEC id and note what implemented behaviour
   you would expect for each. Then read the plan's scope map and Landmines section.
   Expectations come from the contract, then the diff is tested against them — not the
   reverse.
2. **Close the diff against the scope map both ways.** `git diff main...HEAD --stat`,
   then the full diff. Every changed file traces to a scope-map slice; every planned
   slice appears in the diff or the PR-body draft (`docs/workflow/<item>/pr-body.md`,
   committed on the branch — implementation skill step 6) records why not. A missing
   pr-body.md is itself a finding. An untraceable file is a finding — unplanned scope,
   however helpful-looking, goes back to stage 4.
3. **Planted-defect check.** For any diff hunk near known defects (`docs/debt-log.md`,
   `docs/landmines.md` §1, the phi-logging register), confirm the change does not
   silently repair or disturb a teaching artifact. A "helpful" fix of a planted defect
   is a finding, always.
4. **Traceability.** Every SHALL clause in the plan's scope map has a test naming its
   SPEC id, or the plan records why not. Run the branch's own tests if cheap; otherwise
   verify they exist and assert the behaviour, not just execution.
5. **Baseline.** Confirm the full-suite result against the pinned baseline in
   `CLAUDE.md` §6: passed grows by exactly the tests this branch adds; xfailed and
   deselected must not move. Prefer re-running (`make test-docker` or the 3.12 venv);
   accept the implementation session's recorded counts only if re-running is impossible,
   and say so in the record.
6. **Idiom and rule sweep over the diff only:**
   - new gateway routes using `_post`/`_get` instead of `_post_checked` (CLAUDE.md §4)
   - exception logging that includes `str(e)` or PHI-bearing fields on touched paths
     (`docs/phi-logging-policy.md`)
   - `Co-Authored-By` trailers in the branch's commits (`CONTRIBUTING.md:53`)
   - landmine §1 zones touched by the diff without the human approval recorded in the
     plan's Landmines section
7. **Verification evidence.** The plan's Verification section was run end-to-end,
   including negative (break-then-revert) checks — evidence in the implementation
   session's notes or reproducible now. The PR-body draft
   (`docs/workflow/<item>/pr-body.md`) discloses which slices ran test-first and which
   didn't, records every plan deviation with rationale, and copies the plan's accepted
   residuals.

## Outcome

- **Any finding → no stamp.** Append a round to `docs/workflow/<item>/impl-findings.md`
  (create on first-ever finding; template below), findings SPEC-cited where applicable,
  one line each. Branch returns to stage 4; plan and spec unchanged. Re-gate is a full
  re-run, fresh session.
- **Clean → stamp.** Set the plan header to `Status: IMPLEMENTED <date>` and append a
  short impl-gate record under the gate record: date, "impl-gated fresh-context", branch
  name and HEAD commit, baseline counts observed, and any residuals accepted at this
  gate. If `impl-findings.md` exists, close it with a final `## Round N — <date>`
  reading `Clean — stamped.` The stamp means push-ready; **push itself stays
  human-gated** per `.claude/skills/implementation/`.

## Round log (`impl-findings.md`)

Gate sessions append rounds; the stage-4 fix session fills dispositions. Round number is
the last in the file plus one (1 for a new file). State decodes from the docs alone:

| Observation | State |
|---|---|
| plan `GATED`, no branch diff | implementation not started |
| plan `GATED`, branch complete, no `impl-findings.md` | impl gate not yet run |
| latest round has findings with empty dispositions | stage-4 fix pending |
| dispositions filled, plan still `GATED` | re-gate pending |
| plan `IMPLEMENTED` | push-ready; round log closed |

Template:

```markdown
# <item> impl-gate findings

> Round log for the implementation gate (see `.claude/skills/impl-gate/`). Gate sessions
> append rounds; the stage-4 fix session fills dispositions. Plan status lives in plan.md.

## Round 1 — <date>

<n> findings, no stamp.

| # | SPEC | Finding | Disposition (stage 4) |
|---|------|---------|-----------------------|
| 1 | <id or —> | <one line> | |
```

**Round-3 rule:** a third round with any open finding stops the loop. Report to the
owner, who decides per finding: accept as a named residual, overrule it, or send the
item back to stage 3 (plan revision, re-gated). Record each decision in the disposition
cell; the next gate run honors recorded owner decisions rather than re-flagging them.

## Never

- Never gate a branch this session helped write.
- Never edit code, plan, or spec from the gate session — round log and stamp only.
- Never stamp with an open finding, however minor — minor goes back to stage 4 cheaply.
- Never fix a finding in-line "while you're there" — analyze-and-amend in one motion
  leaves the final state never checked as a whole.
- Never hand findings off through chat or memory alone — if it isn't in the round log,
  the next session doesn't know it.
