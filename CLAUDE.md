# CLAUDE.md

> Brownfield, HIPAA-regulated web/backend service. Durable source of truth for working here —
> conversation history does not persist between sessions, this does. Keep it accurate; if you
> (Claude) find something here is wrong, flag it and propose a fix.
>
> **Where this file lives, and why.** Repo root, **tracked** — re-tracked 2026-08-05, reversing
> PR #32 the same day it landed (`docs/plans/pipeline-upgrade.md` PIPE-1): parallel worktrees
> and fresh clones must inherit the rules, the ~97 in-repo doc references must resolve, and
> rule changes get PR review. **Edits to this file are approval-gated (§7).** `.claude/`
> tracking is decided too (OD-1, exclusions listed there) and lands in the immediate follow-up
> PR. The old shadow-rename guard is disabled per its own instruction
> (`git config riverbend.allowRepoClaudeMd true`); the parent copy at
> `~/Documents/REVATURE/Riverbend/` is renamed `inactive-claude.md` once PIPE-1 step 8's
> preconditions are met (riverbend-demo rebased or retired first).
>
> **Self-contained:** there is no parent/workspace CLAUDE.md (retired 2026-07-27 →
> `../WORKSPACE-NOTES.md`, not auto-loaded), and everything governing work here is in this
> file, `docs/landmines.md` (the do-not-touch zones, safety rules and negative-test rule,
> cited by `CONTRIBUTING.md`, the PR template and both `_template.md` files — §6 below points
> at it and does not restate it) and `.claude/`.

## 0. Ground rules

- Existing **production** codebase (Riverbend Community Health patient portal), built by an
  outside contractor (Helix Digital Partners) and handed off as-is.
- **HIPAA covered entity.** PHI, auth, disclosures and audit paths are load-bearing.
- The handoff docs are unusually honest: many "bugs" are **documented, intentional gaps**. Check
  `docs/landmines.md` and §9 before "fixing" weirdness.
- When unsure whether a change is safe, stop and ask.

## 1. What this service is

Patient intake + records portal for a multi-clinic community health network. Patients
self-register; front-desk verifies insurance eligibility; clinicians view charts; schedulers book;
ROI clerks process release-of-information.

Monorepo: Next.js 15 App Router frontend (Node 22 + TypeScript) + FastAPI microservices (Python
3.11/3.12) behind a BFF gateway. Postgres 15 is the system of record, Redis 7 holds sessions +
cache. External: payer eligibility clearinghouse (X12 270/271 REST shim), hospital HL7 v2 feed
(ADT/ORU ingest). The portal **never** calls a domain service directly — everything goes through
the gateway, which owns login + session validation and fans requests out.

## 2. Repository map

```
frontend/             # Next.js 15 portal (3070) — the ONLY frontend. BFF route handlers proxy
                      #   to the gateway. pages: intake, records, appointments, roi, login
                      # ⚠️ Registration is BROKEN here and reports success (docs/debt-log.md);
                      #   deliberately not patched, and no longer waiting on a replacement.
  app/lib/gateway.ts  #   server-side call into the gateway
services/
  gateway/            # FastAPI BFF (8070): login, sessions, request fan-out. ⚠️ owns auth
  intake-service/     # (8071) registration, insurance, consent, eligibility trigger
  eligibility-service/# (8072) payer X12 270/271 (no DB; calls payer)
  records-service/    # (8073) patient + chart read façade
  scheduling-service/ # (8074) slots, booking, cancel
  interop-service/    # (8075) HL7 v2 ingest
  roi-service/        # (8076) release-of-information + disclosures
  ai-assistant/       # (8077) LLM features. ⚠️ the only vendor-egress path
config/roles.yaml     # RBAC roles+capabilities (ADR 0017; enforced twin: gateway authz.py)
db/schema.sql         # flattened current schema (loads on a fresh Postgres volume)
db/migrations/00N_*.sql   # ordered, forward-only, hand-synced to schema.sql
db/seed/generate_seed.py  # deterministic seed generator → seed/seed.sql
adr/                  # `_template.md` owns the required sections — copy it
docs/
  landmines.md        # ⚠️ TRACKED source of truth for the do-not-touch zones, the safety rules
                      #   and the negative-test rule. §6/§7 here point at it; read it, do not
                      #   look for a second copy.
  debt-log.md         # the worked debt entries (§9 indexes them) · todo.md
  onboarding-seam-map.md  # §10.3's seam/wall rule made concrete: the 6 safe extension points
                      #   with worked examples, and the 8 walls with why. Read before landing a
                      #   change somewhere new. No other file links it.
  review-loop-metrics.md  # A/B/C label per review finding + measured baseline. Append only.
  specs/wN.md         # weekly engagement specs — the source of truth for scheduled work.
                      #   `_template.md` owns EARS rules + ID scheme
  handover/           # jira-tickets.md (client asks), breach policy, auditor Q, payer status,
                      #   portal.har
tests/                # pytest; integration tests marked and need live infra
eval/ · scripts/ · logs/  # eval harness; local tooling (gitignored); local logs
.claude/              # skills, hooks, commands, settings. Tracking lands in the follow-up
                      #   PR (pipeline-upgrade OD-1, exclusions apply). See §10.1.
```

- **Entry points:** each service is `app.py` (FastAPI app + routers). Frontend boots via Next.js.
- **Config:** `.env` (⚠️ gitignored now, but still in git history), read by each service's
  `config.py`. Compose injects downstream service URLs as env vars (`docker-compose.yml`).
- **No shared Python library.** Every service copy-pastes the same layout: `config.py` / `db.py`
  (lazy engine, no connect-on-import) / `models.py` / `schemas.py` (Pydantic v2) /
  `logging_config.py` / `app.py`. Match it exactly when adding code (ADR 0001).
- **The SvelteKit rebuild is descoped** (2026-08-05, PR #31). Its scaffold, spec (`FE-R*`), gate
  track (`G0`–`G6`) and design set are on branch **`alt/sveltekit-portal`**. **ADRs 0012–0015 are
  still here in `adr/`**, carrying `Status: Superseded 2026-08-05` headers — only their unchanged
  pre-descope text is on that branch, so read them for the decision as taken, never as current
  plan. `FE-R*`, `G0`–`G6` and `P2`–`P7` are **dead vocabulary** — if a doc still uses them, that
  doc is stale. Do not resurrect the rebuild without an explicit decision.

## 3. Commands

- **Everyday targets are `##`-documented in the `Makefile`** — that is the single source; do not
  restate them here.
- ⚠️ **`make test` / bare `pytest` do not work on this machine.** Local Python is 3.8, the suite
  needs 3.12. Two tiers: `.venv/bin/python -m pytest` to iterate (~2s), and **`make test-docker`**
  (python:3.12 container, mirrors CI) as the only claim-worthy gate.
- **There is no JS gate and no lint/format target for Python.** `make test-frontend` went with the
  rebuild; CI builds `frontend/` and nothing type-checks, lints or tests it. What CI gates is in
  `.github/workflows/ci.yml`.
- **`make status` is retired** — the dashboard was mostly the rebuild's gate track. Engagement
  status comes from `docs/specs/`, `docs/debt-log.md` and `gh pr list`.
- **Setup:** `cp .env.example .env` then `make up`, which also generates the gitignored
  `.env.ai-proxy` / `.env.redis` if absent. Postgres seeds on first boot.
- **Demo logins** (all password `portal123`): `frontdesk`, `drnguyen`, `roiclerk`, `mokonkwo`, …
  (see `db/seed/generate_seed.py`).
- **Ports** are in `docker-compose.yml` and the §2 map; the gateway serves `/docs`. ⚠️ Redis 6379
  and the domain services 8071–8076 are `expose`-only, not published.

## 4. How things actually work

- **Layering in practice:** portal → gateway (`_get`/`_post` httpx proxies, 30s timeout) → domain
  service → Postgres. Gateway `require_session` only checks "is logged in"; `require_capability`
  adds the role check (ADR 0017). Neither binds a session to a patient.
- **Imitate:** the `config/db/models/schemas/app` module layout, consistent across every service.
- **Do NOT imitate:** proxy helpers swallow errors into `{"error": str(e)}` (200 OK with an error
  body); intake logs full request bodies (PHI) at INFO.

## 5. Testing strategy

- **Where:** `tests/`, pytest (`pytest.ini`; `integration` marker). No shared package, so unit
  tests load the target by file path (`tests/conftest.py::load_module`).
- **The negative-test rule, the characterization-tests-first rule, and the list of deliberate gaps
  that must not be "fixed" are in `docs/landmines.md` §3.** Read it there.
- Run `/security-review` (or a local adversarial pass) on the diff **before** opening a PR that
  touches auth/PHI/ROI — the review bot caught both PR #2 leaks only after push.

## 6. Landmines and do-not-touch zones

> **These moved out of this file on 2026-08-05 and are now tracked at `docs/landmines.md`.** A
> required rule cannot live in a file a fresh clone does not have — `CONTRIBUTING.md`, the PR
> template and both `_template.md` files cite it, and the PR template makes "which zones does this
> touch" a required field.
>
> **Read `docs/landmines.md` §1 before editing anything risky.** Do not restate any of it here;
> a second copy is the §10.1 failure mode, and the shorter, more confident copy wins.

The one thing worth repeating, because it governs whether you may act at all:

- **Never edit without explicit human approval:** auth, PHI columns, ROI/disclosure logic,
  migrations, `.env`/secrets.

## 7. Safety rules for changes

> Also moved — `docs/landmines.md` §2. Smallest change that solves the problem; schema touches
> update both `schema.sql` and a migration; confirm call sites before deleting; flag contract and
> config-default changes; land at seams, not walls.

- After changes, run the §3 checks (unit tests + relevant service import smoke) and report results.
- Park tangents in `docs/todo.md` (§11) rather than widening the diff.
- **Edits to this file (`CLAUDE.md`) are approval-gated** — the rulebook does not change without
  a human signing the diff (`docs/plans/pipeline-upgrade.md` PIPE-1, 2026-08-05).

## 9. Known debt

*(§8, a glossary of standard terms, was removed; numbering left intact so external references
still resolve.)*

The four client asks (`docs/handover/jira-tickets.md`) map onto known gaps. `docs/debt-log.md` has
the **worked** entries in detail (D1, D1b, D3b, D4, D5a/b, D6, D8, D11, D12); the full D1–D14
curriculum taxonomy and the week→debt mapping live in project memory `curriculum-arc`. This table
indexes both — several IDs appear nowhere else, so do not thin it to a pointer.

| Gap | Status |
|-----|--------|
| **RIV-088 / RIV-141** slow/freezing intake ← inline eligibility call (D4, W3) | ~ partly closed by PR #11 / ADR 0010 **and PR #14 shipped the W3 agent work**; verification still runs on the `/intake` request thread, and gateway `proxy_intake` still uses the error-swallowing `_post`. **D4b: the result is never persisted** — `insurance_coverages.status` keeps its `'unknown'` default even after the payer answers |
| **RIV-160** allergy differs per chart ← no MPI (D5a, W2) and HL7 AL1 dropped (D6, W6) | open |
| **RIV-175** double confirmations ← booking race, no UNIQUE/idempotency (D5b, W5) | open, spec-only |
| **IDOR** cross-patient chart reads succeed; sessions not patient-bound (D11, W4) | open — **next week up** |
| **ROI authz** no 45 CFR 164.508 enforcement, no accounting of disclosures (D12) | open |
| **Compliance** plaintext PHI (D3), PHI in logs (D1), mutable non-tamper-evident audit log (D2) | open (W1 logs) |
| **Auth** no session expiry (D10), single role / no segregation of duties (D8), no MFA | ~ D8 partly closed by ADR 0017 (four roles + gateway capability enforcement; `staff` compat rows keep every capability); D10 and MFA open. **The idle-logoff mitigation went with the rebuild** — nothing logs an operator off today |
| **CI** `gitleaks` guards recurrence only (`--no-git`); no dependency or image scan; old `.env` secrets still in git history (D9, W1) | partly closed |
| **N+1 / full-table scans** in records read/search paths (D8, W4) | open |
| **Intake contract break** registration 422s, gateway relays 200, UI reports success, no patient row | open and **unscheduled** — the fix was folded into the descoped rebuild. TODO-1, the highest-value item in the register |
| **No JS test harness, no frontend runtime smoke** — the intake defect *class* is unguarded, and nothing starts the frontend container | open (TODO-7, TODO-45) |
| **RIV-201** thin security/auth test coverage overall | open |
| **AI output guardrail** ungrounded LLM summary; hallucinated clinical content reaches clinicians unchecked | open |
| **PHI to vendor** full encounter `{name,dob,mrn,notes}` to a cloud LLM on SaaS ToS, no BAA (D13); the "de-identified" export drops only `name`, leaving 17/18 Safe-Harbor identifiers (D14) | open |
| **Two AI features with no UI** — `/ai/visit-chat` has never had one in any portal | open and unscheduled (TODO-44) |

## 10. Working agreements

### 10.1 One source of truth per instruction

- **An instruction lives in exactly one place.** If `.claude/skills/` owns how a step is done, this
  file points at the skill rather than restating it. If a skill and this file disagree, **the skill
  wins** on how-to, and the disagreement is a bug to fix immediately in whichever file is behind.
  (Duplication cost a review round on 2026-07-27: one instruction, two files, only one maintained,
  and the shorter more confident copy won.) The same rule is why §6/§7 above are pointers.
- **This file is tracked (2026-08-05, reversing PR #32), and `.claude/` tracking lands in the
  follow-up PR** (pipeline-upgrade OD-1; excluded and still local-only: `settings.local.json`,
  `gates/state.json`, `scheduled_tasks.lock`, `__pycache__`). Rule changes therefore get PR
  review; the "push code and docs, tooling stays local" rule is retired. Backup:
  `../.riverbend-tooling-snapshots/` — its own git repo, deliberately outside `Riverbend/`;
  `snapshot.sh` fires on Claude Code **SessionEnd**, `restore.sh <ref>` restores point-in-time.
  It still covers the OD-1 exclusions, the memory base and the gitignored `scripts/`; `.env*`
  excluded. That repo's `README.md` owns the mechanics and holds the canonical copies of every
  `.git/hooks/` guard.
- **Untrack with `git rm -r --cached`, never `git rm`.** Both stage an identical deletion, so the
  diff and the review look the same — but `git rm` also unlinks the file. PR #20 wiped the entire
  tooling tree that way. Verify files are still on disk before committing. A `.git/hooks/pre-commit`
  guard blocks the combination (staged deletion + newly ignored + absent from working tree) and
  prints the recovery recipe; bypass with `ALLOW_IGNORE_DELETE=1` when the deletion is intended.
- ⚠️ **Branch-switch history (kept for the record):** during the one day this file was
  untracked-and-parent-level (PR #32, 2026-08-05), a `checkout`/`merge` from a pre-#32 ref
  could delete an untracked repo-root copy and re-add a stale tracked one — both happened that
  day (the re-add left `riverbend-demo` shadowing the live file with a pre-descope copy,
  removed in `07a0c0b`). `post-checkout`/`post-merge` guards renamed arriving repo-root copies
  to `CLAUDE.md.shadow-<ref>`. **Now that this file is re-tracked, that guard is disabled per
  its own instruction** — `git config riverbend.allowRepoClaudeMd true`, set 2026-08-05; the
  hooks stay installed, not deleted. Mechanics in the snapshots `README.md`. Branches cut
  before the re-track carry their own older `CLAUDE.md` — a checkout showing "modified:
  CLAUDE.md" after switching back is that, not an edit.
- **`git clean -xfd` deletes ignored files** — until the `.claude/` tracking PR lands that is
  all of `.claude/`, and after it the OD-1 exclusions — survivable only back to the last
  snapshot commit.
- **CI cannot run any `.claude/` tooling, tracked or not** — hooks execute only inside Claude
  Code sessions. Anything that must gate a merge belongs in `.github/workflows/` or the
  `Makefile`; a hook-only check is advisory. Tracking buys portability and review, not
  enforcement.

### 10.2 Delegating to subagents

Delegate only when a subagent buys something this thread cannot get itself: **parallelism**,
**isolation** (a reviewer that never saw the reasoning which produced the diff, so it cannot
inherit that reasoning's blind spots), or **breadth**. Not for token thrift. **Cap at one; do not
fan out** — this model delegates readily, so the cap is the lever that matters.

| Need | Use | Notes |
|------|-----|-------|
| Pre-push adversarial diff review | one `diff-reviewer` pass (`.claude/agents/`; assembles its own pack) | `verify-stack` §6 is authoritative |
| Locate code / call sites | `caveman:cavecrew-investigator` or `Explore` | read-only |
| Bounded 1–2 file edit | `caveman:cavecrew-builder` | refuses 3+ file scope |
| Ad-hoc mid-development diff review | `caveman:cavecrew-reviewer` | **not** a pre-push gate — retired from that role 2026-07-25 (78k tokens, 0 findings, missed every real defect) |
| §4 regression proof (layer reverts + red counts) | `regression-proof` workflow (`.claude/workflows/regression-proof.js`) | `verify-stack` §4 is authoritative; 3 Haiku worktree agents, verdict computed in-script, main thread defines the proof |
| Week-boundary doc-drift sweep | `doc-drift` skill (`.claude/skills/doc-drift/`): sequential Haiku `Explore` readers, one per doc family | skill authorizes each reader, one at a time; report-only, never edits docs |
| Brief perspective review after `/feature-start` | `spec-lens` skill (`.claude/skills/spec-lens/`): sequential session-model read-only lenses (security/authz, ops/runbook, decision record) | skill authorizes each lens, one at a time; report-only, never edits brief or spec — human amendment of the brief is the HITL gate |

**Authorisation.** Sessions may run under a standing "don't spawn subagents unless asked" rule. A
skill or command that instructs a subagent step **is** that authorisation for that step
(`verify-stack`'s adversarial diff review is the standing example). The same doctrine covers
workflows: a skill's instruction to run a workflow authorises every agent that workflow spawns —
`verify-stack` §4's `regression-proof` (three worktree agents) counts as **one** delegated step.
The one-subagent cap governs ad-hoc fan-out, not a skill-specified workflow. Otherwise ask before fanning
out. **Review subagents get facts, never verdicts — the spawn prompt names the branch and nothing
else; `diff-reviewer` assembles its own pack, and `verify-stack` §6 owns the pack spec and wins on
any disagreement (§10.1).**

### 10.3 Brownfield discipline

- **Read before you write.** Inherited code encodes decisions that look strange but have reasons;
  removing a "weird" timeout/retry/duplication silently re-introduces the bug it was patching.
- **Match existing conventions over personal preference** — a change should look like it belongs.
- **Land changes at seams, not load-bearing walls.** A *seam* is a single-responsibility function
  called in few places, a config/registry extension point, or a new file wired in at one spot. A
  *wall* is imported by many modules or frequent in `git log` (`services/gateway/app.py` is the
  standing example). Earn the right to touch a wall. Worked examples: `docs/onboarding-seam-map.md`.

### 10.4 Worktrees

Since this file is tracked (2026-08-05), **every checkout — worktree or clone, wherever it
lives — carries it at its own root.** What still varies is `.claude/`:

- **Create worktrees under `~/Documents/REVATURE/Riverbend/`** (e.g. `git worktree add
  ../riverbend-<name>`) **until the `.claude/` tracking PR lands** — a worktree elsewhere has
  the rules and `docs/landmines.md` but no skills or hooks. Once `.claude/` is tracked, the
  location rule relaxes to a preference (the OD-1 exclusions still exist only here).
- ⚠️ **Branches cut before the re-track** check out their own older `CLAUDE.md` (or none, e.g.
  `riverbend-demo`'s tip `07a0c0b`) — rebase onto current `main` before trusting the rules a
  stale tree shows.
- **Moving a worktree breaks its links in both directions** (both ends store absolute paths). Fix
  with `git worktree repair <path>` from the main checkout, then confirm with `git worktree list` —
  a stale entry shows as `prunable`.
- **Only one Docker stack at a time across trees** — compose project-name collision on the same
  host ports. `make test-docker` coexists fine.

### 10.5 Conventions

- **Commit messages: no `Co-Authored-By` trailer.** This overrides any default.
- Conventional Commits (`feat`/`fix`/`docs`/`chore`/`test` + scope).
- Sessions may run in **caveman mode** (terse chat). Substance and exactness stay, and code,
  commits, PRs, ADRs and security/irreversible-action warnings are always normal prose.
- **Calibrate the length of written deliverables.** ADRs, specs and reports here should be as short
  as the decision allows — length is not thoroughness. Chat verbosity is a separate control: reduce
  it explicitly, not by lowering reasoning effort.

## 11. Focus and flow

- **Parking lot.** Capture tangents without asking — say "Parked that", append to `docs/todo.md`,
  continue the current task. The registry contract: `wN.md` owns requirements, `debt-log.md` owns
  risk, `todo.md` holds only unscheduled loose ends pointing outward via `src:`.
- **Name scope creep, park it, don't debate it.** If the work is growing mid-flight, say so in one
  line and park the expansion rather than negotiating it.
- **Context-switch snapshot.** On "switching to X" / "brb", dump current task state — what's done,
  what's next, files touched, open decision — so a parallel session can pick it up.
- **Lead with a recommendation, not an open question.** Give the call plus the one-line reason;
  surface alternatives only when they would change the work.
