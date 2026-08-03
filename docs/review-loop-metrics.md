# Review-loop metrics

> Why the `address-review` skill has a clustering step and a design gate, and how we
> tell whether they are working. Baseline measured 2026-07-28 over every code PR merged
> to that date. **Do not re-derive this from scratch** — append to it (§4).

## 1. What is measured

Every automated-review finding gets one label at triage time (`address-review` §2):

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
   That is why `address-review` §2's design-gate trigger is *"the fix introduces or
   alters state"* rather than a judgement call about size.
2. **PR #7 is the worst case and the clearest one.** r6 was a legitimate A finding —
   the paid AI endpoint genuinely had no aggregate abuse control. The fix invented a
   budget/refund/single-flight subsystem (`services/gateway/security.py` 67 → 364
   lines) mid-review, with no design step, and r7–r14 were spent making that
   subsystem correct. Eleven of that PR's findings never existed until we wrote them.
3. **C is a different failure with a different cure.** PR #2's budget-egress defect
   survived four fixes because each fix addressed the instance in front of it. The
   cure is the class sweep (`address-review` §4), not the design gate.
4. **The reviewer never objects to complexity — 0 findings out of 64.** Nothing
   external will flag machinery growth. If complexity is to be justified, the
   justification has to come from our own spec (requirement IDs) and from §3's
   cheapest-fix line.

## 4. Ongoing log (append one line per round)

Format: `PR #N r<k> — <count> findings: <labels> · <one-line note>`.
The ledger also goes in the PR reply (`address-review` §6) so it survives independently
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
precondition of any reassignment; root cause is D10 (no session TTL, CLAUDE.md §9), out of this PR's
scope and §6-gated. Reviewer's own summary concedes "the ADR text acknowledges this."

PR #28 r2 — 2 findings: same two as r1, restated verbatim (same anchors, same recommendations);
0 new. The bot reviews the branch diff only and the RBAC diff was unchanged (r1 pushed only the
main merge + this ledger), so a further tag on an unchanged diff reproduces the round — loop
recognized and cut: dispositions stand as r1 recorded, no re-tag, merge proceeds on the human
§6 approval this PR's review was designated to carry (ADR 0017 context; gate table in
`docs/specs/rbac.md` §6). Method note: a scoped-out finding restated on an unchanged diff is
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
