"""Migration 008 adds the mount-import run history table.

008 is DB-only: one new table, one index, no backfill and no filesystem work.
These tests pin the schema, the ledger entry, the closed CHECK lists, the
re-apply idempotence, and that a v7 database upgrades without touching its
existing rows. Later migrations may be appended, so the version and ledger
assertions scope themselves the way `test_migration_005.py` does.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from migrations import MIGRATIONS, applied_migrations, run_migrations

IMPORT_RUN_COLUMNS = {
    "id",
    "kind",
    "status",
    "mode",
    "root",
    "started_at",
    "finished_at",
    "registered",
    "known",
    "ignored",
    "failed",
    "rejected",
    "reason",
    "errors_json",
}

NEW_INDEX = "idx_import_run_started_at"

SHIPPED_LEDGER = {
    1: "initial_schema",
    2: "nested_folders_and_mount_sources",
    3: "asset_metadata_and_bundles",
    4: "folder_identity_and_reference_flags",
    5: "users_and_sessions",
    6: "audit_log",
    7: "projects",
}

# Migration 013 appends `asset.thumb_version` after this upgrade path, so "the
# existing rows are kept" is asserted over the columns a v7 database had.
# `SELECT *` would compare 19 columns against 20 and fail on an unchanged row.
ASSET_V7_COLUMNS_SELECT = (
    "SELECT id, filename, mime, size, tags_json, title, notes, folder_id, source_path, name, "
    "creator, collection, storage_path, supporting_file_count, prepared_file_id, "
    "prepared_metadata_json, missing_since, disk_mtime, is_reference FROM asset ORDER BY id"
)


def sqlite_engine(path: Path) -> Engine:
    return create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})


def make_v7_engine(path: Path) -> Engine:
    engine = sqlite_engine(path)
    assert run_migrations(engine, MIGRATIONS[:7]) == 7
    return engine


def table_columns(database_engine: Engine, table: str) -> set[str]:
    with database_engine.connect() as conn:
        rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def object_names(database_engine: Engine, kind: str) -> set[str]:
    with database_engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE 'sqlite_%'", (kind,)
        ).fetchall()
    return {str(row[0]) for row in rows}


def row_count(database_engine: Engine, table: str) -> int:
    with database_engine.connect() as conn:
        return int(conn.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar_one())


def insert_asset(conn: Connection, asset_id: str) -> None:
    conn.exec_driver_sql(
        "INSERT INTO asset(id, filename, mime, size, name, storage_path) "
        "VALUES (?, 'model.stl', 'model/stl', 1, ?, ?)",
        (asset_id, asset_id, f"{asset_id}/model.stl"),
    )


def insert_run(
    conn: Connection,
    run_id: str,
    *,
    kind: str = "mount",
    status: str = "running",
    mode: str | None = None,
    started_at: float = 0.0,
) -> None:
    conn.exec_driver_sql(
        "INSERT INTO import_run(id, kind, status, mode, started_at) VALUES (?, ?, ?, ?, ?)",
        (run_id, kind, status, mode, started_at),
    )


def test_fresh_database_reaches_v8(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "fresh.db")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    migration = next(migration for migration in MIGRATIONS if migration.version == 8)
    assert migration.name == "import_run_history"
    ledger = applied_migrations(database_engine)
    assert {version: ledger[version] for version in SHIPPED_LEDGER} == SHIPPED_LEDGER
    assert ledger[8] == "import_run_history"
    assert table_columns(database_engine, "import_run") == IMPORT_RUN_COLUMNS
    assert NEW_INDEX in object_names(database_engine, "index")


def test_v7_database_upgrades_and_keeps_existing_rows(tmp_path: Path) -> None:
    database_engine = make_v7_engine(tmp_path / "upgrade.db")
    with database_engine.begin() as conn:
        insert_asset(conn, "a-1")
        insert_asset(conn, "a-2")
    with database_engine.connect() as conn:
        assets_before = tuple(conn.exec_driver_sql(ASSET_V7_COLUMNS_SELECT).fetchall())

    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    with database_engine.connect() as conn:
        assert tuple(conn.exec_driver_sql(ASSET_V7_COLUMNS_SELECT).fetchall()) == assets_before
    assert row_count(database_engine, "import_run") == 0


def test_migration_008_is_idempotent(tmp_path: Path) -> None:
    database_engine = make_v7_engine(tmp_path / "idempotent.db")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    with database_engine.begin() as conn:
        insert_run(conn, "run-1", status="succeeded", mode="copy", started_at=1.0)
    with database_engine.connect() as conn:
        runs_before = tuple(conn.exec_driver_sql("SELECT * FROM import_run ORDER BY id").fetchall())

    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    migration = next(migration for migration in MIGRATIONS if migration.version == 8)
    with database_engine.begin() as conn:
        migration.apply(conn)

    with database_engine.connect() as conn:
        assert tuple(conn.exec_driver_sql("SELECT * FROM import_run ORDER BY id").fetchall()) == runs_before
    assert NEW_INDEX in object_names(database_engine, "index")


def test_closed_check_lists_reject_unknown_values(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "checks.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    with pytest.raises(IntegrityError):
        with database_engine.begin() as conn:
            insert_run(conn, "run-bad-kind", kind="storage")

    with pytest.raises(IntegrityError):
        with database_engine.begin() as conn:
            insert_run(conn, "run-bad-status", status="queued")

    with pytest.raises(IntegrityError):
        with database_engine.begin() as conn:
            insert_run(conn, "run-bad-mode", mode="move")


def test_defaults_and_null_mode_match_the_ddl(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "defaults.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    with database_engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO import_run(id, status, started_at) VALUES ('run-1', 'running', 1.0)")

    with database_engine.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT kind, mode, finished_at, registered, known, ignored, failed, rejected, reason, errors_json "
            "FROM import_run WHERE id = 'run-1'"
        ).fetchone()
    assert tuple(row) == ("mount", None, None, 0, 0, 0, 0, 0, None, "[]")
