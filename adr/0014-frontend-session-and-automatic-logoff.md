# ADR 0014 — Hold the gateway token server-side behind an httpOnly cookie, and log an idle operator off after 10 minutes

**Status:** Proposed
**Date:** 2026-07-31
**Author:** Riverbend engagement team
**Debt:** D10 (no session expiry) · D1/D3 (PHI at rest, for the storage half) · new scope for the
rebuilt portal (`docs/specs/frontend-rebuild.md` §8 #12, `FE-R27`–`FE-R29`)

## Context

The rebuilt portal (`portal/`, SvelteKit, ADR 0012) has to decide where the gateway session token
lives in the browser. ADR 0012 §3 deliberately did **not** decide this: it pinned the *transport*
("the same bearer-token transport as today") and left storage open, naming it as a decision someone
would otherwise make implicitly while writing the login page.

What today's portal does, verbatim from the code:

```ts
// frontend/app/lib/session.ts:9-10, 28-31
const TOKEN_KEY = "riverbend.token";
const USER_KEY = "riverbend.user";

export function setSession(token: string, user: PortalUser): void {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}
```

Its own comment states the posture: *"the only 'auth' the portal does is stash the token in
localStorage — there is no refresh, no expiry handling, and no real route-guard enforcement on the
backend"* (`session.ts:5-7`).

Three properties of this system make that a heavier exposure than it would be in an ordinary app,
and all three are documented landmines. `CLAUDE.md` §6, verbatim:

> ⚠️ **Auth / sessions** (`services/gateway/`, `security.py`, `auth.yaml`) — sessions never
> expire, single role, no MFA. **Never change auth behavior without explicit human approval.**

> ⚠️ **IDOR on chart reads** — `GET /patients/{id}/records` requires a session but never binds
> it to `{patient_id}`; IDs are sequential and walkable. Intentional gap, documented in code.

So the token is not PHI, but it is an unexpiring bearer credential that reads every chart in the
network, and the only thing that revokes it is an operator choosing to click Sign out —
`POST /logout` does destroy the Redis session (`services/gateway/app.py:196-199`, called from
`frontend/app/components/AppShell.tsx:102`), and nothing else does, because `create_session` sets no
TTL. Verified, not assumed: there is no idle timeout anywhere in the current portal, and
`docs/specs/frontend-rebuild.md` carried no session requirement before this ADR.

The deployment that matters is a shared front-desk workstation in a clinic waiting area. In that
setting `localStorage` writes the credential in plaintext into the browser profile on disk, where it
survives tab close, browser close and reboot, and is readable both by any XSS on the origin and by
anyone with filesystem access to the profile.

External convention, gathered 2026-07-31 rather than recalled:

- Automatic logoff is **45 CFR 164.312(a)(2)(iii)**, an *addressable* implementation specification —
  which means implement it if reasonable and appropriate, or adopt an equivalent and document the
  rationale. It does not mandate an interval; the practised range is 2–5 minutes on shared screens
  and 10–15 minutes in private offices, chosen by risk analysis.
- **Epic MyChart** logs a user out after 10–15 minutes idle, varying by health system.
- **OWASP**'s Authentication Cheat Sheet and JWT testing guidance both advise against holding
  session identifiers in `localStorage`; there is no `httpOnly` equivalent for web storage.
- **SMART on FHIR** guidance for browser-based apps is explicit: short-lived tokens, never browser
  local storage, use `httpOnly` cookies or server-side session storage.

Riverbend's compliance posture is self-asserted (ADR 0002), so "what an auditor anchors on" is the
relevant standard, and the current implementation is the pattern two of those sources name
specifically as the thing not to do.

One further force, and the reason this ADR exists rather than a one-line spec row: the option the
external guidance recommends had been **excluded** by `docs/specs/frontend-rebuild.md` §8 #12 and by
ADR 0012 §3, both of which read `httpOnly` cookies as an auth-behaviour change requiring §6 approval
and gate G4.

## Decision

### 1. The browser never holds the gateway token

The portal's own server layer holds the gateway token. The browser receives a session cookie set
`httpOnly`, `Secure`, `SameSite=Lax`, and no `Max-Age`/`Expires` — a session cookie, so it does not
persist to disk across a browser restart. Client-side JavaScript can neither read nor write it.

Every gateway call continues to originate from the portal's server and continues to carry
`Authorization: Bearer <token>`, exactly as `frontend/app/lib/gateway.ts` does today.

**Invariant:** the gateway contract is unchanged by this ADR. `require_session`
(`services/gateway/app.py:117`) is never asked to accept a cookie, and no gateway file is edited.
This is what keeps the decision outside `CLAUDE.md` §6's auth-approval boundary, and it is the whole
reason the option is available at P2 rather than at G4.

### 2. Why that is not the change ADR 0012 §3 excluded

ADR 0012 §3 ruled cookies out because "`require_session` accepting a cookie is a change to auth
behaviour." That reason is correct and applies to a hop this decision does not touch. There are two:

```
browser  ──httpOnly cookie──▶  portal (SvelteKit server)  ──Authorization: Bearer──▶  gateway
         ^^^^^^^^^^^^^^^^^^                                ^^^^^^^^^^^^^^^^^^^^^^^
         our own BFF                                       unchanged; require_session untouched
```

The exclusion generalised "cookies" from the gateway hop to both hops. ADR 0012 §3 is amended in
place with a pointer here (its invariant #3 survives — the *transport to the gateway* really is
unchanged), and spec §8 #12 records the withdrawal. What made this possible is a constraint ADR 0012
already pinned for other reasons: the browser never calls the gateway directly, so there is always a
server of ours in the path to hold a secret.

**CSRF.** Cookie-borne auth to our own server introduces CSRF, which bearer headers did not.
SvelteKit's `csrf.checkOrigin` is enabled by default and rejects cross-origin form POSTs.
**It must not be disabled**, and `SameSite=Lax` is the second layer; a future reader who turns
either off has reintroduced the vulnerability this section priced.

### 3. Where the token sits server-side

Inside the cookie value itself, encrypted with a key from the portal service's environment — not in
a server-side session store.

**Invariant:** no new infrastructure dependency for `portal/`. A store (Redis) is the stronger shape
and buys server-side revocation of the portal session, but Redis is `expose`-only in compose
(ADR 0011 round 1) and the frontend has never had a Redis dependency; adding one is a
`CLAUDE.md` §7 config/dependency change, and it is not needed to get the credential out of
JavaScript's reach. Recorded as deferred gap #2 rather than rejected.

### 4. Idle automatic logoff: 10 minutes

While a session is active, no operator interaction for **10 minutes** causes the portal to
`POST /logout` — the existing gateway endpoint, which destroys the Redis session — and return the
operator to the login surface. The cookie is cleared in the same response.

**The number's rationale, since 164.312(a)(2)(iii) requires one to be documented:** 10 minutes is
the floor of the MyChart range an auditor is most likely to compare against, and Riverbend's
workstations are shared but attended (a front-desk position, not an unattended kiosk), which is why
this is not the 2–5 minute shared-screen figure. Intake is a multi-minute form, so a shorter timer
costs re-login mid-registration. The interval is a **value**; the invariant is that the timeout is
enforced by invalidating the session **server-side**, not by clearing client state — a timer that
only forgets the token locally leaves a live credential in Redis forever and would satisfy the letter
of an idle-logoff control while providing none of it.

**What it looks like from outside:** the operator lands on the login surface with an explicit
"signed out after inactivity" message, distinguishable from a failed login. A request made with the
invalidated token receives the gateway's normal 401, which is what the `FE-R28` test asserts — the
proof is the rejection, not the redirect.

### 5. No patient data in web storage

`localStorage`, `sessionStorage` and IndexedDB hold no patient data — no search results, no chart
cache, no draft intake containing a name, DOB, SSN or note. This is a separate control from the token
decision and survives regardless of how §3 is later revised: PHI cached in a browser profile is PHI
at rest on a shared clinic workstation, outside every log-redaction control the repo has
(`docs/phi-logging-policy.md` governs log lines, not browser storage).

### 6. No authorization-relevant value is persisted client-side

Today `session.ts:30` caches `PortalUser`, role included, and `AppShell.tsx:188` renders the header
badge from it. The new portal persists none of it; role comes from `GET /me`
(`services/gateway/app.py:202-204`), which returns it from the Redis session hash.

This is load-bearing for spec §8.3 tier 2. Tier 2's legitimacy rests on provenance — "the role is
real server data, not a username→role map invented in the browser". A role read back out of
operator-editable web storage has browser provenance wearing server clothes, so navigation derived
from it would be the antipattern §8.3 forbids, arrived at by a different route.

## Alternatives considered

| Alternative | Why it lost |
|---|---|
| **`localStorage`** (true parity with today) | The only option with literally zero regression risk and zero new requirements, which is why it was the presumptive answer. It loses because the exposure it carries is the one this system is least able to absorb: an unexpiring credential to an IDOR-walkable record set, in plaintext on the disk of a shared workstation, surviving reboot. It is also the specific pattern OWASP and SMART on FHIR both name as the thing not to do, and Riverbend's posture is self-asserted, so "an auditor reads the guidance we ignored" is a real cost. |
| **`sessionStorage`** | Genuinely better than `localStorage` — nothing on disk after the tab closes — and it is the only option that permits two operators signed in simultaneously in two tabs, which sounded like a shared-workstation feature. Rejected on both halves: it is still fully JavaScript-readable, so it does not clear the guidance bar; and clinic workstation sharing is serial rather than parallel (the industry answer to it is fast user switching, not two live sessions), so the per-tab isolation is friction — two tabs means two logins — sold as a benefit. |
| **In-memory only** | Strongest on the storage axis: nothing readable from any storage at all. Rejected because it logs the operator out on every reload and every new tab, which is severe friction for a front-desk archetype (`docs/design/01-operators-and-tasks.md`), and because it buys less than it appears to — the Redis session survives, so the token is hidden from our own app rather than revoked. §4's server-side invalidation is what actually shortens credential life, and it composes with any storage choice. |
| **`httpOnly` cookie + server-side session store (Redis)** | The alternative actually preferred on merit, and the shape a mature deployment ends at: the cookie carries an opaque id, the token never leaves the server, and the portal session becomes independently revocable. Deferred, not rejected — it needs the frontend's first Redis dependency (compose wiring on an `expose`-only service, a new env var, a `CLAUDE.md` §7 flag) and delivers no additional protection against the threat §1 describes. Deferred gap #2 names what would pull it in. |
| **Cookie all the way to the gateway** (`require_session` accepts a cookie) | Correctly excluded, and still excluded. This is a change to auth behaviour: `CLAUDE.md` §6 explicit approval, gate G4, and a change to a load-bearing wall (`services/gateway/`). It also gains nothing over §1 for the browser-facing threat. This is the change ADR 0012 §3 meant to forbid, and it remains forbidden. |
| **Do nothing at P2; defer session handling to W9/G4** | Consistent with the "P2 is contract truth, not features" framing and it keeps the P2 diff smaller. Rejected because the login page has to store the token *somehow* to exist, so deferring is not neutral — it ships `localStorage` by default and then makes the fix a migration of a shipped auth surface rather than a greenfield choice. The decision is unavoidable at P2; only its quality is optional. |

## How this serves the client and domain

Riverbend gets the two controls an auditor asks about first — no credential reachable by page script,
and a documented, enforced automatic logoff with a written rationale for the interval — on the
addressable specification the current portal silently skips. Neither requires touching the auth
service, so neither carries the risk that made §6 gate auth changes in the first place.

For the front desk it means a station left unattended stops being an open chart after ten minutes
instead of indefinitely, and it costs one re-login after a coffee break. For the ROI clerk and
clinician the change is invisible, which is the intent.

## Accepted tradeoffs / deferred gaps

1. **D10 is not closed.** The Redis session still has no TTL. `FE-R28` bounds the credential's life
   only for an operator who goes idle *inside this app*; a token captured before the timer fires
   remains valid forever, and a session abandoned by closing the browser is never invalidated
   server-side at all (the cookie dies, the Redis key does not). Only a gateway-side TTL closes
   this — W9 / G4 work, `docs/debt-log.md` D10.
2. **No server-side portal session store, so the portal session cannot be revoked centrally.**
   Acceptable now because §3's threat is a browser-readable credential, which the cookie closes, and
   because `POST /logout` already revokes the thing that matters (the gateway session). Closed by
   adding Redis to `portal/` — pulled in by the first of: a second portal replica needing shared
   session state, a requirement to terminate another operator's session, or rotation of the cookie
   encryption key needing to invalidate outstanding cookies.
3. **`FE-R27` does not make XSS harmless.** Script on the origin cannot read the cookie but can still
   *use* it, issuing authenticated requests from the victim's browser. What the cookie removes is
   credential **exfiltration** — the attacker cannot take the token elsewhere or keep it after the
   tab closes. Closed only by the usual XSS controls (CSP, no `{@html}` on untrusted input), which
   are not in this ADR's scope.
4. **Cookie encryption key handling is minimal.** The key comes from the portal service's
   environment with no rotation mechanism; rotating it invalidates every outstanding session, which
   is an availability event, not a data-loss one. Acceptable because `.env` handling is already a
   documented landmine (`CLAUDE.md` §6, secrets in git history) and this ADR must not add a secret
   to a tracked file. **The key must not be committed**, and the fresh-deploy default must fail
   closed rather than seeding a shared literal — see Consequences.
5. **The 10-minute interval is a judgement, not a derivation.** It is defensible against the MyChart
   comparison and the addressable-specification requirement to document a rationale, but no
   Riverbend-specific risk analysis exists to pin it. Revisit if the client states a policy interval;
   the value is one constant, and the invariant in §4 is what a test holds.
6. **`FE-R29` is a prohibition, so it can only be tested adversarially.** A green suite proves the
   paths the test drives, not the absence of caching everywhere. Its test therefore drives the real
   search and chart surfaces and scans *every* storage key and value, per `CLAUDE.md` §5's
   negative-test rule; a future surface that caches patient data will not be caught by it unless the
   test is extended to drive that surface too. Named so the coverage claim stays honest.
7. **Patient-facing use is out of scope and blocked elsewhere.** Spec §8 #16 reopens the patient
   surface, and this ADR's controls survive it, but a patient login is gated on D11 session binding
   regardless. Nothing here should be read as making patient accounts safe.

## Consequences

**New in `portal/`:** one server-side session module owning cookie read/write, token forwarding and
the logoff timer's endpoint. Every gateway call routes through it; no component reads a token. The
module is the single seam where §3 can later become a Redis-backed store without touching callers.

**New config, and the default a fresh deploy actually seeds:** the portal needs a cookie encryption
key. It is generated into the gitignored env file by `make up` alongside `.env.ai-proxy` and
`.env.redis` (`CLAUDE.md` §3), and the service **fails to start** when it is absent — it does not
fall back to a built-in literal, because a shared default key across deploys is equivalent to no
encryption and would present as a working service. That failure must be visible on the service's
health surface rather than only in a stack trace (project memory
`fail-closed-guards-must-be-observable`).

**Harder now:** any client-side feature wanting the raw token, and any "keep me signed in" request —
both are now explicit decisions against this ADR rather than incidental. Debugging login involves the
server layer instead of devtools' storage tab.

**Easier now:** the store upgrade in gap #2 is one module. A patient surface (spec §8 #16) inherits a
credential the page cannot read, which is the property a two-audience origin needs most.

**Tests that hold the line** (all P2, ADR 0013's harness): `FE-R27`'s adversarial storage/cookie
scan, `FE-R28`'s timer unit test plus the 401-after-timeout assertion, `FE-R29`'s post-search and
post-chart storage scan. A failure in any of these is a regression of this decision, not a new bug.
`FE-R27` and `FE-R29` are prohibitions, so each needs the mutation check `docs/specs/_template.md`
and project memory `thresholds-must-be-reachable` require: break the control deliberately and confirm
the test fails, or the test is decoration.

## Future: a gateway-side session TTL (W9 / G4) — what changes

When the gateway gains real session expiry and per-action authorization:

- `FE-R28`'s client timer becomes a second layer rather than the only bound; keep it, but the
  authoritative lifetime moves server-side and the two intervals must be stated in terms of each
  other (project memory `thresholds-must-be-reachable` — pin them, and name the test).
- Gap #1 closes, and D10's entry in `docs/debt-log.md` can move.
- Re-evaluate §3: with a real session lifetime, a server-side store's revocation story is worth more
  than it is today.
- Re-evaluate the cookie-to-gateway alternative on its merits, since the §6 approval it needs will be
  on the table anyway for the authorization work.
