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
