---
name: verify-stack
description: Run this repo's full verification ritual before any push - unit suite in a python:3.12 container (local Python is 3.8 and cannot run the suite), per-service import smoke, compose config validation, the regression-proof procedure for new tests, and a pre-push adversarial diff review that front-loads what the @codex-review bot would catch. Use before pushing code changes or when the user asks to verify.
---

# Verify the Riverbend stack

Local dev Python is 3.8; services run 3.12 in Docker. The repo's test suite
does not run on 3.8 at all (pre-existing). Everything below mirrors CI.

## 1. Unit suite (CI mirror)

```bash
make test-docker
```

Uses the `Dockerfile.test` image with the dev deps baked in, so pip does not
re-resolve them per run (20.5s → 12s; a no-change rebuild is ~0.6s, and editing
`requirements-dev.txt` reinstalls automatically). The bare
`docker run ... python:3.12 bash -c "pip install -q -r requirements-dev.txt && pytest"`
form still works and is what CI does — prefer the target.

**While iterating, prefer the local `.venv` (~2s)** — `.venv/bin/python -m pytest
tests/test_intake_breaker.py -q` — or a targeted container run,
`make test-docker ARGS="tests/test_intake_breaker.py -q"` (~4s). The container is
the authoritative gate (arm64 vs CI's amd64), so any "verified" claim comes from
it; iteration does not need it. A 2026-07-26 audit measured 25 full-suite
container runs against 14 pushes (~1.8/push — near the floor, since regression-proof
needs ≥2 per new test) but only 2 `.venv` runs against 45 targeted container runs:
the fast loop is the underused part, not the gate.

**Invariant: exactly 1 xfailed, 0 failed, and the pinned deselected count.**
The xfail is the IDOR test — it staying xfail is correct; it flipping to XPASS
means someone changed auth behavior (§6 zone) — stop and flag, never adjust the
test. Deselected counts the `integration`-marked tests under `tests/integration/`:
a maintained number, not a frozen one, but it moves only when a human moves it —
so a *change* in it is a stop-and-report unless you are the one who added or
removed an integration test. Any `failed` is a stop-and-report too.

**The numbers live in exactly one place: `EXPECT_XFAILED` / `EXPECT_DESELECTED` /
`EXPECT_FAILED` at the top of `.claude/hooks/xfail-invariant.sh`** — deliberately
not restated here (§10.1). Restating them is what let the deselected count sit
wrong in this file for a whole PR. Read the hook for the current values; a
deliberate change edits the constant in that file and nothing else.

The pass total is *not* an invariant — it grows as tests are added (50 on
2026-07-07, 261 by PR #11 / 2026-07-23, 811 on 2026-08-02). Compare it against
the last known count on your branch; a *drop* is a stop-and-report.

**Enforced since 2026-08-02** by that hook, a `PreToolUse(Bash)` matcher on
`git push`: it runs this suite (13.7s warm — it runs rather than parsing a cached
transcript, because a stale green cannot speak for the tree being pushed) and
denies the push on any deviation, naming the parsed counters in the denial. The
XPASS denial says *auth behavior changed — stop and investigate, do not adjust
the test*, and means exactly that. `ALLOW_UNVERIFIED_PUSH=1` is the escape hatch
for when the suite genuinely cannot run (Docker down), same doctrine as the
pre-commit guard's `ALLOW_IGNORE_DELETE=1` — never to get past a red suite.
Golden test: `bash .claude/hooks/test/test-xfail-invariant.sh` (fixture-driven,
never starts Docker).

## 2. Import smoke (per touched service)

CI runs `python -c "import app"` per service with that service's requirements:

```bash
docker run --rm -v "$PWD":/repo -w /repo/services/<service> python:3.12 \
  bash -c "pip install -q --disable-pip-version-check --root-user-action=ignore \
             -r requirements.txt && python -c 'import app'"
```

Per-service deps differ, so there is no baked image for this one; the extra pip
flags only suppress the root/version notices that otherwise land in context on
every run. (A shared pip-cache volume was measured and rejected: 8.7s → 7.6s.)

Run for every service whose files the diff touches. ai-assistant imports
keyless by design — needing `ANTHROPIC_API_KEY` at import time is a regression.

## 3. Compose + build

```bash
make config                          # validates docker-compose.yml
docker compose build <service>       # only if a Dockerfile/requirements changed
```

## 4. Regression-proof any NEW test

A new test must be shown to fail against pre-fix code, then pass with it.
Report the red/green pair per layer explicitly. "Test passes" alone is not
verification here.

**Division of labor.** The main thread — you, per this section — defines what
"proof" means for the PR: which refs, which files revert to them, which
targeted tests run, and the exact red count each layer must produce. The
`regression-proof` workflow (`.claude/workflows/regression-proof.js`) only
*executes* that definition: one Haiku worktree agent per layer, in parallel,
each reverting/mutating and counting reds in the container. Gathering the
refs/files/tests/expected-reds is the judgment work and never delegates.

**Default path — the workflow:**

1. **Commit the round's work first.** Worktrees materialize the
   **default-branch tip**, not the session branch — committed-but-unpushed
   work is invisible at start. Unpushed commits ARE reachable via the shared
   object store, so branch state is recovered per layer via ordered
   `git checkout <branch-ref> -- <files>` (see step 3).
2. Build the test image once from the main checkout:
   `docker build -q -t riverbend-test:py312 -f Dockerfile.test .`
   Parallel-safe (verified 2026-08-05): `Dockerfile.test` bakes only
   requirements-dev.txt and bind-mounts the repo, so each agent's
   `make test-docker` build is a cache no-op on the shared tag.
3. Invoke the Workflow tool with
   `scriptPath: .claude/workflows/regression-proof.js` and args
   `{ layers: [ { layer, reverts: [{ref, files: […]}] | mutation: "<exact
   file+line edit>", tests: "<pytest args>", expected_red: N }, … ] }` —
   layer meanings below. **Lead each layer's `reverts` with branch-state
   materialization** — ordered `git checkout <branch-ref> -- <files>` entries
   that recover the session branch on top of the default-tip worktree, then
   the layer's own revert/mutation. Expected reds are **measured, not
   guessed**: measure them in that exact shape (worktree from default tip +
   ordered checkouts + container), the same way the agents will (targeted
   `make test-docker` runs), e.g. in a throwaway worktree under `Riverbend/`.
   This ordering is what turned run wf_be5272d0 FAIL → PASS on 2026-08-05.
4. The workflow returns a per-layer verdict table, comparison done in plain JS
   in the script (no judgment agent). **Any layer whose actual red count
   differs from expected is a hard fail of the whole proof** — no partial
   credit. Fix the test or re-measure honestly; never tune expected_red to
   whatever came back.
5. **Cleanup:** changed worktrees are not auto-removed. They land at
   `.claude/worktrees/wf_<runid>-N`, each on a throwaway branch
   `worktree-wf_…`. `git worktree remove --force` each, `git branch -D` its
   branch, confirm with `git worktree list`.

Worktrees hold tracked files only — no CLAUDE.md, no `.claude/` (by design,
post-descope). The layer agents are mechanical and their prompts are
self-contained, so nothing gets copied in. A proof that needs local tooling
the worktree lacks is a case for the manual fallback below, not a setup step.

**Manual fallback** — when the repo state is too dirty to commit cleanly, or
the proof needs tooling worktrees lack:

```bash
git stash push -- <implementation files>   # keep the test in the tree
# rerun the new test -> MUST FAIL
git stash pop
# rerun -> MUST PASS
```

### What the layers mean (applies to both paths)

**A whole-file stash proves less than it looks like once a round layers several
fixes into one file** (measured on PR #14 r4). Stashing `app.py` reverts to
`origin/main`, so a test can fail for a reason that has nothing to do with the
fix it guards — or, worse, *pass*, because the behaviour it asserts also held
before the feature that broke it existed. Two of that round's six tests were in
that position. Where a fix is one line or one hunk, **restore that line
specifically** (copy the file aside, edit it back to the pre-fix form, run the
targeted test, restore the copy) and report the per-fix red/green pair. The
useful question is not "does this test need the file" but "does this test
discriminate the fix".

**Two layers, once the adversarial pass finds defects in your own fix.** From
PR #14 r6 on: layer A reverts to the branch tip (proves the tests need the
round's work at all), layer B reverts **your own first cut** — the version you
had before the pre-push pass — leaving the second-cut changes out. Only layer B
pins what that pass found, and it is the layer that catches a "fix" whose test
would have passed against the flawed first attempt. Where the change is a
declared bound rather than a branch, neither layer discriminates it: widen the
bound (mutation) and confirm the at-limit case fails. On r6, layer A red 15/16,
layer B red 8, and the mutation red 2 — three different questions, three
different runs.

A test that stays green in *every* layer is not a safety net, it is decoration:
delete it, or make it discriminate. One did on r6 and was deleted.

## 5. PHI/security diffs: dynamic check

For anything touching a log path or redaction: `make up`, drive the real flow
(e.g. `POST /intake` via gateway 8070 with PHI planted in a NON-PHI field like
`consents`), then read the actual log output and confirm `[REDACTED]`
everywhere. Static tests missed the consents leak once already (PR #2 lesson).

## 6. Adversarial diff review (before the approval gate)

Front-load what the `@codex-review` bot would catch, so review rounds shrink
(added 2026-07-23; rationale rewritten 2026-07-25).

**Why this is a separate agent and not a self-check.** The original rationale
said a self-review would have caught PR #11's early rounds. That premise no
longer holds — the working model self-verifies without being asked, and it still
missed three real defects in r5 that an independent reviewer found (a coverage
verdict keyed on a downstream `status` string, a 4xx tripping the shared
breaker, a half-open wedge in `check.py`). The value here is **blind-spot
isolation**, not a second opinion: a reviewer that never saw the reasoning which
produced the diff cannot inherit that reasoning's assumptions. Re-reading your
own diff, however carefully, can.

This matters because Anthropic's Opus 5 guidance says to delete verification
scaffolding written for earlier models ("include a final verification step",
"use a subagent to verify") — it causes over-verification. **That guidance does
not apply to this ritual.** Steps 1–5 are deterministic evidence (a real test
run, a real import, a real log scan), not model self-checking, and step 6 is
adversarial *discovery*, not re-confirmation of work already done. Don't delete
any of it by pattern-matching on the word "verify."

**When:** any diff touching logic, a response/API contract, concurrency, a
timeout/retry budget, or a flow that spans layers (frontend BFF → gateway →
service). Skip for pure docs/comments/config-value-only diffs, and for
test-only diffs — step 4's stash-proof is deterministic evidence that the test
discriminates, which is the whole claim a test-only diff makes.

**How:** spawn the **`diff-reviewer`** agent (`.claude/agents/diff-reviewer.md`)
on the branch diff (`git diff origin/main...`). It assembles its own briefing
pack (spec below) and attacks like the adversarial bot — NOT a rehash of
`/security-review` (that covers PHI/security separately). The lens list — this
text is the authoritative review spec, which the agent reads at spawn (§10.1:
one source of truth; the agent file holds only procedure and format):
- **Correctness / edge paths** — error branches, non-2xx/malformed responses,
  empty/None inputs, off-by-one, the unhappy path.
- **Contract / back-compat** — does a changed field break a caller that reads the
  old shape? Is a sentinel (`False`, `""`, `0`) ambiguous with "unknown"? Additive
  vs breaking?
- **Cross-layer** — is the same symptom/scaffold (a delay, a timeout, a retry,
  a magic number) duplicated in another layer that this diff didn't touch? Grep
  the mechanism across `frontend/`, `services/gateway/`, and the service
  ([[trace-symptom-across-all-layers]]).
- **Concurrency** — shared state under FastAPI's threadpool, check-then-act,
  breaker/lock races.
- **Budgets/limits** — do nested timeout/retry budgets compose (inner < outer)?

**One `diff-reviewer` pass. Cap at one — do not fan out.** The working
model reaches for subagents readily; a second reviewer on the same diff is
duplicated cost, not coverage. A pass that dies mid-run (the r6 first attempt
returned "Agent terminated early due to an API error") yields **nothing** — its
partial output is not a review. Re-run it; that is a retry, not a fan-out.
(Before 2026-08-02 this step was a `general-purpose` agent fed a hand-assembled
pack; `diff-reviewer` replaced it — same standards, pack assembled by the agent.)

**Check the review's `Files read:` header before trusting it.** The agent's
output opens with the list of files it actually read; a review missing the
verbatim diff, the call-site reads, or the new tests skipped its own pack —
discard it and re-run.

Do **not** use `cavecrew-reviewer` here (dropped 2026-07-25). Its contract is
one line per finding — `path:line: severity: problem. fix.` — which is a
reasoning constraint, not a formatting one: the defects this step exists to
catch need a multi-step failure trace across services, and a reviewer built
around one-line output searches for the class of defect that fits one line. On
the r5 diff it returned 0 defects for 78k tokens while the `general-purpose`
pass found all of them, and its findings skewed toward out-of-scope nits (a
`float(os.getenv(...))` note applying to every setting in the repo) — pressure
in the wrong direction, given this model already over-expands scope. Its
compressed-output tradeoff also buys nothing here: context sits near 20% of a
1M window. It stays in the roster for ad-hoc "review my working diff" during
development; it is not a pre-push gate.

Ask it to say plainly when a section is sound — an agent that must produce
findings will invent them.

### The briefing pack (the spec of what the agent must gather before judging)

A subagent starts from an empty context: it inherits none of this thread's
conversation and none of the files already read here. Since 2026-08-02 the
`diff-reviewer` agent assembles the pack itself as its first phase — the main
thread no longer hand-builds it — but the spec of what the pack contains lives
here, and the agent file points at this section rather than duplicating it.

Separate the two things that get conflated here:

- **The value is independent judgment** — a reviewer that never saw the reasoning
  which produced the diff cannot inherit that reasoning's assumptions.
- **The cost is independent cartography** — the reviewer not knowing where
  anything is. The pack phase bounds that cost: gather everything first, judge
  second, no unbounded exploration interleaved with opinion-forming
  ([[session-length-dominates-token-cost]]).

The spawn prompt hands the agent the branch name and nothing else. **Facts, not
verdicts** — verdicts are what contaminate isolation; a call-site map does not,
and the agent builds its own.

The pack, gathered in full before any opinion is formed:

- the full `git diff origin/main...` output, inline and verbatim
- the inventory of touched files
- a call-site map: who calls each changed function, as `file:line`
- contract facts: what the changed code returns on each branch, and what its
  callers do with each of those returns
- the tests that already cover this surface, by name

Deliberately excluded — the spawn prompt must never contain: why the design was
chosen, what was considered and rejected, and any "I already checked X, it's
fine." Those are the assumptions the pass exists to test.

Then constrain the search, not the reasoning (the agent file encodes these):

- **No orientation greps.** The pack the agent built is its authoritative
  geography; after the pack phase, a file may be read only to test a *named*
  failure hypothesis — hypothesis first, then the read. This converts an
  unbounded sweep into targeted tracing.
- **Cap the number of findings, never their length.** Top findings by severity,
  each with a full multi-step failure trace. The dropped `cavecrew-reviewer`
  failed because one-line output is a reasoning constraint in disguise (see
  above); a count cap is not.
- **One pack, whichever lenses run.** This step and `/security-review` need the
  same geography and differ only in lens, so the discovery cost should be paid
  once. If the diff is small (≲3 files in a single service), one agent carrying
  both trigger lists is fine — one prelude, one exploration, two lenses. Keep
  them separate above that size.

### When the security lens is worth its own pass

**Not every round.** The two lenses overlap heavily *in this repo*, because the
security surface here largely IS the correctness surface — PHI handling is data-
flow correctness, and the adversarial pass traces data flow anyway. Measured
twice now (see the table below): on PR #14 the security pass has produced **zero
unique findings across two runs**, and on the pre-push pass for `84117fd` its
top candidate turned out to be the adversarial pass's ship-blocker seen from
another angle. Meanwhile the adversarial pass's `re.IGNORECASE` Unicode finding
in round 3 was, in substance, a PHI/patient-safety finding — the security-shaped
defect was caught by the correctness lens, unprompted.

So run `/security-review` when the diff opens a **new surface**, not when it
changes behaviour on an existing one. New surface means any of:

- a new **egress** (a new outbound call, a new destination, a new field added to
  an existing outbound payload);
- a new **persistence sink**, or a new field written to an existing one;
- a new **auth/authz decision point**, or a change to an existing one;
- a new **externally reachable route**, or a route changing its auth posture;
- a new **parser of untrusted input**, or a new credential/secret path.

PR #14 rounds 1–2 hit several of these (Redis credentials, a public `/healthz`
doing I/O, two new endpoints) and the pass was justified. Round 3 hit none — it
changed control flow, a regex flag, and two response fields on surfaces that
already existed — and returned zero, predictably. When you skip it, **say so in
the approval gate and name which trigger was absent**, so skipping stays a
judgement on record rather than a quiet omission.

CLAUDE.md §5's "run it on auth/PHI/ROI diffs before a PR" still holds for
**opening** a PR. This rule is about the per-round loop after that.

### ⚠ `/security-review` builds its diff from COMMITTED state only

Its `DIFF CONTENT` is `origin/main...HEAD`. Working-tree changes are **absent
from the diff it hands the reviewer**, even though the `GIT STATUS` block it
prints lists them as modified — which reads as if they were included. Verified
on PR #14 round 3: the artifact ended at the branch tip and contained zero
occurrences of `llm_egress`, `re.ASCII`, or `_assistant_health`, i.e. none of
the round's actual work. The pass came back clean on code it had never seen. It
was saved only by the reviewer independently noticing the mismatch and reading
the working tree instead — luck, not design.

`/security-review` is a built-in command, so this cannot be fixed in-repo.
**Commit first, then invoke it.** If you must run it on uncommitted work, state
in the sub-agent prompt that the artifact is stale and that the working tree is
authoritative.

**Cost:** read it from the harness after each run — `/usage`, or the token
total in the agent's completion notification — and judge it there; the
hand-appended per-run table that used to live here was retired 2026-08-02 (its
nine rows, PR #14 r2–r7 plus the cavecrew baselines, live in this file's git
history). Expected band on a ~35KB diff: 70–130k, and the number to watch is
the *orientation-call count* (target: 0), since it does not drift with diff
size. Subagent transcripts do not appear in
`~/.claude/projects/<project>/*.jsonl` (no `isSidechain` rows), so the harness
report is the only source.

Two conclusions that measured history settled — do not re-litigate them:

**`cavecrew-reviewer` is retired here for good.** Two runs, two zeros — the
second with the same briefing pack the `general-purpose` run had, on the same
diff, so the pack is not what separates them. It cost 30k to conclude "diff
is sound" about code containing a refund path that would have let a rotated
Bedrock key escape the tenant spend ceiling. Cheap and wrong is the worst cell
in the matrix; do not re-litigate this on the grounds that it is cheap.

**The adversarial pass earns its cost every round; the security pass has not
yet earned a separate one.** PR #14 r3's two highs were both in code the main
thread had just written and self-reviewed — one of them a fix that was wrong in
the unsafe direction, which is exactly the blind spot an isolated reviewer
exists to catch and exactly what self-review cannot. Keep it every round. Gate
the security lens on the new-surface rule above.

**A round-5 addition: point the pass at the fix's own tests, not only its code.**
On a ~4KB diff the pass cost 66k for 8 calls and its highest-value finding was
in the *test*, not the implementation — the new invariant test computed its
expected value from the production predicate, so it was an identity and would
have survived a mutation that deleted the whole model-selection step. Self-review
does not catch that: the same reasoning that wrote the predicate writes the
expectation. Include the new tests verbatim in the pack and name "does each new
assertion discriminate the fix, or restate it?" as a lens. Step 4's stash-proof
answers this for a *missing* implementation, not for an expectation derived from
the implementation that is present.

The pack run read 9 files in 12 calls with **zero** orientation greps — the
budget went into tracing rather than searching, and it found a class of defect
self-review had not: a per-operation timeout being reasoned about as if it were
a per-probe timeout. Cost is roughly flat versus the no-pack baseline; what
changed is what the tokens bought.

**A round-7 addition: the fix's own change of policy is a defect class, and it is
the one self-review is worst at.** Round 7 replaced a fail-open Redis lock with a
fail-closed one, and the pass's top finding was a regression the fix had
introduced rather than anything the review round had asked about: the old
fail-open path returned the token it had just sent, so the route's
compare-and-delete cleaned up whenever the write had actually landed, and raising
instead of returning discarded that token. The fault the fix reasoned about
(`maxmemory` + `noeviction`, where the write does not land) was real but was not
the only one — a reset connection or a failover can leave the write **applied**
with its reply lost, and then the orphaned lock wedged the resource for its whole
TTL. Two lenses worth naming in the pack from now on:

- **"What did the code you replaced do that yours no longer does?"** A behaviour
  change is not only what it adds. This one deleted a cleanup path nobody had
  written down as a feature.
- **"Enumerate the fault, don't pick one."** A store fault has several shapes
  (write refused, write applied and reply lost, read-only, credential rejected),
  and a fix justified against one of them silently assumes the others behave the
  same. The tests inherit that assumption: this round's first cut injected a fault
  that *failed* the write, so no test could see the applied-then-lost case.

The cost was 127k over 19 calls, roughly double the r2–r6 band, on a ~30KB diff
that included 8 changed test files. Still zero orientation greps. The extra spend
went into the pass verifying its own claims by running the suite against probe
fakes it wrote — which is what made the top finding arrive as a reproduction
rather than a hypothesis, and is worth the money on a diff that changes a
concurrency policy.

Triage findings, fix the real ones **with regression-proven tests** (step 4),
re-run the suite, then present the approval gate.

## Report format

State: suite counts + the xfail/deselected invariant, which import smokes ran,
compose result, regression-proof pass/fail pairs, the dynamic check result if
applicable, and the adversarial-review findings + their disposition. Any
`failed`, a pass-count drop, or an XPASS is a stop-and-report, not a footnote.
