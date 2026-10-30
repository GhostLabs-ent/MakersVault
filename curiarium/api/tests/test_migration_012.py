"""Migration 012 adds the TOTP enrolment state and the recovery-code table.

012 is DB-only and append-only: three nullable columns on `users`, one on
`sessions`, one new table and its two indexes. Only ciphertext (a seed) and a
peppered HMAC (a recovery code) are ever stored, so the tests here pin the shape
of that storage and the two properties a later change could quietly break:

* re-applying 012 is harmless - `_add_column` guards on `PRAGMA table_info` and
  the table and indexes are `IF NOT EXISTS` - and it preserves a row that is
  already enrolled;
* a v11 database upgrades to 12 without touching the rows it already had.

Later migrations may be appended, so the version and ledger assertions scope
themselves the way `test_migration_011.py` does.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from migrations import MIGRATIONS, applied_migrations, run_migrations

VERSION = 12
NAME = "mfa_totp"

USERS_TABLE = "users"
SESSIONS_TABLE = "sessions"
RECOVERY_TABLE = "mfa_recovery_codes"
RECOVERY_UNIQUE_INDEX = "idx_mfa_recovery_codes_user_hmac"
RECOVERY_USER_INDEX = "idx_mfa_recovery_codes_user_id"

# What 012 appends. Everything before it is pinned by the migrations that shipped
# it, so these sets only name the new columns.
ADDED_USER_COLUMNS = {"totp_secret", "totp_enrolled_at", "totp_last_step"}
ADDED_SESSION_COLUMNS = {"mfa_verified_at"}
RECOVERY_COLUMNS = {"id", "user_id", "code_hmac", "created_at", "used_at"}

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
}

# The columns a v11 database had. `SELECT *` would compare one column against two
# and fail on an unchanged row, so "the existing rows are kept" is asserted over
# exactly these.
USERS_V11_COLUMNS_SELECT = (
    "SELECT id, username, email, password_hash, role, disabled, created_at, updated_at FROM users ORDER BY id"
)
SESSIONS_V11_COLUMNS_SELECT = (
    "SELECT id, user_id, username, kind, refresh_token_hash, device, user_agent, client_ip, "
    "created_at, last_used_at, access_expires_at, refresh_expires_at, revoked_at, "
    "previous_refresh_token_hash, rotated_at FROM sessions ORDER BY id"
)


def sqlite_engine(path: Path) -> Engine:
    database_engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(database_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        # Same per-connection pragma the API engine installs in `db.py`.
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return database_engine


def make_v11_engine(path: Path) -> Engine:
    database_engine = sqlite_engine(path)
    assert run_migrations(database_engine, MIGRATIONS[:11]) == 11
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


def index_is_unique(database_engine: Engine, name: str) -> bool:
    with database_engine.connect() as conn:
        rows = conn.exec_driver_sql(f"PRAGMA index_list({RECOVERY_TABLE})").fetchall()
    entry = next(row for row in rows if str(row[1]) == name)
    return int(entry[2]) == 1


def index_columns(database_engine: Engine, name: str) -> list[str]:
    with database_engine.connect() as conn:
        rows = conn.exec_driver_sql(f"PRAGMA index_info({name})").fetchall()
    return [str(row[2]) for row in rows]


def migration_012():
    return next(migration for migration in MIGRATIONS if migration.version == VERSION)


def insert_user(conn: Connection, user_id: str, username: str) -> None:
    conn.exec_driver_sql(
        "INSERT INTO users(id, username, created_at, updated_at) "
        "VALUES (?, ?, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
        (user_id, username),
    )


def insert_session(conn: Connection, session_id: str, *, user_id: str, refresh_hash: str) -> None:
    conn.exec_driver_sql(
        "INSERT INTO sessions(id, user_id, username, kind, refresh_token_hash, created_at, last_used_at, "
        "access_expires_at, refresh_expires_at) VALUES (?, ?, 'alice', 'password', ?, 1, 1, 2, 3)",
        (session_id, user_id, refresh_hash),
    )


def insert_recovery_code(conn: Connection, code_id: str, user_id: str, code_hmac: str) -> None:
    conn.exec_driver_sql(
        "INSERT INTO mfa_recovery_codes(id, user_id, code_hmac, created_at) VALUES (?, ?, ?, ?)",
        (code_id, user_id, code_hmac, "2026-01-01T00:00:00+00:00"),
    )


def test_fresh_database_reaches_v12(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "fresh.db")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    migration = migration_012()
    assert migration.name == NAME
    assert MIGRATIONS[-1].version == VERSION
    ledger = applied_migrations(database_engine)
    assert {version: ledger[version] for version in SHIPPED_LEDGER} == SHIPPED_LEDGER
    assert ledger[VERSION] == NAME


def test_the_enrolment_columns_exist_on_a_fresh_database(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "columns.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    assert ADDED_USER_COLUMNS <= table_columns(database_engine, USERS_TABLE)
    assert ADDED_SESSION_COLUMNS <= table_columns(database_engine, SESSIONS_TABLE)
    assert table_columns(database_engine, RECOVERY_TABLE) == RECOVERY_COLUMNS
    assert RECOVERY_TABLE in object_names(database_engine, "table")
    assert {RECOVERY_UNIQUE_INDEX, RECOVERY_USER_INDEX} <= object_names(database_engine, "index")


def test_a_recovery_code_is_unique_per_account_and_digest(tmp_path: Path) -> None:
    """The set must be a set, and the per-user lookup must still be an index."""
    database_engine = sqlite_engine(tmp_path / "indexes.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    assert index_is_unique(database_engine, RECOVERY_UNIQUE_INDEX) is True
    assert index_columns(database_engine, RECOVERY_UNIQUE_INDEX) == ["user_id", "code_hmac"]
    assert index_is_unique(database_engine, RECOVERY_USER_INDEX) is False
    assert index_columns(database_engine, RECOVERY_USER_INDEX) == ["user_id"]


def test_a_recovery_code_belongs_to_a_real_account(tmp_path: Path) -> None:
    """The foreign key is the reason truncating accounts must delete codes first."""
    database_engine = sqlite_engine(tmp_path / "foreign_key.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    with pytest.raises(IntegrityError):
        with database_engine.begin() as conn:
            insert_recovery_code(conn, "c-1", "no-such-user", "digest-1")

    with database_engine.begin() as conn:
        insert_user(conn, "u-1", "alice")
        insert_recovery_code(conn, "c-1", "u-1", "digest-1")
    with database_engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM mfa_recovery_codes").scalar_one() == 1


def test_one_account_cannot_store_the_same_digest_twice(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "duplicate.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    with database_engine.begin() as conn:
        insert_user(conn, "u-1", "alice")
        insert_user(conn, "u-2", "bob")
        insert_recovery_code(conn, "c-1", "u-1", "digest-1")
        # The same digest for a different account is legal: the pair is the key.
        insert_recovery_code(conn, "c-2", "u-2", "digest-1")

    with pytest.raises(IntegrityError):
        with database_engine.begin() as conn:
            insert_recovery_code(conn, "c-3", "u-1", "digest-1")


def test_reapplying_012_is_harmless_and_preserves_an_enrolment_that_exists(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "idempotent.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    with database_engine.begin() as conn:
        insert_user(conn, "u-1", "alice")
        conn.exec_driver_sql(
            "UPDATE users SET totp_secret = 'blob', totp_enrolled_at = '2026-01-01T00:00:00+00:00', "
            "totp_last_step = 4321 WHERE id = 'u-1'"
        )
        insert_recovery_code(conn, "c-1", "u-1", "digest-1")

    migration = migration_012()
    with database_engine.begin() as conn:
        migration.apply(conn)
    with database_engine.begin() as conn:
        migration.apply(conn)

    with database_engine.connect() as conn:
        stored = conn.exec_driver_sql(
            "SELECT totp_secret, totp_enrolled_at, totp_last_step FROM users WHERE id = 'u-1'"
        ).one()
        codes = conn.exec_driver_sql("SELECT COUNT(*) FROM mfa_recovery_codes").scalar_one()
    assert tuple(stored) == ("blob", "2026-01-01T00:00:00+00:00", 4321)
    assert codes == 1
    assert {RECOVERY_UNIQUE_INDEX, RECOVERY_USER_INDEX} <= object_names(database_engine, "index")


def test_upgrading_a_v11_database_keeps_its_rows(tmp_path: Path) -> None:
    database_engine = make_v11_engine(tmp_path / "upgrade.db")
    with database_engine.begin() as conn:
        insert_user(conn, "u-1", "alice")
        insert_session(conn, "s-1", user_id="u-1", refresh_hash="current-hash")
    with database_engine.connect() as conn:
        users_before = tuple(conn.exec_driver_sql(USERS_V11_COLUMNS_SELECT).fetchall())
        sessions_before = tuple(conn.exec_driver_sql(SESSIONS_V11_COLUMNS_SELECT).fetchall())

    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    with database_engine.connect() as conn:
        assert tuple(conn.exec_driver_sql(USERS_V11_COLUMNS_SELECT).fetchall()) == users_before
        assert tuple(conn.exec_driver_sql(SESSIONS_V11_COLUMNS_SELECT).fetchall()) == sessions_before
        # Not enrolled, so every new column is NULL - never a defaulted secret.
        assert conn.exec_driver_sql(
            "SELECT totp_secret, totp_enrolled_at, totp_last_step FROM users"
        ).one() == (None, None, None)
        assert conn.exec_driver_sql("SELECT mfa_verified_at FROM sessions").one() == (None,)
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM mfa_recovery_codes").scalar_one() == 0
