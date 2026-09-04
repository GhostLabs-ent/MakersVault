"""Stopped-instance recovery mutations with exact-file and lock enforcement."""

from __future__ import annotations

from contextlib import contextmanager
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import time
import unicodedata
import uuid

from recovery import (
    RecoveryError,
    extract_database_component,
    extract_outer_archive,
    sha256_file,
    verify_extracted_backup,
)


class RecoveryMutationError(RuntimeError):
    pass


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _exact_regular_file(path: Path, label: str) -> Path:
    candidate = path.absolute()
    try:
        mode = candidate.lstat().st_mode
    except OSError as exc:
        raise RecoveryMutationError(f"{label} is not readable: {candidate}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise RecoveryMutationError(f"{label} must be one exact regular file: {candidate}")
    return candidate


@contextmanager
def _locked_database(path: Path):
    database = _exact_regular_file(path, "database")
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(database, flags)
    except OSError as exc:
        raise RecoveryMutationError("database could not be opened safely") from exc
    connection: sqlite3.Connection | None = None
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RecoveryMutationError("database instance lock is already held") from exc
        wal = Path(f"{database}-wal")
        if wal.exists() and wal.stat().st_size:
            raise RecoveryMutationError(
                "database has an active WAL; stop the instance and checkpoint it first"
            )
        connection = sqlite3.connect(database, timeout=1, isolation_level=None)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN EXCLUSIVE")
        if [str(row[0]) for row in connection.execute("PRAGMA quick_check")] != ["ok"]:
            raise RecoveryMutationError("SQLite quick_check did not return ok")
        yield database, connection
        connection.commit()
    except sqlite3.Error as exc:
        if connection is not None:
            connection.rollback()
        raise RecoveryMutationError("stopped-instance database mutation failed") from exc
    except Exception:
        if connection is not None:
            connection.rollback()
        raise
    finally:
        if connection is not None:
            connection.close()
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _require_security_schema(connection: sqlite3.Connection) -> int:
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    required = {"schema_migration", "useraccount", "browsersession", "recoverymarker"}
    if not required.issubset(tables):
        raise RecoveryMutationError("database is not a schema-16 MakersVault database")
    version = int(
        connection.execute("SELECT MAX(version) FROM schema_migration").fetchone()[0] or 0
    )
    if version < 16:
        raise RecoveryMutationError("database must be migrated to schema 16")
    if version >= 17 and not {
        "webauthncredential", "webauthnchallenge", "authenticatorpolicy"
    }.issubset(tables):
        raise RecoveryMutationError("database is missing schema-17 authenticator state")
    return version


def _schema_version(connection: sqlite3.Connection) -> int:
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if "schema_migration" not in tables:
        return 0
    return int(
        connection.execute("SELECT MAX(version) FROM schema_migration").fetchone()[0] or 0
    )


def _revoke_all_sessions(connection: sqlite3.Connection, now_epoch: int) -> int:
    active = int(
        connection.execute(
            "SELECT COUNT(*) FROM browsersession WHERE revoked_at IS NULL"
        ).fetchone()[0]
    )
    connection.execute(
        "UPDATE browsersession SET revoked_at = ? WHERE revoked_at IS NULL",
        (now_epoch,),
    )
    return active


def _revoke_all_challenges(connection: sqlite3.Connection, now_epoch: int) -> int:
    active = int(
        connection.execute(
            "SELECT COUNT(*) FROM webauthnchallenge WHERE consumed_at IS NULL"
        ).fetchone()[0]
    )
    connection.execute(
        "UPDATE webauthnchallenge SET consumed_at = ? WHERE consumed_at IS NULL",
        (now_epoch,),
    )
    return active


def _insert_marker(
    connection: sqlite3.Connection,
    kind: str,
    details: dict[str, object],
) -> str:
    marker_id = str(uuid.uuid4())
    connection.execute(
        "INSERT INTO recoverymarker(id, kind, created_at, details_json, processed_at) "
        "VALUES (?, ?, ?, ?, NULL)",
        (
            marker_id,
            kind,
            _timestamp(),
            json.dumps(details, sort_keys=True, separators=(",", ":")),
        ),
    )
    return marker_id


def mark_restored_database(database_path: Path) -> dict[str, object]:
    """Revoke copied sessions and queue an auditable startup marker."""
    with _locked_database(database_path) as (_database, connection):
        version = _schema_version(connection)
        revoked = (
            _revoke_all_sessions(connection, int(time.time()))
            if version >= 14 else 0
        )
        marker_id = None
        if version >= 16:
            _require_security_schema(connection)
            revoked_challenges = (
                _revoke_all_challenges(connection, int(time.time()))
                if version >= 17 else 0
            )
            details: dict[str, object] = {"revoked_sessions": revoked}
            if version >= 17:
                details["revoked_challenges"] = revoked_challenges
            marker_id = _insert_marker(
                connection,
                "raw_restore",
                details,
            )
    return {
        "marker_id": marker_id,
        "revoked_sessions": revoked,
        "revoked_challenges": revoked_challenges if version >= 17 else 0,
        "schema_version": version,
    }


def recover_existing_administrator(
    database_path: Path,
    backup_archive: Path,
    username: str,
    password_hash: str,
    password_policy_version: int,
) -> dict[str, object]:
    """Reset one existing account only after proving an exact matched backup."""
    backup = _exact_regular_file(backup_archive, "backup archive")
    normalized = unicodedata.normalize("NFKC", username).strip().casefold()
    if not normalized or len(normalized) > 256:
        raise RecoveryMutationError("username must contain between 1 and 256 characters")
    with _locked_database(database_path) as (database, connection):
        version = _require_security_schema(connection)
        try:
            with tempfile.TemporaryDirectory(prefix="makersvault-admin-recovery-") as work:
                extracted = Path(work)
                seen = extract_outer_archive(backup, extracted)
                verify_extracted_backup(
                    extracted,
                    seen,
                    allow_administrator_recovery=True,
                )
                backed_up_database = extract_database_component(
                    extracted / "database.tar", extracted / "database"
                )
                if sha256_file(database) != sha256_file(backed_up_database):
                    raise RecoveryMutationError(
                        "backup does not contain the exact pre-change database"
                    )
        except RecoveryError as exc:
            raise RecoveryMutationError(
                "matched backup could not be independently verified"
            ) from exc
        rows = connection.execute(
            "SELECT id, username FROM useraccount WHERE username_normalized = ?",
            (normalized,),
        ).fetchall()
        if len(rows) != 1:
            raise RecoveryMutationError("exactly one existing account must match")
        user_id, stored_username = str(rows[0][0]), str(rows[0][1])
        now = _timestamp()
        if version >= 17:
            connection.execute(
                "UPDATE useraccount SET password_hash = ?, enabled = 1, "
                "password_policy_version = ?, password_change_required = 1, "
                "role = 'administrator', mfa_enabled = 0, updated_at = ? WHERE id = ?",
                (password_hash, password_policy_version, now, user_id),
            )
            removed_credentials = int(
                connection.execute(
                    "SELECT COUNT(*) FROM webauthncredential WHERE user_id = ?",
                    (user_id,),
                ).fetchone()[0]
            )
            revoked_challenges = int(
                connection.execute(
                    "SELECT COUNT(*) FROM webauthnchallenge "
                    "WHERE user_id = ? AND consumed_at IS NULL",
                    (user_id,),
                ).fetchone()[0]
            )
            connection.execute(
                "DELETE FROM webauthncredential WHERE user_id = ?", (user_id,)
            )
            connection.execute(
                "DELETE FROM webauthnchallenge WHERE user_id = ?", (user_id,)
            )
            current_mode = str(
                connection.execute(
                    "SELECT mode FROM authenticatorpolicy WHERE id = 'global'"
                ).fetchone()[0]
            )
            reset_mfa_policy = current_mode != "optional"
            connection.execute(
                "UPDATE authenticatorpolicy SET mode = 'optional', updated_at = ?, "
                "updated_by_user_id = NULL WHERE id = 'global'",
                (now,),
            )
        else:
            connection.execute(
                "UPDATE useraccount SET password_hash = ?, enabled = 1, "
                "password_policy_version = ?, password_change_required = 1, "
                "role = 'administrator', updated_at = ? WHERE id = ?",
                (password_hash, password_policy_version, now, user_id),
            )
            removed_credentials = 0
            revoked_challenges = 0
            reset_mfa_policy = False
        revoked = _revoke_all_sessions(connection, int(time.time()))
        details: dict[str, object] = {
            "user_id": user_id,
            "revoked_sessions": revoked,
        }
        if version >= 17:
            details.update(
                revoked_challenges=revoked_challenges,
                removed_credentials=removed_credentials,
                reset_mfa_policy=reset_mfa_policy,
            )
        marker_id = _insert_marker(
            connection,
            "administrator_recovery",
            details,
        )
    return {
        "marker_id": marker_id,
        "revoked_sessions": revoked,
        "revoked_challenges": revoked_challenges,
        "removed_credentials": removed_credentials,
        "reset_mfa_policy": reset_mfa_policy,
        "user_id": user_id,
        "username": stored_username,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply a stopped-instance recovery marker")
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = mark_restored_database(args.database)
    except RecoveryMutationError as exc:
        print(f"Restore recovery error: {exc}", file=os.sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
