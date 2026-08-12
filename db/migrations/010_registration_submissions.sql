-- 010_registration_submissions — idempotency record for POST /intake
-- 2026-08-11 · Helix Digital Partners
-- Closes the D4 residual e4 made reachable: registration commits, then the
-- response is lost in transit, so the operator retries a registration that
-- already exists and gets a second chart with its own coverage and consent
-- rows. The client supplies an identifier for the submission attempt; this
-- table binds that identifier to the registration it produced, and the row is
-- written in the SAME transaction as the patient/coverage/consent writes. A
-- record written outside that transaction reopens the window it exists to
-- close.
-- The UNIQUE constraint is the mechanism, not an optimization: it decides a
-- concurrent collision (the loser blocks on it, then re-reads and replays) and
-- it keeps replay lookup cheap as the table grows.
-- Rows are kept FOREVER. No expiry, no pruning (requirements D-7): a retention
-- horizon is a date past which a late retry silently creates the duplicate this
-- table prevents. The unbounded growth is accepted and recorded.
-- No PHI: an opaque client-generated identifier (random, derived from no
-- submitted value — E5-SPEC-38), a keyed non-reversible content fingerprint
-- (E5-SPEC-41 — HMAC, never a plain hash: a plain hash of guessable fields is a
-- dictionary-reversible confirmation oracle), a patient id and a timestamp. The
-- fingerprint decides whether a request carrying a recorded identifier is a
-- replay of the same attempt (answer the recorded registration) or a different
-- payload under a reused key (answer 409, E5-SPEC-42) — an edited retry after a
-- lost response must never be confirmed with content that was never saved.
-- No indexes beyond the constraint-backed one — D8 (the schema has zero
-- CREATE INDEX) is a registered deliberate defect, and no existing table gains
-- an index here.

CREATE TABLE registration_submissions (
    id SERIAL PRIMARY KEY,
    submission_id TEXT NOT NULL,
    payload_fingerprint TEXT NOT NULL,
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_registration_submission_id UNIQUE (submission_id)
);
