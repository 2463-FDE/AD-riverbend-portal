# W2 PR body — relevant-records helper, duplicate disclosure, match key + review queue

> Status: MERGED `e86e11d` 2026-08-08 (PR #63, squash, branch
> `feat/noref-w2-match-key-helper` deleted)
>
> **Codex round 2 — 2026-08-08, dry, verdict `approve`, loop closed.** "No ship-blocking
> defect found in the branch diff. No material findings." Both "top things to improve"
> were labelled **E** (harness/infrastructure, not code): the reviewer could not run
> pytest in its own environment, and its CI-wiring worry was already closed —
> `.github/workflows/ci.yml:91` runs `pytest -m "not integration" -q` from the repo root,
> collecting the whole `tests/` tree, and the `tests` job on this very head had already
> reported 923/5/1. Answered with evidence, no commit: full suite at `2258a18`
> **923 passed, 5 deselected, 1 xfailed** (baseline exactly), named slice
> (`test_gateway_authz` · `test_gateway_review_queue` · `test_matching_parity` ·
> `test_records_relevant` · `test_retro_match` · `test_review_queue`) **106 passed**, and
> the matching CI run. The round re-inspected both r1 fix surfaces — the conditional queue
> UPDATE and the reordered records scan — and drew nothing, which is the B-round check
> those fixes needed. Round log in `review-findings.md`, ledger line in
> `docs/review-loop-metrics.md` §4. Squash-merged with owner approval 2026-08-08 as
> `e86e11d`; `main` fast-forwarded `6a86a98..e86e11d`, branch deleted.
>
> **Codex round 1 — 2026-08-08, 2 findings, both `[medium]`, both fixed on the branch.**
> Labelled **A/A** (defects in the code as pushed); round log and evidence in
> `review-findings.md`, ledger line in `docs/review-loop-metrics.md` §4. (1) The
> disposition handler was read-check-write, so two concurrent reviewers could both see
> `pending` and the later commit would silently replace the first verdict and
> `decided_by` — the audit trail of a human duplicate-patient judgment. Now one
> conditional `UPDATE … WHERE status = 'pending' RETURNING` with a 409 when it matches
> nothing (`9459fee`). (2) The relevant-records helper spent the `max_scan` budget in
> encounter-id order *before* ranking, so a chart larger than the bound could omit a
> newer allergy from the clinician's first-attention panel; the already-loaded encounter
> list is now ordered by the item-sort key before the scan loop, costing no extra query
> and leaving the deliberate N+1 and D8 untouched (`2258a18`). Neither fix introduces or
> alters state, so neither was routed back to stage 3. Suite re-run: **923 passed, 1
> xfailed, 5 deselected** — baseline +2 (one regression per finding), xfail and deselected
> unmoved; `CLAUDE.md` §6 updated 921 → 923. Both guards proven load-bearing by
> break-then-revert. Pushed `47a1526..2258a18` with owner approval; **all 14 CI checks
> green** again, `r1:` disposition comment posted and `@codex-review` re-tagged
> 2026-08-08 — round 2 awaited.
>
> **Rebase record — 2026-08-08.** Branch reconciled onto `main` @ `6a86a98` after the two
> W2 docs PRs landed (#61 requirements/spec/gated plan, #62 citation repoint); head moved
> `cda34b6` → `47a1526`. The rebase carried **no code** — `git diff` between the two heads
> is empty outside markdown — so the impl-gate verification below still covers this tree,
> and no re-gate was run. Two conflicts, both from the #60 doc-drift sweep, resolved on
> merits: `docs/onboarding-seam-map.md`'s walls table keeps **both** `main`'s corrected D4
> row and this branch's new patient-identity row; and `docs/todo.md` carried a genuine **id
> collision** — #60 took TODO-57, so this branch's frozen-`eval/rag/` entry renumbered to
> **TODO-58** per `gate-findings.md` finding 4's own re-check instruction. Suite re-run at
> the rebased tip from a clean `git archive` extract: **921 passed, 1 xfailed, 5
> deselected** — exact baseline, xfail and deselected unmoved. Pushed 2026-08-08 with owner
> approval; PR #63 opened, all **14 CI checks green**, `MERGEABLE / CLEAN`.
>
> **Impl-gate record — 2026-08-08, impl-gated fresh-context.** Branch
> `feat/noref-w2-match-key-helper`, HEAD `cda34b6`. Round 1, clean — no findings, no
> round log opened. Re-verified independently from a `git archive` of the branch (not
> the authoring checkout): full suite **921 passed, 1 xfailed, 5 deselected** (+100 on
> the 821 baseline, xfail/deselected unmoved); `check_drift.py` exit 0; frontend vitest
> 55/55 and `tsc --noEmit` green; both `matching.py` copies byte-identical by hash;
> branch commits carry no `Co-Authored-By` trailer; registry-sweep grep re-run — every
> remaining `match_key: none`/"no MPI" hit lands on the plan §9 amend or
> deliberately-not-amended list. Residuals accepted at this gate: none beyond the four
> named in the plan and restated below (SPEC-3/6 surface boundary, SPEC-6 fail-safe,
> SPEC-20 detection floor, TODO-58 frozen `eval/rag/` artifacts). `npm run lint`/`build`
> and the live-stack pass were not re-run at the gate; accepted from the implementation
> session's record below. Push stays human-gated.
>
> Delivery state for W2 lives on this header (spec stays AGREED, plan stays GATED).
> Draft written by the stage-4 implementation session; the impl gate reads it from the
> working tree. Lands on `main` via `noncode-merge`, never cherry-picked onto the code
> branch.
>
> Branch: `feat/noref-w2-match-key-helper` (off `main` @ `2532a7d`, after W3's #58/#59)

---

## Overview

W2's analysis half has been on `main` since the prior engagement (`eval/rag/REPORT.md`,
ADR 0005, D5a, the drift gate) and is verified, not rebuilt, here. This PR is the
un-landed half: the clinician-facing retrieval helper with its duplicate disclosure, the
ADR 0005 SSN-corroborated match key at intake, the front-desk review queue, and the
retroactive pass over existing rows.

**Flag-and-review only. Nothing in this PR merges, alters, or deletes a patient row** —
ADR 0005 decisions 3 and 4. A wrong automated merge cross-contaminates two people's
charts, so dispositioning a queue entry records a human judgment and the merge itself
stays a Health Information Management procedure. That is asserted negatively, not
assumed: `test_review_queue.py::test_disposition_never_touches_a_patient_row` compares
every patient field before and after a `duplicate_confirmed`, and
`test_retro_match.py::test_pass_never_writes_a_patient_row` asserts the pass adds and
deletes nothing.

Two facts discovered at plan stage shape the design and are worth restating:

- **The eval retriever is local** (`sentence_transformers`, `eval/rag/retriever.py`) —
  there is no vendor-egress retrieval anywhere in the estate, and corpus embeddings were
  already embed-once-cached. So W2 adds no vendor egress at all (W2-SPEC-15 holds
  trivially, and is asserted rather than assumed by a no-embedding-import scan over the
  whole of `services/records-service/`).
- **Chart open carries no query text**, so semantic retrieval at serve time is
  ill-defined. Serve-time relevance is deterministic salience ranking — allergies first,
  then medications, then recency — with the `reason` on every item, so a clinician can
  see the ranking rather than trust a score. The serving path contains no embedding code,
  which is how W2-SPEC-13 holds by construction rather than by budget discipline.

## Risk & landmines

Touches `docs/landmines.md` §1 zones: **migrations** (new `009_duplicate_review_queue.sql`
plus the hand-synced `db/schema.sql` blocks — additive only, two new tables, **no PHI
columns**, no change to any existing table) and **patient identity / intake** (the ADR 0005
match key itself, owner-scoped into W2 at requirements stage 2026-08-07; the plan's owner
review is the planning approval and this PR is the gated code review it named).

**Auth zone not touched.** No change to `require_session`, `require_capability`, sessions,
`config/roles.yaml`, or `services/gateway/authz.py`. The three new gateway routes reuse
existing capabilities through existing machinery — `records.read` for the helper (the
chart-read grant), `patients.write` for the queue (the registration grant front_desk,
admin and staff already hold and clinician and roi_clerk already lack). No new role, no
new capability, no unauthenticated path. `EXPECTED_ROUTE_CAPABILITIES` in
`tests/test_gateway_authz.py` is edited deliberately and in-plan, with denial tests added
for every new route (clinician + roi_clerk → 403, anonymous → 401).

**PHI columns:** none added, none modified. **ROI:** untouched.

### Deliberate defects preserved

- **D11** (IDOR / session-not-patient-bound chart reads) — the helper route inherits it in
  kind, not widened in kind: per-patient-id, no new cross-patient query surface, no search
  parameter, no new capability. Not fixed. The *exposure set* grows by one route, so the
  D11 row in `docs/debt-log.md` now lists it — `docs/landmines.md` §1 says to size the D11
  fix against the whole set, and an unlisted route is an unsized one. Registry upkeep, not
  a fix; status stays OPEN.
- **D8** (schema has zero indexes) — no `CREATE INDEX` added. The normalized-SSN prefilter
  in both the intake hook and the disclosure path is a deliberate sequential scan,
  acceptable at seed scale and degrading with growth exactly as D8 already records.
- **D4 open half** — the fourteen inherited `_get`/`_post` proxy routes that swallow every
  failure into a 200-OK `{"error": str(e)}` body are untouched and unmigrated. The new
  routes never use them; `_get_checked` is added as the read-side twin of `_post_checked`,
  and `test_gateway_review_queue.py::test_queue_routes_never_use_the_swallowing_helpers`
  proves it behaviourally by wiring the legacy helpers to explode.
- **D5b**, **TODO-1** (registration is non-functional and reports success) — untouched. The
  match hook sits *after* `_create_patient`, which the broken portal payload never reaches.
- **D2**, **D3** — unchanged. The matcher creates no new stored SSN copy: normalization
  happens in the WHERE clause over the existing plaintext column, and neither new table has
  an SSN column (asserted at schema level in `test_intake_match_key.py`).

### Accepted residuals (carried from the plan, unchanged)

- **SPEC-3/6 surface boundary.** The disclosure lives on the portal chart surface and in
  the helper response. A raw API consumer of the *existing* `GET /patients/{id}/records`
  gets none — that route is D11/D8 territory, deliberately untouched. The portal, which is
  the spec's named system element, always shows it.
- **SPEC-6 failure path.** If the helper endpoint is down, the fail-safe is the frontend's
  fixed fallback, not a backend guarantee. The fallback says both things — relevant records
  unavailable **and** duplicate-chart status not confirmed — so an unanswered disclosure
  check cannot read as "no duplicates".
- **SPEC-20 detection floor (owner-decided).** Tier 2 (fuzzy name + DOB where the SSN is
  missing or invalid) is deferred, so a duplicate without a usable SSN produces no
  candidate, no disclosure, and no queue entry. The retroactive pass reports those rows
  explicitly as `rows with no usable ssn … unchecked` rather than counting them as clean.
- **Three `eval/rag/` artifacts go deliberately stale.** `REPORT.md:19`, its renderer
  `report.py:143`, and `data.py:310` keep naming `match_key: none` as the root cause after
  this PR flips that file. The report is the frozen measured baseline the drift gate
  compares against (SPEC-9/10); re-rendering it would move that baseline for a reason
  unrelated to measurement. Each is true as of the measurement it reports and false as a
  statement about `main` after this lands. **Tracked as `docs/todo.md` TODO-58** so it is
  visible to a doc-drift sweep, not only inside this workflow bundle. (Allocated as
  TODO-57 in the plan; renumbered at the 2026-08-08 rebase onto `237c74c` per the plan's
  re-check instruction — the doc-drift sweep took TODO-57 in the interim.)
- **Disclosure freshness vs ranking scope.** The disclosure is evaluated live per chart
  open, but the *ranking* still only sees the opened chart — a sibling's penicillin allergy
  remains invisible from 1042. That is precisely what the banner discloses, and only an HIM
  merge fixes it.
- **A deliberate coverage gap closed on purpose.** `docs/landmines.md` §3 listed "no
  input-normalization or duplicate-patient tests" as deliberate. The duplicate-patient half
  is now closed by three suites; the clause is amended in §3 to keep the
  input-normalization half open (W2 adds no intake input canonicalization — the matcher's
  `normalize_ssn`/`normalize_name` are matcher-side only and never touch what is stored).
  A moved gap is a reportable event, so it is named here, in §3, and in the `CLAUDE.md` §6
  baseline line — not absorbed into a new pass count.

## What ran test-first, and what didn't

**Test-first (red → green), per `.claude/skills/tdd/`:**

- §1 matcher (`matching.py` ×2) — `tests/test_matching_parity.py` written and failing
  first.
- §3 intake match hook — `tests/test_intake_match_key.py` written first; 11 of 18 red
  before the hook existed.
- §4 retroactive pass — `tests/test_retro_match.py` written first (collection error until
  `retro_match.py` existed).
- §6 relevant records + disclosure — `tests/test_records_relevant.py` written first; 15 of
  18 red before the endpoint existed.
- §7 eval corpus cap — cap tests added to `tests/test_rag_eval.py` alongside the change.
- §5 frontend — `app/review-queue/page.test.tsx` and `app/records/page.test.tsx`.

**Not test-first, with reasons:**

- §2 migration + ORM models — DDL and column declarations, no behavioural seam of their
  own. Covered by the slices that write to the tables, plus a mechanical
  migration-vs-`schema.sql` column/constraint diff run in verification.
- §5 intake-service queue routes — the two routes were written before
  `tests/test_review_queue.py`. Honest deviation from the inner loop; the tests are the
  same ones the loop would have produced (including the load-bearing
  patient-row-untouched negative), but they were not observed red first.
- §5 frontend BFF proxies, the `AppShell` nav entry, and §9 registry upkeep — 7-line proxy
  shells and prose, no seam to drive.

## Deviations from the plan

1. **Two test files the plan's Verification demands but its Files-touched table omits.**
   The plan's Verification step 4 requires queue-listing, disposition, session-stamping and
   denial tests, but the table lists only four new suites, none covering the queue service
   or the gateway's queue routes. Added `tests/test_review_queue.py` (intake-service
   routes) and `tests/test_gateway_review_queue.py` (gateway: `decided_by` from session,
   forged `decided_by` discarded, `_get_checked` typed 504/502/502-non-JSON relay). Plan
   fact wrong, fix trivial — no design change.
2. **"Non-empty `allergies`" is sentinel-aware, not literally non-empty.** The plan's §6
   ranks records "whose encounter carries non-empty `allergies`". Implemented literally,
   the seed's own patient 1601 — whose allergies column reads `none known` — would open
   with a phantom allergy at the top of a clinician's panel. `eval/rag/data.py`
   (`parse_clinical_list`, `_NO_ALLERGY_SENTINELS`) exists precisely to avoid that, and
   `tests/test_rag_eval.py::test_none_known_is_not_an_allergy` already pins it on the eval
   side. `records-service/app.py` gets a small `_ASSESSED_EMPTY` set citing that source.
   Behaviour-affecting, so flagged rather than folded in silently.
3. **`matching.py` accepts any `Mapping`, not just `dict`.** The plan specifies "plain
   dicts". SQLAlchemy's `.mappings()` returns `RowMapping`, which is a `Mapping` but not a
   `dict`, so an `isinstance(row, dict)` check would have silently read every field as
   empty in both services. Widened to `collections.abc.Mapping` (dicts still pass) with ORM
   attribute access as the fallback, so tests and services exercise one code path.
4. **`classify_ssn_group` groups internally by normalized SSN.** The plan describes it as
   taking one SSN group; it now tolerates a mixed set by classifying each group
   independently. Both callers still prefilter in SQL, so this changes nothing they do —
   it removes a failure mode where a broken prefilter could weld two SSN groups into one
   candidate pair, which is a wrong-merge candidate over two different humans.
   `test_matching_parity.py::test_rows_from_different_ssns_never_share_a_component` pins it.
5. **`_forbid_fanout` in `tests/test_gateway_authz.py` now also patches
   `_get_checked`/`_post_checked`.** Without it the "no downstream fan-out on a denied
   request" assertion is vacuous for every route added since the checked-helper split —
   including the pre-existing `POST /ai/intake-instructions` row and all three new routes.
   Strengthens an existing test; no production change.
6. **A real bug found by a test, fixed in the same slice.** `app/review-queue/page.tsx`
   initially depended on `useRouter()`'s return value inside a `useCallback`; Next hands
   back a fresh object each render, so the mount effect refetched the queue on every
   render. Held behind a ref instead.

**Planned slices with an empty result:** none. Every slice in the plan's scope map produced
a change. §8 (backfill verification of SPEC-7..10 and SPEC-19) is verification of record and
correctly produced no diff — all five claims re-verified against the working tree this
session, no gap found, so there is no finding to file.

## Verification run

| Step | Result |
|---|---|
| 1. Suite + baseline | `make test-docker` → **`923 passed, 1 xfailed, 5 deselected`**. Was `821/1/5`; **+102 passed, xfail and deselected unmoved**. `CLAUDE.md` §6 updated. (100 at the original push; +2 at codex r1.) |
| 2. Matcher (SPEC-20/21) | Parity + coherence green, including the eval's full topology zoo replayed row-for-row. Negatives: drifting one copy of `matching.py` → parity test red → revert. Collapsing `status_for` to a whole-group verdict → 4 tests red including the mixed fixture → revert. |
| 3. Intake hook (SPEC-22/23/32) | Candidate → 201 + queue rows; matcher raising → 201 + failure row + class-only log. Negative: making the hook re-raise → 4 tests red → revert. |
| 4. Queue (SPEC-25..28) | Pending-only listing; disposition stamps `decided_by` from the session and a forged client value is discarded; pair leaves the pending list; patient rows byte-identical after `duplicate_confirmed`; clinician/roi_clerk 403 and anonymous 401 on both routes. |
| 5. Helper scoping (SPEC-4/17) | With the Maria cluster present, `1042`'s response contains no sibling record and no sibling id **anywhere in the payload** (adversarial over the whole JSON); disclosure `candidate`; a no-SSN patient → `none`; a mixed group discloses per row. |
| 6. Embedding discipline (SPEC-11/12/13) | Pinned encode-count test still green; the whole of `services/records-service/` imports no embedding or vendor SDK; cap below corpus → `CorpusTooLarge` raised **before any encode and before the heavy imports**, cache dir untouched; cap ≥ corpus → unchanged. |
| 7. PHI (SPEC-14/16) | Log-scan tests on the match path, the queue path and the relevant-records path; SSN planted in `name`, `address` and the driver's exception message survives into no log record; queue responses carry no SSN or address. Negative: logging `str(e)` on the match path → 2 tests red → revert. |
| 8. Drift gate (SPEC-9/10) | `make eval` green. Negative: one byte edited in `db/seed/goldset.json` → `make eval` exits 1 → revert → green. |
| 9. Live stack | **Run 2026-08-08 on a fresh volume, fully green** — every expectation in the plan's step 9 reproduced, including the Maria trio. Detail below. |
| 10. Frontend gates | `npm run typecheck`, `npm run lint`, `npm test` (**55 passed**, 5 files), `npm run build` all green. Both new API routes and `/review-queue` appear in the route manifest. |
| 11. Registry sweep | Sweep grep re-run; **every remaining hit lands on the amend list or the deliberately-not-amended list** (ADR 0005 context, `specs-deprecated/w2.md`, the two pinning tests, the three `eval/rag/` sites → TODO-58). `TODO-58` exists and names all three. `docs/landmines.md` §3 no longer claims there are no duplicate-patient tests while still claiming there are no input-normalization ones. Migration `009` and `db/schema.sql` carry **identical columns and constraints** (mechanical diff), with `009` plain `CREATE TABLE` and `schema.sql` `IF NOT EXISTS`, matching each file's existing convention. |

### Step 9 — live stack, 2026-08-08

**Scope caveat after codex r1.** The live-stack results below were produced *before* the
round-1 fixes. The ranking fix cannot change what they show — the seeded charts are three
orders of magnitude below `RELEVANT_RECORDS_MAX_SCAN=500`, so the bound was never reached
and the ranking is unchanged for every chart in the run. The **disposition write is a
different matter**: it went from an ORM row mutation to a Core `UPDATE … RETURNING`
executed through the session, and the row below reporting `409`, the `decided_by`
session-stamping and the byte-identical patient rows was recorded against the old
statement. Those three claims are re-verified against real Postgres in the run recorded
below the table; nothing in the table is carried forward on inference.

#### Post-fix re-run, 2026-08-08 (owner go-ahead)

`intake-service` and `records-service` rebuilt and restarted against the same database
the earlier run left behind.

| Check | Result |
|---|---|
| **Two concurrent dispositions on one pending pair** | Both fired at pair 9 in parallel: **one 200, one 409**. One `dispositioned` row, one `decided_by`, one `decided_at` — the second request wrote nothing. This is the finding's own scenario reproduced on real Postgres, and it is the claim the stub suite could only model. |
| Disposition + forged `decided_by` | `chief_of_staff` in the body → recorded as **`frontdesk`**, the session username, through the `UPDATE … RETURNING` path. |
| Sequential re-disposition / unknown pair | **409** / **404**, unchanged from the pre-fix run — the conditional write is now the sole 409 mechanism (proved by break-then-revert: dropping the predicate reds the pre-existing sequential-409 test too). |
| Patient rows untouched (SPEC-27) | `md5(patients::text)` over rows 1330 and 1852 **identical** before and after a disposition; rowcount 256 unchanged. |
| Pending list | Dispositioned pairs leave it (4 → 1 across the run). |
| Chart-open ranking (SPEC-1) | 1042 → `candidate`, medication items; **1330 → `candidate` with `allergy` as its top reason** (the penicillin record still ranks first); 1601 → `none`, `medication`/`medication`/`recent` — the `none known` sentinel still produces **no phantom allergy**, which is the property an SQL-side ranking would have put at risk. |
| Disclosure vs disposition | 1042 and 1330 still disclose `candidate` after their pair was dispositioned `duplicate_confirmed` — queue state plays no part, as specified. |
| PHI in logs | Both new paths grepped: disposition lines carry `pair_id`, the verdict and the staff username only; no patient id, name, DOB, SSN or address. |

**Not exercised live:** the scan bound itself. No seeded chart approaches
`RELEVANT_RECORDS_MAX_SCAN=500`, so the live stack cannot reach the condition finding #2
describes; that path is covered deterministically by
`test_the_scan_bound_cannot_drop_a_higher_ranked_record`, which fails on the pre-fix
ordering. **State added by this run:** three more queue rows moved to `dispositioned`
(3, 9, 11). No patient row was created, altered or deleted.

Run twice, with owner go-ahead each time. The **first** run used the operator upgrade path
(images rebuilt, migration `009` applied to the existing database with `psql`); the
**second** used a recreated volume, so `db/schema.sql` created both tables on init. That is
worth noting on its own: **both halves of the hand-synced schema were exercised** — the
migration on an existing database, and `schema.sql` on a fresh one — which is the only way
to catch the drift class landmines §2 warns about, since there is no migration runner.

The results below are from the **clean-volume run** (255 seeded patients). All eleven
containers healthy.

| Check | Result |
|---|---|
| Retroactive pass (SPEC-29/30/31) | 255 scanned, 252 SSN groups, 1 row reported as **unchecked** (id 1728, SSN area 666 — structurally never issued, correctly refused), **3 candidate pairs: exactly the Maria trio** 1042↔1330, 1042↔1588, 1330↔1588. Re-run → same 3 found, **0 inserted**. Patient rowcount unchanged. |
| Intake hook (SPEC-22/23/31) | `POST /intake` registering a fourth Maria with the SSN typed as `412 55 9981` → registration completes (`patient_id: 1852`) and **3 new pairs** queue linking it to all three existing charts, so the normalization works end to end. The pair already **dispositioned** was not re-queued (still exactly one row, still `dispositioned`), and the two still-pending pairs were not duplicated. `match_evaluation_failures` empty. |
| Helper + disclosure (SPEC-1/3/4/17) | Clinician opens 1042 → `duplicate_disclosure: "candidate"`, items ranked, and an assertion over the **whole JSON** confirms no sibling id (1330, 1588) and no sibling record — 1330's penicillin allergy is correctly *absent* from 1042 while the banner discloses that the set may be incomplete. That is the RIV-160 harm surfaced without query-time unioning. Opening 1330 → `candidate`, and its **top-ranked item's reason is `allergy`** — the penicillin record ranks first on the chart that holds it. |
| Sentinel ranking (deviation 2) | Patient 1601, whose `allergies` column reads `none known`, ranks `medication`/`medication`/`recent` — **no phantom allergy**, and `disclosure: none`. |
| Authz (SPEC-18/28) | front_desk → helper **403**; clinician → queue **403** (`requires capability patients.write`); anonymous → **401** on all three routes. |
| Queue + disposition (SPEC-25/26/27) | front_desk lists the 3 pending pairs; payload carries **no SSN and no address**. Disposition with a **forged `decided_by: "chief_of_staff"`** → recorded as `"frontdesk"`, the session username. Pair leaves pending (3 → 2). Re-disposition → **409**; unknown pair → **404**. Patient rows 1042/1330 **byte-identical** (md5 over the full rows) after a `duplicate_confirmed`; rowcount unchanged. |
| Portal round-trip | `/review-queue` and `/records` serve 200 with the nav entry present. Driving the **BFF proxies** with a real token: `GET /api/review-queue` → 5 pending, `GET /api/patients/1042/relevant-records` → `disclosure=candidate`, `POST /api/review-queue/2/disposition` with a forged `decided_by` → `decided_by=frontdesk`. The forged value is discarded through the portal path too, not only the direct gateway one. |
| PHI in logs (SPEC-14/24) | intake, records and gateway logs grepped for every SSN form, name, DOB, address and `penicillin` in play → **clean**. What the paths do log: `intake: match key evaluated for patient 1852 ssn_mates=4 candidate_pairs=6`; `relevant-records patient_id=1601 scanned=3 returned=3 disclosure=none`; and disposition lines carrying only `pair_id`, the verdict, and the staff username. |

**Not verified visually.** The Chrome extension was not connected, so the banner's on-page
placement was not eyeballed. What *is* pinned: `app/records/page.test.tsx` asserts the
banner's text, its `rb-alert--warn` class, the absence of sibling ids and of any link, and
the chart-renders-anyway split; and the disclosure, fallback and "does not merge, change,
or delete either chart" strings were confirmed present in the served **client** bundle,
so they are client-authored fixed literals rather than anything relayed from upstream.

**State left behind:** the clean-volume run left patient `1852`, six queue rows (one
`dispositioned` by `frontdesk`, one by the portal path), and the seeded data. Nothing was
deleted — deleting patient rows is precisely what this change must never do. `make down`,
`docker volume rm ad-riverbend-portal_pgdata`, `make up` returns the volume to seed state.

**One finding from the first (dirty-volume) run, kept because it is a real operator
lesson.** That database had accumulated 26 hand-created rows from earlier manual testing,
one of which — "Maria Gonzalez", same SSN and DOB, **blank address** — bridged the cluster:
it corroborates 1042 and 1330 (strong name + DOB) but not 1588 ("M. Gonzalez" is an
initial-only name, a weak signal, and with no address there is no second signal). The
component was connected but not a clique, so every row in it classified **ambiguous** — no
pair, no disclosure. That is W2-SPEC-21 behaving exactly as specified, matching
`eval/rag/data.py` row for row, and it is pinned in `test_matching_parity.py`. The
practical consequence: **one sloppy registration can suppress the disclosure for an entire
real cluster.** That is the honest cost of the pairwise-corroboration rule (the alternative
— letting a bridge row weld a cluster together — merges two different humans), and it is
worth knowing before anyone reads a quiet review queue as "no duplicates".

## Files touched

Backend: `services/intake-service/{matching,retro_match}.py` (new), `app.py`, `models.py`,
`schemas.py`, `intake.yaml`; `services/records-service/matching.py` (new), `app.py`,
`schemas.py`, `config.py`; `services/gateway/app.py`; `db/migrations/009_duplicate_review_queue.sql`
(new), `db/schema.sql`; `eval/rag/{retriever,run}.py`.

Frontend: `app/review-queue/page.tsx` (new), `app/api/review-queue/route.ts` and
`app/api/review-queue/[id]/disposition/route.ts` (new),
`app/api/patients/[id]/relevant-records/route.ts` (new), `app/records/page.tsx`,
`app/components/AppShell.tsx`, `app/lib/types.ts`, plus `page.test.tsx` for both surfaces.

Tests: `tests/test_{matching_parity,intake_match_key,retro_match,review_queue,gateway_review_queue,records_relevant}.py`
(new); `tests/test_{gateway_authz,rag_eval,intake_schemas}.py` (amended).

Registry: `adr/0005-mpi-match-key.md` (Status → Accepted, tier 1 only),
`docs/landmines.md` (§1 duplicate-patients bullet, §3 coverage-gap clause),
`docs/debt-log.md` (D5a narrowed, D11 exposure set), `docs/runbook.md` (RIV-160 entry +
retroactive-pass procedure), `ARCHITECTURE.md`, `docs/onboarding-seam-map.md`,
`docs/todo.md` (TODO-58), `CLAUDE.md` §6 baseline.
