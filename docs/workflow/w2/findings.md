# w2 findings

> Round log for this item's three gated stages: the drift gate
> (`.claude/skills/drift-gate/`), the impl gate (`.claude/skills/impl-gate/`), and the
> `@codex-review` loop (owned by `.claude/skills/implementation/`). Each stage appends
> rounds under its own heading, created on that stage's first finding; the next-stage
> session fills the dispositions. Findings only — plan maturity lives in `plan.md`,
> delivery status in `pr-body.md`.

## Gate

### Round 1 — 2026-08-08

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

### Round 2 — 2026-08-08

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

## Review

> PR #63, `@codex-review` by JesterCharles.

### Round 1 — 2026-08-08

Verdict `needs-attention`. 2 findings, both `[medium]`. All 14 CI checks green.

| # | SPEC | Finding | Disposition (A/B/C/E) |
|---|------|---------|-----------------------|
| 1 | W2-SPEC-26/27 | `services/intake-service/app.py:246-259` — disposition is read-check-write: two concurrent reviewers can both observe `status == "pending"`, both commit, and the later write silently overwrites the earlier `disposition`/`decided_by`. Loses the audit trail of a human duplicate-patient judgment. | **r1: A** — accepted, fixed on branch (`9459fee`). Single conditional `UPDATE … WHERE status = 'pending' RETURNING`, 409 on no match. No new state, so no re-gate. Regression: `test_review_queue.py::test_a_concurrent_disposition_cannot_overwrite_the_first_one`. |
| 2 | W2-SPEC-1 | `services/records-service/app.py:202-248` — encounters are scanned in `Encounter.id` order and capped at `relevant_records_max_scan` **before** salience ranking is applied. On a chart with more than `max_scan` records, older low-value rows can consume the budget so a newer allergy/medication encounter is never read, and the clinician's first-attention panel omits exactly what it exists to surface. | **r1: A** — accepted, fixed on branch (`2258a18`). Owner-routed 2026-08-08 as a branch fix, not a stage-3 return. Regression: `test_records_relevant.py::test_the_scan_bound_cannot_drop_a_higher_ranked_record`. |

#### Verification notes (fix-session step 2, evidence)

- **#1 is a defect in the code as pushed.** The 409 path already verified in the
  live-stack run (`pr-body.md` step 9) is the *sequential* re-disposition case; it does
  not close the concurrent one. The plan (§5, `plan.md:281-286`) specifies
  "404 on unknown id, 409 if already dispositioned" without naming a mechanism, so the
  non-atomic read-check-write is an implementation choice, not the plan's design.
  No new state (counter/TTL/lock/breaker/budget/cache) is needed to close it: a single
  conditional `UPDATE ... WHERE id = :pair_id AND status = 'pending' RETURNING *` with
  409 on zero rows updated.
- **#2 is latent, not reproducible at seed scale.** `RELEVANT_RECORDS_MAX_SCAN`
  defaults to 500 (`services/records-service/config.py:18`) and no seeded chart comes
  close, which is why every verification run in `pr-body.md` — including the live-stack
  pass where 1330's penicillin allergy correctly ranked first — passed. The defect
  needs a chart larger than the scan bound. The implementation is a faithful reading of
  the plan (`plan.md:328-332`), whose order of operations ("rank … return top
  `max_items` … scanning at most `max_scan`") does not settle whether the bound applies
  before or after ranking. That ambiguity is the root cause.

#### Routing (fix-session step 4)

Both findings cluster to one root cause each; neither shares one. Neither fix introduces
or alters state — no counter, TTL, lock, breaker, budget or cache is added, and
`relevant_records_max_scan` keeps its meaning, its default and its N+1 ceiling — so
neither triggers the design gate, and both were patched on the branch.

**#2 was owner-routed on 2026-08-08**, between the two candidate branch fixes and a
stage-3 return. The chosen fix is the ranking reorder; it landed **in Python over the
already-loaded encounter list** rather than as the SQL `ORDER BY` first sketched. Same
effect, strictly better: the encounter rows are loaded in full before the bound is spent
either way (`max_scan` bounds records scanned and the N+1 query count, never the
encounter read), so the reorder costs no additional query — and it keeps
`_has_clinical_content` in the loop, so the `none known` sentinel is still not an
allergy. The SQL variant would have had to re-express that sentinel set in a CASE or let
sentinel encounters eat scan budget from the allergy band. Codex's own suggestion —
ranking in bounded SQL queries — was **not** taken: it would reopen the deliberate N+1
and D8 (`plan.md:328-329`, "the N+1 stays — D8 is deliberate"), which is a landmine
decision, not a review fix.

#### Re-verification (fix-session step 5)

- `make test-docker` → **923 passed, 1 xfailed, 5 deselected**. Baseline was 921/1/5;
  **+2 passed** (the two regressions above), **xfail and deselected unmoved**.
  `CLAUDE.md` §6 baseline updated to 923.
- Negatives, break-then-revert: dropping the `status = 'pending'` predicate from the
  UPDATE → **2 red** (the new concurrency test *and* the pre-existing
  `test_already_dispositioned_pair_is_409`, which confirms the conditional write is now
  the sole 409 mechanism rather than a second belt) → revert → green. Re-keying the
  encounter sort to `id` → the new ranking regression red → revert → green.
- The intake stub session was extended to evaluate a conditional UPDATE against the row
  as it stands at write time, which is what makes the race test meaningful rather than a
  restatement of the handler.

### Round 2 — 2026-08-08

Verdict `approve`. **0 material findings** — "No ship-blocking defect found in the
branch diff." All 14 CI checks green at the reviewed head `2258a18`. No findings table:
the round is dry, and the two "top things to improve" items are not defects in the diff.

| # | SPEC | Item | Disposition (A/B/C/E) |
|---|------|------|-----------------------|
| 1 | — | "The reviewer could not actually run the test suite (pytest wasn't installed in the review environment) … run the full slice and post the passing output before merging." | **r2: E** — harness limitation, not a code defect. Answered with evidence rather than a change: see below. |
| 2 | — | "Make sure CI is configured to run these new test files automatically." | **r2: E** — already true before the round, and provably so. `.github/workflows/ci.yml:91` runs `pytest -m "not integration" -q` from the repo root, which collects the whole `tests/` tree; no per-file registration exists or is possible to omit. The `tests` job on this PR's own head reported **923 passed, 5 deselected, 1 xfailed in 42.22s** — that count *is* the new files running. |

#### What the dry round actually checked (evidence, not absence of evidence)

The round names its coverage: gateway authz/proxy paths, duplicate-queue write semantics,
the matching/retroactive pass, the schema changes, and frontend API forwarding. Two of
those matter specifically because of round 1:

- **Queue write semantics were re-inspected after the r1 #1 fix** and drew no finding —
  the conditional `UPDATE … WHERE status = 'pending' RETURNING` is the surface the fix
  wrote, so a clean read there is the B-round check, not a repeat of r1's read.
- **The records path was re-inspected after the r1 #2 reorder** with the deliberate N+1
  and D8 left in place, and the round did not re-raise the bounded-SQL suggestion it made
  in r1 — the landmine rationale held on second look.

#### Evidence posted for item 1

- Full suite, `make test-docker` at head `2258a18`: **923 passed, 5 deselected, 1 xfailed
  in 33.11s** — the `CLAUDE.md` §6 baseline exactly, xfail and deselected unmoved.
- Named slice (`test_gateway_authz` · `test_gateway_review_queue` · `test_matching_parity`
  · `test_records_relevant` · `test_retro_match` · `test_review_queue`): **106 passed**.
- CI `tests` job on the same head (run 31281202640): **923 passed, 5 deselected, 1
  xfailed** — the suite had in fact already run green in CI before the round asked.

#### Routing

Nothing to route: no code change, no re-gate, no new test. Loop closes at 2 rounds
(2 A-fixes in r1, 1 dry round) — merge-ready.
