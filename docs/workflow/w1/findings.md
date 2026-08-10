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
