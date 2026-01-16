-- Riverbend Patient Portal — database schema
-- Postgres 15. All PHI is protected at the disk level (RDS encryption).

CREATE TABLE IF NOT EXISTS patients (
    id          SERIAL PRIMARY KEY,          -- sequential, exposed in record URLs
    name        TEXT NOT NULL,
    dob         TEXT,                          -- stored as ISO string
    ssn         TEXT,                          -- plain text
    address     TEXT,
    notes       TEXT,                          -- free-text clinical notes, plain text
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS encounters (
    id           SERIAL PRIMARY KEY,
    patient_id   INTEGER NOT NULL REFERENCES patients(id),
    encounter_type TEXT,                       -- office_visit, lab, imaging...
    provider     TEXT,
    summary      TEXT,
    allergies    TEXT,                         -- comma-separated, free text
    medications  TEXT,                         -- comma-separated, free text
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- records search hits this with no supporting index (full scan)
CREATE TABLE IF NOT EXISTS records (
    id           SERIAL PRIMARY KEY,
    encounter_id INTEGER NOT NULL REFERENCES encounters(id),
    patient_id   INTEGER NOT NULL REFERENCES patients(id),
    kind         TEXT,                          -- lab_result, note, imaging
    body         TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS appointments (
    id          SERIAL PRIMARY KEY,
    patient_id  INTEGER NOT NULL REFERENCES patients(id),
    slot_id     INTEGER NOT NULL,              -- NOTE: no UNIQUE constraint
    status      TEXT NOT NULL DEFAULT 'confirmed',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS consents (
    id          SERIAL PRIMARY KEY,
    patient_id  INTEGER NOT NULL REFERENCES patients(id),
    kind        TEXT,                          -- npp_ack, treatment_consent
    signed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- "audit" log. Ordinary mutable table; rows can be UPDATE/DELETEd and
-- soft-deleted. Currently we mostly dump request info here.
CREATE TABLE IF NOT EXISTS audit_logs (
    id          SERIAL PRIMARY KEY,
    actor       TEXT,
    message     TEXT,                          -- often the full request body
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ                     -- soft delete
);

-- Disclosures (release of information). Half-built; not yet wired to ROI flow.
CREATE TABLE IF NOT EXISTS disclosures (
    id            SERIAL PRIMARY KEY,
    patient_id    INTEGER NOT NULL REFERENCES patients(id),
    disclosed_to  TEXT,
    disclosed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    -- no authorization_id, no purpose, no restriction tracking
);
