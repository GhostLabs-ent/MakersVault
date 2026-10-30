"""Migration 014 records who added each asset and through which door.

014 is DB-only and append-only: two nullable `VARCHAR` columns and nothing else -
no index, no backfill, no filesystem work. The tests here pin the ledger, the
columns' shape, and the three properties a later change could quietly break:

* re-applying 014 is harmless - `_add_column` guards on `PRAGMA table_info` -
  and it preserves a row whose attribution was already stamped;
* a v13 database upgrades to 14 without touching the asset rows it already had,
  and each existing row reads (NULL, NULL): attribution unknown, never
  backfilled or guessed;
* the columns arrive without an index, so a filter on them is a query, not a
  schema promise.

Later migrations may be appended, so the version and ledger assertions scope
themselves the way `test_migration_011.py` does - there is deliberately no
`MIGRATIONS[-1].version == 14` pin.
"""

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from migrations import MIGRATIONS, _migration_014_asset_attribution, applied_migrations, run_migrations

ASSET_TABLE = "asset"
CREATED_BY_COLUMN = "created_by"
CREATED_VIA_COLUMN = "created_via"
ATTRIBUTION_COLUMNS = (CREATED_BY_COLUMN, CREATED_VIA_COLUMN)

SHIPPED_LEDGER = {
    1: "initial_schema",
    2: "nested_folders_and_mount_sources",
    3: "asset_metadata_and_bundles",
    4: "folder_identity_and_reference_flags",
    5: "users_and_sessions",
    6: "audit_log",
    7: "projects",
    8: "import_run_history",
    9: "asset_file_order",
    10: "oidc_identities",
    11: "session_rotation_history",
    12: "mfa_totp",
    13: "asset_thumb_version",
}

# The columns a v13 database had that this test compares - a deliberate subset,
# because `SELECT *` would compare 15 columns against 17 and fail on an
# unchanged row. It spans one column from each append (001 `filename`, 002
# `source_path`, 003 `name`, 004 `is_reference`, 013 `thumb_version`) so the
# equality really proves that the whole row survived, not just three columns.
ASSET_V13_COLUMNS_SELECT = (
    "SELECT id, filename, mime, tags_json, title, source_path, name, creator, collection, "
    "storage_path, missing_since, is_reference, thumb_version FROM asset ORDER BY id"
)


def sqlite_engine(path: Path) -> Engine:
    database_engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(database_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        # Same per-connection pragma the API engine installs in `db.py`.
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return database_engine


def make_v13_engine(path: Path) -> Engine:
    database_engine = sqlite_engine(path)
    assert run_migrations(database_engine, MIGRATIONS[:13]) == 13
    return database_engine


def table_columns(database_engine: Engine, table: str) -> set[str]:
    with database_engine.connect() as conn:
        rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def attribution_column(database_engine: Engine, column: str) -> tuple:
    """The `PRAGMA table_info` row for one new column: (name, type, notnull, dflt_value)."""
    with database_engine.connect() as conn:
        rows = conn.exec_driver_sql(f"PRAGMA table_info({ASSET_TABLE})").fetchall()
    return next(tuple(row[1:5]) for row in rows if str(row[1]) == column)


def asset_indexes(database_engine: Engine) -> dict[str, tuple[str, ...]]:
    """Index name -> the columns it covers, straight from SQLite's catalogue."""
    with database_engine.connect() as conn:
        names = [str(row[1]) for row in conn.exec_driver_sql(f"PRAGMA index_list({ASSET_TABLE})").fetchall()]
        return {
            name: tuple(
                str(row[2]) for row in conn.exec_driver_sql(f"PRAGMA index_info('{name}')").fetchall()
            )
            for name in names
        }


def migration_014():
    return next(migration for migration in MIGRATIONS if migration.version == 14)


def insert_asset(conn, asset_id: str, filename: str) -> None:
    conn.exec_driver_sql(
        "INSERT INTO asset(id, filename, mime, size) VALUES (?, ?, 'model/stl', 42)",
        (asset_id, filename),
    )


def test_fresh_database_reaches_v14(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "fresh.db")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    migration = migration_014()
    assert migration.name == "asset_attribution"
    ledger = applied_migrations(database_engine)
    assert {version: ledger[version] for version in SHIPPED_LEDGER} == SHIPPED_LEDGER
    assert ledger[14] == "asset_attribution"


def test_the_attribution_columns_are_nullable_text_without_a_default(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "columns.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    assert attribution_column(database_engine, CREATED_BY_COLUMN) == (CREATED_BY_COLUMN, "VARCHAR", 0, None)
    assert attribution_column(database_engine, CREATED_VIA_COLUMN) == (CREATED_VIA_COLUMN, "VARCHAR", 0, None)
    assert table_columns(database_engine, ASSET_TABLE) >= set(ATTRIBUTION_COLUMNS)


def test_upgrading_a_v13_database_keeps_its_assets_and_leaves_them_unattributed(tmp_path: Path) -> None:
    database_engine = make_v13_engine(tmp_path / "upgrade.db")
    with database_engine.begin() as conn:
        insert_asset(conn, "a-1", "cube.stl")
    with database_engine.connect() as conn:
        assets_before = tuple(conn.exec_driver_sql(ASSET_V13_COLUMNS_SELECT).fetchall())

    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    with database_engine.connect() as conn:
        assert tuple(conn.exec_driver_sql(ASSET_V13_COLUMNS_SELECT).fetchall()) == assets_before
        # (NULL, NULL) means "this row predates attribution", never a guessed door.
        assert tuple(conn.exec_driver_sql("SELECT created_by, created_via FROM asset").one()) == (None, None)


def test_reapplying_014_is_harmless_and_preserves_a_stamped_row(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "idempotent.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    with database_engine.begin() as conn:
        insert_asset(conn, "a-1", "cube.stl")
        conn.exec_driver_sql("UPDATE asset SET created_by = 'ada', created_via = 'upload' WHERE id = 'a-1'")

    for _ in range(2):
        with database_engine.begin() as conn:
            _migration_014_asset_attribution(conn)

    with database_engine.connect() as conn:
        assert tuple(conn.exec_driver_sql("SELECT created_by, created_via FROM asset").one()) == ("ada", "upload")


def test_014_creates_no_index(tmp_path: Path) -> None:
    """Attribution is filterable, not indexed: no query plan is promised here."""
    database_engine = make_v13_engine(tmp_path / "no_index.db")
    indexes_before = asset_indexes(database_engine)
    with database_engine.begin() as conn:
        _migration_014_asset_attribution(conn)
    indexes_after = asset_indexes(database_engine)

    assert indexes_after == indexes_before
    assert [columns for columns in indexes_after.values() if set(columns) & set(ATTRIBUTION_COLUMNS)] == []
