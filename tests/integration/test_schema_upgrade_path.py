"""
The upgrade path is schema-equivalent, seed-free, and pre-stamped
(e6-SPEC-12/13/14/17; e5b harvest pins, salvaged with surgery).

Integration-marked: needs a live Postgres via the DB_* env the runner reads. Each
test works in its own throwaway database (per-test scratch, real service DB
untouched — §1 migrations-zone isolation).

  * the runner never writes seed data — it applies migration files only (SPEC-12);
  * a volume built by the runner from db/migrations/*.sql carries every table and
    column any migration introduces, the column-add subclass 004/006/007/008
    included (SPEC-13 — the subclass a table-level IF NOT EXISTS schema re-run
    would silently skip, which is why the runner exists);
  * a runner-built database is structurally equivalent to a db/schema.sql-built
    one (SPEC-14, the hand-sync pin);
  * a db/schema.sql-initialized volume is born with the ledger pre-stamped for
    every migration it flattens, and the pre-stamp set equals the on-disk
    migration set, so the runner applies nothing on it (SPEC-17, e6-D-9).
"""
import os
import sys
import uuid

import pytest

from conftest import load_module

pytestmark = pytest.mark.integration

migrate = load_module("db/migrate.py", "db_migrate_upgrade")
SCHEMA_SQL = (
    open(os.path.join(os.path.dirname(migrate.__file__), "schema.sql")).read()
)
MIGRATION_FILES = {os.path.basename(p) for _, p in migrate.discover()}


def _admin():
    c = migrate.connect(dbname="postgres")
    c.autocommit = True
    return c


@pytest.fixture
def make_conn():
    """Factory for fresh empty databases; all dropped at teardown."""
    names, conns = [], []

    def _make():
        name = f"mig_test_{uuid.uuid4().hex[:12]}"
        a = _admin()
        with a.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{name}"')
        a.close()
        c = migrate.connect(dbname=name)
        names.append(name)
        conns.append(c)
        return c

    yield _make

    for c in conns:
        try:
            c.close()
        except Exception:
            pass
    for name in names:
        a = _admin()
        with a.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=%s AND pid<>pg_backend_pid()",
                (name,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
        a.close()


def _load_schema_sql(conn):
    with conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)


def _columns(conn, table):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s",
            (table,),
        )
        return {r[0] for r in cur.fetchall()}


# ------------------------------------------------------------- seed-free (12)

def test_the_runner_writes_no_seed_data(make_conn):
    conn = make_conn()
    migrate.apply(conn, out=lambda *_: None)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM patients")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM records")
        assert cur.fetchone()[0] == 0


# ------------------------------------------------ column-add subclass (13)

def test_every_migration_column_reaches_the_upgraded_volume(make_conn):
    conn = make_conn()
    migrate.apply(conn, out=lambda *_: None)
    # the column-add subclass a whole-table IF NOT EXISTS re-run would skip:
    assert {"mrn", "gender", "phone", "email", "created_via"} <= _columns(conn, "patients")   # 004
    assert {"provider", "reason", "location", "scheduled_for"} <= _columns(conn, "appointments")  # 006
    assert {"reason", "location", "status"} <= _columns(conn, "encounters")                   # 007
    assert {"title", "status", "reference_range"} <= _columns(conn, "records")                # 007
    assert "roi_request_id" in _columns(conn, "disclosures")                                  # 008


# ------------------------------------------------------- equivalence (14)

def test_runner_build_is_schema_equivalent_to_schema_sql(make_conn):
    from_migrations = make_conn()
    migrate.apply(from_migrations, out=lambda *_: None)

    from_schema = make_conn()
    _load_schema_sql(from_schema)

    a = migrate.structural_fingerprint(from_migrations)
    b = migrate.structural_fingerprint(from_schema)
    assert a == b, (
        "runner-built and schema.sql-built schemas diverge:\n"
        f"only in migrations: {[(k, [x for x in a[k] if x not in b[k]]) for k in a]}\n"
        f"only in schema.sql: {[(k, [x for x in b[k] if x not in a[k]]) for k in b]}"
    )


# ------------------------------------------------------- pre-stamp (17)

def test_schema_sql_volume_is_born_prestamped_and_runner_applies_nothing(make_conn):
    conn = make_conn()
    _load_schema_sql(conn)
    assert migrate.ledger_exists(conn)
    assert migrate.apply(conn, out=lambda *_: None) == []


def test_prestamp_set_equals_the_on_disk_migration_set(make_conn):
    conn = make_conn()
    _load_schema_sql(conn)
    assert migrate.applied(conn) == MIGRATION_FILES
