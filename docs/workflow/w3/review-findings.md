# w3 codex review findings

> Round log for the @codex-review loop. Rounds appended as review returns; dispositions
> filled by the stage-4 fix session. Delivery status lives in pr-body.md.

## Round 1 — 2026-08-07

2 findings (PR #58, `@codex-review` by JesterCharles). Verdict: needs-attention.
Dispositions: **A, fixed** × 2. One cluster each; the first was fixed as its class
(both places the server loses visit context), not just the flagged 404 instance.

| # | SPEC | Finding | Disposition (r1: A/B/C/E) |
|---|------|---------|---------------------------|
| 1 | W3-SPEC-20 | [high] Expired visits keep the old transcript while the next send starts a new server conversation (`frontend/app/assistant/page.tsx:62-67`). On a 404 the client only clears `visitId`; every prior turn stays rendered in the same `role="log"`, the next message opens a fresh gateway visit with no memory, and a clerk can read the follow-up answer as continuing the visible conversation — mixing stale payer facts with a contextless answer. | **A** — genuine defect in the original push. Fixed as the class, not the instance: a `boundary` turn (`rb-alert--warn`, "New conversation starts here… restate the patient and member details") is appended at **both** places the server loses this visit's context — the 404 path the finding flagged, and the 200-with-`visit_id: null` path (`visit_memory: "unavailable"`), which has the same failure mode and which the original code already treated as "next turn starts fresh" without saying so on screen. Prior turns stay readable (the answer already given was in-context when given); the seam separates them from anything after. No state introduced (render-only transcript entry; no counter/TTL/lock/breaker/budget/cache) → trivial patch on branch, no re-gate. Regression tests: boundary asserted on the 404 flow (extended existing test) and on the null-id 200 flow (new test, landmines §3 negative) — red against the pre-fix page, green with it. |
| 2 | W3-SPEC-22 | [medium] Malformed 200 responses are accepted if they contain only a `reply` string (`frontend/app/assistant/page.tsx:95-112`). A 200 body missing `disclaimer`, `visit_id`, `visit_memory`, or a valid `eligibility` object still renders as a successful answer, silently dropping the safety metadata that distinguishes verified coverage from unqualified text — reachable under version skew or a misrouted proxy response, the exact cases the shape check claims to defend. | **A** — genuine defect in the original push; the code's own comment claimed a defense it only half-implemented. Fixed with `isVisitChat`, a type-guard validating the full contract exactly as the reviewer specified: string `reply` **and** `disclaimer`; `visit_id` null or 32-lowercase-hex (the shape the gateway mints at `security.py:649` and pins inbound at `app.py:711` — verified against the source, not assumed); `visit_memory` ∈ {ok, stale, unavailable}; `assistant` ∈ {ok, degraded, unknown}; `eligibility` null or a non-array object. Any other 200 body renders the fixed FALLBACK and nothing else. No state introduced → trivial patch on branch, no re-gate. Regression tests: 8-case `it.each` (missing disclaimer / visit_memory / assistant / eligibility, unrecognised states, wrong-shape id, non-object eligibility), each asserting FALLBACK shown **and** reply text absent (landmines §3 negative) — red against the pre-fix page, green with it. |

Re-verified after the fixes: frontend `npm test` 29 passed (was 20; +9 from this round),
`typecheck`/`lint`/`build` clean, `/assistant` in the route manifest; `make test-docker`
`821 passed, 1 xfailed, 5 deselected` — exact pinned baseline (this round touches no Python).
Stash-proof: with `page.tsx` reverted to `dc92fc5`, 10 tests red (the 9 new + the extended
404 test); green with the fix. Fix commit on branch after this log's date line.

## Round 2 — 2026-08-07

1 finding (PR #58, `@codex-review` by JesterCharles). Verdict: needs-attention.
Disposition: **A, fixed** × 1.

| # | SPEC | Finding | Disposition (r2: A/B/C/E) |
|---|------|---------|---------------------------|
| 1 | W3-SPEC-22 | [medium] Assistant health `unknown` is accepted but rendered as normal (`frontend/app/assistant/page.tsx:149-150`). `isVisitChat` accepts `assistant: "unknown"` — the state the gateway emits when it cannot recognise ai-assistant's health field during version skew — but the render path only banners `degraded`, so `unknown` is indistinguishable from `ok`. That defeats the backend's explicit tri-state and lets a deterministic or unclassified reply read as a normal tailored answer. | **A** — genuine defect in the original push. **Not B**, checked per metrics §5 step 4: the flagged mechanism is the render predicate `degraded: data.assistant === "degraded"`, present verbatim in `dc92fc5:frontend/app/assistant/page.tsx:116,161` with no `unknown` branch. r1's `isVisitChat` only made the accepted vocabulary *explicit*; the collapse pre-dates it. Fixed by carrying the gateway's tri-state onto the turn (`assistant?: VisitChatResponse["assistant"]` replacing the `degraded` boolean) and giving `unknown` its own honest banner: "The assistant did not report how it produced this reply, so treat its wording as unconfirmed — it may be a standard checklist rather than a tailored one. The coverage verdict above is unaffected." Took the reviewer's first remedy, **rejected the second (reject in `isVisitChat` → FALLBACK)** with reason: the gateway states at `app.py:1180` that `unknown` is the expected reading mid-rolling-deploy, so failing the turn would discard a coverage verdict a real payer call already paid for — the mistake the gateway's own round 3 fixed — and would make every deploy look like an outage. Equally rejected reusing the `degraded` wording, which would claim a checklist we cannot confirm (the false-alarm half of the same gateway comment). No state introduced (render-only) → trivial patch on branch, no re-gate. Regression tests: `unknown` asserts the distinct banner **and** that the turn still succeeds (reply, verdict badge, no `role="alert"`) **and** that the degraded wording is absent; a paired `ok` test asserts neither banner, so a blanket always-warn cannot pass. |

**Lesson for the next round that pins a closed vocabulary.** r1 widened the accepted set to
the gateway's full tri-state and stopped at the door — validated three states, rendered two.
A vocabulary check and a render map are one contract: when a round pins the members, walk each
member to a distinct on-screen treatment or an explicit "renders as nothing, deliberately".
This one landed A on the mechanism test but sat one step from B.

Re-verified after the fix: frontend `npm test` 31 passed (was 29; +2 from this round),
`typecheck`/`lint`/`build` clean, `/assistant` in the route manifest; `make test-docker`
`821 passed, 1 xfailed, 5 deselected` — exact pinned baseline (this round touches no Python).
Stash-proof: with `page.tsx` reverted to the r1 tip `7b5d7d2`, 1 test red (the `unknown`
banner test); the paired `ok` test passes pre-fix by design — it is the blanket-banner guard,
not the discriminator. Fix commit on branch after this log's date line.

## Round 3 — 2026-08-07

1 finding (PR #58, `@codex-review` by JesterCharles). Verdict: needs-attention.
Disposition: **A, fixed** × 1.

| # | SPEC | Finding | Disposition (r3: A/B/C/E) |
|---|------|---------|---------------------------|
| 1 | W3-SPEC-18 / W3-SPEC-22 | [medium] Malformed eligibility status can crash the chat render path (`frontend/app/assistant/page.tsx:66-67`). `isVisitChat` verifies only that `eligibility` is an object, then stores it as a trusted `EligibilityVerdict`; a skewed or misrouted 200 carrying `eligibility: { status: 1 }` passes the guard and `VerdictBadge` later calls `status.toLowerCase()`, throwing during render. Under the same skew path the guard already treats as reachable, an optional badge field takes down the front-desk assistant instead of degrading to the fixed fallback. | **A** — genuine defect in the original push. **Not B**, checked per metrics §5 step 4: `verdictTone`'s `if (!status) return null; TONES[status.toLowerCase()…]` ships verbatim at `dc92fc5:frontend/app/components/VerdictBadge.tsx:29-30`, and `dc92fc5:page.tsx:112` passed `data.eligibility ?? null` to the badge with **no** guard at all — the throw was reachable before r1 existed and r1 narrowed it rather than creating it. Reproduced exactly as described: `TypeError: status.toLowerCase is not a function`. Fixed at **both** ends, which is the r2 lesson applied rather than re-learned — (i) `verdictTone` returns null for any non-string status, so the shared component degrades to no badge instead of throwing for *every* caller, present and future ("outside the vocabulary renders nothing" already was the rule; a non-string is outside it); (ii) `isVerdict` in `isVisitChat` checks the verdict's own declared field types (`active` boolean/null, `status`/`payer`/`checked_at`/`observed_at` string/null), so the guard's `d is VisitChatResponse` claim is true of the nested object too, not just its outer type. Took **both** of the reviewer's alternatives, which are not redundant: the guard keeps a malformed contract off the screen (consistent with the other eight r1 malformed-200 cases — a wrong-typed field is a broken body, unlike r2's `unknown`, which was a *valid* state the gateway means), and the component guarantees no body of any origin can throw inside render, the one failure worse than a missing badge (blank surface, no verdict, no fallback). Unknown **extra** keys pass on purpose and are pinned by a test: strictness that fails on an additive gateway field would turn every deploy into an outage — the r2 reasoning, held. No state introduced (render-only + pure predicate) → trivial patch on branch, no re-gate. |

**Lesson for the next round that hardens a boundary.** r1 validated `eligibility` to the depth
the *type name* suggested (an object) rather than the depth the *consumer* reads (a string field
it lowercases). A guard is only as deep as the field access downstream of it: when a round pins a
shape, follow every field it hands on to where it is dereferenced, and check the leaf, not the
container. Same family as r2 ("validated three states, rendered two") and #49 r2 ("check the
graph, not the job") — three rounds now on one shape: **the round that hardens a boundary must
walk the value to its consumer.**

Re-verified after the fix: frontend `npm test` 37 passed (was 31; +6 from this round),
`typecheck`/`lint`/`build` clean; `make test-docker` `821 passed, 1 xfailed, 5 deselected` —
exact pinned baseline (this round touches no Python). Stash-proof: with `page.tsx` and
`VerdictBadge.tsx` reverted to the r2 tip `997a042`, 5 tests red (4 malformed-verdict fallback
cases + the non-string badge case, the last failing with the reviewer's exact
`TypeError: status.toLowerCase is not a function`); green with the fix. The extra-key positive
passes pre-fix by design — it is the over-strictness guard, not the discriminator. Fix commit on
branch after this log's date line.

## Round 4 — 2026-08-07

0 findings (PR #58, `@codex-review` by JesterCharles). Verdict: **approve**. Loop dry at
4 rounds (3 A-fixes, 1 dry); squash-merged `f69a554`.

No dispositions — no findings to label.

**What the dry round actually checked** (read for coverage, not just for the empty list —
the #49 r3 lesson): the new proxy route `frontend/app/api/ai/visit-chat/route.ts` against
the gateway's visit-chat contract, the assistant surface, `VerdictBadge`, and both test
files, for correctness and contract issues. That is the r1–r3 blast radius re-inspected
after three rounds of patching, which is the confirmation worth having: the three fixes
did not break the contract they were hardening. It did **not** re-check anything outside
the branch diff — the accepted residuals (SPEC-10/11/12/13/17 partials, nav visible to
unauthorized roles, unpinned `maxLength` mirror) are untouched by this verdict and stay
open exactly as `pr-body.md` records them. Its one forward-looking note (keep extending
the two test files as the assistant grows) carries no action this round.
