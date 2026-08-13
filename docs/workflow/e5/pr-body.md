# e5 branch B — registration idempotency

> Status: PUSHED PR #76 2026-08-12
>
> **Review round 5** (2026-08-13): one finding, **B — a defect in the code round
> 3's fix wrote**, the first B on this item. Fixed on the branch in `958d46c`
> (`findings.md` §Review round 5). Round 3 emptied `REGISTRATION_FINGERPRINT_KEY`
> in `.env.example` so a committed placeholder could not satisfy the guard; that
> closed a published-key hole and opened an availability one, because
> `_fingerprint_key` answers 503 on an unset key and the intake healthcheck only
> polls `/healthz`, which never exercises it — so a stack brought up from the
> committed files reported HEALTHY while no patient could be registered.
> The fix copies the shape this estate already uses for the redis password:
> `make up` **generates** `.env.registration` (`openssl rand -hex 32`, gitignored,
> 64 characters over a 32-character floor), and `intake-service` loads it alone,
> after `.env` so the generated value beats any leftover assignment in the shared
> file. That also takes a PHI-derived key off the shared `.env` that compose hands
> to every container — a gain a startup guard would not have bought. The template
> still ships EMPTY, so a checkout that never ran `make` still fails closed. The
> healthcheck is deliberately unchanged: with the key generated it would assert a
> condition that can no longer be false in a make-driven stack, and a `/healthz`
> that computes a fingerprint is a PHI-adjacent probe. **Routing:** a branch
> patch, not stage 3 — the fix adds no counter, TTL, lock, breaker, budget or
> cache, only bootstrap wiring. +8 tests (7 structural in
> `tests/test_compose_topology.py`, 1 outcome test that runs the Makefile recipe
> and feeds what it wrote to the guard); the round-3 template test repoints to
> `.env.registration.example`. Suite **1309 / 1 / 5** (+8; xfail and deselected
> unmoved), `make eval` green, `gitleaks --no-git` over the tracked tree clean.
> Round 4's re-raised eligibility residual did **not** return.
>
> **Review round 4** (2026-08-12): one finding, **no code change** — round 3's
> finding 1 re-raised verbatim ("a replay re-runs live eligibility"), same
> anchor and same remedy, answered again from the record per the fix-session
> step-2 rule and the owner decision taken the day before (`findings.md` §Review
> round 4). Round 3's other finding, the fingerprint-key guard, did **not**
> return: the fix held. No new finding was raised against anything on the
> branch, so the loop is **dry on new findings** and the suite is unchanged at
> **1301 passed / 1 xfailed / 5 deselected**, frontend 110. One docs-only
> change was taken on the owner's decision (`383be97`):
> `tests/test_intake_idempotency.py::test_the_replay_is_indistinguishable_from_the_original`
> asserted eligibility equality against a deterministic payer stub, which reads
> stronger than accepted residual 5 guarantees — the docstring now scopes the
> claim to the registration and names the residual; the name and every
> assertion are unchanged, and the suite is unchanged with it.
> `contracts/intake-registration.json` and the replay-path comments made no such
> claim and were not touched. **Re-tagged for a round 5 on the owner's
> decision** (2026-08-12): the eligibility residual is settled and another
> restatement changes nothing, but the round is cheap and the branch's other
> mechanisms have been read fewer times — the disposition comment names which
> finding is closed and which surfaces are open.
>
> **Round-3 revision** (2026-08-12): codex review round 3 returned two findings
> and the **round-3 rule** stopped the loop, so both dispositions are the
> owner's, taken 2026-08-12 (`findings.md` §Review round 3).
> *Finding 1 — a replay re-runs live eligibility:* **reaffirmed as accepted
> residual 5** and closed from the record, no code change. The reviewer's own
> remedy, persisting the verdict, is `docs/debt-log.md` D4 residual 3 — already
> open, and the reason residual 5 exists; reopening it is new state on the
> registration path and would be a stage-3 revision, not a branch patch.
> *Finding 2 — the committed placeholder key satisfied the guard:* **fixed on
> the branch at full scope** in `2a6c4d5`–`03ee5a0`. `_fingerprint_key` now
> refuses an unset, whitespace-only, sentinel-matching or under-32-character
> key with the same 503, naming the variable and never the value;
> `.env.example` ships the key EMPTY. Both halves are load-bearing — the
> placeholder was 41 characters, so the floor alone would have passed it, and a
> 31-character random secret is no sentinel. Live against the rebuilt image with
> the template as its `env_file`: the shipped value arrives as `''` → 503, the
> old placeholder → 503, a 31-char key → 503, a real 64-char key → accepted;
> the refusal log line carries no key material. +11 tests, all red before the
> guard moved (suite **1301 / 1 / 5**, frontend unchanged at 110).
>
> **Impl-gate record, round 3** (2026-08-12, impl-gated fresh-context,
> `.claude/skills/impl-gate/`): branch `fix/e5-registration-idempotency`,
> HEAD `547493f`. Baseline re-run this gate session: `make test-docker` →
> **1290 passed, 1 xfailed, 5 deselected**; frontend `npm test` → **110
> passed**; `make eval` green. Rounds 1–2 dispositions verified in place. One
> finding: the baseline table's r2 mismatch row read +7 for six cases (rows
> summed 1291 against the stated and measured 1290) — owner decision 2026-08-12
> per the round-3 rule: corrected in the gate session (+7 → +6, this file only;
> no code, plan or spec touched) and the fresh re-gate waived, recorded in
> `findings.md` §Impl gate round 3. Residuals accepted at this gate: unchanged
> from the list below. Pushed on the owner's instruction 2026-08-12.
>
> **Impl gate round 2** (2026-08-12): one finding — plan verification step 12's
> break-then-revert negative was neither evidenced nor recorded as skipped while
> this file marked step 12 ✅. It was **run**, not recorded away: the step-12 row
> below now carries the scratch-database result (inline `UNIQUE` → the loser gets
> 503 instead of replaying; named constraint restored → both callers 201, same
> chart). No code change — the constraint name, its matcher and both DDL files
> were already in agreement, and the negative confirms the runtime consequence
> the §13 DDL-name pin stands in for. One delivered-text correction alongside it:
> `tests/test_intake_idempotency.py`'s module docstring scoped itself
> "E5-SPEC-24 … E5-SPEC-40" while carrying the E5-SPEC-41/42/43 cases (the drift
> round 2 noted, not a finding); it now reads `… E5-SPEC-43` and states the
> content-match qualification.
>
> **Round-2 revision** (2026-08-12): codex round 2 found that a replay was keyed
> on the identifier alone, so an operator who lost a response and *corrected* a
> value was answered `201` for the original chart while the edit was silently
> dropped. That is a spec defect, not a coding one — the fix is new persisted
> state — so it went back through stage 2 and stage 3 (spec amendment 2, D-18:
> E5-SPEC-30 qualified, E5-SPEC-41/42/43 added; plan re-gated fresh-context,
> round 9). This session implements that revision: a keyed content fingerprint
> recorded with the identifier, a `409` for a recorded identifier arriving with
> different content, and a portal that re-mints on the first edit after an
> unconfirmed submit. Suite: **1290 passed, 1 xfailed, 5 deselected** (+14);
> frontend **110 passed** (+4). Details in every section below, marked
> *(round-2 revision)* where they are new.
>
> **Review record** — round 1 (`@codex-review`, 2026-08-11): 1 finding, **1 A / 0 B /
> 0 C**, fixed on the branch. `submission_id` accepted any well-formed UUID; it now
> requires version 4. Round detail and the scoped-down claim are in
> `findings.md` §Review. Suite after the fix: **1276 passed, 1 xfailed, 5 deselected**
> (+7 over the 1269 this branch pushed with).
>
> **Impl-gate record** — 2026-08-11, impl-gated fresh-context
> (`.claude/skills/impl-gate/`). Branch `fix/e5-registration-idempotency`,
> HEAD `60a77a8`. Baseline re-run this gate session: `make test-docker` →
> **1269 passed, 1 xfailed, 5 deselected** (matches the table below; +22 over
> chunk 1's landed 1247/1/5 = 18 idempotency + 2 gateway forwarding pins + 2
> parametrized topology guards; xfailed and deselected unmoved). Frontend
> `npm test` → **106 passed**; `make eval` green. Note on baseline provenance:
> the +22 is compared against chunk 1's landed count recorded on PR #74, since
> `CLAUDE.md` §6 still pins the pre-chunk-1 969 and is deliberately left for
> the owner (see Verification below). Diff closes both ways against the plan's
> chunk-2 scope map; all six deviations and the one beyond-plan test
> (E5-SPEC-34's structural scan) are recorded above and traceable. No landmine
> §1 zone entered without a recorded owner act; D5/D5b/D8/D11/D2 verified
> untouched. Residuals accepted at this gate: the four the round-6 plan stamp
> carries (E5-SPEC-30/31, E5-SPEC-33 — `lock_timeout` now proven live,
> E5-SPEC-34, E5-SPEC-40/TODO-62), unchanged. Push stays human-gated.
> Chunk 2 of e5 (plan D-13): E5-SPEC-24 … E5-SPEC-43. Branch A (the
> gateway/portal error contract, E5-SPEC-1 … E5-SPEC-23) merged 2026-08-11 —
> PR #74 code `762f614`, PR #75 artifacts `49784d0` — and is not in this diff.
> **This file replaced branch A's delivery record** on the owner's call at the
> start of implementation; branch A's record is in git history and on PR #74/#75.
> Spec: `docs/workflow/e5/spec.md` (AGREED 2026-08-11, frozen; amended and
> re-frozen twice — E5-SPEC-8, then D-18).
> Plan: `docs/workflow/e5/plan.md` (GATED 2026-08-11, round 9).
> Branch: `fix/e5-registration-idempotency`.

## What this changes

`POST /intake` commits the registration and then evaluates the match key and
verifies eligibility on the same request thread. A response lost in transit
therefore leaves a **committed chart** while the portal correctly tells the
operator nothing was saved (E4-SPEC-7, and that honesty is e4's fix working).
The operator retries. There was no idempotency key and no uniqueness guard, so
the retry created a **second chart with its own coverage and consent rows** —
the residual e4 made reachable, recorded at `docs/debt-log.md` D4 residual 2.

The caller now names the submission **attempt**:

1. **`submission_id`** — a required, UUID-validated root field on the request
   (`contracts/intake-registration.json`, additive on the request side only).
   The portal mints it once per mount with `crypto.randomUUID`, falling back to
   `getRandomValues` because `randomUUID` is secure-context-only.
2. **`registration_submissions`** — one row per completed registration, UNIQUE
   on `submission_id`, written **inside the registration's own transaction**. A
   record written outside it reopens the window it exists to close.
3. **Replay** — a recorded identifier answers `201` with the recorded
   `patient_id`, through the unchanged response model, and creates no patient,
   coverage, consent or review-queue row. No replay marker: the retry *is* the
   confirmation the operator lost (requirements D-5).
4. **Collision** — the UNIQUE index decides a concurrent race. The loser blocks
   on it, bounded by the new `REGISTRATION_LOCK_WAIT_SECONDS` (Postgres
   `SET LOCAL lock_timeout`, 5s default), then re-reads and replays the winner.
   An expired bound is a `503` into e4's existing system-failure branch — no
   fifth result branch.
5. **`payload_fingerprint`** *(round-2 revision, E5-SPEC-41)* — a keyed
   HMAC-SHA256 over the canonical validated payload, recorded beside the
   identifier **in the same transaction**. Keyed, never a plain hash: the input
   is DOB, SSN and member id, and a plain digest of guessable fields in a
   persisted column is a dictionary-reversible confirmation oracle. Computed
   before the replay lookup and **fail-closed** — with no
   `REGISTRATION_FINGERPRINT_KEY` the service answers `503` and registers
   nothing, rather than degrading to an unkeyed digest.
6. **Mismatch → `409`, re-mint at the portal** *(round-2 revision, E5-SPEC-42,
   E5-SPEC-43)* — a recorded identifier arriving with different content answers
   a constant-detail `409`, creating nothing and modifying nothing; the portal's
   existing non-400/422 arm renders it as a system failure, so no gateway or
   portal branch changed. And the operator never meets it: the form re-mints the
   identifier on the first **edit** after an unconfirmed submit, so a correction
   is a new attempt. Both halves are needed — the `409` alone would have trapped
   the desk in a loop resubmitting the same rejected identifier, and the re-mint
   alone would leave every non-portal caller able to overwrite meaning.

**Deliberately not a master patient index.** Nothing on this path reads
demographics, so the same human registered twice with two identifiers still
forks two charts and is still only queued for review. D5 stays open; E5-SPEC-36
and E5-SPEC-37 exist to prove it did not close, and both are tested.

## Risk & landmines

`docs/landmines.md` §1 zones **entered**:

- ⚠️ **Migrations and the schema.** One new table, hand-synced across
  `db/schema.sql` and `db/migrations/010_registration_submissions.sql`.
  **Owner approval recorded 2026-08-11 at the start of this implementation
  session**, on the entry-checklist question naming the exact DDL: new table
  only, UNIQUE `submission_id`, FK `patient_id`, `created_at`; no existing
  table, column or PHI column altered. The plan's Landmines section stated the
  requirement but carried no named owner act for this zone (unlike the gateway
  zone), so it was secured before any code was written rather than inferred
  from requirements agreement. *(Round-2 revision: the table gains
  `payload_fingerprint TEXT NOT NULL`. Migration 010 is amended **in place**
  rather than followed by an 011 — it exists only on this unmerged branch, so
  there is no deployed copy to migrate from. Owner approval for the new
  persisted state is recorded with spec amendment 2, D-18, E5-SPEC-41's
  ⚠ human-gate note.)*
- ⚠️ **PHI — a new logged value and a new stored column.** `log_metadata` gains
  `submission_id`, the only value in that projection copied out rather than
  flattened to a presence flag. It is safe for exactly the reason E5-SPEC-38
  requires: random, derived from nothing submitted. The same shape as the LLM
  path's provider `request_id`. Register row updated
  (`docs/phi-logging-policy.md`, the intake body-at-INFO row) with the two
  negative tests that scan the stored row, the formatted log records and the
  response for every submitted value. *(Round-2 revision: a second stored value,
  and this one **is** PHI-derived — `payload_fingerprint`. It stays keyed for
  that reason, the service refuses to run unkeyed, it is never logged, and the
  mismatch `409` carries a constant detail. Register row extended with the three
  negative tests: the keyed property, the stored digest scanned for every
  submitted value, and the refusal's own log records scanned for what changed.)*
- ⚠️ **A new secret.** `REGISTRATION_FINGERPRINT_KEY`, empty by default in
  `config.py` (fail-closed) and **shipped EMPTY in `.env.example`**. *(Round-3
  revision, owner decision 2026-08-12 on codex finding 2 — approval for this
  edit to a secret template is that decision, taken at full scope. It first
  shipped a marked dev placeholder, on the `DB_PASSWORD` / `SESSION_SECRET`
  precedent. That was wrong for this key and the reason is in the same file
  fourteen lines below: `AWS_BEARER_TOKEN_BEDROCK` ships empty precisely because
  CI seeds `.env` with `cp .env.example .env`, so a non-empty placeholder
  satisfies a bare presence check. Presence **was** the whole guard here, so a
  template-seeded deploy would have fingerprinted DOB, SSN and member id under a
  committed key. `_fingerprint_key` now also rejects placeholder sentinels and
  keys under 32 characters, and it names the variable, never the value.)*
  *(Round-5 revision, owner approval recorded 2026-08-13 before code — the zone
  is entered again and more widely: `.env.example`, a new
  `.env.registration.example`, `.gitignore`, the `Makefile`'s generation target
  and `docker-compose.yml`'s `env_file` list. Emptying the shared template was
  right and incomplete: `/healthz` does not exercise the key, so a
  template-seeded stack reported healthy and registered nobody. The key now
  lives in a scoped `.env.registration` that `make up` **generates**
  (`openssl rand -hex 32`), loaded by intake-service alone and listed after
  `.env`. Two gains, not one: the fail-closed guard stops costing availability,
  and a PHI-derived key stops riding the shared `.env` that compose hands to
  every container — the `.env.redis` argument, which applies harder here because
  the fingerprint's inputs are guessable. No `.env`, `.env.redis` or
  `.env.ai-proxy` content was read or modified.)* No real key is in the diff and
  the shipped template is empty. It is deliberately **not** added to
  `docs/debt-log.md`'s remediation runbook step 1: that checklist rotates the
  credentials that reached git history and enumerates them from the committed
  blob, and this key has never been committed. `docs/runbook.md` had no `.env`
  rotation procedure at all when impl gate round 1 finding 1 caught a pointer
  into it resolving to nothing; the round-5 change gives it one — an operator
  entry for "every registration answers 503 while the container is green",
  with the regeneration command and the rotation cost. Never give this a
  non-empty default in code: a default key is a published key.
- ⚠️ **ADR 0010 budget pinning.** `REGISTRATION_LOCK_WAIT_SECONDS` widens
  intake's worst case on the registration path from `ELIGIBILITY_TIMEOUT_SECONDS`
  (8s) to the **sum** (13s).
  `tests/test_eligibility_budget_alignment.py::test_the_gateway_registration_bound_never_preempts_intake`
  now asserts against that sum from both sources of truth — otherwise it would
  keep passing while no longer describing what it guards. No existing value is
  widened or loosened; the gateway's 30s clears 13s + 1s margin.
  `tests/test_compose_topology.py`'s two guards are parametrized over both keys.
- ⚠️ **Auth / sessions — not edited.** No `Depends`, no capability, no
  `config/roles.yaml` or `authz.py` change. `proxy_intake` is unchanged code:
  E5-SPEC-28 lands as tests over the existing route, not as an edit.

**Deliberate defects preserved, not fixed:** D5 / no MPI (proved still open by
test and live); D11 and the `?q=%25` corpus dump; D5b and RIV-175; D8 — the new
UNIQUE index is on the new table only, no existing table gains one; D2; the HL7
AL1/RXA xfail. Register-first / async re-verification (D4's other follow-up) is
untouched: this makes the retry safe, register-first would shrink the window.

## Accepted residuals

Copied from the plan's Landmines section, with their live outcomes:

1. **A bounded-wait expiry answers imprecisely** (E5-SPEC-33, spec D-11). The
   loser is told "not saved" while the winner may have saved it. Accepted at
   spec stage: the operator's next retry carries the same identifier and replays
   into the real confirmation. Unchanged.
2. **`lock_timeout` had to be proven, not assumed** — **now proven**, and the
   `statement_timeout` fallback was **not** taken. See verification step 12: at
   `REGISTRATION_LOCK_WAIT_SECONDS=1` against real Postgres, a POST blocked on a
   held conflicting transaction returned **503 in 1.06s**, having registered
   nothing. This residual is closed by measurement.
3. **A portal-bug rejection renders in the correctable-at-the-desk branch**
   (E5-SPEC-40, D-10). A missing or malformed `submission_id` is a 422, and 422
   is the class the portal renders as "correct them at the desk" — but the
   operator typed nothing that caused it. Accepted rather than adding a fifth
   result branch to a contract e4 had just frozen. **Filed as TODO-62** with the
   condition that reopens it: a second caller.
4. **Submission identifiers grow without bound** (requirements D-7). No expiry,
   no pruning — a retention horizon is a date past which a late retry silently
   creates the duplicate this closes. Recorded in the schema comment, the
   migration header and here; deliberately **not** deferred to a future item.
5. **The replay costs a second eligibility hop** (plan D-14). The original
   verdict is not persisted (D4 residual 3), so it cannot be read back; the
   replay re-verifies through the same bounded, breaker-guarded hop, which is
   what keeps it indistinguishable from the original.
6. **The verdict still reaches no column.** D4 residual 3 untouched — it is why
   residual 5 exists.
7. **The service cannot prove the identifier was drawn at random** (added by review
   round 1). It now rejects anything that is not a version 4 UUID, which closes the
   accidental non-random cases — the nil UUID an uninitialized field serializes to,
   and the name-derived v5 a "make the key deterministic" change produces. It does
   **not** close a caller that sends a *constant* v4: those four version bits are
   self-report, not evidence, and a hash of patient values can carry them just as
   well. Such a caller replays the first patient's chart for every later patient —
   real harm, and unreachable without a second caller inside the gateway's session
   boundary, which is why the portal's mint (`frontend/app/intake/payload.ts`) stays
   the guarantee. Recorded here, in the validator docstring and in the PHI register
   rather than papered over by the version check reading like a proof.
8. **Rotating `REGISTRATION_FINGERPRINT_KEY` invalidates every recorded
   fingerprint** *(round-2 revision, plan D-19)*. A lost-confirmation retry that
   straddles a rotation answers `409` instead of replaying. The operator
   re-enters on a fresh mount, the second chart is queued as a candidate
   duplicate (E5-SPEC-37), and nothing is silent. Accepted: rotation is rare,
   the straddle window is minutes, and key versioning is machinery this estate
   does not have. Recorded in the `.env.example` comment and `config.py`.
9. **The fingerprint is PHI-derived and must stay keyed** *(round-2 revision,
   E5-SPEC-41)*. The mitigation is the HMAC plus the fail-closed guard, both
   test-pinned; the residual is that the column exists at all, and a future
   refactor to a plain hash would turn it into a reversible oracle. The keyed
   property is asserted by test (same payload, two keys, two digests) so that
   refactor reddens. *(Round-3 revision: "keyed" now means keyed with a real
   secret. The guard was presence-only and the template shipped a usable value,
   so the accepted residual was narrower than the delivered state — that gap was
   codex finding 2, fixed rather than accepted. What remains accepted is
   unchanged: the column exists, and its safety rests on a secret the deployment
   holds.)*
10. **A concurrent collision loser with different content gets `409`, not a
    queue entry** *(round-2 revision)*. It is refused rather than silently
    confirmed, which is the point — but unlike the portal path there is no
    re-mint behind it, so a non-portal caller racing itself with two payloads
    under one identifier loses the second one with only a `409` to say so.

## Test-first, and what wasn't

Ran **test-first** (`tdd` loop, one clause → one failing test → minimal code):

- The budget invariant (§12) — the sum assertion was written first and failed on
  the missing `.env.example` key before the knob existed.
- All of §11's behaviour (§13): `tests/test_intake_idempotency.py` was written
  whole and run **15 failed / 2 passed** before `schemas.py` or `app.py` moved.
  (Its 18th case, the E5-SPEC-34 retention scan, was added afterwards — see the
  traceability note under Deviations.)
- §10's gateway forwarding pins, and the portal cases in `page.test.tsx`.

**Not test-first** (no behavioural seam of their own — the plan's Verification
section covers them):

- §7 schema + migration DDL and the `RegistrationSubmission` model.
- §8's contract declaration edit — its assertions are inherited from both
  existing contract suites, which read the declaration.
- Registry upkeep (debt-log, todo, phi-logging-policy, the module docstring).
- Fixture updates across six existing test files (mechanical: the new required
  field).

**Negative checks run on the new tests themselves** (break → red → revert;
`services/intake-service/app.py` confirmed byte-identical afterwards):

| Break | Result |
|---|---|
| Drop the `* 1000` in `_bound_the_collision_wait` | 2 red — the value pin and the interpolation pin. This is exactly the defect gate round 5 found in the plan text |
| Remove the `_is_submission_collision` branch | `test_a_collision_replays_the_winner_instead_of_writing_twice` red |
| *(r2)* Make the fingerprint comparison always match | **5 red** — the three mismatch cases, the lost-response-then-edit case, and the collision-loser case |
| *(r2)* Swap the HMAC for a plain `hashlib.sha256` of the same payload | `test_the_fingerprint_is_keyed_and_reveals_no_submitted_value` red; every other test still green, which is why that one exists |
| *(r2)* Give the missing key a fallback value instead of failing closed | both `test_an_unkeyed_service_refuses_to_register_at_all` cases red |
| *(r2)* Spell the constraint inline (`submission_id TEXT NOT NULL UNIQUE`) in `db/schema.sql` | the DDL-name pin red for that file — the failure that would otherwise appear only against real Postgres, as a routine collision answering 503 |
| *(r3)* Put a usable 64-hex key back in `.env.example` | `test_the_key_the_template_ships_fails_closed` red. The first attempt at this break — restoring the original `dev-…-change-me` placeholder — stayed **green**, correctly: that value is on the sentinel list, so the template still fails closed. The pin's subject is "the shipped value cannot key a deploy", not "the shipped value is empty", and only a usable key breaks it |
| *(r5)* Empty the generated `.env.registration` and recreate `intake-service` | Live, not a test break: every registration `503` **while the container still reported healthy** — the round-5 finding reproduced under the new wiring. Key restored → `200`, new chart |
| *(r5)* Swap the `Makefile`'s `openssl rand` recipe for `cp .env.registration.example` | `test_the_fingerprint_key_is_generated_not_copied` and `test_the_generated_key_registers` red — the second is the one that matters, since it proves the copied value cannot key a stack, not merely that the recipe's text changed |

`services/intake-service/app.py` and `db/schema.sql` confirmed restored from
their pre-break copies after each.

*(Round-5 revision)* Ran **test-first**: the seven topology pins, the
generated-key outcome test and the repointed template test were run against the
pre-fix tree (`958d46c^` with only the two test files taken from the fix) and
came back **9 failed / 2 passed** — every one of the nine red for the reason it
was written, none of them vacuous. All nine green after the wiring landed.
Registry upkeep in the same commit (`docs/phi-logging-policy.md`,
`docs/runbook.md`, `CLAUDE.md` §3's generated-file list) is **not** test-first:
no behavioural seam, and `CLAUDE.md` §3 is corrected here because this change is
what made its claim wrong.

*(Round-3 revision)* Ran **test-first**: all 11 key-guard cases were written and
run **10 failed / 1 passed** before `_fingerprint_key` existed — the one pass
being the positive control, which is what it is for. **Not test-first**: the
`.env.example` and `config.py` comment edits and the PHI register row, none of
which has a behavioural seam; the three fixture keys lengthened to clear the
floor are mechanical.

*(Round-2 revision)* Ran **test-first**: the four portal re-mint cases in
`page.test.tsx` (3 red before `page.tsx` moved, the fourth green by construction
and kept as the pinned negative — an unedited retry must still reuse the
identifier). **Not test-first**: the fingerprint slice's service code and its
tests were written in one pass and then proven by the four break-then-revert
negatives above, which is weaker evidence than red-first and is recorded as
such. The DDL, the model column, the config key and the `.env.example` entry
have no behavioural seam of their own.

## Deviations from the plan

1. **`tests/test_compose_topology.py` needed a `pytest` import.** The plan
   parametrizes two guards over both bound keys; the file imported `re`, `yaml`
   and `pathlib` but never `pytest`. One added import, no behaviour change.
2. **Three test doubles needed `get_bind()`** (`_StubSession` in
   `test_intake_match_key.py`, `_FailingSession` in `test_intake_db_error_phi.py`)
   and one needed `scalar_one_or_none()` (`_StubResult`). `_create_registration`
   now asks the session for its dialect, and `create_intake` now reads the
   submission record first. Both doubles report a non-Postgres dialect, so the
   bounded wait is skipped there — deliberate, and both halves of that dialect
   guard are pinned in `tests/test_intake_idempotency.py`.
3. **The unique constraint is named** (`uq_registration_submission_id`) rather
   than left implicit — landed ahead of the plan, which has since caught up. The
   collision path has to tell *our* violation from any other integrity error
   without stringifying an exception that would embed the bound patients row, so
   it keys on the constraint name (plus the column shape SQLite reports). §7's
   DDL wrote `TEXT NOT NULL UNIQUE` when this entry was written; **gate round 7
   corrected it** to the delivered named-constraint text and added the
   structural pin (`findings.md` §Gate round 7, finding 2), so the GATED plan
   and the code now agree. Kept as the record of why the name is load-bearing,
   not as an open divergence (impl gate round 1, finding 2).
4. **`docs/phi-logging-policy.md` was edited**, which the plan's chunk-2 file
   list did not name (it named only debt-log and todo). The projection gained a
   copied-out value; leaving the register silent about that is the failure mode
   §5 of the plan exists to prevent.
5. **`.env` (gitignored, machine-local) gained the new key.** Not in the diff.
6. **E5-SPEC-34 gained a test the plan did not call for.** The traceability pass
   (implementation step 4) found it was the one chunk-2 clause with no test
   naming it — the plan carries "kept forever" as schema prose only. "We decided
   not to build a pruner" is exactly the decision a later convenience commit
   undoes silently, and the failure shows up weeks later as a duplicate chart, so
   it is now a structural scan over the tracked tree for any delete/truncate of
   `registration_submissions`.
7. *(r2)* **Two more test doubles needed a method.** `_StubResult` in
   `test_intake_match_key.py` gained `one_or_none()` — the replay lookup now
   reads two columns (patient id and fingerprint) rather than one scalar — and
   `test_intake_idempotency.py`'s `_boom` double gained the third
   `_create_registration` parameter. The plan named only
   `test_intake_db_error_phi.py`'s four sites for that argument.
8. *(r2)* **The mismatch test scans the refusal's own log records, not every
   record.** The plan's §13 says the log lines around the mismatch carry no
   submitted value; the request-metadata line legitimately carries the consent
   kinds (a closed, pinned vocabulary — the D1 projection), so the consents case
   would fail a whole-log scan for a value that is there by design. The scan is
   scoped to WARNING-and-above, with the reason written at the assertion.
9. *(r2)* **`docs/phi-logging-policy.md` and `docs/debt-log.md` were edited
   again** — the register row gains the fingerprint's account, and D4 residual 2
   gains the content-match qualification and the `E5-SPEC-24..43` range. Same
   reasoning as deviation 4: a register silent about a new PHI-derived stored
   value is the failure mode it exists to prevent.
10. *(r2)* **`.env` (gitignored, machine-local) gained
    `REGISTRATION_FINGERPRINT_KEY`, and the local dev volume's
    `registration_submissions` table was dropped and recreated from the amended
    migration** so live verification ran against the shipped DDL. Owner approved
    both before they were done (the `.env` zone and the table recreate). Neither
    is in the diff; the 12 submission rows from earlier live rounds are gone from
    the dev volume, which is dev state, not repo state.
11. *(r5)* **The fingerprint key no longer comes from where the plan said it
    does.** Plan §12 sites `REGISTRATION_FINGERPRINT_KEY` in `.env.example` and
    the shared `.env`; it now lives in a scoped, generated `.env.registration`,
    with `.env.example` carrying only a pointer. **Plan fact superseded by a
    review finding, not a plan design error** — §12's own fail-closed
    requirement is unchanged and still enforced by the same guard; what moved is
    where the value comes from and who receives it. Recorded here rather than
    re-gated because the fix adds no state (fix-session step 4) and no spec
    statement names the file. `docker-compose.yml`, the `Makefile`,
    `.gitignore` and `.github/workflows/ci.yml` are in the chunk-2 diff for the
    first time as a result; the plan's Files-touched list did not name them.
12. *(r5)* **`docs/runbook.md` and `CLAUDE.md` were edited**, neither in any
    plan file list. The runbook gains the operator entry for "every registration
    answers 503 while the container reports green" — the symptom this round
    exists to remove, kept because a hand-rolled `docker compose up` can still
    reach it — and `CLAUDE.md` §3's list of what `make up` generates was made
    wrong by this change, so it is corrected in the commit that broke it.
13. *(r5)* **`.env.registration` (gitignored, machine-local) was generated on the
    dev machine** by `make config`, and the local `.env`'s leftover
    `REGISTRATION_FINGERPRINT_KEY` was deliberately **left in place** rather than
    cleaned — it is what proved the `env_file` ordering live (the container took
    the generated value, not the stale shared one). Neither file is in the diff.

## Planned work absent from the diff

- **Nothing from the plan's chunk-2 scope is missing.** §7–§13 all landed,
  including the round-2 revision's additions to §7, §9, §11, §12 and §13 and the
  gate-round-7 items that postdated the first push (the DDL constraint-name pin
  and the fail-closed key's fixture fallout).
- **Chunk 1 (§1–§6) is deliberately absent** — merged separately per D-13.
- **No `docker-compose.yml` edit** (plan §12): intake-service loads the shared
  `.env`, so the new knob reaches it without a compose change, exactly as the
  plan predicted. The two parametrized topology guards are what keep it that way.
- **`TODO-62` was free at landing** (max allocated was TODO-61) — the collision
  rule's re-check passed, no renumber.

## Verification

Full suite: **`make test-docker` → 1309 passed, 1 xfailed, 5 deselected**
(2026-08-13, after the round-5 fix; 1301 after the round-3 fix, 1290 after the
round-2 revision, 1269 at first push).

Against branch A's landed count of **1247 / 1 / 5** (2026-08-11) — the
`CLAUDE.md` §6 baseline still reads the pre-chunk-1 **969 / 1 / 5** and is
deliberately left for the owner, since chunk 1's own delivery record set the
newer number:

| | Count |
|---|---|
| Branch A landed | 1247 |
| `tests/test_intake_idempotency.py` (new) | +18 |
| `tests/test_gateway_intake_proxy.py` — forwarding pins | +2 |
| `tests/test_compose_topology.py` — two guards parametrized over two keys | +2 |
| **At push** | **1269** |
| `tests/test_intake_schemas.py` — v4 rejection cases + canonicalization (review r1) | +4 |
| `tests/test_intake_idempotency.py` — three non-v4 endpoint cases (review r1) | +3 |
| **At review round 2** | **1276** |
| `tests/test_intake_idempotency.py` — mismatch ×3, lost-response-then-edit, reordered-consents replay, collision-loser mismatch (r2) | +6 |
| `tests/test_intake_idempotency.py` — fail-closed key (fresh + recorded), keyed property, stored-digest PHI scan (r2) | +4 |
| `tests/test_intake_idempotency.py` — DDL constraint-name pin and fingerprint-column pin, each over both DDL files (r2, plan §13) | +4 |
| **At review round 3** | **1290** |
| `tests/test_intake_idempotency.py` — placeholder/short-key refusal, 8 parametrized cases (r3) | +8 |
| `tests/test_intake_idempotency.py` — the template-reading pin, the no-key-in-the-log negative, the real-key positive control (r3) | +3 |
| **At review round 5** | **1301** |
| `tests/test_compose_topology.py` — the key scoped to intake, load order, template empty, generated-not-copied, every compose target's prerequisite, gitignored (r5) | +7 |
| `tests/test_intake_idempotency.py` — the generated key registers, running the Makefile recipe for real (r5) | +1 |
| **Total** | **1309** |

**xfailed and deselected did not move.** No deliberate coverage gap moved —
`docs/landmines.md` §3's list is unchanged by chunk 2.

Frontend gate: `npm test` **110 passed** (6 at first push, +4 for the re-mint
cases), `npm run build`, `typecheck`, `lint` all clean (lint's one warning is
the pre-existing `DateField` `aria-required` note). `make eval` green (the drift
gate hashes seed + corpus; neither the schema change nor the migration touches
them).

Plan verification section, chunk-2 steps:

| # | Step | Result |
|---|------|--------|
| 11 | Idempotency, the operator's outcome | ✅ Live: same body twice → `201` / same `patient_id` (1856), no replay marker. `patients` 1, `insurance_coverages` 1, `consents` 2, `registration_submissions` 1. Repeated through the **gateway** with a real session: `patient_id` 1864 both times |
| 12 | The concurrent collision | ✅ Two simultaneous POSTs, one identifier → both `201` with `patient_id` 1857, exactly one chart. **Then the bound:** `REGISTRATION_LOCK_WAIT_SECONDS=1`, conflicting transaction held open → **503 in 1.06s**, zero patients written, log line `failed to create registration (OperationalError)`. `lock_timeout` proven against real Postgres; no `statement_timeout` fallback taken. **Then the negative** *(run 2026-08-12, impl gate round 2 finding 1)*: in a scratch database (`riverbend_scratch`, `db/schema.sql` loaded, `registration_submissions` recreated with the inline `submission_id TEXT NOT NULL UNIQUE` — Postgres names it `registration_submissions_submission_id_key`) with an intake-service instance pointed at it, the two-caller case answered **`503 registration store unavailable` to the loser and `201` to the winner**, log line `failed to create registration (IntegrityError)` — the collision fell through `_is_submission_collision` into the generic store-unavailable branch instead of replaying, exactly the runtime failure the §13 DDL-name pin exists to catch first. Reverted in place (`DROP CONSTRAINT` → `ADD CONSTRAINT uq_registration_submission_id UNIQUE (submission_id)`) and re-run on the same harness: **both callers `201`, same `patient_id`, one chart, one submission row** — so the constraint *name* is what the negative isolates, not the harness. Scratch database dropped, the dev database never pointed at (0 rows from the run in `riverbend`, its named constraint intact) |
| 13 | A fresh registration is never a replay | ✅ Same person, two identifiers → two charts, and `duplicate_review_queue` row 13 `(1862, 1863) intake pending`. D5 still open. *(First attempt used SSN `904567890`, which `is_valid_ssn` rejects — no pair, correctly. Re-run with a valid SSN.)* |
| 13b | A mismatched replay is refused, an edited form re-mints *(round-2 revision)* | ✅ Live through the gateway with a real session. First submit → `patient_id` 1870. Same `submission_id` with an edited DOB **and** member id (`1985-03-21` / `EXMP000999`) → **409 `registration submission conflict`**, and `SELECT dob, member_id` still returns `1985-03-12 / EXMP000201` — the exact query that proved the defect proves the fix. Byte-identical re-post → **201 replay**, same `patient_id`, one `registration_submissions` row (64-hex fingerprint). Refusal log line: `a recorded submission was replayed with different content, refusing (patient_id=1870)` — no submitted value, no fingerprint. **Portal end** (headless Chromium against the rebuilt stack, POST bodies captured off the network): fill `/intake`, stop intake-service, submit → e4's system-failure branch; restart, **edit one consent**, resubmit → `201`, chart 1871, and the two posted bodies carried **different** identifiers. **Fail-closed**: with `REGISTRATION_FINGERPRINT_KEY` emptied and intake restarted, a fresh identifier **and** an already-recorded one both answered **503**, `patients` unchanged and no new submission row; key restored and re-verified. **The queued pair**, the other half of the clause: the same person re-registered under a fresh identifier → chart 1872 and `duplicate_review_queue` row 14 `(1870, 1872) intake pending`. *(The browser run's second chart, 1871, is correctly **not** queued — the portal form used a different name and DOB, so the SSN alone is not a corroborated match key. That is W2's rule working, not a miss.)* |
| 14 | Rejection | ✅ Missing and malformed identifiers → **422**, nothing written. Portal render is e4's unchanged correctable-at-the-desk branch, covered by `page.test.tsx`; not re-driven in a browser (the branch is not touched by this diff) |
| 15 | PHI | ✅ Negative tests green; live `intake-service` logs scanned for every name/SSN used in the run above — **zero matches**, and the `POST /intake meta=` lines carry the identifier plus presence flags only |
| 16 | Baseline and gaps | ✅ Table above; re-run 2026-08-12 after the round-2 revision |
| 17 | `make eval` | ✅ Green |

**Beyond the plan — the operator's loop driven in a real browser** (headless
Chromium against the rebuilt stack, since the identifier is minted in the
shipped bundle and no unit test exercises that):

- Two registrations through `/intake` from separate mounts → two distinct
  UUIDv4 identifiers on the posted bodies, neither containing any typed value
  (E5-SPEC-35, E5-SPEC-38).
- **The lost-confirmation loop end to end** (E5-SPEC-26): with intake-service
  stopped, submit → e4's system-failure branch renders; restart, retry from the
  same mount → both POSTs carried the **same** identifier and exactly **one**
  chart exists.

*(Steps 1–10 are branch A's and were verified on PR #74.)*
