---
name: requirement-synthesis
description: Stage 1 of the delivery workflow (docs/workflow/README.md). Turn the engagement owner's raw ask for a week into an agreed requirements document at docs/workflow/wN/requirements.md. Use when the user provides a new weekly ask, says "start week N", or invokes /requirement-synthesis.
---

# Requirement synthesis

Input: a week number and the engagement owner's raw ask, given fresh in conversation.
Output: `docs/workflow/wN/requirements.md`, agreed with the owner. This stage produces
**requirements, not solutions** — no design, no file lists, no EARS phrasing (that is the
spec stage).

## Process

1. **Capture the ask verbatim.** Quote it exactly in §1. Never paraphrase the source.
2. **Interrogate the repo before the owner.** Check `docs/debt-log.md`, `docs/todo.md`,
   `docs/landmines.md` §1, and the relevant code for context the ask touches. Do not read
   `docs/specs-deprecated/` — it is archive, not input.
3. **Draft the document** per the template below. Requirement IDs are `WN-REQ-n`, allocated
   once, never renumbered.
4. **Ask the owner the open questions** (use structured multi-choice where possible), fold
   answers in, and move resolved items out of §5.
5. **Stop at agreement.** The owner marks it agreed; only then does the spec stage start.

## Requirement rules

- Each requirement is one testable statement of need — what must be true, not how.
- Name the actor (front desk, patient, clinician, system) and the observable outcome.
- Flag any requirement touching a `docs/landmines.md` §1 approval-gated zone (auth, PHI
  columns, ROI/disclosure, migrations, secrets) with `⚠ human-gate`.
- Out-of-scope is as load-bearing as in-scope: record what was considered and cut, with
  one clause of why.
- If the ask names something the client expects to *see*, a UI surface requirement must
  appear in the requirements table or its exclusion in out-of-scope (lesson of TODO-44).
- **This skill owns the document's section numbering, and the numbering is not stable.**
  The template below is a starting shape, not a contract: §5 is deleted at agreement when
  empty, and an item may add sections the template has no slot for (`e4` added a deferrals
  section and a decisions table, so out-of-scope is §7 there; `e2` numbers its requirements
  table §4). Downstream stages therefore locate sections by **heading**, never by number —
  and this document cites its own sections by the number they actually carry.

## Template

```markdown
# W<N> Requirements

> Status: DRAFT | AGREED <date>
> Source: engagement owner ask, <date>

## 1. Raw ask (verbatim)

> <quoted ask>

## 2. Context

<what in the repo this touches: debt IDs, TODOs, services, prior decisions. Cite paths.>

## 3. Requirements

| ID | Requirement | Notes |
|----|-------------|-------|
| W<N>-REQ-1 | <actor + observable outcome> | <constraints, ⚠ human-gate if applicable> |

## 4. Assumptions

<what is being taken as true without owner confirmation, each one challengeable>

## 5. Open questions

<numbered; delete section when empty at agreement — leave the gap, do NOT renumber what
follows: ids and cites already written against §6 would silently repoint>

## 6. Out of scope

<considered and cut, with why>
```

Add sections where an item needs them (a deferrals table, a decisions record) rather than
forcing content into a slot above. Numbering shifts when you do, which is expected — see
the numbering rule above.
