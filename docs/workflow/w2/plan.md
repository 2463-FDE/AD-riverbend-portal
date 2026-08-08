# W2 Code Plan — retrieval helper, duplicate disclosure, match key + review queue

> Status: GATED 2026-08-08
>
> **Gate record — 2026-08-08, gated fresh-context** (round 2; round 1's four findings
> verified fixed independently). Residual-named SPECs carried into implementation and
> review: **SPEC-3/6** (disclosure lives on the portal surface and in the helper
> response — a raw consumer of the existing `GET /patients/{id}/records` gets none);
> **SPEC-6 failure path** (fail-safe is the frontend's fixed fallback, not a backend
> guarantee); **SPEC-20** (owner-decided — tier 2 deferred, so no-usable-SSN duplicates
> yield no candidate, no disclosure, no queue entry); and the deliberately-stale
> `eval/rag/` root-cause artifacts (SPEC-9/10 baseline), tracked as `docs/todo.md`
> TODO-58 (allocated as TODO-57 in this plan; renumbered at the 2026-08-08 landing per
> §9's own re-check instruction — the doc-drift sweep took TODO-57 in the interim. All
> bare TODO-57 cites below are repointed, dated 2026-08-08; the hedged "as of this plan"
> allocation statements stand as written).
>
> Plan maturity only. The plan header never carries delivery state (IMPLEMENTED, pushed,
> merged) — that lives in `docs/workflow/w2/pr-body.md`. The impl gate does not touch
> this header.
> Workflow stage 3 (code plan). Anchors to the frozen spec `docs/workflow/w2/spec.md`
> (W2-SPEC-1..32, AGREED 2026-08-07). Requirements: `docs/workflow/w2/requirements.md`
> (AGREED 2026-08-07).

## Context

The analysis half of W2 is landed and frozen (`eval/rag/REPORT.md`, ADR 0005, D5a, the
drift gate). This plan builds the un-landed half: the clinician-facing retrieval helper
with duplicate disclosure, the ADR 0005 SSN-corroborated match key at intake, the
front-desk review queue, and the retroactive pass — flag-and-review only, no merges
(ADR 0005 decisions 3–4). Debt anchors: D5a (no MPI), D11 (must not widen), D3-family
(plaintext SSN — matcher adds no copies), D13/D14 (no new vendor egress).

Two facts discovered at plan stage shape the whole design:

- **The eval retriever is local** (`sentence_transformers`, `all-MiniLM-L6-v2`,
  `eval/rag/retriever.py:22,69`) — the estate has no vendor-egress retrieval anywhere,
  and corpus embeddings are already embed-once-cached (`retriever.py:78-91`, pinned by
  `tests/test_rag_eval.py:415-430`).
- **Chart open carries no query text.** The eval's queries come from the goldset;
  a chart open has no question to embed, so semantic retrieval at serve time is
  ill-defined. Serve-time relevance is therefore deterministic salience ranking, and
  the serving path contains no embedding code at all (SPEC-13 by construction).

**Base branch note:** W3 (PR #58, `feat/noref-w3-assistant-surface`) is frontend-only
(9 files; `AppShell.tsx` nav + new `/assistant` surface). W2 implementation branches
from `main` after #58 merges; the only overlap is the `AppShell.tsx` nav array, a
trivial rebase if ordering changes.

**Decisions carried into this plan** (plan-stage, owner-confirmed 2026-08-07):
- Serve-time relevance is **deterministic salience ranking** in records-service; no
  embedding code on the request path. The SPEC-11 corpus cap lands in the eval harness
  (where embeddings actually exist) plus a serve-side row bound.
- Review-queue routes gate on the **existing `patients.write` capability** (held by
  front_desk/admin/staff; excludes clinician/roi_clerk). No new role, no new capability.
- Disclosure is computed by **live matcher evaluation at chart open** (rows sharing the
  opened chart's normalized SSN, classified per ADR 0005), not derived from queue state.
  Folded into the relevant-records response; on endpoint failure the frontend shows a
  fixed "completeness not confirmed" fallback (SPEC-6 fail-safe).
- Retroactive pass is a **CLI inside intake-service** (`docker compose exec`), no new
  route or authz surface. Idempotent via the queue's UNIQUE pair constraint.
- Consequence of the above (design, not re-asked): matcher/queue/hook live in
  **intake-service** (ADR 0005 owner of intake identity), helper + disclosure in
  **records-service**, per-service `matching.py` copies per ADR 0001.

## Scope map (spec → change)

| SPEC | Change |
|------|--------|
| W2-SPEC-1 | records-service `GET /patients/{id}/relevant-records` (salience ranking) + gateway route + records-page panel (§6) |
| W2-SPEC-2 | Frontend fallback: fixed non-PHI literal on fetch/validation failure; chart list renders independently (§6) |
| W2-SPEC-3, 5, 6 | Live matcher classification in the relevant-records response → `rb-alert--warn` banner; banner-only, no sibling ids/links, no blocking (§6) |
| W2-SPEC-4, 17 | Endpoint queries filter on the opened `patient_id` only; negative tests assert sibling records absent even when a cluster exists (§6, V5) |
| W2-SPEC-7, 8, 9, 10 | Backfill-verified against `main` this session — evidence recorded in §8; no change |
| W2-SPEC-11 | Eval: `max_corpus_docs` refuse-over-cap guard in `EmbeddingRetriever` + env/flag; serve: configured scan/return bounds (§7, §6) |
| W2-SPEC-12, 13 | Already satisfied: embed-once cache (`retriever.py:78-91`, pinned test) + serve path with zero embedding code; negative test asserts no embedding import in records-service (§7, V6) |
| W2-SPEC-14, 15, 16 | Class-name-only logging idiom + allowlisted metadata on every new path; helper egresses nothing (no vendor call exists in it); landmines §3 scan tests (V7) |
| W2-SPEC-18 | Helper gateway route reuses `records.read` behind `require_session`; no new capability/role/unauth path (§6) |
| W2-SPEC-19 | Backfill-verified: REPORT.md §1/§2/§4, ADR 0005, D5a, GOLDSET.md all present and traceable (§8) |
| W2-SPEC-20, 21 | `matching.py` (per-service copies) adapted from `eval/rag/data.py` corroboration functions; parity + coherence tests (§1) |
| W2-SPEC-22, 23, 32 | Post-commit match hook in `POST /intake`; queue insert; failure recorded in `match_evaluation_failures`; creation always completes (§3) |
| W2-SPEC-24 | Normalization in memory only; no SSN column in new tables (schema-level guarantee); log scan tests (§2, §3, V7) |
| W2-SPEC-25, 26, 27, 28 | intake-service queue routes + gateway (`patients.write`) + `/review-queue` page; disposition updates queue row only (§5) |
| W2-SPEC-29, 30, 31 | `retro_match.py` CLI: read patients, classify, queue candidate pairs; `ON CONFLICT DO NOTHING`; no patient writes (§4) |

Registry upkeep (no SPEC): `intake.yaml` match_key line, ADR 0005 status flip,
`docs/landmines.md` §1 duplicate-patients bullet and §3 coverage-gap clause, D5a
narrowing, D11 route list, runbook retro-pass procedure, CLAUDE.md §6 baseline re-measure,
`docs/todo.md` TODO-58 (frozen-report staleness), and the full stale-`match_key`/"no MPI"
sweep across code, docs and test comments (§9).

## Implementation

### 1. Matcher module — `matching.py` ×2 (SPEC-20, 21, 24)

New `services/intake-service/matching.py` and `services/records-service/matching.py`
(identical copies, header noting source, per ADR 0001 / seam map "per-service module
copy-paste"). Content adapted from `eval/rag/data.py`, which already implements the
ADR 0005 semantics the spec cites: `normalize_ssn` (`data.py:78`), `is_valid_ssn`
(`:89`), `normalize_name` (`:94`), `_dobs_compatible` (transposition-tolerant, `:144`),
`_addresses_match` (`:156`), `_demographics_corroborate` (`:167`), and — the load-bearing
one — the cluster split and classification in `_split_ssn_cluster` (`:195`) together with
`_all_pairs_corroborate` (`:186`). `resolve_identities` (`:302`) is only the driver loop
over SSN groups and carries none of the semantics; port `_split_ssn_cluster`, not it.
Tier 2 (fuzzy name+DOB, no SSN) is **not** ported — a row without a valid SSN yields no
candidate (SPEC-20 owner note).

**A shared SSN is not one group.** `_split_ssn_cluster` first splits SSN-mates into
connected components under `_demographics_corroborate`, then classifies each component
independently: a component of ≥2 rows that is a clique (every pair corroborates, ≥2 of
similar name / DOB / address) is **candidate**; a component of ≥2 that is not a clique is
**ambiguous** row-by-row (corroboration chains through a bridge row and is not
transitive); a singleton component inside a multi-row SSN group is **non-mergeable**
(conflict). One SSN group can therefore emit a candidate component *and* conflict rows at
the same time — four rows where 1–2 corroborate and 3, 4 corroborate with nobody yield one
candidate pair plus two conflicts. A single verdict per SSN group cannot express that, so
the module never returns one.

Public surface, over plain dicts (`id, name, dob, ssn, address`) so both ORM rows and eval
fixtures feed it:

- `classify_ssn_group(rows) -> list[Component]`, where `Component` is
  `{"patient_ids": [int], "status": "candidate" | "ambiguous" | "conflict"}` — one entry
  per connected component, mirroring `_split_ssn_cluster`'s `Identity` list.
- `candidate_pairs(rows) -> list[tuple[int, int]]` — ordered `(a < b)` pairs drawn from
  **candidate components only**, never spanning two components (SPEC-21).
- `status_for(rows, patient_id) -> "candidate" | "ambiguous" | "conflict" | "none"` — the
  status of the component containing that row; `"none"` when the row has no usable SSN or
  no SSN-mates. This is the disclosure predicate (§6). Asking "does the group classify
  candidate?" would be wrong for a mixed group in both directions.

SSN handled in local variables only — never stored, never logged, never returned in any
log-bound structure (SPEC-24).

Tests: `tests/test_matching_parity.py` — (a) the two service copies are byte-identical
(stricter than the `redaction.py` precedent, whose copies have drifted apart and are
only behavior-parity-tested in `tests/test_redaction.py` — both `matching.py` files are
new, so byte-parity is free and blocks that drift class); (b) coherence with
`eval/rag/data.py`: on the seed fixtures the module classifies the Maria trio
(1042/1330/1588) candidate, and reproduces the eval's ambiguous (bridge-row) and
non-mergeable fixtures from `tests/test_rag_eval.py`; (c) **the mixed group** — one SSN,
a corroborating pair plus two mutual non-corroborators — where `classify_ssn_group`
returns three components, `candidate_pairs` returns exactly the one in-clique pair, and
`status_for` returns `candidate` for the pair members and `conflict` for each outlier.

### 2. Schema — migration `009_duplicate_review_queue.sql` (SPEC-24, 25, 31, 32)

⚠ Approval-gated zone (migrations). Both `db/schema.sql` and the new migration carry the
same tables, columns, and constraints (hand-sync rule, landmines §2) — but **not the same
`CREATE TABLE` form**, because the two files do not use the same one today. Verified this
session: all 12 tables in `db/schema.sql` use `CREATE TABLE IF NOT EXISTS` (`:15`–`:161`)
and every migration uses the plain form (`001_init.sql:4`, `008_roi_requests.sql:9`).
So:

- `db/migrations/009_duplicate_review_queue.sql` — plain `CREATE TABLE` (snippet below
  verbatim), preceded by the `003+` header convention (`-- 009_duplicate_review_queue — …`
  / date+org line / rationale lines, as in `008_roi_requests.sql:1-7`).
- `db/schema.sql` — the same two blocks appended with `CREATE TABLE IF NOT EXISTS`
  substituted, under a `-- ---` section comment matching the ROI/disclosures blocks
  (`schema.sql:140-144`), column names aligned to the file's existing gutter.

Nothing else differs between the two copies; the implementer picks nothing.

```sql
CREATE TABLE duplicate_review_queue (
    id SERIAL PRIMARY KEY,
    patient_id_a INTEGER NOT NULL REFERENCES patients(id),
    patient_id_b INTEGER NOT NULL REFERENCES patients(id),
    source TEXT NOT NULL,                 -- 'intake' | 'retroactive'
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending' | 'dispositioned'
    disposition TEXT,                     -- 'duplicate_confirmed' | 'not_duplicate'
    decided_by TEXT,
    decided_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_review_pair_order CHECK (patient_id_a < patient_id_b),
    CONSTRAINT uq_review_pair UNIQUE (patient_id_a, patient_id_b)
);

CREATE TABLE match_evaluation_failures (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    error_class TEXT NOT NULL,            -- exception class name only, never a message
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Design points: ordered pair + UNIQUE is the SPEC-31 idempotency mechanism (insert with
`ON CONFLICT DO NOTHING`); **no PHI columns** — ids, enums, timestamps, and a username
only, so SPEC-24's "no new stored SSN copy" holds at schema level; `error_class` mirrors
the class-name-only logging idiom. **No new indexes** — D8's "zero CREATE INDEX"
condition is a registered deliberate defect; the SSN scan in §6 stays a sequential scan
on purpose (residual, see Landmines). No seed rows → `db/seed/generate_seed.py`
untouched → drift-gate seed byte-compare unaffected.

ORM models for both tables go in `services/intake-service/models.py`;
`duplicate_review_queue` is mirrored in `services/records-service/models.py` only if §6
needs it (it does not — disclosure is live evaluation, not queue reads).

### 3. Intake match hook (SPEC-22, 23, 24, 32)

`services/intake-service/app.py` — at the D5 seam (`app.py:93-95`, the flagged-not-fixed
comment block), **after** `_create_patient` commits (`app.py:131-134`) so registration
can never be blocked by matching:

```
patient_id = _create_patient(db, req.demographics)   # existing, committed
_evaluate_match_key(db, patient_id, req.demographics) # new — never raises
```

`_evaluate_match_key`: whole body in `try/except Exception`. Normalize the new row's
SSN in memory; if invalid/absent → return (tier-2 deferred, SPEC-20). Else load only the
rows sharing that normalized SSN — normalization happens **in the WHERE clause, not by
pulling the table into memory**:

```sql
SELECT id, name, dob, ssn, address FROM patients
 WHERE ssn IS NOT NULL AND regexp_replace(ssn, '\D', '', 'g') = :normalized
```

No new column, no stored SSN copy (SPEC-24) — an expression over the existing plaintext
column, matching `normalize_ssn`'s digits-only rule. Then run `matching.candidate_pairs`
over the returned rows and insert one queue row per returned pair (`ON CONFLICT DO
NOTHING`), `source='intake'`. Pairs come from candidate components only, so ambiguous and
conflict rows contribute none, and no pair ever spans two components (SPEC-21). Note the
insert set is not restricted to pairs involving the new row: a new row can complete a
clique among rows that were previously ambiguous, and those pairs are genuinely newly
queueable. On any exception: log
`type(e).__name__` only (the service idiom, `app.py:141` pattern), insert a
`match_evaluation_failures` row in its own guarded transaction, and return — the 201
response is unaffected either way (SPEC-23/32). Log lines carry `patient_id`, counts,
and class names only (PHI policy rules 2–3).

Update `services/intake-service/intake.yaml:3` → `match_key: ssn_corroborated` with a
comment pointing at ADR 0005 (flag-and-review, tier 2 deferred). Safe: the drift gate
and `tests/test_rag_eval.py:498` pin the *report render* (a string literal at
`eval/rag/report.py:143`), not this file; `test_match_key_none_mirrors_current_intake`
(`tests/test_rag_eval.py:79-81`) is a pure fixture function, also unaffected.

Tests: `tests/test_intake_match_key.py` (sibling-pinning idiom from
`tests/test_intake_db_error_phi.py:27-43`): candidate → 201 + queue rows; ambiguous and
non-mergeable fixtures → 201 + no rows; **mixed group → 201 + exactly the in-clique pair
queued, no pair naming the conflict row**; matcher raises → 201 + failure row + class-only
log; repeat intake of the same person → no duplicate queue rows; adversarial log-scan
tests: SSN (dashed and bare) planted in `name`/`address`/exception message never
appears in any log record (landmines §3 end-to-end scan pattern).

### 4. Retroactive pass CLI (SPEC-29, 30, 31)

New `services/intake-service/retro_match.py` — `python retro_match.py` inside the
container (`docker compose exec intake-service …`), documented in `docs/runbook.md`.
Reads all patients (`id, name, dob, ssn, address`), groups by normalized valid SSN,
runs `matching.candidate_pairs` per group, inserts every returned pair
(`source='retroactive'`, `ON CONFLICT DO NOTHING`), prints counts + pair ids only
(`patient_id` is the allowlisted identifier — PHI policy rule 2). This is the whole-table
pass, so it reads every row by design — unlike §3 and §6, which prefilter in SQL.
SELECT + queue INSERT only — no patient writes (SPEC-30). Re-run inserts nothing new
(SPEC-31); already-dispositioned pairs are also blocked by the same UNIQUE constraint
(status is not part of the key, deliberately — a dispositioned pair is never re-queued).

**The CLI is also the reader for `match_evaluation_failures`** (SPEC-32). Without it that
table has no consumer anywhere — a write-only table is the D2 failure mode inverted
(`audit_logs` has no writers), and "the failure is recorded" would mean "visible in psql
to whoever thinks to look". The run therefore ends by printing the distinct
`error_class` counts and how many of those `patient_id`s the pass has just re-evaluated,
which is exactly the SPEC-32 "remains eligible for a later retroactive pass" claim being
discharged rather than asserted. The runbook procedure (§9) reads that block.

Tests: `tests/test_retro_match.py` — stubbed session over the seed fixtures: Maria trio
yields exactly the 3 pairs (1042,1330)/(1042,1588)/(1330,1588); second run inserts 0;
patients table untouched (assert no add/delete/update on patient objects); ambiguous
fixture yields 0 pairs; a seeded `match_evaluation_failures` row appears in the printed
summary and its patient is covered by the pass.

### 5. Review queue — service routes, gateway, portal (SPEC-25..28)

**intake-service** (`app.py`):
- `GET /review-queue` → pending pairs, each with per-patient `{id, name, dob,
  created_via, created_at}` (minimum needed to judge a pair; **no SSN, no address** —
  front-desk minimum-necessary is an open debt row, not widened here), plus
  `source, created_at`.
- `POST /review-queue/{pair_id}/disposition` body
  `{"disposition": "duplicate_confirmed" | "not_duplicate", "decided_by": str}` →
  updates the queue row to `dispositioned` + stamps `decided_by`/`decided_at`; 404 on
  unknown id, 409 if already dispositioned. Touches only `duplicate_review_queue`
  (SPEC-27). Schemas in `schemas.py` incl. a `log_metadata`-style allowlist for the one
  request log line.

**gateway** (`services/gateway/app.py`):
- New `_get_checked(service, path, timeout, params=None)` mirroring `_post_checked`
  (`app.py:1222-1258`): typed 504/502 relay, class-name-only logging, never `str(e)`.
  The 14 legacy `_get`/`_post` routes are **not** migrated (open half of D4,
  approval-gated, untouched) — new routes simply never use the swallowing helpers
  (CLAUDE.md §4 "do not add a fifteenth").
- `GET /review-queue` → `require_capability("patients.write")` →
  `_get_checked("intake", "/review-queue", timeout=30.0)`.
- `POST /review-queue/{pair_id}/disposition` → same capability →
  `_post_checked("intake", …, {**payload, "decided_by": session["username"]},
  timeout=30.0)` — the deciding user comes from the session hash
  (`security.py:275-279` stores `username`/`role`), never from the client body
  (client-supplied `decided_by` is discarded).
- Both routes added to `EXPECTED_ROUTE_CAPABILITIES`
  (`tests/test_gateway_authz.py:105-123`) — a deliberate, in-plan edit of a pinned
  test. Denial tests added: clinician and roi_clerk → 403 on both routes; anonymous →
  401 (SPEC-28, landmines §3 negative-test rule).

**frontend:** BFF routes `app/api/review-queue/route.ts` and
`app/api/review-queue/[id]/disposition/route.ts` (7-line `proxy(...)` shape,
`app/api/ai/visit-chat/route.ts` precedent). New page `app/review-queue/page.tsx`
(W3 assistant-page patterns: `apiFetch`, fixed non-PHI notice literals, 401 →
`clearSession()`+redirect, 403 → blocked notice, response type-guard before render).
Lists pending pairs side-by-side with Confirm-duplicate / Not-a-duplicate actions;
a dispositioned pair leaves the list (SPEC-26). Copy states the disposition records a
judgment and merging is a manual HIM procedure. Nav entry in `AppShell.tsx` NAV array
(visible to every signed-in role, gateway enforces — the W3 nav decision, recorded at
`AppShell.tsx:33-38`). Tests `app/review-queue/page.test.tsx` (mock `apiFetch`,
explicit `afterEach(cleanup)`, no vitest globals).

### 6. Relevant records + disclosure (SPEC-1..6, 17, 18, 11-serve, 13)

**records-service** (`app.py`): `GET /patients/{patient_id}/relevant-records` →

```json
{ "patient_id": 1042, "duplicate_disclosure": "candidate" | "none",
  "items": [ { "record_id": 7, "kind": "lab_result", "title": "...",
               "occurred_at": "...", "reason": "allergy" | "medication" | "recent" } ] }
```

- **Ranking (deterministic):** load the opened patient's encounters + records (existing
  query shapes, `app.py:90-140`; the N+1 stays — D8 is deliberate); rank records whose
  encounter carries non-empty `allergies` first, then non-empty `medications`, then by
  `occurred_at` descending; return top `settings.relevant_records_max_items`
  (default 10), scanning at most `settings.relevant_records_max_scan` (default 500)
  records — both env-driven in `config.py` (SPEC-11 serve bound). Items carry titles +
  dates + reason tags, not record bodies — the panel links attention, the chart below
  it remains the record view. 404 on unknown patient (mirrors `app.py:72-87`).
- **Disclosure:** rows sharing the opened patient's normalized SSN are loaded with the
  same SQL-side `regexp_replace(ssn, '\D', '', 'g') = :normalized` prefilter as §3 — the
  whole `ssn IS NOT NULL` population is never pulled into records-service memory, which
  matters because this is a per-chart-open path, not a per-registration one. The response
  is `"candidate"` iff `matching.status_for(rows, patient_id) == "candidate"` — the
  status of the component **containing the opened patient**, not a verdict over the SSN
  group, so a mixed group discloses correctly for each of its rows. Ambiguous / conflict /
  no-SSN / no SSN-mates → `"none"` (SPEC-3 owner note, SPEC-21). Queue state plays no
  part, so the disclosure survives dispositions until charts are actually merged by HIM.
- **Scoping:** every query filters on the opened `patient_id`; sibling ids never appear
  in the response in any field (SPEC-4/5/17 — the disclosure is a bare enum). Failure
  → `SQLAlchemyError` → 503 class-name-only (service idiom `app.py:60-62`).

**gateway:** `GET /patients/{patient_id}/relevant-records` →
`require_capability("records.read")` (the chart-read capability — SPEC-18: no new
capability, no new role, `require_session` chain unchanged) → `_get_checked("records",
…, timeout=30.0)`. Added to `EXPECTED_ROUTE_CAPABILITIES`; denial tests: front_desk →
403, anonymous → 401. D11 note: the route is per-patient-id and session-not-patient-
bound exactly like the existing chart read — the gap is inherited in kind, not widened in
kind (no new cross-patient query surface, no search parameter, no new capability). But the
*exposure set* grows by one route, and `docs/debt-log.md:267` currently anchors D11 at
`records-service/app.py:91` alone while `docs/landmines.md` §1 says to size the D11 fix
against the whole set. A route that is not on the list does not get sized. So the D11 row
gains this endpoint (§9) — registry upkeep, not a fix.

**frontend:** `app/records/page.tsx` (the de facto chart-open surface — no
`patients/[id]` page exists) gets, above the existing encounter list:
- a relevant-records panel (`Card`) fetched from
  `app/api/patients/[id]/relevant-records/route.ts` (new BFF proxy) after the chart
  fetch; chart rendering is independent of this fetch (SPEC-2);
- `duplicate_disclosure === "candidate"` → `rb-alert--warn`, `role="status"`, fixed
  literal: sibling charts may exist, the shown record set may be incomplete, merging is
  handled by HIM — **no sibling ids, no links, nothing blocked** (SPEC-3/5/6);
- fetch failure or type-guard failure → fixed non-PHI literal: relevant-records
  unavailable **and** duplicate-chart status not confirmed — treat the record set as
  possibly incomplete (SPEC-2 deterministic fallback carrying the SPEC-6 fail-safe).

Tests `app/records/page.test.tsx`: panel renders items; candidate → banner with no
sibling ids in the DOM; `"none"` → no banner; rejected fetch → chart list still
renders + fallback text (negative: no upstream error string reaches the DOM).

### 7. Eval corpus cap (SPEC-11, 12, 13)

`eval/rag/retriever.py`: `EmbeddingRetriever.__init__` gains
`max_corpus_docs: int` (default from `RAG_MAX_CORPUS_DOCS`, default 1000); `_load()`
raises `RuntimeError` naming the cap and the actual size when exceeded —
**refuse, never truncate** (silent truncation would change scores under a green gate).
`run.py` passes it through (`--max-corpus-docs` flag). Current corpus is 5 docs → no
behavior change, REPORT.md byte-identical, drift gate untouched (its report re-render
uses the stub path, which has no cap — the cap guards the embedding spend, which only
the embed path incurs). SPEC-12/13 need no new code: cache pinned by
`tests/test_rag_eval.py:415-430`; a new test asserts **no module in
`services/records-service/` (the whole directory, not just `app.py` — `matching.py`,
`config.py`, and `schemas.py` are equally capable of importing one)** references an
embedding or vendor SDK, so the serve path has no embedding code by construction.

Tests: cap-exceeded raises before any `encode` call (assert via the existing
`encode_log` seam); cap ≥ corpus → unchanged behavior.

### 8. Backfill verification of record (SPEC-7..10, 19) — evidence, no change

Verified against the working tree this session:

- **SPEC-7** — REPORT.md §2 (`REPORT.md:21-31`) measures each chart against the union
  of its cluster (`metrics.fragment_coverage_gap`, `metrics.py:92-113`); per-identity,
  not per-chart. ✓
- **SPEC-8** — §4 prose (`REPORT.md:55`): "Passing this gold-set does not mean the
  clinician sees a complete record…". Gold-set agreement is never presented as
  completeness evidence anywhere in the report. ✓
- **SPEC-9** — `db/seed/goldset.json` retained; bytes pinned by `corpus.sha256`
  (fingerprint spans patients.csv/encounters.csv/goldset.json, `check_drift.py:159,
  305-315`); §4 records why passing is insufficient. ✓
- **SPEC-10** — `eval/rag/check_drift.py` fails (exit 1) on seed, fingerprint, goldset
  or report drift; runs in CI (`.github/workflows/ci.yml:102-110`) and `make eval`.
  Baseline = today's committed REPORT.md per the owner decision. ✓
- **SPEC-19** — candidate rate: REPORT §1 (`REPORT.md:7`, computed by
  `metrics.candidate_duplicate_rate`); allergy gap: REPORT §2 + D5a; gold-set foil:
  REPORT §4 + GOLDSET.md; intake root cause: REPORT.md:19 + ADR 0005 + D5a — each
  traceable to the eval run that produced it. ✓

No gap found → no finding to file; this section is the verification record.

### 9. Registry upkeep (no SPEC)

- `adr/0005-mpi-match-key.md`: Status Proposed → Accepted in the implementation PR
  (requirements §4: the status moves only through this gated path).
- `docs/landmines.md` §1 "Duplicate patients" bullet: match key now evaluated at create
  (tier 1 only, flag-and-review); existing duplicates remain until HIM merges.
- `docs/debt-log.md` D5a: narrow to "candidate flagging live (W2); tier 2 deferred;
  merges manual".
- `docs/debt-log.md` D11 (`:267`): add `GET /patients/{patient_id}/relevant-records` to
  the row's location list. The row anchors `records-service/app.py:91` alone today, and
  `docs/landmines.md` §1 requires sizing the D11 fix against the whole exposure set —
  an unlisted route is an unsized one. Status stays OPEN; nothing is fixed here.
- `docs/runbook.md`: retroactive-pass procedure, including reading the CLI's
  `match_evaluation_failures` summary (§4) — that block is the only operator-facing view
  of a recorded match failure.
- `docs/landmines.md:123` (§3 deliberate-coverage-gap list) asserts "no input-normalization
  or **duplicate-patient tests** (RIV-201)". §4 of this plan adds three duplicate-patient
  suites (`test_matching_parity.py`, `test_intake_match_key.py`, `test_retro_match.py`),
  so that half of the clause stops being true, and §3 is the tracked source of truth for
  which gaps are deliberate. Amend the clause to keep the input-normalization half open
  (W2 adds no intake input canonicalization — the matcher's internal `normalize_ssn` /
  `normalize_name` are matcher-side only) and record the duplicate-patient half as closed
  by W2. **A moved gap is itself a reportable event** (`docs/landmines.md` §3, CLAUDE.md
  §6): the closure is deliberate and in-plan, so it is named here, in the PR body, and in
  the CLAUDE.md §6 baseline note — not silently absorbed into a new pass count.
- CLAUDE.md §6 baseline: re-measure passed count after the new tests land (xfail=1,
  deselected=5 must be unchanged — moved means a deliberate gap moved).
- `docs/todo.md`: new entry at the next free id (**TODO-57** as of this plan; ids are
  allocated once and never renumbered, so re-check the tail before writing) recording the
  deliberately-stale `match_key: none` artifacts — `eval/rag/REPORT.md:19`, its renderer
  `eval/rag/report.py:143`, and `eval/rag/data.py:310`'s "intake's current behavior"
  docstring — with the reason they stay (frozen measured baseline, SPEC-9/10) and the
  condition that clears them (whichever change next moves the baseline legitimately).
  Without this the falsehood is tracked only in a workflow artifact, and the registry
  contract (`docs/todo.md:8-11`, CLAUDE.md §8) puts an unscheduled loose end owned by
  nobody in `todo.md`, which is where a doc-drift sweep looks. `tags: hygiene · src:
  eval/rag/REPORT.md:19, eval/rag/report.py:143, eval/rag/data.py:310`.
- Stale `match_key: none` / "no MPI" claims this change falsifies — amend the prose, do not
  delete the tests or the schema note. Full site list, from a repo-wide sweep this session
  (`grep -rn "match_key: none\|no MPI\|no match key\|match-key lookup"`):
  - `services/intake-service/app.py:93-95` — the `# D5 (flagged, not fixed): no MPI /
    match-key lookup on (name, dob, ssn). Every intake inserts a brand new chart…` block
    sits **directly above** the new hook (§3 lands at this seam). Amend in the same edit
    that adds the call, or the file contradicts itself line-to-line: match-key evaluation
    is now live (tier 1, flag-and-review); the second sentence stays true — every intake
    still inserts a new chart, because W2 merges nothing.
  - `services/intake-service/app.py:16` — module docstring, "one person forks into
    several charts (intake.yaml match_key: none)"
  - `ARCHITECTURE.md:103` — "self-service intake has no MPI/match key; one person can
    become several charts (RIV-160)". First clause false after §3, second clause stays
    true. Amend the first only.
  - `docs/runbook.md:99` — the RIV-160 incident entry's "(no match key)" parenthetical.
    Amend, and point the reconcile step at the review queue (§5) and the retroactive pass
    (§4), which is where the operator now finds the pairs.
  - `docs/onboarding-seam-map.md:25` — walls table, "**Patient identity** (D5, no MPI) |
    Every intake creates a new chart; `patient_id` is not stable per person." The wall
    stays a wall and both consequences stay true (no merges in W2); the "no MPI" label
    narrows to "tier-1 match key, flag-and-review only". Do not downgrade the row.
  - `tests/test_intake_schemas.py:113-115` ("no MPI/match key" coverage-gap NOTE)
  - `tests/test_rag_eval.py:80` ("intake today")
  - `docs/landmines.md` §1 bullet at `:63` — covered by the third bullet of this section.
  - `db/schema.sql:44-45` NOTE — its first clause stays true (there is still no DB-level
    unique match key; matching is application-level flag-and-review) but its second
    sentence, "See intake.yaml match_key: none.", becomes a false cite. Amend that
    sentence only; the DDL and the rest of the note are untouched.
  - Deliberately **not** amended, each for a stated reason: `adr/0005-mpi-match-key.md:11`
    (ADR context is decision-as-taken; only the Status flips), `docs/specs-deprecated/w2.md:7,
    20,50` (archive — the registry contract says it is not written to),
    `tests/test_rag_eval.py:498` and `tests/test_drift_check.py:467` (they pin the frozen
    report render and the eval's address handling, not intake's behavior), and the three
    `eval/rag/` sites above (frozen baseline — carried to `docs/todo.md` instead).
- `services/intake-service/intake.yaml` is served verbatim by `GET /intake/config`
  (`app.py:70`). Verified this session: no gateway proxy route, no frontend reference, no
  test asserts `match_key` through that endpoint, so the flip changes no consumer.
- REPORT.md and `report.py:143` stay **unchanged** — the report is the frozen measured
  baseline (SPEC-9/10) and the literal is hardcoded render prose, not a read of
  `intake.yaml`, so `make eval` and `tests/test_rag_eval.py:498` both survive the flip.
  Same for `eval/rag/data.py:310`, whose docstring calls `"none"` "intake's current
  behavior" — the eval keeps simulating both modes and the drift gate compares against the
  frozen report, so changing the docstring alone would buy nothing and changing the mode
  would move the baseline. Consequence recorded twice: as a residual below, and — so it
  outlives this workflow bundle — as the new `docs/todo.md` entry above.

## Slice order

The sections above are grouped by subsystem, not by build order. The TDD loop
(`.claude/skills/tdd/`) takes them in dependency order:

1. §1 matcher (`matching.py` ×2) — pure, no DB, no routes; every later slice depends on
   its component semantics.
2. §2 migration + ORM models — nothing to insert into before this. ⚠ gated.
3. §3 intake hook — needs 1 and 2.
4. §4 retro CLI — needs 1 and 2; independent of 3, so it can swap with it.
5. §5 queue routes (intake-service → gateway → portal) — needs rows to list, so after 3
   or 4.
6. §6 relevant records + disclosure — needs 1; independent of 2–5 (disclosure is live
   evaluation, never a queue read), so it can run in parallel with 3–5.
7. §7 eval corpus cap — independent of everything above.
8. §9 registry upkeep — last, once the facts it records are true.

§8 is verification of record, not a build slice.

## Files touched

| File | Change |
|------|--------|
| `db/migrations/009_duplicate_review_queue.sql` | new — queue + failures tables, plain `CREATE TABLE` ⚠ |
| `db/schema.sql` | same two tables appended as `CREATE TABLE IF NOT EXISTS` (hand-sync rule) ⚠; `:44-45` NOTE cite amended |
| `services/intake-service/matching.py` | new — matcher copy |
| `services/records-service/matching.py` | new — identical copy |
| `services/intake-service/app.py` | match hook at the D5 seam; queue routes |
| `services/intake-service/models.py` | queue + failures ORM models |
| `services/intake-service/schemas.py` | queue/disposition schemas + log allowlist |
| `services/intake-service/retro_match.py` | new — retroactive pass CLI |
| `services/intake-service/intake.yaml` | `match_key: ssn_corroborated` |
| `services/records-service/app.py` | relevant-records endpoint + disclosure |
| `services/records-service/schemas.py` | response models |
| `services/records-service/config.py` | `relevant_records_max_items` / `_max_scan` |
| `services/gateway/app.py` | `_get_checked`; 3 new routes (2 caps) |
| `eval/rag/retriever.py`, `eval/rag/run.py` | corpus cap (refuse-over-cap) |
| `frontend/app/records/page.tsx` | panel + disclosure banner + fallback |
| `frontend/app/review-queue/page.tsx` (+ test) | new — queue surface |
| `frontend/app/api/patients/[id]/relevant-records/route.ts` | new BFF proxy |
| `frontend/app/api/review-queue/route.ts` (+ `[id]/disposition/`) | new BFF proxies |
| `frontend/app/components/AppShell.tsx` | nav entry |
| `frontend/app/records/page.test.tsx` | new — panel/banner/fallback tests |
| `tests/test_matching_parity.py`, `test_intake_match_key.py`, `test_retro_match.py`, `test_records_relevant.py` | new suites |
| `tests/test_gateway_authz.py` | route-capability pins + denial tests (deliberate edit) |
| `tests/test_rag_eval.py`, `tests/test_intake_schemas.py` | stale-comment amendments |
| `adr/0005…` (Status), `docs/landmines.md` (§1 `:63`, §3 `:123`), `docs/debt-log.md` (D5a, D11), `docs/runbook.md` (`:99` + retro procedure), `ARCHITECTURE.md:103`, `docs/onboarding-seam-map.md:25`, `docs/todo.md` (new TODO-58), CLAUDE.md §6 | registry upkeep (§9) |

## Out of scope (from requirements §6)

- **Auto-merging duplicate charts** — ADR 0005 decision 3: a wrong merge
  cross-contaminates two humans' records; flag-and-review only.
- **Executing chart merges** (including the Maria cluster) — dispositioning a queue
  entry records the human judgment; the merge itself is a manual HIM procedure, not W2
  engineering work.
- **Query-time record unioning across charts** — rejected in ADR 0005 alternatives;
  masks the intake defect and leaves every other consumer fragmented.
- **Fixing D6 (HL7 AL1/RXA silently dropped)** — the *other* allergy-visibility gap
  under RIV-160; separate defect, separate change, xfail-pinned in the suite.
- **Fixing D11 (IDOR / unbounded search)** — chart-read authz is its own gated fix,
  sized against the whole exposure set per `docs/landmines.md` §1; W2 only avoids
  widening it.
- **External EMPI / probabilistic MPI** — considered and rejected for this engagement
  in ADR 0005 alternatives.

## Verification (end-to-end)

1. **Suite + baseline:** `make test-docker` (or the 3.12 venv) green; xfail=1 and
   deselected=5 unchanged; passed count grows only by the new tests (record the new
   number for CLAUDE.md §6).
2. **Matcher (SPEC-20/21):** parity + coherence tests green — Maria trio candidate,
   bridge-row fixture ambiguous, conflict fixture non-mergeable, and the mixed fixture
   (one SSN → candidate pair + two conflicts) yielding three components, one pair, and
   per-row `status_for` verdicts. Negative: mutate one copy of `matching.py` → parity
   test red → revert. Negative: collapse `status_for` to a whole-group verdict → the
   mixed-fixture test goes red → revert (proves the test binds the per-component
   contract, which is the SPEC-21 semantics).
3. **Intake hook (SPEC-22/23/32):** candidate intake → 201 + queue rows; matcher
   forced to raise → 201 + `match_evaluation_failures` row + class-only log. Negative:
   temporarily make the hook re-raise → the 201 test goes red → revert (proves the
   test binds the never-blocks contract).
4. **Queue (SPEC-25..28):** list shows pending only; disposition stamps
   `decided_by` from the session (client-supplied value ignored — test posts a forged
   `decided_by` and asserts the session username wins) and removes the pair from
   pending; patients rowcount and content unchanged after disposition (SPEC-27
   negative); clinician/roi_clerk 403, anonymous 401 on both routes.
5. **Helper scoping (SPEC-4/17):** with the Maria cluster seeded, relevant-records for
   1042 contains no record with `patient_id != 1042` in any field (adversarial
   assertion over the whole JSON), and `duplicate_disclosure == "candidate"` (SPEC-3);
   a no-SSN patient → `"none"`.
6. **Embedding discipline (SPEC-12/13):** pinned encode-count test stays green; new
   test asserts records-service imports no embedding module; cap test (SPEC-11): set
   cap below corpus size → `RuntimeError` before any encode; revert.
7. **PHI (SPEC-14/16, landmines §3):** end-to-end log-scan tests — SSN planted in
   `name`, `address`, and a raised exception message on the match path and the
   relevant-records path never survives into any log record; queue API responses carry
   no SSN/address. Negative: temporarily log the raw exception → scan test red →
   revert.
8. **Drift gate (SPEC-9/10):** `make eval` green on the finished branch. Negative:
   edit one byte of `db/seed/goldset.json` → exit 1 → revert.
9. **Live stack:** `make up`; clinician login → records page for 1042 → panel +
   disclosure banner, chart readable, no sibling links (SPEC-1/3/5); fail only the
   retrieval path — temporarily 500 the relevant-records BFF route (or block that one
   request in devtools; stopping records-service would fail the chart fetch too and
   prove nothing) → panel shows the fixed fallback, chart renders unaffected (SPEC-2;
   the same split is pinned headlessly in `page.test.tsx` by rejecting only the
   relevant-records mock); front_desk login → `/review-queue` lists pairs after
   `docker compose exec intake-service python retro_match.py` (Maria trio = 3 pairs);
   re-run the CLI → still 3 (SPEC-31); disposition one pair → gone from pending, both
   patient rows unchanged in psql (SPEC-27/30); clinician curl of `/review-queue` →
   403 (SPEC-28).
10. **Frontend gates:** `cd frontend && npm run typecheck && npm run lint && npm test`
    green; `npm run build` green (build type-checks/lints first — e1 gate-interaction
    note applies to the new files).
11. **Registry sweep (§9, no SPEC):** re-run
    `grep -rn "match_key: none\|no MPI\|no match key\|match-key lookup" --exclude-dir=.git
    --exclude-dir=workflow .` on the finished branch — `docs/workflow/` is excluded because
    this plan, its spec and its gate log all quote the pre-change wording as the record of
    what changed, and amending them would falsify the bundle. Account for **every**
    remaining hit against §9's list — each is
    either amended or on the deliberately-not-amended list with its reason. A hit that is
    on neither list is a missed site, not an acceptable remainder. Separately: `TODO-58`
    exists in `docs/todo.md` and names all three `eval/rag/` sites;
    `docs/landmines.md:123` no longer claims there are no duplicate-patient tests while
    still claiming there are no input-normalization ones; `db/schema.sql`'s two new blocks
    use `IF NOT EXISTS` and `db/migrations/009_*.sql`'s do not, with identical columns and
    constraints (diff the two by eye — there is no runner to catch a drift, landmines §2).
    **Gate interaction:** the "do not amend" half of this sweep is already enforced by an
    existing gate — `tests/test_rag_eval.py:498` and `make eval`'s report byte-compare go
    red if an implementer over-corrects `eval/rag/REPORT.md` or `report.py:143`. So an
    over-eager sweep fails at step 1/step 8, before step 11 ever runs, and step 11's real
    load is the *under*-corrected half (the doc and comment sites, which nothing enforces).

## Landmines / risk

- **§1 zones touched:** **migrations** (new `009_*.sql` + `schema.sql` sync — this
  plan's owner review is the planning approval; the code change still rides the gated
  review) and **patient identity / intake** (the ADR 0005 implementation itself —
  owner-scoped into W2 at requirements stage 2026-08-07, human-gated at review).
  **Auth zone not touched:** no change to `require_session`/`require_capability`
  behavior, sessions, or roles.yaml — new routes reuse existing capabilities through
  existing machinery. PHI columns: none added, none modified. ROI: untouched.
- **Deliberate defects preserved:** D11 (helper route inherits session-not-patient-
  bound chart reads — suppressed with citation, not fixed, not widened), D8 (no new
  indexes; the disclosure's SSN pass is a deliberate sequential scan — acceptable at
  seed scale, degrades with growth exactly as D8 already records), D5b, TODO-1
  (registration break untouched — the match hook sits after `_create_patient`, which
  the broken portal payload never reaches; verifiable via curl with the correct
  payload shape), intake's 14 swallowing proxy routes (D4 open half untouched).
- **Accepted residuals:**
  - SPEC-3/6: the disclosure lives on the portal chart surface and in the helper
    response; a raw API consumer of the *existing* `GET /patients/{id}/records` gets no
    disclosure (that route is D11/D8 territory, deliberately untouched). The portal —
    the spec's named system element — always shows it.
  - SPEC-6 failure path: if the helper endpoint is down, the fail-safe is the
    frontend's fixed "completeness not confirmed" fallback, not a backend guarantee.
  - SPEC-20 (owner-decided): no-usable-SSN duplicates produce no candidate, no
    disclosure, no queue entry — tier 2 is deferred, so W2's detection floor is the
    SSN-corroborated tier.
  - **A tracked artifact goes deliberately stale.** `eval/rag/REPORT.md:19`, its renderer
    `eval/rag/report.py:143`, and `eval/rag/data.py:310` keep stating the root cause as
    "`intake.yaml` sets `self_service_intake: true` with `match_key: none`" after §3 flips
    that file. The report is the frozen measured baseline (SPEC-9/10) and re-rendering it
    to say otherwise would move the drift-gate baseline for a reason unrelated to
    measurement, so it stays. It is true as of the measurement it reports, and false as a
    statement about `main` after this lands. The correction rides whichever change next
    moves the baseline legitimately. **Tracked as `docs/todo.md` TODO-58 (§9)** — a
    residual named only in a workflow bundle is invisible to a doc-drift sweep.
  - Disclosure freshness is per chart open (live evaluation) but the *record ranking*
    reflects only the opened chart — a sibling's penicillin allergy is still invisible
    from 1042; that is precisely what the banner discloses and only an HIM merge fixes.
- **Version caveat:** none new — no new runtime dependency anywhere (matcher is
  stdlib; no torch enters services; frontend adds no packages).
- **PR-body "Risk & landmines" line:** "Touches §1 zones: migrations
  (009, additive queue/failures tables, no PHI columns), patient identity/intake
  (ADR 0005 match key, flag-never-merge, owner-scoped 2026-08-07). Auth, PHI columns,
  ROI untouched. D11/D8/D5b/TODO-1 preserved; residuals as named in the plan."
