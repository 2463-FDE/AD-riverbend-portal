# ADR 0015 — Serve staff and patients from separate origins, and make the origin runtime config

**Status:** Proposed
**Date:** 2026-07-31
**Author:** Riverbend engagement team
**Debt:** none directly — new scope (`docs/specs/frontend-rebuild.md` §8 #16, `FE-R30`–`FE-R31`).
Adjacent to D11 (a patient principal is unsafe until session→`patient_id` binding lands) and to
D10/D1 through the controls ADR 0014 depends on this file to define. It closes none of them.

## Context

Two decisions taken on 2026-07-31 turn out to depend on a fact nobody had written down: which origin
the portal is served from.

- `adr/0014` §1 sets the session cookie `Secure`. Whether that is correct, harmless or silently fatal
  depends entirely on the scheme in the address bar.
- `adr/0014` §2 relies on SvelteKit's `csrf.checkOrigin`, which compares a request's `Origin` header
  against the app's own origin. Under `adapter-node` behind a reverse proxy, the server only knows its
  public origin if it is told.

Neither ADR 0012, 0013, 0014 nor `docs/specs/frontend-rebuild.md` mentions transport security, a
hostname, or `ORIGIN`. What the repository does contain, measured 2026-07-31:

- **No TLS anywhere in the stack we ship.** `docker-compose.yml` has no reverse proxy, no certificate
  handling, and no `https` reference; the existing frontend service publishes plain `3070:3070`
  (`docker-compose.yml:219-227`).
- **Production is HTTPS on a hostname.** The handoff QA capture records
  `https://portal.riverbend.example.com/api/patients/1042/records`
  (`docs/handover/portal.har:11`) — so TLS is terminated by infrastructure that exists outside this
  repository and is undocumented inside it.
- **The demo runs on `localhost`.** Decided by the user 2026-07-31: the client demo is a screen-share
  of a local stack, which is why `Secure` is not currently a live problem — browsers treat
  `http://localhost` as a secure context.

The second force is the audience question. `docs/specs/frontend-rebuild.md` §8 #16 reopened a
patient-facing surface on 2026-07-31, and §8 #16 already states the consequence this ADR has to
answer:

> a shared origin means an XSS in the patient surface reaches staff credentials, which `FE-R27`
> contains and a separate origin would contain better

`adr/0014` gap #3 prices exactly how much containment `FE-R27` buys, and it is less than it looks:

> Script on the origin cannot read the cookie but can still *use* it, issuing authenticated requests
> from the victim's browser.

Two landmines make that worse here than in an ordinary two-audience app. `CLAUDE.md` §6, verbatim:

> ⚠️ **IDOR on chart reads** — `GET /patients/{id}/records` requires a session but never binds
> it to `{patient_id}`; IDs are sequential and walkable. Intentional gap, documented in code.

> ⚠️ **Auth / sessions** … sessions never expire, single role, no MFA. **Never change auth behavior
> without explicit human approval.**

So a staff credential borrowed by script on a shared origin reads every chart in the network, and
nothing expires it. `config/roles.yaml` also has no non-staff principal, and `users.role` defaults to
`'staff'` (`db/schema.sql:19`).

The reason to decide this now rather than at the patient surface's own phase is that both apps are
unbuilt. Every option below costs approximately nothing today and one of them costs a refactor of a
shipped auth surface later.

## Decision

### 1. Two origins, one gateway

Staff and patients are served from **different hostnames**: `portal.riverbend.example.com` for staff,
`patients.riverbend.example.com` (name subject to the client's DNS) for patients. Two compose
services, two `ORIGIN` values, one gateway behind both.

**Invariant: a patient-facing surface never shares an origin with the staff portal.** Same-origin
hosting would make an XSS in patient pages equivalent to an XSS in the staff portal, which — given
walkable IDs and non-expiring sessions — is network-wide chart access, and `FE-R27` bounds
exfiltration only, not use (ADR 0014 gap #3).

**Splitting by port is not a split.** Cookies match on host and ignore port, so a `Path=/` cookie set
by `localhost:3071` is also sent to `localhost:3070`. Port separation gives the appearance of
isolation with none of the mechanism; it is named here because it is the cheap thing someone reaches
for.

### 2. The cookie is host-only — no `Domain` attribute, ever

`FE-R30`. The session cookie is set without a `Domain` attribute, making it host-only.

**Invariant: no cookie set by either app carries a `Domain` attribute.** Setting
`Domain=.riverbend.example.com` would share the cookie across both hostnames and hand the patient
origin the staff credential — undoing §1 entirely while leaving the hostnames looking separate. This
is the one line that makes §1 real rather than cosmetic, which is why it is a requirement and not a
note.

The two apps also use **distinct cookie names**, so a stray host-wide cookie from any future
subdomain cannot be mistaken for either app's session.

### 3. `ORIGIN` is runtime config, never a build constant

`FE-R31`. Each deployment sets `adapter-node`'s `ORIGIN` environment variable — or
`PROTOCOL_HEADER`/`HOST_HEADER` where TLS is terminated upstream.

**Invariant: the origin is resolved at request time from the environment, exactly as `GATEWAY_URL`
is (ADR 0012 §4).** This is the same scar, one variable over: a build-time origin is baked into the
artifact, so the image that passes in dev is wrong in production. `$env/static/private` is the trap;
`$env/dynamic/private` or `process.env` is the mechanism.

Two settings are derived from it rather than stated independently, so they cannot drift out of
agreement with reality:

- **The cookie's `Secure` flag** (ADR 0014 §1) — true whenever `ORIGIN`'s scheme is `https`.
- **`csrf.checkOrigin`'s comparison target** (ADR 0014 §2).

**Fresh-deploy default, and what failure looks like:** compose sets `ORIGIN: http://localhost:3071`
for the local stack, mirroring how `GATEWAY_URL: http://gateway:8070` is already injected. There is
**no production default and no fallback guess** — a deploy that does not set `ORIGIN` gets a service
that fails to start and reports the reason on `GET /healthz` (ADR 0014's Consequences), rather than
one that guesses `localhost` and silently drops every cookie. A wrong origin is not a degraded mode;
it is a login loop with no error message, which is the failure this ADR exists to prevent.

### 4. What this does **not** decide

- **Patient authentication.** Blocked on D11: `GET /patients/{id}/records` checks only "is logged in",
  so a patient account reads every other patient's chart. That bind is W4 analysis and a
  `CLAUDE.md` §6 approval at G4 — and `docs/specs/w4.md:138-139` is explicit that W4's shippable
  output is analysis plus prototype, with the live fix landing later. **Nothing in this ADR makes a
  patient login safe to ship.**
- **The patient principal's place in the role model.** "Patient" is a different principal class, not a
  staff role, so spec §8.3's three tiers do not describe it and `config/roles.yaml` would gain a
  non-staff principal. G4.
- **Who terminates TLS in production, and the real hostnames.** Outside this repository; the open
  question is recorded in Consequences.
- **A Content-Security-Policy for either app.** Separate origins make a stricter patient CSP possible
  without negotiating against staff needs, but no CSP is adopted here (ADR 0014 gap #3 still stands).

### 5. The seam that keeps this cheap

The patient surface lives in **its own directory and its own compose service**, not as a route group
inside `portal/`. Nothing patient-facing is built now — this is only about where it would go.

**Invariant: no patient-facing route is nested inside the staff app's route tree.** Nested, a later
host split is a refactor of a shipped auth surface; separate, it is a deploy change. `CLAUDE.md` §10.3
calls this landing changes at seams rather than load-bearing walls, and the seam is free to place
before either app exists.

ADR 0014's session module stays the **single** holder of the token and the cookie logic. A second app
consumes it as a shared module rather than reimplementing cookie handling — one implementation of the
control, per `CLAUDE.md` §10.1.

## Alternatives considered

| Alternative | Why it lost |
|---|---|
| **Same origin, patient surface under a path** (`portal.…/patient/*`) | The cheapest option, and the one that needs no DNS or compose work — which is why it would win by default if nobody decided. It loses because it makes an XSS in patient pages equivalent to an XSS in the staff portal, and this system is unusually bad at absorbing that: walkable sequential IDs (D11), sessions that never expire (D10), and `FE-R27` containing exfiltration but not use (ADR 0014 gap #3). The saving is one compose service and one DNS name; the exposure is every chart in the network. |
| **Separate port, same host** (`:3071` staff, `:3072` patients) | Rejected on a mechanism, not a preference: **cookies ignore port**, so both apps share one cookie namespace and the "separation" protects nothing that matters. It also reads as isolation to a future maintainer, which makes it worse than the honest same-origin option. |
| **Separate origin *and* a separate gateway or service fleet** | The strongest isolation available, and genuinely better on paper. Rejected as out of all proportion: it duplicates the auth-owning load-bearing wall (`CLAUDE.md` §10.3), and the threat this ADR addresses is browser-side script, which a second gateway does nothing about. |
| **Decide it when the patient surface is actually built** | Consistent with the no-speculative-abstraction rule in spec §2, and it keeps this pass smaller. Rejected for the reason ADR 0014's "do nothing at P2" row was rejected: the login page must choose a cookie shape to exist at all, so deferring is not neutral — it ships a host-wide-capable cookie and a nested route tree by default, and then the fix is a migration instead of a decision. The decision is unavoidable; only its quality is optional. |
| **Build-time dev/prod differentiation** (a `dev` build with relaxed cookie flags, a `prod` build with strict ones) | Considered because it is the intuitive answer to "configure for production", and rejected as a category error: an origin is a property of *serving*, not of *compiling*, so no build flag creates a browser boundary. It also reintroduces exactly the failure ADR 0012 §4 quotes — deployment facts baked into an artifact — and a `dev` build whose cookie flags are relaxed is a build that must never reach production, i.e. a new way to ship an insecure default. Runtime environment config on one identical artifact gets the same result with none of that. |

## How this serves the client and domain

Riverbend gets an answer to the question an auditor asks as soon as patients can log in: what stops a
flaw in the patient-facing pages from reaching staff credentials and, through them, every chart. The
answer is a browser-enforced origin boundary rather than a containment argument about one cookie
attribute. It also gets a portal that fails visibly instead of mysteriously when a deployment is
misconfigured, which is a support-cost saving on a front desk that cannot debug a login loop.

For the front desk and the ROI clerk the change is invisible today: same URL, same behaviour. The cost
is one additional compose service and one DNS name at the point a patient surface ships.

## Accepted tradeoffs / deferred gaps

1. **Production TLS and the real hostnames are unknown [?].** `docs/handover/portal.har:11` shows
   HTTPS on `portal.riverbend.example.com`, but nothing in this repository terminates TLS or records
   who does. Acceptable now because the demo is a `localhost` screen-share and `ORIGIN` makes the
   value a per-deployment setting rather than a code change. **What closes it:** the client naming the
   terminator and the two hostnames. Until then, no production `ORIGIN` default exists — deliberately.
2. **Two origins mean two deployments to keep in step.** A cookie-name change, a session-module
   change or a key rotation has to reach both. Acceptable because the second app does not exist yet
   and §5 keeps the session logic in one shared module. **What would close it:** nothing; this is the
   price of the boundary, and it is smaller than the shared-origin exposure it buys out of.
3. **This ADR does not reduce the XSS risk *within* either app.** A separate origin contains the blast
   radius across audiences; it does nothing about script injected into the staff portal itself. ADR
   0014 gap #3 owns that, and a CSP is still unadopted (§4).
4. **`FE-R30` and `FE-R31` are prohibitions and configuration, which are weak test surfaces.**
   `FE-R30` (no `Domain`) is testable by asserting the `Set-Cookie` header, and it needs the mutation
   check `docs/specs/_template.md` and project memory `thresholds-must-be-reachable` require: add a
   `Domain` deliberately and confirm the test fails. `FE-R31` is verified by inspection plus one
   container check that a non-default `ORIGIN` is honoured at runtime — the same proof ADR 0012 §4's
   rule needs and has never had.
5. **Nothing here is verified against a running system.** No `portal/` exists. Every claim in this ADR
   is about configuration that has not been written, and the `Set-Cookie` and `ORIGIN` behaviours are
   **to be verified against the built image, not assumed** — the same wording ADR 0013's Consequences
   uses for the runtime image, for the same reason.

## Consequences

**New, outside `portal/`:** `docker-compose.yml` gains `ORIGIN` on the portal service beside
`GATEWAY_URL`, and a second frontend service when the patient app is built. `docs/runbook.md` gains
the portal in its health-check block (ADR 0014's Consequences). `.env.example` gains `ORIGIN` with the
local value and a comment stating there is no production default.

**New requirements:** `FE-R30` (host-only cookie, no `Domain`) and `FE-R31` (`ORIGIN` from runtime
env) in `docs/specs/frontend-rebuild.md` §5, both at **G2**, because both are properties of the login
surface P2 builds and neither can be retrofitted without touching it.

**No change to any service in `services/`.** The gateway is not edited, `require_session` is not
asked to accept anything new, and no CORS configuration is introduced — ADR 0012 §2's invariant is
what makes a second browser-facing app possible without touching the gateway at all.

**Fresh-deploy default:** `ORIGIN: http://localhost:3071` in compose; **no production default**, and
absence is a start-up failure reported on `GET /healthz` rather than a guess.

**Now easier:** adding the patient surface (a directory and a compose service, not a refactor);
giving patients a stricter CSP; reasoning about which app a cookie belongs to.
**Now harder:** running the portal on a bare hostname over HTTP, which now fails visibly instead of
producing a login loop — the intended direction.

**Tests that hold the line once implementation starts:** the `Set-Cookie` assertion for `FE-R30`
(with its mutation proof), the runtime-`ORIGIN` container check for `FE-R31`, and ADR 0014's
`FE-R27` storage/cookie scan, which is what would catch a cookie that became readable or host-wide.
A failure in any of these is a regression of this decision rather than a new defect.

## Future: a patient surface is actually built — what changes

When D11's session→`patient_id` bind has merged and a patient app is in scope:

- A second compose service, its own `ORIGIN`, its own cookie name, its own CI job.
- `config/roles.yaml` gains a non-staff principal, and the `users` table has to represent a patient
  identity — schema plus a hand-synced migration (`CLAUDE.md` §7), at G4.
- Re-evaluate a CSP for both apps, which is cheap once the origins are already separate.
- Re-read ADR 0014 §5 and §6 against the new audience: no patient data in web storage and no
  client-persisted authorization value are audience-independent, but the *surfaces* their adversarial
  tests must drive double.
