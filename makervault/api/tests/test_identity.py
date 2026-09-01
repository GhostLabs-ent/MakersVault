from pathlib import Path

from argon2 import PasswordHasher, Type
from sqlalchemy import create_engine

from identity_service import (
    ARGON2_HASH_PREFIX,
    PASSWORD_POLICY_VERSION,
    PasswordPolicyError,
    authenticate_initial_administrator,
    bootstrap_initial_administrator,
    normalize_username,
    validate_new_password,
)
from migrations import run_migrations


def sqlite_engine(path: Path):
    return create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )


def test_bootstrap_creates_one_hashed_persistent_administrator_and_is_idempotent(
    tmp_path: Path,
) -> None:
    database_engine = sqlite_engine(tmp_path / "identity.db")
    assert run_migrations(database_engine) == 13

    created = bootstrap_initial_administrator(
        database_engine,
        username="Admin",
        password="test-only-password",
    )
    repeated = bootstrap_initial_administrator(
        database_engine,
        username="Changed Environment Name",
        password="different-environment-password",
    )

    assert created.created is True
    assert repeated.created is False
    with database_engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT id, username, username_normalized, display_name, password_hash, "
            "enabled, password_policy_version, password_change_required, last_login_at "
            "FROM useraccount"
        ).mappings().all()
    assert len(rows) == 1
    user = rows[0]
    assert user["id"]
    assert user["username"] == "Admin"
    assert user["username_normalized"] == "admin"
    assert user["display_name"] == "Admin"
    assert user["password_hash"].startswith(ARGON2_HASH_PREFIX)
    assert "m=65536,t=3,p=1" in user["password_hash"]
    assert "test-only-password" not in user["password_hash"]
    assert user["enabled"] == 1
    assert user["password_policy_version"] == PASSWORD_POLICY_VERSION
    assert user["password_change_required"] == 0
    assert user["last_login_at"] is None

    authenticated = authenticate_initial_administrator(
        database_engine,
        username="admin",
        password="test-only-password",
    )
    assert authenticated is not None
    assert authenticated.id == user["id"]
    assert authenticate_initial_administrator(
        database_engine,
        username="Changed Environment Name",
        password="different-environment-password",
    ) is None


def test_successful_login_rehashes_an_older_argon2_parameter_set(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "rehash.db")
    run_migrations(database_engine)
    bootstrap_initial_administrator(
        database_engine,
        username="admin",
        password="test-only-password",
    )
    old_hash = PasswordHasher(
        time_cost=1,
        memory_cost=8 * 1024,
        parallelism=1,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    ).hash("test-only-password")
    with database_engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE useraccount SET password_hash = ?, password_policy_version = 1",
            (old_hash,),
        )

    assert authenticate_initial_administrator(
        database_engine,
        username="admin",
        password="test-only-password",
    ) is not None

    with database_engine.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT password_hash, last_login_at FROM useraccount"
        ).fetchone()
    assert row is not None
    assert row[0] != old_hash
    assert "m=65536,t=3,p=1" in row[0]
    assert row[1] is not None


def test_bootstrap_grandfathers_a_valid_legacy_password_without_lockout(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "legacy-password.db")
    run_migrations(database_engine)

    result = bootstrap_initial_administrator(
        database_engine,
        username="legacy-admin",
        password="twelve-chars",
    )

    assert result.created is True
    assert result.password_change_required is True
    assert authenticate_initial_administrator(
        database_engine,
        username="legacy-admin",
        password="twelve-chars",
    ) is not None


def test_disabled_or_malformed_persistent_identity_fails_closed(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "disabled.db")
    run_migrations(database_engine)
    bootstrap_initial_administrator(
        database_engine,
        username="admin",
        password="test-only-password",
    )
    with database_engine.begin() as conn:
        conn.exec_driver_sql("UPDATE useraccount SET enabled = 0")
    assert authenticate_initial_administrator(
        database_engine, username="admin", password="test-only-password"
    ) is None

    with database_engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE useraccount SET enabled = 1, password_hash = 'not-an-argon2-hash'"
        )
    assert authenticate_initial_administrator(
        database_engine, username="admin", password="test-only-password"
    ) is None


def test_new_password_policy_accepts_passphrases_and_rejects_weak_choices() -> None:
    assert validate_new_password("all lowercase words are fine") == "all lowercase words are fine"
    assert validate_new_password("Unicode passphrase 🛠️") == "Unicode passphrase 🛠️"
    assert normalize_username("  Ａdmin  ") == "admin"

    for password in ("short", "passwordpassword", "correcthorsebatterystaple"):
        try:
            validate_new_password(password)
        except PasswordPolicyError:
            pass
        else:
            raise AssertionError(f"weak password was accepted: {password!r}")
