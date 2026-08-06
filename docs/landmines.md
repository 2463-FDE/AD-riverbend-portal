# Landmines, safety rules, and the negative-test rule

> **Read this before editing anything risky.** This is a HIPAA covered entity's production
> codebase, inherited from an outside contractor. Many things that look like bugs are documented,
> intentional gaps — check §1 before "fixing" weirdness, and check `docs/debt-log.md` for the
> worked entries behind each one.
>
> **This file is the tracked source of truth for the three rules below.** `CONTRIBUTING.md`, the
> PR template, `adr/_template.md` and `docs/specs/_template.md` all cite it and none of them
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
  `/patients/{id}/records` alone. **And the set includes a path that needs no ids at all**
  (measured 2026-08-06): `q` reaches the search pattern un-escaped
  (`services/records-service/app.py:48,159`), so `GET /records/search?q=%25` is a bare `%`
  wildcard that matches every row and returns full `Record.body` for all of them, unbounded by any
  `LIMIT`. Sizing the fix against "sequential ids are walkable" alone under-scopes it by the whole
  corpus. Detail and candidate fixes in `docs/debt-log.md` D11.
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
- ⚠️ **Duplicate patients** — self-service intake has no MPI or match key (RIV-160).
- ⚠️ **Brittle HL7 mapping** — only PID and PV1 are mapped; AL1 (allergies) and RXA (meds) are
  silently dropped (RIV-160).
- ⚠️ **Secrets in git history** — `.env` was committed in the past. It is gitignored and untracked
  now, but the old secrets **remain in git history** (rotation and scrub pending). CI's `gitleaks`
  job runs `--no-git`, so it guards against *recurrence* in the tracked tree and does not scan
  history; there is still no dependency or image vulnerability scan. Do not add more secrets, and
  flag before rotating.
- ⚠️ **Schema and migrations are hand-synced** — there is no migration runner, and on a fresh
  volume only `db/schema.sql` runs. A mismatch breaks fresh-volume boots against existing
  databases.
- ⚠️ **Intake registration is broken and reports success** — the portal's payload 422s at
  intake-service, the gateway relays it as HTTP 200, and the UI prints a success message with no
  patient row created. Inherited from handoff commit `3663c4b`, unscheduled, and **deliberately
  not patched piecemeal**: the fix touches the gateway's error handling (the open half of D4) and
  widens a consent enum, so it is approval-gated. Full analysis in `docs/debt-log.md`.

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
  tests, and no input-normalization or duplicate-patient tests (RIV-201). A push hook pins the
  expected xfail and deselected counts; if one moves, the gap moved, and that is a finding rather
  than a number to update.
- Run an adversarial pass over the diff **before** opening a PR that touches auth, PHI or ROI. The
  review bot caught both PR #2 leaks only after push.
