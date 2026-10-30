from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

from migrations import MIGRATIONS, Migration, applied_migrations, run_migrations


def sqlite_engine(path: Path):
    return create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )


def create_pre_v5_1_fixture(path: Path) -> None:
    fixture_engine = sqlite_engine(path)
    with fixture_engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE folder (id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, tags_json VARCHAR NOT NULL)"
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE asset (
                id VARCHAR PRIMARY KEY,
                filename VARCHAR NOT NULL,
                mime VARCHAR NOT NULL,
                size INTEGER NOT NULL,
                tags_json VARCHAR NOT NULL,
                title VARCHAR,
                notes VARCHAR,
                folder_id VARCHAR
            )
            """
        )
        conn.exec_driver_sql(
            "CREATE TABLE appconfig (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL)"
        )
        conn.exec_driver_sql(
            "INSERT INTO folder(id, name, tags_json) VALUES ('folder-1', 'Parts', '[]')"
        )
        conn.exec_driver_sql(
            """
            INSERT INTO asset(id, filename, mime, size, tags_json, title, notes, folder_id)
            VALUES
              ('asset-1', 'widget.stl', 'model/stl', 120, '[]', 'Widget', 'First', 'folder-1'),
              ('asset-2', 'widget-copy.stl', 'model/stl', 130, '[]', 'Widget', 'Second', 'folder-1')
            """
        )


def table_columns(database_engine, table: str) -> set[str]:
    with database_engine.connect() as conn:
        return {
            str(row[1])
            for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
        }


def test_fresh_database_reaches_current_schema(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "fresh.db")

    version = run_migrations(database_engine)

    assert version == MIGRATIONS[-1].version
    assert applied_migrations(database_engine) == {
        migration.version: migration.name for migration in MIGRATIONS
    }
    with database_engine.connect() as conn:
        tables = {
            str(row[0])
            for row in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {"folder", "asset", "assetfile", "appconfig", "schema_migration"}.issubset(tables)


def test_pre_v5_1_fixture_migrates_and_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    create_pre_v5_1_fixture(db_path)
    database_engine = sqlite_engine(db_path)

    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    assert {
        "name",
        "creator",
        "collection",
        "source_path",
        "storage_path",
        "supporting_file_count",
        "prepared_file_id",
        "prepared_metadata_json",
    }.issubset(table_columns(database_engine, "asset"))
    assert "parent_id" in table_columns(database_engine, "folder")

    with database_engine.connect() as conn:
        assets = conn.exec_driver_sql(
            "SELECT id, name, title, storage_path, supporting_file_count "
            "FROM asset ORDER BY id"
        ).fetchall()
        migration_count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM schema_migration"
        ).scalar_one()

    assert assets == [
        ("asset-1", "Widget", "Widget", "asset-1/widget.stl", 0),
        ("asset-2", "Widget (2)", "Widget (2)", "asset-2/widget-copy.stl", 0),
    ]
    assert migration_count == len(MIGRATIONS)

    with pytest.raises(IntegrityError):
        with database_engine.begin() as conn:
            conn.exec_driver_sql(
                """
                INSERT INTO asset(
                    id, name, filename, mime, size, tags_json, title,
                    folder_id, storage_path, supporting_file_count
                ) VALUES (
                    'asset-3', 'widget', 'third.stl', 'model/stl', 140, '[]',
                    'widget', 'folder-1', 'asset-3/third.stl', 0
                )
                """
            )


def test_failed_migration_is_not_recorded(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "failed.db")

    def fail(_conn) -> None:
        raise RuntimeError("planned migration failure")

    failing = (*MIGRATIONS, Migration(99, "planned_failure", fail))

    with pytest.raises(RuntimeError, match="planned migration failure"):
        run_migrations(database_engine, failing)

    assert 99 not in applied_migrations(database_engine)


def test_recorded_migration_name_mismatch_stops_startup(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "mismatch.db")
    run_migrations(database_engine)
    with database_engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE schema_migration SET name = 'unexpected' WHERE version = 1"
        )

    with pytest.raises(RuntimeError, match="recorded as"):
        run_migrations(database_engine)


def test_unknown_newer_migration_stops_older_build(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "newer.db")
    run_migrations(database_engine)
    with database_engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO schema_migration(version, name) VALUES (999, 'future_schema')"
        )

    with pytest.raises(RuntimeError, match="newer or unknown"):
        run_migrations(database_engine)
