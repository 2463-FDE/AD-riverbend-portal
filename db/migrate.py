"""
db/migrate.py — forward-only migration runner + ledger (E6-REQ-9, e6-SPEC-9..14/17).

One command brings a database created before any given migration to the current
schema by applying ``db/migrations/*.sql`` in filename order and recording each
in a ``schema_migrations`` ledger, so an applied migration is never re-run
(e6-SPEC-9/10). Each file is applied in its own transaction: a failing file
records nothing and, because Postgres DDL is transactional, leaves none of its
changes behind (e6-SPEC-11). The runner never writes seed data — it applies
migration files only (e6-SPEC-12).

Two commands:

  apply     (default) create the ledger if absent, then run every migration the
            ledger has not recorded, in filename order.
  baseline  record an already-current legacy volume's migrations WITHOUT running
            them — but only after verifying the live schema structurally matches
            a scratch build of the full migration set (e6-D-19). A behind-head
            volume fails this check and is refused, so its ledger is never
            falsely stamped current.

A volume that already has tables but no ledger (one created before this runner
existed) is refused by ``apply`` with an instructive error pointing at
``baseline`` — the migration files are bare DDL, so blindly re-running 001 on a
populated volume would crash (e6-D-14). §1 migrations zone (docs/landmines.md);
approved by e6-D-5/D-9/D-14/D-19.
"""
import glob
import os
import sys
import uuid

import psycopg2

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")
LEDGER_TABLE = "schema_migrations"

# The runner self-creates the ledger; migration 011 ships the identical DDL so
# the both-files rule holds and a schema.sql-born volume has the table too. Kept
# byte-identical to db/migrations/011_schema_migrations.sql (e6-D-17).
LEDGER_DDL = (
    "CREATE TABLE IF NOT EXISTS schema_migrations (\n"
    "    filename   TEXT PRIMARY KEY,\n"
    "    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()\n"
    ");"
)


class LedgerlessDatabaseError(RuntimeError):
    """A non-empty volume with no ledger — refuse apply, point at baseline."""


class BaselineMismatchError(RuntimeError):
    """The live schema does not match the full migration set — refuse to stamp."""


class MigrationFailedError(RuntimeError):
    """A migration file raised — carries the filename and the exception class
    name only, never the driver message (class-name-only idiom, CLAUDE.md §4)."""


def conn_params(dbname=None):
    """Connection parameters from the environment, defaults matching the compose
    topology (same env contract as book.py / config.py)."""
    return dict(
        host=os.getenv("DB_HOST", "postgres"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=dbname or os.getenv("DB_NAME", "riverbend"),
        user=os.getenv("DB_USER", "riverbend_app"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def connect(dbname=None):
    return psycopg2.connect(**conn_params(dbname))


def discover(migrations_dir=None):
    """(filename, path) for every migration, in filename order. A None dir
    resolves to MIGRATIONS_DIR at call time, so a test (or main) can redirect it
    by setting the module global."""
    return sorted(
        (os.path.basename(p), p)
        for p in glob.glob(os.path.join(migrations_dir or MIGRATIONS_DIR, "*.sql"))
    )


def ledger_exists(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (f"public.{LEDGER_TABLE}",))
        return cur.fetchone()[0] is not None


def user_tables(conn):
    """Base tables in the public schema other than the ledger itself."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE' "
            "AND table_name <> %s",
            (LEDGER_TABLE,),
        )
        return {r[0] for r in cur.fetchall()}


def applied(conn):
    with conn.cursor() as cur:
        cur.execute(f"SELECT filename FROM {LEDGER_TABLE}")
        return {r[0] for r in cur.fetchall()}


def ensure_ledger(conn):
    with conn:
        with conn.cursor() as cur:
            cur.execute(LEDGER_DDL)


def apply(conn, migrations_dir=None, out=print):
    """Apply every unrecorded migration in filename order. Returns the list of
    filenames applied this call (empty when the volume is already current)."""
    migrations_dir = migrations_dir or MIGRATIONS_DIR
    if not ledger_exists(conn):
        if user_tables(conn):
            raise LedgerlessDatabaseError(
                "database already contains tables but has no schema_migrations "
                "ledger — refusing to apply. This looks like a volume created "
                "before the migration runner existed; the migration files are "
                "bare DDL and re-running them would crash. Record its "
                "already-applied migrations first:\n\n"
                "    python db/migrate.py baseline\n"
            )
        ensure_ledger(conn)

    done = applied(conn)
    pending = [(fn, path) for fn, path in discover(migrations_dir) if fn not in done]
    if not pending:
        out("nothing to apply — database is current")
        return []

    applied_now = []
    for fn, path in pending:
        with open(path, encoding="utf-8") as f:
            sql = f.read()
        # One transaction per file: on failure `with conn` rolls the whole file
        # back — nothing recorded, no partial DDL left behind (e6-SPEC-11).
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        f"INSERT INTO {LEDGER_TABLE}(filename) VALUES (%s)", (fn,)
                    )
        except Exception as e:
            # Filename + exception class only, never the driver message: a DDL
            # failure against live tables makes Postgres echo offending row
            # values (`Key (ssn)=(...) already exists`) — PHI in operator
            # stderr. The filename is the diagnostic anchor; the row is read
            # with psql by someone who is allowed to see it.
            raise MigrationFailedError(
                f"migration failed at {fn} ({type(e).__name__})"
            ) from e
        out(f"applied {fn}")
        applied_now.append(fn)
    return applied_now


def structural_fingerprint(conn):
    """A name-independent, comparable snapshot of the schema's structure:
    tables/columns/types/nullability/defaults and PK/UNIQUE/FK/CHECK constraints.
    The ledger table and indexes are excluded (e6-SPEC-14, e6-D-10 — indexes are
    D8's deliberate zero-index condition). Compared by content, never by
    Postgres-generated constraint names, which embed differing OIDs across two
    builds."""
    cur = conn.cursor()

    cur.execute(
        "SELECT table_name, column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name <> %s ORDER BY 1,2",
        (LEDGER_TABLE,),
    )
    columns = [tuple(r) for r in cur.fetchall()]

    cur.execute(
        "SELECT tc.table_name, tc.constraint_type, "
        "  (SELECT array_agg(kcu.column_name ORDER BY kcu.column_name) "
        "     FROM information_schema.key_column_usage kcu "
        "    WHERE kcu.constraint_name = tc.constraint_name "
        "      AND kcu.table_schema = tc.table_schema) "
        "FROM information_schema.table_constraints tc "
        "WHERE tc.table_schema='public' AND tc.table_name <> %s "
        "  AND tc.constraint_type IN ('PRIMARY KEY','UNIQUE')",
        (LEDGER_TABLE,),
    )
    pk_unique = sorted((t, ct, tuple(cols or [])) for t, ct, cols in cur.fetchall())

    cur.execute(
        "SELECT tc.table_name, kcu.column_name, ccu.table_name, ccu.column_name "
        "FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu "
        "  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
        "JOIN information_schema.constraint_column_usage ccu "
        "  ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema "
        "WHERE tc.table_schema='public' AND tc.table_name <> %s "
        "  AND tc.constraint_type = 'FOREIGN KEY'",
        (LEDGER_TABLE,),
    )
    fks = sorted(tuple(r) for r in cur.fetchall())

    # Explicit CHECKs only — the implicit NOT NULL checks are already carried by
    # is_nullable in `columns`, and their generated names embed OIDs.
    cur.execute(
        "SELECT tc.table_name, cc.check_clause "
        "FROM information_schema.check_constraints cc "
        "JOIN information_schema.table_constraints tc "
        "  ON cc.constraint_name = tc.constraint_name AND cc.constraint_schema = tc.table_schema "
        "WHERE tc.table_schema='public' AND tc.table_name <> %s "
        "  AND tc.constraint_type = 'CHECK' AND cc.check_clause NOT LIKE %s",
        (LEDGER_TABLE, "%IS NOT NULL%"),
    )
    checks = sorted(tuple(r) for r in cur.fetchall())

    return {"columns": columns, "pk_unique": pk_unique, "fks": fks, "checks": checks}


def _drop_scratch(name):
    admin = connect(dbname="postgres")
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        admin.close()


def baseline(conn, migrations_dir=None, out=print):
    """Record the full on-disk migration set as applied WITHOUT running it, but
    only after the live schema is verified to structurally match a scratch build
    of that same set (e6-D-19). Refuses (stamping nothing) on any mismatch, so a
    behind-head volume is never falsely recorded current. Returns True if it
    stamped, False if the ledger was already present."""
    if ledger_exists(conn) and applied(conn):
        out("ledger already present — nothing to baseline")
        return False

    scratch = f"migrate_scratch_{uuid.uuid4().hex[:12]}"
    admin = connect(dbname="postgres")
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{scratch}"')
    finally:
        admin.close()
    try:
        sconn = connect(dbname=scratch)
        try:
            # Reuse the runner's own apply path — the reference schema is the
            # same artifact the parity test pins, no second schema source.
            apply(sconn, migrations_dir, out=lambda *_: None)
            reference = structural_fingerprint(sconn)
        finally:
            sconn.close()

        if structural_fingerprint(conn) != reference:
            raise BaselineMismatchError(
                "live schema does not structurally match the full migration set "
                "— refusing to baseline. This volume is behind head (or has "
                "drifted); stamping it would record migrations it does not "
                "carry and the runner would then skip the repairs it needs. "
                "Bring it to head manually, then re-run baseline."
            )

        ensure_ledger(conn)
        migrations = discover(migrations_dir)
        with conn:
            with conn.cursor() as cur:
                for fn, _ in migrations:
                    cur.execute(
                        f"INSERT INTO {LEDGER_TABLE}(filename) VALUES (%s) "
                        "ON CONFLICT (filename) DO NOTHING",
                        (fn,),
                    )
        out(f"baseline recorded {len(migrations)} migrations; ran none")
        return True
    finally:
        _drop_scratch(scratch)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "apply"
    if cmd not in ("apply", "baseline"):
        print(f"unknown command {cmd!r} (use: apply | baseline)", file=sys.stderr)
        return 2
    conn = connect()
    try:
        if cmd == "baseline":
            baseline(conn)
        else:
            apply(conn)
    except (LedgerlessDatabaseError, BaselineMismatchError, MigrationFailedError) as e:
        # These three carry runner-authored text only — no driver message.
        print(str(e), file=sys.stderr)
        return 1
    except Exception as e:  # a dead connection, an unreadable file, etc.
        print(f"migration failed ({type(e).__name__})", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
