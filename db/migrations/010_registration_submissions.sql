-- 010_registration_submissions — the POST /intake idempotency ledger
-- 2026-08-13 · Helix Digital Partners
-- Makes a registration safe to retry (e5b): a submission that commits and then
-- loses its response no longer forks a second chart on retry. One row per
-- registration attempt, keyed by the portal's mint-random version-4 UUID.
-- The UNIQUE constraint on submission_id is the SOLE arbiter of a retry — the
-- first committer wins, and every retry of the same attempt re-reads this row
-- inside a bounded lock wait (e5b-D-12).
-- No PHI columns by design (e5b-SPEC-18/20/21): submission_id is non-PHI by
-- construction, payload_fingerprint is a keyed HMAC of the validated content
-- from which no patient value is recoverable (e5b-D-8/D-11), and the rest is an
-- FK and a timestamp. No eligibility verdict is persisted (e5b-SPEC-29).
-- No indexes beyond the constraint-backed one — D8 (the schema has zero
-- CREATE INDEX) is a registered deliberate defect, not touched here.

CREATE TABLE registration_submissions (
    id SERIAL PRIMARY KEY,
    submission_id TEXT NOT NULL,          -- portal-minted version-4 UUID, non-PHI
    payload_fingerprint TEXT NOT NULL,    -- keyed HMAC of validated content, not reversible
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_registration_submission_id UNIQUE (submission_id)
);
