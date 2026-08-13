"""The upgrade path for a database created before a migration (PR #76 round 6).

`db/migrations/*.sql` has no runner (`CLAUDE.md` §2) and `docker-compose.yml`
mounts `db/schema.sql` into `/docker-entrypoint-initdb.d`, which Postgres runs
**only** on a brand-new volume. So a `pgdata` volume that predates a migration
never receives it, and the first service that reads the new table answers 503
on every request — measured for `registration_submissions` against a volume
seeded from `main`'s schema (`docs/workflow/e5/findings.md` E-6). The class is
older than this branch: `insurance_coverages` (005), `roi_requests` (008) and
`duplicate_review_queue` (009) are read the same unconditional way.

What makes an upgrade possible at all is that `db/schema.sql` is re-appliable:
every table is `CREATE TABLE IF NOT EXISTS`, so piping the file into a running
database creates what is missing and no-ops what is not. `make schema-apply`
is that one command, and these tests pin the three properties it rests on —
the re-appliable form, the hand-sync that makes the flattened file a complete
substitute for the migration history, and the target applying the schema
WITHOUT the seed (re-running `db/seed/seed.sql` on a populated volume doubles
every serial-id table; see the debt-log row).

Structural assertions on tracked files only — nothing here needs a database.
"""
import glob
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "db" / "schema.sql"
MIGRATIONS = sorted(glob.glob(str(ROOT / "db" / "migrations" / "*.sql")))

_CREATE_TABLE = re.compile(r"CREATE TABLE(\s+IF NOT EXISTS)?\s+(\w+)", re.I)
_TABLE_BLOCK = re.compile(
    r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(\w+)\s*\((.*?)\n\);", re.S | re.I
)
_ADD_COLUMN = re.compile(r"ALTER TABLE\s+(\w+)\s+ADD COLUMN\s+(\w+)", re.I)


def _schema_text():
    return SCHEMA.read_text()


def _schema_blocks():
    return {
        m.group(1).lower(): m.group(2) for m in _TABLE_BLOCK.finditer(_schema_text())
    }


def _makefile_recipe(target):
    """The recipe lines of one Makefile target, comments and blanks dropped."""
    lines = (ROOT / "Makefile").read_text().splitlines()
    out, collecting = [], False
    for line in lines:
        if re.match(rf"^{re.escape(target)}\s*:", line):
            collecting = True
            continue
        if collecting:
            if line.startswith("\t"):
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    out.append(stripped)
            elif line.strip() == "":
                continue
            else:
                break
    return out


def test_every_flattened_table_is_re_appliable():
    """The property the whole upgrade path rests on. A future plain
    `CREATE TABLE` in db/schema.sql makes the file abort partway through on an
    existing database — and it aborts on the FIRST existing table, so the new
    one at the bottom never gets created while psql reports errors nobody
    reads."""
    plain = [
        m.group(2)
        for m in _CREATE_TABLE.finditer(_schema_text())
        if not m.group(1)
    ]
    assert plain == [], (
        "db/schema.sql must stay re-appliable — these tables are not "
        f"IF NOT EXISTS, so `make schema-apply` breaks on an existing DB: {plain}"
    )


@pytest.mark.parametrize("path", MIGRATIONS, ids=[pathlib.Path(p).name for p in MIGRATIONS])
def test_every_migrated_table_reached_the_flattened_schema(path):
    """`docs/landmines.md` §2: the migration and the flattened schema are
    hand-synced. A table that exists only in a migration file cannot be applied
    by `make schema-apply` at all, so the upgrade path silently skips it."""
    migrated = {m.group(2).lower() for m in _CREATE_TABLE.finditer(pathlib.Path(path).read_text())}
    missing = sorted(migrated - set(_schema_blocks()))
    assert missing == [], (
        f"{pathlib.Path(path).name} creates tables db/schema.sql does not have — "
        f"the two files have drifted: {missing}"
    )


@pytest.mark.parametrize("path", MIGRATIONS, ids=[pathlib.Path(p).name for p in MIGRATIONS])
def test_every_migrated_column_reached_the_flattened_schema(path):
    """The column half of the same hand-sync. This one is also the bound on the
    upgrade path: `IF NOT EXISTS` skips a table that already exists, columns
    and all, so a migration that ADDs a column to an existing table is NOT
    applied by re-running the schema — the runbook says so, and this test at
    least guarantees the flattened file is not itself behind."""
    blocks = _schema_blocks()
    missing = []
    for m in _ADD_COLUMN.finditer(pathlib.Path(path).read_text()):
        table, column = m.group(1).lower(), m.group(2).lower()
        block = blocks.get(table)
        if block is None or not re.search(rf"^\s*{column}\b", block, re.M | re.I):
            missing.append(f"{table}.{column}")
    assert missing == [], (
        f"{pathlib.Path(path).name} adds columns db/schema.sql does not carry: {missing}"
    )


def test_the_schema_apply_target_never_runs_the_seed():
    """The upgrade command applies DDL and nothing else. `db/seed/seed.sql` has
    no ON CONFLICT anywhere, so on a populated volume its explicit-id inserts
    error and every serial-id table DOUBLES (measured: consents 403→806,
    insurance_coverages 255→510). An operator upgrading a database must not be
    handed a command that does that."""
    recipe = _makefile_recipe("schema-apply")
    assert recipe, "Makefile has no schema-apply target"
    body = "\n".join(recipe)
    assert "db/schema.sql" in body, "schema-apply must apply db/schema.sql"
    assert "seed" not in body, (
        "schema-apply must not touch the seed — re-running db/seed/seed.sql on a "
        f"populated volume duplicates every serial-id table: {recipe}"
    )


def test_the_seed_target_still_does_both():
    """Positive control for the assertion above: `make seed` is the target that
    loads schema AND demo data, so the two are distinguishable and the test
    above cannot pass by reading the wrong recipe."""
    body = "\n".join(_makefile_recipe("seed"))
    assert "db/schema.sql" in body and "db/seed/seed.sql" in body


def test_the_runbook_documents_the_upgrade_path_and_its_bound():
    """An upgrade command nobody can find is not a path. The runbook is where
    an operator looks (`docs/runbook.md` already advertises `make seed` for an
    already-running DB, which is the command that duplicates the data), so the
    correction has to live there and has to state what re-applying the schema
    does NOT do."""
    text = (ROOT / "docs" / "runbook.md").read_text()
    assert "make schema-apply" in text, "docs/runbook.md does not name the upgrade command"
    assert "ADD COLUMN" in text, (
        "docs/runbook.md must state the bound: IF NOT EXISTS skips an existing "
        "table, so an ALTER TABLE ... ADD COLUMN migration still needs hand-applying"
    )
