---
description: Pick a curriculum week/feature and start work with the verbatim client ask, debt mapping, and relevant landmines in hand
---

Help the user start work on one of the 10 Riverbend curriculum weeks. This command has two phases: pick, then brief. Do not create a branch, write code, or open a PR as part of this command — it only gathers context and hands off; branching/PR conventions belong to the `pr-open` skill, run separately once work actually starts.

## Phase 1 — which feature

Ask the user which week/feature to start (use AskUserQuestion or a plain numbered list — whichever fits). Show the short Feature name for each so it's not just "W1"/"W2":

| Wk | Feature |
|----|---------|
| 1 | PHI-safe LLM wrapper |
| 2 | RAG dedup/fragmentation eval |
| 3 | Eligibility agent (timeout/breaker) |
| 4 | Patient-view IDOR fix |
| 5 | Double-booking fix (spec only) |
| 6 | HL7 allergy/med mapping fix |
| 7 | Tracing + LLM guardrail |
| 8 | Safe-Harbor de-id + BAA memo |
| 9 | RBAC + ROI authorization |
| 10 | Append-only audit trail (capstone) |

Before presenting the list, do a quick fresh status check (same checks `/dashboard` uses — `gh pr list --state all`, `grep` the `D<n>` markers in `services/*/app.py`, `ls adr/`) so you can flag which weeks look already Done/In Progress, in case the user picks one that's already shipped.

## Phase 2 — brief the picked week

Once a week is picked, **read `docs/specs/w<N>.md`** — it is the source of truth for this week. Print, sourced from that doc:

1. **The verbatim client ask** — spec §1 (persona included). The actual words to work from, not a paraphrase.
2. **What it really is** — spec §2 (decoded defect + debt ID(s)/ticket(s)).
3. **Deliverable scope** — spec §3 (in/out of scope) + §4 (deliverables). Do not build past a spec-only week's line, and do not pull in an explicitly out-of-scope item — flag it for its owning week instead.
4. **Acceptance criteria** — spec §5 (the done-definition) + §6 landmines. This is what the work will be checked against.
5. **Current status** — from the Phase 1 check (or run `/dashboard`): Done/In Progress/Pending + which acceptance criteria are unmet. If already Done, say so and ask about re-open/extend rather than silently duplicating.

If a `w<N>.md` is somehow missing, say so and stop rather than reconstructing the ask from
memory — the spec docs are the only canonical copy of the client's words (all ten shipped in
PR #12). A paraphrased ask is how a decoded defect quietly turns back into the client's own
wrong mental model.

## After the brief

Ask the user how they want to proceed (e.g. explore the relevant code first, draft an ADR, or go straight to a branch) — don't assume next step. If they're ready to branch/PR, point them at the `pr-open` skill rather than doing it inline here.
