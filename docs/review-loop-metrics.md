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
