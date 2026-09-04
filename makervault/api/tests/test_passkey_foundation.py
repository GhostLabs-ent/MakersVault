import sqlite3
import tarfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from migrations import MIGRATIONS, run_migrations
from recovery import RecoveryError, consistency_audit, create_backup, verify_backup
from recovery_mutation import mark_restored_database, recover_existing_administrator


ADMIN_ID = "11111111-1111-4111-8111-111111111111"
SESSION_ID = "22222222-2222-4222-8222-222222222222"
CREDENTIAL_ID = "33333333-3333-4333-8333-333333333333"
CHALLENGE_ID = "44444444-4444-4444-8444-444444444444"
ENCODED_CREDENTIAL_ID = "Y3JlZGVudGlhbC1pZC1maXh0dXJl"
ENCODED_PUBLIC_KEY = "cHVibGljLWtleS1tYXRlcmlhbC1maXh0dXJl"


def _tar_directory(source: Path, output: Path) -> None:
    with tarfile.open(output, "w") as archive:
        archive.add(source, arcname=".", recursive=True)


def schema17_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    database_dir = tmp_path / "database"
    storage_dir = tmp_path / "storage"
    database_dir.mkdir()
    storage_dir.mkdir()
    database = database_dir / "app.db"
    engine = create_engine(f"sqlite:///{database}")
    assert run_migrations(engine) == MIGRATIONS[-1].version == 17
    engine.dispose()

    connection = sqlite3.connect(database)
    connection.executescript(
        f"""
        INSERT INTO useraccount(
            id, username, username_normalized, display_name, password_hash,
            enabled, password_policy_version, password_change_required, role,
            created_at, updated_at, last_login_at, mfa_enabled
        ) VALUES (
            '{ADMIN_ID}', 'Admin', 'admin', 'Administrator',
            '$argon2id$v=19$fixture', 1, 1, 0, 'administrator',
            '2026-09-04T00:00:00Z', '2026-09-04T00:00:00Z', NULL, 1
        );
        INSERT INTO browsersession(
            id, user_id, secret_digest, created_at, last_seen_at, idle_expires_at,
            absolute_expires_at, idle_ttl_seconds, reauthenticated_at, revoked_at,
            client_address, user_agent
        ) VALUES (
            '{SESSION_ID}', '{ADMIN_ID}', '{'a' * 64}', 100, 110, 200, 300, 90,
            105, NULL, '127.0.0.1', 'fixture'
        );
        INSERT INTO webauthncredential(
            id, user_id, credential_id, public_key, sign_count, transports_json,
            device_type, backed_up, label, created_at, last_used_at
        ) VALUES (
            '{CREDENTIAL_ID}', '{ADMIN_ID}', '{ENCODED_CREDENTIAL_ID}',
            '{ENCODED_PUBLIC_KEY}', 7, '["internal","hybrid"]', 'multi_device', 1,
            'Primary passkey', '2026-09-04T00:00:00Z', NULL
        );
        INSERT INTO webauthnchallenge(
            id, user_id, purpose, challenge_digest, session_id, transaction_digest,
            rp_id, origin, created_at, expires_at, consumed_at, attempt_count
        ) VALUES (
            '{CHALLENGE_ID}', '{ADMIN_ID}', 'registration', '{'b' * 64}',
            '{SESSION_ID}', NULL, 'vault.example.test', 'https://vault.example.test',
            120, 300, NULL, 0
        );
        UPDATE authenticatorpolicy
        SET mode = 'require_administrators',
            updated_at = '2026-09-04T00:00:00Z',
            updated_by_user_id = '{ADMIN_ID}'
        WHERE id = 'global';
        """
    )
    connection.commit()
    connection.close()

    database_tar = tmp_path / "database.tar"
    storage_tar = tmp_path / "storage.tar"
    _tar_directory(database_dir, database_tar)
    _tar_directory(storage_dir, storage_tar)
    return database, storage_dir, database_tar, storage_tar


def test_contract6_represents_schema17_authenticator_state(tmp_path: Path) -> None:
    _database, _storage, database_tar, storage_tar = schema17_fixture(tmp_path)
    archive = tmp_path / "schema17.backup.tar.gz"

    manifest = create_backup(
        database_tar, storage_tar, archive, "v5.1.0", "gate11e-1a"
    )

    assert manifest["recovery_contract_version"] == 6
    assert manifest["database"]["schema_version"] == 17
    assert manifest["database"]["row_counts"]["webauthncredential"] == 1
    assert manifest["database"]["row_counts"]["webauthnchallenge"] == 1
    assert manifest["database"]["row_counts"]["authenticatorpolicy"] == 1
    assert manifest["consistency"]["webauthn_credential_count"] == 1
    assert manifest["consistency"]["pending_webauthn_challenge_count"] == 1
    assert verify_backup(archive) == manifest


@pytest.mark.parametrize(
    ("mutation", "finding"),
    [
        (
            "UPDATE webauthncredential SET public_key = 'not-base64url'",
            "invalid_webauthn_credential_ids",
        ),
        (
            "UPDATE webauthnchallenge SET expires_at = created_at + 301",
            "invalid_webauthn_challenge_ids",
        ),
        (
            "UPDATE useraccount SET mfa_enabled = 0 WHERE id = '" + ADMIN_ID + "'",
            "policy_unenrolled_account_ids",
        ),
    ],
)
def test_contract6_rejects_corrupt_authenticator_state(
    tmp_path: Path,
    mutation: str,
    finding: str,
) -> None:
    database, _storage, _database_tar, storage_tar = schema17_fixture(tmp_path)
    connection = sqlite3.connect(database)
    connection.execute(mutation)
    connection.commit()
    connection.close()
    database_tar = tmp_path / "corrupt-database.tar"
    _tar_directory(database.parent, database_tar)

    report = consistency_audit(database, [])
    assert report["status"] == "inconsistent"
    assert report[finding]
    with pytest.raises(RecoveryError, match="inconsistent"):
        create_backup(
            database_tar,
            storage_tar,
            tmp_path / "corrupt.backup.tar.gz",
            "v5.1.0",
            "gate11e-1a",
        )


def test_schema17_raw_restore_revokes_challenges_but_keeps_credentials(
    tmp_path: Path,
) -> None:
    database, _storage, _database_tar, _storage_tar = schema17_fixture(tmp_path)

    result = mark_restored_database(database)

    connection = sqlite3.connect(database)
    try:
        challenge = connection.execute(
            "SELECT consumed_at FROM webauthnchallenge WHERE id = ?", (CHALLENGE_ID,)
        ).fetchone()
        marker = connection.execute(
            "SELECT details_json FROM recoverymarker WHERE id = ?",
            (result["marker_id"],),
        ).fetchone()
        credential_count = connection.execute(
            "SELECT COUNT(*) FROM webauthncredential"
        ).fetchone()[0]
    finally:
        connection.close()

    assert result["revoked_sessions"] == 1
    assert result["revoked_challenges"] == 1
    assert challenge is not None and challenge[0] is not None
    assert credential_count == 1
    assert '"revoked_challenges":1' in marker[0]


def test_schema17_stopped_recovery_clears_factor_and_relaxes_policy(
    tmp_path: Path,
) -> None:
    database, _storage, database_tar, storage_tar = schema17_fixture(tmp_path)
    backup = tmp_path / "prechange.backup.tar.gz"
    create_backup(database_tar, storage_tar, backup, "v5.1.0", "gate11e-1a")

    result = recover_existing_administrator(
        database,
        backup,
        "Admin",
        "$argon2id$v=19$new-temporary-hash",
        1,
    )

    connection = sqlite3.connect(database)
    try:
        account = connection.execute(
            "SELECT mfa_enabled, password_change_required, role FROM useraccount "
            "WHERE id = ?",
            (ADMIN_ID,),
        ).fetchone()
        credential_count = connection.execute(
            "SELECT COUNT(*) FROM webauthncredential WHERE user_id = ?", (ADMIN_ID,)
        ).fetchone()[0]
        challenge_count = connection.execute(
            "SELECT COUNT(*) FROM webauthnchallenge WHERE user_id = ?", (ADMIN_ID,)
        ).fetchone()[0]
        policy_mode = connection.execute(
            "SELECT mode FROM authenticatorpolicy WHERE id = 'global'"
        ).fetchone()[0]
    finally:
        connection.close()

    assert account == (0, 1, "administrator")
    assert credential_count == 0
    assert challenge_count == 0
    assert policy_mode == "optional"
    assert result["removed_credentials"] == 1
    assert result["revoked_challenges"] == 1
    assert result["reset_mfa_policy"] is True
