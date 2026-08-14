# e5b — registration idempotency, restarted

Status: plan GATED 2026-08-13 · delivery PUSHED PR #79 2026-08-14 (spec FROZEN 2026-08-13)
Item: successor of e5 chunk 2 (PR #76, closed unmerged 2026-08-13) — make `POST /intake`
safe to retry, restarted from requirements under the one-file pipeline
Baseline at branch: 1247 passed, 1 xfailed, 5 deselected (`.venv` py3.12, `-m "not integration"`, 2026-08-13 at branch cut; `CLAUDE.md` §6's 969 confirmed stale per the e5 close record)

> Restart of record, 2026-08-13: e5 chunk 2's design was closed unmerged (PR #76 — eight
> review rounds, one undispositioned ninth, a growing accepted-residual set; disposition
> in `docs/workflow/e5/pr-body.md` §Status, landed `b6c160b`). This item re-derives the
> work from requirements. Its stage-1 input is the close-out harvest
> (`~/Documents/Work/process-plans/e5b-restart/harvest.md`, session-local): the full
> round ledger, the residual set, e5's owner decisions, and the verification evidence.
> Prior owner decisions are re-confirmed here, never silently inherited.

## Decisions

| ID | Stage | Decision | Why (one sentence) |
|---|---|---|---|
| e5b-D-1 | req | Close PR #76 unmerged and restart from requirements under the current pipeline; the branch is reference until this item's spec freezes, then deleted (owner 2026-08-13) | eight review rounds kept re-raising surfaces the frozen spec had never decided — the loop was doing spec work at review prices, and the foundations predate the gated one-file pipeline |
| e5b-D-2 | req | e5's E5-REQ-10..13 substance re-homes here as e5b-REQ-1..4 (owner 2026-08-13, via the restart decision) | the *need* was never in dispute — one chart per retried submission, no accidental MPI, no PHI in the mechanism; only the design and its process restart |
| e5b-D-3 | req | Remount/draft lifecycle is out of e5b; reserved as named successor item e7 (owner 2026-08-13) | the complete fix writes PHI to browser storage on a shared front-desk workstation — a `docs/landmines.md` §1 decision of its own — and the identifier-only middle ground was measured strictly worse than the gap, so the question gets its own gated item rather than blocking or bloating this one |
| e5b-D-4 | req | e5's requirements-stage decisions D-5 (replay indistinguishable from the original success), D-6 (collision loser waits for the winner's result), D-7 (identifiers kept forever) are re-confirmed wholesale (owner 2026-08-13) | none was disputed across nine review rounds; e5 D-5 now reads together with e5b-REQ-2 — an *identical* replay is indistinguishable, a *corrected* retry is never confirmed as the original |
| e5b-D-5 | req | A served replay re-verifies eligibility live; the verdict from the original submission is never replayed (owner 2026-08-13) | this churned twice in PR #76 review (e5 D-14's shape) — pre-deciding at requirements keeps it from recurring as review-time spec work, and it is what lets eligibility-verdict persistence stay out of scope |
| e5b-D-6 | spec | Re-confirm e5 D-10: the identifier is a required field of the request contract; a missing or malformed one is rejected in e4's correctable-at-the-desk branch (owner 2026-08-13) | the portal is today's only caller and always sends it; the TODO-62 residual (a non-correctable rejection in the correctable branch) re-derives as a named residual, accepted over a new portal branch or an optional field |
| e5b-D-7 | spec | Re-confirm e5 D-11: bounded-wait expiry answers in the existing system-failure branch, nothing written (owner 2026-08-13) | undisputed across nine review rounds; the next retry replays the committed result, so the imprecision self-heals |
| e5b-D-8 | spec | The content binding is keyed by a server-side secret and fails closed when the secret is missing or unreal; algorithm and canonical form stay plan detail (owner 2026-08-13) | an unkeyed hash of guessable fields is a dictionary-reversible offline confirmation oracle (e5 residual 9, r3 f2); pinning both properties at spec is what keeps PR #76's r3/r5 churn from recurring |
| e5b-D-9 | spec | The boundary-vs-mint split is a named limit: the portal's mint owns the randomness guarantee; the service's format check narrows accidental derivation only and cannot prove randomness (owner 2026-08-13) | e5 D-21's measured limit; naming where each guarantee lives is the decision e5b-REQ-4 forces into the open |
| e5b-D-10 | plan | Identifier = client-minted UUIDv4, required root field `submission_id`, stored `TEXT`; minted `crypto.randomUUID()`, `crypto.getRandomValues` fallback (portal not guaranteed a secure context); the service's SPEC-19 format check = version-4 bits; the id joins `log_metadata`'s allowlist (owner 2026-08-13, re-derives e5 D-17/D-21) | undisputed across PR #76's nine rounds; the id is by construction non-PHI (SPEC-18), so logging it is what makes a replay diagnosable without any payload value |
| e5b-D-11 | plan | Content binding = HMAC-SHA256 over the canonical validated payload — pydantic-validated request minus `submission_id`, `json.dumps` with `sort_keys=True`, compact separators, `ensure_ascii=True`, `consents` sorted — keyed by `REGISTRATION_FINGERPRINT_KEY`; one shared key-real predicate (unset/whitespace/known-sentinel/under-32-chars all unreal) serves the request path and the health probe (owner 2026-08-13, re-derives e5 D-19 + r3 f2 + r7 f1b) | satisfies e5b-D-8's two pinned properties; fingerprinting the validated model, not the raw body, makes reordered-consents and whitespace-equivalent retries the same attempt; two copies of the predicate is how a probe goes green on a value the request path refuses |
| e5b-D-12 | plan | Bounded wait = Postgres `lock_timeout` set on the registration transaction from `REGISTRATION_LOCK_WAIT_SECONDS` (seconds, default 5); unique violation ⇒ winner committed, loser re-reads and replays (or 409s on mismatch); lock timeout ⇒ the existing 503 branch; no polling (owner 2026-08-13, re-derives e5 D-15) | the UNIQUE constraint is the only arbiter (e5 D-6 via e5b-D-4); units trap named at plan: the knob is seconds, `lock_timeout` is ms — a test pins the issued value (`'5000ms'`) or a dropped conversion ships a 1000×-shorter bound |
| e5b-D-13 | plan | Key provisioning per the `.env.redis` precedent: `make up` generates gitignored, intake-scoped `.env.registration` (`openssl rand -hex 32`), loaded after `.env`; no template ships; `.gitignore` gains the entry; the stray untracked `.env.registration` in the working tree (leftover of closed e5 testing) is deleted before branch cut and regenerated by `make up` (owner 2026-08-13, re-derives e5 r5) | the r5 lesson: fail-closed guards cost a healthy-but-503 stack unless the documented boot path satisfies them; scoping the file keeps the key out of every other service's environment |
| e5b-D-14 | plan | Health = extend intake's `/healthz` with a schema-presence check over `Base.metadata` (class, not instance) plus the D-11 key-real predicate; refusal detail names the missing table set or the variable name, never a value; compose `depends_on` stays `service_started` (owner 2026-08-13, re-derives e5 r7 overrule + f1b) | an accurate red beats a stable lie; `service_healthy` would turn one stale table into an estate-wide boot failure |
| e5b-D-15 | plan | Mismatch answers HTTP 409 with a constant non-PHI detail; `_post_checked` relays it; the portal's existing non-400/422 arm renders the system-failure message — no gateway edit, no new portal result branch. Re-mint on first edit after a non-success: flag set on failure result and network-error catch, every field change funnels through one `touch()` helper, id and flag live in refs, success screen replaces the form (owner 2026-08-13, re-derives e5 D-19 relay + D-20) | SPEC-13's "existing system-failure branch" is exactly the portal's non-400/422 arm (`page.tsx:99-100`); a ref, not state — the mint is synchronous with the first edit and nothing renders from it |
| e5b-D-16 | delivery | Size budget for this item raised 400 → 700 lines (owner 2026-08-14, disposition of impl-gate round-1 finding 1) | the 400 default was sized for authored sections and e5b's header-through-Plan sits ~330; the overage is the append-only Findings/Delivery record — unusually deep for a restart item (two drift-gate rounds, the impl gate, codex rounds to come) — and raising the budget keeps that record intact where trimming would thin evidence |

## Requirements

Status: AGREED 2026-08-13
Source: engagement owner ask, 2026-08-13, verbatim:

> "E5B is getting a bit bloated, and we've come to accept some residuals. Also, its
> foundations were built without the latest iteration of the workflow process. What are
> your thoughts on closing this PR, while keeping this branch as a reference for now and
> restarting e5b from the start?"

Decision taken: close, keep the branch as reference, restart (e5b-D-1). The defect this
item exists for is OPEN on `main`: a registration that commits and then loses its
response leaves a row the operator never sees confirmed, and the retry forks a second
chart with its own coverage and consent rows (`docs/debt-log.md`, "Intake contract
break" residual 2 — the register-first residual). PR #76 proved the class fixable and
its nine review rounds are this item's inherited checklist (e5b-REQ-6).

| ID | Requirement | Notes |
|----|-------------|-------|
| e5b-REQ-1 | When a front-desk operator re-submits a registration whose outcome was never delivered to them, the system holds exactly one patient chart, one coverage record, and one consent set for that submission | ⚠ human-gate — PHI path, `docs/landmines.md` §1; a duplicate chart carries its own consents, making the duplicate a compliance artefact, not just data-quality. Re-homed per e5b-D-2 |
| e5b-REQ-2 | An operator's corrected re-submission is never confirmed as the original: the system never acknowledges content it did not save, and never silently discards a correction | the PR #76 round-2 lesson, runtime-confirmed there (an idempotency key without content awareness confirmed an edited retry while dropping the edit — a spec defect that cost an amendment plus a re-gate mid-review); requirements-level now so it cannot recur as review-time spec work |
| e5b-REQ-3 | A genuinely new registration is never refused or absorbed as a retry — including for a person who already has a chart: two genuine submissions for one person still create two charts and still queue the pair for human review, never a merge | ⚠ human-gate — PHI; planted-defect preservation (`CLAUDE.md` §0): D5/no-MPI stays open and must be *shown* open (`docs/landmines.md` §3 negative tests). Re-homed per e5b-D-2 |
| e5b-REQ-4 | The retry mechanism introduces no patient-identifying value into any surface it creates: nothing it mints, records, or logs is derived from or carries patient data, wherever it lands (log line, response body, persisted state) | ⚠ human-gate — PHI columns + `docs/phi-logging-policy.md`; e5's review also proved the *boundary* can only narrow accidental derivation, not prove randomness — where each guarantee lives is a spec-stage decision this requirement forces into the open. Re-homed per e5b-D-2 |
| e5b-REQ-5 | An operator can tell from the health surface whether registration can work: for every state reachable from the committed templates and the documented boot and upgrade paths (fresh clone, make-driven stack, database predating this item's state), the service never reports healthy while refusing every registration | the PR #76 r5 B (healthy-but-503 stack from templates) and the r6→r7 re-raise (existing databases never receive new state; overruled into a health-signal guard) — the two deploy-surface churn sources, now a requirement instead of review findings |
| e5b-REQ-6 | Every surface PR #76's nine review rounds raised that e5b leaves unclosed is, before e5b merges, either encoded in this item's artifacts or recorded as a named registry entry / documented exclusion | the anti-narrowing rule (e6's REQ-6 shape); the harvest's round ledger and residual list are the checklist — nothing from the closed PR dies silently |
| e5b-REQ-7 | When the system serves a replayed registration outcome, any eligibility result it presents comes from a live re-verification at replay time, never from a verdict stored at the original submission | e5b-D-5 |

Out of scope: persisting the eligibility verdict (`docs/debt-log.md` D4 residual 3 — its
own item; twice re-raised in PR #76 review and twice reaffirmed as out, consistent with
e5b-D-5) · register-first / async re-verification (same debt entry, different fix class) ·
remount/draft lifecycle (e5b-D-3 — named successor item e7) · D5 merge/MPI and D5b/RIV-175
booking race (planted, curriculum) · the `make seed` guardrail and migration-runner class
(debt-log cross-cutting rows; `schema-apply` cherry-pick is queued for the restarted e6) ·
TODO-62's fifth portal result branch (closed-at-birth; re-derives only if the spec re-takes
the required-field + 422 choice).

## Spec

Status: FROZEN 2026-08-13 (open questions resolved as e5b-D-6..9)

Check column: `test:` pinned test id (filled at impl, changes only by owner decision) ·
`cmd:` impl-gate runnable check · `gate:` human judgment at impl gate, observation
recorded in Delivery. Configured values are named as configuration; numbers are plan
detail. "Identifier" = the submission-attempt identifier; "content binding" = the
recorded artifact SPEC-12 defines. ⚠ rows inherit the `docs/landmines.md` §3
negative-test rule; §1 approval before code on persisted-state and contract rows.

**e5b-REQ-1 — one chart, one coverage record, one consent set per retried submission**

| ID | EARS | Check | ⚠ |
|---|---|---|---|
| e5b-SPEC-1 | When a registration whose outcome was never delivered to the operator is re-submitted with identical content, the intake service shall hold exactly one patient chart for that submission | test: replay-single-chart | ⚠ |
| e5b-SPEC-2 | When such a re-submission is served, the intake service shall create no additional coverage record and no additional consent row | test: replay-no-coverage-consent | ⚠ |
| e5b-SPEC-3 | The portal shall attach an identifier to every registration submission, unchanged across re-submissions of the same attempt | test: fe-attempt-identifier | ⚠ |
| e5b-SPEC-4 | The identifier shall be a declared, required field of the registration request payload contract (additive extension of the frozen contract; e5b-D-6) | test: contract-identifier-field | ⚠ |
| e5b-SPEC-5 | The gateway shall forward the identifier unchanged and shall never generate, substitute, or drop one | test: gateway-forwards-identifier | ⚠ |
| e5b-SPEC-6 | The intake service shall record the identifier against the registration in the same transaction that creates the chart; a transaction that does not commit shall record nothing | test: identifier-same-transaction | ⚠ |
| e5b-SPEC-7 | When a request carries a recorded identifier with content matching the content binding, the intake service shall answer with the original success outcome and patient identifier, creating and modifying nothing; the response shall carry no replay indication (e5 D-5, per e5b-D-4) | test: replay-indistinguishable | ⚠ |
| e5b-SPEC-8 | When concurrent requests carry the same identifier, exactly one shall create the registration; the other shall wait a configured bounded time and answer with the winner's result (e5 D-6, per e5b-D-4) | test: collision-loser-waits | ⚠ |
| e5b-SPEC-9 | If the bounded wait expires, then the intake service shall answer in the existing system-failure branch and create nothing; the next retry replays the committed result (imprecision accepted, e5b-D-7) | test: wait-expiry-503 | ⚠ |
| e5b-SPEC-10 | The intake service shall retain recorded identifiers without expiry or pruning (e5 D-7, per e5b-D-4) | test: no-pruning-path | ⚠ |
| e5b-SPEC-11 | If a submission arrives without an identifier, then the intake service shall reject it in the existing correctable-input branch and create nothing (e5b-D-6; the TODO-62 residual re-derives, named at delivery) | test: missing-identifier-rejected | ⚠ |

**e5b-REQ-2 — a corrected re-submission is never confirmed as the original**

| ID | EARS | Check | ⚠ |
|---|---|---|---|
| e5b-SPEC-12 | In the same transaction as SPEC-6's record, the intake service shall record a content binding derived from the validated submitted content, sufficient to distinguish an identical re-submission from a differing one | test: binding-same-transaction | ⚠ |
| e5b-SPEC-13 | If a recorded identifier arrives with content differing from the content binding, then the intake service shall answer with a failure in the existing system-failure branch, create and modify nothing, and never acknowledge the differing content as saved | test: mismatch-writes-nothing | |
| e5b-SPEC-14 | When the operator edits any form value after an attempt whose outcome was a failure or was never delivered, the portal shall submit subsequent submissions as a new attempt with a fresh identifier (if the original committed, the edit creates a second chart and the pair queues per SPEC-16 — visible, never a silent discard) | test: fe-remint-on-edit | |

**e5b-REQ-3 — a genuinely new registration is never refused or absorbed**

| ID | EARS | Check | ⚠ |
|---|---|---|---|
| e5b-SPEC-15 | When a submission carries an unrecorded identifier, the intake service shall create a new registration — including when identical patient-identifying values already exist (D5/no-MPI stays open, shown open) | test: no-accidental-mpi | ⚠ |
| e5b-SPEC-16 | When two genuine submissions for one person both complete, the system shall hold two charts and queue the pair for human duplicate review, never merging | test: pair-queued-not-merged | ⚠ |
| e5b-SPEC-17 | The portal shall mint a fresh identifier for every new registration; an identifier shall never be reused across registrations | test: fe-fresh-per-registration | ⚠ |

**e5b-REQ-4 — the mechanism introduces no patient-identifying value anywhere**

| ID | EARS | Check | ⚠ |
|---|---|---|---|
| e5b-SPEC-18 | The portal shall mint the identifier from a source independent of all patient data and form content — the randomness guarantee lives at the mint (e5b-D-9) | test: fe-mint-independent | ⚠ |
| e5b-SPEC-19 | If a submitted identifier does not conform to the declared random format, then the intake service shall reject it and create nothing. Named limit: the format check narrows the accidental-derivation class only and cannot prove randomness (e5b-D-9) | test: format-check-boundary | ⚠ |
| e5b-SPEC-20 | No surface the retry mechanism creates — log line, response body, persisted state — shall carry a patient-identifying value | test: no-phi-any-surface | ⚠ |
| e5b-SPEC-21 | From the persisted content binding, no patient-identifying value shall be recoverable, including by an actor who holds the stored records and guesses candidate field values (the offline-oracle property — keyed derivation, e5b-D-8) | test: binding-not-reversible | ⚠ |
| e5b-SPEC-22 | If the server-side secret the content binding depends on is missing or not a real secret, then the intake service shall refuse registration processing before any read or write, and the refusal shall name the configuration, never a value (e5b-D-8) | test: key-fail-closed | ⚠ |

**e5b-REQ-5 — health reflects the ability to register**

| ID | EARS | Check | ⚠ |
|---|---|---|---|
| e5b-SPEC-23 | While the intake service is in a state in which every registration would be refused, its health surface shall not report healthy | test: health-tracks-refusal | |
| e5b-SPEC-24 | When the stack is brought up from a fresh clone by the documented boot path, registration shall work: the committed templates plus the boot path shall produce a configuration satisfying every fail-closed guard this item adds (the r5 invariant) | test: boot-path-outcome | |
| e5b-SPEC-25 | While the database predates this item's persisted state, the intake service shall not report healthy, and its health detail shall name the missing state carrying no patient data and no secret value (upgrade *command* is out of scope → e6) | test: stale-db-unhealthy | |
| e5b-SPEC-26 | When a refusing state (missing schema state, unreal secret) is introduced into a running stack and then reverted, the health surface shall track both transitions | gate: live break-then-revert on an isolated stack, observation in Delivery | |

**e5b-REQ-6 — nothing from PR #76 dies silently**

| ID | EARS | Check | ⚠ |
|---|---|---|---|
| e5b-SPEC-27 | Before e5b merges, every surface in the harvest round ledger (r1–r9) and residual list shall be traceable to an e5b artifact clause, a named registry entry, or a documented exclusion | gate: traceability audit at impl gate, recorded in Delivery | |

**e5b-REQ-7 — replayed eligibility is live, never stored**

| ID | EARS | Check | ⚠ |
|---|---|---|---|
| e5b-SPEC-28 | When a served replay presents eligibility information, it shall come from a live re-verification performed at replay time, through the same bounded, breaker-guarded path as an original submission (e5b-D-5) | test: replay-reverifies-live | |
| e5b-SPEC-29 | The retry mechanism shall persist no eligibility verdict | test: no-verdict-persisted | |

Exclusions: eligibility-verdict persistence and register-first re-verification
(debt-log D4 residual 3, per e5b-D-5) · remount/draft lifecycle (e5b-D-3 → e7) ·
D5 merge/MPI and D5b booking race (planted; SPEC-15/16 prove D5 open, never close it) ·
migration-runner class and `make seed` guardrail (debt-log cross-cutting; `schema-apply`
queued for restarted e6 — SPEC-25 pins only the health signal) · TODO-62's fifth portal
result branch (stays closed-at-birth; SPEC-13 answers in the existing branch).

## Plan

Status: GATED 2026-08-13

Design is carried by e5b-D-10..15; this section is the file-level delta and its checks.
Migration number verified free on main this session: `db/migrations/` ends at `009_*.sql`.

Changes (file level):
- `db/migrations/010_registration_submissions.sql` — new table `registration_submissions`
  (`submission_id TEXT` with named constraint `uq_registration_submission_id`,
  `payload_fingerprint TEXT`, `patient_id` FK → `patients.id`, `created_at`); no verdict
  column exists to persist (e5b-SPEC-6, -10, -12, -29; e5b-D-11/12)
- `db/schema.sql` — hand-synced `CREATE TABLE IF NOT EXISTS` append of the same table,
  the repo's 15th (e5b-SPEC-6; the hand-sync landmine)
- `services/intake-service/models.py` — `RegistrationSubmission` model mirroring 010
  (e5b-SPEC-6)
- `services/intake-service/schemas.py` — `submission_id` required root field on
  `IntakeRequest` with a version-4 validator; `submission_id` added to `log_metadata`'s
  allowlist (e5b-SPEC-4, -11, -19; e5b-D-10)
- `services/intake-service/config.py` — `registration_fingerprint_key`,
  `registration_lock_wait_seconds` (default 5) (e5b-SPEC-8, -22; e5b-D-11/12)
- `services/intake-service/app.py` — fail-closed key guard before any read/write; replay
  lookup by recorded id; fingerprint compare → replay (201, original `patient_id`, live
  eligibility re-verification through `_verify_eligibility_guarded`) or 409; submission
  row inserted inside `_create_registration`'s existing single transaction with
  `lock_timeout` SET; unique-violation → re-read-and-replay, lock-timeout → existing 503
  branch; `/healthz` extended per e5b-D-14 (e5b-SPEC-1, -2, -6..9, -13, -15, -22, -23,
  -25, -28; e5b-D-11/12/14/15)
- `contracts/intake-registration.json` — `submission_id` joins `request_fields.root` and
  `sample_request` (e5b-SPEC-4; both suites assert it, same slice as the two test files)
- `frontend/app/intake/payload.ts` — `newSubmissionId()` mint (randomUUID +
  getRandomValues fallback); `buildIntakePayload` gains the 4th argument (e5b-SPEC-3,
  -17, -18; e5b-D-10)
- `frontend/app/intake/page.tsx` — id + edited-since-non-success flag in refs; mint at
  first submit of an attempt; `touch()` funnel re-mints on first edit after a non-success
  (e5b-SPEC-3, -14, -17; e5b-D-15)
- `Makefile` — generated `.env.registration` target on the `.env.redis` pattern; joins
  the standing target prerequisites (e5b-SPEC-24; e5b-D-13)
- `docker-compose.yml` — intake-service `env_file` becomes the list
  `[.env, .env.registration]`; nothing else gains the file (e5b-SPEC-24; e5b-D-13)
- `.gitignore` — `.env.registration` entry (e5b-D-13)
- `.env.example` — `REGISTRATION_LOCK_WAIT_SECONDS=5` with its budget-invariant comment;
  no key entry (the key is generated, never templated) (e5b-SPEC-8, -24)
- `tests/test_intake_idempotency.py` — new; homes the spec's `test:` ids
  replay-single-chart, replay-no-coverage-consent, identifier-same-transaction,
  replay-indistinguishable, collision-loser-waits, wait-expiry-503, no-pruning-path,
  missing-identifier-rejected, binding-same-transaction, mismatch-writes-nothing,
  no-accidental-mpi, pair-queued-not-merged, format-check-boundary, no-phi-any-surface,
  binding-not-reversible, key-fail-closed, replay-reverifies-live, no-verdict-persisted
- `tests/test_intake_schema_guard.py` — new; health-tracks-refusal, stale-db-unhealthy
  (e5b-SPEC-23, -25)
- `tests/test_intake_schemas.py` — v4-only + canonicalization cases (e5b-SPEC-19;
  e5b-D-11)
- `tests/test_intake_payload_contract.py` — contract-identifier-field (e5b-SPEC-4)
- `tests/test_gateway_intake_proxy.py` — gateway-forwards-identifier: byte-for-byte
  forward, mints none (e5b-SPEC-5; test-only — `proxy_intake`'s `payload: dict`
  passthrough already forwards, verified this session)
- `tests/test_compose_topology.py` — scoped-generated-secret pins (reaches only intake;
  loads after `.env`; generated not copied; gitignored; every target's prerequisite) plus
  the boot-path outcome test that runs the Makefile recipe and feeds what it wrote to the
  key-real predicate (e5b-SPEC-24)
- `tests/test_eligibility_budget_alignment.py` — new assertion: gateway
  `INTAKE_TIMEOUT_SECONDS` ≥ intake `ELIGIBILITY_TIMEOUT_SECONDS` + lock wait + margin,
  against defaults and `.env.example` (8 + 5 + 1 ≤ 30 today) (e5b-SPEC-8; landmine budget
  pinning)
- `frontend/app/intake/payload.contract.test.ts` — fe-attempt-identifier contract half,
  fe-mint-independent, fe-fresh-per-registration mint cases (v4, distinct per call,
  fallback path) (e5b-SPEC-3, -17, -18)
- `frontend/app/intake/page.test.tsx` — attempt semantics: same id across re-submissions,
  fresh per registration, fe-remint-on-edit, unreached-submit counts as undelivered
  (e5b-SPEC-3, -14, -17)
- `docs/phi-logging-policy.md` — register rows for the mechanism's new log surfaces,
  re-derived (why the id is loggable; why keyed HMAC, never a plain hash) (e5b-SPEC-20)
- `docs/debt-log.md` — "Intake contract break" residual 2 status update at landing
- `docs/runbook.md` — key-rotation note (rotation invalidates recorded fingerprints;
  bounded, visible) (e5b-D-13 residual)
- `docs/todo.md` — the SPEC-11 non-correctable-rejection residual re-filed as a named
  entry (id assigned at landing per the collision rule; TODO-62 stays a closed record)
- mechanical accommodations — every existing test that POSTs `/intake` or constructs
  `IntakeRequest` gains the now-required field (sweep re-run this session:
  `rg "IntakeRequest\("` plus `/intake` POSTs over `tests/`):
  `tests/test_intake_endpoint.py` (plus its settings-object key fixture — config reads
  env at class-body import time), `test_intake_db_error_phi.py` (`IntakeRequest(**payload)`,
  line 128), `test_intake_match_key.py` (line 133), `test_intake_schemas.py`'s nine
  existing constructor cases (the `pytest.raises` cases too, so each still fails for its
  intended field, not the missing id), `test_redaction.py` fixture field (lines 85, 137),
  sqlite `get_bind` stubs where the new lookup needs them (e5b-SPEC-4 making the field
  required forces these; no assertion weakened). `test_intake_freeze_regression.py`,
  `test_intake_deferred.py`, `test_intake_breaker.py` drive `_verify_eligibility`/breaker
  paths with `Insurance` objects only — no accommodation; gateway AI tests hit
  `/ai/intake-instructions` — out of reach

Landmine approvals (verbatim, never compressed):
- **Migrations / PHI-adjacent schema** (`docs/landmines.md` §1 "Schema and migrations are
  hand-synced"; §1 PHI handling): the item adds one new table via
  `db/migrations/010_registration_submissions.sql` plus the hand-synced `db/schema.sql`
  append. No existing table or PHI column is altered. The new table carries no PHI by
  construction: `submission_id` is mint-random (e5b-SPEC-18), `payload_fingerprint` is a
  keyed HMAC from which no patient value is recoverable (e5b-SPEC-21), the rest is an FK
  and a timestamp. Entry approved by the owner's spec freeze of 2026-08-13, which stamped
  every ⚠ persisted-state and contract row (e5b-SPEC-4, -6, -12) after resolving
  e5b-D-6..9; plan-stage decisions e5b-D-10..15 owner-confirmed 2026-08-13 (gate round 1
  finding 3 disposition) — no owner act outstanding before implementation code.
- **Secret files / bootstrap** (§1 "Secrets in git history" — do not add more secrets):
  the item introduces `REGISTRATION_FINGERPRINT_KEY` as a generated, gitignored,
  intake-scoped `.env.registration` (e5b-D-13). No secret value is committed: no template
  ships, `.env.example` gains only the non-secret lock-wait knob, and `.gitignore` gains
  the entry. A stray untracked `.env.registration` from the closed e5 branch's live
  testing sits in the working tree today; it is deleted before branch cut and regenerated
  by `make up` — it never enters git. Key rotation invalidates recorded fingerprints —
  accepted residual, bounded and visible (a straddling retry answers 409), documented in
  the runbook over building key-versioning machinery.
- **Inline eligibility budget** (§1 "Inline eligibility call"): the bounded lock wait
  enters intake's request-thread budget. No timeout is widened and no breaker threshold
  is loosened; `tests/test_eligibility_budget_alignment.py` gains the sum-shape assertion
  covering the new knob (8s eligibility + 5s lock wait + 1s margin ≤ the gateway's 30s
  intake timeout, both defaults and `.env.example`).
- **Auth / sessions**: not touched. `proxy_intake`'s `require_capability("patients.write")`
  and everything in the gateway auth path are unchanged; the gateway diff is zero code
  (one test file only).
- **Deliberate defects in reach, preserved**: D5/no-MPI stays open and is *shown* open by
  e5b-SPEC-15/16's negative tests (an unrecorded id always creates; two genuine
  submissions still fork and queue, never merge). D5b/RIV-175, D11/`?q=%25`, D2
  (audit_logs writerless), D8 (zero indexes — the only new index is the UNIQUE constraint
  on the new table, nothing existing gains one), and the HL7 AL1/RXA xfail are untouched.
- **Accepted residuals, named**: expiry of the bounded wait answers imprecisely in the
  503 branch (e5b-D-7; self-heals on next retry) · a missing/malformed identifier is a
  non-correctable rejection surfaced in the correctable-input branch (e5b-D-6; the
  TODO-62-shape residual, re-filed at landing) · the v4 format check narrows the
  accidental-derivation class only — randomness is guaranteed only at the mint (e5b-D-9)
  · a served replay costs a second live eligibility hop, inside the existing budget
  (e5b-D-5) · recorded identifiers grow unboundedly, order-of-`patients` (e5b-D-4) · the
  fingerprint is derived from PHI and must stay keyed forever (e5b-D-8) · remount loses
  the attempt id — deferred whole to e7 (e5b-D-3) · e5b-SPEC-25 ships the health signal
  only; the upgrade command is e6's (`make schema-apply` cherry-pick), so an operator on
  a stale database gets an accurate red and a runbook pointer, not a fix command from
  this item · `lock_timeout` semantics must be proven against real Postgres, not sqlite
  (verification 8; a `statement_timeout` fallback, if ever taken, has wider blast radius
  and is recorded as a decision).

Verification (runnable, expected output stated):
1. `.venv/bin/python -m pytest -m "not integration" -q` → all green; count =
   branch-cut baseline + this item's additions, xfail/deselected unmoved at 1/5
   (baseline measured and recorded in Delivery at branch cut; `CLAUDE.md` §6's 969 is
   known-stale, per the e5 close record) (all `test:` SPEC rows)
2. `make test-docker` → same result under python:3.12 — the claim-worthy gate
3. `cd frontend && npm test` → green including the new mint/attempt cases; `npm run
   build && npm run typecheck && npm run lint` clean (e5b-SPEC-3, -14, -17, -18)
4. `.venv/bin/python -m pytest tests/test_intake_payload_contract.py -q` and
   `cd frontend && npx vitest run app/intake/payload.contract.test.ts` → both green —
   the two-sided contract holds with `submission_id` (e5b-SPEC-4)
5. break-then-revert (key): empty the value in the generated `.env.registration`,
   restart intake → `GET /healthz` 503 with detail naming the variable and no value;
   `POST /intake` 503 before any write; restore → `/healthz` 200, `POST /intake` 201
   (`app.py:115`) (e5b-SPEC-22, -23, -26; live
   half is the SPEC-26 gate observation, recorded in Delivery)
6. break-then-revert (schema): on an isolated scratch stack, drop
   `registration_submissions`, restart intake → `/healthz` 503 naming the missing table,
   no patient data, no secret; re-apply `db/schema.sql` → healthy (e5b-SPEC-25, -26)
7. `make down && rm -f .env.registration && make up` from a clean checkout state →
   `.env.registration` regenerated with a real key; intake healthy; a registration
   round-trips (e5b-SPEC-24, the r5 invariant)
8. integration marker: against real Postgres, the registration transaction shows
   `lock_timeout = '5000ms'` for the default 5 — the issued value, pinning the s→ms
   conversion (e5b-SPEC-8; e5b-D-12's units trap)
9. break-then-revert (negative-control): revert the v4 validator → format-check tests
   red; restore → green. Revert the `touch()` re-mint → fe-remint-on-edit red; restore →
   green (e5b-SPEC-14, -19; `docs/landmines.md` §3 rule)
10. `rg "submission_id" services/gateway/` → no matches, and `git diff main --stat --
    services/gateway/` at PR time → empty — the gateway code diff is zero; SPEC-5 is
    enforced by test alone (e5b-SPEC-5)
11. impl gate: SPEC-27 traceability audit — every harvest r1–r9 row and residual maps to
    an e5b clause, a registry entry, or a named exclusion; observation recorded in
    Delivery (e5b-SPEC-27)

## Findings

### Gate — round 1, 2026-08-13

4 findings, no stamp.

| # | SPEC | Finding | Disposition (stage 3) |
|---|------|---------|-----------------------|
| 1 | e5b-SPEC-4 | The mechanical-accommodations list omits `tests/test_intake_db_error_phi.py`, which constructs `IntakeRequest(**payload)` (line 128) and goes red the moment `submission_id` becomes required — an unplanned red file at implementation. | Fixed 2026-08-13: file added to the mechanical-accommodations row; the sweep re-run (`rg "IntakeRequest\("` + `/intake` POSTs over `tests/`) also surfaced `test_intake_schemas.py`'s nine existing constructor cases, added to the same row |
| 2 | e5b-SPEC-4 | The same list names `test_intake_freeze_regression.py`, `test_intake_deferred.py`, and `test_intake_breaker.py` as tests that "POST `/intake`", but none POSTs `/intake` or constructs `IntakeRequest` — all three drive `_verify_eligibility`/breaker paths with `Insurance` objects only and need no accommodation; the claim is a wrong in-repo fact. | Fixed 2026-08-13: three files removed; the row now records what they actually drive and scopes itself to constructs-`IntakeRequest`-or-POSTs-`/intake`, re-verified by the same sweep |
| 3 | — | Plan-stage decisions e5b-D-10..15 are not recorded as owner-confirmed: the register rows carry only a date where e5b-D-1..9 carry "owner 2026-08-13", and the Landmines block itself names their confirmation as "the remaining owner act" — so the ⚠ zone entries (migrations/PHI table via D-10..12, secret bootstrap via D-13) rest on approvals the file does not yet record; plan-authoring requires plan decisions owner-confirmed, and item state must be derivable from the file alone. | Fixed 2026-08-13: owner confirmed e5b-D-10..15 wholesale this session; register rows stamped `owner 2026-08-13`, Landmines block updated to record no outstanding owner act |
| 4 | e5b-SPEC-22 | Verification 5's restore step expects "both 200", but `POST /intake` answers 201 on success (`services/intake-service/app.py:115`) — wrong expected output in a runnable check. | Fixed 2026-08-13: restore step now expects `/healthz` 200, `POST /intake` 201, citing `app.py:115` |

Gate evidence (verified fresh this session, working tree at `b6c160b`): migrations end at
`009_duplicate_review_queue.sql` and `db/schema.sql` holds 14 tables (the plan's "15th"
holds); `_create_registration` (`app.py:151`), `_verify_eligibility_guarded` (`app.py:420`),
`log_metadata` allowlist (`schemas.py:160`) all exist as cited; `proxy_intake` is
`payload: dict` on `_post_checked`, which relays downstream status/bodies as-is (the D-15
409 relay holds); `page.tsx:99-100` is the cited non-400/422 arm; the `.env.redis`
generate-and-prerequisite Makefile pattern, intake's single `env_file: .env`, the
`ELIGIBILITY_TIMEOUT_SECONDS=8` / `INTAKE_TIMEOUT_SECONDS=30` defaults, and the stray
untracked `.env.registration` all match the plan; the duplicate-review queue SPEC-16 leans
on exists (`009`, `matching.py`). Check map complete — 29 rows, exactly one mechanism
each; freeze scope holds (no rows for the e7 deferral); change list closes both ways
except finding 1; the spec's test-id map closes over the five named test homes; gateway
`test_gateway_authz.py` / `test_gateway_proxy_error_contract.py` POST `/intake` but need
no accommodation (gateway never validates the payload) — the plan's omission of them is
correct.

### Gate — round 2, 2026-08-13

Clean, stamped GATED.

checked: full fresh re-run against the final text — e5b-SPEC-1..29 per-SPEC verdicts
(all satisfied or residual-named in the Landmines block: SPEC-8 real-Postgres
`lock_timeout` proof, SPEC-11 TODO-62-shape rejection, SPEC-19 mint-only randomness,
SPEC-25 signal-only); check map complete (29 rows, one mechanism each; 27 `test:` ids
each homed to a named file, 2 `gate:` with Delivery-recorded observations); ⚠ coverage
(20 ⚠ rows, every §1 zone entry citing a decision ID, e5b-D-10..15 recorded
owner-confirmed per round-1 f3); freeze scope holds (no rows for the e7 remount
deferral); change list closes both ways; round-1 dispositions verified applied
(accommodation sweep re-run and matching file-for-file and line-for-line, three
no-accommodation files confirmed `Insurance`-only, verification 5 expects 201 at
`app.py:115`); in-repo facts re-verified fresh at `b6c160b` (migrations end `009`,
`db/schema.sql` 14 tables, `app.py:96/115/151/420`, `schemas.py:160`,
`page.tsx:99-100`, `proxy_intake` dict-passthrough on `_post_checked`, zero
`submission_id` under `services/gateway/`, `.env.redis` Makefile
generate-and-prerequisite pattern, intake `env_file: .env`, 8s/30s timeout defaults so
8+5+1 ≤ 30, intake config reads env at class-body import, contract carries
`request_fields.root` + `sample_request`, `tests/test_intake_idempotency.py` and
`tests/test_intake_schema_guard.py` do not yet exist, stray untracked
`.env.registration` present and unignored); three plan-authoring checks run cold
(self-consistency incl. the generated key passing the key-real predicate and the
compose/topology pins; gate interaction incl. two-sided contract suites and unchanged
gateway route set; residual honesty); verification runnable, 11 numbered commands with
expected output, negative break-then-revert at 5/6/9.

### Impl gate — round 1, 2026-08-13

3 findings, no stamp.

| # | anchor | finding | disposition |
|---|--------|---------|-------------|
| 1 | README size budget | `docs/workflow/e5b.md` is 471 lines against the 400-line default budget checked at this gate, and no stage-tagged decision in the register raises it — either trim (the Delivery section is the growth since the plan gate) or record an owner decision that raises the budget and says why. | A — raised @ e5b-D-16 (owner 2026-08-14): item budget 700; file 533 at disposition |
| 2 | e5b-SPEC-8 | `tests/test_intake_idempotency.py:13` cites `tests/integration/test_intake_lock_timeout.py` as the real-Postgres proof site, but no such file exists (`tests/integration/` holds only `test_records_flow.py`) — Delivery's own deviation records the proof as a live run with no committed integration file, so the docstring is a wrong in-repo fact of the class round-1 gate finding 2 already caught once. | A — fixed 2026-08-13 (owner-directed same-session fix): docstring now cites the unit pin + the Delivery verification-8 live run and why no integration file ships; file re-run green (27 passed) |
| 3 | e5b-SPEC-24 | Plan verification 7 (`make down && rm -f .env.registration && make up` → key regenerated, intake healthy, a registration round-trips) is the only numbered verification with no recorded evidence: Delivery records 1–4/8/9/10 and defers 5/6's live halves to this gate via the SPEC-26 `gate:` row, but v7 is neither run-recorded nor deferral-noted. | A — fixed 2026-08-13 (owner-directed same-session fix): v7 run live under `COMPOSE_PROJECT_NAME=e5bv7` (real `make up` target, fresh isolated volume, removed after) and recorded in Delivery — key regenerated real, healthz 200, 201 + replay |

Gate evidence (fresh session, working tree clean at `c597ac9`): full suite re-run
(`.venv` py3.12, `-m "not integration"`) → **1295 passed, 5 deselected, 1 xfailed** —
baseline 1247 + 48, xfail/deselected unmoved, matching Delivery; frontend `npm test` →
109 passed incl. `page.test.tsx` 18. Spec test-id map closes: all 27 `test:` labels
found in the named files, no `cmd:` rows. Pinned-test diff clean: E4's
`test_the_gateway_registration_bound_never_preempts_intake` untouched (the e5b
sum-shape is a new sibling test); every accommodation is additive (valid
`submission_id` supplied so each `pytest.raises` case still fails for its intended
field; no assertion weakened). Change list closes both ways — the one unplanned file
(`.github/workflows/ci.yml`) is covered by Delivery deviation 2. Idiom sweep clean:
no `Co-Authored-By`, gateway code diff empty, `rg submission_id services/gateway/`
zero, no `str(e)` on touched paths, new log lines carry `submission_id` + class names
only, PHI-register row present. Planted defects preserved: D5 shown open
(`test_no_accidental_mpi`, two-charts-never-merged), D8 untouched (only the
constraint-backed index), D2/D5b/D11/AL1-RXA xfail untouched. Landmine approvals
present in the plan's block for migrations, secret bootstrap, and budget; no stray
`.env.registration` tracked or in tree.

`gate:` observations (quoted here, not written to Delivery, since the round is red):
- **e5b-SPEC-26 live break-then-revert** — isolation: scratch compose project
  `e5bgate` (postgres + intake-service only, its own network and `pgdata` volume,
  removed with `down -v` after; the engagement stack was not running and its volume
  never mounted). Key half: real generated key + fresh schema → `/healthz` 200; key
  emptied + container recreated → `/healthz` 503
  `{"detail":"registration unavailable: REGISTRATION_FINGERPRINT_KEY not configured"}`
  and `POST /intake` the same 503 with `registration_submissions` count 0 after (no
  write); key regenerated by the make recipe → 200, `POST /intake` 201
  (`patient_id` 1852), byte-identical replay → 201 same `patient_id`. Schema half:
  `DROP TABLE registration_submissions` → 503
  `{"detail":"registration schema incomplete: missing registration_submissions"}` (no
  PHI, no secret); re-apply `db/schema.sql` → 200. Both transitions tracked both ways.
- **e5b-SPEC-27 harvest traceability audit** (against
  `~/Documents/Work/process-plans/e5b-restart/harvest.md`): r1 → e5b-SPEC-19/D-9 +
  TODO-67; r2 → e5b-REQ-2, SPEC-12/13/14, D-11; r3 f1 + r4 → e5b-D-5, SPEC-28/29,
  D4-residual-3 exclusion; r3 f2 → D-8/D-11 key-real predicate, SPEC-22; r5 →
  e5b-REQ-5, SPEC-24, D-13, the boot-path outcome test; r6 → SPEC-25 + the
  schema-apply/e6 exclusion + debt-log "No migration runner" (landed `b6c160b`); r7
  f1/f1b → SPEC-23/25/26, D-14, shared predicate; r7 f2 + r8 + r9 (remount, open at
  close) → e5b-D-3 → named successor e7, excluded in Requirements and Spec. Residuals
  1–8: 1 → D-5 + exclusions; 2 → e7; 3 → D-9/SPEC-19 named limit; 4 → runbook
  rotation note (this branch); 5 → PHI-register row (this branch); 6 → debt-log
  cross-cutting + SPEC-25 signal-only; 7 → debt-log seed row (landed `b6c160b`); 8 →
  TODO-67 and the re-derived SPEC rows. **Nothing unmapped.**

### Impl gate — round 2, 2026-08-14

Clean, stamped `delivery IMPLEMENTED` (plan stamp untouched).

checked: full fresh re-run against `c2a0b7f` (tree clean; round-1 fix delta since
`c597ac9` is `e5b.md` + one test docstring — zero runtime code) — round-1 dispositions
honored (f1 → e5b-D-16 budget 700, file 533 at gate; f2 docstring cites the unit pin +
verification-8 live run, no phantom integration file, `tests/integration/` holds only
`test_records_flow.py`; f3 → v7 evidence recorded in Delivery); pinned-test diff clean
(all 27 `test:` labels homed in the five named files, E4's
`test_the_gateway_registration_bound_never_preempts_intake` untouched with the e5b
sum-shape as a new sibling, every accommodation additive — each `pytest.raises` case
carries a valid `submission_id` so it still fails for its intended field); size budget
533 ≤ 700 (e5b-D-16); no `cmd:` rows; both `gate:` rows re-observed live this round
(observations in the Delivery gate record); change list closes both ways — the one
unplanned file (`.github/workflows/ci.yml`) is Delivery deviation 2; baseline re-run
twice — `.venv` py3.12 **and** `make test-docker` both **1295 passed, 5 deselected,
1 xfailed** (+48 traced test-for-test, xfail/deselected unmoved so no deliberate gap
moved); frontend re-run — `npm test` 109 passed (page 18, payload.contract 13),
`build`/`typecheck` clean, lint's one warning is the pre-existing DateField
aria-required one; planted defects preserved (D5 shown open by
`test_no_accidental_mpi` + two-charts-never-merged, D8 gains only the
constraint-backed UNIQUE index, D2/D5b/D11/AL1-RXA xfail and `docs/landmines.md`
untouched); idiom sweep clean (no `Co-Authored-By` trailers on the five branch
commits, gateway code diff empty and `rg submission_id services/gateway/` zero —
SPEC-5 by test alone, no `str(e)` on touched paths, new log lines carry
`submission_id` + exception class names only, PHI-register row present); §1 zone
approvals recorded in the plan's Landmines block (migrations/PHI-adjacent table,
secret bootstrap, eligibility budget; auth untouched); SPEC-17 checked in code — the
success screen replaces the form with only a dashboard `Link` exit, so a stale
attempt id cannot straddle registrations without a remount (remount itself is the
e7 deferral, e5b-D-3); portal-independent scrutiny of the idempotency core found no
defect (replay lookup → fingerprint compare → 409-or-replay, collision loser
re-reads the winner and 503s if the winner rolled back, `SET LOCAL lock_timeout`
gated to the postgresql dialect inside the single transaction).

### Review — round 1, 2026-08-14

PR #79, reviewer codex (`@JesterCharles` bot). One finding.

| # | Spec | Finding | Disposition |
|---|---|---|---|
| 1 | e5b-SPEC-20 | Caller-controlled `submission_id` is logged raw at every request-path site (initial metadata via `log_metadata`, success, replay-mismatch, replay-served). The version-4 format check proves shape, not randomness (e5b-D-9), so a caller reaching the gateway directly bypasses the portal mint and can smuggle an SSN/MRN into the UUID's 122 free bits — landing PHI in logs. e5b-D-10 chose raw logging on the strength of SPEC-18 mint-independence, but that is a *portal* guarantee the service cannot enforce; the anti-narrowing question e5b-REQ-6 forces surfaces it as a real defect against SPEC-20. | **A · fixed @cf19d96** — trivial route (keyed digest is a pure transform over the already-provisioned, fail-closed `REGISTRATION_FINGERPRINT_KEY`; no new state → no re-gate). New `_submission_log_id` emits a keyed HMAC digest (`submission_ref`) at all four sites; `log_metadata` no longer emits the raw id. PHI-log path → negative test `test_malicious_valid_uuid_is_never_logged_raw` (well-formed v4 UUID embedding an SSN in the node field; asserts raw id and SSN absent from logs and body, digest present). `docs/phi-logging-policy.md` register row + comment at both edited call sites updated. |

Verify: `.venv` py3.12 `-m "not integration"` → **1296 passed, 5 deselected, 1 xfailed**
(+1 the new negative test; xfail/deselected unmoved). Frontend untouched (Python + docs
only).

### CI — secret-scan (self-caught, 2026-08-14)

Not a codex finding — the PR #79 `secret-scan` (gitleaks) job was **red from the first
push** (`8bcc1e6`), which the impl gate and Delivery missed. Root cause: the synthetic
`REGISTRATION_FINGERPRINT_KEY` test fixture `REAL_KEY` (a repeated `0123456789abcdef`,
64 hex chars) trips the default `generic-api-key` entropy rule in
`tests/test_intake_idempotency.py:54` and `tests/test_intake_schema_guard.py:45`. No
`.gitleaks.toml` existed, so CI ran the bare default ruleset. Owner-approved mechanism
(scoped `.gitleaks.toml` allowlist over inline `gitleaks:allow` or a value change): a
config that **extends** the default ruleset (`[extend] useDefault = true`) and allowlists
only that exact 64-hex value — not a path, not the `tests/` tree — so any real
high-entropy leak still fails (the D9 recurrence guard is preserved); `ci.yml` passes
`--config=/repo/.gitleaks.toml` explicitly. Verified locally against the pinned
`gitleaks:v8.18.4` image: both `REAL_KEY` findings clear, default rules still fire on
other high-entropy strings; the remaining local hits (`.venv/`, `frontend/.next/`,
`.env.registration`) are untracked/gitignored and absent from CI's `actions/checkout`
tracked tree. Fixed @839bed6.

### Review — round 2, 2026-08-14

One finding.

| # | Spec | Finding | Disposition |
|---|---|---|---|
| 1 | e5b-SPEC-8/25 | `healthz` compares table *names* only, so a database where `registration_submissions` exists but lacks `uq_registration_submission_id` — a partially applied migration — reports healthy while the sole retry arbiter (e5b-SPEC-8) is absent: two same-`submission_id` requests each insert a patient and ledger row, silently restoring the duplicate-chart bug. e5b-D-14 chose the schema-presence check but recorded no decision on shape, so this deepens the same guard rather than contradicting a decision. | **A · fixed @70a2964** — trivial route (read-only inspector extension, no new state → no re-gate). Guard now verifies the ledger's declared columns and the UNIQUE constraint on `submission_id`, matched by covered column set (the name is DDL cosmetics; uniqueness is what idempotency rests on). Refusal detail names table/column/constraint only, never a value. Two drift regression tests: table rebuilt without the constraint, and without a declared column — each reads 503. |

Verify: `.venv` py3.12 `-m "not integration"` → **1298 passed, 5 deselected, 1 xfailed**
(+2 the drift tests; xfail/deselected unmoved). Frontend untouched (Python only).

## Delivery

Status: delivery DRAFT — impl gate not yet run (the `IMPLEMENTED` stamp lands when
a fresh-context impl-gate session returns clean; the plan stamp stays GATED)

Branch cut from `main` at the artifact's first commit; baseline measured then and
recorded in the header (1247 passed, 1 xfailed, 5 deselected). Full suite after
implementation, `make test-docker` (the claim-worthy gate) and `.venv` py3.12
agree: **1295 passed, 5 deselected, 1 xfailed** — `+48` passed, xfailed and
deselected **unmoved** (1/5), so no deliberate-gap count moved. Frontend gate:
`npm test` 31 passed (payload.contract 13, page 18), `build` + `typecheck` +
`lint` clean (lint's one warning is the pre-existing DateField one, untouched).

Test additions trace exactly to the change list: two new files —
`tests/test_intake_idempotency.py` (27), `tests/test_intake_schema_guard.py` (3) —
plus extensions to `test_intake_schemas.py` (+8), `test_intake_payload_contract.py`
(+1), `test_gateway_intake_proxy.py` (+2), `test_eligibility_budget_alignment.py`
(+1), `test_compose_topology.py` (+6). 27 + 3 + 18 = 48. Every one of the 27
frozen `test:` labels is homed in a named file (verified by scan); the 2 `gate:`
rows are the Delivery observations below.

Slices test-first (behavioural seam, `tdd` loop): schemas identifier + validator,
the app.py idempotency core, the health guard, and the frontend mint/attempt
semantics — each EARS row got its failing test at the plan's seam before the code.
Slices with no behavioural seam, verified by their own checks rather than TDD:
the DB migration/model/schema-sync, config knobs, and the infra wiring (Makefile,
compose, `.gitignore`, `.env.example`) — covered by the contract, topology,
budget, and boot-path tests.

Deviations (plan facts correct; these are consequences the change list implied but
did not spell out):
- **Verification 8 (real-Postgres `lock_timeout`) run live, no committed
  integration file.** The change list names no `tests/integration/` file, so none
  was added — adding one would also move the deselected count. The s→ms conversion
  is unit-pinned (`test_intake_idempotency.py::test_lock_timeout_ms_conversion_pins_the_units`,
  `_lock_timeout_ms()` → 5000), and real-Postgres acceptance was proven live (below).
- **`test_ci_seeds_every_env_file_the_topology_requires` generalized + CI seed
  step gained `make .env.registration`.** The no-template decision (e5b-D-13) makes
  `.env.registration` the first generated, template-less env_file; the existing CI
  test asserted a `cp *.example` for *every* env_file, so it now branches on
  template presence and CI generates the file with its committed recipe. Required
  by the change list's own "no template ships", not a scope addition.
- **The E4 budget test kept intact; the lock-wait invariant added as a new test.**
  `test_the_gateway_registration_bound_never_preempts_intake` (E4-SPEC-17/18, a
  pinned test) is unchanged; the e5b sum-shape (eligibility + lock wait + margin ≤
  gateway bound) is a new sibling test, so no owner-pinned test was altered.
- **`.env.example` INTAKE_TIMEOUT invariant comment amended** to name the lock
  wait in the budget (8 + 5 + 1 = 14 ≤ 30) — part of the planned `.env.example`
  change; called out because the edit touched the neighbouring comment block.

No planned slice is absent from the diff. The gateway code diff is empty
(`git diff main -- services/gateway/` → nothing; `rg submission_id services/gateway/`
→ none): SPEC-5 is enforced by test alone (e5b-SPEC-5, verification 10).

Live-run evidence (isolation stated per the §1 evidence rule):
- **Verification 8 — real-Postgres `lock_timeout`** (e5b-SPEC-8; isolation: a
  throwaway `postgres:15` scratch container, no repo stack touched, removed after):
  the service's issued `SET LOCAL lock_timeout = '5000ms'` (for the default 5) is
  accepted and `SHOW lock_timeout` returns `5s`; the dropped-×1000 control `'5ms'`
  returns `5ms`. The s→ms conversion holds against real Postgres.
- **Verification 9 — negative break-then-revert** (§3 rule): reverting the v4
  validator (`if False`) reddens `test_format_check_boundary[*]` (3 fail); restore →
  green. Disabling the `touch()` re-mint reddens `page.test.tsx` fe-remint cases
  (2 fail: SPEC-14 edit + never-delivered); restore → green. Both files restored.
- **Verification 7 — boot-path regeneration** (e5b-SPEC-24; run 2026-08-13 at the
  impl-gate round-1 fix, isolation: the real `make up` target under
  `COMPOSE_PROJECT_NAME=e5bv7` — fresh project-scoped volume, engagement volume
  never mounted, removed with `down -v` after): `rm -f .env.registration && make up`
  → the recipe regenerated a real 64-hex key, intake `/healthz` 200 on the freshly
  seeded schema, `POST /intake` 201, byte-identical replay 201 same `patient_id`
  with a fresh eligibility `checked_at` (live re-verification visible).
- **Verifications 1–4, 10** green as recorded above. **`make eval` not run:**
  nothing under `eval/rag/` or the retrieval path changed.

`gate:` observations:
- **e5b-SPEC-26 (health break-then-revert):** the schema-guard suite is the
  automated half (`test_intake_schema_guard.py`: unreal key → 503 naming the
  variable; missing `registration_submissions` → 503 naming the table; real key +
  full schema → 200). The live break-then-revert on a running stack is deferred to
  the impl gate's live pass, isolation to be stated there.
- **e5b-SPEC-27 (harvest traceability audit):** performed at the impl gate against
  `~/Documents/Work/process-plans/e5b-restart/harvest.md`; observation recorded when
  the gate runs.

Residuals — filed at landing, registry IDs only (no restatement here):
- `docs/todo.md` **TODO-67** — the SPEC-11 non-correctable-422 residual, re-derived
  on `main` (TODO-62 stays a closed record; ids never reused, e5b-D-6).
- `docs/debt-log.md` "Intake contract break" residual-2 → **CLOSED (`e5b`)**; the
  register-first and verdict-persistence residuals stay open there (e5b-D-5).
- `docs/phi-logging-policy.md` register — the mechanism's new log surfaces, keyed
  fingerprint, and loggable-id rationale (REVIEWED 2026-08-13).
- `docs/runbook.md` — the key-rotation note (rotation invalidates recorded
  fingerprints; bounded, a straddling retry 409s).

Impl gate record — 2026-08-14, impl-gated fresh-context (round 2; round 1
2026-08-13 red with 3 findings, all dispositioned A). Branch
`feat/e5b-registration-idempotency` at `c2a0b7f`. Baseline observed by the gate
session's own runs: `make test-docker` **and** `.venv` py3.12 both
**1295 passed, 5 deselected, 1 xfailed** (branch-cut 1247 + 48; gaps unmoved);
frontend `npm test` 109 passed, `build`/`typecheck`/`lint` clean (pre-existing
DateField warning only).

`gate:` observations (both re-observed live this round):
- **e5b-SPEC-26 break-then-revert** — isolation: scratch compose project
  `e5bgate2` (postgres + intake-service only, project-scoped network and volume,
  removed with `down -v` after; the engagement stack was not running and its
  volume never mounted). Key half: real generated key + fresh seeded schema →
  `/healthz` 200; key emptied + container recreated → `/healthz` **and**
  `POST /intake` both 503
  `{"detail":"registration unavailable: REGISTRATION_FINGERPRINT_KEY not configured"}`,
  `registration_submissions` count 0 after (nothing written); key regenerated by
  the committed make recipe → `/healthz` 200, `POST /intake` 201
  (`patient_id` 1852), byte-identical replay → 201 same `patient_id`. Schema
  half: `DROP TABLE registration_submissions` → 503
  `{"detail":"registration schema incomplete: missing registration_submissions"}`
  (no PHI, no secret value); re-apply `db/schema.sql` → 200. Both transitions
  tracked both ways.
- **e5b-SPEC-27 harvest traceability audit** (fresh, against
  `~/Documents/Work/process-plans/e5b-restart/harvest.md`): r1 → e5b-SPEC-19 /
  e5b-D-9 named limit; r2 → e5b-REQ-2, SPEC-12/13/14, D-11; r3 f1 + r4 →
  e5b-D-5, SPEC-28/29, D4-residual-3 exclusion; r3 f2 → D-8/D-11 key-real
  predicate, SPEC-22; r5 → e5b-REQ-5, SPEC-24, D-13, the boot-path outcome
  test; r6 → SPEC-25 signal-only + the schema-apply/e6 exclusion + debt-log
  "No migration runner" (landed `b6c160b`); r7 f1/f1b → SPEC-23/25/26, D-14,
  the shared predicate; r7 f2 + r8 + r9 (undispositioned at close) → e5b-D-3 →
  named successor e7, excluded in Requirements and Spec. Residuals 1–8:
  1 → D-5/REQ-7 + exclusions; 2 → e7; 3 → D-9/SPEC-19; 4 → runbook rotation
  note (this branch); 5 → PHI-register row (this branch) + Landmines residual;
  6 → debt-log cross-cutting + SPEC-25 signal-only; 7 → debt-log seed row
  (landed `b6c160b`); 8 → the re-derived SPEC rows + TODO-67. **Nothing
  unmapped.**

Residuals accepted at this gate: exactly the plan Landmines block's named set
(e5b-D-3/5/6/7/8/9 shapes, the SPEC-25 signal-only scope, the real-Postgres
`lock_timeout` proof standing as the unit pin + the recorded verification-8
live run with no committed integration file) — nothing new accepted here.
Stamp means push-ready; push stays human-gated.
