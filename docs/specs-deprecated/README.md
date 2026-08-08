# DEPRECATED — historical record only

Deprecated 2026-08-06. These are the weekly engagement specs written under the previous
process. They remain the graded record for weeks shipped before the change and existing
documents (ADRs, debt log, todo register) still cite them by path — **do not edit, delete,
or backfill them.**

New work follows the staged workflow in `docs/workflow/README.md`: requirements and specs
live in `docs/workflow/wN/`, with specs written in EARS form. Nothing new lands in this
folder.

## Two references in these files no longer resolve

Added 2026-08-08 (`docs/todo.md` TODO-53). The do-not-edit rule wins, so the corrections
live here rather than in the files:

- **"Status: derived by `/dashboard` from live repo state" (line 6 of every `wN.md`).**
  Dead tooling (`CLAUDE.md` §11). Status for these weeks is derived nowhere — read it from
  git history and the PRs that closed them. Same for `_template.md:5`, which justifies the
  requirement-ID scheme by `address-review`'s design gate; the live successor is EARS
  `WN-SPEC-n` IDs checked by `.claude/skills/drift-gate/`.
- **`CLAUDE.md §n` citations point at the pre-2026-08-06 file** — old §5, §6, §7 and §9 are
  now `docs/landmines.md` §3, §1, §2 and `docs/debt-log.md` (`git show c04806d:CLAUDE.md`).
