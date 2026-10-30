"""Migration 013 adds the monotonic thumbnail version `asset.thumb_version`.

013 is DB-only and append-only: one `INTEGER NOT NULL DEFAULT 0` column and
nothing else - no index, no filesystem work, no thumbnail touched. The tests
here pin the ledger, the column's shape, and the two properties a later change
could quietly break:

* re-applying 013 is harmless - `_add_column` guards on `PRAGMA table_info` -
  and it preserves a row whose version was already bumped;
* a v12 database upgrades to 13 without touching the asset rows it already
  had, and each existing row defaults to 0 ("no thumbnail"), never NULL.

Later migrations may be appended, so the version and ledger assertions scope
themselves the way `test_migration_011.py` does - there is deliberately no
`MIGRATIONS[-1].version == 13` pin.
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

import db
from migrations import MIGRATIONS, applied_migrations, run_migrations

ASSET_TABLE = "asset"
THUMB_VERSION_COLUMN = "thumb_version"

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
}

# The columns a v12 database had that this test compares - a deliberate
# subset, because `SELECT *` would compare 19 columns against 20 and fail on an
# unchanged row. It spans one column from each append (001 `filename`, 002
# `source_path`, 003 `name`, 004 `is_reference`) so the equality really proves
# that the whole row survived, not just three columns of it.
ASSET_V12_COLUMNS_SELECT = (
    "SELECT id, filename, mime, tags_json, title, source_path, name, creator, collection, "
    "storage_path, missing_since, is_reference FROM asset ORDER BY id"
)


def sqlite_engine(path: Path) -> Engine:
    database_engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(database_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        # Same per-connection pragma the API engine installs in `db.py`.
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return database_engine


def make_v12_engine(path: Path) -> Engine:
    database_engine = sqlite_engine(path)
    assert run_migrations(database_engine, MIGRATIONS[:12]) == 12
    return database_engine


def table_columns(database_engine: Engine, table: str) -> set[str]:
    with database_engine.connect() as conn:
        rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def thumb_version_column(database_engine: Engine) -> tuple:
    """The `PRAGMA table_info` row for the new column: (name, type, notnull, dflt_value)."""
    with database_engine.connect() as conn:
        rows = conn.exec_driver_sql(f"PRAGMA table_info({ASSET_TABLE})").fetchall()
    return next(tuple(row[1:5]) for row in rows if str(row[1]) == THUMB_VERSION_COLUMN)


def migration_013():
    return next(migration for migration in MIGRATIONS if migration.version == 13)


def insert_asset(conn, asset_id: str, filename: str) -> None:
    conn.exec_driver_sql(
        "INSERT INTO asset(id, filename, mime, size) VALUES (?, ?, 'model/stl', 42)",
        (asset_id, filename),
    )


def test_fresh_database_reaches_v13(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "fresh.db")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    migration = migration_013()
    assert migration.name == "asset_thumb_version"
    ledger = applied_migrations(database_engine)
    assert {version: ledger[version] for version in SHIPPED_LEDGER} == SHIPPED_LEDGER
    assert ledger[13] == "asset_thumb_version"


def test_the_thumb_version_column_is_a_not_null_counter_defaulting_to_zero(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "columns.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    assert thumb_version_column(database_engine) == (THUMB_VERSION_COLUMN, "INTEGER", 1, "0")
    assert table_columns(database_engine, ASSET_TABLE) >= {THUMB_VERSION_COLUMN}


def test_upgrading_a_v12_database_keeps_its_assets_and_defaults_them_to_zero(tmp_path: Path) -> None:
    database_engine = make_v12_engine(tmp_path / "upgrade.db")
    with database_engine.begin() as conn:
        insert_asset(conn, "a-1", "cube.stl")
    with database_engine.connect() as conn:
        assets_before = tuple(conn.exec_driver_sql(ASSET_V12_COLUMNS_SELECT).fetchall())

    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    with database_engine.connect() as conn:
        assert tuple(conn.exec_driver_sql(ASSET_V12_COLUMNS_SELECT).fetchall()) == assets_before
        # NOT NULL DEFAULT 0: an old row reads as "no thumbnail", never NULL.
        assert conn.exec_driver_sql("SELECT thumb_version FROM asset").one() == (0,)


def test_reapplying_013_is_harmless_and_preserves_a_bumped_version(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "idempotent.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    with database_engine.begin() as conn:
        insert_asset(conn, "a-1", "cube.stl")
        conn.exec_driver_sql("UPDATE asset SET thumb_version = 7 WHERE id = 'a-1'")

    migration = migration_013()
    with database_engine.begin() as conn:
        migration.apply(conn)
    with database_engine.begin() as conn:
        migration.apply(conn)

    with database_engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT thumb_version FROM asset").one() == (7,)


def test_applying_013_from_scratch_touches_nothing_under_the_thumbnail_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The column is repaired at boot by the service; the migration does no I/O."""
    database_engine = make_v12_engine(tmp_path / "no_fs.db")
    touched: list[str] = []
    real_stat = os.stat
    real_scandir = os.scandir
    real_listdir = os.listdir

    def under_thumbs(path) -> bool:
        try:
            candidate = Path(os.fspath(path))
        except TypeError:
            return False
        return candidate == db.THUMBS or candidate.is_relative_to(db.THUMBS)

    def recording_stat(path, *args, **kwargs):
        if under_thumbs(path):
            touched.append(os.fspath(path))
        return real_stat(path, *args, **kwargs)

    def recording_scandir(path="."):
        if under_thumbs(path):
            touched.append(os.fspath(path))
        return real_scandir(path)

    def recording_listdir(path="."):
        if under_thumbs(path):
            touched.append(os.fspath(path))
        return real_listdir(path)

    monkeypatch.setattr(os, "stat", recording_stat)
    monkeypatch.setattr(os, "scandir", recording_scandir)
    monkeypatch.setattr(os, "listdir", recording_listdir)

    with database_engine.begin() as conn:
        migration_013().apply(conn)

    assert thumb_version_column(database_engine) == (THUMB_VERSION_COLUMN, "INTEGER", 1, "0")
    assert touched == [], touched
