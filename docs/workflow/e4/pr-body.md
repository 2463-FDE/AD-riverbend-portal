# E4 — registration works, fails honestly, and is contract-guarded

> Status: MERGED e68fea8 2026-08-10
>
> Lifecycle: `DRAFT` → `IMPLEMENTED 2026-08-10` (impl gate, record below) → `PUSHED PR #72
> 2026-08-10` → `MERGED e68fea8 2026-08-10`. Pushed as `fix/noref-registration-contract` @
> `e40d4b0`; squash-merged to `main` at `e68fea8`, branch deleted.
>
> **Review loop: one round, closed at r1 without a code change.** Codex returned a single `[high]`
> finding — a lost registration response can be retried into a duplicate chart, because
> `POST /intake` carries no idempotency key — with a `needs-attention` / no-ship verdict. The
> premise was accepted and the finding declined as the accepted residual disclosed below
> (*Accepted residuals*, bullet 1): the fix persists state, so it is a design-gated stage-3 change,
> and the reviewer's cheaper alternative contradicts frozen E4-SPEC-7. One correction to the
> finding, verified against `main`: the window is inherited, not introduced here — `main`'s
> `create_intake` had a wider one — what this branch changed is that it became reachable. Full
> disposition: `findings.md` §Review round 1, PR #72 comment, `docs/review-loop-metrics.md` §4.
>
> **The residual was not merely declined — it was rehomed.** Owner direction 2026-08-10: `e5` is
> widened by a second chunk carrying it (`docs/workflow/e5/requirements.md` §2.1, E5-REQ-10 through
> E5-REQ-13, DRAFT). Two of those requirements are guards the review did not ask for: idempotency
> must not become an accidental MPI (D5 stays open by design), and the key must not be derived from
> patient values.
>
> Delivery state for e4 lives here, not in `plan.md` (which stays `GATED`) and not in
> `findings.md` (findings only). Spec: `docs/workflow/e4/spec.md` (AGREED 2026-08-10, frozen).
> Plan: `docs/workflow/e4/plan.md` (GATED 2026-08-10, five gate rounds).
> Branch: `fix/noref-registration-contract`.
>
> **Impl gate record — 2026-08-10, impl-gated fresh-context.** Branch
> `fix/noref-registration-contract` @ `e40d4b0`. No findings; no round was appended to
> `findings.md` (`## Impl gate` therefore does not exist for this item). Push-ready —
> push itself stays human-gated.
>
> Re-run at the gate, not accepted from the implementation session's notes:
> `make test-docker` → **`969 passed, 1 xfailed, 5 deselected`** against the `940 / 1 / 5`
> baseline — **+29, xfailed and deselected unmoved**, and the 29 reconcile exactly with the
> per-file counts claimed below (11 + 7 + 6 + 2 + 1 + 1 + 1). `cd frontend && npm test` →
> 7 files / 77 tests green; `npm run typecheck` clean; `npm run lint` shows only the
> pre-existing `DateField.tsx:103` warning; `npm run build` succeeds. Both scoped greps
> ("Intake submitted successfully", the three deleted symbols) return nothing.
>
> Closed both ways: every one of the 27 changed files traces to a plan scope-map slice, and
> every slice appears in the diff. All 28 SPEC ids trace to a change; 25 are named literally
> in the diff, and E4-SPEC-26/27/28 are the registry statements the plan's §9 records as
> having no test. No planted defect is repaired or disturbed: `docs/landmines.md` §3's
> deliberate-gap list is untouched, D5/D5b/D8/D11 and the booking race are not in the diff,
> and the one inherited behaviour deliberately changed with no registry entry (the
> per-consent commit and its swallowed failure) is disclosed in the plan's Landmines section
> and again above. Idiom sweep clean: no new `_post`/`_get` call site — thirteen remain, the
> number every edited document claims — no `str(e)` added on any code path, no
> `Co-Authored-By` trailer. Both `docs/landmines.md` §1 zones in the diff (gateway error
> handling on the registration route, the `ConsentKind` PHI control) carry the owner approval
> recorded at requirements D-1 and in the plan's Landmines section.
>
> **Residual accepted at this gate:** plan verification step 11's browser half — driving the
> wizard in a real browser — was not executed, disclosed under *Live stack check* below. The
> wizard's own DOM behaviour is covered by 13 jsdom tests and the live network path beneath
> it by the three `make up` checks; the seam neither covers is the wizard rendering against a
> real response, and it stays unverified rather than inferred. The plan's other 14
> verification steps, including all 12 break-then-revert negatives, are recorded as run.

## Overview

Patient registration through the portal was **completely non-functional on `main` and the UI
reported success** — TODO-1, `docs/debt-log.md` "Intake contract break", inherited from handoff
commit `3663c4b`. This closes all four layers, and makes the *class* impossible rather than
patching the instance: the two sides of the `POST /intake` payload are now declared once in
`contracts/intake-registration.json` and asserted from both CI suites, so either side drifting
reddens its own job.

It also closes TODO-55 (nothing drove `POST /intake` as an endpoint) and TODO-56 (the eligibility
verdict was discarded by the wizard), and corrects the registries that still described the defect
as unscheduled.

`Refs:` TODO-1, TODO-55, TODO-56 · D4 (open half, registration route only) · RIV-141 (partial)

| Endpoint | Before | After |
|---|---|---|
| `POST /intake` (gateway) | `_post`, hardcoded 30s; every downstream failure relayed as **200** with an `{"error": str(e)}` body | `_post_checked`, `settings.intake_timeout_seconds`; downstream status relayed, timeout → 504, transport → 502, exception **class** only in logs |
| `POST /intake` (intake-service) | patient, coverage and consents committed separately; a consent failure swallowed | one transaction, one commit; any failure rolls back to nothing and answers 503 |

## Behavior

**Registration completes, and the shape is declared once.** The portal now sends
`demographics.name` (not `first_name`/`last_name`), `insurance.payer_name` (not `carrier`),
`consents` as a list of `ConsentKind` values (not a boolean object), and `created_via` explicitly;
`notes` is the one deliberate omission and the contract records it as such, with a test proving an
omitted field is optional in the schema. `frontend/app/intake/payload.ts` is a plain module so the
contract test can call the builder without mounting the four-step wizard.

**Success is never faked.** The confirmation renders only on a numeric `patient_id`. A 2xx that
confirms no record is a failure now — that branch is exactly what the deleted fallback string hid.
A 400/422 says the details are correctable at the desk; anything else says the system could not
complete it. The downstream `detail` is never rendered: it can carry the submitted values that
were rejected.

**Nothing partial survives a failed registration (E4-SPEC-4).** `_create_registration` writes
patient + coverage + consents in one transaction. The match-key hook (ADR 0005) and eligibility
verification both run *after* the commit, so neither can block or fail a registration —
verification is additionally wrapped at the call site, keeping `_verify_eligibility`'s deliberate
propagate-on-unexpected contract (which the breaker's `try/finally` test depends on) while the
registration stops riding on it.

**The consent vocabulary is closed and equal on both sides.** `ConsentKind` gains
`financial_responsibility_ack` and `communications_opt_in` (resolved 2026-07-30, inherited not
reopened), and the form gains a fifth consent — release of information — so the two sets match.
The enum is a documented PHI control, so the widening is re-proved rather than assumed inert and
the members are pinned as five literals.

**The registration bound is configured and pinned.** New `INTAKE_TIMEOUT_SECONDS` (default 30 —
the same number `_post` hardcoded, so the bound does not move). It must stay above intake's own
`ELIGIBILITY_TIMEOUT_SECONDS`, enforced at all four places it can be set: the code default and
`.env.example` (`tests/test_eligibility_budget_alignment.py`), plus a per-service `environment:`
block and a scoped `.env.*.example` template (`tests/test_compose_topology.py`) — the two vectors
the value-level invariant cannot see.

**The verdict reaches a screen.** The confirmation renders W3's `VerdictBadge`, with an explicit
"Insurance eligibility was not checked" line whenever there is no verdict inside the eligibility
path's four-value vocabulary.

## Wiring

- `.env.example` gains `INTAKE_TIMEOUT_SECONDS=30` with the invariant in its comment. No compose
  change and no per-service override — that is now test-enforced, not conventional.
- No CI workflow edit: the `tests` and `frontend` jobs already exist and both already gate
  `docker-build` via `needs` (`.github/workflows/ci.yml:135`), so a contract break attributes to
  whichever job owns the drifting side.
- New top-level `contracts/` directory — language-neutral, no build step, read by pytest via a
  repo-root path and by Vitest via `node:fs` (not an `import`, so nothing outside `frontend/`
  enters the TypeScript project `next build` checks).
- **No schema change and no migration.** `consents.kind` is plain `TEXT` with no `CHECK`
  (`db/schema.sql`), so the enum widening needs neither; the column comments in `models.py` and
  `schema.sql` are corrected to the five.

## Registries corrected (E4-SPEC-26, 27, 28)

- **`docs/todo.md`** — TODO-1, TODO-55 and TODO-56 closed with what closed them *and* what did
  not; new **TODO-61** for the `roi_consent` constraint.
- **`docs/landmines.md` §1** — the registration bullet now names the three guards that must not be
  quietly changed, and states that the other thirteen proxy routes are still the open half of D4.
- **`docs/debt-log.md`** — the "Intake contract break" section marked DELIVERED with its analysis
  kept as the record; the stale "no JavaScript test harness, so the class is unguarded" claim
  retracted (E4-SPEC-27); D4's follow-up line records the registration half done and the estate
  deferred to `e5`; D4 residual 2 closed with its cross-service residual named; residual 3
  explicitly still open and retargeted off a deleted symbol.
- **`docs/phi-logging-policy.md`** — register upkeep only (see *Risk & landmines*).
- **`adr/0010`** — one dated amendment blockquote (see *Risk & landmines*).
- **`tests/README.md`** — the `POST /intake` gap moves out of the deliberate list into the
  entries-that-left note; new tests listed by area.
- **`CLAUDE.md`** — §5's registration paragraph (it asserted a live defect that no longer exists),
  §6's baseline count, and a one-line `contracts/` entry in the §2 map.

## Risk & landmines

**Two `docs/landmines.md` §1 zones are touched, both owner-approved** (requirements D-1, carried
into the plan's Landmines section):

1. **Gateway error handling** — the open half of D4, on the **registration route only**. The other
   thirteen `_post`/`_get` call sites are untouched and deferred to `e5`.
2. **The `ConsentKind` PHI control** — widened by two members and re-proved, not assumed inert.

Not touched: auth, PHI columns, ROI/disclosure logic, migrations, secrets.

**Called out because these are the shapes a reviewer should stop on:**

- **`docs/phi-logging-policy.md` is edited, and it is a live control document.** Register upkeep
  only, forced by three functions the register names being merged into one. No rule, threshold or
  row status changes, and no row moves from OPEN to FIXED. The `_post`/`_get` row is narrowed to
  the thirteen remaining routes and records the registration route as migrated.
- **`adr/0010-eligibility-resilience.md` appears in the diff.** One symbol in one Consequences
  sentence, with a dated `> Amended` blockquote per the repo's ADR convention. No budget value, no
  status, no decision text changes; ADR 0010 stays `Accepted`.
- **New: the intake form now collects `roi_consent`.** It is **not** a 45 CFR 164.508
  authorization, nothing in `roi-service` reads the `consents` table, and D12 stays open —
  recorded as **TODO-61** so the next person to work on ROI finds the constraint before the
  shortcut. This was the owner's choice for satisfying E4-SPEC-9's set equality; the alternative
  was amending a frozen spec.
- **One inherited behaviour deliberately changed with no registry entry to cite:** the per-consent
  commit and the swallowed consent-write failure. It carries no D-number, no landmines bullet and
  no debt-log row — it was described only as an inherited shortcoming in the intake module
  docstring. E4-SPEC-4 requires one transaction, so it goes, and the docstring is corrected rather
  than left asserting the old shape. Flagged because "inherited oddity with no registry entry" is
  exactly the shape that is usually a teaching artifact.

**Deliberate defects preserved.** Nothing here touches D5 (no MPI — every `/intake` still forks a
new chart), D5b, D8, D11, the booking race, or the HL7 gap. The registration defect itself is
inherited breakage, not a seeded teaching artifact: no `D<n>` marker, filed in the debt log without
a D-number, and TODO-1 asked for it to be fixed.

## Accepted residuals

Carried from the plan's gate record, not rediscovered here:

- **E4-SPEC-4 — atomicity is per-request, not cross-service.** A registration that commits and
  then loses its response in transit leaves a patient row the operator never sees confirmed: the
  portal reports a system failure and the row exists. Closing it needs an idempotency key on
  `POST /intake`, which is register-first's territory (D4 follow-up, `e5`+).
- **E4-SPEC-25 — `VerdictBadge` renders the four-value vocabulary only.** An off-vocabulary
  degraded verdict falls into the "not checked" line, understating a *degraded* state as an
  *unchecked* one. Chosen over widening the badge's tone map, which would change W3's frozen
  `/assistant` surface and invent a tone for a status outside the eligibility path's own
  vocabulary. Pinned by a test so it stays a known shape rather than drifting.

No new residual was introduced during implementation.

## Test-first record

Every slice with a behavioural seam ran test-first (red → minimal code → green):

| Slice | Test-first? | Red test written first |
|---|---|---|
| 1. Consent vocabulary | yes | `tests/test_intake_schemas.py` five-literal pin |
| 2. Single-transaction registration | yes | `tests/test_intake_db_error_phi.py` retargeted at `_create_registration` |
| 3. Gateway `_post_checked` + timeout | yes | `tests/test_gateway_intake_proxy.py` (whole file) |
| 4. Shared payload declaration | yes | `tests/test_intake_payload_contract.py` |
| 5. Portal payload / error contract / verdict | yes | `frontend/app/intake/page.test.tsx` E4 cases |
| 6. Endpoint tests | n/a — the slice *is* tests | — |
| 7. Gateway proxy tests | folded into slice 3 | — |
| 8. Budget pinning | yes | `.env.example` source assertion red before the value existed |
| 9. Registries | **no behavioural seam** — documentation only | — |

## Traceability

Every SPEC id in the plan's scope map is named literally in at least one test or configuration
file in this diff, greppable as `E4-SPEC-<n>` — **except E4-SPEC-26, 27 and 28**, which are
statements about the registries themselves (record the defect as delivered; stop asserting the
contract-mismatch class is unguarded; state the post-delivery status of TODO-55, TODO-56 and D4's
follow-up line). Those are satisfied by the documentation edits listed under *Registries
corrected* above, and the plan's §9 records that they have no test.

## Verification

- **`make test-docker`: `969 passed, 1 xfailed, 5 deselected`.** Baseline was `940 / 1 / 5`
  (`CLAUDE.md` §6). **+29 passed, xfailed and deselected unmoved**, so no deliberate gap moved:
  11 gateway registration proxy, 7 intake endpoint, 6 payload contract, 2 compose override guards,
  1 budget invariant, 1 consent-enum pin, 1 no-longer-swallowed consent failure. The `POST /intake`
  endpoint gap that closed (TODO-55) was **not** one of `docs/landmines.md` §3's deliberate list,
  which is unchanged — `docs/todo.md` said so explicitly.
- **`cd frontend && npm test`: 7 files / 77 tests green** (was 5 files / 55). `npm run typecheck`
  clean. `npm run lint` shows only the pre-existing `DateField.tsx:103` warning, not in this diff.
  `npm run build` succeeds.
- **`make eval` not run — nothing under `eval/rag/` or the retrieval path is in the diff.**
- **Every negative check in the plan's Verification section fired.** Each was applied, run, and
  reverted:

  | Negative | Result |
  |---|---|
  | rename `payer_name` → `carrier` in the contract file | pytest side red |
  | rename it in `payload.ts` instead | Vitest side red |
  | drop `roi` from the form's consent catalog | Vitest set assertion red |
  | drop `communications_opt_in` from `ConsentKind` | pytest set assertion + five-literal pin red |
  | restore the per-consent commit | `test_intake_endpoint.py` mid-transaction case red |
  | point `proxy_intake` back at `_post` | 8 of 11 gateway tests red (the 422 arrives as 200) |
  | `INTAKE_TIMEOUT_SECONDS=4` in `.env.example` | budget invariant red from the template source |
  | `INTAKE_TIMEOUT_SECONDS: 4` in the gateway's compose `environment:` | compose guard red, budget test still green — which is the point |
  | `INTAKE_TIMEOUT_SECONDS=4` in `.env.redis.example` | scoped-template guard red |
  | move `_evaluate_match_key` above `_create_registration` | ADR 0005 ordering test red |
  | drop the first-commit-only guard in `_OrderedSession` | ordering test red with a third marker |
  | restore `flush()`'s `obj` parameter in the stub | all 17 `create_intake` tests red with `TypeError` |

- **Scoped greps, both clean.** `grep -rn "Intake submitted successfully" frontend/ services/ tests/`
  returns nothing (the string survives only in `docs/debt-log.md` and the `Superseded`
  `adr/0013`, both records of the defect).
  `grep -rn "_create_patient\|_create_coverage\|_record_consents" services/ tests/ adr/ docs/*.md CLAUDE.md`
  returns nothing — every live document that named a deleted symbol was retargeted without
  restating the dead name.

### Live stack check — partially executed, disclosed

Run against `make up` with `gateway`, `intake-service` and `frontend` rebuilt from this branch:

- **Through the portal's own BFF route** (`POST localhost:3070/api/intake`): a valid submission
  returns 200 with a `patient_id`; the old broken portal shape returns **422** with a generic
  `{"detail": "intake service error"}` — not the 200 it used to return, and carrying none of the
  submitted values.
- **Through the gateway**: same, and the database shows one patient row, one coverage row and all
  **five** consent rows for it; the rejected shape left **zero** rows behind.
- **Outage branch**: with `intake-service` stopped, the call answers **502**
  `{"detail": "intake service unreachable"}` and the gateway log carries
  `transport error: ConnectError` — the class only, no URL and no `str(e)`.
- **Not executed: driving the wizard in a real browser.** The Chrome extension is not connected in
  this environment and Playwright is not installed, and installing a browser runtime was out of
  proportion to the check. The wizard's own DOM behaviour — the five consents, the policy-holder
  checkbox, the four result branches and the four verdict states — is covered by 13 jsdom tests in
  `page.test.tsx` with `apiFetch` mocked; the real network path underneath them is covered by the
  three live checks above. **The one seam neither covers is the wizard rendering against a real
  response**, and a reviewer should treat that as unverified rather than assume it from either
  half.
- The two patients created by these checks were deleted from the dev database afterwards.

## Plan deviations

- **`payload.contract.test.ts` resolves the contract path by walking up from `process.cwd()`,
  not from `import.meta.url`.** The plan specified `node:fs` with a relative URL; Vite rewrites
  `import.meta.url` to a non-file URL under the Vitest transform, so `readFileSync` threw
  `The URL must be of scheme file`. The upward walk is cwd-independent, so it holds whichever
  directory the runner starts in. Plan fact wrong, fix trivial — the constraint the plan actually
  cared about (no `import`, so nothing outside `frontend/` enters the TS project) is unchanged.
- **`page.test.tsx` selects the HIPAA consent by `/notice of privacy practices \(hipaa\)/i`.** The
  new ROI consent's body also cites the Notice of Privacy Practices, so the old selector matched
  two elements. Test-local disambiguation, no production change.
- **`tests/test_intake_db_error_phi.py`'s session double gained a `fail_on` switch.** The three
  writes are now one transaction, so the patients INSERT fails at `flush()` while the coverage and
  consent INSERTs fail at `commit()`; one hardcoded failure point could no longer reach all three.
- **The `docs/landmines.md` §1 registration bullet was rewritten as a guard, not just marked
  delivered.** The plan said "rewritten as delivered"; what landed also names the three things
  that must not be quietly changed (the enum, the migrated route, the single payload declaration),
  because a bullet that only says "fixed" gives a future session nothing to not-break.
- **`CLAUDE.md` §2 gained a one-line `contracts/` map entry** — not in the plan's scope map. §2 is
  the only enumeration of top-level directories, so a new one is invisible without it. The stale
  `⚠️ Registration is BROKEN` line under `frontend/` was deleted with no replacement. Both
  trimmed to minimum length on owner direction during implementation.

## Planned work absent from the diff

None. Every slice in the plan's scope map produced a diff, and every SHALL clause in the scope map
has at least one test naming its SPEC id or a registry edit that satisfies it.

---

Follows `CONTRIBUTING.md`: no `Co-Authored-By` trailer; no schema change, so no migration.
