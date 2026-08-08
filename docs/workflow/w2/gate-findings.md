# w2 gate findings

> Round log for the drift gate (see `.claude/skills/drift-gate/`). Gate sessions append
> rounds; the stage-3 revision session fills dispositions. Plan status lives in plan.md.

## Round 1 — 2026-08-08

4 findings, no stamp.

Scope map closes both ways (all of W2-SPEC-1..32 mapped; every planned change traces to a
SPEC or to named registry upkeep). Every sampled plan fact verified in the working tree
this session. Per-SPEC verdict: no SPEC is unsatisfied — SPEC-3/6, SPEC-20 and the
REPORT.md staleness are residual-named. All four findings are in §9 registry upkeep and
§2 DDL, not in spec coverage.

| # | SPEC | Finding | Disposition (stage 3) |
|---|------|---------|-----------------------|
| 1 | upkeep (SPEC-22) | §9's stale-`match_key: none` sweep names 4 sites but misses 4 more the change falsifies: `services/intake-service/app.py:93` ("D5 (flagged, not fixed): no MPI / match-key lookup" — the comment sits directly above the new hook), `ARCHITECTURE.md:103`, `docs/runbook.md:99`, `docs/onboarding-seam-map.md:25` | **Fixed.** §9's sweep bullet is now the output of a repo-wide grep run this session, not a hand list: all four named sites added with per-site instructions (`app.py:93-95` amended in the same edit that adds the hook, since the comment sits directly above it; `ARCHITECTURE.md:103` first clause only — "one person can become several charts" stays true; `runbook.md:99` repointed at the review queue and retro pass; seam-map `:25` narrows the "no MPI" label but stays a wall). The sweep also surfaced a fifth, `eval/rag/data.py:310`, folded into the frozen-baseline residual with finding 4. A **deliberately-not-amended** list with per-site reasons now covers the remaining hits (ADR 0005 context, `specs-deprecated/w2.md`, the two pinning tests, the `eval/rag/` trio). Verification step 11 re-runs the grep and requires every hit to land on one list or the other |
| 2 | upkeep (SPEC-20, 21) | `docs/landmines.md:123` (§3 deliberate-coverage-gap list) keeps asserting "no input-normalization or **duplicate-patient tests** (RIV-201)" after the plan adds three duplicate-patient suites; §3 is the tracked source of truth for that list and a moved gap is itself a reportable event, so amending the clause (input-normalization half stays) belongs in §9 | **Fixed.** New §9 bullet amends `docs/landmines.md:123`: duplicate-patient half recorded as closed by W2 (naming the three suites), input-normalization half stays open — W2 adds no intake input canonicalization, and the matcher's `normalize_ssn`/`normalize_name` are matcher-side only. The bullet states explicitly that a moved gap is a reportable event and routes it to three places (§9, PR body, CLAUDE.md §6 baseline note) rather than letting it disappear into a new pass count. Verification step 11 checks both halves of the amended clause |
| 3 | upkeep (SPEC-24, 25) | §2 prescribes "both `db/schema.sql` and the new migration get the same DDL" over a plain `CREATE TABLE` snippet, but all 12 tables in `db/schema.sql` use `CREATE TABLE IF NOT EXISTS` while migrations (e.g. `008_roi_requests.sql:9`) use the plain form. Migrations is an approval-gated zone — say which form lands in which file rather than leaving the implementer to pick | **Fixed.** §2 now prescribes the split explicitly, with the convention verified in-tree this session (schema.sql `:15`–`:161` all `IF NOT EXISTS`; `001_init.sql:4` and `008_roi_requests.sql:9` plain): the migration takes the snippet verbatim behind the `003+` header convention, `db/schema.sql` takes the same two blocks with `IF NOT EXISTS` substituted, under a section comment matching `schema.sql:140-144` and aligned to the file's gutter. "Nothing else differs between the two copies; the implementer picks nothing." Files-touched rows updated; step 11 diffs the two |
| 4 | residual (SPEC-9, 10) | The accepted "a tracked artifact goes deliberately stale" residual (`eval/rag/REPORT.md` §1 / `report.py:143` keep stating `match_key: none`) is recorded in the plan only. Per the registry contract (`docs/todo.md:8-11`, CLAUDE.md §8) an unscheduled loose end owned by nobody belongs in `docs/todo.md`; §9 adds no entry, so after merge the falsehood is tracked in a workflow artifact and nowhere a doc-drift sweep would look | **Fixed.** §9 gains a `docs/todo.md` entry at the next free id (TODO-57 as of this plan, with a re-check instruction since ids are allocated once and never renumbered), naming all three frozen sites — `REPORT.md:19`, `report.py:143`, and `data.py:310` (found by the finding-1 sweep) — plus the reason they stay and the condition that clears them, in the file's pipe-separated line format with `tags`/`src`. The Landmines residual now cross-references TODO-57 instead of standing alone; step 11 checks the entry exists |

## Round 2 — 2026-08-08

Clean — stamped.

Round 1's four dispositions verified independently this session, not taken on the
disposition cells' word: the §9 sweep re-run (`grep -rn "match_key: none\|no MPI\|no match
key\|match-key lookup"`, workflow excluded) returns 17 hits and every one lands on §9's
amend list or its deliberately-not-amended list; `docs/landmines.md:123` amendment splits
the clause correctly; `db/schema.sql` is 12/12 `IF NOT EXISTS` against plain
`CREATE TABLE` in `001_init.sql:4` / `008_roi_requests.sql:9`, matching §2's prescribed
split; `TODO-56` is the highest allocated id, so TODO-57 is free.

Scope map closes both ways (W2-SPEC-1..32 all mapped; every planned change traces to a
SPEC or to named §9 upkeep). Requirements §6 carried verbatim. Sampled plan facts all
verified in the working tree — matcher symbol lines in `eval/rag/data.py`, the D5 seam at
`intake-service/app.py:93-95`, `_post_checked` at `gateway/app.py:1222+`,
`EXPECTED_ROUTE_CAPABILITIES` at `tests/test_gateway_authz.py:105-123`, capability grants
in `config/roles.yaml`/`authz.py`, and the doc anchors (`landmines.md:63,123`,
`ARCHITECTURE.md:103`, `runbook.md:99`, `onboarding-seam-map.md:25`, `debt-log.md:267`,
`schema.sql:44`). Two load-bearing assertions re-derived rather than sampled: nothing
outside `intake-service` reads `intake.yaml` (`run.py` uses the literal
`MATCH_KEYS = ("none","name_dob","ssn")`, `report.py:143` is hardcoded prose), so the
`match_key` flip moves no gate; and `interop-service` creates no patient rows, so the
`POST /intake` hook is the whole chart-create surface for SPEC-22.

Per-SPEC verdict: none unsatisfied. Residual-named — SPEC-3/6, SPEC-6 failure path,
SPEC-20, and the frozen `eval/rag/` artifacts (SPEC-9/10, TODO-58 — allocated as
TODO-57 above, renumbered at the 2026-08-08 landing per finding 4's re-check
instruction; the doc-drift sweep took TODO-57 in the interim) — all written into
Landmines/risk. One candidate finding was raised and dropped: the three new env tunables
(`RELEVANT_RECORDS_MAX_ITEMS`/`_MAX_SCAN`, `RAG_MAX_CORPUS_DOCS`) are absent from
`.env.example`, but records-service's own `DEFAULT_PAGE_LIMIT`/`MAX_PAGE_LIMIT` are absent
too, so the plan matches the closest in-repo precedent rather than breaking a convention.
