# e4 findings

> Round log for this item's three gated stages: the drift gate
> (`.claude/skills/drift-gate/`), the impl gate (`.claude/skills/impl-gate/`), and the
> `@codex-review` loop (owned by `.claude/skills/implementation/`). Each stage appends
> rounds under its own heading, created on that stage's first finding; the next-stage
> session fills the dispositions. Findings only — plan maturity lives in `plan.md`,
> delivery status in `pr-body.md`.

## Gate

### Round 1 — 2026-08-10

5 findings, no stamp.

| # | SPEC | Finding | Disposition (stage 3) |
|---|------|---------|-----------------------|
| 1 | E4-SPEC-28 | §9 reserves `TODO-59` and states "highest today is TODO-58"; `docs/todo.md:73-74` already carries open **TODO-59** (the dead push-hook claim) and **TODO-60** (the ADR `LLMTimeout` enumerations), so the reserved id collides and the stated fact was wrong when written | Fixed. §9 reserves **TODO-61**, states TODO-60 as the highest and names what TODO-59/60 are, re-verified against `docs/todo.md:73-74` this session; the re-check-at-landing instruction stays. Landmines PR-body line updated to TODO-61, and verification step 13 now makes the landing re-check an explicit check rather than a parenthetical |
| 2 | E4-SPEC-4, E4-SPEC-15 | The plan deletes `_create_patient` / `_create_coverage` / `_record_consents`, but `docs/phi-logging-policy.md:86-88` carries one register row per function; that file is in neither §9 nor Files touched, so the live PHI-violation register would name three functions that no longer exist | Fixed. `docs/phi-logging-policy.md` added to §9 and Files touched: the three rows collapse into one for `_create_registration`, each keeping its dated finding and blast-radius note; the `_record_consents` row also records the swallowed write failure gone (E4-SPEC-4). The `_post`/`_get` row — which the finding did not name but is falsified the same way, since it says the fix "belongs to the D4 `_post_checked` migration" — records the registration route migrated and the thirteen deferred to `e5`. New Landmines bullet flags that a live PHI control document is in the diff, and new verification step 14 greps for the three dead symbols across `docs/`, `tests/`, `services/` |
| 3 | E4-SPEC-22, E4-SPEC-23, E4-SPEC-28 | `tests/README.md:56-58` asserts "No test drives `POST /intake` as an endpoint … unguarded (`docs/todo.md` TODO-55)" — the exact gap `tests/test_intake_endpoint.py` closes — and `tests/README.md` appears in neither §9 nor Files touched | Fixed. Added to §9, Files touched, and the E4-SPEC-22/23 scope-map row. The bullet moves out of the "deliberate gaps" list into that file's own closed-entries note (its 2026-08-08 convention), naming `tests/test_intake_endpoint.py`. Verified this session that `docs/landmines.md` §3's deliberate list never contained this gap and `docs/todo.md:69` states it is not one — so no §3 edit and no gap moved; step 14 asserts that, tying it to the step-12 baseline move |
| 4 | E4-SPEC-17, E4-SPEC-18 | §3 waives a compose override with "`tests/test_compose_topology.py` pins that convention"; that file pins the shared-`.env` rule only for `AI_MEMBER_ID_PREFIXES` (`:344`, `:354`), so a per-service `environment: INTAKE_TIMEOUT_SECONDS:` in `docker-compose.yml` would defeat the pinned bound with a green suite — guard it or name the residual | Fixed by guarding, not by naming a residual. §3's waiver is replaced with the measurement (the gateway does carry an `environment:` block, `docker-compose.yml:83-90`) plus a new `tests/test_compose_topology.py` section keyed on `INTAKE_TIMEOUT_SECONDS`, mirroring the catalog one. Two assertions, because the finding's vector is not the only one: no per-service `environment:` entry, and no `.env.*.example` scoped template — the gateway loads `.env.ai-proxy` and `.env.redis` *after* `.env`, and a later `env_file` wins. Added to Files touched, the scope-map row, and verification step 7 as two break-then-revert negatives that must fire while step 7's own two sources stay green |
| 5 | — (citation) | The out-of-scope heading reads "from requirements §6"; requirements §6 is the decisions table and out-of-scope is §7 (the content itself is carried verbatim). Inherited from the `plan-authoring` template, whose heading assumes §6 | Fixed in this plan — heading now cites §7. **The template is the actual defect and is not fixed here**: `.claude/skills/plan-authoring/SKILL.md` hardcodes "§6" in both its process step 1 and its template, so every future plan inherits the same wrong cite whenever a requirements doc has a §6 that is not out-of-scope. Tooling change, outside every E4 SPEC — filed for the owner rather than folded into a code PR |

### Round 2 — 2026-08-10

6 findings, no stamp.

| # | SPEC | Finding | Disposition (stage 3) |
|---|------|---------|-----------------------|
| 1 | E4-SPEC-28 | Landmines/risk (`plan.md:598`) still cites **TODO-59** as the entry recording that no code may read the `roi_consent` row as an authorization, while §9 (`:465-469`) and the PR-body line (`:633`) both say **TODO-61**. TODO-59 is a live open entry — the dead push-hook claim (`docs/todo.md:73`). Round 1 finding 1 repointed §9 and the PR-body line and missed this third site | Fixed. The Landmines bullet now cites **TODO-61** and points at §9 for the id, so the number lives in one place and the other two sites reference it rather than restating it — which is what let round 1's repoint miss a site. The re-check-at-landing instruction stays in §9 and in verification step 13; `docs/todo.md:73-74` re-verified this session (TODO-59 the dead push-hook claim, TODO-60 the ADR `LLMTimeout` enumerations, both open, highest is TODO-60) |
| 2 | E4-SPEC-25 | The accepted residual (`plan.md:620`) justifies not widening `VerdictBadge` by "would restyle the four pages already using it (W3-SPEC-18)". `VerdictBadge` is imported by exactly **one** page, `frontend/app/assistant/page.tsx:6` (measured this session, whole `frontend/` tree). The four-page component is `StatusBadge` (`app/page.tsx`, `roi/`, `records/`, `appointments/`), which W3 deliberately left untouched — so the residual's stated cost is not the cost that exists | Fixed, and the residual survives on a better reason. Re-measured this session: `VerdictBadge` has exactly one importer, `frontend/app/assistant/page.tsx:6`; the four-page component is `StatusBadge`, and `VerdictBadge.tsx:10-15` is where that restyle-four-pages cost actually belongs — the plan had borrowed W3's justification for *not extending StatusBadge* and misapplied it to widening `VerdictBadge`. The rewritten residual states the real cost: widening the tone map changes the frozen W3 assistant surface too, and inventing a tone for a status outside the eligibility path's own four-value vocabulary is what W3-SPEC-6 forbids and `frontend/app/components/VerdictBadge.test.tsx:67-96` pins. The residual itself is unchanged and still accepted |
| 3 | E4-SPEC-1, E4-SPEC-4 | Files touched names only "`tests/test_intake_match_key.py` — `_StubSession` gains `flush()`", but the ordering guarantee the plan cites to preserve ADR 0005 (`:334`) is `_OrderedSession` at `:338-341`, which keys its `"patient-committed"` marker on **`refresh()`** — a method `_create_registration` never calls. Re-keying that marker to `flush()` would also assert a weaker property than the plan claims: `flush()` fires *inside* the transaction, before the commit, so the post-commit ordering would no longer be what the test binds. The marker belongs on `commit()`, and the plan does not say so | Fixed as the finding directs. §2's ordering bullet now spells the re-binding out: `_OrderedSession`'s `"patient-committed"` marker moves to **`commit()`**, explicitly not to `flush()`, with the reason written down — `flush()` fires inside the transaction, so keying it there would weaken the assertion from the ADR 0005 post-commit property to a post-flush one while staying green. `_StubSession.refresh` (`:96-97`) becomes `flush` with the same `NEW_ID` body, since that is now what assigns the PK, keeping the double modelling only what `app.py` calls. Files touched carries all three edits plus the `:334` docstring retarget; the plan's citation is widened from `:334` to `:331-349` so it names the test, not one line of its docstring |
| 4 | E4-SPEC-26, E4-SPEC-28 | Verification step 14's `grep -rn "_create_patient\|_create_coverage\|_record_consents" docs/ tests/ services/` cannot "return nothing outside history" as stated: `docs/workflow/w2/plan.md:202,206,647` and `docs/workflow/w2/pr-body.md:143` are frozen delivery records that must not be rewritten, and `docs/workflow/e4/plan.md` and this `findings.md` name all three symbols themselves. The check needs scoping to the live registries it is actually guarding | Fixed. Step 14 now greps `services/ tests/ adr/ docs/*.md CLAUDE.md` and must return **nothing** — a hard check rather than an "outside history" judgement call. Both exclusions are stated with their reason: `docs/workflow/**` is frozen delivery records (the four w2 hits, plus e4's own `plan.md`/`findings.md`), and `docs/specs-deprecated/` + `docs/handover/` are archives that carry none of the three today (measured). The flat `docs/*.md` glob is noted as reaching exactly the six live registries. The step also enumerates the live hits it must clear, which surfaced one the plan had missed: `services/intake-service/app.py:362`, a rule-3 comment citing `_create_patient` inside `_evaluate_match_key` — a function that **survives** this change. That retarget is now in §2 and in the Files touched row |
| 5 | E4-SPEC-4, E4-SPEC-15 | Two further live citations of a deleted symbol are unaccounted for: `docs/debt-log.md:139` (D4 residual 3, "`_create_coverage` writes …") — §9's debt-log paragraph marks residual 3 still open but names no symbol retarget — and `adr/0010-eligibility-resilience.md:154`, which is in neither §9 nor Files touched and lies outside step 14's grep scope entirely | Fixed, by different means for the two files, recorded as a plan-stage decision (owner-confirmed 2026-08-10): a **live register** is retargeted in place, a **dated decision record** is amended, never rewritten. So `docs/debt-log.md:139` — D4 residual 3, which stays open and whose claim e4 does not change — is retargeted at `_create_registration` in §9's debt-log paragraph. `adr/0010-eligibility-resilience.md:154` takes a dated `> Amended 2026-08-10` blockquote naming the new symbol and confirming residual 3 open, per `adr/_template.md`'s never-rewrite-history rule and the amendment idiom of ADRs 0011/0013/0014; `Accepted` status, decision text and every budget value untouched. `adr/` is now inside step 14's grep scope, ADR 0010 is in Files touched, and a Landmines bullet flags that an ADR 0010 hunk appears in the diff — the same call-out the plan already makes for `docs/phi-logging-policy.md` |
| 6 | — (out-of-scope carry) | The first out-of-scope bullet is not verbatim from requirements §7: the clause "and no portal surface consumes their error bodies, so the deferral is chunked delivery rather than narrowed scope" is dropped (the other seven bullets match exactly). That clause is the one requirements §2's own 2026-08-08 correction undercuts, so the fix is either restoring it verbatim or amending requirements §7 — an owner call at stage 1, not a silent plan edit | Fixed at stage 1 by owner decision, 2026-08-10: **requirements §7's bullet is amended**, and the plan then carries the amended text verbatim. Recorded as requirements **D-6**, same mechanism as D-5, with the requirements doc re-stamped AGREED 2026-08-10. The falsified clause is replaced by the deferral's real basis, which D-3 already gave and which §2's correction does not touch — the contract decision lands in e4, the remaining thirteen route contracts land in `e5` — plus an explicit sentence that it is **not** deferred because the portal is unaffected, pointing at §2 and E4-REQ-12. Restoring the clause verbatim was rejected: a plan that knowingly carries a false sentence to satisfy a verbatim rule defeats the rule's purpose |

### Round 3 — 2026-08-10

4 findings, no stamp. **Round-3 rule fires** — the loop stops here and each finding below is an
owner decision (accept as a named residual, overrule, or amend the spec), recorded in its
disposition cell. Findings 1 and 2 are both inside the single §2 bullet that round 2 finding 3
created; findings 3 and 4 are citation-level.

| # | SPEC | Finding | Disposition (stage 3) |
|---|------|---------|-----------------------|
| 1 | E4-SPEC-1, E4-SPEC-4 | §2 (`plan.md:177-180`) re-keys `_OrderedSession`'s `"patient-committed"` marker from `refresh()` to `commit()`. That turns `tests/test_intake_match_key.py::test_match_evaluation_runs_after_the_patient_row_is_committed` **red**: `_evaluate_match_key` commits on its own success path (`services/intake-service/app.py:350`), so the marker fires twice and `order` becomes `["patient-committed", "match-evaluated", "patient-committed"]` against an `==` assertion. `commit()` is the right *event* — it is not a unique one, and the plan does not say how the second call is excluded (first-commit-only marker, or a marker keyed on the Patient object being in `self.added`) | Confirmed red against the tree this session (`app.py:350`, assertion at `tests/test_intake_match_key.py:350`) and **fixed**, owner decision 2026-08-10: **first-commit-only marker**, the first of the two mechanisms the finding names. §2 now carries the guarded `commit()` override verbatim with its reason, and the assertion text at `:350` is left exactly as it stands — the re-key becomes invisible to the property being asserted, which is the point. The finding's second option (keying on the Patient in `self.added`) was rejected on measurement: `self.added` is never cleared, so it fires on `_evaluate_match_key`'s commit too and needs the same ordinal guard anyway. Added as a plan-stage decision at the top and as verification step 15, whose second negative — drop the guard, watch a third element appear — is what keeps the guard from reading as decoration |
| 2 | E4-SPEC-1, E4-SPEC-4 | Same bullet: "`_StubSession.refresh` (`:96-97`) becomes `flush` with the same `NEW_ID` body". Not implementable — `_create_registration` calls `db.flush()` with **no arguments** while `refresh(self, obj)` takes one, so all 16 `create_intake` calls in that file raise `TypeError`. The body must change (assign `NEW_ID` from what the stub already recorded in `self.added`), which is exactly what the plan says it does not do | Fixed as the finding directs. §2 now states the rename **and** that the body must change, with the no-arg `flush()` written out: it walks `self.added` and assigns `NEW_ID` to any object still lacking a PK. Measured this session that this assigns exactly what `refresh()` did — `_create_registration` adds the patient, flushes, *then* adds coverage and consents, so the patient is the only member of `self.added` at the one call site. The plan's "same body" claim is deleted rather than softened, since it was the false half. Verification step 15's third negative restores the `obj` parameter and watches the 16 calls raise `TypeError`; Files touched carries the corrected description |
| 3 | E4-SPEC-1, E4-SPEC-4 | Same bullet, wrong cite: `_OrderedSession` is at `tests/test_intake_match_key.py:338-346` (its `refresh` override at `:339-341`), not `:335-341` — `:335` is the second line of the test's docstring. Round 2 finding 3 named this site correctly; the plan text does not | Fixed, both sites re-read this session: `_OrderedSession` is `:338-346` and its `refresh` override `:339-341` — the plan now carries both, so the class and the overridden method are separately checkable. The enclosing test's own citation was wrong the same way and the gate did not flag it: `:331-349` in §2's first line is actually `:333-350` (`:331`/`:332` are blank and the section comment). Corrected with it, and in Files touched |
| 4 | — (citation) | Three further off-by-one/two cites, each load-bearing for a reader checking the plan against the tree: `_post_checked` is `services/gateway/app.py:1295-1331`, not `:1295-1338`; `_post` is `:1245-1251`, not `:1245-1252`; the fallback string "Intake submitted successfully." is `frontend/app/intake/page.tsx:115`, not "line 113" (`:113` is the ternary's test); D4 residual 2 is `docs/debt-log.md:126-138`, not `:128-138` | All four fixed, each re-read from the working tree this session: `_post_checked` `:1295-1331` (§3), `_post` `:1245-1251` (Context), the fallback string `:115` (Context — the plan now cites the line rather than naming it in prose, so it fails visibly if it moves), D4 residual 2 `:126-138` (§2). `:126`/`:127` are the residual's own numbered opening, which is what the plan is pointing at, so the old start line understated the range rather than pointing elsewhere |

**Everything else re-verified clean this session**, against the working tree: out-of-scope carried
**verbatim** from requirements §7 (byte-equal, checked programmatically); all 28 SPEC ids present in
the scope map and every planned change traceable to a SPEC id or named registry upkeep; the
`docs/todo.md:69`/`:73-74`, `tests/README.md:56-58`, `docs/phi-logging-policy.md:86-88`,
`docs/debt-log.md:139`/`:333-336`, `adr/0010:154`, `.github/workflows/ci.yml:135`,
`docker-compose.yml:79-82`/`:83-90`, `tests/test_intake_match_key.py:96-97` and
`frontend/app/components/VerdictBadge.tsx:10-15` cites; the step-14 grep scope (its enumerated live
hit list is exactly what `grep -rn` returns today, `services/intake-service/app.py:362` included);
the contract file's `request_fields` against `Demographics`/`Insurance`/`IntakeRequest`;
`VerdictBadge`'s single importer; `@types/node` and the vitest default include for
`payload.contract.test.ts`; `fastapi`+`httpx` already in `requirements-dev.txt`;
`settings = Settings()` in `services/gateway/config.py:198`; and `frontend/app/lib/gateway.ts`
relaying upstream status verbatim, which E4-SPEC-5/6/7 depend on.

**Per-SPEC verdict:** satisfied — E4-SPEC-2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18,
19, 20, 21, 22, 23, 24, 26, 27, 28. Residual-named — E4-SPEC-25 (`VerdictBadge`'s four-value
vocabulary; a degraded off-vocabulary verdict reads as unchecked) and E4-SPEC-4's second residual
(atomicity is per-request, not cross-service). FINDING — E4-SPEC-1 and E4-SPEC-4, via §2's stub
re-binding only; the production change each states is sound.

**Round-3 escalation outcome, owner 2026-08-10.** No finding was accepted as a residual, overruled,
or answered by a spec amendment: all four were confirmed against the working tree in the stage-3
session and **fixed**. Only finding 1 carried a design choice, and the owner took the
first-commit-only marker (dispositions above). The spec is unchanged and stays frozen. The owner
also decided the gate does **not** close by overrule: the plan stays `Status: DRAFT` for a full
fresh-session re-gate as **round 4** — round 3's findings were all real, so a cold re-read of the
final text is earning its cost rather than repeating a dry round.

### Round 4 — 2026-08-10

2 findings, no stamp. **Past the round-3 threshold** — the loop already escalated once, so both
findings below are owner decisions (accept as a named residual, overrule, or amend the spec) rather
than an automatic return to stage 3. Neither touches a production change: one is a verification
step that cannot pass as written, the other a stated measurement that is false of the tree.

| # | SPEC | Finding | Disposition (stage 3) |
|---|------|---------|-----------------------|
| 1 | E4-SPEC-5 | Verification step 8 (`plan.md:629-630`) requires that the string "Intake submitted successfully." **"appears nowhere in the tree"**. It cannot pass: the string is also in `docs/debt-log.md:321` — inside the "Intake contract break" section §9 explicitly **keeps** as the record — and in `adr/0013-frontend-test-harness.md:30`, a `Superseded` decision record the plan's own never-rewrite-history rule forbids editing. The check needs the same scoping step 14 got in round 2 (live code + the portal tree, not the record documents), or it reads as green-by-judgement exactly where E4-SPEC-5's deleted fallback is being proved gone | Fixed as the finding directs, owner-directed in-session 2026-08-10. Step 8 now carries a scoped hard check — `grep -rn "Intake submitted successfully" frontend/ services/ tests/` returns **nothing** — with both exclusions stated and reasoned, the same two classes step 14 already names: `docs/debt-log.md:321` is the live record of the defect this PR fixes, `adr/0013-frontend-test-harness.md:30` is a `Superseded` decision record. Re-measured this session: those two plus `frontend/app/intake/page.tsx:115` are the only hits in the tree, and `:115` is what the PR deletes, so the scoped grep goes from one hit to zero |
| 2 | E4-SPEC-9 | The plan-stage decision bullet (`plan.md:35-37`) states "**Measured this session:** the form offers four and `ConsentKind` has five". `ConsentKind` has **three** members today — `npp_ack`, `treatment_consent`, `roi_consent` (`services/intake-service/schemas.py:21-23`); five is what §1's own widening produces, and §1 (`:108-113`) says the enum *gains* two members. So the plan asserts as a measurement of the tree a number only its own change creates, and the two sections contradict each other. The form-offers-four half is correct (`page.tsx:328-341`), and the conclusion — 4 ≠ 5, so equality needs a fifth form item — survives once the sentence is stated as post-widening | Fixed, owner-directed in-session 2026-08-10. The bullet now separates the two numbers and cites both: the form offers four (`page.tsx:328-341`), `ConsentKind` has **three** today (`schemas.py:21-23`), and the vocabulary this item lands is **five** because §1 applies the inherited 2026-07-30 widening. Neither number is the form's four, so the conclusion is unchanged and now agrees with §1 |

**Everything else re-verified clean this session**, cold, against the working tree. All 28 SPEC ids
appear in the scope map and every planned change traces to a SPEC id or named registry upkeep; the
out-of-scope section matches requirements §7. Round 3's four fixes each check out: `_OrderedSession`
is `tests/test_intake_match_key.py:338-346` with its `refresh` override at `:339-341`, the enclosing
test `:333-350` and its `==` assertion at `:350`; `_evaluate_match_key` does commit at
`services/intake-service/app.py:350`, so the first-commit-only guard is load-bearing; `_StubSession.refresh`
is `:96-97` and `self.added` (`:78`) holds only the patient at the one `flush()` call site, so the
no-arg body assigns what `refresh()` did; 16 `create_intake` calls in that file, and it is the **only**
test file that calls `create_intake`; `_post_checked` `:1295-1331`, `_post` `:1245-1251`,
`proxy_intake` `:251-253`, the fallback string `frontend/app/intake/page.tsx:115`, D4 residual 2
`docs/debt-log.md:126-138`. Also re-measured: step 14's grep scope returns exactly the live hit list
the plan enumerates, `services/intake-service/app.py:362` included; `docs/todo.md:73-74` (TODO-59/60
open, highest TODO-60, so TODO-61 is free); `tests/README.md:56-58` and its closed-entries note at
`:60`; `docs/landmines.md` §3's deliberate list (`:125-127`) does not contain the `POST /intake` gap;
`docs/phi-logging-policy.md:86-88`; `docs/debt-log.md:139` and `:333-336`;
`adr/0010-eligibility-resilience.md:154`; `.github/workflows/ci.yml:135` (`tests` and `frontend` both
in `docker-build`'s `needs`); `docker-compose.yml:79-82`/`:83-90` and
`tests/test_compose_topology.py:344`/`:354`/`:363`, including that `.env.example` does not match the
`.env.*.example` glob; `settings = Settings()` at `services/gateway/config.py:198` with a class-body
default idiom; intake's `eligibility_timeout_seconds` default 8 in code and `.env.example:39`;
`MARGIN_SECONDS = 1.0` and five existing sections in `tests/test_eligibility_budget_alignment.py`;
`db.py`'s `autoflush=False`; `Consent.kind` comment `models.py:44` and `db/schema.sql:124` with no
`CHECK`; the intake module docstring's per-consent-commit bullet `:33`; the contract file's
`request_fields` against `Demographics`/`Insurance`/`IntakeRequest` and the form's four insurance
inputs (`page.tsx:305-315`); `VerdictBadge`'s single importer `frontend/app/assistant/page.tsx:6`,
its `:10-15` comment and `VerdictBadge.test.tsx:67-96`; `frontend/app/lib/gateway.ts` relaying
upstream status verbatim and answering its own transport failure with 502; `fastapi` + `httpx` in
`requirements-dev.txt`; and `contracts/` not existing yet.

**Per-SPEC verdict:** satisfied — E4-SPEC-1, 2, 3, 6, 7, 8, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
20, 21, 22, 23, 24, 26, 27, 28. Residual-named — E4-SPEC-4 (atomicity is per-request, not
cross-service) and E4-SPEC-25 (`VerdictBadge`'s four-value vocabulary; an off-vocabulary degraded
verdict reads as unchecked). FINDING — E4-SPEC-5 (verification only; the production change is sound)
and E4-SPEC-9 (stated measurement only; the change and its conclusion are sound).

**Round-4 outcome, owner 2026-08-10 — two standing rules deliberately overridden, recorded here
because the record is the only place a future session can learn it.** The owner directed
fix-and-approve **in this gate session**, so this session both wrote the two fixes into `plan.md`
and stamped it, against `.claude/skills/drift-gate/` rule 2 ("the gate session never edits the
plan") and against the fresh-session re-gate the round-3 escalation had set. What that buys and what
it costs: both findings were verification/measurement text with no production change behind them,
each fix was re-measured against the working tree in the same session, and everything else in the
plan had just been re-verified cold above — so the final text is **not** unread, but the two edited
paragraphs are the one part of it no cold session has seen. Named rather than implied.

**Tooling defect closed the same session.** Gate round-1 finding 5 filed the `plan-authoring`
hardcoded-`§6` template defect for the owner rather than folding it into a code PR. The owner took
it now, and the fix is wider than that one site: `.claude/skills/requirement-synthesis/` **owns the
requirements document's section numbering** and three consumers hardcoded a number they do not own —
`plan-authoring/SKILL.md:17` and its template heading, and `drift-gate/SKILL.md:34`, which pointed
this very round at requirements §6 when e4's out-of-scope is §7. All three now locate the section by
heading; the owning skill states that its numbering is not stable and why (`e4` added a deferrals
and a decisions section, `e2` numbers its requirements table §4, `w1`–`w3` deleted §5 and left the
gap). Frozen delivery records need no edit — `w1`, `w2`, `w3`, `e1` and `e2` plans cite §6 and are
each correct for their own requirements. Tooling change, outside every E4 SPEC; it lands separately
from the e4 code PR.

### Round 5 — 2026-08-10

Clean — stamped. Not a fresh-context round: the round-4 findings were fixed and the plan stamped in
the round-4 session by owner direction (see the outcome note above), and this entry exists so the
round log agrees with the `Status: GATED` header rather than to claim a cold re-read that did not
happen.
