---
name: spec-authoring
description: Stage 2 of the delivery workflow (docs/workflow/README.md). Turn an AGREED Requirements section into the EARS Spec section of docs/workflow/<item>.md — the frozen contract the drift gate and review anchor against. Use when an item's requirements are agreed and the user says "start spec", "spec stage", or invokes /spec-authoring.
---

# Spec authoring (EARS)

Input: the contract file `docs/workflow/<item>.md` with `## Requirements` at
`Status: AGREED`. Refuse to start from a DRAFT — requirements change through their own
stage, not here.
Output: the `## Spec` section (contract file), agreed with the owner, then **frozen**
(`Status: FROZEN <date>`, header `Status:` advanced). It changes only by explicit human
decision (`docs/workflow/README.md`). This stage produces **behavior contracts, not
design** — no file paths, no module names, no implementation choices (that is the plan
stage).

## Process

1. **Read the agreed requirements.** Every non-deferred `<item>-REQ-n` must be covered;
   nothing outside them may be specified. Scope grows only by going back to stage 1.
2. **Write EARS rows** (`<item>-SPEC-n`, allocated once, never renumbered), one behavior
   per row, each independently verifiable. One requirement usually yields several rows:
   the normal path, the unwanted-behavior paths, any state-dependent behavior. Group rows
   by requirement (or name the REQ in Notes) so coverage closes both ways: every
   non-deferred REQ → ≥1 SPEC, every SPEC → exactly one REQ.
3. **Fill the check column.** Every row carries exactly one mechanism:
   - `test:` — a pinned test id. The name is *planned* here, filled in at implementation;
     the impl gate checks the map is complete. Behavioral detail lives in the named test,
     which CI runs — prose stays only for what a test cannot carry (rationale, scope
     exclusions, human-gate markers).
   - `cmd:` — a runnable impl-gate command with its expected output, for process
     properties no test can pin (baseline invariants, artifact checks).
   - `gate:` — a human judgment or hand-run assertion at the impl gate, **with its
     observation recorded in `## Delivery`**. Out-of-repo and click-ops state (branch
     protection, live API config) always gets `gate:`, never a pretend `test:`.
4. **Scope the freeze.** Requirements rows marked `DEFERRED → <item>` get no SPEC rows;
   the frozen set covers non-deferred rows only, and the drift gate checks the exclusion
   held. Deferred IDs re-home when the successor item is synthesized.
5. **Carry gates forward.** A `⚠ human-gate` on a requirement marks every SPEC row
   derived from it. PHI/authz/sanitization behavior inherits the `docs/landmines.md` §3
   negative-test rule — say so in Notes, don't restate the rule.
6. **Ask the owner the open questions** (answers become `spec`-tagged entries in the
   item's `## Decisions` register, in the plan file `docs/workflow/plans/<item>.md`),
   and stop at agreement. Owner marks FROZEN; land both files via `noncode-merge`
   (README landing rule). The frozen
   contract is the EARS rows **and their pinned checks** — a pinned row or pinned test
   changes only by owner decision, and the impl gate diffs for it
   (`.claude/skills/impl-gate/`).

## EARS patterns

Use the smallest pattern that fits; name the system element precisely.

- **Ubiquitous:** The `<element>` shall `<response>`.
- **Event-driven:** When `<trigger>`, the `<element>` shall `<response>`.
- **State-driven:** While `<state>`, the `<element>` shall `<response>`.
- **Unwanted behavior:** If `<condition>`, then the `<element>` shall `<response>`.
- **Optional feature:** Where `<feature>`, the `<element>` shall `<response>`.

Configured values are named as configuration (`a configured <thing>`), not as numbers —
numbers are plan or implementation detail unless the requirement itself fixed one (then
record the fixing decision in the register).

## Template (the section)

```markdown
## Spec

Status: DRAFT | AGREED, FROZEN <date>

Check column: `test:` pinned test id (filled at impl, changes only by owner decision) ·
`cmd:` impl-gate runnable check · `gate:` human judgment at impl gate, observation
recorded in Delivery.

| ID | EARS | Check | ⚠ |
|---|---|---|---|
| <item>-SPEC-1 | <statement> | test: <planned id> | ⚠ |

Exclusions: <what the frozen set deliberately does not cover, one clause each, cited>.
```
