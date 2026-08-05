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

PR #25 r3 — 0 findings: verdict **approve**, "No material findings" · **The class fix held.** After
two rounds of runtime failure inferred from static config, the round that followed a real CI runtime
signal produced no findings at all, and the reviewer's own summary now cites the container-start
health smoke as what covers "the riskiest part of a new service". That is the answer to r2's open
question: the class fix worked, and it worked where r1's instance fix (a comment) had not. Recorded
because a single round proves little on its own — the claim to test on the next scaffold-shaped PR is
that *shipping a runtime signal costs one round and removes a class of finding*, not that comments
are useless.

Two advisories appeared in r3's prose but in neither the raw findings block nor the verdict, and both
were checked rather than accepted: "confirm CI actually collects `tests/test_compose_topology.py`" —
it does, proven by delta, `733 passed` on run `30670931154` against `734 passed` on `30675208217`,
moving by exactly the one test added; and "a 500 that returns bytes should fail the smoke" — already
false, since `curl -fsS` exits 22 on any status >= 400. The narrower residual they did not state (200
with a wrong body) is real but unreachable today and is `docs/todo.md` TODO-28, deferred by the user
to P2 PR 2 where `/healthz` grows its first failure branches. **Worth noting for the log's own
sake:** an `approve` verdict still carried two prose claims, one of which was wrong on the flags. The
prose summary is not the findings block, and checking it cost two commands.

PR #25 MERGED — squash `82df049`, 3 rounds, 3 findings total: **1 A / 0 B / 0 C, 2 refuted.** No
fix-round-induced findings on this PR at all, against the 41% B baseline.

PR #26 r1 — 3 findings: **3 A / 0 B / 0 C.** Verdict `needs-attention`, one `[high]` no-ship. Of the
three, one was fixed (gateway `_get` returning downstream 422/503 as 200), one was closed by
**deleting** the flagged code rather than repairing it (the `provider_id` filter, which joined
`slots` through an FK-less column), and one was scoped to tracked debt after a design gate (the
`[high]`: binding `/schedule` to a front-desk permission is D7/RBAC, which `docs/specs/w4.md` §3
explicitly assigns to W9, and a §6 auth zone besides).

**The gate earned its stop on the `[high]`.** The reviewer's recommended fix — a permission check on
one route — is exactly the shape the PR #7 post-mortem in §3 warns about: plausible, bounded-looking,
and stateful. On a system with `default_role: staff` for every account it would have denied nobody,
so the "authorization regression test proving unauthorized sessions cannot read" that the finding
asks for could not have been written to fail. That is a decorative control plus a test that proves
nothing, shipped inside the week whose own spec defers the decision. One design page cost less than
the rounds spent unwinding it would have.

**Also worth logging: one finding was closed by deletion.** Step 4's "can it be closed by deleting?"
question is easy to skip because it feels like a non-answer. Here it was the whole answer — the
alternative fixes were a brittle free-text name match or a migration, and no consumer of the
parameter existed. Net diff for that cluster is negative.

**And the round's most serious defect came from the pre-push adversarial pass, not the bot:** the
day queue filtered on `scheduled_for`, which the booking UI never populates, so it returned nothing
but seeded rows in production — right in dev, empty in prod.

**And one prose/findings-block divergence, the same class as r3 on PR #25:** the summary said the
route is "broader than the old `/appointments` path, which at least required a caller-supplied
`patient_id`". True but not the point — `patient_id` there was a query shape, never an authz control,
and `GET /records/search?q=` already returns cross-patient *clinical notes* on `require_session`
alone. The novelty claim does not survive contact with CLAUDE.md §6, which already names all of them
as one class. The underlying finding is still correct; only its framing as a new trust boundary is
not. Second round in a row where checking the prose against the repo changed the disposition.

PR #26 r2 — 2 findings: 2 A / 0 B / 0 C · **[high]** cross-patient PHI on session-only auth —
**verbatim repeat of r1's finding**, re-scoped, no code. Not labelled C: C is "an earlier round
tried to fix it and did not close it", and this was never attempted — it was scoped out at a design
gate with human approval. **[medium] A, fixed** — the day query filtered on time only, so a
cancelled visit still rendered in the front-desk arriving queue with name, MRN and reason. Closed
with an exclusion predicate (`FE-R34`), never an allowlist: `appointments.status` is free TEXT with
no CHECK, so `IN ('confirmed','completed')` would silently drop any status added later — the same
silent-drop class as the FK-less inner join r1 removed from this very query.

**Zero B/C for the second round running on this PR, and the reason is visible in the process.** The
pre-push pass returned 4 findings, 3 of them defects in code *this round had just written* — an
overclaiming comment ("the two literals cannot drift"; the constant reaches 1 of 4 producers of that
column), a drift test that pinned writer↔constant instead of writer↔reader, and a second test whose
assertions restated the first's while banning an equivalent refactor. Those are textbook B-class
findings, caught before the push instead of arriving as r3. A mutation the pass provoked also
falsified a claim in one of the round's own new docstrings (the "survives an equivalent `notin_`
refactor" test did not, because SQLAlchemy binds an `IN` list as one parameter rather than as
scalars). The pass's own top finding was checked and partly wrong — it asserted booking marks
`slots.status = 'booked'`; nothing in the repo writes that column at all — which is the second time
in three rounds that checking a reviewer's prose against the tree changed the disposition. Parked
accurately as TODO-35 rather than as filed.

PR #26 r3 — 2 findings: 2 A / 0 B / 0 C · **[critical]** `GET /schedule` reachable unauthenticated
on host port 8074 — true, and a pre-existing six-service *class* (every domain service published,
none with auth), not created by this PR. Answered with the sequencing reply
(issuecomment-5160702865): class fix landed as PR #27 / ADR 0016 / D15 (unpublish 8071–8076,
closed allowlist). **[high]** no `schedule.read` enforcement — third round for this finding; the
first two scoped it out because a capability check on a single-`staff`-role system denies nobody
and its negative test cannot be written to fail. PR #28 / ADR 0017 landed the role machinery from
main (with the §6 approval carried on that PR's review), which made the 403 test writable — closed
on this branch after the main merge: `require_capability("schedule.read")` on the route, the
roi_clerk 403 param, and the wiring pin. The finding was right in the end because the system
changed underneath it, not because the earlier scoping was wrong.

PR #26 r4 — 1 finding: restatement, 0 new · the 8074 finding again as no-ship, plus an ask for a
direct-access rejection test. Satisfied by PR #27's topology tests (no `ports:` key + the
loopback-spelling class guard), not by new work on this branch. Recorded as a restatement per the
PR #28 r2 convention: it measures the bot's statelessness, not our defect rate.

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

PR #26 r5 — 1 finding: 1 B (first on this PR) · **[high] fixed** — r3 gated `GET /schedule` with
`schedule.read`, which ADR 0017 grants to clinicians, so any clinician session could pull the
all-patient day queue (name, MRN, provider, reason). Capability split per the reviewer's shape
after a design gate + §6 approval: `schedule.day_queue.read` (front_desk/admin/staff), clinician
keeps `schedule.read` for `/slots` + per-patient `/appointments`. Labelled B, arguably softly: the
clinician grant itself is ADR 0017's (main), but r3 chose the capability that made the combination
effective on this route. Pre-push pass (general-purpose + pack, both lenses merged per the
small-diff rule): 47k tokens, 2 tool calls, **0 orientation greps**, 0 code defects, 2 doc findings
(stale CLAUDE.md §6 capability name; the split-is-conditional-on-role-migration caveat) — and it
verified test discrimination against 4 mutations. Round also drove the real stack: rebuilt images,
role-corrected demo users, and observed clinician 403 / front_desk 200 / anonymous 401 first-hand —
which caught nothing the suite missed but converted two inferences into observations, including one
gate claim that was wrong (the 5th deselected test is PR #28's records-flow addition, not a
day-queue integration test as first asserted).

PR #26 r6 — 1 finding: 1 A · **[medium] fixed** — day filter on
`COALESCE(scheduled_for, slots.start_at)` across an outer join: unindexable, so every
`GET /schedule` seq-scanned appointments (shape shipped in the original push `43dbbc4`).
Design-gated (fix = migration, §6): reviewer's persisted-`visit_at`-column shape rejected as
mid-review stateful machinery touching the RIV-175 booking surface; approved shape was the
stateless UNION ALL rewrite + index-only migration 009 (ADR 0018). Proof: EXPLAIN ANALYZE on 66k
synthetic rows, 21.4 ms seq-scan → 0.79 ms all-index with identical membership; live gateway check
identical to old shape on seed data. Pre-push pass (general-purpose + pack): 58k tokens, 9 calls,
**0 orientation greps**, 4 findings — 2 medium test-gaps both real and instructive: the isouter
mutation on the membership join and the status-into-slot-branch mutation each survived the round's
6 advertised mutation-proofs, i.e. the pass found holes in the mutation matrix itself, not the
code. Both closed with mutation-proven assertions; 1 low migration lock note fixed; 1 partial-index
suggestion declined (priced in ADR 0018 tradeoff 1). Fix commit `f7864e1`.

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
