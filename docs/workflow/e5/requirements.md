# E5 Requirements

> Status: AGREED 2026-08-10, amended 2026-08-11 (fact corrections only, owner-approved)
> Source: engagement owner ask, 2026-08-08; widened by owner direction 2026-08-10 (§1, second ask)
>
> **Amendment 2026-08-11** — the e5 drift gate (`findings.md` §Gate round 1) found this document's
> portal-surface measurements wrong. Owner disposition: correct them and cover the missed surface
> rather than carry it as a residual. Three corrections, all factual: §2 and D-8 gain the records
> chart read (`frontend/app/records/page.tsx:78`) as a sixth unchecked read surface; the
> "13 of 17 `apiFetch` call sites check status" claim in §2, §4 and D-8 is corrected to 10 of 17;
> and §6's "unchecked write surfaces" is corrected — those four writes do check status. No
> requirement text changed, no requirement was added or removed, and the scope boundary is where
> it was: E5-REQ-2 always read "a read surface", so the enumeration was catching up to it.
> Open questions closed by owner decision 2026-08-10 — §5 is now the decisions record, and its
> section number is unchanged so cites written against it still point where they did.
> Depends on: `docs/workflow/e4/` — e5 applies a contract e4 freezes. **e4 is DONE**: code merged
> as PR #72 and the delivery record as PR #73, both 2026-08-10. The blocking condition below is
> fully satisfied; the frozen contract is on `main`.
>
> *(Superseded, kept as the record: "e4 is itself DRAFT as of this writing, so nothing here may be
> specced until e4 is agreed." — 2026-08-08.)*

## 1. Raw ask (verbatim)

> e5

Invoked as `/requirement-synthesis e5`, with no accompanying prose. The substance of the ask is
the deferral recorded in the preceding item, quoted in full:

> **D-3 | The estate conversion is deferred to a named item now, not at pickup: `e5`.** Its
> requirement is E4-REQ-11 in §4.
> — `docs/workflow/e4/requirements.md` §6

and the item this document is the other half of:

> **A** — make registration work. **B** — the class fix. **C** — the silent-success amplifier
> (gateway `proxy_intake` off the error-swallowing `_post`).

**This is an engagement-sourced item, not a client ask** (`docs/workflow/README.md:115`). There
is no COO message behind it and none is invented here; the originating need is the one the owner
stated at e4: *take the complete solution over the cheap one that needs reversing later; chunk
delivery, never narrow scope.* e5 is the second chunk.

**Second ask, 2026-08-10 — widen e5 to carry registration idempotency.** Verbatim:

> Widen into e5

Asked in the e4 implementation session while dispositioning PR #72 codex round 1, whose single
`[high]` finding is the lost-confirmation duplicate-registration window (`findings.md` §Review
round 1). The alternatives put to the owner were: widen e5 by one chunk, or open `e7`. The owner
chose e5. e4's own disposition declines the finding as a pre-disclosed accepted residual and names
e5 as its home, so this document is where that routing has to be real — a residual routed to a
document that does not carry it is routed nowhere.

## 2. Context

**What e4 leaves.** e4 converts the registration path off the inherited error-swallowing gateway
helpers and freezes the error contract. Thirteen inherited call sites remain
(`services/gateway/app.py`, re-measured on `main` after e4 merged): eight `_get` at
`:264, 307, 312, 319, 335, 347, 354, 377` and five `_post` at `:359, 366, 382, 389, 1239`. They
span eligibility, records, scheduling, ROI and interop. `_post` and `_get` (`app.py:1249-1265`)
collapse every failure into a **200 OK** `{"error": str(e)}` body and log `str(e)`.

**The conversion targets already exist and are in production use.** `_post_checked`
(`app.py:1299`) and `_get_checked` (`:1267`) relay downstream status, map transport failures to
typed 502/504, and log the exception **class** only. W2 landed three routes on them
(`proxy_review_queue`, `proxy_review_disposition`, `proxy_relevant_records`, all `timeout=30.0`),
and the two `/ai` routes use them. CLAUDE.md §4 already names them the standard and says not to
add a fifteenth inherited caller. e5 is repointing, not designing.

e4 added a fourth converted route and, with it, a second timeout precedent: `proxy_intake`
(`app.py:257`) passes `settings.intake_timeout_seconds`, a configurable value defaulting to 30
(`services/gateway/config.py:74`). So the estate now carries both a literal `timeout=30.0` and a
settings-backed one. e5 takes the literal `timeout=30.0` shape (D-4) — a choice between two
existing precedents, not a new design.

**The portal half, and why it is not optional.** Discovered while drafting e4 and recorded as a
correction there. The portal's inherited read surfaces check no response status:

- `frontend/app/roi/page.tsx:50-52`
- `frontend/app/appointments/page.tsx:31-33` and `:42-45`
- `frontend/app/page.tsx:39-47` (dashboard: appointments and records)
- `frontend/app/records/page.tsx:78-83` (the chart read) — *added 2026-08-11, see the count
  correction below*

Each parses the body and coerces anything non-list to `d.items ?? []` (the records chart read
coerces `json.encounters ?? []` and then says **"No records found for this patient."**). So a
downstream outage today renders as **"you have none"** — an empty appointment list, an empty ROI
queue, a patient with no chart — which is the read-side twin of the registration silent success.
Converting the gateway alone does not change it: `{"detail": …}` is as non-list as `{"error": …}`,
and with no `r.ok` check the page still shows empty. **The gateway conversion is necessary and not
sufficient**; the visible defect closes only when both halves land.

The correct pattern is already in-tree from W2 — `frontend/app/records/page.tsx:96-113` checks
`!res.ok`, then shape-guards the body, and sets an explicit failed state.

**Count correction, 2026-08-11.** This document twice claimed thirteen of seventeen `apiFetch`
call sites already check status, leaving four as the gap. Both numbers were wrong and the pair
was internally inconsistent (13 + 5 enumerated ≠ 17). Re-measured on `main`: **17 non-test call
sites, 10 checking status, 7 not.** The seven are the six read surfaces listed above plus
`frontend/app/components/AppShell.tsx:112` (logout — a write, out of scope per §6). The sixth
read, the records chart read, was missed at this stage and found by the e5 drift gate
(`findings.md` §Gate round 1, finding 3); the owner's disposition 2026-08-11 was to cover it, so
it is folded in here, in D-8, and in E5-SPEC-8 rather than carried as a residual. Its omission is
conspicuous: the pattern this document cites as the one to imitate is the sibling function twenty
lines below it in the same file.

**Zones this crosses** (`docs/landmines.md` §1):

- **ROI / disclosure logic** is an approval-gated zone, and three of the thirteen routes are ROI
  (`proxy_roi_list`, `proxy_roi_create`, `proxy_roi_fulfill`). Error-path only — but the zone is
  entered, so it is gated.
- **The D11 exposure set** includes `proxy_patients`, `proxy_search`, `proxy_records` and
  `proxy_roi_list`. e5 changes their failure behaviour and must not widen what they return.
- **ADR 0010 budget pinning** governs any timeout on a path reaching eligibility;
  `tests/test_eligibility_budget_alignment.py` enforces it and `docs/landmines.md` §1 forbids
  widening either side without re-reading the ADR.
- **`proxy_hl7` has no portal surface at all** — its callers are external interop senders, so
  changing what a bad message is answered with is an outward-facing contract change, not an
  internal one.

**Registries this closes:** the remainder of D4's follow-up line (`docs/debt-log.md` D4 status,
"moving the gateway `proxy_intake` path off the legacy error-swallowing `_post` onto
`_post_checked`" — e4 does intake, e5 does the rest), and CLAUDE.md §4's standing "fourteen
inherited proxy routes" count.

**ID re-homing**, per the `docs/workflow/e2/requirements.md` §4.3 mechanism: E4-REQ-11 →
E5-REQ-1, E4-REQ-12 → E5-REQ-2. e4 §4 keeps them as the record of what was deferred; the live
IDs are the E5 ones.

### 2.1 The second chunk — registration idempotency

**The defect.** `POST /intake` commits the registration and then, on the same request thread,
evaluates the duplicate match key and verifies eligibility before the 201 leaves
(`services/intake-service/app.py:132-144`). A connection drop or a gateway timeout anywhere in
that window leaves a committed patient row while the portal — correctly, per e4's frozen
E4-SPEC-7 — tells the operator the registration was **not saved**. The operator retries. There
is no idempotency key on the request and no uniqueness guard on `patients`, so the retry creates
a second chart with its own coverage and consent rows for one human being.

**It is not e4's doing, and this matters for how it is sized.** `main` before e4 had the same
window and a wider one: it committed the patient, then ran the matcher, eligibility *and* the
consent write before responding (`git show main:services/intake-service/app.py`, lines 127-148).
e4 shortened the post-commit path and made a lost response leave behind a *complete* registration
rather than a possibly consent-less one. What e4 changed is **reachability** — portal registration
worked nowhere before, so nothing could reach the window end to end. e5 is closing an inherited
defect that e4 made observable, not repairing e4.

**What bounds it today, and why that is not enough.** A retry duplicate carries the same SSN and
corroborating demographics, so `_evaluate_match_key` queues the pair for human review under the
tier-1 match key (ADR 0005). Flag, never merge — so the two charts stay split until a human acts,
and each carries its own consents. That is D5, which is open by design; e5 must not close it. The
distinction to hold: **D5 is "one person, several charts, because there is no MPI"; this is "one
submission, several charts, because the request is not idempotent."** A retry duplicate is not a
matching problem — the caller knows it is the same registration and has no way to say so.

**Why it needs its own chunk rather than a patch.** The fix persists state: a client-generated
key and a record binding it to the registration it produced, written in the same transaction. That
means a new table, therefore `db/schema.sql` **and** a migration — an approval-gated zone
(`docs/landmines.md` §1) requiring recorded human approval before any code is written. It also
adds a field to `contracts/intake-registration.json`, the payload declaration e4 froze and both
suites assert. Additive only: e5 may extend that contract, and may not rename, retype or remove
anything in it, or change the error contract e4 froze (§6).

**Rejected framings, recorded so the plan stage does not re-derive them:**

- **A `UNIQUE` constraint on a natural key** (SSN + DOB + name) is cheaper and wrong here: it
  would make "every `/intake` forks a new chart" impossible, which is D5 — a documented planted
  defect. The key must be supplied by the caller, not inferred from the patient.
- **Register-first** (return 201 at the commit, move match and eligibility to async work) is a
  different fix for the same class and stays out of scope (§6). It needs the job/result store
  ADR 0010 defers, and moving eligibility off the request thread would drop the verdict e4 just
  put on the confirmation screen (E4-SPEC-24).
- **Shrinking the window** (background-tasking the post-commit work) does not close the class and
  breaks E4-SPEC-24 the same way.

**Registry this closes:** the idempotency half of D4's follow-up, recorded as the *residual on the
residual* at `docs/debt-log.md:143-146` and in the `intake-service` module docstring.

## 3. Requirements

| ID | Requirement | Notes |
|----|-------------|-------|
| E5-REQ-1 | System: every gateway proxy route surfaces a downstream failure or rejection to its caller as a failure, not as a success response carrying an error body | ⚠ human-gate — gateway error handling; the set includes three ROI routes. Re-homed E4-REQ-11; applies the contract e4 freezes |
| E5-REQ-2 | Front desk / patient: a downstream outage on a read surface is shown as an outage, not as an empty result | Re-homed E4-REQ-12. The user-visible half; `records/page.tsx:96-113` is the in-tree pattern. All unchecked read surfaces, per D-8 (six call sites, corrected 2026-08-11) |
| E5-REQ-3 | System: no gateway proxy log line or response body carries exception text that can embed a request URL or its query parameters | ⚠ human-gate — PHI. The `member_id` leak class; the inherited helpers still log `str(e)` on every route |
| E5-REQ-4 | System: bounding a converted call does not preempt the downstream service's own bounded path | ⚠ human-gate — ADR 0010 pinning on any eligibility-reaching path |
| E5-REQ-5 | System: no route's success behaviour changes — a request that succeeds today returns the same status and body after conversion | the regression floor; this is an error-path change only |
| E5-REQ-6 | System: no route's authorization behaviour changes — same capability, same roles, no new unauthenticated path, and no widening of what the D11-exposed reads return | ⚠ human-gate — RBAC is test-pinned to `config/roles.yaml`; D11 is a documented intentional gap and e5 neither fixes nor widens it |
| E5-REQ-7 | Interop sender: an HL7 message that interop rejects or fails to process is answered as a rejection, not as an acknowledgement | ⚠ outward-facing contract change, taken deliberately per D-2 — the only e5 change whose blast radius leaves the estate |
| E5-REQ-8 | Engineering org: no error-swallowing proxy helper remains reachable, so the class cannot return via a new route | Satisfied by deleting `_post`/`_get` (D-3), so CLAUDE.md §4's "do not add a fifteenth" becomes structural rather than advisory |
| E5-REQ-9 | Engagement owner: the registries stop carrying the gateway conversion as outstanding debt | D4's follow-up line, CLAUDE.md §4's "fourteen inherited proxy routes", and e4 §4's deferral record |
| E5-REQ-10 | Front desk: retrying a registration submission whose outcome was never seen results in one patient chart, not two | The chunk-2 outcome, stated as what the operator gets. Source: PR #72 codex r1 |
| E5-REQ-11 | System: a registration request carries an identifier of the submission attempt, and a repeat of that attempt returns the registration the first one created rather than creating another | ⚠ human-gate — new persisted state, so `db/schema.sql` plus a migration. Extends `contracts/intake-registration.json` additively on the request side only (§6); the replay answers with the original `201` (D-5), and a concurrent collision resolves per D-6 |
| E5-REQ-12 | Front desk: a fresh registration is never mistaken for a retry — a new submission always creates a new chart, including for a patient who is already registered | The D5 guard, stated as a requirement rather than left to the plan. Idempotency must not become an accidental MPI |
| E5-REQ-13 | System: the submission identifier is not derived from and does not carry patient-identifying values | ⚠ human-gate — PHI. A key hashed from SSN/DOB/name would put PHI in logs, error bodies and a new column, and would also violate E5-REQ-12 |

**UI surface.** E5-REQ-2 and E5-REQ-10 are the client-visible outcomes; E5-REQ-7 is the only
requirement with no portal surface, and its exclusion is deliberate (interop has external callers,
not screens). Recorded per the lesson of TODO-44.

**Two chunks, one item.** E5-REQ-1 through E5-REQ-9 are the gateway/portal error-contract
conversion; E5-REQ-10 through E5-REQ-13 are registration idempotency. They share no code and no
seam, so the plan stage may sequence them independently and land them as separate branches.
**They are specced together** (D-1): one frozen spec, one gate. The split option is closed at
this stage — the spec stage inherits the decision rather than re-taking it.

## 4. Assumptions

- ~~**e4 lands first.**~~ **Satisfied, not assumed.** e4 merged 2026-08-10 (PR #72 code, PR #73
  delivery record), so the contract e5 applies is frozen and on `main`. Kept as the record of
  what was blocking.
- ~~`timeout=30.0` matches what W2's three converted routes already use…~~ **Decided, not
  assumed** — D-4. The residual risk the assumption named is unchanged and now accepted: a
  uniform 30s may be wrong for `proxy_search`, which can scan the whole corpus with no `LIMIT`.
  That is D11's problem and out of scope here (§6).
- Converting error paths does not widen D11. The routes return the same rows on success; only
  the failure representation changes. If that is wrong, E5-REQ-6 is the requirement that catches
  it.
- `frontend/app/records/page.tsx:96-113` is the pattern the portal half imitates, not a new
  design. It shipped with W2 and is already the repo's convention for a checked read.
- ~~The four unchecked portal read surfaces listed in §2 are the complete set.~~ **Wrong, and
  corrected 2026-08-11** — there were six, not four, and the measurement behind the claim was also
  wrong (§2, count correction). Re-measured on `main` after e4 merged: 17 non-test `apiFetch` call
  sites, **10** checking status. The unchecked six reads are §2's list; the seventh unchecked site
  is the logout write. e4 added none — its registration path checks status. Kept struck rather than
  deleted because D-8 and E5-SPEC-8 were both sized against the wrong number.
- **The retry that matters is the operator's, not the browser's.** The portal does not retry
  automatically today, so the duplicate arrives because a human re-submits a form the portal told
  them was not saved. If an automatic retry is ever added, the key has to survive it too — but no
  requirement here assumes one exists.
- **The submission identifier is generated at the form, not at the gateway.** A gateway-generated
  key changes nothing: the gateway is inside the window that is lost, so its retry would carry a
  new key. Challengeable, and the plan stage should re-check it against how the portal's
  `apiFetch` boundary is shaped.
- **`consents.kind` needs no schema change and neither does this** — except for the new table.
  No existing PHI column is touched by chunk 2; the migration adds a table and nothing else.

## 5. Decisions

Taken by the engagement owner 2026-08-10, closing the eight open questions this section carried
in DRAFT. Each is binding on the spec stage; a plan that departs from one is drift, not a choice.

| ID | Decision | Consequence |
|----|----------|-------------|
| D-1 | **e5 is specced as one item with two chunks.** Not split back out as `e7`. | One `spec.md` covering E5-REQ-1..13, internally sectioned by chunk; one gate. The plan stage may still sequence the chunks independently and land them as separate branches — §3's two-chunk note stands as guidance, not as a split. |
| D-2 | **`proxy_hl7` converts with the other twelve**, and the outward-facing contract change is documented rather than avoided. | E5-REQ-7 stays in scope. Always-200 is the defect, not the contract: HL7 senders expect ACK/NAK. The spec must state the change as outward-facing, and the PR body must name it — this is the one e5 change whose blast radius leaves the estate. |
| D-3 | **`_post` and `_get` are deleted**, not left unreferenced. | E5-REQ-8 becomes a structural guarantee: CLAUDE.md §4's "do not add a fifteenth" stops being advisory because there is nothing to call. `docs/landmines.md` §2's don't-delete-unused rule is satisfied by a call-site search that must return zero before the deletion lands, and that search is a gate item. |
| D-4 | **Uniform `timeout=30.0`**, except where ADR 0010 binds. | Follows W2's three converted routes rather than e4's settings-backed `proxy_intake` shape; no new config surface. Eligibility-reaching paths stay pinned per E5-REQ-4 and `tests/test_eligibility_budget_alignment.py`. `proxy_search` gets 30s too — its unbounded scan is D11's problem, out of scope here (§6). |
| D-5 | **A replayed registration answers with the original `201` and `patient_id`.** No replay marker, no `200`. | The retry is indistinguishable from success, which is the point: the operator gets the confirmation they lost. `contracts/intake-registration.json`'s response shape is unchanged — chunk 2's additive extension is on the **request** side only. The portal needs no fifth result branch, so e4's four frozen branches (E4-SPEC-6, E4-SPEC-7) hold. |
| D-6 | **On a concurrent collision, the loser waits for the winner and returns the winner's result.** | The `UNIQUE` constraint decides the race; the losing request must then read and replay, not answer "duplicate". The wait is bounded — an unbounded one converts a duplicate into a hang. Naming the mechanism here means the drift gate checks a stated design rather than discovering one. |
| D-7 | **Submission identifiers are kept forever.** No retention window, no pruning. | Removes the horizon past which a late retry silently creates the duplicate the item exists to prevent, and avoids inventing scheduled-job machinery this estate does not have. The table grows at the same order as `patients`; the growth is **accepted and recorded**, and the migration carries an index so it stays cheap to look up. |
| D-8 | **E5-REQ-2 covers every unchecked portal read surface**, not only those on converted routes. | `frontend/app/roi/page.tsx:50`, `frontend/app/appointments/page.tsx:31` and `:42`, `frontend/app/page.tsx:39` and `:44`, `frontend/app/records/page.tsx:78`. All read routes e5 converts, so they fall in naturally. Write surfaces are not added (that would need new ids); 10 of 17 `apiFetch` call sites already check status and are untouched. *(Amended 2026-08-11 by owner disposition of gate finding 3: the enumeration said "four" and listed five call sites, and missed the records chart read entirely. Scope is unchanged in kind — E5-REQ-2's text was always "a read surface" — so this is a corrected measurement, not a widened requirement.)* |

## 6. Out of scope

- **The registration path's error contract** — e4's chunk. e5 must not re-open what e4 froze:
  no field in `contracts/intake-registration.json` is renamed, retyped or removed, the gateway's
  registration error mapping is untouched, and the portal's four result branches keep their
  meanings (E4-SPEC-6, E4-SPEC-7). Chunk 2 **adds** a field to that contract and adds a replay
  path to `POST /intake`; that is the one registration change e5 carries, and it is additive.
  *(Narrowed 2026-08-10 by the second ask. Before then this line excluded the registration path
  entirely.)*
- **Fixing D11 / IDOR and the unbounded `%` search** — e5 touches four routes in the D11 exposure
  set and is required not to widen them (E5-REQ-6), but the fix is sized against the whole set on
  its own item.
- **The booking race** (`scheduling-service/book.py`, RIV-175) and **D5b** — `proxy_book` and
  `proxy_cancel` are converted here; the double-booking defect behind them is untouched.
- **Register-first / async eligibility re-verification** — D4's other remaining follow-up, an
  architecture change rather than a contract fix. It attacks the same lost-confirmation class that
  chunk 2 closes, from the other side (shrink the window rather than make the retry safe), and it
  needs the job/result store ADR 0010 defers. Chunk 2 does not depend on it and does not preclude
  it.
- **D5 / the master patient index** — chunk 2 makes one *submission* idempotent, not one *person*.
  Two genuinely separate submissions for the same patient still fork two charts, still get queued
  as a candidate pair, and still get merged by nobody. E5-REQ-12 exists to keep that true.
- **HL7 AL1/RXA mapping** — `proxy_hl7`'s error contract is in scope; what interop does with a
  well-formed message is not.
- **The portal's *write* surfaces** — booking, cancel, ROI-create and ROI-fulfill
  (`appointments/page.tsx:59`, `:84`, `roi/page.tsx:67`, `:96`), plus logout
  (`components/AppShell.tsx:112`). E5-REQ-2 is a read-surface requirement and D-8 kept it that
  way; covering the writes would need new ids, and the gateway routes behind them are converted
  here either way. *(Corrected 2026-08-11: this bullet called those four writes "unchecked". They
  are not — all four check `!r.ok` and set an explicit error message, crudely but correctly, at
  `appointments/page.tsx:69` and `:85` and `roi/page.tsx:79` and `:97`. The one genuinely
  unchecked write is logout, and it has no result surface to mis-render. Nothing about the scope
  boundary changes; the phantom does.)*
- **Retention or pruning of submission identifiers** — D-7 keeps them forever deliberately. No
  scheduled job, no horizon. The unbounded growth is accepted and recorded, not deferred to a
  future item.
- **CI check routing** — `e3`'s chunk.
- **Correcting the README compliance claim** — TODO-12, human-gated by scenario design.
