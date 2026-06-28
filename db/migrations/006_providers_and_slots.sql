-- 006_providers_and_slots — schedulable slots
-- 2026-03-19 · Helix Digital Partners
-- Introduces providers + bookable slots so the portal can do slot search.
-- NOTE: appointments.slot_id still has no UNIQUE constraint and no FK to slots
-- — the booking path is check-then-insert (RIV-175 double-booking).

CREATE TABLE providers (
    id        SERIAL PRIMARY KEY,
    name      TEXT NOT NULL,
    specialty TEXT,
    location  TEXT
);

CREATE TABLE slots (
    id          SERIAL PRIMARY KEY,
    provider_id INTEGER REFERENCES providers(id),
    location    TEXT,
    start_at    TIMESTAMPTZ NOT NULL,
    end_at      TIMESTAMPTZ,
    status      TEXT NOT NULL DEFAULT 'open'
);

ALTER TABLE appointments ADD COLUMN provider      TEXT;
ALTER TABLE appointments ADD COLUMN reason        TEXT;
ALTER TABLE appointments ADD COLUMN location      TEXT;
ALTER TABLE appointments ADD COLUMN scheduled_for TIMESTAMPTZ;
