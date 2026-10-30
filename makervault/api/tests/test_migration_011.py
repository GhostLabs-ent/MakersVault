"""Migration 011 adds one generation of refresh-rotation history.

011 is DB-only and append-only: two nullable columns on `sessions` and one
non-unique index. Only a hash is ever stored, so the tests here pin the ledger,
the documented column set, and the two properties a later change could quietly
break: the index is not unique (a superseded hash may legitimately repeat in
history) and re-applying 011 preserves a row that already carries one.

Later migrations may be appended, so the version and ledger assertions scope
themselves the way `test_migration_010.py` does.
"""

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection, Engine

from migrations import MIGRATIONS, applied_migrations, run_migrations

SESSIONS_TABLE = "sessions"
ROTATION_INDEX = "idx_sessions_previous_refresh_token_hash"
# Migration 005 created these thirteen columns; 011 adds two and 012 adds
# `mfa_verified_at`.
SHIPPED_SESSION_COLUMNS = {
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
ADDED_SESSION_COLUMNS = {"previous_refresh_token_hash", "rotated_at", "mfa_verified_at"}

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
}


def sqlite_engine(path: Path) -> Engine:
    database_engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(database_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        # Same per-connection pragma the API engine installs in `db.py`.
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return database_engine


def make_v10_engine(path: Path) -> Engine:
    database_engine = sqlite_engine(path)
    assert run_migrations(database_engine, MIGRATIONS[:10]) == 10
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


def insert_user(conn: Connection, user_id: str, username: str) -> None:
    conn.exec_driver_sql(
        "INSERT INTO users(id, username, created_at, updated_at) "
        "VALUES (?, ?, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
        (user_id, username),
    )


def insert_session(
    conn: Connection,
    session_id: str,
    *,
    user_id: str | None,
    refresh_hash: str,
    previous_hash: str | None = None,
) -> None:
    columns = (
        "id, user_id, username, kind, refresh_token_hash, device, user_agent, "
        "client_ip, created_at, last_used_at, access_expires_at, refresh_expires_at, revoked_at"
    )
    values: tuple = (
        session_id,
        user_id,
        "alice",
        "password",
        refresh_hash,
        None,
        None,
        None,
        1,
        1,
        2,
        3,
        None,
    )
    if previous_hash is not None:
        columns = f"{columns}, previous_refresh_token_hash"
        values = (*values, previous_hash)
    placeholders = ", ".join("?" for _ in values)
    conn.exec_driver_sql(f"INSERT INTO sessions({columns}) VALUES ({placeholders})", values)


def test_fresh_database_reaches_v11(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "fresh.db")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    migration = next(migration for migration in MIGRATIONS if migration.version == 11)
    assert migration.name == "session_rotation_history"
    ledger = applied_migrations(database_engine)
    assert {version: ledger[version] for version in SHIPPED_LEDGER} == SHIPPED_LEDGER
    assert ledger[11] == "session_rotation_history"
    assert ADDED_SESSION_COLUMNS <= table_columns(database_engine, SESSIONS_TABLE)


def test_the_sessions_table_keeps_its_shipped_columns_and_gains_two(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "columns.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    assert table_columns(database_engine, SESSIONS_TABLE) == SHIPPED_SESSION_COLUMNS | ADDED_SESSION_COLUMNS


def test_the_previous_hash_index_exists_and_is_not_unique(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "index.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    with database_engine.connect() as conn:
        index_sql = conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?", (ROTATION_INDEX,)
        ).scalar_one()
        index_list = conn.exec_driver_sql(f"PRAGMA index_list({SESSIONS_TABLE})").fetchall()
        index_info = conn.exec_driver_sql(f"PRAGMA index_info({ROTATION_INDEX})").fetchall()

    entry = next(row for row in index_list if str(row[1]) == ROTATION_INDEX)
    assert int(entry[2]) == 0, "the previous-hash index must not be UNIQUE"
    assert [str(row[2]) for row in index_info] == ["previous_refresh_token_hash"]
    assert "UNIQUE" not in str(index_sql).upper()


def test_reapplying_011_is_harmless_and_preserves_a_previous_hash(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "idempotent.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    with database_engine.begin() as conn:
        insert_user(conn, "u-1", "alice")
        insert_session(
            conn,
            "s-1",
            user_id="u-1",
            refresh_hash="current-hash",
            previous_hash="previous-hash",
        )

    migration = next(migration for migration in MIGRATIONS if migration.version == 11)
    with database_engine.begin() as conn:
        migration.apply(conn)
    with database_engine.begin() as conn:
        migration.apply(conn)

    assert ROTATION_INDEX in object_names(database_engine, "index")
    with database_engine.connect() as conn:
        stored = conn.exec_driver_sql(
            "SELECT COUNT(*), MAX(previous_refresh_token_hash) FROM sessions"
        ).one()
    assert stored == (1, "previous-hash")


def test_upgrading_a_v10_database_keeps_its_session_rows(tmp_path: Path) -> None:
    database_engine = make_v10_engine(tmp_path / "upgrade.db")
    with database_engine.begin() as conn:
        insert_user(conn, "u-1", "alice")
        insert_session(conn, "s-1", user_id="u-1", refresh_hash="current-hash")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    with database_engine.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT id, refresh_token_hash, previous_refresh_token_hash, rotated_at FROM sessions"
        ).one()
    assert row[0] == "s-1"
    assert row[1] == "current-hash"
    assert row[2] is None
    assert row[3] is None
