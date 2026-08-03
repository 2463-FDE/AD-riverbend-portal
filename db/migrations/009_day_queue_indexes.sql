-- 009_day_queue_indexes — index-backed front-desk day queue
-- 2026-08-02 · PR #26 (codex r6), ADR 0018
-- GET /schedule?date= filtered on COALESCE(appointments.scheduled_for,
-- slots.start_at) across an outer join — an expression no B-tree index can
-- serve, so every day view scanned all of appointments. The query is rewritten
-- as a UNION ALL of two branches, each filtering one of these indexed columns;
-- ix_appointments_slot_id also serves the slot-branch join back to
-- appointments (the column has no FK, so nothing indexed it).
-- Plain CREATE INDEX, not CONCURRENTLY: the build takes a write-blocking
-- SHARE lock on each table, acceptable because both tables are human-scale
-- (tens of thousands of rows — milliseconds) and migrations here are
-- hand-applied in a maintenance moment, not run against live traffic.

CREATE INDEX ix_appointments_scheduled_for ON appointments (scheduled_for);
CREATE INDEX ix_appointments_slot_id       ON appointments (slot_id);
CREATE INDEX ix_slots_start_at             ON slots (start_at);
