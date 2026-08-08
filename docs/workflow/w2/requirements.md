# W2 Requirements

> Status: AGREED 2026-08-07
> Source: engagement owner ask, 2026-08-07

## 1. Raw ask (verbatim)

> CLIENT MESSAGE
> Our clinicians are constantly complaining that they have to click through a patient's entire history to find anything relevant. Could you build a retrieval helper that surfaces the most relevant past records the moment they open a chart? The last contractor left a little 'gold set' of example questions and expected answers you can test against — it all looked great when he demoed it. I've exported a chunk of our patients and encounters tables for you. Don't go too crazy on cost, our AI budget is basically a Claude Pro plan.
> — Dr. Maya Okonkwo, COO — Riverbend Community Health
>
> WHAT THEY HANDED OVER
> Export patients.csv (patients-table dump). Three rows stand out: 1042 | Maria Gonzalez | 1971-03-02, 1330 | Maria Gonzales | 1971-03-02, 1588 | M. Gonzalez | 1971-02-03 — different patient IDs but the same SSN (412-55-9981) and address, all created via self-service intake.
> Export encounters.csv: allergy and med rows are scattered across those three IDs — the penicillin allergy is recorded only under patient 1330.
> Contractor's goldset.json: query "show me Maria Gonzalez's allergies" → expected answer cites records from patient 1042 only.
> Intake config intake.yaml: self_service_intake: true, match_key: none (no de-dup on name/DOB/SSN at create).
> Clinician Jira ticket RIV-160 (Dr. Nguyen): "Why does the allergy list look different depending on which chart I open for the same lady (Maria Gonzalez)? One chart shows penicillin, another shows none."
>
> 🔍 QUESTIONS TO DIG INTO
> Scan the patient export — is each human really one patient ID, or could one person appear more than once?
> Collect every allergy/med for "Maria Gonzalez" across the data — do you get the full list from any single patient ID?
> The contractor's gold-set passes. Does passing it actually prove the clinician sees a complete record?
> What in intake.yaml would let one person become three separate charts?
>
> CURRENT PROBLEMS (STATED / KNOWN)
> Clinicians waste time hunting through patient history.
> Retrieval 'looks fine' on the contractor's gold-set.
>
> ⚠ QUOTA / SCOPE RISK
> Embedding a large record dump can burn Pro quota. Cap corpus size; embed once and cache — do not re-embed per run.

## 2. Context

- **The analysis half of this ask is already landed on `main`.** Every "question to dig
  into" has a registered, measured answer: `eval/rag/REPORT.md` (3 candidate identities
  behind 5 rows — 40% candidate duplicate rate; the penicillin allergy visible only from
  chart 1330; the gold-set shown to be written per *chart*, not per *human*, so passing it
  proves fragmentation-fidelity, not completeness), `adr/0005-mpi-match-key.md` (Proposed —
  match-key spec; flag, never auto-merge), `docs/debt-log.md` D5a (no MPI → duplicate
  charts, RIV-160), and `tests/test_rag_eval.py`. Per the W1 precedent, pre-existing
  artifacts are **verified against this document once agreed** — a gap is a finding, not a
  rebuild trigger.
- **The handed-over exports are the repo's seed fixtures.** `db/seed/patients.csv`,
  `encounters.csv`, `goldset.json` contain exactly the rows the ask quotes (Maria cluster,
  SSN 412-55-9981). No new data ingestion is involved; `eval/rag/corpus.sha256` pins the
  bytes in CI.
- **The un-landed half is the clinician-facing helper itself.** No portal surface or
  service endpoint surfaces relevant records on chart open today. `eval/rag/retriever.py`
  is an offline eval harness, not a serving path.
- **ADR 0005 already rejects "fix it in the retrieval layer"**: query-time merging masks
  the defect while intake keeps minting duplicates. Any helper built on these charts
  inherits the fragmentation and lends it authority (`REPORT.md` §5) — which is why
  duplicate *disclosure* (not merge) is a requirement below, and intake de-dup is an open
  question, not an assumption.
- **Nearby approval-gated zones** (`docs/landmines.md` §1): patient identity / intake
  changes (ADR 0005 consequence: human approval required), PHI handling and vendor egress
  (`services/ai-assistant/` is the only sanctioned egress path, D13/D14), chart-read authz
  (D11 — the helper must not widen it). Adjacent but distinct defect: D6 (HL7 AL1/RXA
  allergy drop) is a second allergy-visibility gap with the same ticket, RIV-160.
- **Owner decisions, 2026-08-07** (structured Q&A, this stage): build the clinician-facing
  helper including the portal surface; ADR 0005 match-key implementation **enters W2
  scope** (scope approval — the implementation change itself still rides gated review);
  duplicate-cluster behavior is a disclosure banner (no sibling navigation, no blocking);
  acceptance artifact is the existing `eval/rag` report + drift gate, no new gold-set;
  the review queue's operational owner is the **front_desk** role; the ADR 0005 decision-4
  retroactive pass over existing rows is in scope.

## 3. Requirements

| ID | Requirement | Notes |
|----|-------------|-------|
| W2-REQ-1 | Clinician: on opening a patient chart in the portal, the most relevant past records for that patient are surfaced without clicking through the full history | the ask's core need; UI surface required (TODO-44 lesson) |
| W2-REQ-2 | Clinician: when the opened chart belongs to a candidate-duplicate cluster (per the ADR 0005 corroboration rules), the surfaced view shows a disclosure banner — sibling charts may exist and the shown record set may be incomplete — and never presents a fragmented chart as the whole record | owner 2026-08-07: banner only, no sibling navigation, no blocking; **never** auto-merge (ADR 0005 decision 3); ⚠ human-gate adjacency: patient identity |
| W2-REQ-3 | System: acceptance of the helper is measured per *human*, not per *chart*; agreement with the contractor's gold-set is explicitly not sufficient evidence that a clinician sees a complete record | owner 2026-08-07: the existing `eval/rag` report + drift gate is the acceptance artifact; no new gold-set; the contractor gold-set is retained as the foil, not the bar |
| W2-REQ-4 | System: total AI/embedding spend for the helper is bounded — corpus size capped, embeddings computed once and cached, never recomputed per run or per request | client quota constraint, near-verbatim; eval harness already embeds-once + caches |
| W2-REQ-5 | System: the helper's data path writes no PHI to logs, and PHI leaves the estate only via the sanctioned ai-assistant egress path (if it leaves at all) | ⚠ human-gate (PHI); `docs/landmines.md` §3 negative tests required |
| W2-REQ-6 | Clinician/system: the helper does not widen chart-read exposure — a user can retrieve records only for the chart they opened, no broader than today's gateway capability checks | D11 is open by design; the helper must not add a new cross-patient read path |
| W2-REQ-7 | Engagement owner: the export findings (duplicate rate, safety gap, gold-set foil, intake root cause) are registered in the owner-facing registries | already satisfied on `main` (`REPORT.md`, ADR 0005, D5a, drift gate); backfill-verify once agreed |
| W2-REQ-8 | System: at chart-create time, intake evaluates the ADR 0005 match key; a candidate match flags the pair for human review while intake still proceeds — no registration is blocked and no charts are merged automatically | owner-approved in scope 2026-08-07; ⚠ human-gate (patient identity / intake); matching must add no new plaintext SSN copies or logs (ADR 0005 consequence, D3) |
| W2-REQ-9 | Front desk: a review queue exists where flagged candidate-duplicate pairs can be seen and dispositioned | owner 2026-08-07: front_desk is the operational owner (existing role, no RBAC addition); disposition ≠ merge — see out of scope |
| W2-REQ-10 | System: a retroactive matcher pass over existing patient rows queues today's candidate duplicates (starting with the Maria cluster) for review | ADR 0005 decision 4; owner-approved in scope 2026-08-07; read-only pass, queue only |

## 4. Assumptions

- The handed-over CSVs/goldset are the existing seed fixtures; W2 involves no new client
  data and no real-PHI export (the `REPORT.md` header warning stands).
- "AI budget is basically a Claude Pro plan" is a cost-discipline constraint (bounded,
  cached, capped), not a literal instruction to run production retrieval on a consumer
  plan.
- The owner's in-scope ruling for the match key is *scope* approval; the implementation
  change to intake-service still lands as its own explicitly approved, gated review
  (ADR 0005 consequences; `docs/landmines.md` §1). ADR 0005's status moves from
  `Proposed` only through that gated path.
- The contractor gold-set stays in the repo as the documented foil; it is not deleted or
  silently "fixed".

## 6. Out of scope

- **Auto-merging duplicate charts** — ADR 0005 decision 3: a wrong merge cross-contaminates
  two humans' records; flag-and-review only.
- **Executing chart merges** (including the Maria cluster) — dispositioning a queue entry
  records the human judgment; the merge itself is a manual HIM procedure, not W2
  engineering work.
- **Query-time record unioning across charts** — rejected in ADR 0005 alternatives; masks
  the intake defect and leaves every other consumer fragmented.
- **Fixing D6 (HL7 AL1/RXA silently dropped)** — the *other* allergy-visibility gap under
  RIV-160; separate defect, separate change, xfail-pinned in the suite.
- **Fixing D11 (IDOR / unbounded search)** — chart-read authz is its own gated fix, sized
  against the whole exposure set per `docs/landmines.md` §1; W2 only avoids widening it.
- **External EMPI / probabilistic MPI** — considered and rejected for this engagement in
  ADR 0005 alternatives.
