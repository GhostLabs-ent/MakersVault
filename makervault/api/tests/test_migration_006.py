"""Migration 006 adds the append-only audit log.

006 is DB-only (new table, no backfill, no filesystem), so these tests pin the
schema, the ledger entry, the append-only triggers, and the fact that a v5
database upgrades without touching its existing rows.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

import migrations
from migrations import MIGRATIONS, applied_migrations, run_migrations

AUDIT_COLUMNS = {
    "id",
    "created_at",
    "actor",
    "actor_user_id",
    "actor_role",
    "actor_kind",
    "action",
    "target",
    "detail_json",
    "request_id",
    "method",
    "path",
}

NEW_INDEXES = {
    "idx_audit_events_created_at",
    "idx_audit_events_actor",
    "idx_audit_events_action",
}

NEW_TRIGGERS = {"audit_events_no_update", "audit_events_no_delete"}


@pytest.fixture(autouse=True)
def temp_storage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every migration run at a throwaway storage root (004 reads it)."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    monkeypatch.setattr(migrations, "_storage_root", lambda: storage_root)
    return storage_root


def sqlite_engine(path: Path) -> Engine:
    return create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})


def make_v5_engine(path: Path) -> Engine:
    engine = sqlite_engine(path)
    assert run_migrations(engine, MIGRATIONS[:5]) == 5
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


def insert_event(conn: Connection, event_id: str) -> None:
    conn.exec_driver_sql(
        "INSERT INTO audit_events(id, created_at, actor, actor_role, actor_kind, action, target, "
        "detail_json, request_id, method, path) VALUES (?, '2026-01-01T00:00:00.000000+00:00', "
        "'root', 'admin', 'password', 'asset.delete', 'asset-1', NULL, 'req-1', 'DELETE', '/asset/asset-1')",
        (event_id,),
    )


def test_fresh_database_reaches_v6(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "fresh.db")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    assert MIGRATIONS[-1].version == 6
    assert MIGRATIONS[-1].name == "audit_log"
    assert applied_migrations(database_engine)[6] == "audit_log"
    assert table_columns(database_engine, "audit_events") == AUDIT_COLUMNS
    assert NEW_INDEXES.issubset(object_names(database_engine, "index"))
    assert NEW_TRIGGERS.issubset(object_names(database_engine, "trigger"))


def test_v5_database_upgrades_and_keeps_existing_rows(tmp_path: Path) -> None:
    database_engine = make_v5_engine(tmp_path / "upgrade.db")
    with database_engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO users(id, username, created_at, updated_at) "
            "VALUES ('u-1', 'alice', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
        conn.exec_driver_sql(
            "INSERT INTO sessions(id, user_id, username, refresh_token_hash, created_at, last_used_at, "
            "access_expires_at, refresh_expires_at) VALUES ('s-1', 'u-1', 'alice', 'hash-1', 0, 0, 0, 0)"
        )
    with database_engine.connect() as conn:
        users_before = tuple(conn.exec_driver_sql("SELECT * FROM users ORDER BY id").fetchall())
        sessions_before = tuple(conn.exec_driver_sql("SELECT * FROM sessions ORDER BY id").fetchall())

    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    with database_engine.connect() as conn:
        assert tuple(conn.exec_driver_sql("SELECT * FROM users ORDER BY id").fetchall()) == users_before
        assert tuple(conn.exec_driver_sql("SELECT * FROM sessions ORDER BY id").fetchall()) == sessions_before
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM audit_events").scalar_one() == 0


def test_migration_006_is_idempotent(tmp_path: Path) -> None:
    database_engine = make_v5_engine(tmp_path / "idempotent.db")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    with database_engine.begin() as conn:
        insert_event(conn, "e-1")
    with database_engine.connect() as conn:
        before = tuple(conn.exec_driver_sql("SELECT * FROM audit_events ORDER BY id").fetchall())

    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    migration = next(migration for migration in MIGRATIONS if migration.version == 6)
    with database_engine.begin() as conn:
        migration.apply(conn)

    with database_engine.connect() as conn:
        assert tuple(conn.exec_driver_sql("SELECT * FROM audit_events ORDER BY id").fetchall()) == before
    assert NEW_TRIGGERS.issubset(object_names(database_engine, "trigger"))


def test_audit_events_are_append_only(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "append-only.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    with database_engine.begin() as conn:
        insert_event(conn, "e-1")

    with pytest.raises(IntegrityError):
        with database_engine.begin() as conn:
            conn.exec_driver_sql("UPDATE audit_events SET actor = 'mallory' WHERE id = 'e-1'")

    with pytest.raises(IntegrityError):
        with database_engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM audit_events WHERE id = 'e-1'")

    with database_engine.connect() as conn:
        row = conn.exec_driver_sql("SELECT actor FROM audit_events WHERE id = 'e-1'").fetchone()
    assert row[0] == "root"
