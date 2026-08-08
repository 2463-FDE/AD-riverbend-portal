-- 009_duplicate_review_queue — candidate-duplicate review queue + match failures
-- 2026-08-08 · Helix Digital Partners
-- Backs the ADR 0005 tier-1 match key: intake and the retroactive pass flag
-- candidate duplicate pairs here for a human to disposition. Flag-and-review
-- only — nothing in this schema merges, alters, or deletes a patient row.
-- No PHI columns: ids, enums, timestamps and a staff username only, so
-- evaluating the match key creates no new stored SSN copy.
-- The ordered-pair CHECK plus the UNIQUE constraint are the idempotency
-- mechanism: a re-run of the retroactive pass inserts nothing new, and a
-- dispositioned pair is never re-queued (status is deliberately not part of
-- the key).
-- No indexes beyond the constraint-backed ones — D8 (the schema has zero
-- CREATE INDEX) is a registered deliberate defect, not an oversight to fix here.

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
