# ADR 0012 — Rebuild the staff portal on SvelteKit, behind an unchanged gateway contract

**Status:** Superseded 2026-08-05 — the frontend rebuild is descoped and this decision is not being
executed. The engagement returned to the curriculum weeks (W1–W4), and the inherited Next.js portal
is the only frontend. **The scaffold, the spec, the design set and this ADR's unchanged text are on
branch `alt/sveltekit-portal`.** What still stands independently of the framework choice: §3's
finding that the gateway contract needs no change either way, and the operator-shift evidence in
the design set that motivated a rebuild at all. Nothing below has been edited to reflect the
descope — read it as the decision as taken, not as current plan.
**Date:** 2026-07-30
**Author:** Riverbend engagement team
**Debt:** none directly — new scope (`docs/specs/frontend-rebuild.md`). Adjacent to D4, D6, D8 and
D11 through the requirements this decision makes satisfiable; it closes none of them by itself.

## Context

The P0 design phase walked the running portal against each seeded operator's actual shift and graded
what the system can serve. `docs/design/01-operators-and-tasks.md` §3 records the result, and it is
not a styling problem:

- Front desk: "Register a new patient — **Broken** — every submission 422s and the UI reports success
  **[E]**". "Confirm coverage is active — **Partly** — result is already in the intake response and
  the UI discards it **[E]**". "Find an existing patient — **Yes** — `GET /patients?q=` exists;
  **no UI uses it** **[E]**".
- Clinician: "Confirm the chart is the right patient — **No** — the chart displays none of these;
  1042 and 1043 look alike **[E]**". "Read the visit history in date order — **No** — encounters
  render as 'Dr. Patel · 1 record', no dates **[E]**".
- ROI clerk: "Confirm the right patient before disclosing — **No** — form takes a bare numeric ID,
  shows no name **[E]**".

The surface being replaced, measured rather than estimated: **2,523 lines** of TypeScript/TSX under
`frontend/app`, Next.js 15.1.3 with React 19, one runtime dependency beyond the framework
(`react-day-picker ^9.14.0`), **14 BFF route handlers** under `frontend/app/api`, and — on the work
the operators actually do — five forms and three tables. `frontend/app/intake/page.tsx` is 555 lines,
predominantly `useState` spread-updates over one wizard.

Three constraints bound any choice here:

- **The portal → gateway invariant.** CLAUDE.md §1: "The portal **never** calls a domain service
  directly — everything goes through the gateway, which owns login + session validation and fans
  requests out." Verified for the transport as well: there is **no CORS middleware anywhere in
  `services/gateway/`**, so today the browser only ever speaks to same-origin `/api/*` handlers,
  which proxy server-side (`frontend/app/lib/gateway.ts`).
- **Auth is a landmine.** CLAUDE.md §6: "⚠️ **Auth / sessions** … sessions never expire, single role,
  no MFA. **Never change auth behavior without explicit human approval.**" And §10.3: the gateway is
  "imported by many modules or frequent in `git log` (`services/gateway/app.py` is the standing
  example)" — a load-bearing wall, not a seam.
- **ADR 0001 chose this stack**, and Riverbend inherited it from Helix Digital Partners. Replacing it
  spends continuity that the client, not the engagement, owns.

One process constraint shaped the *timing* rather than the outcome. The user's rule of 2026-07-28:
write P0's requirements before scoring candidates, or the criteria are post-hoc. That precondition is
now discharged — `FE-R1`–`FE-R26` are written and gated, and `docs/design/01`–`05` all exist.

## Decision

Rebuild the staff portal on **SvelteKit with TypeScript**, as a **second compose service**, behind a
gateway contract that does not change.

### 1. Scope and coexistence

The new app is a new service in `docker-compose.yml`, on port **3071**, built from its own directory.
The existing Next.js portal stays on 3070 and stays runnable until `FE-R1`–`FE-R3` pass on the new
frontend, as `FE-R15` requires. This **resolves open decision #4 by implication**: a "route group
behind a flag" inside the existing Next.js app cannot host a SvelteKit application, so the
second-service option is the only one left. Decision #4 is closed by this ADR, not still open.

### 2. Invariant — the browser never calls the gateway directly

Every gateway call is made from the SvelteKit **server** side: a `+server.ts` endpoint, a `load`
function, or a form action. The 14 existing route handlers port one-for-one.

This is stated as an invariant rather than as a technique because of what the alternative costs:
a browser-direct call requires CORS middleware in the gateway, which means editing an auth-owning
load-bearing wall to enable a frontend convenience. **The gateway must never need a CORS
configuration as a result of this rebuild.** If a future change appears to need one, the change is
wrong, not the invariant.

### 3. Invariant — auth transport is unchanged by this ADR

The new frontend uses the **same bearer-token transport as today**: the token is held client-side and
forwarded as an `Authorization` header to the app's own server endpoints, which pass it straight
through to the gateway, exactly as `frontend/app/lib/gateway.ts` does now.

SvelteKit's form actions make `httpOnly` cookies the idiomatic path, and cookie-based sessions would
genuinely be an improvement — a token in `localStorage` is XSS-readable, on top of sessions that
never expire (D10). It is nonetheless **out of scope here**, because `require_session` accepting a
cookie is a change to auth behaviour: CLAUDE.md §6 approval, and gate **G4** per `FE-R14`. Named
explicitly so it is not smuggled in later as "how SvelteKit does auth."

> **Amended 2026-07-31 — see `adr/0014-frontend-session-and-automatic-logoff.md`.** The invariant
> above stands: the transport *to the gateway* is unchanged, and `require_session` is never asked to
> accept a cookie. But the paragraph over-generalised from that hop to both hops, and was read
> (including by this ADR's own author, and by `docs/specs/frontend-rebuild.md` §8 #12) as excluding
> `httpOnly` cookies altogether. It does not: a cookie between the **browser and our own BFF**,
> where the portal's server holds the token and still sends `Authorization: Bearer` onward, touches
> no auth boundary. ADR 0014 takes that option, and the sentence "the token is held client-side"
> above is superseded — under ADR 0014 the token is held **server-side**, which the portal→gateway
> invariant in §2 is precisely what makes possible. Cookie-to-gateway remains excluded on the reason
> stated above.

### 4. Configuration

`GATEWAY_URL` is read **at request time, never as a module-level constant.** This is not a
preference: the existing code carries the scar — "Read at REQUEST time (not as a module-level const)
so the container's `GATEWAY_URL` env is honored at runtime and never constant-folded into the
standalone build (which baked localhost)." The same failure is available in any bundler, so the rule
carries over verbatim.

**The SvelteKit-specific mechanism, named because the rule without it is unenforceable
(2026-07-31 audit, finding 9).** `$env/static/private` is inlined at build time and reproduces the
scar exactly — same failure, new bundler. Only `$env/dynamic/private`, or `process.env` under
`adapter-node`, honours the container's environment at request time. The invariant is request-time
resolution; `$env/dynamic/private` is the value.

Fresh-deploy default: the compose service sets `GATEWAY_URL: http://gateway:8070`, mirroring the
existing `frontend` service. There is no localhost fallback in the container path.

### 5. The accessibility gate is the build, not a lint suggestion

`FE-R17` — "The build shall fail when an interactive element lacks an accessible name" — is satisfied
by Svelte's compiler-level a11y diagnostics, escalated so that **warnings are errors in CI**. The
invariant is *the build fails*; the mechanism (`svelte-check --fail-on-warnings`, or an `onwarn`
handler that throws) is a value that may change.

Stated precisely, because this is the criterion the decision leans on hardest: Svelte's checks live
in the compiler and apply to every component by default. React's equivalent
(`eslint-plugin-jsx-a11y`) can also fail CI, but it is opt-in per rule.

> **Amended 2026-07-31 — measured, see §Audit-round corrections finding 3.** The paragraph above
> originally continued: React's plugin "analyses JSX syntactically, so it does not see attributes
> assembled dynamically. The advantage is real and it is narrower than 'one has a gate and the other
> does not.'" **That sentence is withdrawn as a discriminator**: `svelte-check` is defeated by
> `<button {...rest}>` in exactly the same way, so the dynamic-attribute blind spot is shared, not a
> Svelte advantage. What survives measurement is narrower and still real — Svelte's rules are on by
> default and apply to every component, where `eslint-plugin-jsx-a11y`'s equivalent
> (`control-has-associated-label`) is opt-in.
>
> **The gate's measured scope, which is narrower than `FE-R17`'s wording.** With `svelte@5.56.8` +
> `svelte-check@4.7.4`, `--fail-on-warnings` exits 1 (and exits 0 without the flag, so the flag is
> load-bearing). It **catches** an icon-only `<button>` or `<a>` with no accessible name
> (`a11y_consider_explicit_label`), a `<label>` not associated with a control, a missing `alt`, and
> click handlers on static elements. It is **silent** on: `<input>`, `<textarea>` and `<select>` with
> no accessible name; `<button {...rest}>`; `aria-label={maybeUndefined}` (attribute presence
> satisfies it, the value is never evaluated); and `<div role="button">` with no name. So the gate
> covers **buttons and links**, not "interactive elements" — see gap #5, `FE-R17`'s reworded scope in
> `docs/specs/frontend-rebuild.md` §5, and ADR 0013's re-opened axe question.
>
> **Narrowed again 2026-07-31 by a second measurement — see §Implementation-round corrections.** "It
> catches an icon-only `<button>` or `<a>`" is true of every icon shape *except* the commonest one: a
> `<button>` or `<a>` whose only child is `<img alt="">` is **silent**. Read the sentence above as
> catching *empty* buttons and links, plus ones whose only child is a `<span>` or `<svg>`.

### 6. What is dropped

`react-day-picker` goes, necessarily. **ADR 0008 is superseded in part** by this ADR: its dependency
choice is void, while its underlying finding — that month-by-month traversal to 1974 is unusable for
a DOB field — stands and is still owed by `FE-R7`, now re-implemented natively.

### 7. What is explicitly not decided here

The test harness. `docs/specs/frontend-rebuild.md` §4 deliverable 3 requires its own ADR written
**after** this one; Vitest is the presumptive shape and is not chosen by this file. Data-loading
strategy per surface (server `load` vs client fetch) belongs to P3/P4. The component-gallery question
(open decision #5) stays deferred until real primitives exist.

## Alternatives considered

Most of `FE-R1`–`FE-R26` are framework-neutral: an identity banner, third-person copy, a timezone
formatter and a not-answered-vs-declined chip are all equally buildable in either stack. Scoring
every requirement would pad the table toward whichever candidate has more rows. So the table below is
restricted to the requirements where the stacks measurably differ, plus the operator-task load from
`FE-R18`'s output.

| Criterion (source) | SvelteKit | Next.js 15 (incumbent) |
|---|---|---|
| `FE-R17` accessible-name gate — **row corrected 2026-07-31, see §5's amendment** | compiler-level, on by default for every component, fails the build — but **buttons and links only**; silent on form-control names and on spread attributes | `eslint-plugin-jsx-a11y`, opt-in rules; `control-has-associated-label` exists but is off by default; equally blind to spread |
| Form ergonomics — 5 forms, the largest 555 lines of `useState` spread-updates (`FE-R1`, `FE-R21`) | two-way binding removes the update boilerplate outright | the boilerplate is the framework's model; a form library is a further dependency |
| Token set delivery (`docs/design/05-design-tokens.md`) | scoped CSS is native; tokens land as plain CSS custom properties | needs a CSS strategy decision or a CSS-in-JS dependency |
| `FE-R2` error-surface discipline | server endpoints, plain returns, no RSC/route-handler split to reason about | route handlers already work; the RSC boundary is extra ceremony without extra safety here |
| `FE-R3` shared fixture, JS-side assertion | Vitest, standard | Vitest/Jest, standard — **neutral** |
| `FE-R15` both portals runnable | forces the clean answer: a separate service | permits an in-app route group, which blurs which app is under test |
| Continuity of the client's inherited stack (ADR 0001) | **loses** — a framework Riverbend never chose | **wins** — the only criterion it wins, and the one the client would raise |
| Handoff / staffing | Svelte experience at Riverbend or Helix is unknown **[?]** | React is the safer hiring assumption |

**Next.js 15, staying put — genuinely considered, and it loses on the criteria above.** It is not a
strawman: it is the incumbent, it works, the 14 route handlers already do the right thing, and the
continuity argument is the strongest single argument in this ADR. It loses because the criteria that
discriminate — a real a11y gate, and form ergonomics across five forms — are exactly where the P0
findings concentrated, and because continuity is one criterion against four.

Two arguments were available for SvelteKit and are **rejected as unsound**, recorded so they are not
revived in review:

- **Bundle size / performance.** 2,523 lines total. The latency an operator actually feels is the D4
  eligibility hop on the intake save, which is backend and bounded by ADR 0010. Irrelevant either
  way.
- **"React caused these defects."** Nothing in `docs/design/01` §3 is React's fault — a chart with no
  patient name, a discarded eligibility result and a 422 reported as success are all application
  logic. SvelteKit is justified as a better substrate, never as a fix.

**SvelteKit as a static/SPA build, browser calling the gateway directly — rejected.** It requires
adding CORS to `services/gateway`, i.e. an auth-adjacent edit to the standing example of a
load-bearing wall (CLAUDE.md §10.3), in order to delete a server hop that already exists and works.
It also loses the server-side seam where `FE-R16` (no PHI in operator-facing errors) is enforceable.

**A route group behind a flag in the existing Next.js app — not available.** It cannot host Svelte.
Retained here only to record that decision #4's two options were not equally live once #2 resolved.

**Remix / TanStack Start / plain Vite SPA — not scored.** Each would need its own criteria pass, and
neither the requirements nor the client's constraints point at them; adding them to the table would
be decoration.

## How this serves the client and domain

Riverbend gets the accessible-name gate enforced by CI rather than asserted in a policy document,
which is a defensible answer to an auditor asking how the portal's accessibility is maintained. Front
desk and ROI staff get the five forms and three queues rebuilt on a substrate where the identity
confirmation and error-state work the P0 flows specify is cheap rather than a 555-line wizard patch.
The cost is borne in handoff, not in operation: the running system keeps the same gateway, the same
ports, the same auth and the same deployment shape.

## Accepted tradeoffs / deferred gaps

1. **Riverbend runs two frontend frameworks for the duration of the rebuild.** Acceptable because
   `FE-R15` requires the old portal to stay runnable anyway, so the overlap is the requirement, not a
   side effect. Closed when `FE-R1`–`FE-R3` pass on the new frontend and the Next.js portal is
   removed.
2. **Svelte experience at Riverbend and Helix is unknown [?].** Recorded at authoring time as the
   real residual risk, unbounded by anything in this ADR. What reduces it: an in-repo component
   gallery (open decision #5, deferred to P3) and the harness ADR, both of which make the codebase
   legible to someone who has not used Svelte. What would close it: confirmation from the client that
   the stack is acceptable to whoever maintains this after handoff.

   **Answered 2026-07-30 — approved.** Put to the engagement's trainer acting in the client role, and
   approved. Recorded with that provenance rather than as "the client approved", because a
   trainer-in-role is the decision-maker available to this engagement and not a Riverbend stakeholder;
   an auditor reading this register should be able to tell the difference. The gap is closed on the
   term it named — stack acceptability — and the two mitigations above still apply, since approval of
   a choice is not the same as a maintainer being able to read the code.
3. **`FE-R7` is re-opened, not inherited.** Dropping `react-day-picker` means the DOB entry problem
   ADR 0008 solved must be solved again from scratch, and the native-`<input type="date">` option
   ADR 0008 rejected comes back into scope on its own merits.
4. **Auth posture is unchanged, not improved.** The token stays XSS-readable in client storage and
   sessions still never expire (D10). This ADR deliberately neither worsens nor fixes it. Closed by
   G4 / W9, with explicit human approval.
5. **The a11y gate covers accessible names only — and, measured 2026-07-31, only on buttons and
   links.** It does not check contrast, focus order or reading order. Contrast is covered by
   measurement in `docs/design/05-design-tokens.md` §1/§6, not by CI; focus order is unverified. A
   gate that covers one WCAG failure mode must not be cited as covering accessibility.

   **Extended by the audit (finding 3/4):** the gate is also silent on `<input>`, `<select>` and
   `<textarea>` accessible names — i.e. on the five-form surface this decision was partly justified
   by — and on any interactive element whose attributes arrive by spread. `eslint-plugin-svelte@3.22.0`
   does **not** close this: it ships 85 rules and **zero** a11y rules (its `valid-compile` rule only
   re-surfaces the same compiler warnings), so spec decision #15's stated justification for adding
   eslint does not hold. What closes it: `axe-core` in ADR 0013's `client` project, or a custom rule.
   ADR 0013 §8 declined axe **before this measurement existed**, so that decision is re-opened on
   evidence rather than on preference (ADR 0013 gap #9).
6. **Small-viewport behaviour remains unverified** (`04-wireframes.md` §5) — Chrome would not resize
   below ~1500px during the walkthrough. The framework choice neither helps nor hurts this.

## Consequences

**New and changed, outside `frontend/`:**

- `docker-compose.yml` — a second frontend service on 3071 with `GATEWAY_URL: http://gateway:8070`.
- `.github/workflows/ci.yml` — the `frontend` job hardcodes `working-directory: frontend` plus
  `npm install` / `npm run build`. It needs a second job or a matrix, and the `FE-R17` a11y gate
  lands here as a failing build.
- `Makefile` — `frontend-dev` currently reads "run the Next.js dev server"; a second target is
  needed while both apps exist.
- `tests/test_compose_topology.py` — asserts compose structure and iterates services when checking
  that the AI-proxy secret reaches only the gateway and ai-assistant. A new frontend service is swept
  into that loop and should pass on the "does not hold the secret" branch. **To be run, not
  assumed.**

**No change to any service in `services/`.** The gateway contract is HTTP + JSON + a bearer token;
the only Next.js references in the backend are a docstring (`services/gateway/app.py:4`) and a
Makefile comment, both cosmetic. This is worth stating because "we would have to change the backend"
is the objection this decision will otherwise attract without evidence.

**Register effects:** ADR 0001 is **partially superseded** (stack choice for the frontend only; the
service layout and Python conventions stand). ADR 0008 is **superseded in part** — dependency void,
finding intact.

**Now easier:** the five forms, the token set, the a11y gate, and per-surface server-side data
loading. **Now harder:** onboarding anyone who knows React and not Svelte; keeping two apps green in
CI until the old one is deleted.

**Tests that hold the line once implementation starts:** the shared intake fixture asserted from both
sides (`FE-R3`) is what makes the contract break unrepeatable; `tests/test_compose_topology.py` holds
the service topology; the CI a11y job holds `FE-R17`. Failures in those three are regressions of this
decision rather than new defects.

## Future: the Next.js portal is retired — what changes

When `FE-R1`–`FE-R3` pass on the new frontend and the old portal is deleted: the compose service on
3070 and its Dockerfile go; the CI matrix drops back to one frontend job; `Makefile`'s
`frontend-dev` loses its Next.js wording; `react-day-picker` leaves the lockfile; and ADR 0008 moves
from "superseded in part" to fully superseded, since nothing will consume its dependency choice.
`FE-R15` is the gate on all of it, and none of it happens before G2.

## Audit-round corrections (2026-07-31)

A pre-P2 adversarial audit of ADRs 0012–0014 and the spec, run before any frontend code exists.
Not an automated review round, so `docs/review-loop-metrics.md` §4 gains no entry; in that file's
vocabulary every finding here is **A-class** — a defect in the document as originally written.
Recorded append-only per `adr/_template.md`, with in-place amendment blocks where leaving the
original sentence unmarked would let the stale copy win (project memory
`duplicated-instructions-let-the-stale-one-win`).

**Finding 3 — §5's discriminating claim against React was false, and `FE-R17`'s scope exceeds its
mechanism.** Measured with a 13-case probe on `svelte@5.56.8` + `svelte-check@4.7.4`. `svelte-check`
does catch icon-only buttons and links — better than the audit predicted — but is silent on
form-control accessible names, on spread attributes, on dynamic `aria-label` values and on
`role="button"` elements. §5 carries the amendment, the Alternatives table row is corrected, and
gap #5 is extended. The decision itself stands: Svelte's rules are on by default for every
component, which is still an advantage over an opt-in rule, and `FE-R17` was never the only
criterion. What changed is that the criterion is smaller than written, so `FE-R17`'s wording in
`docs/specs/frontend-rebuild.md` §5 is narrowed to match the mechanism rather than left as an
aspiration the gate does not enforce.

**Finding 4 — spec decision #15's premise does not hold.** `eslint-plugin-svelte` has no a11y rules,
so eslint cannot be what makes `FE-R17` "a gate rather than a subset of it". eslint stays for what it
genuinely covers (unused bindings, import hygiene); the a11y gap goes to ADR 0013's re-opened axe
question. Recorded in gap #5 and in spec §8 #15.

**Finding 9 — §4 stated the request-time `GATEWAY_URL` rule without its SvelteKit mechanism.**
`$env/static/private` would have reproduced the scar §4 quotes. §4 now names
`$env/dynamic/private`.

**Not a correction, recorded for navigation:** the origin and audience-separation question that §2's
portal→gateway invariant makes possible — one origin for staff and patients, or two — is decided in
`adr/0015-portal-origin-and-audience-separation.md`. That ADR depends on §2 and changes nothing in
this one.

## Implementation-round corrections (2026-07-31)

Measured while building the scaffold (P2 PR 1), on the versions the repository now pins
(`svelte@5.56.8`, `svelte-check@4.7.4`, `--fail-on-warnings`). Append-only per `adr/_template.md`;
§5 carries a marker so the earlier sentence cannot be read alone.

**Finding 1 — the `FE-R17` gate is silent on the commonest icon-button shape.** A 9-case probe:

| Markup | `a11y_consider_explicit_label` |
|---|---|
| `<button></button>` · `<a href></a>` | fires |
| `<button><span></span></button>` | fires |
| `<button><svg/></button>` · `<a href><svg/></a>` | fires |
| **`<button><img alt=""/></button>`** | **silent** |
| **`<a href><img alt=""/></a>`** | **silent** |
| `<button>{''}</button>` | silent (an expression child reads as text — expected) |

An `<img>` child satisfies the rule on the assumption that it carries an accessible name, and an
explicitly decorative `alt=""` is not re-checked. So the gate catches the *empty* control and the
`<svg>`/`<span>` icon, and misses the `<img>` icon — which is what a designer hands over. The
§5 amendment's sentence is narrowed in place rather than deleted, because a reader arriving at §5
would otherwise take a stale claim as measurement.

This does **not** change the decision. Svelte's rules are still on by default for every component,
which is the surviving discriminator, and `FE-R17` was never the only criterion. It changes the
gate's size, which gap #5 already understates: the uncovered surface is now form controls, spread
attributes, `role="button"` elements **and** `<img>`-icon buttons and links. `axe-core` in ADR 0013's
`client` project (that ADR's gap #9, decided at P3 against real primitives) is still what closes it;
until then, an `<img>`-only control needs an explicit `aria-label` written by hand and caught at
review, and `FE-R17` must not be cited as covering it.
