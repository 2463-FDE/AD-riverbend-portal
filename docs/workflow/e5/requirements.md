# E5 Requirements

> Status: DRAFT
> Source: engagement owner ask, 2026-08-08
> Depends on: `docs/workflow/e4/` — e5 applies a contract e4 freezes. e4 is itself DRAFT as of
> this writing, so nothing here may be specced until e4 is agreed.

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

**UI surface.** E5-REQ-2 is the client-visible outcome; E5-REQ-7 is the only requirement with no
portal surface, and its exclusion is deliberate (interop has external callers, not screens).
Recorded per the lesson of TODO-44.

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

## 6. Out of scope

- **The registration path** — e4's chunk. e5 must not re-open the contract e4 freezes.
- **Fixing D11 / IDOR and the unbounded `%` search** — e5 touches four routes in the D11 exposure
  set and is required not to widen them (E5-REQ-6), but the fix is sized against the whole set on
  its own item.
- **The booking race** (`scheduling-service/book.py`, RIV-175) and **D5b** — `proxy_book` and
  `proxy_cancel` are converted here; the double-booking defect behind them is untouched.
- **Register-first / async eligibility re-verification** — D4's other remaining follow-up, an
  architecture change rather than a contract fix.
- **HL7 AL1/RXA mapping** — `proxy_hl7`'s error contract is in scope; what interop does with a
  well-formed message is not.
- **CI check routing** — `e3`'s chunk.
- **Correcting the README compliance claim** — TODO-12, human-gated by scenario design.
