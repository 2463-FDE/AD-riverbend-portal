"""
Migration runner behaviour against a live Postgres (e6-SPEC-9/10/11, e6-D-14/D-19).

Integration-marked: needs a Postgres reachable via the DB_* env the runner reads
(CI's `migrations` job / `make test-migrations` provide one). Each test works in
its own throwaway database created and dropped by the `db` fixture — the real
service database is never touched (§1 migrations-zone isolation: per-test scratch
databases on a disposable server).
"""
import os
import sys
import uuid

import pytest

from conftest import load_module

pytestmark = pytest.mark.integration

migrate = load_module("db/migrate.py", "db_migrate_runner")

EXPECTED_TABLES = {
    "users", "patients", "insurance_coverages", "providers", "slots",
    "appointments", "encounters", "records", "consents", "audit_logs",
    "roi_requests", "disclosures", "duplicate_review_queue",
    "match_evaluation_failures", "registration_submissions",
}
MIGRATION_FILES = {os.path.basename(p) for _, p in migrate.discover()}


def _admin():
    c = migrate.connect(dbname="postgres")
    c.autocommit = True
    return c


@pytest.fixture
def db():
    """A fresh, empty database; dropped afterwards."""
    name = f"mig_test_{uuid.uuid4().hex[:12]}"
    a = _admin()
    with a.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{name}"')
    a.close()
    conn = migrate.connect(dbname=name)
    try:
        yield conn
    finally:
        conn.close()
        a = _admin()
        with a.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=%s AND pid<>pg_backend_pid()",
                (name,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
        a.close()


# ------------------------------------------------------------- apply (SPEC-9/10)

def test_apply_brings_an_empty_volume_to_current(db):
    migrate.apply(db, out=lambda *_: None)
    assert EXPECTED_TABLES <= migrate.user_tables(db)


def test_apply_records_every_migration_in_the_ledger(db):
    migrate.apply(db, out=lambda *_: None)
    assert migrate.applied(db) == MIGRATION_FILES


def test_a_recorded_migration_is_never_rerun(db):
    first = migrate.apply(db, out=lambda *_: None)
    assert set(first) == MIGRATION_FILES
    second = migrate.apply(db, out=lambda *_: None)
    assert second == []


# --------------------------------------------------------- atomic failure (11)

def test_a_failing_file_records_nothing_and_leaves_no_partial_changes(db, tmp_path):
    (tmp_path / "001_ok.sql").write_text("CREATE TABLE ok_marker (id INT);")
    # two statements: the first would create a table, the second is invalid, so
    # a non-atomic runner would leave partial_marker behind.
    (tmp_path / "002_bad.sql").write_text(
        "CREATE TABLE partial_marker (id INT);\nTHIS IS NOT VALID SQL;"
    )
    with pytest.raises(Exception):
        migrate.apply(db, migrations_dir=str(tmp_path), out=lambda *_: None)

    tables = migrate.user_tables(db)
    assert "ok_marker" in tables
    assert "partial_marker" not in tables            # rolled back whole (e6-SPEC-11)
    assert migrate.applied(db) == {"001_ok.sql"}     # bad file not recorded


def test_main_exits_nonzero_when_a_migration_fails(db, tmp_path, monkeypatch):
    (tmp_path / "001_bad.sql").write_text("THIS IS NOT VALID SQL;")
    name = db.info.dbname
    orig_connect = migrate.connect
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", str(tmp_path))
    # main() calls connect() with no dbname → give it a fresh connection to the
    # scratch volume; it owns and closes that connection itself.
    monkeypatch.setattr(
        migrate, "connect",
        lambda dbname=None: orig_connect(dbname=name if dbname is None else dbname),
    )
    assert migrate.main(["apply"]) == 1


# ------------------------------------------------------ ledgerless refuse (D-14)

def test_a_ledgerless_nonempty_volume_is_refused(db):
    with db.cursor() as cur:
        cur.execute("CREATE TABLE legacy_thing (id INT);")
    db.commit()
    with pytest.raises(migrate.LedgerlessDatabaseError):
        migrate.apply(db, out=lambda *_: None)


# ---------------------------------------------------- baseline verify (D-19)

def test_baseline_stamps_a_matching_ledgerless_volume(db):
    # A volume that IS at head but carries no ledger (a pre-runner legacy volume
    # kept current by hand). Simulate by applying then dropping the ledger.
    migrate.apply(db, out=lambda *_: None)
    with db.cursor() as cur:
        cur.execute("DROP TABLE schema_migrations;")
    db.commit()

    assert migrate.baseline(db, out=lambda *_: None) is True
    assert migrate.applied(db) == MIGRATION_FILES
    # verified current: a follow-up apply runs nothing
    assert migrate.apply(db, out=lambda *_: None) == []


def test_baseline_refuses_a_behind_head_volume(db, tmp_path):
    # Apply only a prefix of the migration set, then drop the ledger: the live
    # schema is missing later migrations' tables/columns, so baseline against the
    # FULL on-disk set must refuse and stamp nothing (e6-D-19).
    full = migrate.discover()
    prefix = full[: len(full) - 3]
    for fn, path in prefix:
        with open(path) as f:
            sql = f.read()
        with db:
            with db.cursor() as cur:
                cur.execute(sql)
    with db.cursor() as cur:
        cur.execute("SELECT to_regclass('public.schema_migrations')")
        # prefix never created a ledger, so nothing to drop; assert clean state
    db.commit()

    with pytest.raises(migrate.BaselineMismatchError):
        migrate.baseline(db, out=lambda *_: None)
    assert migrate.ledger_exists(db) is False
