# CLAUDE.md

> Brownfield web/backend service. This file is the durable source of truth for working
> in this repo. Conversation history does not persist between sessions — this does.
> Keep it accurate. If you (Claude) discover something here is wrong, flag it and propose a fix.
>
> **Self-contained.** There is no parent/workspace CLAUDE.md for this project any more
> (the old `../CLAUDE.md` was retired 2026-07-27 — see §10). Everything that governs work
> here is in this file and in `.claude/`. Do not import guidance from a sibling project.

---

## 0. Read this first

- This is an **existing, production** codebase (Riverbend Community Health patient portal),
  built by an outside contractor (Helix Digital Partners) and handed off **as-is**.
- **HIPAA covered entity.** PHI, auth, disclosures, and audit paths are load-bearing.
  Treat anything touching patient data as high-risk.
- **Understand before changing.** Trace the relevant code path and read existing tests
  before editing anything.
- **Small, reversible changes.** Prefer minimal diffs and frequent commits over rewrites.
- When unsure whether a change is safe, **stop and ask** rather than guessing.
- The handoff docs are unusually honest: many "bugs" are **documented, intentional gaps**
  (see `ARCHITECTURE.md §7`). Do not naively "fix" weirdness without checking §6 below.

---

## 1. What this service is

- **Purpose:** Patient intake + records portal for Riverbend Community Health, a multi-clinic
  community health network. Patients self-register; front-desk verifies insurance eligibility;
  clinicians view charts; schedulers book appointments; ROI clerks process release-of-information.
- **Type:** Monorepo — Next.js frontend + a fleet of FastAPI microservices behind a BFF gateway.
- **Language & runtime:** Python 3.11/3.12 (services), Node 22 + TypeScript (frontend).
- **Framework:** FastAPI (services), Next.js 15 App Router (frontend).
- **Datastore(s):** Postgres 15 (system of record), Redis 7 (sessions + cache).
- **Upstream/downstream dependencies:** payer eligibility clearinghouse (X12 270/271 REST shim),
  hospital HL7 v2 feed (ADT/ORU ingest).

The portal **never** calls a domain service directly — everything goes through the gateway,
which owns login + session validation and fans requests out.

---

## 2. Repository map

```
frontend/              # Next.js 15 portal (port 3070). BFF route handlers proxy to gateway.
  app/                 #   pages: intake, records, appointments, roi, login
  app/lib/gateway.ts   #   server-side call into the gateway
services/
  gateway/             # FastAPI BFF (8070): login, sessions, request fan-out. ⚠️ owns auth
  intake-service/      # (8071) registration, insurance, consent, eligibility trigger
  eligibility-service/ # (8072) payer X12 270/271 (no DB; calls payer)
  records-service/     # (8073) patient + chart read façade
  scheduling-service/  # (8074) slots, booking, cancel
  interop-service/     # (8075) HL7 v2 ingest
  roi-service/         # (8076) release-of-information + disclosures
  ai-assistant/        # (8077) LLM features. ⚠️ the only vendor-egress path — see §6
config/roles.yaml      # RBAC (single "staff" role — see §6)
db/
  schema.sql           # flattened current schema (loads on fresh Postgres volume)
  migrations/00N_*.sql # ordered, forward-only, hand-rolled, kept in sync with schema.sql by hand
  seed/generate_seed.py# deterministic seed generator → seed/seed.sql
adr/                   # 0001 stack · 0002 data/compliance · 0003 auth/sessions · 0004 ai-assistant
                       # 0005 MPI match key · 0006 LangSmith observability · 0007 AI abuse controls
                       # 0008 date-picker dep · 0009 Bedrock provider · 0010 eligibility resilience
                       # 0011 eligibility agent + visit memory
docs/
  runbook.md           # operations + recovery
  debt-log.md          # D1–D14 debt register (the taxonomy the capstone must align to)
  phi-logging-policy.md# what may and may not reach a log line
  review-loop-metrics.md# A/B/C labels on every review finding + the measured baseline the
                       #   address-review design gate is justified by. Append, don't re-derive.
  specs/wN.md          # per-week engagement specs (client ask, scope, requirements)
  handover/            # jira-tickets.md (the client asks), breach policy, auditor Q, payer status, portal.har
tests/                 # pytest; integration tests marked and need live infra
.claude/               # this project's own tooling: skills, hooks, settings. Tracked in git —
                       # see §10 for why it must never diverge by branch.
```

- **Entry points:** each service is `app.py` (FastAPI app + routers). Frontend boots via Next.js.
- **Config:** `.env` (⚠️ **gitignored now, but still in git history** — see §6), read by each service's `config.py`.
  Compose injects downstream service URLs as env vars (see `docker-compose.yml`).
- **No shared Python library.** Every service copy-pastes the same layout:
  `config.py` / `db.py` (lazy engine, no connect-on-import) / `models.py` /
  `schemas.py` (Pydantic v2) / `logging_config.py` / `app.py`. (ADR 0001.)

---

## 3. Commands

> Actual working commands (from `Makefile`). Verify before relying on them.

| Task            | Command                                   |
|-----------------|-------------------------------------------|
| Install (dev)   | `pip install -r requirements-dev.txt`     |
| Run stack       | `make up`     (docker compose up -d)       |
| Stop stack      | `make down`                               |
| Logs / status   | `make logs` / `make ps`                   |
| Build images    | `make build`                              |
| Seed db         | `make seed`     (reload schema + demo data into running db) |
| Regenerate seed | `make seed-gen` (deterministic → seed.sql) |
| psql shell      | `make psql`                               |
| **Run unit tests** | **`make test-docker`** — python:3.12 container, mirrors CI |
| Run one test    | `make test-docker ARGS="tests/test_hl7_parser.py -q"` |
| Run integration | `pytest -m integration`   (needs `make up`) |
| Frontend dev    | `make frontend-dev`  (npm install + npm run dev) |
| Validate compose| `make config`                             |

- ⚠️ **`make test` / bare `pytest` do not work on this machine.** Local Python is 3.8;
  the suite needs 3.12. **`make test-docker` is the only way to run the tests here** — it
  builds `Dockerfile.test` (deps baked) and runs the same command CI does. Rebuild is
  automatic; it only takes time when `requirements-dev.txt` changed.
- **Setup:** `cp .env.example .env` then `make up`. `make up` also generates the scoped
  credential files `.env.ai-proxy` and `.env.redis` if absent (they are gitignored, and
  the `up/down/logs/ps/build/seed/psql/config` targets all depend on them). Postgres seeds
  on first boot from `db/schema.sql` + `db/seed/seed.sql` (mounted into the container).
- **Demo logins** (all password `portal123`): `frontdesk`, `drnguyen`, `roiclerk`,
  `mokonkwo`, … (see `db/seed/generate_seed.py`).
- **Ports:** portal 3070, gateway 8070 (`/docs`), services 8071–8077 (ai-assistant is 8077),
  Postgres 5432, Redis 6379 (⚠️ Redis is `expose`-only, not published — ADR 0011 round 1).
- **No lint / typecheck / format target exists yet.** CI runs: frontend `npm run build`,
  a per-service `python -c "import app"` import smoke test, and `pytest -m "not integration"`.

---

## 4. How things actually work (vs. how they should)

- **Layering in practice:** portal → gateway (`_get`/`_post` httpx proxies, 30s timeout) →
  domain service → Postgres. Gateway `require_session` only checks "is logged in."
- **Auth reality:** `users` table holds PBKDF2-SHA256 hashes. Login stores `session:<token>`
  in Redis (username, role). **No TTL — sessions never expire.** Single `staff` role for
  everyone; no per-action authz; MFA off (`config/roles.yaml`, gateway `auth.yaml`).
- **Migrations are hand-synced** to `schema.sql` — there is no migration runner; on a fresh
  volume only `schema.sql` runs. Keep both in sync by hand if you touch the schema.
- **Patterns to imitate:** the service module layout (`config/db/models/schemas/app`) is
  consistent across services — match it exactly when adding code.
- **Patterns NOT to imitate:** proxy helpers swallow errors into `{"error": str(e)}` (200 OK
  with an error body); intake logs full request bodies (PHI) at INFO. Don't copy these.

---

## 5. Testing strategy

- **Where:** `tests/`. Framework: **pytest** (`pytest.ini`; `integration` marker).
- **Module loading:** no shared package, so unit tests load the target by file path
  (`tests/conftest.py::load_module`).
- **Covered:** password hash roundtrip, HL7 PID/PV1 happy path, eligibility response shaping,
  intake schema validation, one integration login→auth→chart-read flow.
- **Deliberate gaps (mirror real defects — do NOT "fix" the tests to hide them):**
  scheduling race / double-booking untested; IDOR prevention is an `xfail` (cross-patient
  reads currently succeed); HL7 allergy/med extraction `xfail` (AL1/RXA dropped);
  no ROI authorization tests; no input-normalization / dup-patient tests. (RIV-201.)
- **Brownfield rule:** before refactoring untested code, write **characterization tests**
  capturing current behavior first, then change under green.
- **Negative-test rule for PHI/security code (RIV, PR #2 lesson):** any redaction,
  authz, or sanitization function needs at least one **adversarial** test — the input
  placed where the code does *not* expect it (PHI in a non-PHI key, an SSN inside a
  free-text/list field, a request that skips the happy path). Happy-path tests confirm
  intended behavior; they do not prove the safety boundary holds. The `consents` PHI
  leak shipped green because every redaction test asserted the *intended* shape and none
  planted PHI in the wrong place. For anything that writes a payload to a log, add an
  **end-to-end scan test**: feed PHI into every field (incl. non-PHI keys + list items),
  call the real log-formatting path, assert no raw PHI survives (see
  `tests/test_redaction.py::test_safe_log_payload_masks_phi_in_every_field`).
- **Run `/security-review` (or a local adversarial pass) on the diff before opening a PR**
  touching auth/PHI/ROI — the adversarial bot caught both PR #2 leaks *after* push; pull
  that net earlier.

---

## 6. Landmines and do-not-touch zones

> Most valuable section. Read before editing anything risky. Sourced from `ARCHITECTURE.md §7`.

- ⚠️ **Auth / sessions** (`services/gateway/`, `security.py`, `auth.yaml`) — sessions never
  expire, single role, no MFA. **Never change auth behavior without explicit human approval.**
- ⚠️ **IDOR on chart reads** — `GET /patients/{id}/records` requires a session but never binds
  it to `{patient_id}`; IDs are sequential and walkable. Intentional gap, documented in code.
- ⚠️ **ROI has no authorization enforcement** — disclosures go out with no recorded
  45 CFR 164.508 authorization and no accounting trail. Touches PHI + compliance.
- ⚠️ **PHI handling** — `ssn`, `notes` etc. stored as plaintext `TEXT`; intake logs full
  bodies at INFO. Compliance posture is self-asserted (ADR 0002). Anything here is regulated.
- ⚠️ **Inline eligibility call** (`intake` → `eligibility`) — **bounded as of PR #11 / ADR 0010**,
  but still on the request thread. Both hops now have an explicit timeout and their own
  in-process circuit breaker (`eligibility-service/breaker.py`, `intake-service/breaker.py`);
  an outage returns `pending`/`unknown`, never a false `inactive`. Breaker state is
  **per worker**, so up to `workers × 3` slow calls still land at the start of an outage,
  and a payer stall still costs intake up to `ELIGIBILITY_TIMEOUT_SECONDS` per save until a
  circuit opens. The register-first / async re-verify follow-up is what removes that
  (RIV-088 capped, RIV-141 bounded but not fully closed — see `docs/debt-log.md` D4).
  Do not widen a timeout or loosen a breaker threshold here without re-reading ADR 0010:
  the values are pinned to each other (inner < outer), and `tests/test_eligibility_budget_alignment.py`
  enforces that.
- ⚠️ **Booking race** (`scheduling-service/book.py`) — check-then-insert, no UNIQUE on
  `slot_id`, no idempotency key → double-booking (RIV-175).
- ⚠️ **Duplicate patients** — self-service intake has no MPI/match key (RIV-160).
- ⚠️ **Brittle HL7 mapping** — only PID/PV1 mapped; AL1 (allergies) and RXA (meds) silently
  dropped (RIV-160).
- ⚠️ **Secrets in git history** — `.env` was committed in the past; it is now gitignored
  (`.gitignore:11`) and **no longer tracked**, but the old secrets **remain in git history**
  (rotation + history scrub still pending). No secret/vuln/image scan in CI. Do not add
  more secrets; flag before rotating.
- ⚠️ **Schema/migrations** — `schema.sql` and `migrations/*.sql` are hand-synced; a mismatch
  breaks fresh-volume boots vs. existing dbs.
- **Never edit without explicit human approval:** auth, PHI columns, ROI/disclosure logic,
  migrations, `.env`/secrets.

---

## 7. Safety rules for changes

- Make the **smallest change that solves the problem.** Do not refactor unrelated code.
- **Do not** modify public API contracts, DB schema, or config defaults without flagging first.
- **Do not** delete code that looks unused — confirm via call-site search (routes are wired in
  `app.py`; frontend calls via `app/lib/gateway.ts`) before removal.
- Prefer **feature flags / additive changes** over modifying existing behavior in place.
- If you touch the schema, update **both** `db/schema.sql` and a new `db/migrations/00N_*.sql`.
- After changes run the §3 checks (unit tests + relevant service import smoke) and report results.

---

## 8. Glossary / domain terms

- **BFF** — backend-for-frontend; the gateway. Portal talks only to it.
- **ROI** — Release of Information; fulfilling requests to disclose a patient's records.
- **Eligibility 270/271** — X12 EDI transaction pair: 270 = coverage inquiry, 271 = response.
- **HL7 v2 / ADT / ORU** — hospital messaging; ADT = admit/discharge/transfer, ORU = results.
  **PID** = patient ID segment, **PV1** = visit, **AL1** = allergy, **RXA** = medication admin.
- **MPI** — Master Patient Index; the match key Riverbend intake lacks (dup patients).
- **45 CFR 164.508** — HIPAA rule requiring patient authorization before disclosure.
- **PHI** — Protected Health Information.

---

## 9. Open questions / known tech debt

Carried from the handoff (`ARCHITECTURE.md §7`, `tests/README.md`). The four client asks map
directly onto known gaps. **Debt IDs (D1–D14) and `#N` numbers below come from the training
curriculum's canonical debt register** (`2463-FDE/content` → `client-delivery.html`); this is the
taxonomy the Week-10 capstone debt register / roadmap must align to. Each `Wn` tag marks the
week whose deliverable targets that gap (curriculum arc mirrored in project memory
`curriculum-arc`).

- [~] **RIV-088 / RIV-141** — slow / freezing intake ← inline no-timeout eligibility call.
      **Partly closed** by PR #11 (`5eb88c9`, ADR 0010): timeouts + per-service circuit
      breakers on both hops, seeded `time.sleep(4.2)` removed, cross-service PHI leak in the
      eligibility error path closed. Remaining: verification still runs on the `/intake`
      request thread (register-first + out-of-band re-verify), and gateway `proxy_intake`
      still uses the error-swallowing `_post`. (D4, #7 · W3)
- [ ] **RIV-160** — allergy differs per chart for same patient ← duplicate charts (no MPI)
      and/or HL7 AL1 dropped. (D5 no-MPI · W2 / D6 HL7 drop, #11 · W6)
- [ ] **RIV-175** — double confirmations / two people one slot ← booking race, no UNIQUE/idempotency.
      (D5, #8 · W5, spec-only)
- [ ] **IDOR** — cross-patient chart reads succeed (sessions not patient-bound). (D11, #9 · W4)
- [ ] **ROI authz** — no 45 CFR 164.508 enforcement, no accounting of disclosures.
      (D12, #10 · W9 spec / W10 capstone)
- [ ] **Compliance** — plaintext PHI (D3), PHI in logs (D1, #2), mutable "audit" log
      not tamper-evident (D2/D12). (W1 logs / W10 append-only trail)
- [ ] **Auth** — no session expiry (D10), single role / no segregation of duties (D8, #4),
      no MFA. (W4 / W9)
- [ ] **CI** — no secret/dependency/image scanning; `.env` gitignored now but old secrets
      still in git history (scrub pending). (D9, #12 · W1)
- [ ] **N+1 / full-table scans** in records read/search paths. (D8/D10 amplified · W4)
- [ ] **RIV-201** — thin security/auth test coverage overall.
- [ ] **AI output guardrail** — LLM summary is ungrounded; hallucinated clinical content
      (e.g. "continue metformin" for a no-meds patient) reaches clinicians unchecked.
      Safety + liability. *(Not in original §6 landmines — surfaced by curriculum W7.)*
- [ ] **PHI to vendor / no BAA + fake de-identification** — AI summary ships full encounter
      `{name,dob,mrn,notes}` to a cloud LLM on standard SaaS ToS (no BAA, D13, #5); the
      "de-identified" export drops only `name`, leaving 17/18 Safe-Harbor identifiers →
      re-identifiable (D14, #14). *(Not in original §6 landmines — surfaced by curriculum W8.)*

---

## 10. Working agreements (tooling, delegation, process)

> Ported here on 2026-07-27 from the retired workspace-level `../CLAUDE.md`. That file
> was auto-loaded into every session for this project and had drifted out of sync with
> `.claude/skills/` — its subagent roster still recommended a reviewer that
> `verify-stack` had already retired, and the contradiction cost a review round. A
> second, unowned source of truth is worth less than the one you actually maintain, so
> there is now exactly one. It was renamed to `../WORKSPACE-NOTES.md`, which Claude Code
> does not auto-load; nothing was deleted.

### 10.1 One source of truth per instruction, and it must not depend on the branch

**What actually went wrong on 2026-07-27:** `verify-stack` §6 correctly said "do not use
`cavecrew-reviewer` as a pre-push gate" — on this branch *and* on `main`. The retired
workspace `../CLAUDE.md` listed it as the diff-review agent with no such caveat. Both files
were auto-loaded; the shorter, more confident one won. The defect was **duplication**, not
staleness: the same instruction lived in two files and only one was maintained.

So the primary rule is about ownership:

- **An instruction lives in exactly one place.** If `.claude/skills/` owns how a step is
  done, this file points at the skill rather than restating it. Where §10.2 below names
  agents, it is a pointer with a date, and `verify-stack` §6 remains authoritative.
- If a skill and this file disagree, **the skill wins** for how to do the thing, and the
  disagreement is a bug to fix immediately in whichever file is behind — do not just pick
  one and move on, which is precisely what failed here.

`.claude/` is tracked in git, so a process change committed to a feature branch does not
exist on `main` or on the next branch. **Detect that; do not try to prevent it.**

- Starting a session on a feature branch, check for drift before relying on a skill:
  `git diff main...HEAD -- .claude/`. One command, and it is the whole control.
- Process/tooling changes go in their **own** `docs(process)` / `chore(tooling)` commit,
  then ride the PR like anything else. The drift window is the PR's lifetime, which the
  check above covers.

An earlier draft of this section required process commits to land on `main` *promptly*,
ahead of the feature branch carrying them. That is removed deliberately, and re-adding it
needs new evidence. It was written as a precaution against a drift incident that has never
occurred — the 2026-07-27 failure above was duplication, and the drift example first cited
to justify the rule turned out to be false on inspection (`main` already had the correct
guidance). What the rule reliably produced was a cherry-pick-and-merge ritual around
two-line edits. Measured 2026-07-27: five commits have ever touched `.claude/`, four of
them pure tooling with no code mixed in, across 751 lines in 8 files. The hygiene problem
the rule policed was not happening.

Keep `.claude/` **tracked**, and resist gitignoring it when the bookkeeping feels tedious.
This is a training engagement: the process is part of the deliverable, and `verify-stack`
§6's measurements table — which agent found what, at what cost — is harder-won than most
of the code. Untracked, it is invisible to CI and a fresh clone, unreviewable, and one
`rm -rf` from gone. If branch-independence ever genuinely becomes worth engineering, the
mature answer is a symlink into a sibling repo (the dotfile-manager pattern), which keeps
history and review; `git update-index --skip-worktree` is not that answer and silently
discards local edits on a pull conflict.

### 10.2 Delegating to subagents

Delegate when a subagent buys something this thread cannot get itself: **parallelism**
(independent work at once), **isolation** (a reviewer who never saw the reasoning that
produced the diff, so it cannot inherit that reasoning's blind spots), or **breadth** (a
read-only sweep where only the conclusion matters). Not for token thrift — the working
model has a 1M context and the harness summarises rather than stopping, so session length
alone is not a reason.

Roster, current as of 2026-07-27:

| Need | Use | Notes |
|------|-----|-------|
| Pre-push adversarial diff review | **one `general-purpose` pass** with the briefing pack | `verify-stack` §6 is authoritative. Cap at one; do not fan out. |
| Locate code / call sites | `caveman:cavecrew-investigator` or `Explore` | read-only |
| Bounded 1–2 file edit | `caveman:cavecrew-builder` | refuses 3+ file scope |
| Ad-hoc "review my working diff" mid-development | `caveman:cavecrew-reviewer` | **not** a pre-push gate — retired from that role 2026-07-25 (78k tokens, 0 findings, missed every real defect; its one-line output format is a reasoning constraint). |

**Authorisation.** Sessions may run under a standing "don't spawn subagents unless asked"
rule. A skill or command that instructs a subagent step **is** that authorisation for that
step (`verify-stack`'s adversarial diff review is the standing example). Otherwise ask
before fanning out.

**Brief every review subagent with the facts-only pack** described in `verify-stack` §6:
the verbatim diff, the touched-file inventory, a `file:line` call-site map, what each
changed branch returns and what its callers do with it, and the tests already covering the
surface. Forbid orientation greps; cap the finding count, never the finding length.
Withhold every conclusion — *facts, not verdicts* — because inheriting this thread's
assumptions is exactly what destroys the pass's value.

### 10.3 Brownfield discipline

1. **Read before you write — 5–10× more, early.** Inherited code encodes decisions that
   look strange but have reasons. Removing a "weird" timeout/retry/duplication silently
   re-introduces the bug it was patching. See §6 before touching anything risky.
2. **Match existing conventions over personal preference.** A change should look like it
   belongs — same naming, structure, error handling, and test style as its neighbours.
3. **Land changes at seams, not load-bearing walls.** A *seam* is a single-responsibility
   function called in few places, a config/registry extension point, or a new file wired in
   at one spot. A *load-bearing wall* is imported by many modules or frequent in `git log`
   (`services/gateway/app.py` is the standing example). Earn the right to touch a wall.
4. **Resist the refactor instinct.** Early refactors in code you do not fully understand
   are almost always destructive. Defer.

### 10.4 Conventions

- **Commit messages: no `Co-Authored-By` trailer.** This overrides any default.
- Conventional Commits (`feat`/`fix`/`docs`/`chore`/`test` + scope).
- Sessions may run in **caveman mode** (terse chat). Substance and exactness stay, and
  **code, commits, PRs, ADRs, and security/irreversible-action warnings are always written
  in normal prose** — caveman is for chat only.
- Curriculum context (10-week FDE arc, week → debt-ID mapping) lives in project memory
  `curriculum-arc` and `docs/debt-log.md`, not here.
