# Landmines, safety rules, and the negative-test rule

> **Read this before editing anything risky.** This is a HIPAA covered entity's production
> codebase, inherited from an outside contractor. Many things that look like bugs are documented,
> intentional gaps — check §1 before "fixing" weirdness, and check `docs/debt-log.md` for the
> worked entries behind each one.
>
> **This file is the tracked source of truth for the three rules below.** `CONTRIBUTING.md`, the
> PR template, `adr/_template.md` and `docs/specs-deprecated/_template.md` all cite it and none of them
> restate it. Anything that paraphrases these rules somewhere else is a bug to fix here, not
> there. Landmine §1 was previously carried in `CLAUDE.md` §6 and moved here on 2026-08-05 when
> that file was untracked — a required rule cannot live in a file a fresh clone does not have.

## 1. Do-not-touch zones

Sourced from `ARCHITECTURE.md` §7 and the handoff docs.

- ⚠️ **Auth / sessions** (`services/gateway/`, `security.py`, `auth.yaml`) — `users` holds
  PBKDF2-SHA256 hashes; login stores `session:<token>` in Redis with **no TTL, so sessions never
  expire**; MFA is off. Since ADR 0017 every session-protected gateway route requires a role
  capability (`require_capability`; roles `front_desk` / `clinician` / `roi_clerk` / `admin`), but
  the deprecated `staff` role — every pre-RBAC DB row — keeps every capability, and the policy map
  in `services/gateway/authz.py` is test-pinned to `config/roles.yaml`. **Never change auth
  behaviour without explicit human approval.** Where the boundary actually is, since this was
  misread once: it is `require_session` and what the **gateway** accepts. A cookie between a
  browser and one of our own BFFs, where the BFF still sends `Authorization: Bearer` onward, does
  not cross it (ADR 0014); making `require_session` accept a cookie does, and stays
  approval-gated. ⚠️ **`auth.yaml` is declarative only — nothing parses it** (measured
  2026-08-06). The never-expire behaviour is hardcoded in `security.py:275-279`, and
  `password_min_length: 6` is enforced **nowhere** — no length check exists on any login or
  user-creation path, so the file asserts a control the system does not have. Read it as a record
  of intent, never as evidence of behaviour, and do not answer a session or password finding by
  editing it: the change would be inert.
- ⚠️ **IDOR on chart reads** — `GET /patients/{id}/records` requires a session but never binds it
  to `{patient_id}`; ids are sequential and walkable. Intentional gap, documented in code (D11).
  **Cross-patient reads are not only reachable by walking ids:** `GET /patients`,
  `GET /records/search?q=` and `GET /roi/requests` (`patient_id` optional) each return PHI across
  patients. Since ADR 0017 each requires its role capability (`records.search`,
  `disclosures.read`), but **a capability is not a patient bind** — these reads are cross-patient
  by construction — so the D11 fix must be sized against this whole set, not against
  `/patients/{id}/records` alone. **And the set included a path that needed no ids at all**
  (measured 2026-08-06; the metacharacter-and-bound vector **closed by e6 2026-08-16**): `q`
  reached the search pattern un-escaped (`services/records-service/app.py:339`, and the
  patient-name filter at `:51-53`), so `GET /records/search?q=%25` was a bare `%`
  wildcard that matched every row and returned full `Record.body` for all of them, unbounded by any
  `LIMIT`. e6 escapes the LIKE metacharacters at both sites and bounds the result set
  (e6-SPEC-1/2/5), closing that vector; the IDOR itself is not closed — these reads are still
  cross-patient by construction and sessions are still not patient-bound, so the D11 fix is still
  sized against this whole set. **The sized set is now the `swept 23-route` table in
  `docs/research/w4-findings.md`** — a classification-complete sweep of every gateway `@app.`
  route (13 in-set), pinned by `tests/test_w4_exposure_sweep.py` so a route added or missed
  reddens the suite; `GET /patients`, `GET /records/search?q=` and `GET /roi/requests` above stay
  the named by-construction examples (w4-D-23). Detail and candidate fixes in `docs/debt-log.md` D11.
- ⚠️ **Domain services are network-internal** (D15, ADR 0016) — no domain service has auth of its
  own; the gateway is the only session check, so 8071–8076 are `expose`-only and host publishing
  is a closed allowlist in `tests/test_compose_topology.py`. Do not add `ports:` to a service (or
  to a new one) without an ADR plus an allowlist edit; local debugging uses `docker compose exec`
  or a gitignored `docker-compose.override.yml`.
- ⚠️ **ROI has no authorization enforcement** — disclosures go out with no recorded 45 CFR 164.508
  authorization and no accounting trail (D12). Touches PHI and compliance.
- ⚠️ **PHI handling** — `ssn`, `notes` and similar are stored as plaintext `TEXT` (D3); intake
  logs full request bodies at INFO (D1). The compliance posture is self-asserted (ADR 0002).
- ⚠️ **Inline eligibility call** (`intake` → `eligibility`) — bounded by PR #11 / ADR 0010 (per-hop
  timeout plus an in-process circuit breaker; an outage returns `pending`/`unknown`, never a false
  `inactive`), but still on the request thread, and breaker state is per worker. **Do not widen a
  timeout or loosen a breaker threshold without re-reading ADR 0010** — the inner and outer values
  are pinned to each other, and `tests/test_eligibility_budget_alignment.py` enforces it.
- ⚠️ **Booking race** (`services/scheduling-service/book.py`) — check-then-insert, no UNIQUE on
  `slot_id`, no idempotency key, so concurrent requests double-book (RIV-175).
- ⚠️ **Duplicate patients** — intake now evaluates an ADR 0005 tier-1 match key at create
  (normalized SSN + corroborating demographics) and queues candidate pairs for front-desk review;
  it still merges nothing, and there is still no MPI. Tier 2 (fuzzy name + DOB where the SSN is
  missing or invalid) is deferred, so duplicates without a usable SSN go undetected. Existing
  duplicates stay split until Health Information Management merges them by hand (RIV-160).
- ⚠️ **Brittle HL7 mapping** — only PID and PV1 are mapped; AL1 (allergies) and RXA (meds) are
  silently dropped (RIV-160).
- ⚠️ **Secrets in git history** — `.env` was committed in the past. It is gitignored and untracked
  now, but the old secrets **remain in git history** (rotation and scrub pending). CI's `gitleaks`
  job runs `--no-git`, so it guards against *recurrence* in the tracked tree and does not scan
  history; there is still no dependency or image vulnerability scan. Do not add more secrets, and
  flag before rotating.
- ⚠️ **Schema and migrations are hand-synced** — `db/schema.sql` and `db/migrations/*.sql` are
  kept in sync by hand; since e6 a runner (`db/migrate.py`, `make migrate`) applies the migration
  files to an existing volume, and on a fresh volume only `db/schema.sql` runs. A mismatch breaks
  fresh-volume boots against existing databases; `tests/integration/test_schema_upgrade_path.py`
  pins the hand-sync structurally (e6-SPEC-14).
- ⚠️ **Intake registration — fixed 2026-08-10 (`e4`), and the guards are load-bearing.** It used
  to 422 at intake-service, relay as HTTP 200, and print success with no patient row created
  (inherited from handoff commit `3663c4b`). Two of the pieces that fixed it are things you must
  not quietly change: `ConsentKind` is a **documented PHI control** — a closed five-value enum
  pinned by test, and widening it is approval-gated; and `proxy_intake` is the one gateway route
  on `_post_checked`, so putting it back on `_post` restores a 200-for-a-failure contract the
  portal branches on. The payload shape is declared once in `contracts/intake-registration.json`
  and asserted from both suites — edit the declaration, not one side of it.
  **The other thirteen `_post`/`_get` proxy routes were converted 2026-08-11 (`e5`,
  owner-approved) and both swallowing helpers were deleted**, closing D4's estate-wide half. What
  is gated now is the reverse: reintroducing a helper that answers a failure with a success, or
  adding a fan-out route that uses neither checked helper —
  `tests/test_gateway_proxy_error_contract.py` fails both. Full analysis in `docs/debt-log.md`.

**Never edit without explicit human approval:** auth, PHI columns, ROI / disclosure logic,
migrations, and `.env` or any secret file.

## 2. Safety rules for changes

- Make the **smallest change that solves the problem**, and do not widen scope past what was
  asked — park the tangent in `docs/todo.md` instead.
- If you touch the schema, update **both** `db/schema.sql` and a new `db/migrations/00N_*.sql`.
- Do not delete code that looks unused — confirm with a call-site search first. Routes wire up in
  each service's `app.py`; the frontend calls through `frontend/app/lib/gateway.ts`.
- Do not modify public API contracts or config defaults without flagging first. Prefer feature
  flags and additive changes over modifying existing behaviour in place.
- **Read before you write.** Inherited code encodes decisions that look strange but have reasons;
  removing a "weird" timeout, retry or duplication silently reintroduces the bug it was patching.
- **Match existing conventions over personal preference** — a change should look like it belongs.
  There is no shared Python library: every service repeats the same
  `config` / `db` / `models` / `schemas` / `logging_config` / `app` layout (ADR 0001), and new
  code matches it exactly.
- **Land changes at seams, not load-bearing walls.** A *seam* is a single-responsibility function
  called in few places, a config or registry extension point, or a new file wired in at one spot.
  A *wall* is imported by many modules or frequent in `git log` — `services/gateway/app.py` is the
  standing example. `docs/onboarding-seam-map.md` names the six safe extension points and the
  eight walls, with the reason for each.
- After changes, run the checks in the `Makefile` (unit tests plus the relevant service import
  smoke) and report the results.

## 3. The negative-test rule for PHI and security code

The lesson is from PR #2, where a `consents` leak shipped green because every redaction test
asserted the *intended* shape.

- Any redaction, authz or sanitization function needs at least one **adversarial** test — the
  input placed where the code does *not* expect it: PHI in a non-PHI key, an SSN inside a
  free-text or list field, a request that skips the happy path.
- Anything that writes a payload to a log also needs an **end-to-end scan test**: PHI into every
  field including non-PHI keys and list items, call the real log-formatting path, and assert no
  raw PHI survives. The worked example is
  `tests/test_redaction.py::test_safe_log_payload_masks_phi_in_every_field`.
- **Characterization tests first.** Before refactoring untested code, capture the current
  behaviour, then change under green.
- **Do not "fix" the tests to hide a deliberate gap.** These are teaching defects and are meant to
  stay visible: the scheduling race is untested, IDOR prevention is an `xfail` (cross-patient
  reads currently succeed), HL7 AL1/RXA extraction is an `xfail`, there are no ROI authorization
  tests, and no input-normalization tests (RIV-201). A push hook pins the
  expected xfail and deselected counts; if one moves, the gap moved, and that is a finding rather
  than a number to update.
  The **duplicate-patient half of that clause closed deliberately in W2** (ADR 0005 tier 1):
  `tests/test_matching_parity.py`, `tests/test_intake_match_key.py` and `tests/test_retro_match.py`
  now cover it. A moved gap is itself a reportable event, so the closure is named here and in the
  W2 PR body (`docs/workflow/w2/pr-body.md`) rather than absorbed into a new pass count.
  The input-normalization half stays open: W2 adds no intake input canonicalization — the
  matcher's `normalize_ssn`/`normalize_name` are matcher-side only and never touch what is stored.
- Run an adversarial pass over the diff **before** opening a PR that touches auth, PHI or ROI. The
  review bot caught both PR #2 leaks only after push.
