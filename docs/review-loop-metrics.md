# Review-loop metrics

> Why the review fix session clusters findings and design-gates stateful fixes, and how
> we tell whether that works. Baseline measured 2026-07-28 over every code PR merged to
> that date, under the prior engagement's `address-review` loop (a dead name on `main` —
> CLAUDE.md §11); the labels and lessons carry over. The current procedure is
> `.claude/skills/implementation/` "Addressing a round".
> **Do not re-derive this from scratch** — append to it (§4).

## 1. What is measured

Every automated-review finding gets one label at triage time (fix-session step 2):

| Label | Meaning |
|-------|---------|
| **A** | Defect in the code as originally pushed. What the reviewer is nominally for. |
| **B** | Defect in code that an **earlier fix round wrote**. The fix was the new surface. |
| **C** | Defect an earlier round already tried to fix and did not close. |
| **E** | Neither — harness/infrastructure noise (e.g. the bot could not read the diff). |

**A** rounds are the cost of building. **B** and **C** rounds are the cost of how we
respond to reviews, which is the only part of the loop our process can shrink.

## 2. Baseline (measured 2026-07-28)

Six code PRs, 52 review rounds, 64 findings.

| PR | A | B | C | other | rounds | what drove it |
|----|---|---|---|-------|--------|----------------|
| #2  | 6 | 3 | 8 | – | 11 | one budget-egress defect took r2→r4→r5→r6→r7; PHI-in-history recurred 3× |
| #4  | 1 | 2 | 1 | – | 5  | SSN grouping → multi-field clustering → non-transitive merge → weak comparator |
| #5  | 4 | 1 | 0 | – | 6  | mostly genuine original defects; the one B was a bypass of the guard r3 added |
| #7  | 3 | **14** | 0 | 1 | 15 | r6's abuse-control subsystem took r7–r14 to stabilise |
| #11 | 4 | 3 | 2 | – | 7  | the intake-side breaker added at r4 was attacked at r5 and r6 |
| #14 | 8 | 3 | 0 | – | 8  | Redis hardening and the visit lock each created their own next finding |
| **all** | **26 (41%)** | **26 (41%)** | **11 (17%)** | 1 | 52 | **B+C = 58% of findings** |

Round-by-round labels, for audit:

| PR | rounds |
|----|--------|
| #2 | r1 AA · r2 AA · r3 AC · r4 CC · r5 CB · r6 C · r7 C · r8 C · r9 AB · r10 C · r11 B |
| #4 | r1 A · r2 C · r3 B · r4 B |
| #5 | r1 A · r2 A · r3 A · r4 A · r5 B |
| #7 | r1 A · r2 BB · r3 A · r4 BB · r5 E · r6 A · r7 BB · r8 B · r9 B · r10 BB · r11 B · r12 B · r13 B · r14 B |
| #11 | r1 AA · r2 AC · r3 CB · r4 A · r5 B · r6 B |
| #14 | r1 AA · r2 BA · r3 AA · r4 A · r5 A · r6 A · r7 BB |

### Code written during review rounds vs. in the feature itself

Insertions on code paths only (`services/ frontend/ tests/ eval/ db/ docker-compose .github/`),
merge commits and doc-only commits excluded:

| PR | original push | during review rounds | ratio |
|----|---------------|----------------------|-------|
| #2  | 818  | 714  | 0.9× |
| #4  | 983  | 635  | 0.6× |
| #5  | 297  | 499  | 1.7× |
| #7  | 1092 | 2287 | **2.1×** |
| #11 | 603  | 1560 | **2.6×** |
| #14 | 3251 | 4794 | 1.5× |

In four of six PRs the review loop wrote more code than the feature did.

## 3. What the baseline implies (the reasoning the gate encodes)

1. **Every B finding came from stateful machinery** — counters, TTLs, locks,
   single-flight, breakers, budgets, ID catalogs. None came from a plain logic edit.
   That is why the design-gate trigger (fix-session step 4) is *"the fix introduces or
   alters state"* rather than a judgement call about size.
2. **PR #7 is the worst case and the clearest one.** r6 was a legitimate A finding —
   the paid AI endpoint genuinely had no aggregate abuse control. The fix invented a
   budget/refund/single-flight subsystem (`services/gateway/security.py` 67 → 364
   lines) mid-review, with no design step, and r7–r14 were spent making that
   subsystem correct. Eleven of that PR's findings never existed until we wrote them.
3. **C is a different failure with a different cure.** PR #2's budget-egress defect
   survived four fixes because each fix addressed the instance in front of it. The
   cure is the class sweep (fix-session step 4, the C branch), not the design gate.
4. **The reviewer never objects to complexity — 0 findings out of 64.** Nothing
   external will flag machinery growth. If complexity is to be justified, the
   justification has to come from our own spec (requirement IDs) and from §3's
   cheapest-fix line.

## 4. Ongoing log (append one line per round)

Format: `PR #N r<k> — <count> findings: <labels> · <one-line note>`.
The ledger also goes in the PR reply (fix-session step 6) so it survives independently
of this file.

<!-- append below -->

PR #25 r1 — 1 finding: 0 A / 0 B / 0 C, 1 refuted · "no `portal/svelte.config.js`, so the
adapter is misconfigured and the build cannot emit `build/`" — false. SvelteKit 2.x takes
the config inline through the `sveltekit()` Vite plugin. Disproved by clean-tree
`npm run build` and `docker compose build --no-cache portal`, both printing "Using
@sveltejs/adapter-node" and emitting `build/index.js`; the built server answers `/` and
`/healthz` with 200. Closed with a comment at the anchor line, no code change. First
refuted finding in the log — worth watching whether scaffold-shaped PRs draw more of them,
since the reviewer is reasoning from an older SvelteKit convention rather than from the
build.

PR #25 r2 — 2 findings: 1 A / 0 B / 0 C, 1 refuted · **[high] refuted** — "the runtime stage runs
`npm ci --omit=dev` and every package is a devDependency, so the container fails at startup with
module resolution errors". Premise true (the runtime `node_modules` is 19 entries / 84K), conclusion
false: adapter-node rollup-bundles its runtime into `build/`. All 30 bundle files sweep clean of
executable bare specifiers — the only ones present sit inside `/** @import */` JSDoc comments — and
the real image serves `/` and `/healthz` 200. **[medium] A, fixed** — the `docker-build` job stopped
at `docker compose build`, so the healthcheck, the 3071 publish and the `ORIGIN` wiring this PR added
were never executed anywhere. Closed with `FE-R32` plus a CI step that starts the image.

**Class observation, and the reason r2 is worth reading later.** Both refuted findings so far are the
same class: *runtime failure inferred from static config* — r1 from a missing `svelte.config.js`, r2
from an empty runtime dependency tree. r1 was closed with a comment, which is an instance fix, and it
did not stop r2. The class fix is giving the reviewer a runtime signal to check against instead of an
inference, which is what `FE-R32` buys. If a round 3 lands another of these, the class fix did not
work either and the next move is a design question rather than another comment.

PR #27 r1 — 2 findings: 2 A / 0 B / 0 C · **[high] scoping, no code change** — "HL7 feed ingress
removed without replacement": no live feed exists (nothing in repo or handover posts to
interop-service; the only route in is the gateway's session-guarded `POST /hl7/ingest`, untouched).
De-scope was already ADR 0016 §5's accepted decision; the real gap was ARCHITECTURE.md §6 still
describing the feed with no statement that none is connected — recorded there (058074b). Machine
ingress deferred to the ADR that connects a real feed (auth surface, approval-gated).
**[medium] A, fixed** — runbook still curled the removed 807x host ports (two parameterized forms —
`807N`, a `$p` loop — that the ADR's literal pre-landing grep could not match, so its "zero
references" claim was false; corrected in place). Fix also exposed that ADR §4's `exec gateway curl`
valve recipe never worked (image ships no curl) — replaced with the python form, executed verbatim
against the live stack. Class guard added: any loopback spelling × domain host port (literal
8071–8077, globs, `807N`, `$var`) across docs + `eval/` + `tests/`, regression-proven (058074b).

PR #28 r1 — 2 findings: 2 A / 0 B / 0 C · both scoping, no code change — both restate decisions the
PR's own artifacts already record. **[high]** "existing/defaulted users keep full access via `staff`":
deliberate compatibility posture — ADR 0017 §1 + tradeoff #1, `RBAC-R6`/`RBAC-R10` (no-migration is a
tested requirement, not an omission); the per-account UPDATE is deferred to client sign-off (spec §8
open decision 1) and any migration is §6 approval-gated. **[high]** "role revocation does not reach
live sessions": ADR 0017 tradeoff #7 records exactly this, spec §8 #1 makes session invalidation a
precondition of any reassignment; root cause is D10 (no session TTL, `docs/debt-log.md`), out of this PR's
scope and §6-gated. Reviewer's own summary concedes "the ADR text acknowledges this."

PR #28 r2 — 2 findings: same two as r1, restated verbatim (same anchors, same recommendations);
0 new. The bot reviews the branch diff only and the RBAC diff was unchanged (r1 pushed only the
main merge + this ledger), so a further tag on an unchanged diff reproduces the round — loop
recognized and cut: dispositions stand as r1 recorded, no re-tag, merge proceeds on the human
§6 approval this PR's review was designated to carry (ADR 0017 context; gate table in
`docs/specs-deprecated/rbac.md` §6). Method note: a scoped-out finding restated on an unchanged diff is
recorded as a restatement, not a new A — it measures the bot's statelessness, not our defect rate.

PR #29 r1 — 1 finding: 1 A · **[medium] parked** — score-table mask blanks whole rows, so
goldset.json edits are invisible to the gate (shape shipped in the original push `97297b9`, where
the docstring priced it as a score-stability tradeoff). Triaged as accepted-tradeoff and parked as
the corpus-hash follow-up (TODO-41) rather than fixed. Separately, the prose-level `needs:` item
(eval job not gating docker-build) was first called out of scope, then the call was reversed in the
reply — the `needs:` list is a gate list, `secret-scan` proves it — and fixed in `808aaaf`.
(Backfilled with r2: this line was not written when the round closed.)

PR #29 r2 — 2 findings: 2 A · both re-raise r1's parked mask finding, now conceded — the bot's
narrower shape (compare goldset cells, mask only scores) beats the parked corpus-hash one and costs
a smaller diff. **[medium] fixed** — mask made per-cell: each row survives with its `query` /
`expected records` cells (goldset content, identical on both retriever paths) and the row count
compared; only `retrieved`/`recall`/`precision` cells blanked, rsplit from the right so a
pipe-in-query cannot shift the mask. **[medium] fixed** — three end-to-end bite tests (reworded
goldset query, changed `cites_records`, removed case), each + the per-cell unit test
regression-proven red against the r1 mask (4 fail stashed / 17 pass popped). Pre-push pass
(diff-reviewer): 77k tokens, 18 calls, **0 orientation greps**, 2 findings, both real, both fixed
pre-push: the green message overclaimed compared scope — only SSN-cluster rows render into
unmasked text, and the pass *reproduced* a non-clustered rename + planted allergy passing green
(message + docstring rescoped; blind spot widened into TODO-41, closable by the corpus hash) — and
the Makefile mask comment still described the r1 whole-body mask (§10.1 stale-copy class, cut to a
pointer at check_drift.py's header). Fix commit `c7b8247`.

PR #29 r3 — 1 finding: 1 A · re-raise of r1's other parked follow-up (TODO-40's seed.sql half),
conceded via design gate (option (a): stateless regen-and-diff now; TODO-40's derive-one-copy
rewrite stays parked — structural change on the fresh-volume seed path, not a mid-review edit).
**[medium] fixed** — the gate never checked `db/seed/seed.sql`, the file Postgres actually loads;
`check_drift` now regenerates it from the deterministic generator and fails on any byte
difference, before the report diff. Two end-to-end tests (seed.sql hand-edited / generator
edited), both regression-proven red against the r2 check. CI job comment + step name + Makefile
help line rescoped to what is actually covered; remaining CSV↔generator duplication stays named
in the header and the green output. Pre-push pass (diff-reviewer): 99k tokens, 17 calls, **0
orientation greps**, 4 findings, all low, all real, all fixed pre-push with regression-proven
tests (3 red on the round's own first cut): text-mode seed compare blessed a CRLF rewrite (now
bytes); an uncaught crash exited 1 — the "regenerate and commit" code — instead of 2 (now
wrapped); module-level `import retriever` planted a generic name in the host process's
sys.modules when path-loaded by tests (now on-demand under a unique name); the hand-edit test's
mutation hit the header comment, not the clinical INSERT row it claimed to pin (now anchored).
Fix commit `4ef0571`.

PR #29 r4 — 1 finding: 0 A / **1 B** / 0 C · **[medium] fixed** — the seed check r3 added
validated `seed.sql` against `generate_seed.py`, while the report was regenerated from
`patients.csv` / `encounters.csv` / `goldset.json`, and nothing tied the two sources together: a
generator-side fixture edit plus `make seed-gen` left seed.sql matching its generator, the report
matching the untouched CSVs, and the gate green over a fresh volume holding different data than
the committed RIV-160 report claims. **Labelled B, by §5 step 4** — the flagged mechanism
(`_check_seed_sql`) is absent from the original push `97297b9`; r3 wrote it. Not C: no earlier
round tried and failed to close this, because before r3 there was no seed check to be anchored to
the wrong source. First B on this PR, and it is the predicted shape — the round that adds a
checker adds the next round's surface.
Closed by **deleting the second copy** (r1/r3's parked TODO-40, now taken) rather than
cross-checking it: the generator reads its fixture rows' shared columns from the CSVs and keeps
only the columns the eval never sees (mrn/gender/phone/email/notes; encounter
id/reason/location/status), keyed to the CSV rows and dying loudly on a missing file, changed ids,
reordered rows, or a content swap under a stable patient_id. `seed.sql` regenerated
value-identical (whitespace-only, on three hand-aligned encounter rows). Five discrimination tests
on the derivation itself, each proven red against the pre-derivation code.
Pre-push pass (diff-reviewer): 124k tokens, 23 calls, **0 orientation greps**, 5 findings — 3
medium, 2 low — all real, 4 fixed pre-push with regression-proven tests, 1 parked. Two of the
three mediums were in the round's own first cut, i.e. B-class defects caught before they became
rounds: `make seed-gen`'s plain `> db/seed/seed.sql` truncates the target *before* the generator
runs, harmless while the generator read no files and could not fail, and now a way to leave a
0-byte seed for `docker-compose.yml` to mount into a fresh volume's initdb without complaint (temp
file + rename); and the new timeout test pinned the handler but not the arming — the reviewer
mutation-proved both `timeout=` kwargs deletable with the whole file still green (the fake now
asserts `kwargs["timeout"]`, and the same mutation KeyErrors). The third medium was an overclaim
in the r4 header itself: "no generator-side fixture copy left to edit" was false — `audit_logs`'
intake row hand-copied 1042's name/dob/ssn (D1's PHI-in-logs fixture) and `records` id 2's note
paraphrases `encounters.csv`'s allergy column. The derivable half was derived (seed.sql still
byte-identical; a test now asserts no copy of the old SSN survives anywhere in the seed), the
prose half is named in the header as uncovered. The low fixed: `"retriever" not in sys.modules`
asserted a process-global that would go red pointing at an innocent `check_drift.py` the day any
test path-loads `run.py` — now a sys.modules snapshot across the call.
**Parked, named here rather than fixed:** the seed byte-check makes cross-interpreter determinism
of `generate_seed.py` load-bearing (local `make eval` runs children under system 3.8, CI under
3.12) and nothing pins it; verified identical sha256 under both today, so it is latent. The fix is
an interpreter pin or a CI matrix leg — new CI surface, which is a §3 design call and not a
mid-review edit. Also noted for honesty: `test_red_when_the_eval_itself_fails` is characterization,
not regression — it pins behaviour r3 already shipped and was green against the pre-r4 code.
Fix commit `caea30c`.

PR #29 r5 — 1 finding: 0 A / 0 B / **1 C** · **[medium] fixed** — `_check_seed_sql`'s
`SEED_REGENERATE` remediation told operators to run the exact
`python3 db/seed/generate_seed.py > db/seed/seed.sql` redirection whose truncate-before-run
hazard r4's pre-push pass fixed in the Makefile: the shell truncates the live seed to 0 bytes
before the generator starts, so a mid-remediation generator failure recreates the 0-byte-initdb
state that fix closed. **Labelled C, not B**: the string is r3's code (absent from `97297b9`),
but the defect is the truncation class, and r4 fixed that class in the Makefile without sweeping
its other instruction sites — the §5-step-4 class sweep skipped, which is C's definition. A
strict instance-level reading gives B (r4 never *tried* to fix the message); C chosen because it
names the process failure this file measures.
Sweep run now — and its own first pass missed a site, which is the finding's lesson replayed:
grep `"generate_seed.py >"` found three carriers (Makefile, safe since r4's temp-file + rename;
this message, fixed to `make seed-gen` only; `docs/runbook.md:35`, inherited from `3663c4b`,
swept), and only a looser `generate_seed[^)]*>` re-sweep caught the fourth —
`db/seed/generate_seed.py:19`'s own docstring, hiding behind a double space before `>` (swept;
seed.sql regenerated byte-identical). Same variant-blindness applied to the lock-in test: the
assertion is `re.search(r">\s*db/seed/seed\.sql")`, not an exact substring — the message
legitimately says `commit db/seed/seed.sql`, so the pin is redirection-onto-the-path. Proven red
against the r4 string, green with the fix. Residual, named not closed: the test pins only
check_drift's stderr; a future doc can reintroduce the command untested.
Pre-push adversarial pass skipped this round, on the then-current pre-push When-rule (the rule
lived in `verify-stack`, a dead name on `main`; the live owner of this judgment is
`.claude/skills/impl-gate/`): the diff is a
message constant, two doc/docstring lines and one test — no logic, contract, concurrency,
cross-layer or budget change, and the test's discrimination is step-4-proven. Security lens: no
new surface. Fix commit `5bb54d7`.

PR #29 r6 — 1 finding: **1 A** / 0 B / 0 C · **[medium] fixed** — goldset.json's
`expected_patient_id` / `expected_answer` never render into REPORT.md, so an edit to either
drifted green. This is TODO-41's blind spot, parked at r1 and named in the script header and the
green message since r2 — labelled A, not C, per the #26 r2 precedent: never attempted, scoped out
at a design gate, and the last parked item on this PR (r2/r3/r4 conceded the others; the bot has
now re-raised and won every parked item — price that in before parking on this reviewer again).
Closed at a design gate (user call, Option 2 of 3): **corpus fingerprint** —
`eval/rag/corpus.sha256` pins the sha256 of the raw bytes of patients.csv / encounters.csv /
goldset.json, checked after the seed check and before the report diff; red states the operator
obligation (regenerate the embed report, then `check_drift.py --write-fingerprint`, commit both
together); missing sidecar exits 2. Raw bytes over TODO-41's sketched rendered-document hash,
deliberately: rendering covers only what some renderer shows — the class this finding instances —
while byte-pinning exempts no column (a test edits a column NO report section renders and goes
red). Six new tests, five stash-proven red against pre-r6 code; the roundtrip test discriminates
via a stdout assert (pre-r6 argv handling ignored the flag and ran the full check, so an
exit-code-only assert would have passed green — decoration caught at authoring time). The five
older layer tests now refresh the fingerprint in-copy, preserving each layer's e2e discrimination
and proving renderable-field drift survives a refreshed fingerprint into the deeper layers.
Pre-push pass (diff-reviewer): 92k tokens, 18 calls, 0 orientation greps, **3 low** — all real:
"pins every input byte" overclaimed (the eval CODE is an unfingerprinted input: a `metrics.py`
scoring-definition change reaches the report only through masked cells and drifts green; claim
narrowed to "every DATA input byte", residual named in header + CI comment, fingerprinting the
.py files rejected — comment edits would force embed re-runs); `corpus.sha256` untracked at
review time, so a `commit -am` close would have dropped it and broken the eval job repo-wide
exit-2 (process fix: explicit `git add`, verified `A` in the round's stage); this ledger entry
did not exist yet at review time (this is it). Sound-list covered mask/seed/derivation/exit
contract/CI wiring; pass verified 3.8+3.12 green first-hand. Fix commit `fb0e3a1`.

PR #29 r7 — 1 finding: 0 A / **1 B** / 0 C · **[medium] fixed** — r6's `--write-fingerprint`
was a standalone sidecar writer: edit an input, refresh the fingerprint, skip the embed report,
gate green on stale §4 scores — and r6's own roundtrip test pinned that as intended behavior.
B by definition: machinery an earlier fix round wrote. Closed at a design gate (user call,
Option 1 of 3, the reviewer's primary suggestion): the flag is deleted and `run.py` is the only
corpus.sha256 writer, gated to `--retriever embed` writing the default REPORT.md location
(`fingerprint_destination`), so refreshing the fingerprint IS regenerating the report. Residual,
named: a hand-written sidecar (`echo <hex>`) can still lie — no text-file check stops deliberate
forgery; it lands in review as a sidecar hunk with no paired REPORT.md hunk. The five layer
tests now hand-forge the sidecar in-copy (the surviving adversary), preserving layer isolation.
Pre-push pass (diff-reviewer): 89k tokens, 19 calls, 0 orientation greps, **1 medium + 1 low**,
both in this round's own first cut — the class the pass exists for: (medium) TOCTOU — the
fingerprint was hashed at the END of the embed run, so an input edit during the minutes-long
model-download window blessed bytes the report never read; fixed by hashing before the loads and
refusing the write (exit 2) if the recompute differs. (low) The legitimate write path never
executed in any test (embed needs the model), so deleting the write block stayed green — fixed
with a PYTHONPATH shim faking sentence_transformers/numpy, making the real embed write path and
its mid-run guard run e2e in tests. Five new tests total: refresh-flag-removed and
destination-gating stash-proven red vs r6; stub-run-no-write mutation-proven (unconditional
writer → red); embed-writes layer-A red vs r6; TOCTOU layer-B red vs the guard-less first cut.

PR #29 r8 — 1 finding: 0 A / **1 B** / 0 C · **[medium] fixed** — the fingerprint blesses
goldset semantics no rendered artifact shows: `expected_patient_id`/`expected_answer` are
loaded and fingerprinted but scoring uses `cites_records` alone and REPORT.md renders only
query + citations, so an edit to either passes cleanly through the blessed embed re-run.
Premise half-contested in the reply with evidence: the corpus files are tracked, so the edit
always arrives in review as a readable goldset.json hunk beside the sidecar hunk — review is
never meaning-blind; the real residue is that the fields are dead weight the eval never
validates. Closed at a design gate (user call, Option 1 of 3 = reviewer's own alternative):
committed `eval/rag/GOLDSET.md` — every field of every case, keys sorted, values as JSON,
rendered by `report.render_goldset_summary` — regenerated in-process by `check_drift.py` and
diffed (new layer between fingerprint and report diff). Writer (`run.py
--write-goldset-summary`, also any run writing the default REPORT.md location) is deliberately
UNgated, and the reply explains why that is not r7's escape hatch reborn: the summary is a pure
function of goldset.json the check re-derives, so a stale or forged copy cannot survive; the
fingerprint had no re-derivation, which is why ITS writer is gated. Four new tests incl. the
reviewer's requested regression (edit expected_answer → red; blessed embed run → GOLDSET.md
carries the change → green), all four stash-proven red vs the r7 tip. Pre-push pass
(diff-reviewer): 123k tokens, 21 calls, 0 orientation greps, **3 low** — (fixed) red-path
remediation printed a command whose pip step cannot run under local 3.8 (sentence-transformers
needs >=3.9); message now names the 3.12 interpreter; (fixed) the committed-report-location
predicate existed twice (GOLDSET gate inline, fingerprint gate in `fingerprint_destination`) —
the §10.1 duplicated-instruction shape in predicate form; extracted
`is_committed_report_location`, both writers consult it; (accepted, TODO-42) the test file's
~25 subprocess e2e cases roughly double the pre-push hook's warm wall — named as a decision,
not a surprise. 811/5/1 container, gate green under 3.8.

PR #29 r9 — 1 finding: 0 A / **1 B** / 0 C · **[medium] fixed** — r7's mid-run corpus guard
fired AFTER `main()` had already overwritten REPORT.md and GOLDSET.md, so the exact case its
test covers exited 2 saying "did not bless this result" while leaving a half-updated tree;
writes were also non-atomic (crash mid-write → truncated committed artifact). Fixed by
validating the post-run fingerprint before ANY file is touched (`settled_corpus_fingerprint`,
check split from write) and routing all three committed-artifact writes through temp-file +
`os.replace` (`atomic_write`). Reviewer's requested regression added: the mid-run test now
snapshots REPORT.md and GOLDSET.md and asserts byte-identity plus no leftover `.tmp` on the
exit-2 path — stash-proven red vs the r8 tip (fails on REPORT.md bytes), green with the fix.
Pre-push pass (diff-reviewer): SKIPPED on a user call, judgment on record — ~40-line delta,
single-threaded CLI, no contract callers, no cross-layer surface, and the byte-level
regression proof covers the finding's exact failure mode; §6's replaced-code lens closed
inline (only deleted behavior is the bug). Residual named: the fixed `.tmp` suffix clashes
under concurrent runs — accepted for a single-user CLI. 811/5/1 container.

PR #29 r10 — 1 finding: 1 A · **[medium] conceded, parked as TODO-43 — no fix commit; round
closes the loop and the PR merges with this as the recorded open item.** Masked score cells are
not invalidated by eval-code changes: `corpus.sha256` pins the three data files' bytes only, so
a scoring change in `metrics.py` or a ranking change in `retriever.py` leaves the committed
embed-path §4 scores describing old code with the gate green. A, not B, by §5 step 4: the mask
and its code-blindness ship in the original push `97297b9` — r6's fingerprint narrowed the
*data* half of the blind spot, and its reply named this half on record ("the eval code
computing the scores stays unfingerprinted"), rejecting the naive byte-hash of the `.py` files
because a comment edit would force a minutes-long embed re-run. Triage: accepted tradeoff —
blast radius is the committed eval scores only (no runtime/PHI/auth surface), the trigger is an
eval-code edit that skips embed regen, and every workable fix is new design/CI surface
(comment-insensitive code fingerprint of the score-producing functions, a version field written
only by the embed regen path, or a CI leg) — same shape as r4's parked interpreter pin, a
design call rather than a mid-review edit. Ten rounds total on this PR; every finding since r4
targeted machinery a fix round added or a residual already named, which is the diminishing-
returns signal the merge call rests on.

PR #34 r1 — 2 findings: 2 A · both real, one cluster: the original push's class sweep grepped
`str(e)` and missed `log.exception`, which embeds the same exception text via the traceback
(rule-3 mechanism, second spelling). Both fixed by sweeping the whole class, not the two flagged
sites: all 12 DB-error `log.exception` sites in scheduling/roi/records → class-name-only
`log.error`. Booking fix took the reviewer's option B (catch + class name); option A (move
`book()` onto SQLAlchemy) rejected — D5b's raw-psycopg2 race is deliberate debt. ROI edits
log-line-only on explicit §6 approval. Four sentinel tests scan `Formatter().format(record)`
(exc_info text included — `getMessage()` alone passes vacuously pre-fix); all stash-proven
red/green. Dynamic check ran live (postgres stopped + one real ForeignKeyViolation): class-only
lines, no tracebacks; drive-by find → TODO-47 (uvicorn access logs print query-string
identifiers). Pre-push pass (diff-reviewer, 72k/19 calls, zero orientation greps): 2 low — (1)
`cancel_appointment` ran `db.get` outside its try → unhandled ASGI 500 traceback vector; fixed +
sentinel test, red/green proven; (2) same-mechanism sites unregistered (gateway Redis-fault
logs, ai-assistant `str(e)` on the vendor-egress path) → register rows OPEN, no code. Security
lens skipped, judgment on record: no new route/egress/sink/authz/parser. 821/5/1 container.

PR #49 r1 — 1 finding: 1 A / 0 B / 0 C · **[medium] A, fixed** — dev/test toolchain (Vitest, Vite,
jsdom, Testing Library, ESLint) shipped in the production frontend image: the Dockerfile ran plain
`npm install` and never pruned dev deps. Fixed by splitting `frontend/Dockerfile` into `build`
(full install + `next build`) and `runtime` (`npm ci --omit=dev`, copies `.next` + `next.config.mjs`)
stages, plus a `frontend-boot` CI guard that fails if `node_modules/vitest` survives in the built
image. No state introduced → trivial patch, no re-gate. Runtime-verified: image builds, vitest
absent + next/react present, `/healthz` 200. Note vs PR #25 r2: the near-identical "empty runtime
deps" refutation there was SvelteKit adapter-node (rollup-bundled, needs no runtime `node_modules`);
this Next portal runs `next start` and genuinely needs prod deps, so `--omit=dev` is the correct
prune here, not an over-prune.

PR #49 r2 — 1 finding: 1 A / 0 B / 0 C · **[medium] A, fixed** — `frontend-boot` was not in
`docker-build.needs`, so the terminal fan-in job branch protection reads could go green while the
boot probe went red. Fixed by adding the edge; stale `docker-build` NOTE comment corrected, and the
runbook/TODO-45 closure claims made precise about the wiring. **Lesson (both gates missed it):**
E1-SPEC-17 says the pipeline "shall report an overall failure", and the drift gate and impl gate
both accepted "a job exists that polls `/healthz`" as conformance. A CI clause about *pipeline*
outcome is only satisfied by an edge into whatever job is terminal — check the graph, not the job.
Generalizes: for any spec clause naming a system-level outcome, verify the wiring that carries the
signal, not just the component that produces it. Zero-cost to check (`needs` closure over the parsed
workflow), and it was the second consecutive round where a correct component sat behind missing
packaging/wiring (r1 was the Dockerfile).

PR #49 r3 — 0 findings · **dry, verdict `approve`** — "No defensible ship-blocking issue found in
the branch diff. No material findings." Loop closed at 3 rounds (2 A-fixes, 1 dry); squash-merged
`efe6f32`. The dry round did useful confirming work rather than just going quiet: it verified the
r1 fix did not over-prune (runtime image still ships every file the app needs), which is the
regression the `--omit=dev` change could plausibly have caused and which no test in this PR covers.
Reading a dry round for what it *checked*, not only for its empty finding list, is what makes it
evidence rather than an absence of evidence.

PR #58 r1 — 2 findings: 2 A / 0 B / 0 C · **[high] A, fixed** — on a 404 the page cleared
`visitId` but kept the transcript, so the next send opened a fresh contextless gateway visit
under the old coverage answers. Fixed as the class (step 3 cluster): a visible `boundary` seam
("restate the patient and member details") appended at both context-loss sites — the flagged
404 and the 200-with-null-`visit_id` path, which had the same failure mode unflagged. **[medium]
A, fixed** — the "shape check" accepted any 200 carrying a string `reply`, dropping disclaimer
and verdict silently; replaced with a full-contract type guard (`disclaimer` string, `visit_id`
null-or-32-hex verified against gateway `security.py:649`/`app.py:711`, closed vocabularies for
`visit_memory`/`assistant`, `eligibility` null-or-object) → FALLBACK otherwise. No state
introduced by either fix → trivial patches, no re-gate. 9 new tests + 1 extended, all landmines
§3 negatives on the coverage-answer surface; stash-proof vs `dc92fc5`: 10 red / green with fix.
Frontend 29 passed, typecheck/lint/build clean; container suite at the exact pinned baseline.

PR #58 r2 — 1 finding: 1 A / 0 B / 0 C · **[medium] A, fixed** — the gateway reports assistant
health as a tri-state (`ok`/`degraded`/`unknown`, `app.py:1180`) but the page banners only
`degraded`, so `unknown` — the state emitted when ai-assistant's health field is unrecognised
mid-rolling-deploy — rendered as a normal tailored answer. **Labelled A after the §5 step-4
check, and it was close to B**: r1 had just widened `isVisitChat` to accept `unknown`, which is
what the finding anchors on, but the render predicate `degraded: data.assistant === "degraded"`
with no third branch ships verbatim in the original push `dc92fc5` — r1 made the vocabulary
explicit, it did not create the collapse. Fixed by carrying the tri-state onto the turn and
giving `unknown` its own wording ("did not report how it produced this reply… treat its wording
as unconfirmed"). Both of the reviewer's alternatives were rejected with the gateway's own
reasoning: rejecting `unknown` in the guard would discard a verdict a payer call already paid
for and make every deploy read as an outage, and reusing the `degraded` copy would claim a
checklist we cannot confirm. 2 tests (`unknown` → distinct banner + turn still succeeds +
degraded wording absent; `ok` → neither banner, so a blanket always-warn cannot pass); 1
stash-proven red vs the r1 tip `7b5d7d2`. Frontend 31 passed, container 821/1x/5d exact.
**Lesson, generalizable:** a closed-vocabulary check and the render map are one contract. r1
validated three states and rendered two — pinning the members without walking each to a distinct
treatment (or an explicit "renders as nothing, deliberately") leaves the widest member reading as
the safest one. Same shape as #49 r2's "check the graph, not the job": the round that pins a
contract must follow the value to where it is consumed, not stop at the boundary it hardened.

PR #58 r3 — 1 finding: 1 A / 0 B / 0 C · **[medium] A, fixed** — `isVisitChat` checked that
`eligibility` was an object and stopped there, so a skewed 200 with `eligibility: { status: 1 }`
reached `VerdictBadge`, which lowercases `status` and threw during render: the surface went blank
with no verdict and no fallback, the one outcome worse than a missing badge. **A after the §5
step-4 check**: `verdictTone`'s `TONES[status.toLowerCase()…]` ships verbatim in `dc92fc5`, which
passed `data.eligibility ?? null` to the badge with no guard at all — r1 narrowed the throw, it
did not create it. Reproduced exactly (`TypeError: status.toLowerCase is not a function`) and
fixed at both ends, non-redundantly: the guard now checks the verdict's own field types so a
malformed contract never renders (consistent with r1's other eight malformed-200 cases — a
wrong-typed field is a broken body, unlike r2's `unknown`, a valid state), and `verdictTone`
returns null for any non-string so no body of any origin can throw inside render, for every
caller. Unknown **extra** keys pass on purpose, pinned by a test: failing on an additive gateway
field would make every deploy an outage (r2's reasoning, held). 6 tests; 5 stash-proven red vs
the r2 tip `997a042`. Frontend 37 passed, container 821/1x/5d exact.
**Lesson, generalizable:** a guard is only as deep as the field access downstream of it. r1
validated `eligibility` to the depth its *type name* suggested (an object), not the depth its
*consumer* reads (a string it lowercases) — check the leaf, not the container. Third round in a
row on one shape (r2's "validated three states, rendered two", #49 r2's "check the graph, not the
job"): **the round that hardens a boundary must walk the value to its consumer.** Standing rule
for this loop now, not a per-round observation.

PR #58 r4 — 0 findings · **dry, verdict `approve`** — "No defensible ship-blocking issue found in
the branch diff... No material findings." Loop closed at 4 rounds (3 A-fixes, 1 dry); squash-merged
`f69a554`. Read for what it checked (the #49 r3 discipline): it re-inspected the proxy route against
the gateway visit-chat contract, the assistant surface, the badge, and both test files — i.e. the
exact blast radius of r1–r3, confirming three rounds of guard-tightening did not break the contract
they hardened. Nothing outside the branch diff was re-examined, so the accepted residuals are
untouched by the verdict. **Loop shape for W3:** 4 rounds, 4 findings, 4 A / 0 B / 0 C — zero
review-introduced defects across three consecutive fixes, against a baseline where B rounds came
from improvising state mid-review. Every fix this loop was render-only or a pure predicate and
routed as trivial-on-branch; the no-state routing rule (step 4) never had to send anything back to
stage 3, and nothing regressed. The three lessons converge on one rule now standing for this loop:
**the round that hardens a boundary must walk the value to its consumer.**

PR #63 r1 — 2 findings: **2 A / 0 B / 0 C**, 0 refuted · both `[medium]`, both genuine defects in
the code as pushed, both fixed on the branch with a regression each (923/1/5, baseline +2, xfail
and deselected unmoved). **Neither triggered the design gate** — the step-4 test is *"the fix
introduces or alters state"*, and one is a read-check-write collapsed into a conditional UPDATE
while the other reorders an already-loaded list; no counter, TTL, lock, breaker, budget or cache
appears in either. Worth noting against §3's first lesson: the *finding* in #2 is about a budget
(`relevant_records_max_scan`), and the reflex is to route anything budget-shaped back to stage 3.
The rule is about the **fix**, not the finding — the budget keeps its meaning, its default and its
N+1 ceiling, and only the order it is spent in changes. **Lesson:** both defects live in the gap
between a plan sentence and its only faithful reading. #1's plan line named the 409 *contract*
("409 if already dispositioned") and no mechanism, so a non-atomic implementation satisfied it
literally; #2's named a rank and a bound in one sentence without fixing their order, and the
implementation picked the wrong one. Neither gate could have caught either: the plan was
self-consistent, the code matched the plan, and every seeded chart is orders of magnitude below
the scan bound, so no test at seed scale could fail. **Generalizes: when a plan line names a bound
and an ordering in the same breath, the plan owes the order; when it names a status contract on a
shared row, it owes whether the check is in the write.** Both are one clause of plan text, and
both were paid for in a review round instead.

PR #63 r2 — 0 findings · **dry, verdict `approve`** — "No ship-blocking defect found in the branch
diff. No material findings." Loop closed at 2 rounds (2 A-fixes, 1 dry), the shortest code loop in
this ledger. Read for what it *checked*: it re-inspected both r1 fix surfaces — the conditional
queue UPDATE and the reordered records scan — and drew nothing, which is the B-round check the r1
fixes needed and no test in this PR can supply. It also did not re-raise its own r1 bounded-SQL
suggestion, so the landmine rationale for keeping the N+1 (D8) held on a second, independent read.
Both "top things to improve" were **E**, not findings: the reviewer could not run pytest in its
environment, and its CI-wiring worry was already closed before the round began. **Lesson: an E of
this shape is answered with evidence, not a change** — `.github/workflows/ci.yml:91` runs
`pytest -m "not integration" -q` from the repo root, so the whole `tests/` tree is collected and
per-file registration cannot be forgotten; the `tests` job on the reviewed head had already
reported 923/5/1. The cost of the round was one comment carrying three numbers (full suite
923/5/1 local, 106 in the named slice, 923/5/1 in CI), not a commit. **Generalizes: when a reviewer
asks for proof it could not gather itself, check whether the proof already exists upstream before
producing it again — and post the artifact either way, because an unanswered E reads identically
to an ignored A.**

PR #69 r1 — 1 finding: **1 A / 0 B / 0 C**, 0 refuted · **[medium] A, fixed** — the class-name-only
LLM-path log fix (W1-SPEC-13) also deleted the Bedrock `request_id`, which lived only inside the
exception message: two of the three `LLMResponseError` raise sites fire *before* the success log
that emits it, so a schema-drift incident left a 502 with no correlation handle after a paid egress.
Fixed as the reviewer proposed, narrowed to the id: a `request_id` attribute on `LLMError` (the
`egressed` idiom, raiser-set, `None` by default) logged as a structured field at the two catch
sites. **Lesson: a redaction rule deletes a channel, not just a string** — the SPEC-13 sweep asked
"is this message safe to log?" and never asked "what did the message carry that nothing else does?"
The register row and both negative tests hid it, because both were written to prove text was gone,
not that diagnosability survived. Worth carrying into any future rule-shaped sweep: pair "must not
log X" with "must still log Y", or the negative test passes on a log line nobody can use. The
finding was also over-stated on one of its three sites (the structured-validation raise fires after
the success log, so that path lost only the join) — checking each raise site individually is what
kept the fix from growing a provider-error-code surface the spec does not carry.

PR #69 r2 — 0 findings: **dry**, verdict `approve` · tagged on `73b9f06`, the r1 fix commit, so
the dry read lands on the surface r1 wrote rather than on the original diff. Its ship line names
the three claims that carry the PR — the `LLMUnavailable` subclass contract, `request_id` as
structured metadata, and message-leakage removed without moving status/accounting — and it did
**not** re-raise its own r1 recommendation of provider error code / status, which the disposition
had declined; that narrowing held on second look. **Scope note worth carrying: the reviewer is a
code-diff reviewer and named none of the four documentation slices in the diff** (two register
rows, the seam-map cite, `CLAUDE.md` §6 / `todo.md`). On a PR that is half registry upkeep, an
`approve` is evidence about the code only — the registers' evidence is plan verification steps 7
and 8, produced by the impl gate, and nothing in the review loop duplicates it. Loop closed at 2
rounds, 1 A-fix.

PR #72 r1 — 1 finding: **1 A / 0 B / 0 C**, 0 refuted · **[high] A, declined as a pre-disclosed
accepted residual, no code change** — a registration that commits and then loses its response can
be retried into a second `patients` row, because `POST /intake` carries no idempotency key. Premise
accepted in full and one part corrected: `main` had the same commit-then-work-then-respond window,
so the branch does not open it — it makes it *reachable*, because portal registration worked nowhere
before. Declined here because the fix persists state (idempotency key + request/result store), which
is the §3.1 design-gate trigger; the reviewer's cheaper alternative ("UI says status unknown")
contradicts frozen E4-SPEC-7; and the test it asked for would have to be an `xfail`, moving a pinned
count. Routed to `e5`'s requirements stage as the register-first half of D4. **Lesson, and the
reason this round cost one comment rather than a commit: an accepted residual disclosed in the PR
body is not disclosed to this reviewer** — it reads the diff, not the prose around it, and it will
independently rediscover every residual the plan accepted. That is not noise; a residual a cold
adversarial read finds unprompted is evidence the acceptance was worth recording. The cost is one
round per residual per PR, and the only thing that reduces it is accepting fewer of them, not
writing the disclosure differently. Worth watching whether r2 re-raises it after the disposition —
PR #69 r2 did honour a declined recommendation, which is the behaviour this relies on.

PR #74 r1 — **0 findings**, clean, approved in one round. The PR carried three accepted residuals
(pr-body §Accepted residuals), and none came back — which refines rather than contradicts the
PR #72 lesson: all three are *absent from the diff* (out-of-scope `proxy_search`, untouched
eligibility column, work not in the branch), whereas #72's rediscovered residual was a window the
diff itself made reachable. The reviewer reads the diff, so a residual the diff does not exhibit
costs no round; expect rediscovery only for residuals the changed lines make visible.

PR #75 r1 — the first non-code PR through the review loop (the skip rule was revoked
2026-08-11) — 2 findings: **2 A / 0 B / 0 C**, 0 refuted. (1) [medium] the implementation
skill's residual guidance overstated the measured rule: "one round per accepted residual
per PR" was written from e4's n=1 before this PR's own #74 entry refined it to
diff-visible residuals only. Both skill sites aligned; §4 named as the source of truth.
Note the shape: the same PR carried the stale skill line and the ledger refinement that
falsified it, and the reviewer caught the divergence — the CLAUDE.md §10 failure mode (a
duplicated instruction where the stale copy wins) caught at review instead of in the
wild. (2) plan scannability — accepted on premise, fixed as class not instance: the
GATED e5 plan is a stamped record no post-delivery edit may rewrite, so `plan-authoring`
gained a Context scan-summary rule for future plans instead.

PR #75 r2 — 3 findings: **2 A / 1 B / 0 C**, 0 refuted · all three target the review
mechanism this PR ships, which is the point of running it on itself. (1) [medium] A —
step 5's every-round ledger commit read as a self-feeding loop (metrics commit → new
round → new metrics commit); fixed by pinning the termination semantics in the skill:
the ledger line is reviewable diff like any other hunk, but rounds start only on the
re-tag that closes a round with findings — a dry round or `approve` has no re-tag, so
its closing line lands with the merge as bookkeeping. (2) [low] A — the routing table's
"a stage-routed finding does not block by default" named no merge precondition; fixed:
before merge every stage-routed finding needs its route on record in a disposition
(with the filing cite when the route is a registry) and the owner's explicit
wait/land/defer call. (3) [low] **B, the ledger's first non-code B** — r1's class fix
added the scan-summary rule beside a stamped e5 plan that predates it, and nothing said
the rule is prospective; the ambiguity is the fix round's new surface (`ec7d598`), the
predicted B shape in document form. Fixed where the claim lives: the PR body now states
the rule applies to future plans, not retroactively to the gated artifact.

PR #75 r3 — 3 findings: **1 A / 2 B / 0 C**, 0 refuted · **the first round in this ledger
where B outnumbers A**, and the round the round-3 rule was written for. (1) [medium] **B**
— r2's merge precondition said the owner must call *wait / land without / defer* and never
said where that call is recorded or in what words, so every future agent would invent a
format; the under-specification is r2's own surface (`e6c9960`), which did not exist a
round earlier. Fixed with a worked example carrying the exact disposition line and its
three required fields (route, verbatim call, date). (2) [low] **A** — "both measured" for
the diff-visible residual rule overstates n=2; the word ships in the original push
`5e628f2` as "measured on e4" (n=1, thinner still), so r1 inherited the overclaim rather
than creating it. Softened to "observed so far on two PRs", with §4 named as outranking
the skill line if they diverge. (3) [low] **B** — r1's scan-summary rule landed in
`plan-authoring`'s rules section while the Template's `## Context` block still showed the
old shape, so learners read the rule and copied a form that ignores it; the divergence is
`ec7d598`'s surface. Template mirrored.
**Lesson, and the reason this round stopped the loop rather than closing it:** two of the
three findings are defects the previous two fix rounds wrote — the §3.1 B mechanism
reproduced in prose, where the "state" being altered is a rule rather than a counter. A
process rule behaves exactly like stateful machinery under review: adding one creates a
surface (where is it recorded? what wording? does it apply retroactively?) that the next
round finds. **Generalizes: a fix that adds a rule owes the same design-gate question as a
fix that adds state — what does this rule leave unspecified, and where will that show up?**
The three rounds cost, in order, a termination semantics, a merge precondition, and a
worked example, each answering the last one's gap. That is convergent, not divergent, but
it is convergent because the artifacts are documents nobody executes; the same shape in
code is PR #7.

PR #77 r1 — 4 findings: **2 A / 0 B / 0 C**, **2 refuted** · the first round where half the
findings asserted that work in the diff was absent. (1) [medium] **A** — the README claimed
header ownership but never said which stage may write which field, and the `plan DRAFT`
advance was assigned by no file at all (six skills state their own header write;
`plan-authoring` stated none). Fixed with a field→writer table (`9fb793d`). The conflict the
finding actually named — `delivery IMPLEMENTED` vs `## Plan` status — was not real; the
grammar block already carried both axes. (2) [medium] **E** — "the frozen spec contradicts
the mutable `test:` cell" is resolved by the delegation the section table sets up:
`spec-authoring` owns Spec rules and carves the column out at `SKILL.md:26-27` and `:43-45`.
Declined rather than duplicated into the README (`CLAUDE.md` §10). (3) [high] **E** — "the
diff does not show the README update", against a diff whose README change is 160 lines and
the largest file in the PR; all six items named as missing were cited back by line.
(4) [medium] **A/E, split** — the 400-line budget was genuinely homeless (one hit repo-wide,
marked "owned here", no dated decision, no rationale), and is now a dated shape decision with
its basis and its `CLAUDE.md` §11 advisory ceiling; the pinned-test diff in the same finding
was **not** homeless — the rule is `spec-authoring` step 6's freeze scope, and only the gate's
"(owned here)" label was wrong.
**Lesson: a finding that asserts absence is the cheapest kind to check and the most expensive
kind to comply with.** Both E findings here were absence claims, and complying with the second
would have copied a 160-line contract section into the skills that delegate to it — manufacturing
exactly the duplicate-source-of-truth failure the one-file shape exists to remove. The check is
one command (`git diff main...HEAD --stat`) and it ran before any editing. **Generalizes: triage
an absence claim with a diff command before it earns a fix, and when it survives, ask whether
the missing thing is missing or delegated — a review that cannot see the contract file reports
delegation as absence.** Second, smaller: **an "(owned here)" annotation is a claim and grep
settles it** — the same finding covered one rule that was homeless and one that was homed
elsewhere and mislabeled, and only reading both against the tree separated them.
**Process note:** this round had no fresh-context gate available — neither gate can run on a
tooling PR (both key on an item's spec and plan; a skill file has none), so codex was the only
adversarial reader and it misread the diff. Filed as TODO-64, not fixed inside the PR under
review.

PR #77 r2 — 3 findings: **2 A / 0 B / 0 C**, 1 refuted · the round r1's fix made possible.
(1) [medium] **A** — four sites said "set/advance the header to `delivery X`", which reads as
replacing the whole `Status:` line and dropping the `plan GATED` half an earlier stage earned;
each now advances the *delivery axis* and says the plan stamp stands (`e25a0e5`). The reviewer
asked for the literal two-axis string at each site; four copies of a grammar the README owns is
the `CLAUDE.md` §10 shape, so the axis is named instead, and `noncode-merge`'s `MERGED` stamp —
same wording, not in the finding — was fixed with them. (2) [medium] **A** — the gate skills
write a dry `checked:` round on a clean run while the README said a stage with no finding has
no rounds. Resolved by the decode table rather than by preference: it reads "no Gate round" as
*the gate has not run*, which is only sound if a clean run records one, so the README sentence
was the defective half (`f55592c`). (3) [low] **E** — "impl-gate's write boundary contradicts
itself" quotes a rule whose next sentence is the carve-out. Refuted, and the wording tightened
anyway (`56027ce`), since naming the protected Delivery content and the one permitted append
costs three words and removes the misread.
**Lesson: writing a rule down does not only create a surface for the next round to attack — it
also makes latent defects findable, and the two are hard to tell apart from the finding
counts.** Both A findings here are original-push wording (`2aecbbf`), not fix-round wording, so
neither is a **B** — but neither was reachable until r1 wrote "the line carries both axes and a
delivery transition never rolls back the plan stamp" into the README. The reviewer had a rule to
measure four skill sites against, and found them. Compare PR #75 r3, where the rules added by
r1 and r2 were themselves the defect surface: same mechanism, opposite sign. **Generalizes: an
explicit rule converts ambiguity into findings, so expect the round after a state-model fix to
raise more, and label them by whose text is wrong (original push vs fix round), never by which
round could first see them.** Second: **when two documents contradict, look for the third thing
that depends on one of them** — the decode table settled which half was wrong here, and settled
it in one read, where arguing the merits of dry rounds would not have converged.

PR #77 r3 — 6 findings: **1 A / 0 B / 0 C**, 5 refuted · **the round the absence claim came
back**, and the round-3 rule's first application to a non-code PR. The headline finding is r1's
F3 restated — "the README isn't shown carrying those definitions" — against a README that is
the largest file in the diff and had grown twice since, by the reviewer's own two prior rounds
(`9fb793d`, `f55592c`). Two more were the same shape: the branch/merge lifecycle it asked the
README to state is the README's Landing rule, and the pinned-test lifecycle it asked for is
`spec-authoring` step 6. (3) [medium] **A** — both gates say "README owns the round format"
while the section table assigned `## Findings` rules to the stage skill and the README carried
only the heading and numbering; with the inline templates removed, the pointer led to half a
rule. README now carries the row shape and the empty-disposition convention the decode table
keys on (`cab5e5b`). (4) [low] **E**, edit taken (`6cd8bc4`) — the pinned-test lifecycle was
intact in `spec-authoring` and asked about twice, which is a discoverability defect even when
the rule is not. Two suggestions declined with cites: deltas-only wants a worked example (five
delivered plans are the examples), residuals-by-ID wants summaries (`docs/todo.md`'s line format
already guarantees a self-contained line per id).
**Lesson: a reviewer that cannot see the artifact will keep reporting delegation as absence,
and each repetition costs a round even when the answer is a citation.** Three of six findings
this round, and two of four in r1, were absence claims about a file in the diff; every one was
closed by quoting line numbers, and none moved the code. That is not a reviewer defect to
route around — it is the measured cost of this PR class having **no fresh-context gate**: both
gates key on an item's spec and plan, a tooling PR has neither, so the only adversarial reader
is the one worst placed to check the contract (TODO-64). **Generalizes: when the same absence
claim survives a refutation with line cites, stop answering it and fix the reachability instead
— r3's one real finding was exactly that, a pointer that led to half a rule — and count the
repeat rounds as evidence for the missing gate rather than as review noise to absorb.** Cost
here: three rounds, of which one produced two real defects (r2) and one produced one (r3).

PR #76 r1 — 1 finding: **1 A / 0 B / 0 C**, 0 refuted · **[high] A, fixed, with the
reviewer's claim scoped down.** `submission_id` was validated as "parses as a UUID", so the
nil UUID, a v1 and a v5 all passed; the recommendation was to require v4. The observation is
right and was confirmed at runtime before touching the code — a v5 built from `name|dob|ssn`
registered `201` and its derived value landed in the `POST /intake meta=` log line — so the
version check landed (7 tests, all red first; live: nil/v1/v5 → 422 writing nothing, a v4
pair → one chart). **What did not land is the reviewer's account of what it buys.** The
finding credits the check with closing "a client that sends a constant key replays the first
patient's chart", and it does not: `11111111-1111-4111-8111-111111111111` is a valid v4, and
v4 bits can be stamped on a hash of patient values, so the check proves neither randomness
nor non-derivation. It closes the *accidental* class only (an uninitialized field serializes
to the nil UUID; a "make the key deterministic" change produces a v5). Taking the fix while
restating the guarantee cost one extra paragraph in the validator docstring, a scoping clause
on the PHI register row, and residual 7 in the pr-body.
**Lesson: accepting a fix and accepting its rationale are separable, and the second is where
the damage is.** Had the version check shipped described as the reviewer described it, the
next reader of the PHI register would have found "the boundary rejects derived identifiers"
and stopped checking the mint — a control that reads stronger than it is, sited in exactly
the register that exists to be trusted. Fixing the code was one line; not letting the code
carry a false guarantee was the rest of the round. **Generalizes: when a review recommends a
syntactic check for a semantic property (random, fresh, unguessable, owned-by), take the
check if the accidental cases are worth closing, and write down which property it did not
establish — in the artifact a later reader will consult, not only in the reply.**

PR #76 r2 — 1 finding: **1 A / 0 B / 0 C**, 0 refuted · **[high] A, accepted and
routed back through stage 2 and stage 3 rather than patched in the round.** The
replay was keyed on `submission_id` alone, so a lost response followed by a
*corrected* resubmit answered `201` for the original chart and dropped the edit;
confirmed at runtime before any decision, and worse than reported — the replay
re-verified eligibility on the *request's* insurance, so the response echoed the
edited member id while the chart kept the old one. The code implemented
E5-SPEC-30 exactly as written, so the defect was the **spec's**: D-5 decided
"the replay is indistinguishable from the original success" for identical
content and was never weighed against the edit-after-failure case. The fix is a
persisted keyed fingerprint — new state, the skill's structural trigger — so it
went spec amendment → plan revision → fresh-context re-gate (round 9) → this
implementation, which added 14 tests and cost one extra day rather than one
review round.
**Lesson: a finding can be about the diff and still not be fixable in the diff.**
The routing test that worked here was not severity, it was *whose statement is
wrong*: the code matched its clause, so patching the code would have put the
branch out of sync with a frozen spec, and the fingerprint would have arrived as
unplanned persisted state in a review round — which is how every B round in this
baseline started. **Generalizes: when the code correctly implements a clause the
review has just shown to be wrong, the round's output is an amendment, not a
patch; say so in the disposition and name the stage it went back to, so the next
round reads the 409 in the diff as planned work rather than as improvisation.**
Cost of doing it properly, measured: spec amendment 2, plan rounds 7–9, and a
second implementation session; the visible-residual count in the pr-body went
from 7 to 10, which is the price of the new state being real.

PR #76 r3 — 2 findings: **1 A / 0 B / 0 C**, 0 refuted, 1 answered from the
record · **[high] restated residual, closed from the record** — "a replay
re-runs live eligibility instead of replaying the original verdict" is accepted
residual 5 verbatim (plan D-14). No code change, closed with an anchored comment;
the reviewer's remedy is `debt-log` D4 residual 3, already open and the reason
the residual exists. **[high] A, fixed at full scope** — the fingerprint guard
was a bare presence check while `.env.example` shipped a marked dev placeholder,
so a deploy seeded by CI's `cp .env.example .env` would have keyed PHI-derived
fingerprints with a committed value. Now: placeholder sentinels + a 32-character
floor, template shipped empty, +11 tests.
**Lesson: an accepted residual can be narrower than what was delivered, and only
the diff shows the gap.** The pr-body accepted "the fingerprint is PHI-derived
and must stay keyed" and the plan (D-19) explicitly chose a template placeholder;
both were written about the *mechanism*, and neither noticed that the guard's
whole strength was `if not key`. **Generalizes: when a residual's safety rests on
a guard, the residual text must state what the guard actually checks, not what it
is for — "keyed" hid a presence check for two rounds.** Also the first entry
where the estate's own precedent was the whole argument: `llm_client`'s
`_PLACEHOLDER_BEARER_TOKENS` answered this exact question in PR #5 r5, its
rationale sits fourteen lines below the contradicting value in the same
`.env.example`, and nothing in the pipeline reads one guard against its
neighbours — the plan stage, three gate rounds and two impl-gate rounds all
passed over it.
**On the round-3 rule**, which fired here: it earned its place. The two findings
wanted opposite dispositions — one reaffirmed at no cost, one a real PHI-path
defect fixed in full — and both were [high], so severity would not have sorted
them. That per-finding split is the call the rule reserves for the owner.

PR #76 r4 — 1 finding: **0 A / 0 B / 0 C**, 0 refuted, 1 answered from the
record · **the same finding as r3 #1, re-raised verbatim after a dry re-tag** —
"a replay re-runs live eligibility instead of returning a recorded verdict",
same anchor, same remedy. No code change; the owner decision of the previous day
was honoured and cited rather than re-argued. r3's other finding (the
fingerprint-key guard) did not return, so the branch is **dry on new findings**
at r4.
**Lesson: an accepted residual that the diff makes visible does not stop coming
back — it is not paid once.** The pipeline's own line (`.claude/skills/implementation/`
"Landing") says to expect *a* round per visible residual; this is the first
measurement of a residual billed **twice**, and the second answer cost the same
work as the first. §4's earlier reading — two entries, PR #72 and #74 — should now be
read as: the reviewer re-derives from the diff every round, so the cost of a
visible residual is per-round, not per-PR, for as long as the loop runs. That
raises the price of accepting a residual on a *long* review loop specifically,
and it is the strongest argument yet for the "the only thing that reduces the
cost is accepting fewer of them" line, since nothing written in prose reaches
the reviewer at all.
**On dryness:** a round that returns only a restated residual is the loop's
terminal state, not progress — re-tagging again would buy another copy of the
same paragraph. The test worth applying is the one used here — *did this round
name any mechanism the previous round did not?* — and at r4 the answer was no.
**Owner decision 2026-08-12: re-tag anyway**, on the reasoning that the round is
cheap, the docstring commit gives the reviewer new lines, and the branch's other
mechanisms (fingerprint path, collision loser, bounded wait, portal re-mint, the
r3 key guard) have each been read fewer times than the eligibility hop has. The
disposition comment says out loud which finding is settled and which surfaces
are open — worth watching whether steering the reviewer that way changes what
r5 returns, since nothing else in this ledger has tried it.
**One thing the repeat did earn**, and the reason a restated residual is not
pure waste: it pointed at the only delivered artifact that read stronger than
the residual — a test named `test_the_replay_is_indistinguishable_from_the_original`
whose eligibility assertion holds only because the stub is deterministic. Taken
as a docstring scope (`383be97`), assertions untouched, suite unchanged.
**Generalizes: an accepted residual should be audited against the test *names*
on its path, not only the prose that records it** — a test name is a claim, and
it is the claim a reader meets first.

PR #76 r5 — 1 finding: **0 A / 1 B / 0 C**, 0 refuted · **the first B of the
post-baseline era**, and the r4 bet paid: the eligibility residual did not come
back a third time, and steering the reviewer at the branch's unread surfaces
returned a real defect on one of them. The finding is on the path r3's fix
wrote — emptying `REGISTRATION_FINGERPRINT_KEY` in `.env.example` left a
template-seeded stack reporting healthy while every registration answered 503,
because `/healthz` does not exercise the key. Fixed on the branch (`958d46c`),
+8 tests.
**This B does not fit §3.1.** Every baseline B came from *stateful machinery
invented mid-review*; this one came from a two-line change to a guard's
**default**, with no state anywhere near it. The design-gate trigger ("the fix
introduces or alters state") would not have fired on r3's fix and should not
have — routing it to stage 3 would have bought nothing. So §3.1's claim stands
as written about the *baseline*, and this is a second, cheaper B class it does
not cover: **a fix that changes what a guard refuses by default changes what a
default deployment can do, and the blast radius is the boot path, not the code
path.** The tell is available without a design stage — ask "what does a fresh
checkout / template-seeded deploy now do?" — which is one question, not a gate.
**Worth watching** whether that question belongs in the fix session's step 4 as
a checklist item for guard/default changes specifically. One instance is not a
rule; a second B of this shape would make it one.
**Cheaper than the baseline's Bs by a wide margin**: found in one round, fixed
in one commit, no follow-on round attacking the fix — because the fix was a
*copy of a solved shape in this estate* (`.env.redis`'s generate-at-`make up`),
not a new mechanism. That is the second time in this item that the winning move
was "the estate already answered this once, the same way" — r3's own fix cited
`llm_client::_PLACEHOLDER_BEARER_TOKENS` for exactly the same reason. **Generalizes:
before designing a fix for a configuration or guard finding, grep the estate for
the same shape already solved** — it is faster than designing, and it lands a
consistent answer instead of a second convention.

PR #76 r6 — 1 finding: 1 A / 0 B / 0 C, 0 refuted · **[high] A, fixed** (`a04a02b`) — a
`pgdata` volume created before the migration never receives `registration_submissions`
(nothing applies `db/migrations/*.sql`, compose mounts `db/schema.sql` into initdb, which
runs on a fresh volume only), so `_find_registration` catches the missing relation and
every registration answers 503. Confirmed in a scratch container seeded from `main`'s
schema before any decision. **First round of this item to leave the request path** — five
rounds attacked replay semantics, key material and boot wiring; this one attacked *the
database that already exists*. **The r5 lesson repeated and now holds twice**: the estate
had already answered it — `db/schema.sql` is `CREATE TABLE IF NOT EXISTS` throughout, so
the upgrade needed *exposing* (`make schema-apply`), not building, and the reviewer's two
suggestions (migrate inside `make up`; fail startup) were both new mechanism. **The new
lesson is narrower and sharper: verify the obvious answer before recommending it.** The
one-line reply here was "run `make seed`" — the command `docs/runbook.md` advertised for
exactly this case. Running it against a populated database showed it skips the explicit-id
inserts and gives every serial-id table a second copy pointing at the original patients
(`consents` 403→806, `patients` unchanged), i.e. the recommended remedy corrupts the
fixture that teaches D5a. A second, pre-existing defect found only because the disposition
was tested rather than asserted; both are now `docs/debt-log.md` cross-cutting rows.
**Scope note worth keeping**: the finding was true of `main` before this branch existed
(three earlier migrations have the same latent break), and the disposition neither
declined it as out-of-scope nor let it grow into a migration runner — it shipped the
operator path and filed the runner. Class-closing tests over a one-instance integration
test: +24 structural, including the hand-sync parity that reddens if any future migration
and the flattened schema drift.

## 5. How to reproduce

1. `gh pr view <N> --json comments --jq '[.comments[] | select(.author.login=="JesterCharles") | .body]'`
   — real rounds are the ones containing `# Codex Adversarial Review`; the rest are the
   bot's "no new commits" no-ops.
2. Findings are the `- [severity] Title (path:lines)` lines inside the `<details>` block.
3. `gh pr view <N> --json commits` gives the branch's commits in order; the commit
   subjects (`fix(...): … (codex rN)`) map rounds onto commits.
4. Label B by checking whether the flagged mechanism existed in the branch's original
   push — compare symbol occurrences in `git show <first-commit>:<path>` against the
   tip. File existence alone is too coarse: on a feature PR nearly every file lands in
   the first commit, and it is the *mechanism* that post-dates it.
5. Churn: sum `git show --numstat` insertions per non-merge commit, split at the last
   commit of the original push.

## 6. Pre-code gates (append one line per gate stop)

> Added 2026-08-05 at the pipeline-upgrade plan's approval (that plan's §1; OD-3 sited the
> ledger here — same append-only discipline as §4, extended to the gates that stop work
> *before* code exists). The plan itself was superseded 2026-08-06 and deleted 2026-08-09;
> read it at `git show 22e62f8:docs/plans/pipeline-upgrade.md` if the provenance matters.
> **This section outlives it** — the discipline is not tied to that plan's stage vocabulary,
> which is dead (`docs/todo.md`, Dead vocabulary). One line per pre-code gate stop:
> `date · gate · subject · outcome — note`. Outcomes: **passed-unchanged** (the stop changed
> nothing), **amended** (the human changed the artifact), **redirected** (the stage was
> re-run), **aborted** (the work stopped). Dry-run stops carry a `dry-run` tag and are
> excluded from effectiveness counts. The test this section exists to run: a gate whose lines
> are ~all passed-unchanged is a stop on taste and gets removed or merged — the same standard
> §3 applies to the post-code design gate.

**The one entry below is era-1 record, in dead `PG-n` vocabulary** — its subject plan was
superseded 2026-08-06 and deleted 2026-08-09, and no gate named `PG-n` can be reached from `main`.
The stop happened, so the line stays; the next entry here will use whatever the live gate is called
(today: the `.claude/skills/drift-gate/` plan/spec stop).

2026-08-05 · PG-0 · plan:pipeline-upgrade · amended — approved with 3 amendments (a1
riverbend-demo loses all rules after parent rename → rebase-or-retire required; a2 `brief`
dropped from the /dashboard stage enum; a3 dry-run ledger tag); OD-1 track `.claude/` with
exclusions, OD-2 fence rewrite + Lens-4 traceability check, OD-3 ledger sited here.

PR #76 r7 — 2 findings: 1 A / 0 B / 0 C · **[high] the round-6 finding re-raised, and the
first re-raise this item did not answer from the record.** Round 6 accepted the mechanism,
shipped the operator path and declined both enforcement options; round 7 restated it with
the same anchor and the same two remedies, and the owner reversed the health half. Fixed in
`27a05d8`: `/healthz` refuses while any table `Base.metadata` declares is missing, so the
condition presents as an unhealthy container rather than a green one answering 503 to every
registration. **The ledger-worthy part is what the re-raise cost and what it bought.** Cost:
one round. Bought: a fix the disposition-from-the-record path would not have produced —
round 6's reasoning ("a startup guard converts a fixable operational state into a service
that will not boot") was sound about *process exit* and was quietly load-bearing for a
weaker claim, that the signal should stay silent too. The reviewer never distinguished the
two either; the owner did. **Reading for the loop:** the "answer it from the record" rule
(fix-session step 2) is right when the record already weighed the remedy the reviewer names,
and this round is the boundary case — round 6 weighed *both* named remedies and rejected
them, so the rule fired correctly and the owner overruled it anyway, on a narrower option
neither the reviewer nor round 6 had put on the table. That is not a rule failure; it is why
step 2 routes to the owner past round 3 rather than to the fix session. Watch for the
opposite error next: a re-raise answered from a record that only *looks* like it covered the
remedy. **[medium] A, accepted as a residual** — the portal's retry id is lost on remount
(`docs/todo.md` TODO-66). Not patched: the form persists no draft, so persisting the
identifier alone would attach an old attempt to freshly typed content and refuse a genuinely
new registration — worse than the gap — and the complete fix writes PHI to browser storage,
a landmines §1 decision of its own. Second finding this item where the reviewer's stated
remedy rested on a premise (a draft store; a persisted eligibility verdict) the codebase
does not have, which is a cheaper thing to check than to argue: read the premise first, then
the finding. +18 tests; suite 1333 → 1351.

PR #76 r8 — 1 finding: 0 A / 0 B / 0 C, 0 refuted, 1 answered from the record · the remount
residual accepted at r7 (`docs/todo.md` TODO-66), re-raised at the same anchor with the same
remedy and **escalated from [medium] to [high] no-ship** with no new evidence and no change
on that path — `frontend/` is untouched since round 2. Round 7's finding 1 did not return,
so the owner's overrule landed. **The escalation is the entry worth keeping.** This log's
§3.4 records that the reviewer never objects to complexity; this round adds that it also
does not track its own prior severity — the same mechanism, argued the same way, came back
one round later as a merge blocker. Nothing in the loop reconciles the two, so a severity
label is a statement about a round, not about a defect, and a disposition that answers "why
this is accepted" does not lower it. Second measurement of the same shape at r3→r4 (that
one held its severity and was dropped after two restatements). **What it costs and what to
watch:** two of this item's eight rounds have now been spent restating settled residuals,
against one round (r5) where continuing found a real B. The bet is still positive, but the
tell to watch is a re-raise whose *premise* has already been measured absent — here, a draft
store the portal does not have, named in both restatements and in the reviewer's own
suggested test. When a finding's remedy depends on a component that does not exist, checking
the premise is cheaper than arguing the finding, and it is the same check both times.

**Outcome (2026-08-13): PR #76 closed unmerged, owner decision.** A ninth review arrived —
the remount finding a third time, still no-ship — and was never dispositioned; the owner
closed the PR instead and restarted the work as successor item e5b under the current
staged workflow. The scoreboard at close: eight dispositioned rounds, **5 A / 1 B / 0 C**
on code, three of the eight spent restating settled residuals. The close is itself the
entry worth keeping: every surface the reviewer would not let go — the eligibility-replay
contract, the deploy/health story for a new table, the remount/draft lifecycle — was a
question the frozen spec had never decided, so the loop was doing spec work at review
prices (one spec amendment mid-review, D-18, plus a re-gate, plus the restatement rounds).
The successor starts from a spec that pre-encodes those decisions; whether its review loop
shortens is the measurable prediction this section can be checked against.

**PR #78 (the e5 close-record docs PR) r1 — 2026-08-13.** 2 findings, **0 A / 0 B / 0 C /
2 E**, no diff change. Both were improve-suggestions answered with evidence, the W2-r2
shape: (1) a `make seed` refusal guardrail / `schema-apply` target is runtime code, which
the noncode path's scope guard excludes and the routing table sends to the registry — the
filing is in this diff (the seed row's "Fix if taken" clause; the no-runner row naming the
closed branch's mitigation as cherry-pickable), and the owner call (2026-08-13, land
without) queues the cherry-pick as a candidate for the restarted e6 defect batch;
(2) restructuring the debt rows and this ledger into rule-first blocks was declined on the
documents' own contracts — the register's fast-read surface is its Status column and the
new rows match every existing cross-cutting row's shape, while this file is append-only
and compressing its history would rewrite the record it exists to keep; the operator-facing
current rule lives in `docs/runbook.md`, the change the same review called the best here.

**PR #78 r2 — 2026-08-13.** 2 findings + 1 restatement, **2 A / 0 B / 0 C**, both fixed on
the branch: (1) [medium] the runbook's manual psql commands used bare `$DB_USER`/`$DB_NAME`
where the Makefile carries defaults — an operator in a clean shell would connect wrong or
fail; both commands now mirror the Makefile's own `:-riverbend_app`/`:-riverbend` defaults;
(2) [low] "delete the `pgdata` volume" named no command — now the exact reset
(`docker compose down -v`; verified `pgdata` is compose's only named volume, so `-v` is
bounded). The density suggestion is r1's F2 restated and is answered from that record. The
r2 [medium] is the round's lesson: **a runbook command is code that runs in the reader's
shell, not prose** — it inherits none of the Makefile's defaults, so copying a recipe out
of the Makefile into a doc must copy its environment assumptions too.

**PR #78 r3 — 2026-08-13, loop closed by the round-3 rule.** 2 findings, **1 A / 0 B /
0 C**, plus the density suggestion's third consecutive restatement, which engaged the
rule. F1 (the PR summary could read as if seeding were now safe): A, fixed in the PR
description — one explicit line, "documents the foot-guns, does not remove them,
guardrail deferred to the restarted e6 batch". F2 (density, r1-F2/r2-F3 restated with a
concrete variant): **owner disposition 2026-08-13, partial accept** — the two new debt
rows gain a one-line "Operator action today:" lead (they are new rows, no history
rewritten; the runbook stays the deep home), the metrics ledger stays as-is per its
append-only contract, and the full-restructure variant stays declined per the r1/r2
record. Lesson: a reviewer restating a dispositioned style finding converges when the
third round's variant is concrete enough to accept partially — the round-3 rule turned
a stalemate into a bounded improvement, at the cost of the owner's time to decide it.
