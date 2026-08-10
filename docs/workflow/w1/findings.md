# w1 findings

> Round log for this item's three gated stages: the drift gate
> (`.claude/skills/drift-gate/`), the impl gate (`.claude/skills/impl-gate/`), and the
> `@codex-review` loop (owned by `.claude/skills/implementation/`). Each stage appends
> rounds under its own heading, created on that stage's first finding; the next-stage
> session fills the dispositions. Findings only — plan maturity lives in `plan.md`,
> delivery status in `pr-body.md`.

## Gate

### Round 1 — 2026-08-09

8 findings, no stamp.

Spot-verification note: every code/config fact sampled this session held except where a
finding says otherwise — `llm_client.py:79,133,157,469,502,507,518,547,556,567,611,651,668`,
`config.py:55-57`, the boto3 `Config` block at `:251-259`, `boto3==1.40.0`, botocore 1.37.38
`ConnectTimeoutError`/`ReadTimeoutError` parentage exactly as §1 states, the six `app.py`
log sites (`236,249,252,266,271,792`), `phi-logging-policy.md:94` (four sites listed, `:266`
and `:792` absent), `onboarding-seam-map.md:27`, `debt-log.md:6-10`, the SPEC-19 chain
(`page.tsx:141` → `route.ts:6` → `gateway/app.py:605` → `ai-assistant/app.py:218`),
`DateField` (`disableFuture` is set on `dob`, `role="dialog"` popover), the `page.tsx`
labels/ids/button text §5 names, all `test_llm_client.py` / `test_ai_intake_instructions.py`
line cites, TODO-58 as the highest id, and `git ls-files .claude` = nine `SKILL.md` files.

| # | SPEC | Finding | Disposition (stage 3) |
|---|------|---------|-----------------------|
| 1 | W1-SPEC-16, 18 | §4's replacement text deliberately keeps the literal "D9" (the clause naming it client-brief misnumbering) while verification step 8 requires `grep -rn 'D9' docs/onboarding-seam-map.md` to return nothing — the two cannot both hold. | **Fixed — step 8 rewritten.** The finding is right that the two cannot both hold; the resolution is to keep the token and change the assertion, not the reverse. §4 now states explicitly that the post-change file holds **one** `D9`, at `:27`, inside the misnumbering clause, and says why (removing it leaves a reader holding the client brief nothing to match on — the same reason `debt-log.md:6-7` keeps it). Step 8 now asserts exactly one occurrence and that `remediation runbook, D9` is gone; **zero occurrences is a fail**. |
| 2 | W1-SPEC-16, 18 | Wrong fact, twice: `.github/workflows/ci.yml` carries D9 at `:112` and `:119`, not `:113` (§4 "deliberately not touched", and step 8's expected residue) — and step 8's residue list also omits `docs/specs-deprecated/w1.md:7`, `docs/workflow/w1/requirements.md:31,41,68,75` and `spec.md:68`, so the step's output cannot be read as pass/fail. | **Fixed — both halves.** §4 now says `ci.yml:112` and `:119`, measured this session. §4 also carries a flag: `e2`'s own requirements cite `:113`, which is neither occurrence; that is `e2`'s artifact at requirements-DRAFT, so it is flagged for its spec stage, not edited here. Step 8's residue check is now a **complete measured table** (nine rows, every path and line), and passes only when the grep output matches it with no unlisted line. |
| 3 | W1-SPEC-13 | Verification step 5's `grep -n '", e)\|, e,$'` cannot match the sixth site: `app.py:792` writes one argument per line, so the line is a bare `e,` and the pattern returns nothing whether or not that site is fixed; §2's `-` block for `:792` shows the args collapsed onto one line, which is not the source's layout. | **Fixed — grep and snippet.** Step 5's pattern is now `grep -nE ', e\)|^[[:space:]]*e,$'`, verified this session to return exactly the six sites on the clean tree (`:236,249,252,266,271` and the bare `e,` at `:796`); the step now runs it pre-change expecting six and post-change expecting zero. §2's `-` block for `:792` is rewritten to the source's real five-line, one-argument-per-line layout, with a note that the deletion is a bare `e,`. |
| 4 | W1-SPEC-16, 18, 20 | The record table contradicts the miss list: rows 16 and 18 assert satisfied-on-`main` while miss #4 is filed against those same ids, and SPEC-20 has no row at all although "16 of 20 statements hold" only reconciles by counting it. For a backfill-of-record item the table is the deliverable. | **Fixed — table and count rebuilt.** Rows 16 and 18 removed from the satisfied table (they are miss #4); a row for SPEC-20 added, naming `page.tsx:154,159`; SPEC-19's and SPEC-20's rows now say production-satisfied, test-only change. The count line is now **14 of 20 hold, six do not** (SPEC-2, 12, 13, 15, 16, 18 — four gaps spanning six ids), which reconciles: 14 satisfied + 6 missed = 20. Miss #4 now also records what *does* hold of SPEC-16/18 so the evidence is not lost. |
| 5 | W1-SPEC-12 | Recorded satisfied-on-`main` (row 12), but the six `str(e)` sites §2 fixes breach SPEC-12's allowlist too (a stringified message is not "status class, latency, token counts, exception class") — the plan closes it, the record denies it was ever open. | **Accepted — SPEC-12 moved to the miss list.** Row 12 deleted from the satisfied table; the scope map's §2 row is now `W1-SPEC-12, W1-SPEC-13`; §2's heading cites both. The evidence the old row carried (`llm_client.py:567-575`, `app.py:226` `log_metadata(req)`) is preserved inside miss #2, with the reasoning made explicit: the rest of SPEC-12 holds, but partial satisfaction is not satisfaction. |
| 6 | W1-SPEC-19 | Double-mapped in the scope map: once in the "Verified satisfied on `main`. No change." row and once to §5, which adds `frontend/app/intake/page.test.tsx`. | **Fixed.** SPEC-19 removed from the "verified satisfied, no change" scope-map row; it now appears once, mapped to §5, worded "production path verified satisfied on `main`; adds vitest coverage. No production change." SPEC-20 given the same single-row treatment. |
| 7 | — (guard sections) | No `## Files touched` section — required by the plan-authoring template and present in `e1`, `w2` and `w3` plans; and Landmines names the §1 PHI-handling zone as touched without recording the human approval the spec's ⚠ human-gate flags demand (cf. `w2/plan.md:636` "this plan's owner review is the planning approval"). | **Both fixed.** A `## Files touched` section now sits before Out of scope — eleven rows, with ⚠ marking the four landmine-zone files. Landmines gains a **Human approval record** bullet on the `w2` precedent: this plan's owner review is the planning approval for the named PHI-handling edits, the code change still rides impl gate → codex review → merge, and the egress-adjacent statements get tests only. |
| 8 | W1-SPEC-19, 20 | §5's stated preconditions ("That needs three fields and two consents") are incomplete: the surface is a four-step wizard (`page.tsx:34,75-80`) whose demographics, consents and submit live on different steps, so each case also needs the step navigation — an omission at odds with the section's own level of detail (it specifies the DateField popover mechanics). | **Fixed — full wizard navigation written out.** §5's setup is now a `submitIntake()` helper the three cases share, walking all four steps: step 0 demographics (three fields, Continue gated on `demoOk`, `page.tsx:73,387`), step 1 insurance left blank on purpose (which also pins the `fetchInstructions` payload shape, `:135-139`), step 2 the two required consents (`:72`, Consent label/input at `:526,533`), step 3 "Submit intake" (`:401`) with `apiFetch` mocked 200 once. Field and Consent label wiring cited so `getByLabelText` is a checked claim, not an assumption. |

### Round 2 — 2026-08-09

3 findings, no stamp.

Round 1's eight are all discharged and re-verified cold this session: step 8 now asserts
exactly one `D9` at `docs/onboarding-seam-map.md:27` with a nine-row measured residue table
that matches `grep -rn 'D9' docs/ .github/ adr/` exactly (`ci.yml:112,119` confirmed, `:113`
carries neither, `e2/requirements.md:132,133,197` confirmed); step 5's
`grep -nE ', e\)|^[[:space:]]*e,$'` returns exactly six lines on the clean tree
(`236,249,252,266,271` and the bare `e,` at `796`); the record table is 14 satisfied + 6
missed = 20 with SPEC-12 moved to the miss list and SPEC-19/20 single-mapped; `## Files
touched` and the human-approval record are present; §5's wizard walk matches the source
(`STEPS:34`, `step:37`, `consentsOk:72`, `demoOk:73`, Continue gate `:387`, "Submit intake"
`:401`, Field `:441,455`, Consent `:526,533`, titles "Consent to treatment" / "Notice of
privacy practices (HIPAA)", DateField popover `:103-131` with `disableFuture`).

Spot-verification note: every other fact sampled held —
`llm_client.py:42-48,79-84,133-138,157-165,251-259,469-471,492-499,500-506,507-517,518-522,546,555,567-575,611,651,668,671-674`,
`LLMError.egressed = True` default (so the plan's inherited-`egressed` claim stands),
`config.py:55-56`, `_GATEWAY_REFUNDED_STATUSES` at `tests/test_ai_intake_instructions.py:629`
= `{401,422,503}` (502 kept-charged, as §Tests says), the `_formatted(record)` idiom in
`tests/test_scheduling_booking_db_error_phi.py:54-57`, `phi-logging-policy.md:94` (four sites,
`:266`/`:792` absent) and rules 1–6 + `services/ai-assistant/redaction.py`, the SPEC-19 chain
(`page.tsx:141` → `route.ts:6` → `gateway/app.py:605` → `ai-assistant/app.py:218`),
`page.tsx:128-163,182-221` and no `next/navigation` import (so mocking `../lib/session` alone
suffices), no existing test asserting any of the six log lines' text, `git ls-files .claude` =
nine `SKILL.md` and no hook in `Makefile`/`ci.yml` (TODO-59 holds), TODO-58 still the highest
id, and `make eval`'s corpus is `db/seed/*` only, so "untouched" is right.

| # | SPEC | Finding | Disposition (stage 3) |
|---|------|---------|-----------------------|
| 1 | W1-SPEC-2 | Wrong fact, stated twice: §1 says the timeout classes are "verified present in `botocore` 1.37.x; `boto3==1.40.0` is the pin" and Landmines says "verified against botocore 1.37.x under the `boto3==1.40.0` pin" — but `boto3==1.40.0` requires `botocore>=1.40.0,<1.41.0` (PyPI metadata, checked this session), so no gate ever runs 1.37.x; 1.37.38 is this machine's ambient anaconda py3.8 botocore, the interpreter `CLAUDE.md` §3 says cannot run the suite. The design survives — `ReadTimeoutError(HTTPClientError, …)` and `ConnectTimeoutError(ConnectionError, …)` are byte-identical at the botocore 1.40.0 tag — but the Version-caveat residual names the wrong verified version. | **Fixed — both statements re-measured under the pin.** Re-verified in `.venv` (python 3.12.13, the 3.12 interpreter `CLAUDE.md` §3 names), which resolves the pin to boto3 1.40.0 / **botocore 1.40.76**; MRO printed this session: `ReadTimeoutError → HTTPClientError → BotoCoreError` and `ConnectTimeoutError → ConnectionError → BotoCoreError`. The boto3 1.40.0 `METADATA` line `Requires-Dist: botocore (<1.41.0,>=1.40.0)` was read from the installed dist-info, not from PyPI. §1 now states the pin admits any 1.40.x and names 1.40.76 as the measured version; the Version caveat says the same and adds the consequence the finding implies — boto3 being pinned does **not** pin botocore, so a rebuild can move it under a frozen boto3, which is exactly what the two class-asserting tests exist to catch. 1.37.x is named as the ambient py3.8 botocore and explicitly not a gate version. |
| 2 | W1-SPEC-12, 13 | Wrong fact in the accepted residual: it cites the still-OPEN Redis-fault sites as `services/gateway/app.py:175,200,203,1022,1054`, but `:1022` is `raise HTTPException(status_code=502, …)` and `:1054` is blank. Only `:175,200,203` are real; the visit-memory/lock sites are `:1063` and `:1095`, plus a fifth at `:1106` (`log.warning(… (%s) …, e)`) the list omits. The numbers were inherited from the register row rather than measured. | **Accepted and fixed — residual re-measured.** All six numbers confirmed this session: `:1022` is `raise HTTPException(status_code=502, detail="assistant returned an unusable response")`, `:1054` is blank, and the real sites are `:175` (`session store refused`, arg `exc`), `:200`, `:203` (healthz), `:1063` (`visit memory unavailable`), `:1095` (`visit lock unavailable`) and the omitted `:1106` (`log.warning("visit lock unavailable on a first turn (%s); proceeding unlocked", e)`). The Landmines residual now reads `:175, 200, 203, 1063, 1095, 1106` and says outright that this corrects an inherited register claim. |
| 3 | W1-SPEC-15 | The scope map row reads "§3 — register row corrected", and §3 rules the neighbouring OPEN rows stay "with their current text" — but finding 2 shows one of those rows (Redis-fault log sites) points at a `raise` statement and a blank line. A register whose locations no longer resolve is not the "live register" SPEC-15 requires, and the plan closes SPEC-15 with no residual naming what stays stale. Either the row's locations are corrected alongside `:94`, or the residual is written down. | **Fixed — the row's locations are corrected, taking the finding's first branch.** The second branch (write the residual, leave the row stale) buys a smaller diff at the cost of shipping a SPEC-15 closure over a register with a known-dead location, which the next sweep re-opens; the standing rule is to take the complete fix rather than the one that needs reversing. §3 now re-measures the Redis-fault row (`:93`) to its six real sites, cited by handler + exception shape like the `:94` row so the numbers cannot re-stale, with **status unchanged at OPEN** — this PR changes no gateway code, so a flip to FIXED would be the lie in the other direction. Scope map and Files-touched rows updated; the SPEC-12/13 scope-boundary residual still names the six sites as OPEN. Verification step 7 gained the check, with its grep measured on the clean tree (eight lines: the row's six plus `:1250`/`:1259`, which belong to the `_post`/`_get` row). Also re-measured every other cited location in the register so this class of finding does not recur: `interop-service/app.py:54` and the `:94` row's `:236,249,252,271` all still resolve; §3 records that. |

### Round 3 — 2026-08-09

2 findings, no stamp. **Round-3 escalation applies** (`.claude/skills/drift-gate/`): both are
open, so the loop stops here and the owner decides each — accept as a named residual,
overrule, or change the spec. The next gate run honors whatever is recorded in the
disposition cells rather than re-flagging.

Rounds 1 and 2 are all discharged and re-verified cold this session. Round 2's three in
particular: the pin resolves in `.venv` to boto3 1.40.0 / **botocore 1.40.76** (printed this
session) with `ConnectTimeoutError → ConnectionError → BotoCoreError` and
`ReadTimeoutError → HTTPClientError → BotoCoreError`, and `EndpointConnectionError` is a
subclass of neither — so the `isinstance` narrow cannot over-capture and the strengthened
`:427` test is meaningful; the Redis residual's six sites `:175,200,203,1063,1095,1106` are
exactly what `grep -nE 'log\.(error|warning)\(.*%s.*, (e|exc)\)$' services/gateway/app.py`
returns minus the `_post`/`_get` pair `:1250,1259` (eight lines total, as step 7 states); the
`:93` row's re-measure and the `:94` row's four-of-six under-report both hold as written.

Spot-verification note: every other fact sampled held. `llm_client.py:42-48` (import block),
`79-84`, `133-138`, `157-165`, `251-259`, `469-471`, `492-499`, `500-506`, `507-517`,
`518-522` (the `except BotoCoreError` block the snippet edits, byte-for-byte),
`546`, `555`, `567-575`, `611`, `651`, `668`, `671-674`; `LLMError.egressed = True` with
`LLMBudgetExceeded` the only `False` override, so the inherited-`egressed` claim stands;
`config.py:55-56`; the six `app.py` log sites (`236,249,252,266,271` + the bare `e,` at `796`,
grep returns exactly six on the clean tree) and the `:234-235` "safe to log" comment;
`phi-logging-policy.md:93,94` and rules 1–6 + `redaction.py`; `onboarding-seam-map.md:27`;
`debt-log.md:6-10`, D4 `:63`, cross-cutting `.env` row `:306`; the full `D9` residue matches
the step-8 table with no unlisted line (`ci.yml:112,119`, `runbook.md:230`,
`specs-deprecated/w1.md:7`, `e2/requirements.md:132,133,197`, `w1/requirements.md:31,41,68,75`,
`spec.md:68`, `adr/0006:63`, `adr/0008:128`); requirements §6 carried verbatim; the SPEC-19
chain (`page.tsx:141` → `route.ts:6` → `gateway/app.py:605` → `ai-assistant/app.py:218`);
`page.tsx:34,37,72,73,128-163,135-139,154,159,165,182-221,387,401,441,455,526,533` and
`DateField.tsx:103-131` with `disableFuture` on `dob` (`:270-271`); `submit()` sets
`result.ok` on a mocked 200 with no `error` key, so the §5 walk reaches the checklist card;
`next/link` reads only the pages-router context and never throws without a provider, so
mocking `../lib/session` alone does suffice; `.eslintrc.json` exists and `lint`/`typecheck`/
`test` are all real npm scripts; `assistant/page.test.tsx:1-28` is the convention §5 copies;
`test_llm_client.py:107,206,361,406,413,420,427,611,656,680,692,703,715,726-728`,
`test_ai_intake_instructions.py:326,608-624` (four parametrize cases today) and
`_GATEWAY_REFUNDED_STATUSES = {401,422,503}` at `:629`, `test_visit_chat_phi.py` (12 tests),
the `_formatted(record)` idiom at `test_scheduling_booking_db_error_phi.py:54-57`;
`CLAUDE.md:133` baseline `923 passed, 1 xfailed, 5 deselected`; TODO-58 still the highest id;
`git ls-files .claude` = nine `SKILL.md` and no hook in `Makefile` or `ci.yml`, so TODO-59's
premise holds; `landmines.md:127` carries the push-hook claim and §3's deliberate-gap list
names none of the gaps this plan closes.

| # | SPEC | Finding | Disposition (stage 3) |
|---|------|---------|-----------------------|
| 1 | W1-SPEC-2 | §1 adds a fifth typed error and re-splits the botocore→typed mapping, but the plan names no downstream cite sweep for it. Two ADRs state the old shape as current: `adr/0004:38-39` enumerates the typed failures as exactly `LLMBudgetExceeded / LLMUnavailable / LLMConfigError / LLMResponseError`, and `adr/0009:78-80` (Status **Accepted**, the live provider decision) states the mapping as `LLMUnavailable` (throttling/5xx/**connection after retries**) — the branch §1 splits. Neither is amended nor listed as deliberately-not-amended. The `w2` precedent (`w2/plan.md:483`) makes that sweep the convention, and this plan already applies the decisions-as-taken reasoning to `adr/0006:63`/`adr/0008:128` for the D9 cites (§4, step 8) — so the doc half of the change got the sweep and the code half did not. | **Owner decision 2026-08-09 — overruled as a plan finding, logged as a TODO.** Not a plan amendment: the ADR drift is doc-registry upkeep of the same class the plan already files (§6), not a design gap, and the code change stands as written. Filed at landing as **TODO-60** (next free id after the plan's reserved 59; re-check both at landing per the standing id rule and renumber if taken): `adr/0004:38-39` and `adr/0009:78-80` enumerate the typed failures / botocore mapping without `LLMTimeout`. Carried in the plan's gate record so implementation inherits it without re-deriving it. |
| 2 | — (registry upkeep) | §6 files TODO-59 for `docs/landmines.md` §3's claim that "a push hook pins the expected xfail and deselected counts", on the measured fact that no such hook exists. `docs/todo.md` — the file the new entry lands in — carries the same false claim in an open entry: TODO-42 states `.claude/hooks/xfail-invariant.sh` "runs the full suite on every push (13.7s warm baseline)" and its whole cost/benefit rests on that hook existing. It is also a dead `.claude/hooks/` name under `CLAUDE.md` §11. Filing the finding against one file while leaving it standing in the destination file is the "confident stale copy wins" failure the sweep exists to prevent — TODO-59 should name TODO-42 as the second instance, or §6 should state why it stays. | **Owner decision 2026-08-09 — overruled as a plan finding, logged as a TODO.** Same call as finding 1: registry upkeep, not design. No new id — **TODO-59 widens at landing** to name `docs/todo.md` TODO-42's `.claude/hooks/xfail-invariant.sh` claim as the second instance of the same dead-hook class alongside `docs/landmines.md:127`. Carried in the plan's gate record. |

### Round 4 — 2026-08-09

Clean — stamped.

No new findings. Round 3's two were owner-decided (overruled as plan findings, logged as
TODO carries — see the dispositions above); nothing else was open. Plan header set to
`Status: GATED 2026-08-09`, with the two TODO carries and the accepted residuals recorded in
its gate record.

## Impl gate

### Round 1 — 2026-08-09

3 findings, no stamp. Branch `fix/noref-llm-timeout-and-phi-log-hygiene` @ `ea11590`.

Re-run this session, not carried from the implementation notes: `make test-docker` →
**`934 passed, 5 deselected, 1 xfailed`**, matching `CLAUDE.md` §6 as this branch sets it
(+11 from 923, xfailed and deselected unmoved — no deliberate gap moved).
`cd frontend && npm test` → 6 files / 58 tests green (3 new); `npm run typecheck` clean;
`npm run lint` shows only the pre-existing `DateField.tsx:103` warning, which is not in the
diff. Plan verification steps 5, 7 and 8 re-run and reproduce as `pr-body.md` records them:
`grep -nE ', e\)|^[[:space:]]*e,$' services/ai-assistant/app.py` → zero;
`grep -nE 'log\.(error|warning)\(.*%s.*, (e|exc)\)$' services/gateway/app.py` → the row's six
plus `1250`/`1259`; `grep -n 'D9' docs/onboarding-seam-map.md` → exactly `:27`, inside the
misnumbering clause. Every changed file traces to a scope-map slice, no unplanned scope.
Code side is clean: no new gateway route, no `_post`/`_get`, no `str(e)` added, no
`Co-Authored-By` trailer, the landmine §1 PHI-logging approval is recorded in the plan's
Landmines section, and no planted defect is disturbed (`_post`/`_get` at `:1250,1259`,
TODO-1, D1, D4, D5b, D11, D13 all untouched). All three findings are in the register text and
the registry-upkeep slice.

| # | SPEC | Finding | Disposition (stage 4) |
|---|------|---------|-----------------------|
| 1 | W1-SPEC-15 | `docs/phi-logging-policy.md:94` names the sixth site as "the `_plan_reply` visit-chat degrade branch"; `_plan_reply` exists nowhere in the repo — the handler is `_reply_items` (`services/ai-assistant/app.py:714`). The row was rewritten to cite by handler *because* line numbers go stale, and its handler name is wrong on the day it lands: the same unresolvable-citation failure it corrects in the row above. | **Accepted — fixed.** Confirmed cold: `grep -rn '_plan_reply' .` returns nothing; the degrade branch (`except llm_client.LLMError as e` → `log.error("visit-chat degrading to deterministic reply (%s, egressed=%s)", ...)`) sits inside `_reply_items` (`services/ai-assistant/app.py:714`). The row now reads "the visit-chat degrade branch in `_reply_items`", and the row's own cite-by-handler sentence gained the check the finding implies: it names both handlers as real symbols with line anchors (`intake_instructions:223`, `_reply_items:714`), so the citation is grep-resolvable rather than asserted. |
| 2 | W1-SPEC-15 | Same edit, the `:93` Redis row: "the `session_store` refusal" is code-fonted as an identifier, but no `session_store` symbol exists in `services/gateway/app.py` — `:175` sits in `redis_unauthenticated`, the `@app.exception_handler(RedisUnauthenticated)` at `:163`. The two `healthz` cites and the three visit memory/lock cites do resolve; this one does not, in a row re-measured this session expressly for resolvability. | **Accepted — fixed, and the same defect found in a third cite.** `grep -n 'session_store' services/gateway/app.py` returns nothing; `:175` is inside `redis_unauthenticated` (`@app.exception_handler(RedisUnauthenticated)` at `:163`). Fixing only the named cite would have left the same class open, so all six were re-cited by containing symbol: the `redis_unauthenticated` handler, the two probes in `healthz` (`:180`, split by `RedisUnauthenticated` / `RedisUnreachable`), and the three visit memory/lock faults in `proxy_visit_chat` (`:1032`). "visit memory"/"visit lock" were log-message text, not identifiers — now attributed to the handler that emits them. Row gained the same grep-resolvability sentence as the `:94` row. Clustered with finding 1: one root cause, cite-by-handler written without checking the handler exists. |
| 3 | — (registry upkeep) | TODO-60 is not filed and the branch does not record a plan-consistent reason. The plan's gate record states it as an owner decision — "Filed at landing as **TODO-60** … carried in the plan's gate record so implementation inherits it without re-deriving it" (round 3, finding 1) — which the impl gate honors rather than re-litigates. `pr-body.md` §Deviations 2 declines on the grounds that "the scope map does not name it", but the gate record is plan content the gate did check (round 4 clean), so the rationale is wrong on fact; the same section also refers the call back to the owner while §"Planned slices absent from the diff" reads "None." | **Accepted — TODO-60 filed.** The finding is right that the gate record is plan content: round 4 stamped the plan clean *with* the record, so "the scope map does not name it" was the wrong test — the owner decision is the instruction, and honoring it is not unilateral scope. Id re-checked at landing per the standing rule: TODO-59 is the highest on this branch, so 60 is free and no renumber is needed. Filed in `docs/todo.md` naming `adr/0004-ai-assistant-service-and-llm-wrapper.md:38-39` and `adr/0009-ai-assistant-bedrock-provider.md:78-80`, both re-read this session, and recording that neither statement is wrong about behaviour (`LLMTimeout` subclasses `LLMUnavailable`) — the drift is that both read as complete enumerations. `pr-body.md` §Deviations 2 rewritten from a declined-and-referred note to the filing record, and the residual list's "**Not yet filed**" tail dropped. |

### Round 2 — 2026-08-09

1 finding, no stamp. Branch `fix/noref-llm-timeout-and-phi-log-hygiene` @ `04a4ea6`.

Round 1's three are discharged and re-verified cold this session. Both corrected register
cites now resolve to real containing symbols, checked by grep rather than read: the `:94`
row's `intake_instructions` is `services/ai-assistant/app.py:223` and `_reply_items` is
`:714`; the `:93` row's `redis_unauthenticated` is `services/gateway/app.py:164` (decorated
`@app.exception_handler(RedisUnauthenticated)` at `:163`, so `:175` is inside it), `healthz`
is `:180` and holds both probes at `:200` (`RedisUnauthenticated`) and `:203`
(`RedisUnreachable`), and `proxy_visit_chat` is `:1032` with the next `def` at `:1234`, so
all three of `:1063`, `:1095`, `:1106` are inside it. TODO-60 is filed at `docs/todo.md:74`,
id 60 still free (59 the previous highest), and `pr-body.md` §Deviations 2 is the filing
record, not the declined-and-referred note.

Re-run this session, not carried from the implementation notes:

- `make test-docker` → **`934 passed, 5 deselected, 1 xfailed`** (28.9s), matching `CLAUDE.md`
  §6 as this branch sets it. +11 from 923; xfailed and deselected unmoved, so no deliberate
  gap moved. The +11 decomposes exactly as §6 claims: 4 timeout tests, 5 parametrized intake
  PHI-negative cases + 1 visit-chat PHI-negative, 1 `("LLMTimeout", 502)` parametrize case.
- `cd frontend && npm test` → 6 files / 58 tests green, `app/intake/page.test.tsx` 3 new.
  `npm run typecheck` clean. `npm run lint` shows only the pre-existing
  `DateField.tsx:103` `aria-required` warning, which is not in the diff.
- Plan verification step 5: `grep -nE ', e\)|^[[:space:]]*e,$' services/ai-assistant/app.py`
  → **zero**. Widened independently — `grep -rnE 'log\.(error|warning|info|exception)'
  services/ai-assistant/*.py` filtered for `str(e)` / `{e}` / `, e` / `exc_info` also returns
  nothing, so no LLM-path site was missed by the narrower pattern.
- Step 7: `grep -nE 'log\.(error|warning)\(.*%s.*, (e|exc)\)$' services/gateway/app.py` → the
  row's six (`175, 200, 203, 1063, 1095, 1106`) plus `1250`/`1259`, the `_post`/`_get` helpers
  on their own OPEN row. Row status still **OPEN** and no gateway code changed.
- Step 8, first half: `grep -n 'D9' docs/onboarding-seam-map.md` → exactly `:27`, inside the
  misnumbering clause, no longer `remediation runbook, D9`.

Scope closes both ways: all ten changed files trace to a scope-map slice (§1 `llm_client.py`;
§2 `app.py`; §3 `phi-logging-policy.md`; §4 `onboarding-seam-map.md`; §5
`frontend/app/intake/page.test.tsx`; §6 `CLAUDE.md` + `docs/todo.md`; Tests table
`tests/test_llm_client.py`, `tests/test_ai_intake_instructions.py`,
`tests/test_visit_chat_phi.py`), no unplanned scope, and no planned slice is absent.
`git diff main...HEAD --stat -- frontend/app/intake/page.tsx` is empty, confirming the
no-production-frontend-change claim. Code side clean: no new gateway route, no `_post`/`_get`,
no `str(e)` added, no `Co-Authored-By` trailer, the landmine §1 PHI-logging approval recorded
in the plan's Landmines section. No planted defect disturbed — `_post`/`_get` (`:1250,1259`),
the interop HL7 parse row, the unhandled-ASGI row and the Redis-fault row all stay OPEN with
their behaviour unchanged, and TODO-1, D1, D4, D5b, D11, D13 are untouched. Traceability holds:
SPEC-2, 12, 13, 19, 20 each have tests naming the id in a comment, and SPEC-15/16/18 are
documentation statements the plan records as test-less by design.

| # | SPEC | Finding | Disposition (stage 4) |
|---|------|---------|-----------------------|
| 1 | W1-SPEC-16, 18 | Plan verification step 8's second half fails at `HEAD`, and `pr-body.md` records it as a pass. The step defines the pass condition as `grep -rn 'D9' docs/ .github/ adr/` matching its nine-row measured table "with no unlisted line"; at `04a4ea6` the output carries a tenth location the table does not list — `docs/todo.md:74`, the `D9` inside TODO-60's "same class as the `adr/0006`/`adr/0008` D9 cites" clause, introduced by the round-1 fix commit itself (`git show main:docs/todo.md \| grep -c D9` → 0). `pr-body.md:148` states the residue "matches the plan's table with no unlisted line", which is false as written, and `:124`'s re-verification after `04a4ea6` re-ran only step 8's seam-map half ("exactly one `D9`"), which is why the drift was not caught. The token itself is benign — it cites the two ADR cites W1 deliberately leaves standing — so this is an evidence-record correction, not a content change: `pr-body.md` must record `docs/todo.md:74` as an expected residue introduced by this branch and stop claiming an unqualified table match. | **Accepted — B, fixed in the evidence record; no code change.** Confirmed cold: `grep -rn 'D9' docs/ .github/ adr/` at `04a4ea6` returns the plan's nine-row table **plus** `docs/todo.md:74`, and `git show main:docs/todo.md \| grep -c D9` → 0, so the round-1 fix commit introduced it. Labelled **B**, not A: `pr-body.md:148` was true when written at `ea11590` and was made false by the round-1 fix — the fix was the new surface, which is the label's definition. No plan amendment: the table is a dated clean-tree measurement, and a residue line the branch deliberately adds (TODO-60, itself a plan instruction per deviation 2) is an expected delta, not drift. `pr-body.md` now states the delta explicitly in the Verification run, with the `git show main` evidence and the reason the token is benign (it names the two ADR cites W1 leaves standing — the table's own disposition for `adr/0006:63` / `adr/0008:128`), and carries it as §Deviations 4. The `:124` re-verification line no longer reads as a full step-8 pass; it says which half moved. Root cause recorded there too: the post-`04a4ea6` re-verification re-ran only step 8's seam-map half. Suite re-run after the edit — `make test-docker` → **`934 passed, 5 deselected, 1 xfailed`** (31.0s), unmoved. |

### Round 3 — 2026-08-09

Clean — stamped. Branch `fix/noref-llm-timeout-and-phi-log-hygiene` @ `04a4ea6`.

No new findings. Round 2's single finding is discharged: `pr-body.md` no longer claims an
unqualified table match — the Verification run states the `docs/todo.md:74` delta with its
`git show main:docs/todo.md | grep -c D9` → 0 evidence, `:124`'s re-verification line names
which half of step 8 moved, and §Deviations 4 carries it. Re-measured cold this session:
`grep -rn 'D9' docs/ .github/ adr/` returns the plan's nine-row table plus exactly
`docs/todo.md:74` and nothing else.

Re-run this session, not carried from the implementation notes or the earlier rounds:

- `make test-docker` → **`934 passed, 5 deselected, 1 xfailed`** (31.3s), matching
  `CLAUDE.md` §6 as this branch sets it. +11 from 923; xfailed and deselected unmoved, so no
  deliberate gap moved.
- `cd frontend && npm test` → 6 files / 58 tests green (`app/intake/page.test.tsx` 3 new).
  `npm run typecheck` clean. `npm run lint` shows only the pre-existing `DateField.tsx:103`
  `aria-required` warning; `DateField.tsx` is not in the diff.
- Plan verification step 5: `grep -nE ', e\)|^[[:space:]]*e,$' services/ai-assistant/app.py`
  → **zero**. Step 7: `grep -nE 'log\.(error|warning)\(.*%s.*, (e|exc)\)$'
  services/gateway/app.py` → the row's six (`175, 200, 203, 1063, 1095, 1106`) plus
  `1250`/`1259`, the `_post`/`_get` helpers on their own OPEN row; row status still **OPEN**
  and no gateway code changed. Step 8: exactly one `D9` in `docs/onboarding-seam-map.md`,
  at `:27`, inside the misnumbering clause.
- Both corrected register cites re-resolved by grep: `intake_instructions:223` and
  `_reply_items:714` in `services/ai-assistant/app.py`; `redis_unauthenticated:164`,
  `healthz:180`, `proxy_visit_chat:1032` in `services/gateway/app.py`.

Scope closes both ways — all ten changed files trace to a scope-map slice (§1
`llm_client.py`; §2 `app.py`; §3 `phi-logging-policy.md`; §4 `onboarding-seam-map.md`; §5
`frontend/app/intake/page.test.tsx`; §6 `CLAUDE.md` + `docs/todo.md`; Tests table
`tests/test_llm_client.py`, `tests/test_ai_intake_instructions.py`,
`tests/test_visit_chat_phi.py`) — no unplanned scope, no planned slice absent.
`git diff main...HEAD --stat -- frontend/app/intake/page.tsx` is empty, confirming the
no-production-frontend-change claim.

Idiom and rule sweep over the diff: no new gateway route, no `_post`/`_get`, no `str(e)` or
PHI-bearing field added on any touched path, no `Co-Authored-By` trailer in either commit,
and the landmine §1 PHI-logging approval is recorded in the plan's Landmines section. No
planted defect disturbed — `_post`/`_get` (`:1250,1259`), the interop HL7 parse row, the
unhandled-ASGI row and the Redis-fault row all stay OPEN with their behaviour unchanged, and
TODO-1, D1, D4, D5b, D11, D13 are untouched. Traceability holds: SPEC-2, 12, 13, 19, 20 each
have tests naming the id in a comment; SPEC-15/16/18 are documentation statements the plan
records as test-less by design; SPEC-1, 3–11, 14, 17 are the verified-satisfied set with no
change proposed.

Negative-test bite checked by reading rather than re-breaking (the gate session does not edit
code): each PHI-negative test plants a marker **inside the exception message** and asserts it
is absent from the *formatted* record, so the assertion cannot pass against a `str(e)` log
site by construction. The break-then-revert runs themselves are recorded in `pr-body.md`
§Verification run (steps 4, 6, 10).

Two enumerations checked for the same drift TODO-60 files against `adr/0004`/`adr/0009`, and
neither is stale: `adr/0007:94-120` reasons about the 502/503 egress split, which `LLMTimeout`
inherits from `LLMUnavailable`, and `adr/0011:305-312` lists the classes that set
`egressed=False`, which `LLMTimeout` does not join. `tests/test_ai_visit_chat.py`'s
`_LLM_FAILURES` matrix has no `LLMTimeout` row, which is correct rather than a gap — the
class is behaviourally identical to its parent for that matrix (`_reply_items` dispatches on
a single `except LLMError` plus the `egressed` attribute, never on exact type), so a row would
add a test count the plan did not budget without adding coverage.

## Review

> PR #69, `@codex-review` by Codex (adversarial).

### Round 1 — 2026-08-10

1 finding. Verdict `needs-attention`, one `[medium]`, no high/critical.

| # | SPEC | Finding | Disposition (A/B/C/E) |
|---|------|---------|-----------------------|
| 1 | W1-SPEC-12 | `services/ai-assistant/app.py:253-254` — the `LLMResponseError` branch now logs the class name only, but `llm_client._result_from_response` raises that class with the Bedrock `request_id` **inside the message**, before the success `log.info` that would otherwise emit it. A schema-drift incident therefore leaves operators a 502 with no id to correlate against the provider's logs, after a paid egress. Recommends carrying safe structured metadata on the exceptions and logging allowlisted fields only. | **A — accepted, fixed.** Reproduced by reading the raise sites cold: `llm_client.py:568` (no text block) and `:577` (missing usage) both fire *before* `:589`'s success log, so their id reached the log only via `str(e)`, which W1-SPEC-13 removed. The finding's premise is right for those two sites and **over-stated for the third**: `complete_structured`'s validation raise (`:692`) fires after `_result_from_response` succeeded, so `:589` already logged the id — that path lost only the join. Fix is the finding's own recommendation, narrowed to `request_id`: `LLMError` gains a `request_id` attribute set by the raiser (the `egressed` idiom, default `None`), passed at all three `LLMResponseError` raise sites, and logged as a **structured field** at the two class-name-only catch sites (`intake_instructions`' `LLMResponseError` branch; the `_reply_items` degrade branch, which swallows the failure into a 200 and so leaves no other record). No provider error code / status was added — that would need a new `ClientError` mapping surface the spec does not carry, and the id is the correlation handle the finding actually argues for. SPEC-13 is untouched: the message is still never logged. |

**Route.** One finding, so no clustering. Not structural — the fix introduces no
counter, TTL, lock, breaker, budget or cache, only an attribute on an existing exception
class and one more `%s` at two log sites — so it is patched on the branch rather than
returned to stage 3. It lands on a PHI log path, so `docs/landmines.md` §3's negative-test
rule applies and is satisfied: both app-level tests plant PHI **inside the exception
message** and assert the formatted record carries the id and not the message, so a fix that
restored `str(e)` to buy the id back would fail them.

**Verification, re-run this round.**

- `make test-docker` → **`940 passed, 5 deselected, 1 xfailed`** (28.8s). +6 from this
  branch's 934: 4 in `tests/test_llm_client.py` (both pre-success raise sites, the
  structured-validation site, and the `None` default), 1 in
  `tests/test_ai_intake_instructions.py`, 1 in `tests/test_visit_chat_phi.py`. **xfailed and
  deselected unmoved** — no deliberate gap moved. `CLAUDE.md` §6 updated to the measured
  number with the decomposition.
- Break-then-revert, all three confirmed red then green: dropping `request_id` from the
  intake log call reddens `test_bad_response_log_carries_request_id_and_not_the_message`;
  dropping it from the degrade call reddens `test_degrade_log_carries_the_provider_request_id`;
  dropping `request_id=request_id` at `llm_client.py:568` reddens
  `test_response_error_carries_request_id_attribute`.
- Plan verification step 5 still holds: `grep -nE ', e\)|^[[:space:]]*e,$'
  services/ai-assistant/app.py` → **zero**. No `str(e)` returned to any LLM-path site.

### Round 2 — 2026-08-10 (dry)

Verdict `approve`. **0 findings** — "I could not support a material blocking finding from
the diff." No findings table: the round is dry and raises no improvement items either. All
14 CI checks green at the reviewed head `73b9f06`.

#### What the dry round actually checked

The round was tagged on `73b9f06`, the round-1 fix commit, so it is a genuine re-read of the
surface r1's fix wrote — not a repeat of the r1 diff. Its ship line names three claims, each
of which is the load-bearing one for a different half of this PR:

- **"The LLM timeout split preserves the existing `LLMUnavailable` contract."** The subclass
  decision, not the timeout mapping — i.e. it checked the thing that could have broken
  callers (ai-assistant's 502 branch, and through it the gateway's ADR 0007 keep-charge
  rule), which is exactly what `pr-body.md` §"Why `LLMTimeout` subclasses `LLMUnavailable`"
  argues and what `test_llm_timeout_subclasses_unavailable` pins.
- **"`request_id` is carried as structured metadata on response errors."** The r1 fix read
  back clean at the level it was argued: an attribute, not a message. The reviewer did not
  re-raise its own r1 recommendation of provider error code / status, which the disposition
  declined as a surface the spec does not carry — so that narrowing held on second look.
- **"The log changes remove exception-message leakage without changing downstream
  status/accounting behavior."** The two properties the negative tests are built around, and
  the pairing r1's lesson says a redaction sweep must assert together.

**What it did not name.** The four documentation slices in the diff (`phi-logging-policy.md`
register rows, the `onboarding-seam-map.md` `D9` cite, `CLAUDE.md` §6, `docs/todo.md`
TODO-59/60) draw no comment in either round. The reviewer is a code-diff reviewer; the
evidence those slices rest on is plan verification steps 7 and 8, re-run at the impl gate and
recorded in `pr-body.md`, not anything this round checked. Read the approve as covering the
code, not the registers.

The harness banner in the comment body ("You've reached your Fable 5 limit") is the bot's own
quota notice, printed above the `<details>` block on both rounds including the round that
returned a real finding. Not a truncation signal and not a finding.

#### Routing

Nothing to route: no code change, no re-gate, no new test. Loop closes at 2 rounds
(1 A-fix in r1, 1 dry) — merge-ready.
