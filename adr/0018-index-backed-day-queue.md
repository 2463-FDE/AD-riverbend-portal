# ADR 0018 — Day queue goes index-backed by query rewrite, not by a persisted visit timestamp

**Status:** Accepted
**Date:** 2026-08-02
**Author:** Riverbend engagement team
**Debt:** D8-class read-path scan, surfaced by Codex PR #26 round 6 (day queue is new code in that PR, not an inherited entry)

## Context

Codex round 6 on PR #26 flagged `GET /schedule?date=` (medium): the day filter ran on
`COALESCE(appointments.scheduled_for, slots.start_at)` computed **after** an outer join, and
the schema had no indexes beyond primary keys on any of the columns involved. A B-tree index
cannot serve a predicate on an expression assembled across two tables, so Postgres scanned
all of `appointments` and joined `slots` for every day requested. The `limit` guardrail
bounds rows *returned*, not rows *scanned* — with ordinary appointment history the
front-desk queue degrades toward timeout.

The COALESCE was itself deliberate (codex r1/r2 history in the endpoint docstring):
`scheduled_for` is nullable and the booking write path never populates it, so filtering that
column alone returns nothing but seeded rows, and the slot join had to drop no row whose own
`scheduled_for` was usable. Any fix must preserve exactly that membership semantics.

The reviewer's recommended shape was to persist a non-null effective visit timestamp on
`appointments` at booking/import time and index it.

## Decision

Keep the schema's data shape unchanged and make the *query* indexable: rewrite the day
filter as a `UNION ALL` of two branches, each filtering one indexed column, with membership
semantics identical to the COALESCE by construction:

1. **scheduled branch** — rows whose own `scheduled_for` is inside the window. Never joins
   `slots`, so slot state cannot drop a row that carries its own time.
2. **slot branch** — rows with `scheduled_for IS NULL` whose slot's `start_at` is inside the
   window. The inner join *is* the predicate: under the COALESCE an unresolvable slot left
   the visit time NULL and the window excluded the row; a join with no match excludes it
   identically.

Migration `009_day_queue_indexes.sql` (mirrored in `db/schema.sql`) adds the three plain
B-tree indexes the branches need: `appointments.scheduled_for`, `slots.start_at`, and
`appointments.slot_id` (the slot-branch join column, FK-less so nothing else indexes it).

Invariants, each pinned in `tests/test_schedule_day_view.py`:

- **Branches are disjoint** — the `IS NULL` guard on the slot branch; without it a row with
  both times in-window is returned twice and paginates wrong
  (`test_the_branches_are_disjoint_so_no_row_pages_twice`).
- **Both branches carry the same half-open window**
  (`test_the_window_bounds_each_side_of_the_right_operator`).
- **The status exclusion has exactly one site, on the outer query, after the UNION ALL** — a
  copy per branch is two predicates that can drift apart, the r2 spelling-drift failure
  reintroduced inside one statement (`test_cancelled_visits_are_excluded_from_the_queue`).
- **Selection, sort and rendering all read the same branch-produced time column**
  (`test_sort_breaks_ties_on_id`, `test_the_visit_time_falls_back_to_the_slot_start`).

## Alternatives considered

- **Persisted `visit_at NOT NULL` on `appointments` + composite index (reviewer's shape).**
  Rejected: it introduces denormalized state that drifts whenever a slot time or
  `scheduled_for` changes after booking, and `NOT NULL` forces the booking path to resolve
  the slot at write time — but `book()` deliberately inserts any positive `slot_id`
  unchecked (RIV-175 surface, frozen raw-psycopg2 path, W5 scope). The fix would change
  booking behavior from inside a review round, which is the stateful-machinery pattern
  `docs/review-loop-metrics.md` measures as the B-finding factory. If W5's slot/appointment
  work lands durable provider identity and slot integrity on appointments, a persisted
  timestamp can be revisited there with the write path it needs.
- **Indexes only, query unchanged.** Rejected — does not work: the predicate stays on the
  cross-table COALESCE, which no B-tree index serves; the planner still scans.
- **Single query with `OR` of the two branch predicates.** Rejected: Postgres does not
  OR-expand across a join into separate index scans, so the outer-join-then-filter plan
  survives and the OR gains nothing.
- **Track as D8 debt, no code.** Rejected: D8's open entries are *inherited* records-path
  scans; this query is new in PR #26, and the stateless fix is small.

## Accepted tradeoffs / deferred gaps

1. **Three single-column indexes, not a covering composite.** Enough to make scanned-rows
   proportional to day size; a composite with status/id sort keys buys more only alongside
   the persisted-column design already rejected. Revisit with W5.
2. **Write amplification on `appointments` inserts (three index maintenances).** Booking
   volume is human-scale; acceptable.
3. **Plan verification is by captured `EXPLAIN` (below), not by an automated test.** The
   unit harness compiles statements against a fake session and cannot observe a planner;
   asserting plans needs a live-Postgres integration test with representative row counts,
   which the suite does not yet have a pattern for. The structural tests pin the query
   shape that makes the plan possible.

## Consequences

- `services/scheduling-service/app.py` day query is the two-branch shape; the endpoint
  docstring owns the reasoning at the code.
- New migration `009_day_queue_indexes.sql`; `db/schema.sql` hand-synced (§6: the two must
  not diverge or fresh-volume boots differ from migrated databases).
- Fresh volumes get the indexes from `schema.sql`; existing databases only via the
  migration — there is no runner, so applying 009 is a manual step per environment.
- `EXPLAIN ANALYZE` against a synthetic 66k-row `appointments` / 13k-row `slots` dataset
  (inserted and rolled back in one transaction on the dev database, indexes applied):
  the old shape seq-scans all 65,873 non-cancelled appointments and filters them down to
  180 (21.4 ms); the new shape drives every step from an index —
  `ix_appointments_scheduled_for`, `ix_slots_start_at`, `ix_appointments_slot_id`, then
  the primary keys — at 0.79 ms, and produces the identical 180-row day membership before
  the limit, corroborating the equivalence argument on real data. The captured plans are
  in PR #26 (r6 reply).
