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
    assert {
        "folder",
        "asset",
        "assetfile",
        "artifactrevision",
        "contenthashjob",
        "contenthashjobitem",
        "trashpurgeoperation",
        "project",
        "projectmembership",
        "projectrelationship",
        "appconfig",
        "mountscan",
        "schema_migration",
    }.issubset(tables)


def test_schema8_to_schema9_project_expansion_is_empty_and_preserves_artifacts(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "schema8.db"
    create_pre_v5_1_fixture(db_path)
    database_engine = sqlite_engine(db_path)
    assert run_migrations(database_engine, MIGRATIONS[:8]) == 8

    with database_engine.connect() as conn:
        assets_before = conn.exec_driver_sql(
            "SELECT id, name, filename, folder_id, source_path, storage_path, "
            "current_revision_id, deleted_at FROM asset ORDER BY id"
        ).fetchall()
        revisions_before = conn.exec_driver_sql(
            "SELECT id, asset_id, revision_number, filename, storage_path, source_path "
            "FROM artifactrevision ORDER BY asset_id, revision_number"
        ).fetchall()

    assert run_migrations(database_engine, MIGRATIONS[:9]) == 9
    assert run_migrations(database_engine, MIGRATIONS[:9]) == 9

    with database_engine.connect() as conn:
        assets_after = conn.exec_driver_sql(
            "SELECT id, name, filename, folder_id, source_path, storage_path, "
            "current_revision_id, deleted_at FROM asset ORDER BY id"
        ).fetchall()
        revisions_after = conn.exec_driver_sql(
            "SELECT id, asset_id, revision_number, filename, storage_path, source_path "
            "FROM artifactrevision ORDER BY asset_id, revision_number"
        ).fetchall()
        project_count = conn.exec_driver_sql("SELECT COUNT(*) FROM project").scalar_one()
        membership_count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM projectmembership"
        ).scalar_one()
        project_indexes = {
            str(row[1])
            for row in conn.exec_driver_sql("PRAGMA index_list(project)").fetchall()
        }
        membership_foreign_keys = {
            (str(row[2]), str(row[3]), str(row[4]))
            for row in conn.exec_driver_sql(
                "PRAGMA foreign_key_list(projectmembership)"
            ).fetchall()
        }

    assert assets_after == assets_before
    assert revisions_after == revisions_before
    assert project_count == 0
    assert membership_count == 0
    assert "idx_project_active_name_unique" in project_indexes
    assert membership_foreign_keys == {
        ("asset", "asset_id", "id"),
        ("project", "project_id", "id"),
    }


def test_schema9_to_schema10_relationship_expansion_is_empty_and_preserves_state(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "schema9.db"
    create_pre_v5_1_fixture(db_path)
    database_engine = sqlite_engine(db_path)
    assert run_migrations(database_engine, MIGRATIONS[:9]) == 9
    with database_engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO project(id, name, tags_json, created_at, updated_at) "
            "VALUES ('project-1', 'Fixture Project', '[]', 'now', 'now')"
        )
        conn.exec_driver_sql(
            "INSERT INTO projectmembership(project_id, asset_id, created_at) "
            "VALUES ('project-1', 'asset-1', 'now')"
        )
    with database_engine.connect() as conn:
        state_before = {
            "assets": conn.exec_driver_sql(
                "SELECT id, name, filename, folder_id, storage_path, current_revision_id, deleted_at "
                "FROM asset ORDER BY id"
            ).fetchall(),
            "revisions": conn.exec_driver_sql(
                "SELECT id, asset_id, revision_number, storage_path, source_path "
                "FROM artifactrevision ORDER BY id"
            ).fetchall(),
            "projects": conn.exec_driver_sql("SELECT * FROM project ORDER BY id").fetchall(),
            "memberships": conn.exec_driver_sql(
                "SELECT * FROM projectmembership ORDER BY project_id, asset_id"
            ).fetchall(),
        }

    assert run_migrations(database_engine) == 10
    assert run_migrations(database_engine) == 10

    with database_engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM projectrelationship").scalar_one() == 0
        assert conn.exec_driver_sql(
            "SELECT id, name, filename, folder_id, storage_path, current_revision_id, deleted_at "
            "FROM asset ORDER BY id"
        ).fetchall() == state_before["assets"]
        assert conn.exec_driver_sql(
            "SELECT id, asset_id, revision_number, storage_path, source_path "
            "FROM artifactrevision ORDER BY id"
        ).fetchall() == state_before["revisions"]
        assert conn.exec_driver_sql("SELECT * FROM project ORDER BY id").fetchall() == state_before["projects"]
        assert conn.exec_driver_sql(
            "SELECT * FROM projectmembership ORDER BY project_id, asset_id"
        ).fetchall() == state_before["memberships"]
        indexes = {
            str(row[1])
            for row in conn.exec_driver_sql("PRAGMA index_list(projectrelationship)").fetchall()
        }
        foreign_keys = {
            (str(row[2]), str(row[3]), str(row[4]))
            for row in conn.exec_driver_sql(
                "PRAGMA foreign_key_list(projectrelationship)"
            ).fetchall()
        }
    assert "idx_projectrelationship_canonical_unique" in indexes
    assert foreign_keys == {
        ("asset", "target_asset_id", "id"),
        ("asset", "source_asset_id", "id"),
        ("project", "project_id", "id"),
    }

    with database_engine.begin() as conn:
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql(
                "INSERT INTO projectrelationship(id, project_id, source_asset_id, "
                "target_asset_id, kind, created_at) VALUES "
                "('bad-kind', 'project-1', 'asset-1', 'asset-2', 'source_of', 'now')"
            )


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
        "preview_status",
        "preview_reason",
        "preview_attempts",
        "preview_policy_version",
        "preview_updated_at",
        "preview_source",
        "current_revision_id",
        "current_thumb_path",
        "deleted_at",
        "trash_original_folder_id",
        "trash_original_folder_name",
    }.issubset(table_columns(database_engine, "asset"))
    assert "parent_id" in table_columns(database_engine, "folder")
    assert {
        "trigger",
        "status",
        "mode",
        "root_path",
        "started_at",
        "finished_at",
        "imported",
        "skipped",
        "failed",
        "failure_details_json",
        "failure_details_omitted",
    }.issubset(table_columns(database_engine, "mountscan"))
    assert {
        "asset_id",
        "revision_number",
        "sha256",
        "observed_sha256",
        "content_state",
        "storage_path",
        "source_path",
        "prepared_file_id",
        "preview_status",
        "preview_thumb_path",
    }.issubset(table_columns(database_engine, "artifactrevision"))
    assert "revision_id" in table_columns(database_engine, "assetfile")
    assert {
        "trigger",
        "status",
        "asset_ids_json",
        "paths_json",
        "results_json",
        "quarantine_path",
        "requested_bytes",
        "managed_bytes",
        "error",
    }.issubset(table_columns(database_engine, "trashpurgeoperation"))

    with database_engine.connect() as conn:
        assets = conn.exec_driver_sql(
            "SELECT id, name, title, storage_path, supporting_file_count "
            "FROM asset ORDER BY id"
        ).fetchall()
        migration_count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM schema_migration"
        ).scalar_one()
        revisions = conn.exec_driver_sql(
            """
            SELECT a.id, a.current_revision_id, r.asset_id, r.revision_number,
                   r.filename, r.storage_path, r.content_state
            FROM asset a
            JOIN artifactrevision r ON r.id = a.current_revision_id
            ORDER BY a.id
            """
        ).fetchall()

    assert assets == [
        ("asset-1", "Widget", "Widget", "asset-1/widget.stl", 0),
        ("asset-2", "Widget (2)", "Widget (2)", "asset-2/widget-copy.stl", 0),
    ]
    assert migration_count == len(MIGRATIONS)
    assert [(row[0], row[2], row[3], row[4], row[5], row[6]) for row in revisions] == [
        ("asset-1", "asset-1", 1, "widget.stl", "asset-1/widget.stl", "pending"),
        ("asset-2", "asset-2", 1, "widget-copy.stl", "asset-2/widget-copy.stl", "pending"),
    ]
    assert all(row[1] for row in revisions)
    with database_engine.connect() as conn:
        thumb_paths = conn.exec_driver_sql(
            "SELECT id, current_thumb_path FROM asset ORDER BY id"
        ).fetchall()
    assert thumb_paths == [
        ("asset-1", "thumbs/asset-1.jpg"),
        ("asset-2", "thumbs/asset-2.jpg"),
    ]
    with database_engine.connect() as conn:
        trash_defaults = conn.exec_driver_sql(
            "SELECT id, deleted_at, trash_original_folder_id FROM asset ORDER BY id"
        ).fetchall()
    assert trash_defaults == [
        ("asset-1", None, None),
        ("asset-2", None, None),
    ]

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


def test_schema7_to_schema8_upgrade_preserves_identity_and_byte_paths(tmp_path: Path) -> None:
    db_path = tmp_path / "schema7.db"
    create_pre_v5_1_fixture(db_path)
    database_engine = sqlite_engine(db_path)
    assert run_migrations(database_engine, MIGRATIONS[:7]) == 7

    with database_engine.connect() as conn:
        assets_before = conn.exec_driver_sql(
            "SELECT id, name, filename, folder_id, source_path, storage_path, "
            "prepared_file_id, current_revision_id, current_thumb_path "
            "FROM asset ORDER BY id"
        ).fetchall()
        revisions_before = conn.exec_driver_sql(
            "SELECT id, asset_id, revision_number, filename, storage_path, source_path, "
            "prepared_file_id, preview_thumb_path FROM artifactrevision ORDER BY asset_id"
        ).fetchall()

    assert run_migrations(database_engine, MIGRATIONS[:8]) == 8
    assert run_migrations(database_engine, MIGRATIONS[:8]) == 8

    with database_engine.connect() as conn:
        assets_after = conn.exec_driver_sql(
            "SELECT id, name, filename, folder_id, source_path, storage_path, "
            "prepared_file_id, current_revision_id, current_thumb_path "
            "FROM asset ORDER BY id"
        ).fetchall()
        revisions_after = conn.exec_driver_sql(
            "SELECT id, asset_id, revision_number, filename, storage_path, source_path, "
            "prepared_file_id, preview_thumb_path FROM artifactrevision ORDER BY asset_id"
        ).fetchall()
        trash_defaults = conn.exec_driver_sql(
            "SELECT id, deleted_at, trash_original_folder_id, trash_original_folder_name "
            "FROM asset ORDER BY id"
        ).fetchall()
        purge_count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM trashpurgeoperation"
        ).scalar_one()

    assert assets_after == assets_before
    assert revisions_after == revisions_before
    assert trash_defaults == [
        ("asset-1", None, None, None),
        ("asset-2", None, None, None),
    ]
    assert purge_count == 0


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
