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

> **Amended 2026-07-31 — two corrections to this paragraph; see §Audit-round corrections.**
>
> **`Secure` is derived, not stated flatly.** It is derived from the deployment's `ORIGIN` scheme
> (`adapter-node`'s env var — see ADR 0015), which is `true` everywhere except a local `http://localhost`
> dev/demo origin, where browsers treat localhost as a secure context anyway. Hardcoding `secure: true`
> is harmless on localhost and silently fatal on any **non-localhost HTTP** origin: the browser accepts
> the login response, discards the cookie, and every subsequent request is unauthenticated with no error
> to read. **Verified on `http://localhost` only.** Production is HTTPS on a hostname
> (`docs/handover/portal.har:11` — `https://portal.riverbend.example.com`), terminated by
> infrastructure that does not exist in this repository; that is ADR 0015's subject, not this one's.
>
> **The disk-persistence claim is weaker than written.** Chrome's session-restore ("Continue where you
> left off") restores session cookies across a restart, so "does not persist to disk across a browser
> restart" is a workstation setting, not a property of the cookie. The claim is **not load-bearing** —
> §4's `last_seen` clock bounds an abandoned session regardless of whether the cookie survives — and it
> should not be cited as a control. Unverified on the real workstation image; recorded as gap #8.

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

**What that check needs to work, named 2026-07-31 because this ADR leaned on it without it.**
`checkOrigin` compares a request's `Origin` header against the app's own origin, and under
`adapter-node` behind a reverse proxy the server only knows its public origin if it is told: the
`ORIGIN` environment variable, or `PROTOCOL_HEADER`/`HOST_HEADER` when terminating TLS upstream. Left
unset behind a proxy, the comparison is made against the wrong value and the protection is either
absent or rejects legitimate POSTs. `ORIGIN` is therefore **runtime config per deployment, never a
build constant** — the same rule and the same scar as ADR 0012 §4's `GATEWAY_URL`. Values and the
origin topology belong to ADR 0015.

### 3. Where the token sits server-side

Inside the cookie value itself, encrypted with a key from the portal service's environment — not in
a server-side session store.

**Invariant:** no new infrastructure dependency for `portal/`. A store (Redis) is the stronger shape
and buys server-side revocation of the portal session, but Redis is `expose`-only in compose
(ADR 0011 round 1) and the frontend has never had a Redis dependency; adding one is a
`CLAUDE.md` §7 config/dependency change, and it is not needed to get the credential out of
JavaScript's reach. Recorded as deferred gap #2 rather than rejected.

**The cookie's contents and its encryption, specified 2026-07-31 — this section previously said only
"encrypted with a key from the portal service's environment", which is a property and not a
mechanism (see §Audit-round corrections finding 7).**

The cookie value is a **JWE compact token, `A256GCM` content encryption with a `dir` key**, produced
by a named, audited library — `jose` — rather than hand-assembled from primitives. Three invariants,
each with the failure it prevents:

- **Authenticated encryption only.** An unauthenticated mode (e.g. AES-CBC with no MAC) leaves the
  cookie malleable, and a malleable session cookie is a forgery surface, not merely a privacy one.
  `A256GCM` is the value; *AEAD* is the invariant.
- **The key is 32 bytes of CSPRNG output**, base64url-encoded in the environment, and it is **never a
  literal in a tracked file** (see Consequences and gap #4).
- **The token carries a key id (`kid`)**, so rotation can accept the previous key for one deploy
  instead of logging every operator out. Without it, gap #4's "rotation is an availability event" is
  the only option available; with it, that becomes a choice.

**Claims inside the cookie**, and nothing more — every additional field is a byte cost and a PHI
question:

| Claim | Why |
|---|---|
| `token` | the gateway bearer token; the whole point of §1 |
| `username` | so the shell can render who is signed in without a `GET /me` on every navigation |
| `iat` | issued-at, for the absolute bound |
| `last_seen` | last observed operator interaction — **the clock §4's enforcement depends on** |

**No `role`, and no patient data** — §6 forbids the former, `FE-R29` the latter. **Invariant: the
cookie is bounded well under the 4096-byte per-cookie limit**, which the four claims above are, and
which is why the claim list is closed rather than open. A future claim gets added only with the size
re-measured.

`username` is in the list and `role` is not, which is a distinction worth stating because it looks
inconsistent: §6's objection is to an **authorization-relevant** value with browser provenance, and a
sealed cookie the operator cannot edit does not have browser provenance in the first place. `username`
is identity for a header label, it grants nothing, and the gateway re-derives both username and role
from its own Redis session on every call. `role` stays out anyway — the §8.3 tier-2 navigation
decision should read it from `GET /me` so there is exactly one source for it, not two that can
disagree.

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

> **Amended 2026-07-31 — as originally written, this section's invariant could not be met by §3's
> design; see §Audit-round corrections finding 1.** The paragraph above correctly insists the timeout
> be enforced by invalidating the session server-side, and correctly calls a purely local timer a
> control that "would satisfy the letter of an idle-logoff control while providing none of it". But
> with the token inside the cookie and **no server-side store**, nothing except page script knew when
> the operator last interacted — so the *trigger* was client-only however server-side the *effect*
> was, and `FE-R28`'s "confirmed by a subsequent request being rejected" had no server-held clock to
> hang on. A slept laptop, a discarded tab or disabled script defeated it silently.
>
> **The timeout is enforced in two layers, with distinct jobs.** Neither may be cited as doing the
> other's work:
>
> 1. **Client timer — proactive, and the good path.** Ten minutes without operator interaction and the
>    page POSTs to the portal's logoff endpoint, which calls the gateway's `POST /logout` and clears
>    the cookie. This is what makes the Redis session die *promptly*.
> 2. **`last_seen` in the cookie — the enforcement that survives a dead timer.** Every response
>    re-issues the cookie with `last_seen` refreshed (a sliding window). On each request the portal's
>    server compares `now - last_seen` against the interval **before** doing anything else; past it,
>    the request is refused, `POST /logout` is called, and the cookie is cleared. The operator cannot
>    influence this: the cookie is AEAD-sealed, so a forged or rolled-back `last_seen` fails to
>    decrypt.
>
> **Invariant: the idle decision is made by the portal's server from a value the browser cannot
> forge — never by page script alone.** The interval remains a single value shared by both layers.
>
> **The residual exposure, stated because it is smaller than "closed" and larger than nothing.** Layer
> 2 only fires when a request arrives. A browser closed at minute three leaves the Redis session alive
> until something makes a request with that cookie — possibly never. So the credential's life is
> bounded for an operator who *returns*, and unbounded for one who walks away without signing out.
> That is strictly better than the original design (where it was unbounded in both cases) and still not
> D10: only a gateway-side TTL closes it. See gap #1.

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

   **Restated 2026-07-31 after §4's two-layer amendment.** What changed: the bound is now enforced
   from a value the browser cannot forge, rather than from page script that a slept laptop defeats.
   What did **not** change: layer 2 fires only when a request arrives, and both layers are
   portal-side, so the portal cannot expire a session it is never asked about. Read this gap as
   **bounded for a returning operator, unbounded for an abandoning one** — still D10, still the
   gateway's to close.
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
   is an availability event, not a data-loss one. **Softened 2026-07-31:** §3 now specifies a `kid`
   in the token, so a rotation *can* accept the previous key for one deploy instead of signing
   everyone out. No rotation procedure is written, so the availability event remains the default;
   what changed is that it is now a choice rather than the only option. Acceptable because `.env` handling is already a
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
   regardless. Nothing here should be read as making patient accounts safe. **Extended
   2026-07-31:** the origin question that surface raises — one origin for both audiences, or two — is
   decided in `adr/0015-portal-origin-and-audience-separation.md`, which also fixes the two settings
   this ADR depends on and does not own (`ORIGIN`, and the absence of a cookie `Domain`).
8. **The session-cookie disk-persistence claim is unverified, and deliberately not load-bearing
   [added 2026-07-31].** §1 originally asserted the cookie "does not persist to disk across a browser
   restart"; Chrome's session-restore setting can restore session cookies, so that is a property of
   the workstation, not of the cookie. Not measured on the real workstation image — it cannot be
   measured from this repository, and it blocks nothing, because §4's `last_seen` clock bounds an
   abandoned session whether or not the cookie survives a restart. **What closes it:** one manual
   check on the deployed workstation image (log in, quit the browser, reopen, observe whether the
   cookie is still sent). **Do not** cite cookie non-persistence as a control in the meantime.

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

**The health surface that sentence assumed, specified 2026-07-31 — it did not exist (finding 8).**
Verified: the existing `frontend` compose service has **no** healthcheck (`docker-compose.yml:219-227`)
while ten other services do, `docs/runbook.md`'s health-check loop covers only 8070–8076, and nothing
in ADR 0012 or 0013 specifies one for `portal/`. So as written, the fail-closed guard would have
presented exactly as the PR #14 pattern the memory page names: a dead service under a green
dashboard. Three additions, all in `portal/`'s own PR:

- **`GET /healthz` on the portal**, returning non-200 when the cookie key is absent or unusable. It
  reports *that* the key is missing — never the key, never a partial value, never a stack trace.
- **A compose `healthcheck`** on the `portal` service hitting it, matching the shape the other ten
  services already use, so `make ps` shows the service unhealthy rather than up.
- **A line in `docs/runbook.md`'s health-check block** covering the portal, since that loop is what an
  operator actually runs.

**Invariant: a fail-closed guard added here is reachable from the health surface.** A future guard in
this module that raises without a health signal is a regression of this decision.

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

## Audit-round corrections (2026-07-31)

Pre-P2 adversarial audit, run the day after this ADR was written and before any code exists. Not an
automated review round, so `docs/review-loop-metrics.md` §4 gains no entry; all findings are **A-class**
in that file's vocabulary. Append-only per `adr/_template.md`, with in-place amendment blocks where the
original sentence would otherwise be read as current.

**Finding 1 — §3's design made §4's invariant unreachable.** With the token in the cookie and no
server-side store, nothing but page script knew the time of last interaction, so the idle *trigger* was
client-only however server-side the effect was — the very thing §4 calls out as satisfying the letter of
the control and none of it. Fixed by adding a `last_seen` claim to the cookie (§3) and restating §4 as
two layers: a proactive client timer, and a sliding, AEAD-sealed `last_seen` the server checks on every
request. **Redis was reconsidered and still deferred** — §3's reasons (no new infra dependency,
`expose`-only Redis, a `CLAUDE.md` §7 change) are untouched by this finding, and a forgery-proof clock in
the cookie is what the invariant actually needed. Gap #1 restated with the residual exposure.

**Finding 7 — §3 named a property, not a mechanism.** "Encrypted with a key from the portal service's
environment" permitted an unauthenticated mode and an unbounded cookie. §3 now specifies JWE `A256GCM`
via `jose`, a 32-byte CSPRNG key, a `kid` for rotation, and a closed four-claim payload bounded well
under 4096 bytes. Gap #4 softened accordingly.

**Finding 8 — the fail-closed guard had no health surface to fail on.** Consequences required the
missing-key failure be visible on the health surface; measurement showed no healthcheck exists for a
frontend service and none was specified for `portal/`. Now specified: `GET /healthz`, a compose
healthcheck, and a runbook line.

**Finding 4-adjacent — §1's `Secure` flag and §2's `csrf.checkOrigin` both depended on an origin
nobody had written down.** §1 now derives `Secure` from `ORIGIN` and records that the flag is verified
on `http://localhost` only; §2 names `ORIGIN` as what `checkOrigin` needs behind a proxy. The topology
itself is `adr/0015-portal-origin-and-audience-separation.md`.

**Finding 11 — §1 overstated cookie non-persistence.** Amended in place and demoted to gap #8: not
load-bearing, not measurable from this repository, and not to be cited as a control.

**Unchanged by the audit, checked:** §1's core invariant (the browser never holds the token), §2's
two-hop reasoning, §5 (no patient data in web storage), §6 (no client-persisted role), the 10-minute
interval and its rationale, and the Alternatives table.
