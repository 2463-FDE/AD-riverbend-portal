# RBAC — role model and gateway capability enforcement

> Standalone spec: the former `w9.md` was deleted with the other speculative week specs
> (W7–W10 asks were pulled prematurely from static course content). This spec covers only the
> parts pulled forward and implemented now; ROI 45 CFR 164.508 authorization, disclosure
> accounting, session TTL and MFA stay with their owning weeks and get IDs when built.
> Capability vocabulary origin: `docs/specs/w4.md` §3.1. Decision record: ADR 0017.

## 0. ID scheme

`RBAC-R<n>`, allocated once and never renumbered or reused.

## 1. Context / client ask

Codex review of PR #26 (round 3, both findings confirmed): the gateway enforces no per-action
authorization — a single `staff` role holds every permission, so a capability check would deny
nobody and the 403 regression test could not be written to fail. The client's payer-audit ask
(`docs/handover/jira-tickets.md`, W9 row: "single `staff` role, no least privilege") owns the
debt. User ruled 2026-08-02: pull the role model forward, enforce on every session-protected
route, keep `staff` fully granted so no existing account changes behaviour.

## 2. Scope

**In scope:** role vocabulary (`config/roles.yaml`), seeded role assignment, gateway capability
resolution, enforcement (403) on every session-protected gateway route.
**Out of scope:** the D11 patient bind (a capability says *what kind* of read a role may do;
binding a session to *which patient* is W4's fix), ROI per-disclosure 164.508 authorization
(D12), session TTL (D10), MFA, any domain-service-side auth (the gateway is the sole boundary —
ADR 0016), portal role-aware UI (`FE-R14`, gate G4).

## 3. Definitions

- **Capability** — a named action grant (`records.read`), the unit routes require.
- **Declared vs enforced policy** — `config/roles.yaml` is the declared copy ops read;
  `services/gateway/authz.py` is the copy the gateway executes. A pinning test keeps them equal.

## 4. Deliverables

`services/gateway/authz.py` · rewritten `config/roles.yaml` · `require_capability` wired on all
17 session-protected routes in `services/gateway/app.py` · role-carrying seed
(`db/seed/generate_seed.py` + regenerated `seed.sql`) · `tests/test_gateway_authz.py` ·
ADR 0017 · this spec.

## 5. Requirements (EARS)

| ID | Requirement | Verification | Debt | Gate |
|---|---|---|---|---|
| `RBAC-R1` | `config/roles.yaml` shall declare the roles `front_desk`, `clinician`, `roi_clerk`, `admin`, `staff`, each with an explicit capability list. | `tests/test_gateway_authz.py::test_roles_yaml_matches_enforced_map` | D8 | PR review |
| `RBAC-R2` | The gateway's enforced role→capability map shall equal the declaration in `config/roles.yaml`. | same test (pinning) | D8 | PR review |
| `RBAC-R3` | WHEN a request reaches a session-protected gateway route, the gateway shall require that route's named capability of the session's role. | `test_route_capability_wiring_is_pinned` + denial/grant tests | D7/D8 | PR review |
| `RBAC-R4` | IF the session's role does not hold the route's capability, THEN the gateway shall answer 403 without any downstream fan-out. | `test_denied_role_gets_403_and_no_fanout` | D7/D8 | PR review |
| `RBAC-R5` | IF the session's role is unknown, missing, or outside the declared set, THEN the gateway shall answer 403 (fail closed, never 500, never a pass). | `test_unknown_or_missing_role_fails_closed_as_403` | D8 | PR review |
| `RBAC-R6` | WHILE a session's role is `staff`, the gateway shall grant every capability (pre-RBAC compatibility). | `test_staff_keeps_every_capability`, `test_granted_role_reaches_the_downstream_proxy` | — (deliberate) | PR review |
| `RBAC-R7` | Every gateway route shall either carry exactly one capability requirement or appear on the closed public-route list (`/login`, `/logout`, `/healthz`). | `test_no_route_outside_the_public_allowlist_is_uncapped` | D8 | PR review |
| `RBAC-R8` | IF a route is wired to a capability name outside the vocabulary, THEN the gateway shall fail at import rather than silently denying everyone. | `test_wiring_a_capability_outside_the_vocabulary_fails_at_import` | — (new scope) | PR review |
| `RBAC-R9` | WHEN the seed is regenerated, seeded demo users shall carry the role matching their job function (registration → `front_desk`, physicians/RN → `clinician`, ROI clerk → `roi_clerk`, IT → `admin`, unmapped functions → `staff`). | inspection of `db/seed/seed.sql` diff (deterministic generator) | D8 | PR review |
| `RBAC-R10` | The role model shall require no schema change (`users.role TEXT NOT NULL DEFAULT 'staff'` already exists; only seeded values change). | `test_default_role_matches_schema_default` + no `db/migrations/` diff in the PR | — | PR review |
| `RBAC-R11` | The all-patient day queue (`GET /schedule`) shall require `schedule.day_queue.read`, granted to `front_desk`/`admin`/`staff` only; `clinician` shall retain `schedule.read` for per-patient schedule reads. (ADR 0017 amendment 2026-08-02, PR #26 r5.) | `test_route_capability_wiring_is_pinned` + clinician `/schedule` denial and clinician `/appointments` grant params | D7 | PR review |

## 6. Checkpoints / gates

| Gate | Blocks | Artifact | Verified how | Signed by |
|---|---|---|---|---|
| CLAUDE.md §6 auth approval | merge | this PR (enforcement is an auth-behaviour change) | PR review — approval routed through PR B's review per the user's 2026-08-02 ruling, recorded on PR #26 | user |

## 7. Relevant landmines

- ⚠️ **Auth / sessions** — "**Never change auth behavior without explicit human approval.**"
  This PR is that change; the approval is this PR's review (ruling above).
- ⚠️ **IDOR on chart reads** — "requires a session but never binds it to `{patient_id}`."
  Unchanged here; RBAC narrows *who* holds `records.read`, not *which patient* it reaches.
- ⚠️ **ROI has no authorization enforcement** — `disclosures.*` capabilities gate who may use
  ROI routes; the missing per-disclosure 164.508 authorization record remains open (D12).

## 8. Open decisions

| # | Decision | Blocks | Unblocked by |
|---|---|---|---|
| 1 | Migrating existing databases' `users.role` values off `staff` (an UPDATE, not a schema change) | retiring the `staff` role | client sign-off on per-account role assignment, **plus session invalidation for affected accounts** — the role is frozen into the session hash at login and sessions never expire (D10), so the UPDATE alone changes nothing for outstanding tokens (ADR 0017 tradeoff #7) |
| 2 | `billing.read` / `records.write` are granted but mapped to no route | nothing | first route needing them names them |

## 9. Traceability

- D8 (weak authz / no segregation of duties) → `RBAC-R1`–`R5`, `R7`, `R9` → `tests/test_gateway_authz.py`
- D7 (minimum necessary unenforced) → `RBAC-R3`/`R4` role matrix (front desk holds no
  `records.read`/`records.search`) and `RBAC-R11` (clinician holds no
  `schedule.day_queue.read`) → denial tests
- `RBAC-R6`, `R8`, `R10` map to no debt ID: deliberate compatibility, new hardening, and a
  factual no-migration constraint respectively.
