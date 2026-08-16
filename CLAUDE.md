# CLAUDE.md

> Durable context for agentic work in this repo. Conversation history does not survive between
> sessions; this file does. Keep it accurate — if you find a claim here is wrong, fix it in the
> same PR that proves it wrong.
>
> **Rewritten 2026-08-06** from a full read of the repo. The previous version was deleted in
> `e0239b4`; recover it with `git show c04806d:CLAUDE.md` if you need the history. Most of what
> was dropped described tooling that does not exist in a fresh clone (worktree snapshot repos,
> git-hook guards, `.claude/` internals) or dead vocabulary from a descoped rebuild.

## 0. What this repo actually is

A **training repository**. "Riverbend Community Health," "Helix Digital Partners," the COO
persona, the RIV tickets, the patients, and the credentials are all fictional. The code is a
realistic brownfield HIPAA-regulated system carrying **deliberately planted defects**, used as a
ten-week curriculum (`docs/specs-deprecated/w1.md`–`w10.md`, each with the client ask in §1 and the decoded
defect in §2).

Everything downstream follows from this: **a defect here is usually a teaching artifact, not a
bug to fix.** Silently "helpfully" repairing one destroys the exercise. Read
`docs/landmines.md` §1 before editing anything that looks wrong.

Treat the PHI as real anyway. The seeded SSNs, notes, and charts are synthetic, but the whole
point of the exercise is practicing the handling discipline, and the graded surface is whether
you kept it.

## 1. The README is client-facing fiction — do not trust it

`README.md:1` and `:82` assert PHI is encrypted and the system is fully HIPAA compliant. It is
not: every PHI column is plaintext `TEXT`. The overstatement is itself part of the scenario
(`docs/debt-log.md` cross-cutting table, `docs/todo.md` TODO-12 — human-gated, do not
unilaterally edit).

Trust instead, in this order: `docs/landmines.md` (rules), `ARCHITECTURE.md` §7 (honest debt
account), `docs/debt-log.md` (per-defect detail and status), the code.

## 2. Repository map

```
frontend/           Next.js 15 App Router portal (3070) — the ONLY frontend, permanent.
                    app/lib/gateway.ts is the single server-side call into the gateway.
services/
  gateway/          FastAPI BFF (8070). Owns login, sessions, RBAC, fan-out. ⚠️ auth lives here
  intake-service/   (8071) registration, insurance, consent, eligibility trigger
  eligibility-service/ (8072) payer X12 270/271 shim, no DB
  records-service/  (8073) patient + chart read façade
  scheduling-service/ (8074) slots, booking, cancel
  interop-service/  (8075) HL7 v2 ingest
  roi-service/      (8076) release-of-information + disclosures
  ai-assistant/     (8077) LLM features. ⚠️ the only vendor-egress path in the estate
config/roles.yaml   declared RBAC policy; enforced twin is gateway/authz.py (test-pinned equal)
contracts/          cross-boundary payload declarations, asserted from BOTH suites
db/schema.sql       flattened schema — the ONLY thing that runs on a fresh Postgres volume
db/migrations/      ordered SQL files applied by db/migrate.py (`make migrate`, e6) — hand-synced to schema.sql
db/seed/generate_seed.py  deterministic generator → seed.sql
adr/0001..0017      _template.md owns the required sections
docs/               landmines.md · debt-log.md · phi-logging-policy.md · runbook.md ·
                    onboarding-seam-map.md · todo.md · workflow/ (staged delivery pipeline,
                    see its README) · specs-deprecated/wN.md (archive) · handover/ · research/
tests/              pytest; only tests/integration/ needs live infra
eval/rag/           RIV-160 retrieval eval + the CI drift gate
```

- **Entry point per service is `app.py`.** No `routers/` anywhere.
- **No shared Python library** (ADR 0001). Every service copy-pastes
  `config.py` / `db.py` / `models.py` / `schemas.py` / `logging_config.py` / `app.py`. Match that
  layout exactly when adding code; copied modules get a parity test (`tests/test_redaction.py`).
- **Ports:** only `postgres:5432`, `gateway:8070`, `frontend:3070` are host-published. Domain
  services are `expose`-only (ADR 0016) and `tests/test_compose_topology.py` enforces the
  allowlist. A refused `curl localhost:8073` is the topology working, not an outage.

## 3. Commands that actually work

- **Local Python is 3.8; the suite needs 3.12.** Bare `pytest` and `make test` fail on this
  machine. Two options that work:
  - `make test-docker` — python:3.12 container, mirrors CI. The claim-worthy gate.
  - a local 3.12 venv: `python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`,
    then `.venv/bin/python -m pytest -m "not integration" -q` (~26s).
- `make up` / `down` / `logs` / `ps` — needs `cp .env.example .env` first; `make up` generates the
  gitignored `.env.ai-proxy` and `.env.redis` itself. Postgres seeds on first boot.
- `make eval` — the drift gate (`eval/rag/check_drift.py`); also runs in CI.
- Everyday targets are `##`-documented in the `Makefile`. That is the single source — do not
  restate them here or anywhere else.
- **The frontend JS gate is Vitest + RTL + jsdom** (ADR 0018, landed by `e1`). CI runs
  `npm run build`, `typecheck`, `lint`, and `npm test` on `frontend/`, plus a `frontend-boot` job
  that `docker run`s the production image and polls `/healthz` — a boot-broken UI now goes red, not
  green (closed TODO-45). Local one-command: `cd frontend && npm install && npm test`.

## 4. How things actually work

- **Layering:** portal → gateway (`_get`/`_post` httpx proxies, 30s timeout) → domain service →
  Postgres. The portal never calls a domain service directly.
- **Auth:** the gateway is the *only* auth boundary. No domain service has any authentication code
  at all. `require_session` checks "is logged in"; `require_capability` (ADR 0017) adds the role
  check. **Neither binds a session to a patient** — that is D11, and it is intentional.
- **Imitate:** the per-service module layout; the class-name-only exception logging idiom
  (`log.error("...(%s)", type(e).__name__)`); typed errors as in `ai-assistant/llm_client.py`;
  `_post_checked` over `_post`.
- **The error-swallowing proxy helpers are gone.** `_post`/`_get` collapsed every exception into a
  **200 OK** `{"error": str(e)}` body and logged `str(e)`. `e4` converted `POST /intake`, `e5`
  converted the remaining thirteen and **deleted both helpers** (2026-08-11), so the rule is now
  structural rather than advisory: every route that fans out uses `_get_checked`/`_post_checked`,
  and `tests/test_gateway_proxy_error_contract.py` fails any route that does not.
- **The `/ai` paths are the quality reference.** Atomic Redis Lua counters, owner-checked
  single-flight caching, fail-closed configuration guards, closed-vocabulary prompts, deterministic
  fallbacks. When adding new code, that is the standard — not the surrounding CRUD proxies.

## 5. Approval-gated zones

**Never edit without explicit human approval: auth, PHI columns, ROI/disclosure logic, migrations,
`.env` or any secret file.**

`docs/landmines.md` is the tracked source of truth for the do-not-touch zones (§1), the
change-safety rules (§2), and the negative-test rule for PHI/security code (§3). It is cited by
`CONTRIBUTING.md`, the PR template, and both `_template.md` files. **Read it there; do not restate
any of it in this file** — a second copy is the failure mode where the shorter, more confident copy
wins and nobody maintains it.

`docs/phi-logging-policy.md` owns the logging rules and a live register of every known violation
with status. Check the register before reporting a "new" PHI leak — several are already logged as
OPEN by design.

The defect that used to head this section — registration completely non-functional while the UI
reported success — was **fixed 2026-08-10 by `e4`** (TODO-1 closed; `docs/workflow/e4/`, and
`docs/debt-log.md` "Intake contract break" keeps the account of what was wrong). What is worth
knowing before you touch intake or the gateway now is what holds it closed:
`contracts/intake-registration.json` is the one payload declaration both suites assert against,
`ConsentKind` is a test-pinned closed enum and a documented PHI control, and `proxy_intake` is on
`_post_checked`. `e5` (2026-08-11) finished the job: the other thirteen routes are converted, the
swallowing helpers are deleted, and the six portal read surfaces that coerced any non-list body to
an empty result now distinguish failed from empty. What holds it closed is
`tests/test_gateway_proxy_error_contract.py` — a per-route contract, a route-set closure case that
reddens on an unconverted new route, and a structural scan with a positive control.

## 6. Testing

- `tests/`, pytest, one marker (`integration`). No shared package, so tests load modules by file
  path via `tests/conftest.py::load_module`. Bare sibling names (`config`) collide across services
  — pin `sys.modules` first.
- **Baseline, measured 2026-08-16 under `make test-docker`: `1316 passed, 18 deselected, 1 xfailed`.**
  The xfail is the HL7 AL1/RXA gap; the deselected 18 are the integration tests (`tests/integration/`),
  which need a live Postgres and run in CI's `migrations` job / `make test-migrations`, not the
  default run — e6 added 13 of them with the migration runner. These counts are
  load-bearing — a moved count means a deliberate gap moved, which is a finding to report, not a
  number to update. Which additions were deliberate, and what each item added, lives in
  `docs/workflow/<item>` and git history — not here.
- `docs/landmines.md` §3 owns the negative-test rule, the characterization-tests-first rule, and
  the list of deliberate coverage gaps that must stay visible. Read it there before adding or
  changing a test on a PHI, authz, or sanitization path.

## 7. Docs are current, with known exceptions

Trust the docs; the five files that had outgrown their claims were corrected 2026-08-08, dated in
place (`docs/todo.md` TODO-52, closed). One drift is left and it is citation-level: **a
`CLAUDE.md §n` reference written before the 2026-08-06 rewrite points at the wrong section — check
it against the headings above before acting on it.** Counts and the old→new mapping: TODO-57.

The one piece of vocabulary worth holding in your head: ADRs 0012–0015 are `Superseded` (the
SvelteKit rebuild was descoped 2026-08-05). Read them as decisions-as-taken, never as current plan.
`FE-R*`, `G0`–`G6` and `P2`–`P7` are dead vocabulary; a doc still using them is stale.

## 8. Findings from the 2026-08-06 read

A full read of the repo turned up twelve issues that no landmine, ADR, or debt entry covered. All
twelve are filed where the registry contract puts them (`docs/todo.md:8-11` — specs own
requirements, `debt-log.md` owns risk, `todo.md` owns unscheduled loose ends); read them there,
not here. Two of the twelve turned out to be already documented, which is the standing lesson:
**check the registries before reporting a finding as new.**

## 9. Conventions

`CONTRIBUTING.md` owns branching, commit format, and the PR process in full. Read it there. The
only things worth repeating, because they are easy to get wrong and expensive to undo:

- **No `Co-Authored-By` trailer** on commits (`CONTRIBUTING.md:53`) — this overrides any default.
- The PR body's **"Risk & landmines" section is required**: name which `docs/landmines.md` §1 zones
  the change touches, or "none touched."
- A schema change updates **both** `db/schema.sql` and a new `db/migrations/00N_*.sql`.
- Land changes at seams, not load-bearing walls — `docs/onboarding-seam-map.md` names six safe
  extension points and eight walls. `services/gateway/app.py` is the standing wall.
- ADRs, specs, and reports should be as short as the decision allows. Length is not thoroughness.

## 10. Working with agents here

- **One instruction lives in exactly one place.** If `docs/landmines.md` owns a rule, this file
  points at it. Duplication is how a stale copy wins an argument against a maintained one.
- **Read before you write.** Inherited code encodes decisions that look strange but have reasons —
  a "weird" timeout, retry, or duplication is usually patching something. Removing it silently
  reintroduces the bug. The eligibility timeout/breaker values are pinned to each other and
  enforced by `tests/test_eligibility_budget_alignment.py`.

## 11. Tooling

**`.claude/` is tracked as of 2026-08-06.** From-scratch tooling lands here as the staged
workflow (`docs/workflow/README.md`) defines each stage. Currently:
`skills/requirement-synthesis/` (workflow stage 1), `skills/spec-authoring/` (stage 2),
`skills/plan-authoring/` (stage 3), `skills/mockup/` (optional plan-stage input for portal
surfaces; output stays scratch, outside the repo), `skills/drift-gate/` (plan/spec gate),
`skills/implementation/` (stage 4) with its inner loop `skills/tdd/`, `skills/impl-gate/`
(pre-push gate), `skills/noncode-merge/` (gated fast path landing non-code changes on
`main`); and, added 2026-08-15, `agents/` with three gate agents —
`drift-gate-agent`, `impl-gate-agent`, `adv-reviewer-agent` — spawned by the two gate
skills to do the adversarial read. Their toolset is `Read`/`Grep`/`Glob`/`Bash`:
Edit/Write are absent, so the agents cannot edit or stamp through those tools, but
`Bash` (kept for diffs, `cmd:` cells, suite runs) can still write the tree — shell
read-only behavior is a behavioral rule in each definition, not tool enforcement.
Nothing else — no hooks.

**The prior engagement's tooling is deliberately not adopted.** It is not lost — 42 files under
`.claude/` exist on branch `chore/noref-track-claude-tooling` (PR #36, and a second attempt in
PR #37; both closed unmerged 2026-08-06 by the engagement owner). They were never on `main`.
Decision 2026-08-06: process and tooling here get **built from scratch** rather than inherited, so
that branch is a historical record, not a source to copy from. Any in-repo reference to
`address-review`, `spec-lens`, `/dashboard`, `feature-start`, `diff-reviewer`, `verify-stack`,
`doc-drift`, `pr-open`, `render-pdf`, `regression-proof` or `memory-lint` is a **dead name on
`main`** — nothing there can execute it. Treat such an instruction as unexecutable and say so
rather than improvising a substitute or reviving the branch. Live docs were reconciled 2026-08-08
(`docs/todo.md` TODO-53, closed); a dead name surviving in an archived or `Superseded` file is a
record of what happened, not an instruction.

When tooling does get written, it lands in `.claude/` and is committed, so every clone and worktree
inherits the same thing and changes get PR review. Keep machine-local state out — credentials,
per-machine paths, and mutable run state stay gitignored (`.claude/settings.local.json`,
`.claude/scheduled_tasks.lock`, `__pycache__`). `scripts/`, `.env*` and `logs/` remain ignored too.

**CI cannot execute any `.claude/` tooling, tracked or not** — hooks and skills run only inside a
Claude Code session. Tracking buys portability and review, not enforcement. Anything that must gate
a merge belongs in `.github/workflows/ci.yml` or the `Makefile`; a hook-only check is advisory.
