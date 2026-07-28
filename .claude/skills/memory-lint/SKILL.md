---
name: memory-lint
description: Health-check the project's Claude Code memory directory - dangling index pointers, orphan pages, broken wikilinks, dead source citations, stale claims and cross-page contradictions. Use when the user asks to lint/audit/prune memory, when a memory claim looks wrong, or at a week boundary after PRs merge.
---

# Lint the memory directory

Memory is a wiki: `MEMORY.md` is the index, `memory/*.md` are the pages,
`session-handoffs.md` is the append-only log. The failure mode is not size — it is
**a page that quietly stops being true**. This repo has already paid for that class
once: two auto-loaded files stated one rule, only one was maintained, and the stale
one won a review round (memory `duplicated-instructions-let-the-stale-one-win`).
Lint is the control for that class, so run it on the schedule below rather than
waiting to be surprised.

**Run it:** after a PR merges (statuses in `engagement-state` / `open-followups` /
`shipped-prs` all move at once), at a curriculum-week boundary, when a recalled
memory contradicts what the code says, and before trusting an old page in a
decision. Not every session — nothing here changes hourly.

## Phase 1 — mechanical

One call. It takes no arguments in normal use (it derives the memory dir from
`CLAUDE_PROJECT_DIR`):

```bash
bash .claude/skills/memory-lint/lint.sh
```

## Phase 2 — triage

**Most output is not a bug.** Judge each class against this table before touching
anything; the script deliberately reports facts and leaves the verdict here.

| Class | Default verdict | Action |
|---|---|---|
| `dangling-pointer` | **always a bug** | Index cites a deleted page. Remove the line, or restore the page if the deletion was accidental. |
| `orphan-page` | **always a bug** | A page unreachable from the index is a page that will never be recalled. Add a pointer line. |
| `slug-mismatch` / `no-description` / `bad-type` | **bug** | `description:` is what recall matches on — a page without one is dead weight. Fix in place. |
| `no-frontmatter` | usually fine | Only hook-written logs are exempt, and they must be listed in `LOGS` in the script. Any other page: add frontmatter. |
| `unresolved: [[x]]` | depends | A link to an **unwritten memory** is a legitimate TODO marker — leave it. A link to a **skill, command or repo doc** (`[[address-review]]` is one) is the wrong link type: replace it with the real path, because it will never resolve. |
| `in-degree-0` | signal, not a bug | Reachable only via the index. Fine for standalone reference pages; a *lesson* nobody links to is one nobody applies — consider linking it from the page whose work it governs. |
| `dead-source` | **bug** | The page cites a repo path that no longer exists. Either the path moved (update it) or the claim is obsolete (rewrite or delete the page). |
| `no-sources` | tech debt, count only | See "gap 2" below. Do not bulk-backfill. |
| `age` | signal, not a bug | Old ≠ wrong. Use it to pick *which* pages phase 3 re-verifies. |
| co-mention cluster | phase-3 input | Pages that discuss the same PR/ADR/debt ID are where contradictions live. |
| index cost over ceiling | **act** | `MEMORY.md` is re-read every turn; it is the only figure that compounds. Over ~8000 B, shorten hooks or merge pages. |

## Phase 3 — the semantic pass (this is where the real findings are)

Mechanical checks cannot see a false claim. Verify by reading, but read **only**:

1. **One co-mention cluster at a time**, in the 3–5 page band the script prints.
   Read those pages' relevant lines and ask: do they state the same fact about
   that PR/ADR/debt ID? A cluster of 6+ pages is a hub (every page mentions the
   current PR) and is not worth reading as a set.
2. **The oldest 3–5 pages**, checked against the repo — not against your
   expectations. A claim of the form "`file:line` still does X" is the highest-risk
   shape there is; grep the file.
3. **Each index hook against its page body.** Backticked-token drift is already
   checked mechanically and finds little; the real drift is prose that describes
   items the body has since resolved. Compare meaning, not tokens.

Then reconcile:

- **One fact, one page.** If two pages state the same thing, the specific page keeps
  it and the general one links to it with `[[name]]`. Duplication is the defect —
  staleness is only how it surfaces.
- **Delete what is false.** A wrong memory is worse than a missing one. Delete the
  page *and* its index line together.
- **Rewrite, don't append.** Appending a correction to a page leaves both readings
  in context and the reader picks one.
- Report findings to the user before deleting or rewriting anything they wrote.
  Fixing a dangling pointer is bookkeeping; deleting a page they authored is not.

## Format migrations this lint supports

Both are opt-in and adopt **as pages are touched** — a bulk backfill of 24 pages
rewrites history the pages cannot actually source.

**Gap 2 — provenance.** Add a `sources:` list to frontmatter naming what the page
was derived from (repo paths, PR numbers, ADRs, a session transcript). Then
`dead-source` turns silent rot into a mechanical finding, and an old page becomes
re-verifiable instead of merely old.

```yaml
metadata:
  type: feedback
  sources:
    - adr/0010-eligibility-resilience.md
    - tests/test_eligibility_budget_alignment.py
    - "PR #11"          # MUST be quoted — see below
```

Two things the memory store does to frontmatter on save, both found the hard way:

- **It re-nests and re-indents.** A `sources:` written at column 0 comes back under
  `metadata:`, indented. Write it under `metadata:` to begin with, and never anchor a
  check on `^sources:`.
- **It parses YAML, so an unquoted `#` starts a comment.** `- PR #2, #4 r3, #11` was
  saved as `- PR`, silently discarding the rest of the line. **Quote any source
  containing `#`.**

**Gap 3 — a content-oriented index.** `MEMORY.md` is filename-oriented, so a
junk-drawer page like `riverbend-gotchas` hides its contents behind one hook. Group
the index under topic headings (engagement state · review lessons · tooling ·
reference) and let a hook name the *specific* traps it holds. Guard against the
index cost ceiling above while doing it — grouping should not add bulk.

## Token budget

Phase 1 is **~600 tokens of output, one tool call** (measured 2026-07-28: 42 lines /
2403 B against a 25-page, 144K memory dir). Phase 2 is reading. Phase 3 costs one
targeted read per cluster you choose to open — pick two or three, not all twelve.

Waste found while building this, kept so it is not re-invented:

| Anti-pattern | Cost | Cheap form |
|---|---|---|
| Bare `grep -qF "$tok"` on tokens that can start with `-` | a fabricated finding (`--build` parsed as an option — `grep` is ugrep here) | always `grep -qF -e "$tok"` |
| Clustering with the append-only log included | polluted 5 of 14 clusters; the log mentions every artifact | exclude `LOGS` from clustering |
| Reporting every co-mention cluster | 9-page hub rows nobody can act on | keep the 3–5 page band |
| Per-file `no-sources` findings | 24 lines saying the same thing | one count line |
| `cat` the pages to eyeball them | ~13k tokens for the whole dir | phase 1's graph checks, then read only what it flags |
| Anchoring the provenance check on `^sources:` | reported 26/27 pages missing a field 3 of them had | match `^ *sources:`; the store re-indents on save |
| A `sed` range to slice one frontmatter key | broke as soon as the key moved | `awk '/^---$/{n++; next} n==1'` for the whole block |

**Mutation-prove any check you add.** `dead-source` was verified by planting
`docs/does-not-exist.md` in a page's `sources:`, confirming the finding appeared, then
restoring and confirming it cleared. A check that has never fired is not wired
(memory `thresholds-must-be-reachable`).
