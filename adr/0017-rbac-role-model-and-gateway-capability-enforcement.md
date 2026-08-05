# ADR 0017 — RBAC: four real roles, capability enforcement at the gateway, `staff` kept as a full-capability compatibility role

**Status:** Accepted
**Date:** 2026-08-02
**Author:** Riverbend engagement team
**Debt:** D8 (weak authz / no segregation of duties), D7 (minimum necessary unenforced) — the
client's payer-audit ask (`docs/handover/jira-tickets.md`, W9 row). Spec: `docs/specs/rbac.md`.

## Context

Every account holds the single `staff` role and the gateway checks only "is logged in"
(`require_session`). CLAUDE.md §6: "a single `staff` role for everyone; no per-action authz."
Codex review of PR #26 raised the concrete instance three rounds running — `GET /schedule`
enforces no `schedule.read` — and the standing refutation was structural: with one role, a
capability check denies nobody and its regression test cannot fail. `docs/specs/w4.md` §3.1
then named the capability each cross-patient read would require, on three measured facts:
`config/roles.yaml` is read by no code, the session hash already carries `role`
(`services/gateway/security.py`), and the whole enforcement surface is the set of
`Depends(require_session)` routes in one file. The user ruled on 2026-08-02: pull the role
model forward now, as its own PR from main, with enforcement going straight to 403 — the seeded
users are fake, so a shadow mode would protect nobody. This is an auth-behaviour change under
CLAUDE.md §6; the approval is routed through this PR's review (recorded on PR #26).

## Decision

### 1. Role vocabulary

Four real roles — `front_desk`, `clinician`, `roi_clerk`, `admin` — plus `staff`, kept as a
**deprecated compatibility role holding every capability**. `users.role` defaults to `'staff'`
and every pre-RBAC row carries it, so existing databases change behaviour in no way; only the
four real roles can be denied anything. No schema change: `users.role TEXT NOT NULL DEFAULT
'staff'` already exists, and only seeded *values* change (fresh volumes only).

### 2. Capability matrix (minimum necessary, 45 CFR 164.502(b))

14 capabilities; the vocabulary extends `roles.yaml`'s original seven with the names
`docs/specs/w4.md` §3.1 allocated (`records.search`, `schedule.read`) plus `profile.read`,
`eligibility.check`, `disclosures.write`, `ai.use`, `hl7.ingest`.

| Capability | front_desk | clinician | roi_clerk | admin | staff |
|---|---|---|---|---|---|
| profile.read | ✓ | ✓ | ✓ | ✓ | ✓ |
| patients.read | ✓ | ✓ | ✓ | ✓ | ✓ |
| patients.write | ✓ | | | ✓ | ✓ |
| records.read | | ✓ | ✓ | ✓ | ✓ |
| records.search | | ✓ | | ✓ | ✓ |
| records.write | | | | ✓ | ✓ |
| billing.read | | | | ✓ | ✓ |
| eligibility.check | ✓ | | | ✓ | ✓ |
| schedule.read | ✓ | ✓ | | ✓ | ✓ |
| appointments.write | ✓ | | | ✓ | ✓ |
| disclosures.read | | | ✓ | ✓ | ✓ |
| disclosures.write | | | ✓ | ✓ | ✓ |
| ai.use | ✓ | | | ✓ | ✓ |
| hl7.ingest | | | | ✓ | ✓ |

The judged lines: front desk registers, verifies insurance and books but reads no charts —
`records.read`/`records.search` return clinical notes, which registration does not need. The
ROI clerk reads records (compiling disclosure packets is the job) but cannot register or book.
Clinicians read and search but do not register patients or book (schedulers do). Both AI
surfaces (`/ai/intake-instructions`, `/ai/visit-chat`) are front-desk workflow tools (ADR 0007,
ADR 0011), so `ai.use` sits with `front_desk`. `billing.read` and `records.write` are granted
to `admin`/`staff` only and are currently mapped to no route — kept so the declared vocabulary
does not shrink beneath the file's pre-RBAC grants.

### 3. Enforcement: `require_capability` at the gateway, nowhere else

A `require_capability(name)` dependency factory in `services/gateway/app.py` wraps
`require_session`: anonymous callers still 401 first; a session whose role lacks the capability
gets **403 before any downstream fan-out**, with the detail naming the missing capability (an
internal identifier, no PHI). Wired on **all 17 session-protected routes** — the 14 direct
proxies, both AI rate-limit dependencies (capability denial precedes quota consumption), and
`/hl7/ingest`. Domain services stay auth-free: the gateway is the sole boundary (ADR 0016), and
per-service checks would need the shared library ADR 0001 rejected.

Invariants, each pinned by `tests/test_gateway_authz.py`:

- **Declared = enforced.** The executing map lives in `services/gateway/authz.py`;
  `config/roles.yaml` stays the declared copy. `test_roles_yaml_matches_enforced_map` pins them
  equal (same discipline as the payer-prefix catalog and the eligibility budget alignment).
- **Total coverage against a closed list.** Every route carries exactly one capability or sits
  on the closed public list `{/login, /logout, /healthz}` — a new route cannot ship unprotected
  by omission (`test_no_route_outside_the_public_allowlist_is_uncapped`).
- **Unknown role ⇒ zero capabilities ⇒ 403.** Never a 500, never a default grant
  (`test_unknown_or_missing_role_fails_closed_as_403`). Observable as a 403 plus a WARNING log
  naming user, role and capability.
- **Unknown capability name ⇒ boot failure.** A typo'd name on a route would deny everyone
  fail-closed but *silently*; `require_capability` raises at import instead, which a compose
  healthcheck turns red (`fail-closed-guards-must-be-observable`).

### 4. Straight to 403 — no shadow mode

Every seeded account is fake and `staff` keeps every capability, so the only deniable
principals are the new roles this PR itself seeds. A log-only flag would therefore observe
nothing a test does not already prove, while adding a config knob whose "off" state is the
fail-open deploy default this repo has shipped wrong before
(`fail-closed-guard-test-the-default-deploy-state`).

## Alternatives considered

- **Gateway parses `config/roles.yaml` at runtime.** Rejected: needs PyYAML in the image, a
  compose mount (the build context is `services/gateway/` only), and a missing/malformed-file
  failure mode at boot — engineering for zero behavioural gain over a pinning test that already
  fails the suite on drift.
- **Shadow / log-only rollout.** Rejected — §4 above; nobody real can be denied.
- **Route-path exemption lists** (bind everything, exempt `/records/search` etc.). Rejected by
  `docs/specs/w4.md` §3.1: that is the shape a later week rewrites; naming capabilities is the
  shape it populates.
- **Enforce only the routes reviews complained about** (`schedule.read` on `/schedule`).
  Rejected: partial coverage leaves the "which routes are protected" question open every future
  round; the closed-allowlist invariant is only writable when coverage is total.
- **Per-account role UPDATE migration for existing databases.** Deferred, not rejected —
  reassigning real accounts is a client decision (spec §8 open decision 1); seed-only
  assignment carries no lockout risk.

## How this serves the client and domain

The payer audit asked for least privilege; this gives the auditor a one-file, test-pinned
role→capability matrix and a 403 with a named capability at the single enforcement point. Front
desk keeps its whole workflow (register, verify, book, AI tools) while losing chart and
disclosure access it never needed — minimum necessary becomes enforced fact rather than policy
prose.

## Accepted tradeoffs / deferred gaps

1. **`staff` still holds everything.** Deliberate compatibility: existing volumes keep working
   with zero behaviour change. Closes when accounts are reassigned (spec §8 #1) and `staff` is
   retired.
2. **No patient bind (D11).** A clinician with `records.read` still reads *any* chart; the IDOR
   xfail stays xfail (its wording now names the capability precondition). W4 owns the bind.
3. **ROI 164.508 (D12) untouched.** `disclosures.*` gates *who* may use ROI routes; no
   per-disclosure authorization record or accounting exists. W9/W10 own it.
4. **Sessions still never expire (D10), MFA still off.** Out of scope; §6-gated separately.
5. **Legacy portal UX on fresh volumes:** any legacy page outside the account's new role now
   403s — `frontdesk` on records, clinicians on intake and booking, `roiclerk` on eligibility
   and slots. The legacy UI surfaces these as plain errors (`!res.ok` is checked; the 403 is
   not masked). Accepted — the Next.js portal is deliberately unpatched (`docs/debt-log.md`)
   and existing dev volumes are unaffected.
6. **Role changes need a gateway restart** (policy is in code). Acceptable at this scale; a
   runtime store is a future decision if roles become operator-editable.
7. **A role change does not reach already-issued sessions.** `require_capability` reads the
   role frozen into the session hash at login, and sessions never expire (D10) — so an
   `UPDATE users SET role=…` is a silent no-op for every outstanding token,
   including any portal token persisted in `localStorage`, until re-login or explicit
   session invalidation. Any real-account reassignment must therefore ship with session
   invalidation (or the D10 TTL) to be enforceable; recorded on the spec's open decision.
8. **Denials are logged per hit with no dedupe or cap.** A valid low-privilege token can loop
   a denied route and emit unbounded WARNING lines (denials deliberately cost no AI quota —
   the capability check precedes the counter). Bounded: accounts are staff-provisioned, no
   self-service signup writes `users`; revisit if a user-creation route ever lands.

## Consequences

New `services/gateway/authz.py` (policy seam) and `require_capability` in `app.py`; rewritten
`config/roles.yaml` (now with a pinned enforced twin); seed assigns real roles (fresh volumes
only); `GET /me` requires `profile.read`, which every role holds. Fresh-deploy default:
`users.role` still defaults to `'staff'` — a row inserted outside the seed gets full
capability, which is the documented compat posture, not an accident. `GET /me` now returns a
real role, which any future role-aware UI can read — no portal reads it today. Tests holding the
line: `tests/test_gateway_authz.py` (27 tests: pinning, coverage, denials, fail-closed,
grants); `tests/integration/test_records_flow.py` re-actors chart reads to a clinician login
and adds the front-desk 403 (needs a volume seeded on or after this ADR).
