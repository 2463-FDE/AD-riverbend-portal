# CLAUDE.md

> Brownfield, HIPAA-regulated web/backend service. Durable source of truth for working here —
> conversation history does not persist between sessions, this does. Keep it accurate; if you
> (Claude) find something here is wrong, flag it and propose a fix. **Self-contained:** there is
> no parent/workspace CLAUDE.md (retired 2026-07-27 → `../WORKSPACE-NOTES.md`, not auto-loaded).
> Everything governing work here is in this file and `.claude/`.

## 0. Ground rules

- Existing **production** codebase (Riverbend Community Health patient portal), built by an
  outside contractor (Helix Digital Partners) and handed off as-is.
- **HIPAA covered entity.** PHI, auth, disclosures and audit paths are load-bearing.
- The handoff docs are unusually honest: many "bugs" are **documented, intentional gaps**. Check
  §6 and §9 before "fixing" weirdness.
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
frontend/             # Next.js 15 portal (3070). BFF route handlers proxy to gateway.
                      #   pages: intake, records, appointments, roi, login
                      # ⚠️ legacy. Registration is BROKEN here and reports success (debt-log
                      #   cross-cutting); deliberately not patched. Replaced by portal/.
  app/lib/gateway.ts  #   server-side call into the gateway
portal/               # SvelteKit staff portal (3071). Scaffold + JS test harness only so far —
                      #   no login, no gateway calls yet. `make portal-dev` / `make test-frontend`.
                      #   Decisions pinned in ADR 0012 (framework), 0013 (harness), 0014 (session),
                      #   0015 (origin); what is load-bearing in it is in portal/README.md.
services/
  gateway/            # FastAPI BFF (8070): login, sessions, request fan-out. ⚠️ owns auth
  intake-service/     # (8071) registration, insurance, consent, eligibility trigger
  eligibility-service/# (8072) payer X12 270/271 (no DB; calls payer)
  records-service/    # (8073) patient + chart read façade
  scheduling-service/ # (8074) slots, booking, cancel
  interop-service/    # (8075) HL7 v2 ingest
  roi-service/        # (8076) release-of-information + disclosures
  ai-assistant/       # (8077) LLM features. ⚠️ the only vendor-egress path — see §6
config/roles.yaml     # RBAC roles+capabilities (ADR 0017; enforced twin: gateway authz.py)
db/schema.sql         # flattened current schema (loads on a fresh Postgres volume)
db/migrations/00N_*.sql   # ordered, forward-only, hand-synced to schema.sql
db/seed/generate_seed.py  # deterministic seed generator → seed/seed.sql
adr/                  # 0001–0015; `_template.md` owns the required sections — copy it
docs/                 # debt-log.md (§9) · runbook.md · phi-logging-policy.md · todo.md
                      #   onboarding-seam-map.md · design/ · research/ · status/
  review-loop-metrics.md  # A/B/C label per review finding + measured baseline. Append only.
  specs/wN.md         # weekly engagement specs; `_template.md` owns EARS rules + ID scheme
  specs/frontend-rebuild.md  # FE-R1–R26, gates G0–G5
  handover/           # jira-tickets.md (client asks), breach policy, auditor Q, payer status,
                      #   portal.har
tests/                # pytest; integration tests marked and need live infra
eval/ · scripts/ · logs/  # eval harness; local tooling (gitignored); local logs
.claude/              # skills, hooks, settings. NOT tracked — gitignored. See §10.1.
```

- **Entry points:** each service is `app.py` (FastAPI app + routers). Frontend boots via Next.js.
- **Config:** `.env` (⚠️ gitignored now, but still in git history — §6), read by each service's
  `config.py`. Compose injects downstream service URLs as env vars (`docker-compose.yml`).
- **No shared Python library.** Every service copy-pastes the same layout: `config.py` / `db.py`
  (lazy engine, no connect-on-import) / `models.py` / `schemas.py` (Pydantic v2) /
  `logging_config.py` / `app.py`. Match it exactly when adding code (ADR 0001).

## 3. Commands

| Task | Command |
|------|---------|
| Install (dev) | `pip install -r requirements-dev.txt` |
| Run / stop stack | `make up` / `make down` |
| Logs / service status | `make logs` / `make ps` |
| Build images | `make build` |
| Seed db / regenerate seed | `make seed` / `make seed-gen` |
| psql shell | `make psql` |
| **Run unit tests** | **`make test-docker`** — python:3.12 container, mirrors CI |
| Run one test | `make test-docker ARGS="tests/test_hl7_parser.py -q"` |
| Run integration | `pytest -m integration` (needs `make up`) |
| **Run the JS gate** | **`make test-frontend`** — `portal/` only: `svelte-check`, eslint, Vitest |
| Frontend dev | `make frontend-dev` (legacy, 3070) / `make portal-dev` (SvelteKit, 3071) |
| Validate compose | `make config` |
| Regenerate status dashboard | `make status` (local only; needs gitignored `scripts/status.py`) |

- ⚠️ **`make test` / bare `pytest` do not work on this machine.** Local Python is 3.8, the suite
  needs 3.12; `make test-docker` (builds `Dockerfile.test`, runs what CI runs) is the only way.
- **Setup:** `cp .env.example .env` then `make up`, which also generates the gitignored
  `.env.ai-proxy` / `.env.redis` if absent. Postgres seeds on first boot from `db/schema.sql` +
  `db/seed/seed.sql`.
- **Demo logins** (all password `portal123`): `frontdesk`, `drnguyen`, `roiclerk`, `mokonkwo`, …
  (see `db/seed/generate_seed.py`).
- **Ports:** legacy portal 3070, SvelteKit portal 3071, gateway 8070 (`/docs`), services 8071–8077,
  Postgres 5432, Redis 6379 (⚠️ `expose`-only, not published — ADR 0011 round 1).
- **Lint/typecheck exist for `portal/` only** (`svelte-check --fail-on-warnings` + eslint, via
  `make test-frontend`); there is still no Python lint/format target and none for `frontend/`.
  CI (`.github/workflows/ci.yml`) runs the legacy frontend `npm run build`, the `portal` job above
  on Node 22, a per-service `python -c "import app"` import smoke, `pytest -m "not integration"`, a
  `gitleaks` secret scan, and `docker-build`.

## 4. How things actually work

- **Layering in practice:** portal → gateway (`_get`/`_post` httpx proxies, 30s timeout) → domain
  service → Postgres. Gateway `require_session` only checks "is logged in" (§6).
- **Imitate:** the `config/db/models/schemas/app` module layout, consistent across every service.
- **Do NOT imitate:** proxy helpers swallow errors into `{"error": str(e)}` (200 OK with an error
  body); intake logs full request bodies (PHI) at INFO.

## 5. Testing strategy

- **Where:** `tests/`, pytest (`pytest.ini`; `integration` marker). No shared package, so unit
  tests load the target by file path (`tests/conftest.py::load_module`).
- **Covered:** password hash roundtrip, HL7 PID/PV1 happy path, eligibility response shaping,
  intake schema validation, one integration login→auth→chart-read flow.
- **Deliberate gaps — do NOT "fix" the tests to hide them:** scheduling race untested; IDOR
  prevention is an `xfail` (cross-patient reads currently succeed); HL7 AL1/RXA extraction
  `xfail`; no ROI authorization tests; no input-normalization / dup-patient tests. (RIV-201.)
- **Characterization tests first.** Before refactoring untested code, capture current behavior,
  then change under green.
- **Negative-test rule for PHI/security code** (PR #2 lesson): any redaction, authz or
  sanitization function needs at least one **adversarial** test — the input placed where the code
  does *not* expect it (PHI in a non-PHI key, an SSN inside a free-text/list field, a request that
  skips the happy path). The `consents` leak shipped green because every redaction test asserted
  the *intended* shape. Anything writing a payload to a log also needs an **end-to-end scan test**:
  PHI into every field incl. non-PHI keys and list items, call the real log-formatting path, assert
  no raw PHI survives — `tests/test_redaction.py::test_safe_log_payload_masks_phi_in_every_field`.
- Run `/security-review` (or a local adversarial pass) on the diff **before** opening a PR that
  touches auth/PHI/ROI — the review bot caught both PR #2 leaks only after push.

## 6. Landmines and do-not-touch zones

> Most valuable section. Read before editing anything risky. Sourced from `ARCHITECTURE.md §7`.

- ⚠️ **Auth / sessions** (`services/gateway/`, `security.py`, `auth.yaml`) — `users` holds
  PBKDF2-SHA256 hashes; login stores `session:<token>` in Redis with **no TTL, so sessions never
  expire**; MFA off. Since ADR 0017 every session-protected gateway route requires a role
  capability (`require_capability`; roles `front_desk`/`clinician`/`roi_clerk`/`admin`), but the
  deprecated `staff` role — every pre-RBAC DB row — keeps every capability, and the policy map in
  `services/gateway/authz.py` is test-pinned to `config/roles.yaml`. **Never change auth
  behavior without explicit human approval.** Where the boundary actually is, since this was
  misread once: it is `require_session` and what the **gateway** accepts. A cookie between a
  browser and one of our own BFFs, where the BFF still sends `Authorization: Bearer` onward, does
  not cross it (ADR 0014); making `require_session` accept a cookie does, and stays approval-gated.
- ⚠️ **IDOR on chart reads** — `GET /patients/{id}/records` requires a session but never binds it
  to `{patient_id}`; IDs are sequential and walkable. Intentional gap, documented in code.
- ⚠️ **Domain services are network-internal** (D15, ADR 0016) — no domain service has auth of its
  own; the gateway is the only session check, so 8071–8076 are `expose`-only and host publishing
  is a closed allowlist in `tests/test_compose_topology.py`. Do not add `ports:` to a service (or
  a new one) without an ADR + allowlist edit; local debugging uses `docker compose exec` or a
  gitignored `docker-compose.override.yml`.
- ⚠️ **ROI has no authorization enforcement** — disclosures go out with no recorded 45 CFR 164.508
  authorization and no accounting trail. Touches PHI + compliance.
- ⚠️ **PHI handling** — `ssn`, `notes` etc. stored as plaintext `TEXT`; intake logs full bodies at
  INFO. Compliance posture is self-asserted (ADR 0002).
- ⚠️ **Inline eligibility call** (`intake` → `eligibility`) — bounded by PR #11 / ADR 0010 (per-hop
  timeout + in-process circuit breaker; an outage returns `pending`/`unknown`, never a false
  `inactive`), but still on the request thread, and breaker state is per worker. **Do not widen a
  timeout or loosen a breaker threshold without re-reading ADR 0010** — inner and outer values are
  pinned to each other, and `tests/test_eligibility_budget_alignment.py` enforces that.
- ⚠️ **Booking race** (`scheduling-service/book.py`) — check-then-insert, no UNIQUE on `slot_id`,
  no idempotency key → double-booking (RIV-175).
- ⚠️ **Duplicate patients** — self-service intake has no MPI/match key (RIV-160).
- ⚠️ **Brittle HL7 mapping** — only PID/PV1 mapped; AL1 (allergies) and RXA (meds) silently
  dropped (RIV-160).
- ⚠️ **Secrets in git history** — `.env` was committed in the past; it is gitignored and untracked
  now, but the old secrets **remain in git history** (rotation + scrub pending). CI's `gitleaks`
  job runs `--no-git`, so it guards against *recurrence* in the tracked tree and does not scan
  history; there is still no dependency or image vulnerability scan. Do not add more secrets; flag
  before rotating.
- ⚠️ **Schema/migrations are hand-synced** — no migration runner; on a fresh volume only
  `schema.sql` runs. A mismatch breaks fresh-volume boots vs. existing dbs.
- **Never edit without explicit human approval:** auth, PHI columns, ROI/disclosure logic,
  migrations, `.env`/secrets.

## 7. Safety rules for changes

- Make the **smallest change that solves the problem**, and do not widen scope past what was asked
  — park the tangent instead (§11).
- If you touch the schema, update **both** `db/schema.sql` and a new `db/migrations/00N_*.sql`.
- Do not delete code that looks unused — confirm via call-site search first (routes wire in
  `app.py`; frontend calls via `app/lib/gateway.ts`).
- Do not modify public API contracts or config defaults without flagging first. Prefer feature
  flags / additive changes over modifying existing behavior in place.
- After changes, run the §3 checks (unit tests + relevant service import smoke) and report results.

## 9. Known debt

*(§8, a glossary of standard terms — BFF, ROI, HL7/ADT/ORU/PID/PV1, MPI, PHI, 45 CFR 164.508,
X12 270/271 — was removed; numbering left intact so external references still resolve.)*

The four client asks (`docs/handover/jira-tickets.md`) map onto known gaps. `docs/debt-log.md` has
the **worked** entries in detail (D1, D1b, D3b, D4, D5a/b, D6, D8, D11, D12); the full D1–D14
curriculum taxonomy and the week→debt mapping live in project memory `curriculum-arc`. This table
indexes both — several IDs appear nowhere else in the repo, so do not thin it to a pointer.

| Gap | Status |
|-----|--------|
| **RIV-088 / RIV-141** slow/freezing intake ← inline eligibility call (D4, W3) | ~ partly closed by PR #11 / ADR 0010; verification still runs on the `/intake` request thread, and gateway `proxy_intake` still uses the error-swallowing `_post` |
| **RIV-160** allergy differs per chart ← no MPI (D5a, W2) and HL7 AL1 dropped (D6, W6) | open |
| **RIV-175** double confirmations ← booking race, no UNIQUE/idempotency (D5b, W5) | open, spec-only |
| **IDOR** cross-patient chart reads succeed; sessions not patient-bound (D11, W4) | open |
| **ROI authz** no 45 CFR 164.508 enforcement, no accounting of disclosures (D12, W9/W10) | open |
| **Compliance** plaintext PHI (D3), PHI in logs (D1), mutable non-tamper-evident audit log (D2) | open (W1 logs / W10 append-only trail) |
| **Auth** no session expiry (D10), single role / no segregation of duties (D8), no MFA | ~ D8 partly closed by ADR 0017 (four roles + gateway capability enforcement; `staff` compat rows keep every capability); D10 and MFA open (W4 / W9) |
| **CI** `gitleaks` guards recurrence only (`--no-git`); no dependency or image scan; old `.env` secrets still in git history (D9, W1) | partly closed |
| **N+1 / full-table scans** in records read/search paths (D8, W4) | open |
| **RIV-201** thin security/auth test coverage overall | open |
| **AI output guardrail** ungrounded LLM summary; hallucinated clinical content (e.g. "continue metformin" for a no-meds patient) reaches clinicians unchecked (W7) | open |
| **PHI to vendor** full encounter `{name,dob,mrn,notes}` to a cloud LLM on SaaS ToS, no BAA (D13); the "de-identified" export drops only `name`, leaving 17/18 Safe-Harbor identifiers (D14) (W8) | open |

## 10. Working agreements

### 10.1 One source of truth per instruction

- **An instruction lives in exactly one place.** If `.claude/skills/` owns how a step is done, this
  file points at the skill rather than restating it. If a skill and this file disagree, **the skill
  wins** on how-to, and the disagreement is a bug to fix immediately in whichever file is behind.
  (Duplication cost a review round on 2026-07-27: one instruction, two files, only one maintained,
  and the shorter more confident copy won.)
- **`.claude/` is gitignored and untracked** (2026-07-30), so tooling is identical on every branch.
  Backup: `../.riverbend-tooling-snapshots/` — its own git repo, deliberately outside this
  directory; `snapshot.sh` fires on Claude Code **SessionEnd**, `restore.sh <ref>` restores
  point-in-time. It also covers the memory base and the gitignored `scripts/`; `.env*` excluded.
  That repo's `README.md` owns the mechanics and holds the canonical `.git/hooks/pre-commit` guard.
- This file is tracked but snapshotted too (under `project/`), so mid-process edits survive a
  `checkout`/`stash`/`reset --hard`. Let the commit ride the next PR; `snapshot.sh` nags meanwhile.
- **Untrack with `git rm -r --cached`, never `git rm`.** Both stage an identical deletion, so the
  diff and the review look the same — but `git rm` also unlinks the file. PR #20 wiped the entire
  tooling tree that way. Verify files are still on disk before committing. A `.git/hooks/pre-commit`
  guard blocks the combination (staged deletion + newly ignored + absent from working tree) and
  prints the recovery recipe; bypass with `ALLOW_IGNORE_DELETE=1` when the deletion is intended.
- **`git clean -xfd` deletes ignored files**, so it removes all of `.claude/` — survivable only
  back to the last snapshot commit.
- **A fresh clone has no tooling**, and **CI cannot see or run any of it.** Anything that must gate
  a merge belongs in `.github/workflows/` or the `Makefile`; a hook-only check is advisory.

### 10.2 Delegating to subagents

Delegate only when a subagent buys something this thread cannot get itself: **parallelism**,
**isolation** (a reviewer that never saw the reasoning which produced the diff, so it cannot
inherit that reasoning's blind spots), or **breadth**. Not for token thrift. **Cap at one; do not
fan out** — this model delegates readily, so the cap is the lever that matters.

| Need | Use | Notes |
|------|-----|-------|
| Pre-push adversarial diff review | one `general-purpose` pass with the briefing pack | `verify-stack` §6 is authoritative |
| Locate code / call sites | `caveman:cavecrew-investigator` or `Explore` | read-only |
| Bounded 1–2 file edit | `caveman:cavecrew-builder` | refuses 3+ file scope |
| Ad-hoc mid-development diff review | `caveman:cavecrew-reviewer` | **not** a pre-push gate — retired from that role 2026-07-25 (78k tokens, 0 findings, missed every real defect) |

**Authorisation.** Sessions may run under a standing "don't spawn subagents unless asked" rule. A
skill or command that instructs a subagent step **is** that authorisation for that step
(`verify-stack`'s adversarial diff review is the standing example). Otherwise ask before fanning
out. **Brief every review subagent with the facts-only pack** (`verify-stack` §6): verbatim diff,
touched-file inventory, `file:line` call-site map, what each changed branch returns and what its
callers do with it, tests already covering the surface. Forbid orientation greps; cap the finding
count, never the finding length. Withhold every conclusion — *facts, not verdicts*.

### 10.3 Brownfield discipline

- **Read before you write.** Inherited code encodes decisions that look strange but have reasons;
  removing a "weird" timeout/retry/duplication silently re-introduces the bug it was patching.
- **Match existing conventions over personal preference** — a change should look like it belongs.
- **Land changes at seams, not load-bearing walls.** A *seam* is a single-responsibility function
  called in few places, a config/registry extension point, or a new file wired in at one spot. A
  *wall* is imported by many modules or frequent in `git log` (`services/gateway/app.py` is the
  standing example). Earn the right to touch a wall.

### 10.4 Conventions

- **Commit messages: no `Co-Authored-By` trailer.** This overrides any default.
- Conventional Commits (`feat`/`fix`/`docs`/`chore`/`test` + scope).
- Sessions may run in **caveman mode** (terse chat). Substance and exactness stay, and code,
  commits, PRs, ADRs and security/irreversible-action warnings are always normal prose.
- **Calibrate the length of written deliverables.** ADRs, specs and reports here should be as short
  as the decision allows — length is not thoroughness. Chat verbosity is a separate control: reduce
  it explicitly, not by lowering reasoning effort.

## 11. Focus and flow

- **Parking lot.** Capture tangents without asking — say "Parked that", append to `docs/todo.md`,
  continue the current task.
- **Name scope creep, park it, don't debate it.** If the work is growing mid-flight, say so in one
  line and park the expansion rather than negotiating it.
- **Context-switch snapshot.** On "switching to X" / "brb", dump current task state — what's done,
  what's next, files touched, open decision — so a parallel session can pick it up. `/dashboard`
  re-derives *engagement* status from the repo and does not capture in-flight task state.
- **Lead with a recommendation, not an open question.** Give the call plus the one-line reason;
  surface alternatives only when they would change the work.
