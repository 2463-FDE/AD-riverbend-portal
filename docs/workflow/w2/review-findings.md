# W2 codex review findings

> Round log for the @codex-review loop. Rounds appended as review returns; dispositions
> filled by the stage-4 fix session. Delivery status lives in pr-body.md.

## Round 1 — 2026-08-08

PR #63, verdict `needs-attention`. 2 findings, both `[medium]`. All 14 CI checks green.

| # | SPEC | Finding | Disposition (r1: A/B/C/E) |
|---|------|---------|---------------------------|
| 1 | W2-SPEC-26/27 | `services/intake-service/app.py:246-259` — disposition is read-check-write: two concurrent reviewers can both observe `status == "pending"`, both commit, and the later write silently overwrites the earlier `disposition`/`decided_by`. Loses the audit trail of a human duplicate-patient judgment. | **r1: A** — accepted, fixed on branch (`9459fee`). Single conditional `UPDATE … WHERE status = 'pending' RETURNING`, 409 on no match. No new state, so no re-gate. Regression: `test_review_queue.py::test_a_concurrent_disposition_cannot_overwrite_the_first_one`. |
| 2 | W2-SPEC-1 | `services/records-service/app.py:202-248` — encounters are scanned in `Encounter.id` order and capped at `relevant_records_max_scan` **before** salience ranking is applied. On a chart with more than `max_scan` records, older low-value rows can consume the budget so a newer allergy/medication encounter is never read, and the clinician's first-attention panel omits exactly what it exists to surface. | **r1: A** — accepted, fixed on branch (`2258a18`). Owner-routed 2026-08-08 as a branch fix, not a stage-3 return. Regression: `test_records_relevant.py::test_the_scan_bound_cannot_drop_a_higher_ranked_record`. |

### Verification notes (fix-session step 2, evidence)

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

### Routing (fix-session step 4)

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

### Re-verification (fix-session step 5)

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

## Round 2 — 2026-08-08

PR #63, verdict `approve`. **0 material findings** — "No ship-blocking defect found in the
branch diff." All 14 CI checks green at the reviewed head `2258a18`. No findings table:
the round is dry, and the two "top things to improve" items are not defects in the diff.

| # | SPEC | Item | Disposition (r2: A/B/C/E) |
|---|------|------|---------------------------|
| 1 | — | "The reviewer could not actually run the test suite (pytest wasn't installed in the review environment) … run the full slice and post the passing output before merging." | **r2: E** — harness limitation, not a code defect. Answered with evidence rather than a change: see below. |
| 2 | — | "Make sure CI is configured to run these new test files automatically." | **r2: E** — already true before the round, and provably so. `.github/workflows/ci.yml:91` runs `pytest -m "not integration" -q` from the repo root, which collects the whole `tests/` tree; no per-file registration exists or is possible to omit. The `tests` job on this PR's own head reported **923 passed, 5 deselected, 1 xfailed in 42.22s** — that count *is* the new files running. |

### What the dry round actually checked (evidence, not absence of evidence)

The round names its coverage: gateway authz/proxy paths, duplicate-queue write semantics,
the matching/retroactive pass, the schema changes, and frontend API forwarding. Two of
those matter specifically because of round 1:

- **Queue write semantics were re-inspected after the r1 #1 fix** and drew no finding —
  the conditional `UPDATE … WHERE status = 'pending' RETURNING` is the surface the fix
  wrote, so a clean read there is the B-round check, not a repeat of r1's read.
- **The records path was re-inspected after the r1 #2 reorder** with the deliberate N+1
  and D8 left in place, and the round did not re-raise the bounded-SQL suggestion it made
  in r1 — the landmine rationale held on second look.

### Evidence posted for item 1

- Full suite, `make test-docker` at head `2258a18`: **923 passed, 5 deselected, 1 xfailed
  in 33.11s** — the `CLAUDE.md` §6 baseline exactly, xfail and deselected unmoved.
- Named slice (`test_gateway_authz` · `test_gateway_review_queue` · `test_matching_parity`
  · `test_records_relevant` · `test_retro_match` · `test_review_queue`): **106 passed**.
- CI `tests` job on the same head (run 31281202640): **923 passed, 5 deselected, 1
  xfailed** — the suite had in fact already run green in CI before the round asked.

### Routing

Nothing to route: no code change, no re-gate, no new test. Loop closes at 2 rounds
(2 A-fixes in r1, 1 dry round) — merge-ready.
