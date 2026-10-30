"""Migration 009 adds the supporting-file display order.

009 is DB-only: one column, one index, and a one-time backfill. The backfill
assigns 0..n-1 per asset from (filename, id) - the order every earlier build
displayed - so an upgrade never changes what a library looks like. It runs only
when the column was actually added: re-applying 009 must never reset an order
the user chose, which is the one thing a display-order migration can get wrong
without losing data.

Later migrations may be appended, so the version and ledger assertions scope
themselves the way `test_migration_005.py` and `test_migration_008.py` do.
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine

from migrations import MIGRATIONS, applied_migrations, run_migrations

POSITION_INDEX = "idx_assetfile_asset_position"

SHIPPED_LEDGER = {
    1: "initial_schema",
    2: "nested_folders_and_mount_sources",
    3: "asset_metadata_and_bundles",
    4: "folder_identity_and_reference_flags",
    5: "users_and_sessions",
    6: "audit_log",
    7: "projects",
    8: "import_run_history",
}


def sqlite_engine(path: Path) -> Engine:
    return create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})


def make_v8_engine(path: Path) -> Engine:
    database_engine = sqlite_engine(path)
    assert run_migrations(database_engine, MIGRATIONS[:8]) == 8
    return database_engine


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


def insert_asset(conn: Connection, asset_id: str) -> None:
    conn.exec_driver_sql(
        "INSERT INTO asset(id, filename, mime, size, name, storage_path) "
        "VALUES (?, 'model.stl', 'model/stl', 1, ?, ?)",
        (asset_id, asset_id, f"{asset_id}/model.stl"),
    )


def insert_file(conn: Connection, file_id: str, asset_id: str, filename: str, role: str = "supporting") -> None:
    conn.exec_driver_sql(
        "INSERT INTO assetfile(id, asset_id, filename, mime, size, role, storage_path) "
        "VALUES (?, ?, ?, 'text/plain', 1, ?, ?)",
        (file_id, asset_id, filename, role, f"bundles/{asset_id}/{file_id}/{filename}"),
    )


def positions(database_engine: Engine, asset_id: str) -> dict[str, int]:
    """Every row of one asset as {filename: position}, prepared rows included."""
    with database_engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT filename, position FROM assetfile WHERE asset_id = ?", (asset_id,)
        ).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def test_fresh_database_reaches_v9(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "fresh.db")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    migration = next(migration for migration in MIGRATIONS if migration.version == 9)
    assert migration.name == "asset_file_order"
    ledger = applied_migrations(database_engine)
    assert {version: ledger[version] for version in SHIPPED_LEDGER} == SHIPPED_LEDGER
    assert ledger[9] == "asset_file_order"
    assert "position" in table_columns(database_engine, "assetfile")
    assert POSITION_INDEX in object_names(database_engine, "index")


def test_v8_database_backfills_position_from_filename_then_id(tmp_path: Path) -> None:
    database_engine = make_v8_engine(tmp_path / "upgrade.db")
    with database_engine.begin() as conn:
        insert_asset(conn, "a-1")
        insert_asset(conn, "a-2")
        # Inserted out of display order on purpose: the backfill must not depend
        # on insertion order or on rowid.
        insert_file(conn, "f-3", "a-1", "charlie.pdf")
        insert_file(conn, "f-1", "a-1", "alpha.txt")
        insert_file(conn, "f-2", "a-1", "bravo.png")
        insert_file(conn, "f-9", "a-1", "hidden.gcode", role="prepared")
        insert_file(conn, "f-5", "a-2", "zulu.txt")
    with database_engine.connect() as conn:
        rows_before = tuple(
            conn.exec_driver_sql(
                "SELECT id, asset_id, filename, role, size FROM assetfile ORDER BY id"
            ).fetchall()
        )

    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    with database_engine.connect() as conn:
        rows_after = tuple(
            conn.exec_driver_sql(
                "SELECT id, asset_id, filename, role, size FROM assetfile ORDER BY id"
            ).fetchall()
        )
    assert rows_after == rows_before
    assert positions(database_engine, "a-1") == {
        "alpha.txt": 0,
        "bravo.png": 1,
        "charlie.pdf": 2,
        "hidden.gcode": 0,
    }
    assert positions(database_engine, "a-2") == {"zulu.txt": 0}
    assert POSITION_INDEX in object_names(database_engine, "index")


def test_reapplying_009_after_a_manual_reorder_keeps_the_new_order(tmp_path: Path) -> None:
    database_engine = make_v8_engine(tmp_path / "idempotent.db")
    with database_engine.begin() as conn:
        insert_asset(conn, "a-1")
        insert_file(conn, "f-1", "a-1", "alpha.txt")
        insert_file(conn, "f-2", "a-1", "bravo.txt")
        insert_file(conn, "f-3", "a-1", "charlie.txt")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    with database_engine.begin() as conn:
        # The user drags charlie to the top: this is the order that must survive.
        conn.exec_driver_sql("UPDATE assetfile SET position = 0 WHERE id = 'f-3'")
        conn.exec_driver_sql("UPDATE assetfile SET position = 1 WHERE id = 'f-1'")
        conn.exec_driver_sql("UPDATE assetfile SET position = 2 WHERE id = 'f-2'")

    migration = next(migration for migration in MIGRATIONS if migration.version == 9)
    with database_engine.begin() as conn:
        migration.apply(conn)

    assert positions(database_engine, "a-1") == {
        "alpha.txt": 1,
        "bravo.txt": 2,
        "charlie.txt": 0,
    }
    assert POSITION_INDEX in object_names(database_engine, "index")


def test_position_defaults_to_zero_and_the_index_exists(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "defaults.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    with database_engine.begin() as conn:
        insert_asset(conn, "a-1")
        # No position in the INSERT: the column default is the DDL contract.
        conn.exec_driver_sql(
            "INSERT INTO assetfile(id, asset_id, filename, mime, size, role, storage_path) "
            "VALUES ('f-1', 'a-1', 'notes.txt', 'text/plain', 1, 'supporting', 'bundles/a-1/f-1/notes.txt')"
        )

    assert positions(database_engine, "a-1") == {"notes.txt": 0}
    with database_engine.connect() as conn:
        index_sql = conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?", (POSITION_INDEX,)
        ).scalar_one()
    assert "assetfile(asset_id, position)" in str(index_sql)
