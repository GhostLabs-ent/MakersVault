"""Migration 007 adds projects and their asset memberships.

007 is DB-only (new tables, no backfill, no filesystem) and is the migration
that turns on `PRAGMA foreign_keys` in the API engine, so these tests pin the
schema, the ledger entry, the cascade and SET NULL behaviour, the CHECK and
uniqueness constraints, the orphan sweep, and the fact that a v6 database
upgrades without touching its existing rows.

Ad-hoc engines here inherit nothing from `db.py`, so the local helper installs
the same connect listener. That helper is itself asserted to report
`foreign_keys == 1`: otherwise a helper regression would silently neuter every
cascade test.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

import migrations
from migrations import MIGRATIONS, applied_migrations, run_migrations

STAMP = "2026-01-01T00:00:00.000000+00:00"

PROJECT_COLUMNS = {
    "id",
    "name",
    "description",
    "creator",
    "source_url",
    "licence",
    "licence_url",
    "origin",
    "cover_asset_id",
    "owner_id",
    "metadata_json",
    "created_at",
    "updated_at",
}

PROJECT_ASSET_COLUMNS = {
    "project_id",
    "asset_id",
    "role",
    "position",
    "added_at",
}

NEW_TABLES = {"project", "project_asset"}

NEW_INDEXES = {"idx_project_name_unique", "idx_project_asset_asset_id"}

SHIPPED_LEDGER = {
    1: "initial_schema",
    2: "nested_folders_and_mount_sources",
    3: "asset_metadata_and_bundles",
    4: "folder_identity_and_reference_flags",
    5: "users_and_sessions",
    6: "audit_log",
}


@pytest.fixture(autouse=True)
def temp_storage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every migration run at a throwaway storage root (004 reads it)."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    monkeypatch.setattr(migrations, "_storage_root", lambda: storage_root)
    return storage_root


def sqlite_engine(path: Path) -> Engine:
    """Ad-hoc engine with the API's FK enforcement (db.py's listener is not used)."""
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    return engine


def make_v6_engine(path: Path) -> Engine:
    engine = sqlite_engine(path)
    assert run_migrations(engine, MIGRATIONS[:6]) == 6
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


def foreign_keys(database_engine: Engine, table: str) -> set[tuple[str, str, str]]:
    with database_engine.connect() as conn:
        rows = conn.exec_driver_sql(f"PRAGMA foreign_key_list({table})").fetchall()
    return {(str(row[2]), str(row[3]), str(row[6])) for row in rows}


def insert_asset(conn: Connection, asset_id: str) -> None:
    conn.exec_driver_sql(
        "INSERT INTO asset(id, filename, mime, size, name, storage_path) "
        "VALUES (?, 'model.stl', 'model/stl', 1, ?, ?)",
        (asset_id, asset_id, f"{asset_id}/model.stl"),
    )


def insert_asset_file(conn: Connection, file_id: str, asset_id: str) -> None:
    conn.exec_driver_sql(
        "INSERT INTO assetfile(id, asset_id, filename, mime, size, role, storage_path) "
        "VALUES (?, ?, 'model.stl', 'model/stl', 1, 'supporting', ?)",
        (file_id, asset_id, f"bundles/{asset_id}/{file_id}/model.stl"),
    )


def insert_project(conn: Connection, project_id: str, name: str, cover_asset_id: str | None = None) -> None:
    conn.exec_driver_sql(
        "INSERT INTO project(id, name, cover_asset_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (project_id, name, cover_asset_id, STAMP, STAMP),
    )


def insert_membership(conn: Connection, project_id: str, asset_id: str, role: str = "member") -> None:
    conn.exec_driver_sql(
        "INSERT INTO project_asset(project_id, asset_id, role, position, added_at) VALUES (?, ?, ?, 0, ?)",
        (project_id, asset_id, role, STAMP),
    )


def row_count(database_engine: Engine, table: str) -> int:
    with database_engine.connect() as conn:
        return int(conn.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar_one())


def test_helper_engine_enforces_foreign_keys(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "pragma.db")
    with database_engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_fresh_database_reaches_v7(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "fresh.db")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    assert MIGRATIONS[-1].version == 7
    assert MIGRATIONS[-1].name == "projects"
    ledger = applied_migrations(database_engine)
    assert ledger == {**SHIPPED_LEDGER, 7: "projects"}
    assert table_columns(database_engine, "project") == PROJECT_COLUMNS
    assert table_columns(database_engine, "project_asset") == PROJECT_ASSET_COLUMNS
    assert NEW_TABLES.issubset(object_names(database_engine, "table"))
    assert NEW_INDEXES.issubset(object_names(database_engine, "index"))
    assert foreign_keys(database_engine, "project_asset") == {
        ("asset", "asset_id", "CASCADE"),
        ("project", "project_id", "CASCADE"),
    }
    assert foreign_keys(database_engine, "project") == {
        ("asset", "cover_asset_id", "SET NULL"),
        ("users", "owner_id", "SET NULL"),
    }


def test_v6_database_upgrades_and_keeps_existing_rows(tmp_path: Path) -> None:
    database_engine = make_v6_engine(tmp_path / "upgrade.db")
    with database_engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO users(id, username, created_at, updated_at) "
            "VALUES ('u-1', 'alice', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
        conn.exec_driver_sql(
            "INSERT INTO sessions(id, user_id, username, refresh_token_hash, created_at, last_used_at, "
            "access_expires_at, refresh_expires_at) VALUES ('s-1', 'u-1', 'alice', 'hash-1', 0, 0, 0, 0)"
        )
        insert_asset(conn, "a-1")
        insert_asset_file(conn, "f-1", "a-1")
    with database_engine.connect() as conn:
        assets_before = tuple(conn.exec_driver_sql("SELECT * FROM asset ORDER BY id").fetchall())
        files_before = tuple(conn.exec_driver_sql("SELECT * FROM assetfile ORDER BY id").fetchall())
        users_before = tuple(conn.exec_driver_sql("SELECT * FROM users ORDER BY id").fetchall())

    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    with database_engine.connect() as conn:
        assert tuple(conn.exec_driver_sql("SELECT * FROM asset ORDER BY id").fetchall()) == assets_before
        assert tuple(conn.exec_driver_sql("SELECT * FROM assetfile ORDER BY id").fetchall()) == files_before
        assert tuple(conn.exec_driver_sql("SELECT * FROM users ORDER BY id").fetchall()) == users_before
    assert row_count(database_engine, "project") == 0
    assert row_count(database_engine, "project_asset") == 0


def test_migration_007_is_idempotent(tmp_path: Path) -> None:
    database_engine = make_v6_engine(tmp_path / "idempotent.db")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    with database_engine.begin() as conn:
        insert_asset(conn, "a-1")
        insert_project(conn, "p-1", "PLA parts")
        insert_membership(conn, "p-1", "a-1")
    with database_engine.connect() as conn:
        projects_before = tuple(conn.exec_driver_sql("SELECT * FROM project ORDER BY id").fetchall())
        memberships_before = tuple(conn.exec_driver_sql("SELECT * FROM project_asset").fetchall())

    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    migration = next(migration for migration in MIGRATIONS if migration.version == 7)
    with database_engine.begin() as conn:
        migration.apply(conn)

    with database_engine.connect() as conn:
        assert tuple(conn.exec_driver_sql("SELECT * FROM project ORDER BY id").fetchall()) == projects_before
        assert tuple(conn.exec_driver_sql("SELECT * FROM project_asset").fetchall()) == memberships_before
    assert NEW_INDEXES.issubset(object_names(database_engine, "index"))


def test_deleting_an_asset_cascades_its_memberships(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "asset-cascade.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    with database_engine.begin() as conn:
        insert_asset(conn, "a-1")
        insert_asset(conn, "a-2")
        insert_project(conn, "p-1", "PLA parts")
        insert_membership(conn, "p-1", "a-1")
        insert_membership(conn, "p-1", "a-2")

    with database_engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM asset WHERE id = 'a-1'")

    with database_engine.connect() as conn:
        remaining = conn.exec_driver_sql(
            "SELECT project_id, asset_id FROM project_asset ORDER BY asset_id"
        ).fetchall()
    assert remaining == [("p-1", "a-2")]
    assert row_count(database_engine, "project") == 1


def test_deleting_a_project_keeps_assets_and_files(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "project-cascade.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    storage_root = migrations._storage_root()
    planted = storage_root / "bundles" / "a-1" / "f-1" / "model.stl"
    planted.parent.mkdir(parents=True)
    planted.write_bytes(b"solid cube\nendsolid cube\n")
    with database_engine.begin() as conn:
        insert_asset(conn, "a-1")
        insert_asset_file(conn, "f-1", "a-1")
        insert_project(conn, "p-1", "PLA parts")
        insert_membership(conn, "p-1", "a-1")

    with database_engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM project WHERE id = 'p-1'")

    assert row_count(database_engine, "project_asset") == 0
    assert row_count(database_engine, "project") == 0
    assert row_count(database_engine, "asset") == 1
    assert row_count(database_engine, "assetfile") == 1
    assert planted.exists()
    assert planted.read_bytes() == b"solid cube\nendsolid cube\n"


def test_deleting_the_cover_asset_nulls_the_cover(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "cover.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    with database_engine.begin() as conn:
        insert_asset(conn, "a-1")
        insert_project(conn, "p-1", "PLA parts", cover_asset_id="a-1")

    with database_engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM asset WHERE id = 'a-1'")

    with database_engine.connect() as conn:
        rows = conn.exec_driver_sql("SELECT id, cover_asset_id FROM project ORDER BY id").fetchall()
    assert rows == [("p-1", None)]


def test_project_name_uniqueness_is_case_insensitive(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "name-unique.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    with database_engine.begin() as conn:
        insert_project(conn, "p-1", "PLA")

    with pytest.raises(IntegrityError):
        with database_engine.begin() as conn:
            insert_project(conn, "p-2", "pla")


def test_closed_check_lists_reject_unknown_values(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "checks.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    with database_engine.begin() as conn:
        insert_asset(conn, "a-1")
        insert_project(conn, "p-1", "PLA parts")

    with pytest.raises(IntegrityError):
        with database_engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO project(id, name, origin, created_at, updated_at) "
                "VALUES ('p-bad', 'PLA parts 2', 'scraped', ?, ?)",
                (STAMP, STAMP),
            )

    with pytest.raises(IntegrityError):
        with database_engine.begin() as conn:
            insert_membership(conn, "p-1", "a-1", role="cover")


def test_membership_primary_key_rejects_a_duplicate(tmp_path: Path) -> None:
    """The (project_id, asset_id) PK is what makes adding an asset twice idempotent."""
    database_engine = sqlite_engine(tmp_path / "membership-pk.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    with database_engine.begin() as conn:
        insert_asset(conn, "a-1")
        insert_project(conn, "p-1", "PLA parts")
        insert_membership(conn, "p-1", "a-1")

    with pytest.raises(IntegrityError):
        with database_engine.begin() as conn:
            insert_membership(conn, "p-1", "a-1")


def test_defaults_match_the_ddl(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "defaults.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    with database_engine.begin() as conn:
        insert_asset(conn, "a-1")
        conn.exec_driver_sql(
            "INSERT INTO project(id, name, created_at, updated_at) VALUES ('p-1', 'PLA parts', ?, ?)",
            (STAMP, STAMP),
        )
        conn.exec_driver_sql(
            "INSERT INTO project_asset(project_id, asset_id, added_at) VALUES ('p-1', 'a-1', ?)",
            (STAMP,),
        )

    with database_engine.connect() as conn:
        project = conn.exec_driver_sql(
            "SELECT origin, metadata_json, cover_asset_id, owner_id FROM project WHERE id = 'p-1'"
        ).fetchone()
        membership = conn.exec_driver_sql(
            "SELECT role, position FROM project_asset WHERE project_id = 'p-1'"
        ).fetchone()
    assert tuple(project) == ("own", "{}", None, None)
    assert tuple(membership) == ("member", 0)


def test_migration_007_sweeps_orphaned_assetfile_rows(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database_engine = make_v6_engine(tmp_path / "orphans.db")
    with database_engine.begin() as conn:
        insert_asset(conn, "a-1")
        insert_asset_file(conn, "f-1", "a-1")

    # Manufacture the pre-007 defect: FK enforcement does not exist yet, so a
    # raw connection can drop the parent and leave the assetfile row behind.
    raw = database_engine.raw_connection()
    try:
        cursor = raw.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        assert cursor.execute("PRAGMA foreign_keys").fetchone()[0] == 0
        cursor.execute("DELETE FROM asset WHERE id = 'a-1'")
        raw.commit()
    finally:
        raw.close()

    with database_engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM assetfile").scalar_one() == 1

    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    with database_engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM assetfile").scalar_one() == 0
    assert "[migration-007] removed 1 orphaned assetfile row(s)" in capsys.readouterr().out
