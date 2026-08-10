# E5 Requirements

> Status: DRAFT
> Source: engagement owner ask, 2026-08-08; widened by owner direction 2026-08-10 (§1, second ask)
> Depends on: `docs/workflow/e4/` — e5 applies a contract e4 freezes. e4's spec was AGREED and its
> plan GATED 2026-08-10, and the code is open as PR #72, so the blocking condition below is
> satisfied for everything except what PR #72's review still moves.
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
(`services/gateway/app.py`): eight `_get` at `:260, 303, 308, 315, 331, 343, 350, 373` and five
`_post` at `:355, 362, 378, 385, 1235`. They span eligibility, records, scheduling, ROI and
interop. `_post` and `_get` (`app.py:1243-1257`) collapse every failure into a **200 OK**
`{"error": str(e)}` body and log `str(e)`.

**The conversion targets already exist and are in production use.** `_post_checked`
(`app.py:1295`) and `_get_checked` (`:1261`) relay downstream status, map transport failures to
typed 502/504, and log the exception **class** only. W2 landed three routes on them
(`proxy_review_queue`, `proxy_review_disposition`, `proxy_relevant_records`, all `timeout=30.0`),
and the two `/ai` routes use them. CLAUDE.md §4 already names them the standard and says not to
add a fifteenth inherited caller. e5 is repointing, not designing.

**The portal half, and why it is not optional.** Discovered while drafting e4 and recorded as a
correction there. The portal's inherited read surfaces check no response status:

- `frontend/app/roi/page.tsx:50-52`
- `frontend/app/appointments/page.tsx:31-33` and `:42-45`
- `frontend/app/page.tsx:39-47` (dashboard: appointments and records)

Each parses the body and coerces anything non-list to `d.items ?? []`. So a downstream outage
today renders as **"you have none"** — an empty appointment list, an empty ROI queue — which is
the read-side twin of the registration silent success. Converting the gateway alone does not
change it: `{"detail": …}` is as non-list as `{"error": …}`, and with no `r.ok` check the page
still shows empty. **The gateway conversion is necessary and not sufficient**; the visible defect
closes only when both halves land.

The correct pattern is already in-tree from W2 — `frontend/app/records/page.tsx:96-113` checks
`!res.ok`, then shape-guards the body, and sets an explicit failed state. Thirteen of seventeen
`apiFetch` call sites already check status; the inherited four are the gap.

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
| E5-REQ-2 | Front desk / patient: a downstream outage on a read surface is shown as an outage, not as an empty result | Re-homed E4-REQ-12. The user-visible half; `records/page.tsx:96-113` is the in-tree pattern |
| E5-REQ-3 | System: no gateway proxy log line or response body carries exception text that can embed a request URL or its query parameters | ⚠ human-gate — PHI. The `member_id` leak class; the inherited helpers still log `str(e)` on every route |
| E5-REQ-4 | System: bounding a converted call does not preempt the downstream service's own bounded path | ⚠ human-gate — ADR 0010 pinning on any eligibility-reaching path |
| E5-REQ-5 | System: no route's success behaviour changes — a request that succeeds today returns the same status and body after conversion | the regression floor; this is an error-path change only |
| E5-REQ-6 | System: no route's authorization behaviour changes — same capability, same roles, no new unauthenticated path, and no widening of what the D11-exposed reads return | ⚠ human-gate — RBAC is test-pinned to `config/roles.yaml`; D11 is a documented intentional gap and e5 neither fixes nor widens it |
| E5-REQ-7 | Interop sender: an HL7 message that interop rejects or fails to process is answered as a rejection, not as an acknowledgement | ⚠ outward-facing contract change; see open question 1 |
| E5-REQ-8 | Engineering org: no error-swallowing proxy helper remains reachable, so the class cannot return via a new route | CLAUDE.md §4's "do not add a fifteenth" becomes structural rather than advisory. See open question 4 |
| E5-REQ-9 | Engagement owner: the registries stop carrying the gateway conversion as outstanding debt | D4's follow-up line, CLAUDE.md §4's "fourteen inherited proxy routes", and e4 §4's deferral record |
| E5-REQ-10 | Front desk: retrying a registration submission whose outcome was never seen results in one patient chart, not two | The chunk-2 outcome, stated as what the operator gets. Source: PR #72 codex r1 |
| E5-REQ-11 | System: a registration request carries an identifier of the submission attempt, and a repeat of that attempt returns the registration the first one created rather than creating another | ⚠ human-gate — new persisted state, so `db/schema.sql` plus a migration. Extends `contracts/intake-registration.json` additively (§6) |
| E5-REQ-12 | Front desk: a fresh registration is never mistaken for a retry — a new submission always creates a new chart, including for a patient who is already registered | The D5 guard, stated as a requirement rather than left to the plan. Idempotency must not become an accidental MPI |
| E5-REQ-13 | System: the submission identifier is not derived from and does not carry patient-identifying values | ⚠ human-gate — PHI. A key hashed from SSN/DOB/name would put PHI in logs, error bodies and a new column, and would also violate E5-REQ-12 |

**UI surface.** E5-REQ-2 and E5-REQ-10 are the client-visible outcomes; E5-REQ-7 is the only
requirement with no portal surface, and its exclusion is deliberate (interop has external callers,
not screens). Recorded per the lesson of TODO-44.

**Two chunks, one item.** E5-REQ-1 through E5-REQ-9 are the gateway/portal error-contract
conversion; E5-REQ-10 through E5-REQ-13 are registration idempotency. They share no code and no
seam — the plan stage may sequence them independently, and if the spec stage finds the item too
wide to gate as one, splitting chunk 2 back out is a cheaper correction than a joint plan that
has to be revised. Recorded now so that decision is available rather than rediscovered.

## 4. Assumptions

- **e4 lands first.** e5 applies a contract e4 freezes; specced before e4 is agreed, e5 would be
  writing against a decision that can still move.
- `timeout=30.0` matches what W2's three converted routes already use, so adopting it estate-wide
  is following a precedent rather than making a new decision — except on eligibility-reaching
  paths, where ADR 0010 governs (E5-REQ-4). Challengeable: a uniform value may be wrong for
  `proxy_search`, which can scan the whole corpus.
- Converting error paths does not widen D11. The routes return the same rows on success; only
  the failure representation changes. If that is wrong, E5-REQ-6 is the requirement that catches
  it.
- `frontend/app/records/page.tsx:96-113` is the pattern the portal half imitates, not a new
  design. It shipped with W2 and is already the repo's convention for a checked read.
- The four unchecked portal read surfaces listed in §2 are the complete set. Measured this
  session: 17 `apiFetch` call sites, 13 checking status.
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

## 5. Open questions

1. **`proxy_hl7` (E5-REQ-7): do external interop senders depend on the current always-200
   behaviour?** HL7 senders typically expect an ACK/NAK, and today every outcome is a 200. This
   is the only requirement in e5 whose blast radius reaches outside the estate, and the repo does
   not record a sender contract. If unknown, the safe options are to convert it behind the same
   contract and document the change, or to hold `proxy_hl7` back as a third chunk.
2. **Uniform `timeout=30.0`, or per-route values?** Uniform matches W2 and is one decision;
   per-route is more honest for `proxy_search` (unbounded corpus scan, no `LIMIT` — D11) and for
   anything eligibility-reaching. Recommend uniform except where ADR 0010 binds.
3. **Does E5-REQ-2 cover all four unchecked surfaces, or only those on converted routes?** The
   dashboard's records call (`page.tsx:44`) reads a route e5 converts, so all four fall in
   naturally; confirming avoids leaving one surface silently empty.
4. **E5-REQ-8: delete `_post`/`_get` outright, or leave them unreferenced?** Deleting makes the
   class unreproducible and is the stronger guarantee; `docs/landmines.md` §2 says not to delete
   code that looks unused without a call-site search, which after e5 would return nothing.
5. **What does a replayed registration answer with (E5-REQ-11)?** Returning the original `201`
   and `patient_id` is the simplest and makes the retry indistinguishable from success, which is
   the point. The alternative — a `200` marking it as a replay — is more honest to a caller that
   wants to know, and the portal has no use for the distinction today. Recommend the replayed
   `201` and record the choice, because the payload contract pins the response shape.
6. **What happens when the retry arrives before the first request commits?** Two requests with
   one key, concurrently. The key's `UNIQUE` constraint decides it, and the loser must then wait
   for or read the winner's result rather than answering "duplicate" to an operator who has seen
   nothing. This is the part of chunk 2 that is genuinely concurrent, and the design gate should
   see it named rather than discovered.
7. **How long is a submission identifier kept?** Kept forever, the table grows without bound;
   pruned, a late retry past the horizon silently creates the duplicate the item exists to
   prevent. A retention window measured against how long an operator might plausibly re-submit
   (minutes to hours, not days) is the likely answer, but it is a decision, and there is no
   scheduled job anywhere in this estate to enforce it.
8. **Does this get a spec of its own?** See §3's two-chunk note — the spec stage decides whether
   e5 is specced as one item or chunk 2 is split back out. Flagged here so it is a stage-2
   decision rather than an accident.

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
- **CI check routing** — `e3`'s chunk.
- **Correcting the README compliance claim** — TODO-12, human-gated by scenario design.
