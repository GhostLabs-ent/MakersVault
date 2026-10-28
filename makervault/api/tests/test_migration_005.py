"""Migration 005 adds the users and sessions tables.

005 is DB-only (no backfill, no filesystem), so these tests pin the schema, the
ledger entry, and the fact that a v4 database keeps every existing row.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

import migrations
from migrations import MIGRATIONS, applied_migrations, run_migrations

LEDGER = {
    1: "initial_schema",
    2: "nested_folders_and_mount_sources",
    3: "asset_metadata_and_bundles",
    4: "folder_identity_and_reference_flags",
    5: "users_and_sessions",
}

USERS_COLUMNS = {
    "id",
    "username",
    "email",
    "password_hash",
    "role",
    "disabled",
    "created_at",
    "updated_at",
}

SESSIONS_COLUMNS = {
    "id",
    "user_id",
    "username",
    "kind",
    "refresh_token_hash",
    "device",
    "user_agent",
    "client_ip",
    "created_at",
    "last_used_at",
    "access_expires_at",
    "refresh_expires_at",
    "revoked_at",
}

NEW_INDEXES = {
    "idx_users_username_unique",
    "idx_users_email_unique",
    "idx_sessions_refresh_hash_unique",
    "idx_sessions_user_id",
    "idx_sessions_refresh_expires_at",
}


@pytest.fixture(autouse=True)
def temp_storage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every migration run at a throwaway storage root (004 reads it)."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    monkeypatch.setattr(migrations, "_storage_root", lambda: storage_root)
    return storage_root


def sqlite_engine(path: Path) -> Engine:
    return create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})


def make_v4_engine(path: Path) -> Engine:
    engine = sqlite_engine(path)
    assert run_migrations(engine, MIGRATIONS[:4]) == 4
    return engine


def insert_folder(conn: Connection, folder_id: str, name: str) -> None:
    conn.exec_driver_sql(
        "INSERT INTO folder(id, name, tags_json, parent_id, storage_path) VALUES (?, ?, '[]', NULL, ?)",
        (folder_id, name, name),
    )


def insert_asset(conn: Connection, asset_id: str) -> None:
    conn.exec_driver_sql(
        "INSERT INTO asset(id, filename, mime, size, tags_json, name, storage_path) "
        "VALUES (?, 'model.stl', 'model/stl', 10, '[]', ?, ?)",
        (asset_id, asset_id, f"{asset_id}/model.stl"),
    )


def insert_user(conn: Connection, user_id: str, username: str, email: str | None = None) -> None:
    conn.exec_driver_sql(
        "INSERT INTO users(id, username, email, created_at, updated_at) VALUES (?, ?, ?, '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00')",
        (user_id, username, email),
    )


def insert_session(conn: Connection, session_id: str, refresh_hash: str, user_id: str | None = None) -> None:
    conn.exec_driver_sql(
        "INSERT INTO sessions(id, user_id, username, refresh_token_hash, created_at, last_used_at, "
        "access_expires_at, refresh_expires_at) VALUES (?, ?, 'someone', ?, 0, 0, 0, 0)",
        (session_id, user_id, refresh_hash),
    )


def table_columns(database_engine: Engine, table: str) -> dict[str, str]:
    with database_engine.connect() as conn:
        rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]): "" if row[4] is None else str(row[4]) for row in rows}


def index_names(database_engine: Engine) -> set[str]:
    with database_engine.connect() as conn:
        rows = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    return {str(row[0]) for row in rows}


def table_snapshot(database_engine: Engine, *tables: str) -> tuple[tuple[str, tuple], ...]:
    with database_engine.connect() as conn:
        return tuple(
            (table, tuple(conn.exec_driver_sql(f"SELECT * FROM {table} ORDER BY id").fetchall())) for table in tables
        )


def test_fresh_database_reaches_v5(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "fresh.db")

    assert run_migrations(database_engine) == 5

    assert applied_migrations(database_engine) == LEDGER
    assert set(table_columns(database_engine, "users")) == USERS_COLUMNS
    assert set(table_columns(database_engine, "sessions")) == SESSIONS_COLUMNS
    assert NEW_INDEXES.issubset(index_names(database_engine))


def test_users_defaults_are_least_privilege(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "defaults.db")
    assert run_migrations(database_engine) == 5

    users = table_columns(database_engine, "users")
    assert users["role"] == "'viewer'"
    assert users["disabled"] == "0"

    with database_engine.begin() as conn:
        insert_user(conn, "u-1", "alice")
        row = conn.exec_driver_sql("SELECT role, disabled, email, password_hash FROM users WHERE id = 'u-1'").fetchone()
    assert tuple(row) == ("viewer", 0, None, None)


def test_v4_database_upgrades_and_keeps_existing_rows(tmp_path: Path) -> None:
    database_engine = make_v4_engine(tmp_path / "upgrade.db")
    with database_engine.begin() as conn:
        insert_folder(conn, "f-parts", "Parts")
        insert_folder(conn, "f-prints", "Prints")
        insert_asset(conn, "a-cube")
        insert_asset(conn, "a-sphere")
    before = table_snapshot(database_engine, "folder", "asset")

    assert run_migrations(database_engine) == 5

    assert table_snapshot(database_engine, "folder", "asset") == before
    assert applied_migrations(database_engine) == LEDGER


def test_migration_005_is_idempotent(tmp_path: Path) -> None:
    database_engine = make_v4_engine(tmp_path / "idempotent.db")
    with database_engine.begin() as conn:
        insert_folder(conn, "f-parts", "Parts")
        insert_asset(conn, "a-cube")

    assert run_migrations(database_engine) == 5
    before = table_snapshot(database_engine, "folder", "asset", "users", "sessions")

    assert run_migrations(database_engine) == 5
    assert table_snapshot(database_engine, "folder", "asset", "users", "sessions") == before
    assert applied_migrations(database_engine) == LEDGER

    migration = next(migration for migration in MIGRATIONS if migration.version == 5)
    with database_engine.begin() as conn:
        migration.apply(conn)

    assert table_snapshot(database_engine, "folder", "asset", "users", "sessions") == before


def test_usernames_and_emails_are_unique_case_insensitively(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "unique.db")
    assert run_migrations(database_engine) == 5

    with database_engine.begin() as conn:
        insert_user(conn, "u-1", "alice", "Alice@Example.com")

    with pytest.raises(IntegrityError):
        with database_engine.begin() as conn:
            insert_user(conn, "u-2", "ALICE", "other@example.com")

    with pytest.raises(IntegrityError):
        with database_engine.begin() as conn:
            insert_user(conn, "u-3", "bob", "alice@example.COM")

    with database_engine.begin() as conn:
        insert_user(conn, "u-4", "bob", None)
        insert_user(conn, "u-5", "carol", None)
        emails = conn.exec_driver_sql("SELECT COUNT(*) FROM users WHERE email IS NULL").scalar_one()
    assert emails == 2


def test_break_glass_sessions_may_share_a_null_user(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "sessions.db")
    assert run_migrations(database_engine) == 5

    with database_engine.begin() as conn:
        insert_session(conn, "s-1", "hash-1")
        insert_session(conn, "s-2", "hash-2")

    with database_engine.begin() as conn:
        user_ids = conn.exec_driver_sql("SELECT user_id FROM sessions ORDER BY id").fetchall()
    assert [row[0] for row in user_ids] == [None, None]

    with pytest.raises(IntegrityError):
        with database_engine.begin() as conn:
            insert_session(conn, "s-3", "hash-1")
