# ADR 0005 — MPI match key for patient intake (de-duplication)

**Status:** Proposed
**Date:** 2026-07-12
**Author:** Riverbend engagement team

## Context

Self-service intake creates a new patient row on every registration:
`services/intake-service/intake.yaml` sets `self_service_intake: true` with
`match_key: none`. There is no Master Patient Index (MPI) or match key of any
kind (ARCHITECTURE.md §7, debt D5, ticket RIV-160).

The consequence is measured, not hypothetical. The Week-2 retrieval eval
(`eval/rag/`, report in `eval/rag/REPORT.md`) ran against the exported
patients/encounters data and found:

- **40% duplicate rate** — 5 patient rows resolve to 3 humans by SSN. One
  person (Maria Gonzalez) holds three charts: 1042 *Maria Gonzalez*, 1330
  *Maria Gonzales*, 1588 *M. Gonzalez* — identical SSN and address.
- **A patient-safety gap**: her penicillin allergy is recorded only under
  chart 1330. Charts 1042 and 1588 show no allergies. A clinician opening
  either chart could prescribe penicillin. This is exactly Dr. Nguyen's
  RIV-160 report ("the allergy list looks different depending on which chart
  I open").
- **The contractor's retrieval gold-set hides the problem**: it was written
  per chart, not per human (it expects "No known allergies on file" for chart
  1042, and lists 1588 as a separate patient). Retrieval can score perfect
  recall/precision while faithfully reproducing the fragmentation.

Any retrieval helper, AI summary, or chart view built before identity is
fixed inherits the fragmentation and lends it authority.

## Decision (proposed)

Introduce a match key at intake, evaluated at chart-create time:

1. **Primary key: normalized SSN** (digits only). The eval shows why: the
   three Maria rows differ in name spelling (*Gonzalez/Gonzales*), name form
   (*M.* vs *Maria*), and DOB (1971-03-02 vs a transposed 1971-02-03). An
   exact `name + dob` key catches **zero** of the three duplicates; the SSN
   survives all three data-entry variations.
   *Scope caveat:* this ranking is evidence-based for **this export** (five
   rows, SSN identical across all duplicates). At production scale SSN is
   not a safe sole key — SSNs are shared (family members, fraud), mistyped
   (the same data-entry drift that defeats `name_dob` here), and optional at
   self-service intake. Treat SSN as the *highest-weighted attribute* in a
   multi-attribute deterministic score, with tier 2 below as the other
   attributes — not as a standalone identifier.
2. **Fallback for missing/invalid SSN: fuzzy name + DOB** — normalized name
   similarity (e.g. Jaro-Winkler above a tuned threshold) plus DOB with
   transposition tolerance. This tier is advisory only; it exists because SSN
   is optional at self-service intake and can itself be mistyped.
3. **Flag, never auto-merge.** A match does not silently merge charts. Intake
   proceeds, the pair is queued for human review (front-desk/HIM), and the
   clinician-facing UI can surface a "possible duplicate" banner. Auto-merge
   on a wrong match is a worse patient-safety failure than a duplicate:
   it cross-contaminates two real people's records.
4. **Retroactive pass**: the same matcher runs over existing rows to queue
   today's duplicates (starting with the Maria cluster) for review and manual
   merge per HIM procedure.

## Alternatives considered

- **Exact name + DOB key** — rejected on evidence: catches 0/3 of the known
  duplicates (see `eval/rag/REPORT.md` §3 and
  `tests/test_rag_eval.py::test_match_key_name_dob_catches_zero_duplicates`).
- **Probabilistic MPI (Fellegi–Sunter / ML record linkage)** — better recall
  on dirty data, but heavier to build, tune, and govern than this codebase's
  current maturity supports. Reconsider if the deterministic key's review
  queue shows a high miss rate.
- **External EMPI service/product** — strongest option long-term; procurement,
  BAA, and integration cost put it out of scope for this engagement. The
  deterministic key here does not preclude it.
- **Do nothing / fix in retrieval layer** — rejected. Merging records at
  query time (e.g. retrieval unioning charts by SSN) masks the defect while
  intake keeps minting duplicates, and every other consumer (scheduling,
  ROI, HL7 ingest) still sees fragmented charts.

## Consequences

- Scope of this ADR is the **specification**; no intake-service code changes
  ship this week. Implementation lands as its own reviewed change to
  intake-service (⚠️ touches patient identity — human approval required per
  CLAUDE.md §6/§7).
- SSN as primary key means SSN handling gets *more* load-bearing while it is
  still stored plaintext (debt D3). The match key should use the normalized
  hash-or-encrypted form when D3 is addressed; matching logic must not add
  new plaintext SSN copies or logs.
- A review queue is a new operational duty (front-desk/HIM) and needs an
  owner before implementation.
- The eval harness (`eval/rag/`) doubles as the acceptance check: after the
  retroactive merge, re-running it should report a 0% duplicate rate and no
  fragment-coverage gap.
