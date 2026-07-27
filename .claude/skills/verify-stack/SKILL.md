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
service). Skip for pure docs/comments/config-value-only diffs.

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

Give the agent the diff, the trigger list above, and enough context to trace a
failure end-to-end (what the service under test returns, and what its callers
do with it). Ask it to say plainly when a section is sound — an agent that must
produce findings will invent them.

Triage findings, fix the real ones **with regression-proven tests** (step 4),
re-run the suite, then present the approval gate.

## Report format

State: suite counts + the xfail/deselected invariant, which import smokes ran,
compose result, regression-proof pass/fail pairs, the dynamic check result if
applicable, and the adversarial-review findings + their disposition. Any
`failed`, a pass-count drop, or an XPASS is a stop-and-report, not a footnote.
