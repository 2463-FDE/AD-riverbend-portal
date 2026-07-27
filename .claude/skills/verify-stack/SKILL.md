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

Invariant (not a fixed count — the pass total grows as tests are added; it was
50 on 2026-07-07, 261 by PR #11 / 2026-07-23): **exactly 1 xfailed + 4 deselected,
0 failed.** The xfail is the IDOR test — it staying xfail is correct; it flipping
to XPASS means someone changed auth behavior (§6 zone) — stop and flag. Compare
the pass count against the last known count on your branch, not a frozen number;
a *drop* or any `failed` is a stop-and-report.

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

A new test must be shown to fail against pre-fix code:

```bash
git stash push -- <implementation files>   # keep the test in the tree
# rerun the new test -> MUST FAIL
git stash pop
# rerun -> MUST PASS
```

Report both results explicitly. "Test passes" alone is not verification here.

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

**How:** spawn a reviewer agent on the branch diff (`git diff origin/main...`),
prompted to attack like the adversarial bot — NOT a rehash of `/security-review`
(that covers PHI/security separately). Cover:
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

**Agent: one `general-purpose` pass. Cap at one — do not fan out.** The working
model reaches for subagents readily; a second reviewer on the same diff is
duplicated cost, not coverage.

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

### The briefing pack (how to keep this pass cheap without weakening it)

A subagent starts from an empty context: it inherits none of this thread's
conversation and none of the files already read here. It does inherit the fixed
prelude (system prompt, tool schemas, and the ~20KB CLAUDE.md chain, re-paid per
spawn). The prelude is the small, one-time part. The expensive part is
*rediscovery* — a reviewer groping for where things live runs many read/grep
turns, and each turn re-pays its whole accumulated context as cache read
([[session-length-dominates-token-cost]]).

Separate the two things that get conflated here:

- **The value is independent judgment** — a reviewer that never saw the reasoning
  which produced the diff cannot inherit that reasoning's assumptions.
- **The cost is independent cartography** — the reviewer not knowing where
  anything is.

Only the second is worth cutting. So hand the agent the geography and the raw
facts, and withhold every conclusion. **Facts, not verdicts.** Verdicts are what
contaminate isolation; a call-site map does not.

Assemble the pack from what this thread already holds (so it costs output tokens
once, not a multiplied read loop in the agent):

- the full `git diff origin/main...` output, inline and verbatim
- the inventory of touched files
- a call-site map: who calls each changed function, as `file:line`
- contract facts: what the changed code returns on each branch, and what its
  callers do with each of those returns
- the tests that already cover this surface, by name

Deliberately excluded: why the design was chosen, what was considered and
rejected, and any "I already checked X, it's fine." Those are the assumptions
the pass exists to test.

Then constrain the search, not the reasoning:

- **No orientation greps.** State in the prompt that the geography in the pack is
  authoritative, and that a file may be read only to test a *named* failure
  hypothesis — hypothesis first, then the read. This converts an unbounded sweep
  into targeted tracing.
- **Cap the number of findings, never their length.** Ask for the top findings by
  severity, each with a full multi-step failure trace. The dropped
  `cavecrew-reviewer` failed because one-line output is a reasoning constraint in
  disguise (see above); a count cap is not.
- **Build the pack once, feed it to whichever lenses run.** This step and
  `/security-review` need the same geography and differ only in lens, so the
  discovery cost should be paid once. If the diff is small (≲3 files in a single
  service), a single agent carrying both trigger lists is fine — one prelude, one
  exploration, two lenses. Keep them separate above that size.

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

**Record the cost.** After the pass, note the agent's token total and its
findings count here, the way the 78k/0-findings `cavecrew-reviewer` figure above
was recorded — that number is what retires an approach. Subagent transcripts do
not appear in `~/.claude/projects/<project>/*.jsonl` (no `isSidechain` rows), so
take the number from the run's own reporting, not from log archaeology.

Measurements so far:

| run | agent | cost | tool calls | findings |
|-----|-------|------|-----------|----------|
| PR #14 r5 diff (2026-07-25) | `cavecrew-reviewer`, no pack | 78k | — | 0 (all real ones missed) |
| PR #14 r2 fixes (2026-07-27) | `general-purpose` + briefing pack | 72k | 12 | 6, all real, all fixed |
| PR #14 r3 fixes (2026-07-27) | `cavecrew-reviewer` + briefing pack | 30k | 1 | **0** — missed both highs below |
| PR #14 r3 fixes (2026-07-27) | `general-purpose` + briefing pack | 105k | 13 | 4 (2 high), all real, all fixed |
| PR #14 r3 security lens (2026-07-27) | `/security-review` + pack | 153k | 27 | 0 |

Two things that table settles.

**`cavecrew-reviewer` is retired here for good.** Second run, second zero — and
this time it had the same briefing pack the `general-purpose` run had, on the
same diff, so the pack is not what separates them. It cost 30k to conclude "diff
is sound" about code containing a refund path that would have let a rotated
Bedrock key escape the tenant spend ceiling. Cheap and wrong is the worst cell
in the matrix; do not re-litigate this on the grounds that it is cheap.

**The adversarial pass earns its 105k; the security pass has not yet earned
its 153k.** Round 3's two highs were both in code the main thread had just
written and self-reviewed — one of them a fix that was wrong in the unsafe
direction, which is exactly the blind spot an isolated reviewer exists to catch
and exactly what self-review cannot. Keep it every round. Gate the security lens
on the new-surface rule above.

The pack run read 9 files in 12 calls with **zero** orientation greps — the
budget went into tracing rather than searching, and it found a class of defect
self-review had not: a per-operation timeout being reasoned about as if it were
a per-probe timeout. Cost is roughly flat versus the no-pack baseline; what
changed is what the tokens bought. Treat 70–80k as the expected price of this
step on a ~35KB diff, and the *orientation-call count* (target: 0) as the number
to watch, since it does not drift with diff size.

Triage findings, fix the real ones **with regression-proven tests** (step 4),
re-run the suite, then present the approval gate.

## Report format

State: suite counts + the xfail/deselected invariant, which import smokes ran,
compose result, regression-proof pass/fail pairs, the dynamic check result if
applicable, and the adversarial-review findings + their disposition. Any
`failed`, a pass-count drop, or an XPASS is a stop-and-report, not a footnote.
