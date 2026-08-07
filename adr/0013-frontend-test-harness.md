# ADR 0013 — Test the new frontend with Vitest in two projects: real-browser component tests, Node contract tests

**Status:** Superseded 2026-08-05 — descoped with the frontend rebuild (ADR 0012); the harness it
specifies shipped in PR #25 and was removed from `main` with the SvelteKit portal. Text and harness
both live on branch `alt/sveltekit-portal`. **The gap it was written against is still open and now
has nothing scheduled against it:** there is no JavaScript test harness in this repository, and the
intake contract break that §4 deliverable 3 was to make impossible as a *class* is still live on
`main` (`docs/debt-log.md`, "Intake contract break"). A future JS gate should re-read §2's
measurement before re-deciding.
**Date:** 2026-07-30
**Author:** Riverbend engagement team
**Debt:** none directly — new scope (`docs/specs-deprecated/frontend-rebuild.md` §4 deliverable 3). The gap it
closes is the unregistered defect that spec §4 deliverable 6 is adding to `docs/debt-log.md` (the
intake contract break). Adjacent to D1 through `FE-R16` and to D4 through `FE-R2`; it closes neither.

## Context

There is **no JavaScript test harness in this repository.** Measured rather than recalled:
`frontend/package.json` declares four scripts (`dev`, `build`, `start`, `lint`) and no test script,
and its `devDependencies` are `@types/*` plus `typescript` — no runner of any kind. The CI frontend
job (`.github/workflows/ci.yml`, `jobs.frontend`) is `npm install` then `npm run build`, with
`working-directory: frontend` hardcoded. Every piece of frontend logic shipped so far was proven by
node-eval in a session and then discarded; nothing asserts it again.

What that costs is not hypothetical:

- **The intake contract break.** Three payload mismatches between the portal and `intake-service`
  (`first_name`/`last_name` vs `name`; a `consents` object vs `list[ConsentKind]`;
  `insurance.carrier` vs `payer_name`). Every submission 422s, the gateway relays it as HTTP 200, the
  portal prints "Intake submitted successfully.", and no patient row is created. It shipped green past
  `npm run build` **and** past 730 passing pytest tests, because nothing asserts the two sides of that
  payload against each other. `docs/specs-deprecated/frontend-rebuild.md` §1.
- **The review loop keeps asking.** Codex requested frontend tests on PR #8 and PR #9. A finding that
  recurs across PRs is the C-class case in `docs/review-loop-metrics.md`; a harness is what stops it
  recurring rather than being re-argued.

`adr/0012-frontend-framework-sveltekit.md` §7 deliberately left this open: "The test harness.
`docs/specs-deprecated/frontend-rebuild.md` §4 deliverable 3 requires its own ADR written **after** this one;
Vitest is the presumptive shape and is not chosen by this file." G1 is signed, so that precondition is
discharged.

The requirement set, not general good practice, is what this harness has to serve.
`docs/specs-deprecated/frontend-rebuild.md` §5 names a verification method per requirement, and the JS-side load
is: eight **component tests** (`FE-R4`, `R5`, `R7`, `R9`, `R10`, `R11`, `R20`, and `R2`'s DOM half),
two **JS tests** (`FE-R2` both branches, `FE-R3`), a **contract test** asserted from both sides
(`FE-R1`, `FE-R3`, `FE-R21`, `FE-R22`), one **formatter unit test run under a non-clinic `TZ`**
(`FE-R8`), and one **CI job that fails the build** (`FE-R17`). `FE-R16` additionally inherits
CLAUDE.md §5's negative-test rule: anything that surfaces a message needs an adversarial test, with
PHI placed where the code does not expect it.

Three constraints bound the choice:

- **Svelte 5 runes do not evaluate outside a component context.** `$state`/`$derived` are compiler
  constructs; a plain Node test importing a `.svelte` component's reactive state is not a lighter
  version of a browser test, it is a test of something else. This decides the environment split rather
  than expressing a preference.
- **Two frontends coexist** until `FE-R1`–`FE-R3` pass on the new app (`FE-R15`, ADR 0012 §1). CI's
  one frontend job assumes a single directory.
- **The Python gate is containerised because the host cannot run it** (CLAUDE.md §3: local Python is
  3.8, `make test-docker` is the only way). Node is the mirror-image hazard: this machine has Node
  **26.5.0** while CI and the runtime image pin **22**. A JS gate proven only on the host's Node is
  proven on a version nothing deploys.

## Decision

**Vitest**, configured as **two projects in one config**, in the new SvelteKit app's own directory,
with the contract fixture living outside both frontends.

### 1. Two projects, split by what the test needs to be true

| Project | Environment | Matches | Serves |
|---|---|---|---|
| `client` | real browser (Chromium), `@vitest/browser` + `vitest-browser-svelte` | `src/**/*.svelte.test.ts` | `FE-R2` (DOM half), `R4`, `R5`, `R7`, `R9`, `R10`, `R11`, `R16`, `R20` |
| `server` | Node | `src/**/*.test.ts`, `tests/**/*.test.ts` | `FE-R1`, `R2` (branch logic), `R3`, `R8`, `R21` (JS side) |

> **Package name corrected 2026-07-31 at implementation — see §Implementation-round corrections.**
> Vitest 4 moved the Playwright provider out of `@vitest/browser` into **`@vitest/browser-playwright`**,
> which is the package the config actually names. `@vitest/browser` arrives as its dependency.

**Invariant: component behaviour is asserted in a real browser engine, never in a DOM shim.** The
mechanism (`@vitest/browser` with the Playwright Chromium provider) is a value that may change; the
invariant is that a passing component test corresponds to something a browser actually did.

This is the criterion the decision leans on, so it is stated against specific requirements — and
scoped honestly, because almost none of the list needs it. Of the twelve requirements this harness is
accountable for, **eleven would be served correctly by a DOM shim**: `FE-R2` (branch logic), `R3`, `R8`
and `R21` are pure logic and live in the `server` project regardless, and `FE-R4`, `R5`, `R9`, `R10`,
`R11`, `R16` and `R20` are presence-and-text assertions — the header shows name/DOB/MRN; allergy status
reads unavailable rather than blank; a row shows date and time; a past slot offers no booking action; an
unanswered consent does not read as declined; a message carries no PHI; the eligibility result is
displayed. A shim answers all of those.

So the browser is bought for **one requirement in the twelve plus one widget outside them**, and the
decision should be read that thinly:

- **`FE-R7`, date-of-birth entry.** "A typed date is accepted, and any year from 1900 is reachable
  without month-by-month traversal." jsdom's `<input type="date">` is effectively a text input: no
  value-format semantics, no picker, no keyboard stepping. It therefore cannot distinguish "typing a
  date works" from "typing a date does nothing" — it asserts markup and reports green. This is
  precisely the finding ADR 0008 raised and ADR 0012 §6 re-owed by dropping `react-day-picker`, which
  makes it the requirement most exposed to being signed off on false evidence.
- **The patient-search combobox** — the control replacing the raw numeric ID box, so the interface
  behind `FE-R6` and `FE-R25`. Note that both of those rows are verified by `driven repro` in §5, not by
  a component test, so this is the browser buying *automated coverage the spec does not currently ask
  for* on the single most load-bearing new widget in the rebuild. Keyboard navigation, real focus,
  `aria-activedescendant`, and scrolling the active option into view: jsdom has no layout and no
  scrolling, so none of it is verifiable there.

Secondarily, rune-driven state in `.svelte.ts` modules is where the ecosystem's migration pressure
actually comes from, and Playwright's locator API is the same one an E2E suite would use if §2 is ever
reopened — so the shim path means learning two APIs later.

**The honest size of this decision:** one requirement (`FE-R7`) cannot be verified without it, one
widget gets coverage it would otherwise not have, and the cost is a cached browser binary in CI. It is
not a large win, and it is recorded at that size so nobody later cites "we test in a real browser" as
evidence of rigour it does not carry.

**An argument deliberately not used:** accessible-name computation. An earlier draft of this decision
claimed the browser wins there. `@testing-library/dom` ships `dom-accessibility-api`, which is a
reimplementation of the algorithm rather than the browser's own, but a serviceable one. The claim is
withdrawn rather than quietly softened, because an ADR that keeps a weak argument invites a review
round to knock it down and take the sound ones with it.

Once the shim is rejected there is no cheap DOM environment left, so *every* component test runs in
the browser — including the seven DOM assertions that would not have needed it. The split in the table above is
therefore about keeping pure logic out of a browser, not about rationing the browser between
components.

The `.svelte.test.ts` suffix is load-bearing, not cosmetic: the Svelte compiler treats
`*.svelte.js`/`*.svelte.ts` as rune-capable, so the suffix is what lets a test file use `$state` when
driving a component. It is also what the two projects glob on, so a misnamed file runs in the wrong
environment — name it wrong and the test silently loses its browser.

### 2. Playwright enters as a browser provider, not as an E2E framework

**No end-to-end suite is adopted here.** The spec's five `driven repro` requirements (`FE-R1`, `R6`,
`R14`, `R20`, `R25`) stay human-verified at their gates, where the gate text already insists on it —
G2: "`make test-docker` **and** driving the app; a 200 proves nothing here."

Two reasons, both specific:

- An E2E suite against a stubbed gateway would prove the stub's shape, which is what the contract
  fixture already does more cheaply and more honestly. An E2E suite against a **live** stack proves
  something real, and that is exactly what a gate reviewer driving the app does.
- E2E against a live stack means seeded patient data in CI artifacts — Playwright traces, videos and
  failure screenshots. The seed is synthetic, but "PHI-shaped data in build artifacts" is a decision
  for the PHI boundary (CLAUDE.md §6), not a testing convenience, and it should be made deliberately
  in its own ADR rather than acquired as a side effect of installing a test runner.

> **Corrected 2026-07-31 at implementation — the artifact surface is not E2E-specific.** The bullet
> above attributes traces/screenshots to E2E. Measured while building the harness: **browser-mode
> component tests write a PNG of the rendered component on every failure**, with no E2E suite
> anywhere. The reasoning survives — it is the artifact that matters, not which suite produced it —
> but the mitigation had to be real rather than implied, so the `client` project sets
> `browser.screenshotFailures: false` and that was proven by failing a test and confirming no image
> is written. See §Implementation-round corrections.

**What would reopen it:** a P6 queue surface with a genuinely multi-step flow (search → select →
book → cancel) where hand-driving each gate stops being reliable; or the driven-repro list growing
past what a reviewer will actually re-run. Then: a separate ADR covering artifact retention.

**Provenance, recorded because this was decided twice.** The deferral was put to the user on
2026-07-30, overturned — "E2E will be essential" — and then re-deferred by the user the same day on
recalling the artifact/PHI surface. Both directions are kept here on purpose. E2E is not rejected on
merit: it is the only level that sees a *composition* defect, and the intake break is exactly that
shape (a 422 relayed as a 200 and rendered as success, with each layer individually plausible). What
defers it is that the honest configuration — a live composed stack seeded with patient-shaped records —
introduces a PHI surface into CI that does not exist today, and that is an ADR of its own, not a line
item in a testing-tools decision.

> **Amended 2026-07-31 — this ADR was written before ADR 0014 added three G2 requirements it cannot
> fully cover; see §Audit-round corrections finding 2.** `FE-R27`–`FE-R29` (ADR 0014) are verified
> "after login" and "after a name search and a chart view". §7's guarantee table promises component
> tests run with "no server, no database and no network" and that no patient-shaped data enters CI —
> which is also the reason §2 holds. ADR 0014's Consequences nevertheless states these are "all P2,
> ADR 0013's harness". Both cannot be true.
>
> **Resolved by splitting the evidence per requirement, not by adopting E2E.** §2's reason for
> deferring E2E is a PHI-boundary reason and nothing about it changed; adopting E2E to unblock a gate
> would be acquiring a CI PHI surface as a side effect of schedule pressure, which is the specific
> thing §2 warns against. The split is finer than all-or-nothing:
>
> | Requirement | This harness proves | Driven at the gate against a local composed stack |
> |---|---|---|
> | `FE-R27` no token in JS reach | — | all of it: login, then scan `document.cookie` and every web-storage key/value |
> | `FE-R28` idle logoff | the timer logic, as a pure function in the `server` project | the 401 on a request made after the timeout, i.e. server-side invalidation |
> | `FE-R29` no patient data in web storage | a component fed fixture data writes **nothing** to storage — real coverage, no server and no network needed | post-search and post-chart storage state on the running app |
>
> **Invariant: which half of each requirement is CI-proven and which is gate-driven is written down
> per requirement, never left to inference.** `docs/specs-deprecated/frontend-rebuild.md` §5's verification column
> carries it. The driven halves are recorded at G2 the way the gate text already demands ("`make
> test-docker` **and** driving the app; a 200 proves nothing here"), and they join the five existing
> `driven repro` rows under gap #3 — which is now the largest hole in this ADR by a wider margin than
> when it was written. §2's existing reopen triggers are unchanged; this amendment adds none.

### 3. One contract fixture, owned by neither side

`FE-R3` says "one shared intake payload fixture asserted by both a pytest test and a JS test." The
fixture lives at **`tests/contracts/intake_payload.json`** — under the existing `tests/` tree, which
is neither frontend's directory, so neither can quietly fork it. **Invariant: both suites read that
one path at test time.** A copy inside a frontend directory, a symlink, or a fixture regenerated from
either side is a defect, not an optimisation.

Three assertions, and the third is the one that would not be written by default:

1. **pytest** — the fixture validates against intake-service's real `IntakeRequest`, loaded by file
   path through the existing `tests/conftest.py::load_module` helper. No new import machinery; this is
   how every other test in `tests/` reaches a service module (ADR 0001: no shared package).
2. **JS (`server` project)** — the portal's request-payload builder, called with the form state that
   the fixture describes, deep-equals the fixture. This is why the builder must be a plain function
   importable without mounting a component.
3. **pytest** — the set of consent identifiers in the fixture equals the members of `ConsentKind`
   **exactly** (`services/intake-service/schemas.py:8`), as set equality, not containment. Widening
   the enum for the two consents the form collects and cannot store (spec §8.1: financial
   responsibility, electronic communications) without teaching the form about them fails this, and so
   does the reverse. That is `FE-R21` — "the portal shall not collect a consent that cannot be stored"
   — expressed as an assertion instead of a review habit.

> **Amended 2026-07-31 — assertion 3 as written is unsatisfiable; see §Audit-round corrections
> finding 5.** The intake form collects **four** consents (`frontend/app/intake/page.tsx:328-341`:
> treatment, NPP/privacy, financial responsibility, electronic communications) and spec §8.1 widens
> `ConsentKind` to **five**. `roi_consent` is collected by **no UI anywhere** — it exists only in
> `services/intake-service/schemas.py:22`, the `db/schema.sql:121` / `models.py:44` comments, and
> `tests/test_intake_schemas.py:65`. Set equality can therefore only pass by putting a consent in the
> intake fixture that intake never collects, and the predictable resolution under gate pressure is to
> quietly relax it.
>
> **Assertion 3 is replaced by three assertions with distinct jobs.** The framing that containment is
> the weaker option is also withdrawn — for `FE-R21` containment is the *correct* operator, and what
> set-equality was actually reaching for is served better by 3b:
>
> - **3a — `FE-R21`, pytest: every consent identifier in the fixture is a member of `ConsentKind`**
>   (subset). This is exactly "the portal shall not collect a consent that cannot be stored": a form
>   that collects an unstorable consent fails it.
> - **3b — the D1 boundary, pytest: `ConsentKind`'s members equal the five documented literals
>   exactly**, pinned as literals in the test (`npp_ack`, `treatment_consent`, `roi_consent`,
>   `financial_responsibility_ack`, `communications_opt_in`). A silent sixth member, or a widening to
>   bare `str`, fails here. This is the assertion that protects the PHI control the enum *is*
>   (spec §8.1), and it is what set-equality was conflating with `FE-R21`.
> - **3c — the drift that actually broke intake** is assertion 2 above, unchanged. It is the only one
>   of the three that compares the portal's builder against the fixture.
>
> **Not done: splitting `ConsentKind` by surface.** `roi_consent` genuinely belongs to the ROI surface
> rather than intake, so a per-surface enum is defensible — but `consents.kind` is one `TEXT` column in
> one table, and splitting a documented PHI control for no current benefit is not worth the §6 touch.
> Deferred, recorded here so it is a decision rather than an oversight.

`FE-R22` is not satisfied by the fixture and must not be assumed to be. The existing adversarial test
that rejects an out-of-set consent identifier has to be **re-proven to discriminate** after the enum
is widened; the enum is a PHI control (its docstring records free text reaching the intake log), so a
widened set that quietly accepts anything reopens D1.

The fixture is committed, therefore it carries synthetic values only, drawn from the same shapes
`db/seed/generate_seed.py` produces. The `phi-secret-guard` PreToolUse hook is a second net here, not
the rule.

### 4. Time zone: an explicit zone, proven under a wrong ambient one

`FE-R8` is verified by "unit test on the formatter, run under a non-clinic `TZ`". Two parts, and the
second is what makes the first mean anything:

- The formatter takes an **explicit IANA zone** (`America/New_York`) as data. It never reads the
  ambient zone, and it applies no offset arithmetic of its own — `FE-R26` forbids the compensating
  offset that the wrongly-stored seed instants invite (spec §8 #9; that correction belongs to the
  data).
- **Invariant: at least one CI execution of the whole JS suite runs under an ambient `TZ` that is not
  the clinic's.** Value: `TZ=America/Chicago`, the zone on the machine where slots rendered
  03:00–06:00. An accidental ambient-zone dependency then fails instead of passing by luck on a
  machine that happens to be in Eastern time.

The `client` project cannot set a process `TZ` per test, so the formatter tests are `server`-project
tests over a pure function; the component tests assert that a row displays the string the formatter
produced, not that they compute time themselves (`FE-R9`).

### 5. CI: the gate is a job, not a hook

The `frontend` job stays as it is, for the old portal, for the length of the `FE-R15` coexistence
window. A **second job** covers the new app and runs, in order:

1. `npm ci` — against a committed lockfile, on `node-version: "22"`, matching the runtime image.
   **Verified 2026-07-31, and one hazard the lockfile has to absorb:** `vitest@4.1.10` declares
   `engines: ^20 || ^22 || >=24`, `playwright@1.62.1` declares `>=20` and `svelte-check@4.7.4`
   declares `>=18`, so Node 22 is supported by all three. But `@vitest/browser@4.1.10` peers `vitest`
   at an **exact** version while `vitest-browser-svelte@3.0.0` peers `^4.0.0` — a lone `vitest` patch
   bump breaks the install, so the three move together or not at all.
2. `npx playwright install --with-deps chromium` — explicit, cached.
3. `svelte-check --fail-on-warnings` — this is `FE-R17`'s "the build shall fail when an interactive
   element lacks an accessible name" (ADR 0012 §5: the invariant is that the build fails; the
   mechanism is a value).
4. `vitest run` — both projects.
5. `npm run build`.

This job, not a local hook, is the gate. CLAUDE.md §10.1: "A check that exists only as a hook is
advisory by construction", and `.claude/` is untracked, so CI cannot see any of it.

A `make test-frontend` target lands alongside, so the JS gate is invocable the same way the Python one
is. It is a convenience over the same commands, not a second definition of the gate.

The pytest job needs no change — it picks up `tests/contracts/` automatically. "Both jobs" in `FE-R3`
means the existing `tests` job and the new frontend job, and the fixture is what they have in common.

### 6. No coverage threshold; requirement IDs in test names instead

**Rejected: a coverage percentage gate.** There is no defensible floor to anchor it to (project memory
`thresholds-must-be-reachable`: a threshold has to be anchored to something measured, and nothing here
measures a meaningful frontend coverage floor), and it rewards covering the easy bulk of the app over
the twelve requirements this harness is accountable for (`FE-R2`–`R5`, `R7`–`R11`, `R16`, `R20`, `R21`).

Instead: **every test satisfying a spec requirement names that requirement's ID in its title** —
`describe('FE-R7 · DOB entry', …)`. A gate reviewer greps `FE-R7` and reads the assertion. That is
checkable by a human in seconds and needs no tooling.

### 7. The binding constraint: nothing the repository guarantees today may get weaker

Stated as the user's criterion, 2026-07-30: choose a stack that causes **no regression from the current
implementation.** The current implementation's guarantees are thin, which makes them easy to enumerate
and therefore easy to check rather than assert.

| Guarantee today | Where it comes from | Effect of this decision |
|---|---|---|
| The frontend typechecks and compiles | `npm run build` in `jobs.frontend` | **Improved** — `svelte-check --fail-on-warnings` is types plus the `FE-R17` accessible-name gate |
| 730 pytest tests, in a 3.12 container | `jobs.tests` / `make test-docker` | **Unchanged** — `tests/contracts/` adds test files, not runner mechanics |
| The existing portal keeps building | that same job | **Unchanged** — the job is not touched; the new app gets a second one (`FE-R15`) |
| No patient-shaped data anywhere in CI | nothing in CI seeds a database | **Preserved, and it is why §2 holds.** Component tests run with no server, no database and no network — which is also why the driven halves of `FE-R27`–`R29` are gate-verified rather than CI-verified (§2's 2026-07-31 amendment) |
| Merge gates live in CI, not in local hooks | CLAUDE.md §10.1; `.claude/` is untracked | Preserved — §5 puts the gate in a job |
| Gates run on the Node version that deploys | CI and the image both pin 22 | Preserved by pinning 22 in the new job; the host's Node 26 is not the gate |
| No test tooling in a runtime image | accident, not design — `frontend/Dockerfile` runs a bare `npm install` and ships devDependencies | **Improved** — `npm ci --omit=dev`, Chromium fetched only in CI |

The two regressions available here were the ones nobody notices until late, and both are closed above:
patient-shaped data entering CI artifacts (§2), and a browser binary entering a runtime image
(Consequences).

**What this harness cannot do, and must not be credited with: proving feature parity with the portal it
replaces.** The old portal has no tests, and part of its behaviour *is* the defect being replaced — a
chart that shows no patient identity, a success message over a 422. Characterization tests, which
CLAUDE.md §5 would otherwise prescribe before touching untested code, would pin those bugs in place;
that rule governs refactoring code you intend to keep. Parity therefore stays proven by the driven
repro at G2–G5, and this harness's job is narrower and stateable: stop the **new** app from re-shipping
a contract break.

### 8. Not decided here

The new app's directory name and internal layout (P2). The component-gallery question (spec §8 #5)
stays deferred — note that Storybook's Vitest integration would *reuse* this harness rather than
replace it, so choosing it later costs nothing here. Automated accessibility auditing beyond
accessible names (e.g. axe) is not adopted; ADR 0012 gap #5 stands unchanged — contrast, focus order
and reading order remain uncovered by CI.

> **Amended 2026-07-31 — the premise of that last sentence was wrong.** It declined axe as coverage
> *beyond* accessible names, assuming accessible names were already covered by the `FE-R17` gate.
> Measurement (ADR 0012 §5's amendment) shows the gate covers them on **buttons and links only** —
> silent on `<input>`, `<select>` and `<textarea>` names, on spread attributes and on `role="button"`
> elements — and `eslint-plugin-svelte` ships **zero** a11y rules, so spec decision #15 does not close
> it either. For the five-form surface and the search combobox, axe is no longer "beyond" the gate; it
> *is* the gate, or nothing is. **Re-opened as gap #9** rather than adopted here, because it is a scope
> change whose cost should be measured against P3's real primitives instead of estimated now.

## Alternatives considered

**`@testing-library/svelte` + jsdom — the documented default, and it loses on one of twelve
requirements plus one widget.** Not a strawman, and the accounting is stated in its favour: it is what
`svelte.dev/docs/svelte/testing` still documents (`npm install -D jsdom`, plus
`resolve.conditions: ['browser']` so Vitest picks browser entry points while running in Node), it needs
no browser download in CI, it is faster per file, and it is the shape a React-experienced maintainer
would recognise — which mitigates ADR 0012's open gap #2. **Eleven of the twelve requirements would be
served correctly by it** (§1). It loses on `FE-R7` and on the patient-search combobox, for the reasons
in §1, and secondarily on rune-driven state. Choosing it would mean amending `FE-R7`'s verification
method in `docs/specs-deprecated/frontend-rebuild.md` §5 from "component test" to a documented manual repro,
because a jsdom test of that requirement passes without evidence. Trading a cached browser binary for
honest verification of the DOB field and the control that replaces the ID box is the trade this ADR
takes.

**jsdom now, add the browser project when `FE-R7` is built.** The nearest miss. Because the two-project
split exists either way, this defers the Chromium cost rather than avoiding it, and the end state is
identical. It loses on drift: the deferral has to be enforced by a written trigger that fires exactly
when the most false-green-prone requirement in the set is implemented, and a trigger that must fire at
the moment of maximum schedule pressure is a weak control. Rejected in favour of paying a one-time cost
in P2.

**Jest.** Not scored in depth: the Vite config, the Svelte plugin and the alias/`$lib` resolution
already exist for the app build, and Vitest reuses them. Jest needs a parallel transform pipeline for
`.svelte` files that would then drift from the build's.

**Status quo — node-eval in a session, no committed tests.** Recorded because it is the incumbent and
it is what shipped the contract break green past a passing build and 730 passing Python tests.

**On the runner choice being thin, stated rather than dressed up.** Vitest arrived as the presumptive
candidate (project memory `frontend-test-harness-todo`, 2026-07-21, when the stack was still React) and
ADR 0012 §7 carried it forward as presumptive-not-chosen. This file ratifies it; it did not run a real
bake-off, because the discriminator — Vitest reuses the app's own Vite/Svelte config and resolution
while every alternative needs a second pipeline that can drift from the build — is close to a one-way
door and is not Riverbend-specific. Confirmed by the user 2026-07-30. The decisions with actual content
in this ADR are the environment split (§1), the E2E deferral (§2), the fixture's location and its
set-equality assertion (§3), and the absence of a coverage threshold (§6).

**Playwright E2E now.** See §2 — deferred with named triggers, not rejected on principle.

**npm workspaces at the repository root.** Rejected. It adds a root `package.json` and hoists
`node_modules`, while `jobs.frontend` hardcodes `working-directory: frontend` and each frontend image
is built from its own directory as its own compose build context. Two apps, two lockfiles, two CI
jobs, for the coexistence window only — then one, when the Next.js portal goes.

**Assert the contract on the pytest side only.** Rejected: validating the fixture against
`IntakeRequest` proves the fixture is valid, not that the portal sends it. The drift that broke intake
was between the builder and the model, and only assertion 2 in §3 sees it.

## How this serves the client and domain

Front desk's registration cannot silently 422 again without a red CI job: the payload the portal
builds and the payload intake-service accepts are asserted against one committed file, from both
sides. An auditor asking how Riverbend knows an operator-facing error does not leak PHI gets a named
adversarial test rather than a policy sentence. And the two-frontend window that `FE-R15` requires is
covered by two CI jobs instead of trust.

## Accepted tradeoffs / deferred gaps

1. **CI gains a Chromium download, and its cost here is unmeasured [?].** Cached between runs, on a
   workflow that already builds eight service images and runs a gitleaks container, so the ratio is
   plausibly small — but no number is asserted, because none was measured. If it stops being cached and
   starts dominating the run, the split in §1 is what makes moving the cheap tests back to Node a config
   change rather than a rewrite.
2. **Component tests are Chromium-only; cross-browser behaviour is unverified [?].** No requirement in
   §5 names a browser. What closes it: adding Firefox/WebKit to the provider list the first time a
   browser-specific defect is observed, which is a config change.
3. **The five `driven repro` requirements stay human-verified.** They are therefore only as reliable
   as the gate reviewer's willingness to actually drive the app. This is a deliberate consequence of
   §2 and it is the largest hole in this ADR. Trigger to revisit is stated there.

   **Widened 2026-07-31:** the driven set is no longer five. `FE-R27`, the 401 half of `FE-R28`, and
   the post-search/post-chart half of `FE-R29` join it (§2's amendment), and all three are **G2**
   requirements — so the gate that blocks every later phase now depends on gate-driven evidence, not
   only the later gates. Two consequences worth stating rather than discovering: the driven checks must
   be **recorded** (what was driven, what was observed) so G2's signature rests on something re-readable,
   and this is now much closer to §2's own reopen trigger ("the driven-repro list growing past what a
   reviewer will actually re-run") than it was when that trigger was written.
4. **This harness cannot test the old Next.js portal.** `FE-R15` keeps it runnable and untested for
   the coexistence window. Acceptable only because it is being deleted; nothing new should be built in
   it, and a defect found there is a reason to accelerate P2, not to retrofit React test tooling.
5. **The contract fixture proves shape, not persistence.** A payload that validates and round-trips
   still does not prove intake wrote a row, and `FE-R1` is satisfied only with the driven repro at G2.
   Do not let a green contract test be reported as "intake works."
6. **Suite runtime is unmeasured [?].** Browser-mode component tests are slower than jsdom by an
   amount nobody here has measured. Recorded rather than estimated; the first real suite is the
   measurement.
7. **A harness makes the codebase legible only if the tests read as behaviour.** ADR 0012 gap #2
   (Svelte unfamiliarity) is helped by this file, not closed by it, and choosing the less familiar
   tooling in §1 spends a little of that budget.
8. **The browser project's justification is thin, and it is contingent on how `FE-R7` gets built.**
   Eleven of the twelve requirements would be served by a shim (§1). If `FE-R7` lands as a bare native
   `<input type="date">` with no custom picker — the option ADR 0008 rejected and ADR 0012 gap #3
   reopened — then the browser's remaining value is the search combobox alone, and this decision should
   be revisited on that evidence rather than treated as settled. Recorded so the revisit is legitimate
   instead of looking like churn.

9. **The accessible-name gate is narrower than ADR 0012 claimed, and this harness does not cover the
   gap [added 2026-07-31].** Measured: `svelte-check` is silent on `<input>`/`<select>`/`<textarea>`
   accessible names, on spread attributes and on `role="button"` elements, and `eslint-plugin-svelte`
   has no a11y rules at all. So the five-form surface and the patient-search combobox — the surfaces
   ADR 0012 and §1 respectively lean on hardest — have **no automated accessible-name coverage** today.
   Acceptable only because nothing is built yet and `FE-R17`'s wording is being narrowed to match its
   mechanism rather than left overstated. **What closes it:** `axe-core` inside the `client` project
   against real primitives (§8's amendment), decided at P3 when its cost can be measured against real
   components; or a custom eslint rule; or accepting the narrower scope in writing. **Do not** cite
   `FE-R17` as accessible-name coverage for form controls until one of those lands.

## Consequences

**New, in the new app's directory:** a `test` block in the Vite/Vitest config defining the two
projects; `devDependencies` for `vitest`, `@vitest/browser`, `vitest-browser-svelte`, `playwright`,
`svelte-check`; `test` / `test:unit` / `check` scripts; a committed `package-lock.json`.

**New, outside it:** `tests/contracts/intake_payload.json` and its pytest assertions;
`.github/workflows/ci.yml` gains the second frontend job described in §5; `Makefile` gains
`make test-frontend`; `docs/specs-deprecated/frontend-rebuild.md` §4 deliverable 3 is discharged by this file.

**The runtime image must not carry test tooling.** Note the existing pattern before copying it:
`frontend/Dockerfile` runs a bare `npm install`, which installs devDependencies into the image it
ships. Copying that for the new app would put a browser driver in a runtime image. The new Dockerfile
installs production dependencies only (`npm ci --omit=dev`), and the Chromium binary is fetched
explicitly in CI (§5 step 2) and nowhere else. **To be verified against the built image, not
assumed.**

**Fresh-deploy default:** nothing in the running system changes. No new environment variable, no new
service, no new port; ADR 0012 §4's request-time `GATEWAY_URL` rule is untouched. The only new default
is `TZ=America/Chicago` in the test environment, which exists solely to make `FE-R8` fail honestly.

**`/verify-stack` needs a step for the JS gate.** That skill lives in untracked `.claude/`, so the
edit is **not part of this ADR's PR diff** — it is a local tooling change, snapshotted by
`../.riverbend-tooling-snapshots/` (CLAUDE.md §10.1), and stated here because a reader of this ADR
would otherwise reasonably assume the pre-push ritual picked it up automatically.

**Now easier:** every component-test requirement in `FE-R4`–`FE-R11`; proving a redaction or
error-surface path adversarially on the JS side; retiring the node-eval habit. **Now harder:** nothing
in the build path; the friction is one browser download in CI and a Node-version discipline (§Context)
that did not previously matter because nothing ran.

**Tests that hold the line once implementation starts:** the two-sided contract pair over
`tests/contracts/intake_payload.json` (`FE-R3`) is what makes the intake break unrepeatable; the
set-equality consent assertion (`FE-R21`) is what keeps the form and the enum together; the formatter
test under a non-clinic `TZ` (`FE-R8`) is what keeps clinic time from becoming viewer time again; the
`svelte-check` job (`FE-R17`) is the accessible-name gate. A failure in any of those four is a
regression of this decision rather than a new defect.

## Future: the Next.js portal is retired — what changes

When `FE-R1`–`FE-R3` pass on the new frontend and the old portal is deleted (ADR 0012's closing
section): the original `frontend` job goes, the surviving job stops needing a disambiguating name, and
`working-directory` ceases to be ambiguous. `tests/contracts/` does not move — it is deliberately
outside both frontends so that this step is a deletion and not a migration.

## Audit-round corrections (2026-07-31)

Pre-P2 adversarial audit, run before any frontend code exists. Not an automated review round, so
`docs/review-loop-metrics.md` §4 gains no entry; in that file's vocabulary these are **A-class** —
defects in the document as written. Append-only per `adr/_template.md`, with in-place amendment blocks
where an unmarked original sentence would let the stale copy win.

**Finding 2 — this ADR and ADR 0014 contradict each other, one day apart.** ADR 0014 assigns
`FE-R27`–`R29` to "ADR 0013's harness" while §7 guarantees component tests run with no server, no
database and no network. Resolved in §2's amendment by splitting the evidence per requirement — CI
proves the timer logic and the component-level no-write; the login and post-search halves are
gate-driven and recorded. E2E is **not** adopted: §2's reason for deferring it is a PHI-boundary reason
that this finding does not change, and adopting it to unblock a gate would acquire a CI PHI surface as a
side effect of schedule pressure. Gap #3 widens accordingly.

**Finding 5 — §3's assertion 3 was unsatisfiable.** The intake form collects four consents, the widened
`ConsentKind` has five, and `roi_consent` is collected by no UI. Replaced by 3a (subset — this is
`FE-R21`), 3b (enum members pinned as literals — this is the D1 boundary), and 3c (the existing
builder-vs-fixture deep-equal — the only one that sees the drift that broke intake). The claim that
containment is the weaker operator is **withdrawn**: for `FE-R21` it is the correct one, and set-equality
was conflating `FE-R21` with the enum-pinning assertion. Splitting `ConsentKind` per surface is
considered and deferred.

**Finding 4/3 — §8's axe refusal rested on a false premise.** It declined axe as coverage *beyond*
accessible names; measurement shows accessible names are covered on buttons and links only, and
`eslint-plugin-svelte` has no a11y rules. §8 carries the amendment and gap #9 is added.

**Node/peer verification (Q5 of the audit).** Recorded in §5 step 1 rather than here, because it is a
fact the CI job needs at the point of use: Node 22 is supported by all three of `vitest`, `playwright`
and `svelte-check`, but `@vitest/browser` peers `vitest` at an exact version, so the trio must be bumped
together.

**Unchanged by the audit, checked and worth stating:** the fixture's location outside both frontends
(§3), the two-project split (§1), the `TZ` discipline (§4), the no-coverage-threshold decision (§6),
and §7's regression table apart from the one row corrected above.

## Implementation-round corrections (2026-07-31)

Written while building the harness (P2 PR 1) — the first time any claim in this file met a running
runner. Append-only per `adr/_template.md`, with in-place markers in §1 and §2. A-class in
`docs/review-loop-metrics.md`'s vocabulary (defects in the document as written), but not an
automated round, so that file gains no entry.

**Finding 1 — the Playwright provider is its own package in Vitest 4.** The Consequences list names
`@vitest/browser`; `@vitest/browser-playwright@4.1.10` is what exports the `playwright()` provider
the config calls, and it depends on `@vitest/browser`. §1 carries the correction. The exact-peer
hazard §5 step 1 warns about is confirmed and applies to this package (`peerDependencies: { vitest:
'4.1.10' }`), so **`vitest` and `@vitest/browser-playwright` are pinned exactly rather than
caret-ranged** in `portal/package.json` — the coupling is written into the manifest instead of left
to a reader remembering §5.

**Finding 2 — §2's artifact reasoning was scoped to E2E, and the artifact is not.** Browser-mode
component tests write `.vitest-attachments/*.png` and `__screenshots__/*.png` on failure. This was
discovered the ordinary way: a deliberately failed smoke test left two PNGs in the working tree.
Component tests are fed fixtures rather than live data, but `FE-R4`/`FE-R5`/`FE-R20` fixtures are
patient-*shaped* by construction, and an image of one is exactly the CI surface §2 declined to
acquire. Closed at the source — `browser.screenshotFailures: false`, verified by re-failing the test
and confirming nothing is written — with `.gitignore` entries as a second net rather than the
control. **Nothing in §2's E2E deferral changes**; if E2E is ever adopted, its own ADR now has one
fewer thing to discover.

**Finding 3 — the browser project's cost is no longer unmeasured (gap #1/#6, partial).** On this
scaffold: the full suite (2 Node files, 1 browser file) runs in **~2.0s** on Node 22 in a container
with the browser cached, against ~0.2s for the Node project alone. The Chromium download is ~95 MB
and ~30s uncached. Both numbers are for a three-test suite and say nothing about a real one — they
are recorded so the first real measurement has a baseline, not to close the gaps.

**Unchanged and confirmed by running it:** the two-project split works as specified, the
`.svelte.test.ts` suffix does discriminate (a file named `*.test.ts` runs in Node and fails on
`import { page } from 'vitest/browser'`), the `TZ` discipline in §4 holds — and is now enforced by
`portal/tests/ambient-timezone.test.ts`, which fails under `TZ=America/New_York`, proven by running
it that way.
