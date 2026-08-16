-- 011_schema_migrations — the migration ledger (e6, E6-REQ-9)
-- 2026-08-16 · Riverbend
-- Backs db/migrate.py: one row per applied migration, so an applied migration
-- is never re-run (e6-SPEC-10). The runner self-creates this table before
-- applying anything, so this file is a no-op wherever the runner arrived first;
-- it exists because the both-files schema-change rule (CLAUDE.md §9) is literal
-- and db/schema.sql pre-stamps this same ledger on a fresh volume (e6-D-9/D-17).
-- Kept byte-identical to db/migrate.py::LEDGER_DDL.
-- No PHI columns; no index beyond the PK-backed one — D8 untouched.

CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
