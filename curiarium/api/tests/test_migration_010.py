"""Migration 010 binds an external identity to a local account.

010 is DB-only: one table and two indexes, with `(issuer, subject)` unique. That
pair is the provider's immutable principal id and the only binding key, so the
tests here pin three things a later change could quietly break: the ledger, the
documented columns, and the uniqueness/foreign-key refusals. The table is
created with `IF NOT EXISTS`, so re-applying 010 (or opening a v10 database with
an older build that runs the migration by hand) must be harmless.

Later migrations may be appended, so the version and ledger assertions scope
themselves the way `test_migration_005.py` and `test_migration_009.py` do.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from migrations import MIGRATIONS, applied_migrations, run_migrations

IDENTITY_TABLE = "oidc_identities"
IDENTITY_INDEX = "idx_oidc_identities_issuer_subject_unique"
USER_INDEX = "idx_oidc_identities_user_id"
IDENTITY_COLUMNS = {"id", "issuer", "subject", "user_id", "created_at"}

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
}


def sqlite_engine(path: Path) -> Engine:
    database_engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(database_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        # Same per-connection pragma the API engine installs in `db.py`; the
        # missing-user refusal below is only meaningful with it on.
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return database_engine


def make_v9_engine(path: Path) -> Engine:
    database_engine = sqlite_engine(path)
    assert run_migrations(database_engine, MIGRATIONS[:9]) == 9
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


def insert_identity(
    conn: Connection,
    identity_id: str,
    *,
    issuer: str,
    subject: str,
    user_id: str,
) -> None:
    conn.exec_driver_sql(
        "INSERT INTO oidc_identities(id, issuer, subject, user_id, created_at) "
        "VALUES (?, ?, ?, ?, '2026-01-01T00:00:00+00:00')",
        (identity_id, issuer, subject, user_id),
    )


def test_fresh_database_reaches_v10(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "fresh.db")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    migration = next(migration for migration in MIGRATIONS if migration.version == 10)
    assert migration.name == "oidc_identities"
    ledger = applied_migrations(database_engine)
    assert {version: ledger[version] for version in SHIPPED_LEDGER} == SHIPPED_LEDGER
    assert ledger[10] == "oidc_identities"
    assert IDENTITY_TABLE in object_names(database_engine, "table")
    assert {IDENTITY_INDEX, USER_INDEX}.issubset(object_names(database_engine, "index"))


def test_the_table_has_the_documented_columns(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "columns.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    assert table_columns(database_engine, IDENTITY_TABLE) == IDENTITY_COLUMNS


def test_the_unique_index_on_issuer_and_subject_exists(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "index.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    with database_engine.connect() as conn:
        index_sql = conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?", (IDENTITY_INDEX,)
        ).scalar_one()
        index_list = conn.exec_driver_sql(f"PRAGMA index_list({IDENTITY_TABLE})").fetchall()
        index_info = conn.exec_driver_sql(f"PRAGMA index_info({IDENTITY_INDEX})").fetchall()

    entry = next(row for row in index_list if str(row[1]) == IDENTITY_INDEX)
    assert int(entry[2]) == 1, "the (issuer, subject) index must be UNIQUE"
    assert [str(row[2]) for row in index_info] == ["issuer", "subject"]
    assert "UNIQUE" in str(index_sql).upper()


def test_reapplying_010_is_harmless(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "idempotent.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    with database_engine.begin() as conn:
        insert_user(conn, "u-1", "alice")
        insert_identity(conn, "i-1", issuer="https://idp.example.com", subject="s-1", user_id="u-1")

    migration = next(migration for migration in MIGRATIONS if migration.version == 10)
    with database_engine.begin() as conn:
        migration.apply(conn)
    with database_engine.begin() as conn:
        migration.apply(conn)

    assert IDENTITY_INDEX in object_names(database_engine, "index")
    with database_engine.connect() as conn:
        assert conn.exec_driver_sql(f"SELECT COUNT(*) FROM {IDENTITY_TABLE}").scalar_one() == 1


def test_two_identities_for_one_principal_are_refused(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "duplicate.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    with database_engine.begin() as conn:
        insert_user(conn, "u-1", "alice")
        insert_identity(conn, "i-1", issuer="https://idp.example.com", subject="s-1", user_id="u-1")

    with pytest.raises(IntegrityError):
        with database_engine.begin() as conn:
            insert_identity(
                conn, "i-2", issuer="https://idp.example.com", subject="s-1", user_id="u-1"
            )


def test_the_same_subject_at_two_issuers_is_allowed(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "two-issuers.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    with database_engine.begin() as conn:
        insert_user(conn, "u-1", "alice")
        insert_identity(conn, "i-1", issuer="https://idp-one.example.com", subject="s-1", user_id="u-1")
        insert_identity(conn, "i-2", issuer="https://idp-two.example.com", subject="s-1", user_id="u-1")
        count = conn.exec_driver_sql(f"SELECT COUNT(*) FROM {IDENTITY_TABLE}").scalar_one()

    # The pair, not the subject, is the key: a subject is only unique per issuer.
    assert count == 2


def test_an_identity_cannot_reference_a_missing_user(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "missing-user.db")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    with pytest.raises(IntegrityError):
        with database_engine.begin() as conn:
            insert_identity(
                conn, "i-1", issuer="https://idp.example.com", subject="s-1", user_id="does-not-exist"
            )
