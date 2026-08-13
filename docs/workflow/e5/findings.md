# e5 findings

> Round log for this item's three gated stages: the drift gate
> (`.claude/skills/drift-gate/`), the impl gate (`.claude/skills/impl-gate/`), and the
> `@codex-review` loop (owned by `.claude/skills/implementation/`). Each stage appends
> rounds under its own heading, created on that stage's first finding; the next-stage
> session fills the dispositions. Findings only — plan maturity lives in `plan.md`,
> delivery status in `pr-body.md`.

## Gate

### Round 1 — 2026-08-11

3 findings, no stamp.

| # | SPEC | Finding | Disposition (stage 3) |
|---|------|---------|-----------------------|
| 1 | E5-SPEC-21 | The zero-caller gate (`rg -n '\b_post\(\|\b_get\(' services/ frontend/ tests/ eval/` "returns nothing", §2 and verification step 4) is unsatisfiable as written: `tests/test_ai_visit_chat.py:172` defines an unrelated module-local `_post(` with ~30 call sites that match forever — the search needs scoping to the gateway helpers (e.g. `gw._post`/`gw._get` refs plus the gateway source), not a repo-wide name match | **Fixed, 2026-08-11.** Plan §2 and verification step 4 rewritten as two scoped searches: call sites in `services/gateway/` (the two `def` lines excluded — the deletion removes them), plus attribute/string references (`._post`/`._get`/`"_post"`/`"_get"`) across `services/ frontend/ tests/ eval/`. Re-measured this session: the only matches are the six monkeypatch lines §2 already removes; the visit-chat module-local `_post` no longer matches |
| 2 | E5-SPEC-8 | Plan context fact "13 of 17 `apiFetch` call sites already check status" is wrong twice: measured 10 of 17 check, and 13 checked + 5 unchecked ≠ 17 is internally inconsistent | **Fixed at source, 2026-08-11.** The figure was stage-1's; the requirements amendment (owner-approved, finding 3's disposition) corrected it to 10 of 17 and six unchecked reads, and the plan context now carries the corrected measurement (re-verified this session: 17 non-test `apiFetch` sites, 10 checking) |
| 3 | E5-SPEC-8 (E5-SPEC-5 class) | A sixth unchecked read of gateway-proxied results exists and is neither converted nor named as a residual: the records page chart read (`frontend/app/records/page.tsx:78`) checks no status and coerces `json.encounters ?? []`, so after `proxy_records` converts, an outage still renders "No records found for this patient." — outside the spec's four-surface enumeration, so disposition is the owner's (named residual, or spec change at stage 2) | **Accepted — spec change at stage 2, 2026-08-11.** Confirmed as stated. Owner chose coverage over residual. E5-SPEC-8 rewritten as universality over every portal read surface of gateway-proxied results (spec D-12); requirements §2, §4, D-8 corrected — six unchecked reads, not four, and 10 of 17 `apiFetch` sites check status, not 13 (which also closes finding 2's second half at its source). Two further stage-1 facts were wrong and are corrected in the same pass: the enumeration said "four" while listing five call sites, and §6 called four write surfaces "unchecked" when all four check `!r.ok`. Stage 3 must add the chart read and the slots panel to the plan's portal work and re-gate. *Stage 3 done 2026-08-11: the chart read is in the plan's §4 (a `chartFailed` state mirroring its sibling `loadRelevant`, cases extending `records/page.test.tsx`, live check in verification step 8); the slots panel was already converted in the plan and is now named as its own surface per amended E5-SPEC-8; the plan's decision ids renumbered (D-12..D-16 → D-13..D-17) to clear the spec amendment's D-12, and the former plan D-17 (slot-picker-inside-appointments interpretation) retired as superseded by it.* |

### Round 2 — 2026-08-11

1 finding, no stamp. Round-1 dispositions verified: the scoped zero-caller searches were re-run this session and return exactly the six monkeypatch lines the plan removes; the corrected counts (17 non-test `apiFetch` sites, 10 checking, six unchecked reads) were re-measured and hold; the chart read is in plan §4 with its test and live-check coverage. All 40 SPEC ids map both ways in the scope map; every sampled plan fact (gateway line numbers and helper signatures, portal call sites, eligibility budget arithmetic, interop statuses, registry line cites, PHI register row 94, TODO-62, migration numbering, fixture inventories) verified in-repo.

| # | SPEC | Finding | Disposition (stage 3) |
|---|------|---------|-----------------------|
| 1 | E5-SPEC-1..4 | The Landmines section records required human approval only for the ROI subset ("the zone is entered, so the change is human-gated") and the chunk-2 migration ("recorded human approval before any code"); but `docs/landmines.md` §1's intake-registration bullet approval-gates the **whole** thirteen-route migration ("migrating them is approval-gated and scheduled as `e5`"), and the spec marks E5-SPEC-1..4 ⚠ human-gate — the plan records no required owner approval for the ten non-ROI route conversions, so branch A could be implemented from this plan without securing it (e4's precedent recorded "owner approved" for exactly this class of change) | **Fixed, 2026-08-11.** The approval was already on record but the plan never carried it — the record is the chain of owner acts whose sole subject is this migration: e4 requirements D-3 (the estate conversion deferred to the named item `e5`), e5 requirements AGREED 2026-08-10 (E5-REQ-1 ⚠ human-gate; owner D-2..D-4 fix the mechanism), spec AGREED 2026-08-11 (E5-SPEC-1..4 ⚠ human-gate). Now carried in the plan twice, per the e4 precedent (`docs/workflow/e4/plan.md:41-43`): a Context paragraph ("Approval-gated zones deliberately touched, owner-approved before this stage") and a leading Landmines bullet covering all thirteen routes, with the ROI bullet noting the same approval covers its subset. No new approval was minted this session — the plan cites the existing recorded acts, which the re-gate can verify |

### Round 3 — 2026-08-11

2 findings, no stamp. **Round-3 rule engaged: the loop stops here and the owner decides each
finding** (accept as named residual, overrule, or spec change). Round-2's disposition verified:
the whole-conversion approval is carried in Context and a leading Landmines bullet, the
`docs/landmines.md` §1 `:87` quote and the e4 precedent (`docs/workflow/e4/plan.md:41-43`) both
resolve as cited. All 40 SPEC ids map both ways in the scope map; the out-of-scope section is
carried verbatim; every sampled plan fact re-verified in-repo this session (13 call-site lines
and both helper signatures, the two zero-caller searches returning exactly the six monkeypatch
lines §2 removes, the closed route enumeration against every `@app.` decorator, eligibility's
6s worst case vs intake's 8s, interop's 422/413, the six portal call sites and the `loadRelevant`
pattern, `buildIntakePayload`'s three current parameters, migration numbering 010, TODO-62 free,
PHI register row 94, compose-topology guards, D-16's test name, the no-outbound-call claim for
records/scheduling/roi/interop, drift-gate hash scope). Both findings are scope-map
cross-reference errors; the underlying planned work for the cited SPECs is present and sound.

| # | SPEC | Finding | Disposition (owner) |
|---|------|---------|---------------------|
| 1 | E5-SPEC-38, E5-SPEC-39 | Scope-map row cites "§12 negative tests over payload, log line and stored row", but §12 is the lock-wait bound (`REGISTRATION_LOCK_WAIT_SECONDS`); the PHI negative tests live in §13 — a reader tracing these two ⚠ PHI statements through the map lands on the wrong section | **Overruled by owner, 2026-08-11** — not a blocker; cite corrected at stage 3 anyway (scope-map row now points at §13) |
| 2 | E5-SPEC-19 | Scope-map row claims "§5 and the PR body name the outward-facing change", but §5's registry-upkeep table nowhere names the HL7 ingest change — the requirement is actually carried by the Landmines "PR-body lines required" bullet and verification step 9, so the §5 half of the cite is false | **Overruled by owner, 2026-08-11** — not a blocker; cite corrected at stage 3 anyway (scope-map row now names the Landmines PR-body bullet and verification step 9, not §5) |

### Round 4 — 2026-08-11

Clean — stamped. Full fresh re-run against the amended spec (E5-SPEC-8 universality) and
the round-3-revised plan. Round-3's two overruled findings verified corrected anyway
(scope-map cites now §13 and the Landmines PR-body bullet + verification step 9). All 40
SPEC ids map both ways; out-of-scope carried verbatim from requirements §6; every sampled
plan fact re-verified in-repo this session — the 13 call-site lines and both checked-helper
signatures, the route inventory closing to exactly 13 unconverted against the named
exclusions, both zero-caller searches returning only the six monkeypatch lines §2 removes,
the six unchecked portal reads and the `loadRelevant` tri-state pattern, the four write
surfaces checking `!r.ok` as the corrected §6 bullet states, eligibility 6s vs intake 8s vs
the gateway's 30s `INTAKE_TIMEOUT_SECONDS` default, interop's 422/413, success statuses
unmoved by conversion (`_post_checked` returns the body at the route's default 200 — pinned
by `tests/test_gateway_intake_proxy.py:108` — so downstream 201s on book/ROI-create change
nothing, E5-SPEC-13), migration numbering 010, TODO-62 free, PHI register line 94, all
fixture line cites, CI's `docker-build` needing both suite jobs. Residual-named SPECs
recorded in the stamp: E5-SPEC-30/31, E5-SPEC-33, E5-SPEC-34, E5-SPEC-40.

### Round 5 — 2026-08-11

1 finding. Owner-requested last look before branch B (chunk 2) implementation; chunk 1 is
merged (PR #74/#75), so this round re-verified the branch-B half of the stamped plan against
the frozen spec and today's `main`. All chunk-2 facts re-verified in-repo this session:
migrations run 001–009 so 010 is free; the contract's `request_fields.root` carries no
`submission_id` yet; `create_intake` commits at `:132` then match-key then eligibility exactly
as §11's pseudocode assumes, and the existing `SQLAlchemyError` → 503 "registration store
unavailable" branch (`app.py:191-200`) the plan maps the lock-timeout onto exists; the fixture
inventory holds (9 `IntakeRequest(` sites in `test_intake_schemas.py`, `test_redaction.py:85/:137`,
`test_intake_match_key.py:133`, `test_intake_db_error_phi.py:128`, `VALID_REQUEST`); the two
projection tests assert a PHI scan and named keys, not an exact key set; TODO-62 is still free
(max allocated TODO-61; chunk 1's pr-body explicitly reserved it); the confirmation screen
replaces the form with no "register another"; `test_the_gateway_registration_bound_never_preempts_intake`
and the two compose-topology guards resolve; out-of-scope still carried verbatim. Per-SPEC
verdicts for E5-SPEC-24..40: all satisfied or residual-named as the round-4 stamp records,
except the finding below. Implementation note, not a finding: branch B's baseline comparison is
now against chunk 1's landed count (1247 / 1 / 5, `pr-body.md`), not the plan's 969.

| # | SPEC | Finding | Disposition (stage 3) |
|---|------|---------|-----------------------|
| 1 | E5-SPEC-32, E5-SPEC-33 | Plan §11's bounded-wait template is internally inconsistent on units: `SET LOCAL lock_timeout = '<n>ms'` with "`n` an `int()`-coerced settings value", but the settings value (§12, D-15) is `registration_lock_wait_seconds` in **seconds** (default 5) — read literally the plan issues `lock_timeout = '5ms'`, a 1000× shorter bound than D-15 decided, under which a routine concurrent collision 503s instead of waiting and replaying. No planned check disambiguates: §13's unit test pins only that the statement is issued, and verification step 12's hold-past-the-bound case passes identically at 1ms and 1s. Stage 3 states the conversion (`int(seconds * 1000)`, or a `'<n>s'` template) and adds the value/units to the §13 pin | **Fixed, 2026-08-11.** Plan §11 now states `n = int(settings.registration_lock_wait_seconds * 1000)` with the seconds knob and the ms unit both named at the template, and the consequence of a dropped conversion spelled out; §13's dialect pin now asserts the issued value (`'5000ms'` at the 5s default), not merely issuance, so a dropped conversion reddens in the unit test. Plan header back to DRAFT (round-4 stamp superseded); re-gate is a full fresh-context re-run |

### Round 6 — 2026-08-11

Clean — stamped. Full fresh-context re-run of the round-5-revised plan against the frozen
spec. Round-5's disposition verified: §11's template now states the seconds→ms conversion
(`n = int(settings.registration_lock_wait_seconds * 1000)`) with both units named, and §13's
dialect pin asserts the issued value (`'5000ms'` at the 5s default), so §11, §12/D-15 and §13
agree on one bound. Branch A (E5-SPEC-1..23) verified against the delivered state rather than
re-litigated: the helpers are absent from the gateway source, `PROXY_TIMEOUT_SECONDS` sits at
`app.py:1281`, `tests/test_gateway_proxy_error_contract.py` exists, the chart read runs on
`chartFailed` with the never-empty comment, the registries read delivered (CLAUDE.md §4,
`docs/landmines.md` §1 `:86`), and the pr-body carries the outward-facing HL7 section
(E5-SPEC-19). Branch-B facts re-verified in-repo this session: migrations run 001–009 so 010
is free; `contracts/intake-registration.json` `request_fields.root` is still
demographics/insurance/consents with no `submission_id`; `create_intake` commits then
match-keys then verifies eligibility, with one flush/commit in `_create_registration` and the
`SQLAlchemyError` → 503 "registration store unavailable" branch at `app.py:191-200`;
eligibility's worst case (1+2)×2 = 6s vs intake's 8s holds in both `config.py` and
`.env.example`, and `REGISTRATION_LOCK_WAIT_SECONDS` exists nowhere yet; the two
compose-topology registration-bound guards resolve; the fixture inventory holds (9
`IntakeRequest(` sites in `test_intake_schemas.py`, `test_redaction.py:85/:137`,
`test_intake_match_key.py:133`, `test_intake_db_error_phi.py:128`, `VALID_REQUEST`, and
`test_gateway_intake_proxy.py`'s `PAYLOAD` a plain dict); the projection tests (`:108`,
`:130`) assert a PHI scan and structure, not an exact key set; `buildIntakePayload` takes
three arguments today; the confirmation screen replaces the form with no "register another";
`proxy_intake` hands `payload: dict` to `_post_checked` verbatim; TODO-62 is still free (max
allocated TODO-61; reserved by chunk 1's pr-body). All 40 SPEC ids map both ways in the scope
map; out-of-scope carried verbatim from requirements §6; the three authoring checks re-run
cold and hold. Per-SPEC: E5-SPEC-24..29, 32, 35..39 satisfied; E5-SPEC-30/31, E5-SPEC-33,
E5-SPEC-34, E5-SPEC-40 residual-named as the stamp records; E5-SPEC-1..23 accounted for by
merged chunk 1 (PR #74/#75).

### Round 7 — 2026-08-11

3 findings, no stamp. Invoked as `/drift-gate e5b`; there is no `docs/workflow/e5b/` — e5 is one
spec and one plan over two chunks (requirements D-1), so "e5b" reads as chunk 2 / branch B and
this is a full fresh-context re-run of the whole plan against the twice-amended spec
(E5-SPEC-1..43), not a chunk-scoped pass. All 43 SPEC ids map both ways in the scope map; every
planned change traces to a SPEC or to named registry upkeep; out-of-scope is still carried
verbatim from requirements §6 (located by heading — the requirements number it §6). Round-5 and
round-6 dispositions verified in place. Branch A (E5-SPEC-1..23) accounted for by merged chunk 1
(PR #74/#75) and not re-litigated. Facts re-verified in-repo this session: `010` is on this
branch and not on `main`, so D-19's "no environment has run it" holds (there is no migration
runner at all — CLAUDE.md §8); `_post_checked` relays a downstream 4xx status as-is with a plain
string `detail`, and the intake page sends every non-ok status except 400/422 to
`NOT_SAVED_SYSTEM` (`frontend/app/intake/page.tsx:106-115`), so the planned 409 lands in e4's
system-failure branch with no gateway or portal branch edit (E5-SPEC-42); `use_enum_values=True`
makes `req.consents` a list of plain strings, so D-19's "consents sorted" canonicalization is
well-defined; the payload is built from exactly `demo`/`ins`/`consents` plus the identifier, so
D-20's `touch()` seam covers every value that reaches the request; the existing
`SQLAlchemyError` → 503 "registration store unavailable" branch that D-15 maps `lock_not_available`
onto is `_create_registration`'s at `services/intake-service/app.py:317-326`; `intake-service` takes `env_file: .env` in
compose, so §12's "no compose edit is needed" holds for the new key too; TODO-62 is allocated to
exactly the residual the plan reserved it for (landed by this branch, not on `main`), so the
collision rule is satisfied. Per-SPEC: E5-SPEC-1..23 delivered; E5-SPEC-24..28, 31, 35..39, 43
satisfied; E5-SPEC-30, E5-SPEC-33, E5-SPEC-34, E5-SPEC-40 residual-named as before, plus the two
new residuals (fingerprint-key rotation, the fingerprint's PHI-derived keyed property) written in
Landmines; E5-SPEC-29, E5-SPEC-32, E5-SPEC-41, E5-SPEC-42 FINDING per the table below.

| # | SPEC | Finding | Disposition (stage 3) |
|---|------|---------|-----------------------|
| 1 | E5-SPEC-41 | D-19's fail-closed key guard reddens every existing `POST /intake` endpoint test and the plan does not say so. `_payload_fingerprint` runs unconditionally at the top of `create_intake`, `config.py` reads `os.getenv` at class-body time (so a post-import `monkeypatch.setenv` cannot reach it), and both `make test-docker` and CI's `tests` job run bare `pytest` with no `.env` — so `registration_fingerprint_key` is `""` and every 201-expecting case in `tests/test_intake_endpoint.py` (`:132, 158, 204`, …), `test_intake_match_key.py`, `test_intake_db_error_phi.py` and the existing `test_intake_idempotency.py` answers 503. §13 enumerates the fixture fallout of the *required `submission_id` field* and nothing else. The cheapest repair an implementer will reach for — a non-empty default in `config.py` — is exactly what D-19 forbids. Stage 3 names the fixture requirement and how it is set (patch `settings.registration_fingerprint_key` on the loaded module, not the environment) | **Addressed.** §13 gains "Fixture fallout of the fail-closed key": an autouse fixture patching `app_mod.settings.registration_fingerprint_key` (the loaded object — `from config import settings` makes it the same instance), one copy per affected module because each test file loads `config` under its own `sys.modules` name (`intake_config_ep` / `_mk` / `_idem`), so there is no shared object for `tests/conftest.py` to patch. Scoped down from the finding on one point, verified this session: the three modules that reach `create_intake` are `test_intake_endpoint.py` (7 sites), `test_intake_match_key.py` (16 direct `app_mod.create_intake` calls) and `test_intake_idempotency.py` (15); `test_intake_db_error_phi.py` calls `_create_registration` directly and never reaches the guard, so its four sites are fallout of §11's new third parameter, not of the key — recorded as such rather than given a fixture it does not need. Also named: the fail-closed test defeats the autouse fixture by resetting the key to `""` in its body; the fixture lands in the same commit as `_payload_fingerprint` or the TDD signal is meaningless; and §12 now carries the prohibition explicitly — the repair is never a non-empty default in `config.py` |
| 2 | E5-SPEC-29, E5-SPEC-32 | §7's DDL block drops the named unique constraint the collision path matches on. D-19 has 010 **amended in place**, so §7's block is what an implementer edits it to — but §7 spells `submission_id TEXT NOT NULL UNIQUE` (and `CREATE TABLE IF NOT EXISTS`), while the delivered `db/migrations/010_registration_submissions.sql` and `db/schema.sql:221-227` carry `CONSTRAINT uq_registration_submission_id UNIQUE (submission_id)` and `app.py::_is_submission_collision` matches that exact name (or the SQLite `registration_submissions.submission_id` spelling). Applied literally, Postgres names the constraint `registration_submissions_submission_id_key`, which matches neither string, so `_SubmissionAlreadyRecorded` is never raised and a routine concurrent collision answers 503 instead of replaying (E5-SPEC-32 fails, E5-SPEC-33's imprecise branch swallows it). Invisible to the SQLite unit tests, and caught only at live verification step 12. Stage 3 brings §7's DDL to the delivered text and adds the fingerprint column to it | **Addressed.** §7 now states the delivered text and marks the single edit as the `payload_fingerprint` line: the migration block carries `CONSTRAINT uq_registration_submission_id UNIQUE (submission_id)` and plain `CREATE TABLE`, and `db/schema.sql:221-227` is described in its own idiom (`CREATE TABLE IF NOT EXISTS`, aligned columns) rather than collapsed into one block that fits neither file. A paragraph above it names why the constraint name is load-bearing, citing `app.py:193-199` (`_SUBMISSION_CONSTRAINT` / `_SUBMISSION_COLUMN`) and the exact failure — Postgres would name an inline UNIQUE `registration_submissions_submission_id_key`, matching neither string. Beyond the finding: §13 gains a structural pin (both DDL files carry the exact `_SUBMISSION_CONSTRAINT` string and neither spells the constraint inline), so the SQLite-invisible drift reddens in the fast suite instead of waiting for live step 12, and step 12 gains the matching break-then-revert negative |
| 3 | E5-SPEC-41, E5-SPEC-42, E5-SPEC-43 | D-13, the decision that fixes the branch split, still reads "branch B is E5-SPEC-24..40" — the three ids the second spec amendment added are chunk-2 work, planned into §7/§9/§11/§13 under **Branch B**, and named nowhere in the decision that defines what branch B carries. Stage 3 extends the range | **Addressed.** D-13's branch-B range reads E5-SPEC-24..43, with a dated parenthetical recording why it moved (the spec's second amendment appended E5-SPEC-41/42/43 as chunk-2 work). Branch A's range is unchanged |

### Round 8 — 2026-08-11

2 findings, no stamp. Invoked as `/drift-gate e5b`; there is still no `docs/workflow/e5b/` — e5
is one spec and one plan over two chunks (requirements D-1), so this is a full fresh-context
re-run of the whole plan against the twice-amended spec (E5-SPEC-1..43). All 43 SPEC ids map
both ways in the scope map; every planned change traces to a SPEC id or to named registry
upkeep; the out-of-scope section is carried verbatim from requirements §6 (located by heading;
requirements number it §6 — the only diff against the source is one trailing blank line).
Round-7's three dispositions verified in place: §7 now carries the delivered DDL with
`CONSTRAINT uq_registration_submission_id UNIQUE (submission_id)` and plain `CREATE TABLE`,
`db/schema.sql:221-227` is described in its own `CREATE TABLE IF NOT EXISTS` idiom, and both
resolve as cited; §12/§13 carry the fail-closed fixture fallout and the no-default prohibition;
D-13's branch-B range reads E5-SPEC-24..43. The three authoring checks re-run cold and hold.

Facts re-verified in-repo this session: `_SUBMISSION_CONSTRAINT` / `_SUBMISSION_COLUMN` /
`_is_submission_collision` at `services/intake-service/app.py:193-199`; `create_intake`'s
delivered shape matches §11's pseudocode (log line, `_find_registration`, `_create_registration`
→ `_SubmissionAlreadyRecorded` → `_require_registration`, `_evaluate_match_key` on the create
arm only, then `_verify_eligibility_guarded`), and `_create_registration`'s `SQLAlchemyError` →
503 "registration store unavailable" branch is at `:317-326`; `config.py` reads `os.getenv` in
the class body and carries `registration_lock_wait_seconds` but no fingerprint key; `.env.example`
carries `REGISTRATION_LOCK_WAIT_SECONDS=5` and no fingerprint key; `Makefile:78-81` and
`.github/workflows/ci.yml:91` both run bare `pytest -m "not integration" -q` with no `.env` and
nothing loads one, so §12's fail-closed reddening is real; the three modules that reach
`create_intake` load `config` under `intake_config_ep` / `_mk` / `_idem` as §13 states, with 7 /
16 / 15 sites respectively, and `test_intake_db_error_phi.py` (`intake_config_dberr`) has exactly
4 direct `_create_registration` calls that never reach the guard; `test_no_code_path_expires_or_prunes_a_submission_record`
exists (`test_intake_idempotency.py:517`) as the style reference for the new DDL pin;
`Demographics.dob` is `Optional[str]` and `use_enum_values=True` makes `consents` plain strings,
so D-19's `json.dumps(model_dump)` canonicalization is well-defined; `_post_checked` relays a
downstream status as-is and `frontend/app/api/intake/route.ts` proxies through, so the planned
409 reaches the portal's non-400/422 arm (`page.tsx:110-111`) with no branch edit; TODO-62 is
allocated to exactly the residual the plan reserved it for. Not flagged, consistent with rounds
6–7: line cites inside text describing *delivered* work (branch A's thirteen gateway call sites,
§13's `IntakeRequest(` fixture inventory) have moved with the work that landed, and verification
step 16's `969 passed` baseline is stale against chunk 1's landed 1247 and this branch's 1276 —
round 5 already recorded that as an implementation note rather than a finding.

Per-SPEC: E5-SPEC-1..23 delivered (chunk 1, PR #74/#75); E5-SPEC-24..29, 32, 35..37, 39, 41, 42,
43 satisfied; E5-SPEC-30/31, E5-SPEC-33, E5-SPEC-34 residual-named as the round-6 stamp records,
plus the two D-19 residuals (key rotation invalidates fingerprints, the fingerprint is PHI-derived
and must stay keyed) written in Landmines; E5-SPEC-38 and E5-SPEC-40 FINDING per the table below
(E5-SPEC-40 also stays residual-named, TODO-62).

| # | SPEC | Finding | Disposition (stage 3) |
|---|------|---------|-----------------------|
| 1 | E5-SPEC-38, E5-SPEC-40 | §11's `submission_id_well_formed` block still returns `str(UUID(v))` with no version check, and its prose says canonicalizing "rejects anything else" — but review round 1 landed a `parsed.version != 4` rejection (`services/intake-service/schemas.py:107-109`, commit `a1cf9bb`), the contract now words the field as "a client-generated UUIDv4" (`contracts/intake-registration.json:2`), and 7 tests pin it. Nothing in the plan records the constraint: D-17 says "UUIDv4" only of the portal's mint, §13's test inventory and Files-touched carry none of the round-1 cases, and the code block as written is the pre-fix validator — followed literally it reverts a shipped review fix, and an impl-gate diff-vs-plan pass finds the v4 check traceable to no plan text | **Addressed.** New plan decision **D-21** records the constraint, its reason (nil / v1 / v5 are the identifiers a caller reaches by accident; one identifier across two patients replays the FIRST chart, E5-SPEC-36; a `name\|dob\|ssn` v5 puts derived bits in the log projection, the response and a stored column — confirmed live at review round 1, `a1cf9bb`) and its **named limit** (a version check is self-report, not proof of randomness — a constant or hash-stamped v4 passes, so E5-SPEC-38's guarantee stays at the portal's mint). §11's block now carries `parsed = UUID(v)` / `parsed.version != 4` / `return str(parsed)`, and its prose states both properties separately — canonicalization for E5-SPEC-40, the version check for E5-SPEC-38 — instead of "rejects anything else". §13 gains "The v4 constraint is pinned at both levels" inventorying all seven cases (three schema parametrize cases, the canonicalization case that pins the narrowing did not cost E5-SPEC-40, three endpoint parametrize cases). Scope-map rows for E5-SPEC-38/39 and E5-SPEC-40 cite §11 and D-21; Files touched names the schemas change, the two test files and the `docs/phi-logging-policy.md` row (a branch-B row it was missing entirely). Verification step 14 gains the v5 case with a break-then-revert negative. Landmines gains the limit as an accepted residual |
| 2 | E5-SPEC-41, E5-SPEC-43 | Two cites inside text describing *remaining* work do not resolve: §13's fingerprint-key fixture paragraph says `tests/test_intake_idempotency.py` "already binds `config_mod` at `:47`" (it is `:46`; `:47` is `db_mod`), and §9's re-mint reasoning cites the confirmation screen as `page.tsx:159-231` (it is `:170-242`). Both moved when this branch's own delivered chunk-2 code shifted the files, and both are load-bearing for the reader — the first names the object the autouse fixture patches, the second is the evidence for D-20's "a success cannot be edited-and-resubmitted from the same mount" | **Addressed.** Both corrected and re-read this session: §13 says `config_mod` at `:46`, and §9 says `page.tsx:170-242`, with "the `result?.ok` early return" added so the cite is checkable by shape and not only by number. Beyond the finding, one more cite in the same neighbourhood was re-verified and tightened — D-19's portal system-failure branch reads `page.tsx:110-111` (the `rejected` const and the `setResult`), not `:110-112` |

### Round 9 — 2026-08-11

Clean — stamped. Invoked as `/drift-gate e5b`; as in rounds 7–8, no `docs/workflow/e5b/`
exists — this is a full fresh-context re-run of the whole plan against the twice-amended spec
(E5-SPEC-1..43). Round-8's two dispositions verified in place: D-21 exists with its named limit,
§11's validator block carries `parsed.version != 4` (delivered, `services/intake-service/schemas.py`,
`a1cf9bb`), §13 inventories the seven v4 cases, the E5-SPEC-38/39 and E5-SPEC-40 scope-map rows
cite §11 and D-21, Files touched and verification step 14 (v5 break-then-revert) carry them, and
the Landmines residual records the limit; both corrected cites resolve (`config_mod` at
`test_intake_idempotency.py:46`; the confirmation screen at `page.tsx:170-242` with the
`result?.ok` early return at `:170` and the block closing at `:242`). Round-7's three
dispositions still hold (§7's DDL is the delivered named-constraint text, D-13's branch-B range
reads E5-SPEC-24..43, §12/§13 carry the fail-closed fixture fallout).

All 43 SPEC ids map both ways in the scope map; every planned change traces to a SPEC id or
named registry upkeep; out-of-scope carried verbatim from requirements §6 (one trailing blank
line, as round 8 recorded). The three authoring checks re-run cold and hold — gate interaction's
CI claim re-verified (`docker-build` needs both `tests` and `frontend`). Facts re-verified
in-repo this session: `_SUBMISSION_CONSTRAINT`/`_SUBMISSION_COLUMN` and the named constraint in
both DDL files (fingerprint column still the one planned edit); 010 absent from `main`, so
D-19's amend-in-place premise holds; `config.py` carries `registration_lock_wait_seconds` and no
fingerprint key, `.env.example` `REGISTRATION_LOCK_WAIT_SECONDS=5` and no fingerprint key;
`Makefile` and CI's `tests` job run bare `pytest` with no `.env`, so §12's fail-closed reddening
is real; the three modules load `config` as `intake_config_ep`/`_mk`/`_idem` with 7 / 16 / 15
sites and `test_intake_db_error_phi.py` has exactly 4 direct `_create_registration` calls;
`from config import settings` makes the autouse fixture's patch reach the loaded instance;
`buildIntakePayload` takes the identifier as its fourth argument and `page.tsx:47` mints once
per mount; the portal's non-400/422 arm (`page.tsx:110-111`) renders the system-failure branch,
so the planned 409 lands with no branch edit; eligibility's (1+2)×2 = 6s vs intake's 8s;
compose-topology's two bound guards parametrized over both keys; the PHI register's gateway row
FIXED and its intake row carrying `submission_id` with the D-21 boundary account; TODO-62
allocated to exactly the reserved residual; branch A's delivered state (helpers absent,
`PROXY_TIMEOUT_SECONDS` at `app.py:1281`, `tests/test_gateway_proxy_error_contract.py` present).

Per-SPEC: E5-SPEC-1..23 delivered (chunk 1, PR #74/#75); E5-SPEC-24..29, 32, 35..37, 39, 42, 43
satisfied; E5-SPEC-30/31, E5-SPEC-33, E5-SPEC-34, E5-SPEC-38, E5-SPEC-40, E5-SPEC-41
residual-named as the stamp records. Implementation notes, not findings (delivered-text drift,
per the rounds-5–8 convention): the intake module docstring (`app.py:38`) cites
"E5-SPEC-24..40" from before the second amendment and will understate the range once the
D-19/D-20 work lands in that file; `test_intake_schemas.py` now has 11 `IntakeRequest(` sites
against §13's 9 (review round 1's landed cases); verification step 16's `969` baseline remains
stale against the branch's landed counts.

## Impl gate

### Round 1 — 2026-08-12

2 findings, no stamp. First impl-gate finding of this item — the 2026-08-11 gate at HEAD
`60a77a8` was clean and stamped, so this section is new. Full fresh-context re-run over the whole
branch diff (`main...HEAD`, 11 commits: the 7 pushed to PR #76 plus the four-commit round-2
revision), against the twice-amended spec (E5-SPEC-1..43) and the round-9 GATED plan.

Re-run this session, not accepted from the implementation record: `make test-docker` →
**1290 passed, 1 xfailed, 5 deselected**, matching `pr-body.md`'s table exactly and leaving the
xfail and the five deselected unmoved, so no deliberate coverage gap moved; `cd frontend &&
npm test` → **110 passed**; `make eval` green; CI's `secret-scan` command run against a
`git archive HEAD` export (the tracked tree, as CI sees it — scanning the working tree instead
reports 181 local-only hits from `.env`, `logs/` and `node_modules/`) → **no leaks**, so the new
non-empty `.env.example` placeholder does not redden that job.

Diff closes both ways: every one of the 24 changed files traces to plan §7–§13 or to named
registry upkeep, and nothing planned is absent. All twenty chunk-2 SPEC ids (E5-SPEC-24..43) are
cited by name in `tests/` or `frontend/app/`, and the tests assert behaviour rather than
execution — spot-checked on the mismatch parametrize (counts and stored row unchanged, the
changed value absent from the response and from the WARNING-and-above records), the fail-closed
pair (fresh and recorded identifiers alike, the autouse key fixture defeated in-body), the keyed
property (two keys, two digests), and the collision loser (a real `IntegrityError` raised by
blinding the first lookup, not a faked exception). Planted defects verified untouched:
`_evaluate_match_key` is unchanged and still runs on the create arm only (D5), the new
constraint-backed index is on the new table and no existing table gains one (D8), no
`audit_logs` writer appears (D2), no scheduling code is touched (D5b/RIV-175), no D11 surface
moves. Idiom sweep clean: no gateway route changed, every new log site is class-only or a
constant with `patient_id` (permitted by `docs/phi-logging-policy.md:28`, and the same value
`app.py:191` already logs), no `Co-Authored-By` trailer in the eleven commits. Landmine §1 zones
entered — migrations/schema, a PHI-derived stored column, a new secret — each carry a recorded
owner act (`pr-body.md` Risk & landmines; spec D-18's E5-SPEC-41 ⚠ human-gate note). Carried
forward, not re-flagged: `CLAUDE.md` §6's baseline still reads the pre-chunk-1 `969 / 1 / 5`,
deliberately left for the owner since chunk 1's own delivery record set the newer number.

| # | SPEC | Finding | Disposition (stage 4) |
|---|------|---------|-----------------------|
| 1 | E5-SPEC-41 | The shipped rotation pointer for the new secret does not resolve. `.env.example:105` tells the operator to rotate `REGISTRATION_FINGERPRINT_KEY` "per `docs/runbook.md` before any deployment that matters, alongside the other secrets there", and `pr-body.md` repeats it ("the placeholder is marked change-me alongside the other rotatable secrets in `docs/runbook.md`") — but `docs/runbook.md` carries no `.env` secret-rotation procedure and no list of rotatable secrets at all; its only credential content is the `.env.redis` regeneration block (`:145-163`), a different file. The enumerated rotation checklist is `docs/debt-log.md:314` (Remediation runbook step 1: `SESSION_SECRET`, `DB_PASSWORD`, `PAYER_API_KEY`, `BEDROCK_API_KEY`, HL7 feed credentials), and the new key appears in neither list. This is the class `CLAUDE.md` §8 records as a live gap — a wrong pointer inside a human-run, irreversible secret procedure — and it is the only `docs/runbook.md` cite in `.env.example`, so the idiom it claims to follow does not exist either | **Fixed, 2026-08-12.** Confirmed as stated. The pointer is dropped rather than redirected: `docs/debt-log.md:314` is scoped to the credentials that reached git history and says to enumerate them from the committed blob (`git show b9364ca:.env`), and this key has never been committed, so adding it there would file a never-leaked secret in a leak-remediation checklist. The `.env.example` comment is now self-contained and matches the house idiom — no other secret in that file carries a doc pointer: the value is named a placeholder, every deployment mints its own "as `DB_PASSWORD` and `SESSION_SECRET` above do", and the exclusion from step 1 is stated with its reason so the next reader does not re-open the question. The `pr-body.md` "A new secret" bullet carries the same correction and records that the earlier cite resolved to nothing. Plan D-19/§12 asked only for the fail-closed behaviour and the rotation cost in that comment — both were and are there; the runbook cite was unplanned text, and removing it returns the comment to planned scope |
| 2 | E5-SPEC-29, E5-SPEC-32 | `pr-body.md` deviation 3 is false against the GATED plan. It records "the unique constraint is named … rather than left implicit. The plan's DDL wrote `TEXT NOT NULL UNIQUE`" — true of the plan as it stood at the first push, but gate round 7 corrected §7 to carry `CONSTRAINT uq_registration_submission_id UNIQUE (submission_id)` plus a paragraph naming the inline spelling as the failure mode to avoid, and the round-9 stamp is on that text. So the code and the plan agree and the delivery record says they diverge — a reader checking the one entry that touches the collision path's load-bearing string is told the wrong thing about which document decided it | **Fixed, 2026-08-12.** Confirmed as stated: plan §7 carries `CONSTRAINT uq_registration_submission_id UNIQUE (submission_id)` plus the paragraph naming the inline spelling as the failure to avoid, corrected at gate round 7 and stamped at round 9. The entry is restated rather than deleted — the name genuinely landed ahead of the plan, and two later deviations cite this list by number, so renumbering would break them. It now says the plan has since caught up, cites `findings.md` §Gate round 7 finding 2 as what moved it, and marks itself as a record rather than an open divergence. No code change: the constraint name, the matcher and both DDL files were already in agreement |

### Round 2 — 2026-08-12

1 finding, no stamp. Full fresh-context re-run over the whole branch diff
(`main...HEAD`, 12 commits — the 11 gated at round 1 plus `c9248d1`, the round-1 finding-1
fix), against the twice-amended spec (E5-SPEC-1..43) and the round-9 GATED plan. Round-1's
two dispositions verified in place: `.env.example` carries no `docs/runbook.md` cite at all
now and the comment is self-contained on the placeholder, the exclusion and the rotation cost
(finding 1); `pr-body.md` deviation 3 now reads as a record with the gate-round-7 correction
cited rather than as an open divergence, and plan §7 does carry
`CONSTRAINT uq_registration_submission_id UNIQUE (submission_id)` (finding 2).

Re-run this session, not accepted from the implementation record: `make test-docker` →
**1290 passed, 1 xfailed, 5 deselected**, matching `pr-body.md`'s table exactly and leaving
the xfail and the five deselected unmoved, so no deliberate coverage gap moved; `cd frontend
&& npm test` → **110 passed** (`app/intake/page.test.tsx` 20); `make eval` green.

Diff closes both ways: all 24 changed files trace to plan §7–§13 or to named registry upkeep,
and nothing planned is absent — `c9248d1` touches only the `.env.example` comment §12/D-19
already owns. All twenty chunk-2 SPEC ids (E5-SPEC-24..43) are cited by name in `tests/` or
`frontend/app/`, asserting behaviour rather than execution — re-spot-checked on the mismatch
parametrize (counts and stored row unchanged, changed value absent from response and from the
WARNING-and-above records), the fail-closed pair (the autouse key fixture defeated in-body for
fresh and recorded identifiers alike), the keyed property (two keys → two digests), and the
collision loser (a real re-read blinded on the first lookup, not a faked exception). The
portal re-mint funnel is closed at the source: every `setDemo`/`setIns`/`setConsents` in
`frontend/app/intake/page.tsx` appears only in its `useState` declaration and inside `touch()`,
so no field edit bypasses the re-mint (E5-SPEC-43). Planted defects verified untouched:
`_evaluate_match_key` unchanged and still on the create arm only (D5), the constraint-backed
index on the new table only (D8), no `audit_logs` writer (D2), no scheduling code touched
(D5b/RIV-175), no D11 surface moved. Idiom sweep clean: no gateway route changed, no `str(e)`
or PHI-bearing field on any touched path (the new sites are class-only, a constant, or carry
`patient_id`, permitted by `docs/phi-logging-policy.md:28`), no `Co-Authored-By` trailer in the
twelve commits. Landmine §1 zones entered — migrations/schema, a PHI-derived stored column, a
new secret — each carry a recorded owner act. Carried forward, not re-flagged: `CLAUDE.md` §6's
baseline still reads the pre-chunk-1 `969 / 1 / 5`, deliberately left for the owner.
Implementation notes, not findings (delivered-text drift, per the rounds-5–8 convention):
`tests/test_intake_idempotency.py:1` still scopes the module "(E5-SPEC-24 … E5-SPEC-40)" though
it now carries the E5-SPEC-41/42/43 cases — the same drift round 1 noted at `app.py:38`, which
this branch has since corrected; plan verification step 16's `969` baseline remains stale
against the branch's landed counts.

| # | SPEC | Finding | Disposition (stage 4) |
|---|------|---------|-----------------------|
| 1 | E5-SPEC-32, E5-SPEC-29 | Plan verification step 12's negative check is neither evidenced nor recorded as skipped, while `pr-body.md` marks step 12 ✅. Gate round 7 added it to the GATED plan in the same motion as the §13 DDL-name pin (`findings.md` §Gate round 7 finding 2 disposition: "step 12 gains the matching break-then-revert negative"), and plan `:987-990` reads: in a scratch database, recreate the table with `submission_id TEXT NOT NULL UNIQUE` instead of the named constraint and re-run the two-caller case — the loser answers 503 rather than replaying. The `pr-body.md` step 12 row records only the positive half (two simultaneous POSTs → one chart; `REGISTRATION_LOCK_WAIT_SECONDS=1` → 503 in 1.06s), text that predates the round-7 revision, and the r2 session re-drove step 13b live without returning to it. What did land is the §13 structural pin's own break-then-revert at the test level, and only against `db/schema.sql` (Test-first table, r2 row 6) — that pins the *string* in one of the two DDL files; it does not exercise the runtime consequence the step-12 negative exists to demonstrate, which is the whole premise the constraint name is called load-bearing on. Neither Deviations nor "Planned work absent from the diff" says it was traded for the cheaper check | **Fixed, 2026-08-12 — by running the check, not by recording it away.** Confirmed as stated: the step-12 row carried only the positive half, and the r2 session never returned to the negative gate round 7 added. Run this session against real Postgres. Scratch database `riverbend_scratch` created in the dev container, `db/schema.sql` loaded, `registration_submissions` dropped and recreated with the inline `submission_id TEXT NOT NULL UNIQUE` (Postgres names it `registration_submissions_submission_id_key` — matching neither `_SUBMISSION_CONSTRAINT` nor the SQLite `_SUBMISSION_COLUMN` spelling, confirmed in `pg_constraint`), and an intake-service instance pointed at it (`docker compose run --use-aliases -e DB_NAME=riverbend_scratch`, the real one stopped so compose DNS resolved to the scratch instance; the dev database was never pointed at). Two simultaneous POSTs carrying one identifier → **loser `503 registration store unavailable`, winner `201`**, log line `failed to create registration (IntegrityError)`: the collision fell through `_is_submission_collision` into the generic store-unavailable branch instead of replaying — E5-SPEC-32 broken and E5-SPEC-33's imprecise branch swallowing the evidence, which is the runtime consequence the §13 DDL-name pin stands in for and the premise the name is called load-bearing on. **Reverted in place** (`DROP CONSTRAINT` → `ADD CONSTRAINT uq_registration_submission_id UNIQUE (submission_id)`) and the same harness re-run: **both callers `201`, same `patient_id`, one chart, one submission row** — so the negative isolates the constraint name, not the harness. Scratch database dropped; `riverbend` verified untouched (0 rows from the run, named constraint intact). No code change: the constraint name, its matcher and both DDL files were already in agreement, so this was an evidence gap in the delivery record, not a defect. `pr-body.md` step 12 now carries both halves. Delivered-text drift corrected alongside (this round's implementation note, not a finding): `tests/test_intake_idempotency.py`'s module docstring read "E5-SPEC-24 … E5-SPEC-40" while carrying the E5-SPEC-41/42/43 cases — now `… E5-SPEC-43`, with the content-match qualification stated. Plan verification step 16's stale `969` is left alone: the plan is GATED and stage 4 does not edit it, and `pr-body.md` already records the baseline provenance |

### Round 3 — 2026-08-12

1 finding, no stamp. **Round-3 rule engaged: the loop stops here and the owner decides**
(accept as a named residual, overrule, or back to stage 4). Full fresh-context re-run over
the whole branch diff (`main...HEAD`, 13 commits — the 12 gated at round 2 plus `547493f`,
the round-2 docstring correction), against the twice-amended spec (E5-SPEC-1..43) and the
round-9 GATED plan. Round-2's disposition verified in place: `pr-body.md` step 12 carries
both halves of the negative (inline-UNIQUE loser 503s, named-constraint re-run replays), and
`tests/test_intake_idempotency.py:1` reads `… E5-SPEC-43` with the content-match
qualification (`547493f`).

Re-run this session, not accepted from the implementation record: `make test-docker` →
**1290 passed, 1 xfailed, 5 deselected**, xfail and deselected unmoved so no deliberate
coverage gap moved; `cd frontend && npm test` → **110 passed** (`app/intake/page.test.tsx`
20); `make eval` green.

Diff closes both ways: all 24 changed files trace to plan §7–§13 or named registry upkeep
(`547493f` touches only the docstring §13's inventory already owns), and nothing planned is
absent. All twenty chunk-2 SPEC ids cited by name in `tests/` or `frontend/app/`, asserting
behaviour — re-spot-checked on the mismatch parametrize (counts and stored row unchanged,
changed value absent from response and WARNING-and-above records), the fail-closed pair
(autouse fixture defeated in-body, fresh and recorded alike), the keyed property (two keys →
two digests), the collision loser (first lookup blinded, real `IntegrityError`), the DDL-name
and fingerprint-column pins over both files, and the E5-SPEC-34 retention scan. The re-mint
funnel is closed at the source: `setDemo`/`setIns`/`setConsents`/`setSubmissionId` appear
only in their `useState` declarations and inside `touch()`. Planted defects untouched:
`_evaluate_match_key` unchanged on the create arm only (D5), the constraint-backed index on
the new table only (D8), no `audit_logs` writer (D2), no scheduling code (D5b/RIV-175), no
gateway route and no D11 surface moved. Idiom sweep clean: no `str(e)` or PHI-bearing field
on any touched log path, no `Co-Authored-By` trailer in the thirteen commits. Landmine §1
zones entered (migrations/schema, PHI-derived stored column, new secret) each carry a
recorded owner act. Carried forward, not re-flagged: `CLAUDE.md` §6's baseline still reads
the pre-chunk-1 `969 / 1 / 5`, deliberately left for the owner; plan verification step 16's
stale `969` (plan is GATED, stage 4 does not edit it).

| # | SPEC | Finding | Disposition (owner) |
|---|------|---------|---------------------|
| 1 | — | `pr-body.md`'s baseline table over-counts one row and no longer sums: the r2 row "mismatch ×3, lost-response-then-edit, reordered-consents replay, collision-loser mismatch" claims **+7** while enumerating six cases, so the rows total 1291 against the stated and measured 1290. Measured this session: `test_intake_idempotency.py` collected 21 cases at `a1cf9bb` (review r2's recorded 1276) and 35 at HEAD, +14 = the r2 delta exactly (6 + 4 fail-closed/keyed/stored-digest + 4 DDL pins), and no other file gained a test function since `a1cf9bb`. The totals are right and re-verified; the composition a reader audits the load-bearing count against is wrong by one in one cell (+7 → +6) | **Owner, 2026-08-12: fix in the gate session and push.** One cell corrected (`pr-body.md` +7 → +6; rows now sum 1276+6+4+4 = 1290, matching the measured total). No code, plan or spec touched; the fresh re-gate is waived by this decision and recorded here per the round-3 rule |

## Review

> PR #76, `@codex-review` by JesterCharles. Chunk 2 (branch B) only — chunk 1's review
> loop is on PR #74 and is closed.

### Round 1 — 2026-08-11

1 finding.

| # | SPEC | Finding | Disposition (A/B/C/E) |
|---|------|---------|-----------------------|
| 1 | E5-SPEC-38, E5-SPEC-40 | [high] `submission_id` accepts any well-formed UUID, not only a random one (`services/intake-service/schemas.py:77-90`): the nil UUID, a v1 and a v5 all canonicalize through `UUID(v)` and pass. A constant key across two patients replays the first patient's `patient_id`; a v5 derived from patient fields also undermines the "derived from no submitted value" claim | **A — fixed, with the claim scoped down.** Observation confirmed at runtime before the fix: a v5 built from `name\|dob\|ssn` registered `201` and its derived value landed in the `POST /intake meta=` log line. The validator now requires `parsed.version == 4`; canonicalization is unchanged. Live against the rebuilt service: nil / v1 / v5 → `422` with zero rows written, a v4 pair → `201` `patient_id=1868` twice with one `registration_submissions` row. **The reviewer's framing is not adopted in full**: a version check does not close the constant-key hole it is credited with — `11111111-1111-4111-8111-111111111111` is a valid v4 — and cannot prove non-derivation either, since v4 bits can be stamped on any hash. What it closes is the *accidental* class (an uninitialized field serializes to the nil UUID; a "make the key deterministic" change produces a v5), which is the class worth closing at a boundary. The randomness guarantee stays where it always was — the portal's mint — and both the validator docstring and the PHI register now say so rather than implying the boundary proves it. Tests: 3 schema-level rejection cases + 1 canonicalization-survives case (`tests/test_intake_schemas.py`), 3 endpoint cases proving nothing is written (`tests/test_intake_idempotency.py`); all 7 red before the one-line version check, green after |

### Round 2 — 2026-08-11

1 finding.

| # | SPEC | Finding | Disposition (A/B/C/E) |
|---|------|---------|-----------------------|
| 1 | E5-SPEC-30 (as then written) | [high] Replay is keyed only on `submission_id`, never on what was submitted (`services/intake-service/app.py:143-145`): the form reuses the identifier across failures, so first-POST-commits → lost response → operator corrects a typo'd DOB or member id → resubmit returns `201` for the *original* chart and silently drops the edits — the desk sees confirmation while the stored record holds wrong PHI/coverage. Recommends a keyed-HMAC payload fingerprint compared on replay, generic 409 on mismatch, plus same-key/different-payload tests | **A — accepted; structural, routed through stage 2 and 3 rather than patched mid-review.** Confirmed at runtime before any decision: same v4 identifier, first POST (`dob 1985-03-12`, `member_id EXMP000201`) → `201 patient_id=1869`; edited retry (`dob 1985-03-21`, `member_id EXMP000999`) → `201 patient_id=1869` in 0.03s, and `SELECT dob, member_id` returned the originals — the edit was dropped while confirmed. Worse than reported: the replay re-runs eligibility on the *request's* insurance, so the response echoed the edited `member_id` in its eligibility block, actively confirming content that was not saved. The code implemented E5-SPEC-30 as written — the defect is the spec's, decided for identical-content retries (requirements D-5) and never weighed against the edit-after-failure case — so the fix could not land under the frozen spec, and the fingerprint is new persisted state, the skill's structural trigger. Owner decision 2026-08-11 (spec D-18, amendment 2): E5-SPEC-30 qualified on content; E5-SPEC-41 (keyed non-reversible fingerprint recorded in-transaction), E5-SPEC-42 (mismatch → failure in the system-failure branch, nothing written or modified), E5-SPEC-43 (the portal re-mints on the first edit after a non-success submit — the operator-facing resolution; the 409 is defense in depth for non-portal callers, and codex's fix alone would have trapped the operator in a 409 loop, since the form would keep resubmitting the same identifier). Plan revised (D-19 fingerprint mechanism incl. fail-closed key and the collision-loser comparison, D-20 re-mint mechanism), header back to DRAFT, re-gated fresh-context before implementation. **Implemented 2026-08-12** on the same branch: `payload_fingerprint` in migration 010 / `db/schema.sql` / the model, `_payload_fingerprint` (HMAC-SHA256, fail-closed on an unset `REGISTRATION_FINGERPRINT_KEY`) computed before the replay lookup, `_match_or_conflict` on `hmac.compare_digest` for both the sequential replay and the collision loser, and the portal's `touch()` re-mint on the first edit after an unconfirmed submit. +14 tests (suite 1290/1/5), +4 frontend (110). Live: the reported scenario now answers 409 with `SELECT dob, member_id` returning the originals, a byte-identical retry still replays, the portal posts a different identifier after an edit, and an unset key answers 503 for fresh and recorded identifiers alike |

### Round 3 — 2026-08-12

2 findings. **Round-3 rule fired** (`.claude/skills/implementation/`): a third round with open
findings stopped the loop and both dispositions were taken by the owner, 2026-08-12 — finding 1
reaffirmed as residual 5 and closed from the record, finding 2 fixed on the branch at full scope
(sentinel rejection, length floor, empty template, negative tests).

| # | SPEC | Finding | Disposition (A/B/C/E) |
|---|------|---------|-----------------------|
| 1 | E5-SPEC-30, E5-SPEC-31 | [high] Replay re-runs live eligibility instead of replaying the original verdict (`services/intake-service/app.py:154-188`): a replay reuses `patient_id` but falls through to `_verify_eligibility_guarded(req.insurance)`, so a lost-response retry spends another PHI-bearing payer hop and can return a different verdict than the original confirmation. Recommends persisting the first submission's eligibility result and returning it on replay | **Restates accepted residual 5** (`pr-body.md` §Accepted residuals 5; plan D-14 and §Landmines; plan header residual list). Not re-litigated per the fix-session step-2 rule — the mechanism the reviewer objects to *is* the recorded acceptance, taken because the verdict reaches no column (debt-log D4 residual 3, `pr-body.md` residual 6) and because an indistinguishable replay is requirements D-5's point. Persisting the verdict is new state on the registration path → the skill's structural trigger, i.e. stage 3, not a branch patch. **Owner decision 2026-08-12: reaffirm the residual, close from the record.** No code change; answered on PR #76 with an anchored comment citing `pr-body.md` residual 5, plan D-14 and debt-log D4 residual 3. The reviewer's own recommendation — persist the verdict — is D4 residual 3, already open and already the reason this residual exists; reopening it is the owner's call and was not taken here |
| 2 | E5-SPEC-41 | [high] The committed placeholder key is accepted for the PHI-derived HMAC (`services/intake-service/app.py:267-274`, `.env.example:115`): `_payload_fingerprint` fails closed only on an *empty* key, while `.env.example` ships the non-empty `dev-registration-fingerprint-key-change-me`. Recommends rejecting known placeholder sentinels, enforcing a minimum key length, shipping the example empty, and a test that the committed placeholder fails closed | **A, believed genuine and not covered by any recorded residual.** Residual 9 accepts "the column exists at all" and pins the *keyed* property; it does not accept a published key satisfying the guard. Three points make it stronger than the plan weighed at D-19: (a) the estate already solved this exact problem the other way — `services/ai-assistant/llm_client.py:411-450` rejects `_PLACEHOLDER_BEARER_TOKENS` precisely because "a non-empty placeholder must NOT satisfy the guard"; (b) `.env.example:129-134` states that rule in prose, in the same file, 14 lines below the value that breaks it; (c) `.github/workflows/ci.yml:141-143` asserts "Both templates ship fail-closed (empty secrets), so nothing here can weaken a guard" — this branch made that comment false. The compose job only builds, never runs, so emptying the example breaks nothing there. Fix adds no state (sentinel set + length floor + empty example + test), so routing is a branch patch, not stage 3. **Owner decision 2026-08-12: fix on the branch, full scope — accepted in full, nothing scoped down.** `app.py::_fingerprint_key` extracts the guard and refuses an unset, whitespace-only, sentinel-matching or under-32-character key with the same 503, naming the variable and never the value; `.env.example` ships the key EMPTY with the `AWS_BEARER_TOKEN_BEDROCK` rationale spelled out; `config.py`'s comment and the PHI register row record that presence is no longer the guard. Both halves of the check are load-bearing and neither subsumes the other — the shipped placeholder is 41 characters, so the floor alone would pass it; a 31-character random secret is no sentinel, so the list alone would pass that. The three test fixtures that set a short `"e5-test-key"` are lengthened rather than the floor lowered. +11 tests (8 sentinel/length cases, the template-reading pin, the no-key-in-the-log negative, the positive control) |

### Round 4 — 2026-08-12

1 finding. **Past the round-3 rule**, so the disposition is the owner's: the finding is
round 3 finding 1 re-raised verbatim after a dry re-tag, and the recorded owner decision of
2026-08-12 is honoured rather than re-opened. Round 3's finding 2 (the fingerprint-key guard,
fixed in `2a6c4d5`–`03ee5a0`) did not return — the fix held, and no new finding was raised
against it or against anything else on the branch, so this round is **dry on new findings**.

| # | SPEC | Finding | Disposition (A/B/C/E) |
|---|------|---------|-----------------------|
| 1 | E5-SPEC-30, E5-SPEC-31 | [medium] Replay re-runs live eligibility instead of returning a recorded verdict (`services/intake-service/app.py:188-192`): a known `submission_id` reuses the stored `patient_id` and then falls through to `_verify_eligibility_guarded(req.insurance)`, so a retry can report different coverage than the original confirmation if the payer changed state, timed out, or the breaker opened between attempts. Recommends persisting the eligibility status/response on the submission row and returning it on replay; failing that, stating plainly in code, contract and docs that only `patient_id` is idempotent; plus a test that stubs `active` then `inactive` and asserts the replay still answers `active` | **Repeat of round 3 finding 1 — same mechanism, same anchor, same remedy; answered from the record again, no code change.** Nothing about the branch changed between rounds on this path: the round-3 commits touched only `_fingerprint_key`, `.env.example`, `config.py` and the PHI register. The recorded acceptance stands — `pr-body.md` §Accepted residuals 5 and 6, plan D-14 and §Landmines, spec D-18 — and the remedy the reviewer names is `docs/debt-log.md` D4 residual 3, open and by definition the reason residual 5 exists. Persisting the verdict is new state on the registration path (staleness semantics, a column, a migration) → the skill's structural trigger, so stage 3 and a fresh re-gate, not a branch patch. **Owner decision 2026-08-12 (round 3) reaffirmed and not re-litigated.** On the reviewer's second option — "make code, contract and docs agree" — checked rather than assumed: `contracts/intake-registration.json` makes no eligibility claim at all, `app.py`'s replay comments do not claim a replayed verdict, and the residual is stated in three artifacts that land on `main`. The one delivered artifact that reads stronger than the guarantee is `tests/test_intake_idempotency.py::test_the_replay_is_indistinguishable_from_the_original`, which asserts `second["eligibility"] == first["eligibility"]` against a deterministic payer stub — true of the test's world, not of a time-varying payer. Surfaced to the owner as a docs-only option, and **taken**: owner decision 2026-08-12, scope the docstring, keep the name and every assertion (`383be97`). The docstring now states that the eligibility equality holds because the stub is deterministic, that the guarantee is the registration, and where the residual is recorded. No behaviour moved and the suite is unchanged at 1301/1/5. The reviewer's suggested regression test — stub `active` then `inactive`, assert the replay still answers `active` — is deliberately **not** added: it would encode the behaviour residual 5 defers, so it belongs with the D4 residual 3 fix, not ahead of it. **Loop continues**: owner decision 2026-08-12, re-tag for a round 5 — the residual is settled and a fifth restatement of it changes nothing, but the rest of the branch (fingerprint path, collision loser, bounded wait, portal re-mint, the r3 key guard) is worth another pass, and the docstring commit gives the reviewer new lines to read. Said so explicitly in the disposition comment |

### Round 5 — 2026-08-13

1 finding. **Past the round-3 rule**, so the disposition is the owner's; taken 2026-08-13.
Round 4's re-raised residual did **not** return — the loop's own bet (that a fifth restatement
was unlikely and the rest of the branch was worth another pass) paid, and the new finding is on
the path round 3's fix wrote. Labelled **B**: it is a defect in code an earlier fix round
introduced, the first B of this item and the first of the three code PRs since the baseline
(`docs/review-loop-metrics.md` §4). Worth reading as such — the round-3 fix was correct about
the hole it closed and blind to the one it opened, which is the exact shape §3.1 predicts of a
fix that changes a guard's default rather than its logic.

| # | SPEC | Finding | Disposition (A/B/C/E) |
|---|------|---------|-----------------------|
| 1 | E5-SPEC-41 | [high] A stack seeded from the committed templates rejects every registration while reporting healthy (`.env.example:121`, `docker-compose.yml` intake healthcheck): round 3 emptied `REGISTRATION_FINGERPRINT_KEY` in `.env.example`, `_fingerprint_key` raises 503 on an unset key, and the intake healthcheck only polls `/healthz`, which never exercises the key — so operators see green while no patient can register. Recommends generating a real gitignored key during `make up`/bootstrap, or failing startup/health until the key is configured | **B, accepted in full and fixed on the branch** (`958d46c`). Confirmed as an availability regression, not a warning: verified live before the fix by the round-3 commits' own behaviour, and after it by break-then-revert (below). Genuine and covered by no recorded residual — residual 9 accepts the column and pins the *keyed* property, and round 3's disposition accepted an empty template as fail-closed without weighing what fail-closed costs when nothing in the boot path can satisfy it. **Route: branch patch, not stage 3.** The fix adds no runtime state — no counter, TTL, lock, breaker, budget or cache — only bootstrap wiring, so the skill's structural trigger does not fire. **Mechanism, and why this one rather than the reviewer's second option:** the estate had already answered this shape for the redis password — `make up` GENERATES the secret into its own scoped env file (`Makefile:16-20`, `.env.redis.example`) — so the key follows it rather than growing a new startup guard. `.env.registration` is generated per machine (`openssl rand -hex 32`; 64 characters clears the 32-character floor), gitignored, and loaded by intake-service **alone**, listed after `.env` so the generated value beats any leftover assignment in the shared file. The scoping is a second, independent gain the reviewer did not ask for and that a startup guard would not have bought: the shared `.env` reaches every container on the network, and this key is the only thing between a stolen `registration_submissions` column and an offline confirmation oracle over guessable fields. The template still ships EMPTY, so a checkout that never ran `make` still fails closed — generation is what stops that meaning "a healthy stack that registers nobody". The healthcheck is deliberately **not** changed: with the key generated it would assert a condition that can no longer be false in a make-driven stack, and a `/healthz` that computes a fingerprint is a PHI-adjacent probe. +8 tests (7 structural in `tests/test_compose_topology.py` — scoping, load order, template empty, generated-not-copied, every compose target's prerequisite, gitignored; 1 outcome in `tests/test_intake_idempotency.py` that runs the Makefile recipe and feeds what it wrote to the guard), and the round-3 template test repoints to `.env.registration.example`. Registry upkeep filed at the same time: the PHI register row, the runbook's operator entry, and `CLAUDE.md` §3's generated-file list, which this change made wrong |

**E-5 — round-5 live verification, 2026-08-13.** Dev compose stack on the engagement machine
against the synthetic seed (no real service, no production data; the stack was not running
before and was torn down after). `make config` generated `.env.registration` (64 hex chars) and
compose parsed; the intake container's effective `REGISTRATION_FINGERPRINT_KEY` equalled the
generated value and **not** the stale one still present in the local `.env`, proving the
env_file ordering. Through the gateway as `frontdesk`: `POST /intake` → `200` `patient_id=1873`,
byte-identical replay → `200` same id in 0.03s, edited retry on the same identifier → `409`.
Negative (break-then-revert): key emptied and intake recreated → every registration `503`
`registration store unavailable` **while the container still reported healthy**, which is the
finding reproduced under the new wiring; key restored → `200` `patient_id=1874`. Suite
**1309 passed, 1 xfailed, 5 deselected** (1301 → 1309, +8; the xfail and the five deselected did
not move). `make eval` green. `gitleaks --no-git` over the tracked tree plus the new template →
no leaks, so the added file does not redden CI's `secret-scan`.

### Round 6 — 2026-08-13

1 finding. **Past the round-3 rule**, so the disposition is the owner's; taken 2026-08-13.
Round 5's fix held and did not return, and the eligibility residual re-raised at r3/r4 stayed
closed. The new finding is on the branch's *deployment* surface — the first round to leave the
request path entirely — and it is labelled **A**: genuine, covered by no recorded residual, and
not a defect this branch's own fix rounds wrote (the class predates e5, below).

| # | SPEC | Finding | Disposition (A/B/C/E) |
|---|------|---------|-----------------------|
| 1 | E5-SPEC-29 | [high] Existing databases reject every intake: `create_intake` unconditionally queries `registration_submissions` (`services/intake-service/app.py:153-154`), but nothing applies `db/migrations/010_registration_submissions.sql` to an already-running database — `docker-compose.yml:12` mounts only `db/schema.sql` into `/docker-entrypoint-initdb.d`, which Postgres runs on a fresh volume alone, and `make up` runs no migrations. On a volume with existing `pgdata` the query hits a missing table, is caught as `SQLAlchemyError`, and returns `503` for every registration. Recommends wiring the migration into `make up`/the deploy path or failing startup until the table exists, plus an upgrade test that boots from the pre-migration schema | **A, accepted; fixed on the branch as an operator path** (`a04a02b`). Mechanism confirmed at runtime before any decision (E-6): a scratch container seeded from `main`'s `db/schema.sql` has 14 tables and no `registration_submissions`, and the select errors exactly where `_find_registration` catches it (`app.py:372-383`). **The class is older than this branch**, which is what decided the scope: `insurance_coverages` (mig 005), `roi_requests` (008) and `duplicate_review_queue` (009) are read the same unconditional way, so every environment older than those migrations already carries the same latent break — e5 adds a tenth table to a condition `main` has, it does not create one. **Route: branch patch, not stage 3.** The fix adds no runtime state — no counter, TTL, lock, breaker, budget or cache — only an operator command and documentation, so the skill's structural trigger does not fire. **Mechanism, and why not the reviewer's two options:** `db/schema.sql` is already re-appliable (15 of 15 tables are `CREATE TABLE IF NOT EXISTS`), so the upgrade needed exposing, not building — `make schema-apply` pipes the flattened schema into the running database, creating what is missing and no-oping what is not. Wiring it into `make up` was rejected because a migration step that runs unconditionally on every start is a write to a live database nobody asked for, inside the `docs/landmines.md` §1 migrations zone; a startup guard was rejected because it converts a fixable operational state into a service that will not boot. A real runner (versions table, apply step) is the complete answer and is estate-wide, out of this item's scope by owner decision 2026-08-13 and filed as `docs/debt-log.md` cross-cutting "No migration runner", which also records what the mitigation does **not** cover: `IF NOT EXISTS` skips an existing table whole, so an `ALTER TABLE ... ADD COLUMN` migration is still hand-applied. **A second defect surfaced while verifying the obvious answer** and is why "just run `make seed`" is not the disposition: `db/seed/seed.sql` carries no `ON CONFLICT`, so the seed half of that target leaves a half-duplicated corpus on a populated volume — the explicit-id inserts are skipped while every serial-id table gets a second copy attached to the original patients (measured: `consents` 403→806, `insurance_coverages` 255→510, `patients` unchanged at 255) — pre-existing on `main`, and `docs/runbook.md` advertised the command for exactly this case. Filed as the second `docs/debt-log.md` cross-cutting row; the runbook and the `Makefile` `##` line now say fresh-DB-only and point at `schema-apply`. The reviewer's upgrade test is deliberately **not** built as an integration boot test — it would need live Postgres and would exercise one instance; +24 structural tests in `tests/test_schema_upgrade_path.py` close the class instead: the re-appliable form (a future plain `CREATE TABLE` reddens), the table and column hand-sync between every migration and the flattened schema, `schema-apply` applying schema without seed (with `seed` as the positive control), and the runbook stating the bound |

**E-6 — round-6 stale-volume verification, 2026-08-13.** Isolated by construction: a throwaway
`postgres:15` container on its own anonymous volume, no host port, no compose project — the
engagement stack was down and its `ad-riverbend-portal_pgdata` volume was never mounted, read or
written; the container was removed after. Seeded from `git show main:db/schema.sql` + `seed.sql`
→ 14 tables, no `registration_submissions`; `select 1 from registration_submissions` →
`ERROR: relation "registration_submissions" does not exist`, the input to the 503 branch.
Applying the branch's `db/schema.sql` → `15 CREATE TABLE`, 14 `already exists, skipping` notices,
the new table plus `uq_registration_submission_id` created, `patients` 255→255 unchanged. Then
re-running `db/seed/seed.sql` on that populated database → duplicate-key errors on every insert
that names its id (`users`, `patients`, `encounters`, `records`, `slots` — skipped, counts
unchanged at 12/255/475/687/120) and a second copy of every serial-id table: `consents` 403→806,
`insurance_coverages` 255→510, `appointments` 209→418, `audit_logs` 22→44, `roi_requests` 16→32,
`disclosures` 8→16. Both halves measured before and after, not inferred from the after count. The
split is what makes it worse than a clean double — the duplicated coverage and consent rows point
at the original patients — and it is the foot-gun in the command the runbook used to recommend. Suite **1333 passed, 1 xfailed, 5
deselected** (1309 → 1333, +24; the xfail and the five deselected did not move). `make eval`
green (exit 0).

### Round 7 — 2026-08-13

2 findings. **Past the round-3 rule**, so both dispositions are the owner's; taken
2026-08-13. Finding 1 is round 6's, re-raised with the same anchor and the same two
remedies — the first re-raise of this item that the owner **did not** answer from the
record: round 6 shipped the operator path and declined the enforcement half, and round 7
reversed that half. Finding 2 is the first finding of the item to land on the portal's own
state lifecycle rather than on the service or the deploy path, and it is **A**.

*Citation correction, same round:* round 6's disposition cited `0cd880c` for the
upgrade-path fix. That object is a pre-amend dangling commit reachable from no branch; the
commit on `fix/e5-registration-idempotency` is `a04a02b` (the PR comment `r6:` cited it
correctly). Corrected in the row above. Evidence rule: a claim a git object proves is only
evidence if the object resolves from the branch.

| # | SPEC | Finding | Disposition (A/B/C/E) |
|---|------|---------|-----------------------|
| 1 | E5-SPEC-29 | [high] Existing Postgres volumes 503 every intake until a manual schema step runs (`services/intake-service/app.py:153-154`): the round-6 mitigation is documented as an operator command, but nothing in startup or deploy enforces it, so the failure ships as a healthy-looking service. Recommends wiring schema application into the deploy path, **or** failing the intake health/startup check while the table is missing | **Owner overrule of round 6, accepted on the second option; fixed on the branch** (`27a05d8`). Round 6 accepted the mechanism and declined both enforcement options — `make up` applying schema unconditionally is an unrequested write to a live database inside the `docs/landmines.md` §1 migrations zone (still declined, unchanged), and a startup guard "converts a fixable operational state into a service that will not boot". **The owner reversed the second half 2026-08-13**, and the reversal is narrower than what round 6 rejected: the guard lands on the health *signal*, not on process exit, so the container starts, stays diagnosable, and says which table is missing — an unhealthy container instead of a green one that registers nobody. **This is imitation, not invention:** `services/gateway/app.py:179` already sends a real authenticated Redis PING from `/healthz` and answers 503 when the store cannot serve, on the recorded argument that an accurate red beats a stable lie; nothing in the topology drains or restarts on the signal. **Class, not instance:** the check is over `Base.metadata` — every table the service maps — so a future model is inside the guard with no edit, and the three earlier migrations round 6 measured as carrying the same latent break (005, 008, 009) are covered by the same code rather than one row at a time. **Route: branch patch, not stage 3** — it adds no counter, TTL, lock, breaker, budget or cache; it is a read of catalog metadata. **Deliberately not changed:** the gateway's `depends_on` on its seven domain services stays `service_started`, because `service_healthy` would turn one stale table into an estate-wide boot failure — seven working surfaces held down by one broken one. The residual is unchanged in kind and updated in place: `docs/debt-log.md` "No migration runner" now records that intake detects the condition and that `records-`, `roi-` and `scheduling-service` still do not, and the runner itself stays out of scope by the round-6 owner decision. +18 tests in `tests/test_intake_schema_guard.py`; `docs/runbook.md`'s upgrade entry now states the symptom operators will actually see |
| 1b | E5-SPEC-41 | *Not a reviewer finding — the class the fix left half-closed, raised in-session and decided by the owner 2026-08-13.* Making `/healthz` a readiness probe closes "green while every registration 503s" for the schema, but the unconfigured fingerprint key answers 503 on the same requests and round 5 recorded a decision **not** to check it here ("a `/healthz` that computes a fingerprint is a PHI-adjacent probe") | **Owner decision: extend the guard** (`27a05d8`). The round-5 objection is about computing a digest; the landed check asks the configuration whether a real key exists and computes none, so it does not reach it. `_fingerprint_key_is_real` is now one predicate shared by the request path and the probe — two copies is how a health endpoint ends up green on a value the request path refuses. The refusal is polled every 10s, so it names the variable and states neither the value, its length, nor which check refused (the `_fingerprint_key` precedent). Round 5's other half stands untouched: generation at `make up` is still what keeps a make-driven stack green, and the guard only reddens a stack that never ran `make`. PHI register updated with the second refusal site |
| 2 | E5-SPEC-26, E5-SPEC-35 | [medium] The retry id is lost on remount (`frontend/app/intake/page.tsx:56`): `submissionId` lives in `useState` alone, so a refresh, tab restore or crash after an unconfirmed submit mints a new identifier, bypasses the server-side replay and creates a duplicate chart. Reviewer states it as an inference from the state lifecycle. Recommends persisting the in-flight id in `sessionStorage` alongside the draft, clearing it only on confirmed success, plus a remount test | **A, accepted as a residual by owner decision 2026-08-13; no code change. `docs/todo.md` TODO-66.** Mechanism confirmed, and the reviewer is right that no recorded residual covered it. What decided the disposition is the premise the recommendation rests on: **there is no draft.** The intake form persists nothing — `frontend/app/lib/session.ts` is the only browser-storage writer in the portal and it holds the auth token — so a remount loses every typed value along with the identifier, and "re-submit the same attempt" is not a path the operator can take. Persisting the id *alone* would therefore be **worse than the gap**: the old attempt's identifier would attach to freshly typed content, the keyed fingerprint would mismatch, and a genuinely new registration would be refused (E5-SPEC-42) — the 409 trap D-20 was written to prevent — while E5-SPEC-35 ("a new registration gets a new identifier") stopped holding, since a refresh is indistinguishable from a fresh start without a draft to compare. What the branch does today is the outcome D-20 already chose for the edit path: the retyped registration creates a second chart and the pair is queued for human review (E5-SPEC-37), visible rather than silent. The complete fix is draft restore, and its cost is not the retry key: the draft is name, DOB, SSN and insurance, so it writes PHI to browser storage on a shared front-desk workstation — a `docs/landmines.md` §1 decision with its own approval, and new persisted state with a lifecycle, i.e. the skill's structural trigger. Filed with that constraint stated so the session that takes it finds it first |

**E-7 — round-7 live verification, 2026-08-13.** Isolated by construction, as E-6 was: a
throwaway `postgres:15` on its own anonymous volume plus the branch's intake image on a
private network, no host ports, no compose project — the engagement stack was down and its
`ad-riverbend-portal_pgdata` volume was never mounted, read or written; both containers and
the network were removed after. The container ran under the **compose healthcheck command
verbatim**, because the whole claim is what that command reports. Seeded from
`git show main:db/schema.sql` → 14 tables, `registration_submissions` absent. (1) Real key,
table missing: healthcheck **unhealthy**, `/healthz` → `503 {"detail":"schema incomplete"}`,
log `healthz: schema incomplete, missing registration_submissions` — the finding's condition,
now visible where round 6 left it green. (2) Applying the branch's `db/schema.sql` (what
`make schema-apply` pipes in): table created, `patients` 0→0 unchanged, healthcheck goes
**healthy**, `/healthz` → `200`. (3) Break-then-revert on the other half: key emptied,
schema complete → **unhealthy**, `503 {"detail":"registration key not configured"}`, log
naming the variable and no value; key restored → **healthy**, `200`. Suite under the
claim-worthy gate `make test-docker` → **1351 passed, 1 xfailed, 5 deselected**
(1333 → 1351, +18; the xfail and the five deselected did not move). Red-before-green
recorded per slice: the 11 schema cases failed against the pre-fix `/healthz` (9 red, 2
green — the two positives), the 6 key cases failed after the schema half landed. `make eval`
not re-run and the frontend suite not re-run — nothing under `eval/rag/`, the retrieval path
or `frontend/` is in this round's diff.

### Round 8 — 2026-08-13

1 finding, **no code change**. **Past the round-3 rule**, so the disposition is the owner's;
taken 2026-08-13. Round 7's finding 1 — the schema/key health guard — did **not** return,
so the overruled disposition is accepted by the reviewer. What returned is round 7's
finding 2, the residual the owner accepted one round earlier, re-raised at the same anchor
with the same remedy and escalated to a no-ship verdict.

This is the item's second re-raised residual (the eligibility verdict at r3→r4 was the
first), and it re-raises the same way: the recommendation still names a draft store the
portal does not have. The loop continues by owner decision, on the same reasoning that paid
at r5 — a further restatement of a settled residual changes nothing, but the branch has
surfaces the reviewer has read fewer times, and round 7 gave it 18 new tests and a new
endpoint behaviour to read.

| # | SPEC | Finding | Disposition (A/B/C/E) |
|---|------|---------|-----------------------|
| 1 | E5-SPEC-26, E5-SPEC-35 | [high] The idempotency key is lost on remount (`frontend/app/intake/page.tsx:56`): a refresh, navigation, session-refresh remount or tab crash after a committed-but-unconfirmed POST mints a new UUID, the server replays nothing, and a second patient/coverage/consent set is written. Recommends persisting the attempt id outside the component lifetime (`sessionStorage` keyed to the draft), cleared only on a confirmed 201 or an explicit new-registration action, or issuing the key server-side; plus a remount test that submits, fails unconfirmed, remounts *with the same draft* and asserts the original id is resent | **Answered from the record, no code change — this is round 7 finding 2, accepted as a residual by owner decision 2026-08-13 and filed as `docs/todo.md` TODO-66.** Nothing on this path changed between rounds: round 7's commits touched `services/intake-service/app.py`, `tests/`, and four docs; `frontend/` is untouched on this branch since `7e0b2c1` (round 2). The account lives in TODO-66 and is not re-argued here. What is worth recording is that the escalation to no-ship rests on the same premise the r7 disposition measured and found absent: the recommendation says "remounts the intake page **with the same draft**", and there is no draft — `frontend/app/lib/session.ts` is the portal's only browser-storage writer, so a remount loses every typed value with the identifier. The reviewer's own test design is unbuildable as written for that reason, which is the cheapest available check on the finding. The alternative it offers — issue the key server-side — does not reach the mechanism either: a server-issued id still has to be remembered across the remount by the same client that just lost its state. **Not reopened**, per the skill: reopening an accepted residual is the owner's call, and the owner accepted it one round ago with the PHI cost stated. **Loop continues**: owner decision 2026-08-13, re-tag for a round 9 — the disposition comment says which finding is closed and which surfaces are unread, as at r4 |

**E-8 — round-8 verification, 2026-08-13.** No code change, so no re-measurement: the tree
is `1793c31` plus this round's artifact edit, and the last suite run under the claim-worthy
gate (E-7, `make test-docker`) stands at **1351 passed, 1 xfailed, 5 deselected**. CI on the
pushed head: all fourteen jobs green.

### Round 9 — 2026-08-13, undispositioned; PR closed

A ninth codex review was posted: the round-7/8 remount finding a **third** time (anchored
`frontend/app/intake/page.tsx:49-70`, held at no-ship). It was never dispositioned — the
owner closed PR #76 unmerged the same day (decision and rationale: `pr-body.md` §Status),
so this entry is the close-out record, not a disposition. The finding is recorded as
**standing open at close** and is carried to the successor item e5b as a first-class spec
question (the remount/draft lifecycle, including the no-draft premise and the
PHI-in-browser-storage cost measured at rounds 7–8), not as an accepted residual the
successor inherits silently.
