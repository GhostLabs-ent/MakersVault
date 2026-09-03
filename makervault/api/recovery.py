"""MakersVault backup manifest, integrity, and recovery helpers.

This module intentionally uses only the Python standard library so operators can
verify a backup without starting the MakersVault application.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tarfile
import tempfile
import unicodedata
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable, Optional


BACKUP_FORMAT = "makersvault-backup"
BACKUP_FORMAT_VERSION = 1
RECOVERY_CONTRACT_VERSION = 5
SUPPORTED_RECOVERY_CONTRACT_VERSIONS = {2, 3, 4, RECOVERY_CONTRACT_VERSION}
COMPONENT_NAMES = ("database.tar", "storage.tar")
OPTIONAL_NAMES = ("config.env",)
METADATA_NAMES = ("manifest.json", "checksums.sha256")


class RecoveryError(RuntimeError):
    pass


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_member_name(raw: str) -> str:
    if "\\" in raw:
        raise RecoveryError(f"Archive member uses a platform separator: {raw}")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        raise RecoveryError(f"Archive member escapes its root: {raw}")
    parts = [part for part in path.parts if part not in {"", "."}]
    return "/".join(parts)


def validate_component_tar(path: Path) -> list[dict]:
    if not path.is_file():
        raise RecoveryError(f"Backup component is missing: {path}")
    files: list[dict] = []
    seen: set[str] = set()
    try:
        archive = tarfile.open(path, "r:*")
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise RecoveryError(f"Backup component is not a readable tar archive: {path.name}") from exc
    try:
        with archive:
            for member in archive.getmembers():
                name = normalized_member_name(member.name)
                if not name:
                    continue
                if name in seen:
                    raise RecoveryError(f"Backup component contains a duplicate path: {name}")
                seen.add(name)
                if member.isdir():
                    continue
                if not member.isfile():
                    raise RecoveryError(f"Backup component contains a non-regular entry: {name}")
                source = archive.extractfile(member)
                if source is None:
                    raise RecoveryError(f"Backup component member is unreadable: {name}")
                digest = hashlib.sha256()
                with source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(block)
                files.append({
                    "path": name,
                    "size": int(member.size),
                    "sha256": digest.hexdigest(),
                })
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise RecoveryError(f"Backup component is unreadable: {path.name}") from exc
    files.sort(key=lambda item: item["path"])
    return files


def extract_regular_member(archive: tarfile.TarFile, member: tarfile.TarInfo, destination: Path) -> None:
    name = normalized_member_name(member.name)
    if not name or not member.isfile():
        return
    target = destination / Path(*PurePosixPath(name).parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    source = archive.extractfile(member)
    if source is None:
        raise RecoveryError(f"Could not read archive member: {name}")
    with source, target.open("wb") as output:
        shutil.copyfileobj(source, output, length=1024 * 1024)
    os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)


def extract_database_component(path: Path, destination: Path) -> Path:
    members = validate_component_tar(path)
    app_db = [item for item in members if item["path"] == "app.db"]
    if len(app_db) != 1:
        raise RecoveryError("Database component must contain app.db at its root")
    with tarfile.open(path, "r:*") as archive:
        for member in archive.getmembers():
            extract_regular_member(archive, member, destination)
    return destination / "app.db"


def table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def database_summary(database: Path) -> dict:
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise RecoveryError("SQLite database could not be opened read-only") from exc
    try:
        quick_check_rows = connection.execute("PRAGMA quick_check").fetchall()
        quick_check = [str(row[0]) for row in quick_check_rows]
        tables = table_names(connection)
        schema_version = 0
        if "schema_migration" in tables:
            row = connection.execute("SELECT MAX(version) FROM schema_migration").fetchone()
            schema_version = int(row[0] or 0)
        counts = {}
        counted_tables = ["folder", "asset", "assetfile", "appconfig", "mountscan"]
        counted_tables.extend(
            table
            for table in (
                "artifactrevision",
                "contenthashjob",
                "contenthashjobitem",
                "trashpurgeoperation",
                "project",
                "projectmembership",
                "projectrelationship",
                "machineprofile",
                "artifactmachine",
                "useraccount",
                "browsersession",
                "auditevent",
                "recoverymarker",
            )
            if table in tables
        )
        for table in counted_tables:
            counts[table] = (
                int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                if table in tables
                else 0
            )
        return {
            "quick_check": quick_check,
            "schema_version": schema_version,
            "tables": sorted(tables),
            "row_counts": counts,
        }
    except sqlite3.Error as exc:
        raise RecoveryError("SQLite integrity inspection failed") from exc
    finally:
        connection.close()


def _select_assets(connection: sqlite3.Connection) -> list[dict]:
    tables = table_names(connection)
    if "asset" not in tables:
        return []
    columns = table_columns(connection, "asset")
    wanted = [
        "id",
        "filename",
        "source_path",
        "storage_path",
        "prepared_file_id",
        "supporting_file_count",
        "current_revision_id",
        "current_thumb_path",
        "deleted_at",
        "prepared_machine_id",
    ]
    selected = [name for name in wanted if name in columns]
    rows = connection.execute(f"SELECT {', '.join(selected)} FROM asset").fetchall()
    return [dict(zip(selected, row)) for row in rows]


def _select_asset_files(connection: sqlite3.Connection) -> list[dict]:
    tables = table_names(connection)
    if "assetfile" not in tables:
        return []
    columns = table_columns(connection, "assetfile")
    wanted = ["id", "asset_id", "role", "storage_path", "revision_id"]
    selected = [name for name in wanted if name in columns]
    rows = connection.execute(f"SELECT {', '.join(selected)} FROM assetfile").fetchall()
    return [dict(zip(selected, row)) for row in rows]


def _select_revisions(connection: sqlite3.Connection) -> list[dict]:
    tables = table_names(connection)
    if "artifactrevision" not in tables:
        return []
    columns = table_columns(connection, "artifactrevision")
    wanted = [
        "id",
        "asset_id",
        "revision_number",
        "filename",
        "size",
        "sha256",
        "storage_path",
        "source_path",
        "prepared_file_id",
        "preview_thumb_path",
        "prepared_machine_id",
    ]
    selected = [name for name in wanted if name in columns]
    rows = connection.execute(f"SELECT {', '.join(selected)} FROM artifactrevision").fetchall()
    return [dict(zip(selected, row)) for row in rows]


def _select_purge_operations(connection: sqlite3.Connection) -> list[dict]:
    tables = table_names(connection)
    if "trashpurgeoperation" not in tables:
        return []
    columns = table_columns(connection, "trashpurgeoperation")
    wanted = ["id", "status", "asset_ids_json", "paths_json", "quarantine_path"]
    selected = [name for name in wanted if name in columns]
    rows = connection.execute(f"SELECT {', '.join(selected)} FROM trashpurgeoperation").fetchall()
    return [dict(zip(selected, row)) for row in rows]


def _select_projects(connection: sqlite3.Connection) -> list[dict]:
    if "project" not in table_names(connection):
        return []
    rows = connection.execute(
        "SELECT id, deleted_at FROM project ORDER BY id"
    ).fetchall()
    return [dict(zip(("id", "deleted_at"), row)) for row in rows]


def _select_project_memberships(connection: sqlite3.Connection) -> list[dict]:
    if "projectmembership" not in table_names(connection):
        return []
    rows = connection.execute(
        "SELECT project_id, asset_id FROM projectmembership "
        "ORDER BY project_id, asset_id"
    ).fetchall()
    return [dict(zip(("project_id", "asset_id"), row)) for row in rows]


def _select_project_relationships(connection: sqlite3.Connection) -> list[dict]:
    if "projectrelationship" not in table_names(connection):
        return []
    columns = (
        "id",
        "project_id",
        "source_asset_id",
        "target_asset_id",
        "kind",
    )
    rows = connection.execute(
        f"SELECT {', '.join(columns)} FROM projectrelationship "
        "ORDER BY project_id, source_asset_id, target_asset_id, kind, id"
    ).fetchall()
    return [dict(zip(columns, row)) for row in rows]


def _select_machines(connection: sqlite3.Connection) -> list[dict]:
    if "machineprofile" not in table_names(connection):
        return []
    columns = ("id", "name", "category", "archived_at")
    rows = connection.execute(
        f"SELECT {', '.join(columns)} FROM machineprofile ORDER BY id"
    ).fetchall()
    return [dict(zip(columns, row)) for row in rows]


def _select_machine_associations(connection: sqlite3.Connection) -> list[dict]:
    if "artifactmachine" not in table_names(connection):
        return []
    columns = ("asset_id", "machine_id")
    rows = connection.execute(
        f"SELECT {', '.join(columns)} FROM artifactmachine "
        "ORDER BY asset_id, machine_id"
    ).fetchall()
    return [dict(zip(columns, row)) for row in rows]


def _select_available(
    connection: sqlite3.Connection,
    table: str,
    wanted: tuple[str, ...],
) -> list[dict]:
    if table not in table_names(connection):
        return []
    available = table_columns(connection, table)
    selected = [column for column in wanted if column in available]
    if not selected:
        return []
    rows = connection.execute(f"SELECT {', '.join(selected)} FROM {table}").fetchall()
    return [dict(zip(selected, row)) for row in rows]


def _canonical_uuid(value: object) -> bool:
    candidate = str(value or "")
    try:
        return candidate == str(uuid.UUID(candidate))
    except ValueError:
        return False


def _valid_iso_timestamp(value: object) -> bool:
    candidate = str(value or "")
    if not candidate or len(candidate) > 64:
        return False
    try:
        datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _json_object(value: object, maximum_bytes: int = 2048) -> bool:
    candidate = str(value or "")
    if len(candidate.encode("utf-8")) > maximum_bytes:
        return False
    try:
        return isinstance(json.loads(candidate), dict)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False


def _parsed_json_object(value: object, maximum_bytes: int = 2048) -> Optional[dict]:
    if not _json_object(value, maximum_bytes):
        return None
    return json.loads(str(value))


def _valid_audit_details(value: object) -> bool:
    details = _parsed_json_object(value)
    if details is None or set(details) - {"changed_fields", "revoked_sessions"}:
        return False
    if "changed_fields" in details:
        changed = details["changed_fields"]
        if (
            not isinstance(changed, list)
            or any(
                field not in {"display_name", "role", "enabled", "password"}
                for field in changed
            )
        ):
            return False
    revoked = details.get("revoked_sessions", 0)
    return isinstance(revoked, int) and not isinstance(revoked, bool) and revoked >= 0


def _valid_recovery_details(kind: str, value: object, user_ids: set[str]) -> bool:
    details = _parsed_json_object(value)
    if details is None:
        return False
    expected = (
        {"revoked_sessions"}
        if kind == "raw_restore"
        else {"user_id", "revoked_sessions"}
    )
    if set(details) != expected:
        return False
    revoked = details.get("revoked_sessions")
    if not isinstance(revoked, int) or isinstance(revoked, bool) or revoked < 0:
        return False
    return kind == "raw_restore" or str(details.get("user_id") or "") in user_ids


def _external_state(
    source_path: str,
    container_root: Optional[Path],
    host_root: Optional[Path],
) -> str:
    if not container_root or not host_root:
        return "unknown"
    source = PurePosixPath(source_path)
    root = PurePosixPath(container_root.as_posix())
    try:
        relative = source.relative_to(root)
    except ValueError:
        return "outside_mapping"
    return "available" if (host_root / Path(*relative.parts)).is_file() else "unavailable"


def consistency_audit(
    database: Path,
    storage_files: Iterable[str | dict],
    external_container_root: Optional[Path] = None,
    external_host_root: Optional[Path] = None,
) -> dict:
    storage: set[str] = set()
    storage_digests: dict[str, str] = {}
    storage_sizes: dict[str, int] = {}
    for item in storage_files:
        name = str(item.get("path") or "") if isinstance(item, dict) else str(item)
        normalized = normalized_member_name(name)
        if normalized:
            storage.add(normalized)
            if isinstance(item, dict):
                if item.get("sha256"):
                    storage_digests[normalized] = str(item["sha256"])
                if item.get("size") is not None:
                    storage_sizes[normalized] = int(item["size"])
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        tables = table_names(connection)
        assets = _select_assets(connection)
        asset_files = _select_asset_files(connection)
        revisions = _select_revisions(connection)
        purge_operations = _select_purge_operations(connection)
        projects = _select_projects(connection)
        project_memberships = _select_project_memberships(connection)
        project_relationships = _select_project_relationships(connection)
        machines = _select_machines(connection)
        machine_associations = _select_machine_associations(connection)
        users = _select_available(
            connection,
            "useraccount",
            (
                "id", "username", "username_normalized", "display_name",
                "password_hash", "enabled", "password_policy_version",
                "password_change_required", "role", "created_at", "updated_at",
                "last_login_at",
            ),
        )
        browser_sessions = _select_available(
            connection,
            "browsersession",
            (
                "id", "user_id", "secret_digest", "created_at", "last_seen_at",
                "idle_expires_at", "absolute_expires_at", "idle_ttl_seconds",
                "reauthenticated_at", "revoked_at", "client_address", "user_agent",
            ),
        )
        audit_events = _select_available(
            connection,
            "auditevent",
            (
                "id", "occurred_at", "correlation_id", "actor_user_id",
                "actor_username", "actor_role", "action", "result", "object_type",
                "object_id", "method", "route", "permission", "status_code",
                "source_address", "details_json",
            ),
        )
        recovery_markers = _select_available(
            connection,
            "recoverymarker",
            ("id", "kind", "created_at", "details_json", "processed_at"),
        )
        security_table_columns = {
            table: table_columns(connection, table)
            for table in ("useraccount", "browsersession", "auditevent", "recoverymarker")
            if table in tables
        }
        asset_columns = table_columns(connection, "asset") if "asset" in tables else set()
        revision_columns = (
            table_columns(connection, "artifactrevision")
            if "artifactrevision" in tables
            else set()
        )
        schema_version = 0
        if "schema_migration" in tables:
            row = connection.execute(
                "SELECT MAX(version) FROM schema_migration"
            ).fetchone()
            schema_version = int(row[0] or 0)
    finally:
        connection.close()

    asset_by_id = {str(row.get("id") or ""): row for row in assets}
    revision_by_id = {str(row.get("id") or ""): row for row in revisions}
    file_by_id = {str(row.get("id") or ""): row for row in asset_files}
    project_by_id = {str(row.get("id") or ""): row for row in projects}
    machine_by_id = {str(row.get("id") or ""): row for row in machines}
    referenced: set[str] = set()
    managed_present = 0
    missing_managed: list[str] = []
    external: list[dict[str, str]] = []
    malformed_purge_operation_ids: list[str] = []
    purge_status_counts: dict[str, int] = {}
    quarantine_alternates: dict[str, set[str]] = {}
    known_quarantine_paths: set[str] = set()
    recoverable_statuses = {"moving", "quarantined"}
    committed_statuses = {"database_committed", "cleanup_pending"}
    for operation in purge_operations:
        operation_id = str(operation.get("id") or "")
        status = str(operation.get("status") or "unknown")
        purge_status_counts[status] = purge_status_counts.get(status, 0) + 1
        try:
            paths = json.loads(str(operation.get("paths_json") or "[]"))
            asset_ids = json.loads(str(operation.get("asset_ids_json") or "[]"))
            if not isinstance(paths, list) or not isinstance(asset_ids, list):
                raise ValueError
            expected_root = normalized_member_name(
                str(operation.get("quarantine_path") or f".trash-quarantine/{operation_id}")
            )
            for entry in paths:
                if not isinstance(entry, dict):
                    raise ValueError
                source = normalized_member_name(str(entry.get("source") or ""))
                quarantine = normalized_member_name(str(entry.get("quarantine") or ""))
                if not source or not quarantine or not quarantine.startswith(f"{expected_root}/"):
                    raise ValueError
                if status in recoverable_statuses:
                    quarantine_alternates.setdefault(source, set()).add(quarantine)
                    if quarantine in storage:
                        known_quarantine_paths.add(quarantine)
                        referenced.add(quarantine)
                elif status in committed_statuses and quarantine in storage:
                    known_quarantine_paths.add(quarantine)
                    referenced.add(quarantine)
        except (TypeError, ValueError, json.JSONDecodeError, RecoveryError):
            malformed_purge_operation_ids.append(operation_id)

    def locate_managed(path: str) -> tuple[str, Optional[str]]:
        normalized = normalized_member_name(path)
        if normalized in storage:
            referenced.add(normalized)
            return "present", normalized
        for quarantine in sorted(quarantine_alternates.get(normalized, set())):
            if quarantine in storage:
                referenced.add(quarantine)
                return "quarantined", quarantine
        return "missing", None

    managed_revision_present = 0
    quarantined_managed_revision_ids: list[str] = []
    missing_managed_revision_ids: list[str] = []
    revision_digest_mismatch_ids: list[str] = []
    revision_size_mismatch_ids: list[str] = []
    uses_revisions = "artifactrevision" in tables
    primary_rows = revisions if uses_revisions else assets
    for row in primary_rows:
        asset_id = str(row.get("asset_id") or row.get("id") or "")
        revision_id = str(row.get("id") or "") if uses_revisions else ""
        filename = str(row.get("filename") or "")
        managed = normalized_member_name(
            str(row.get("storage_path") or f"{asset_id}/{filename}")
        )
        state, located_path = locate_managed(managed)
        if state == "present":
            managed_present += 1
            managed_revision_present += int(uses_revisions)
            expected_digest = str(row.get("sha256") or "")
            if expected_digest and storage_digests.get(managed) not in {None, expected_digest}:
                revision_digest_mismatch_ids.append(revision_id)
            expected_size = row.get("size")
            if expected_size is not None and managed in storage_sizes:
                if int(expected_size) != storage_sizes[managed]:
                    revision_size_mismatch_ids.append(revision_id or asset_id)
        elif state == "quarantined":
            managed_present += 1
            if uses_revisions:
                managed_revision_present += 1
                quarantined_managed_revision_ids.append(revision_id)
            if located_path:
                expected_digest = str(row.get("sha256") or "")
                if expected_digest and storage_digests.get(located_path) not in {None, expected_digest}:
                    revision_digest_mismatch_ids.append(revision_id)
                expected_size = row.get("size")
                if expected_size is not None and located_path in storage_sizes:
                    if int(expected_size) != storage_sizes[located_path]:
                        revision_size_mismatch_ids.append(revision_id)
        elif row.get("source_path"):
            source_path = str(row["source_path"])
            record = {
                "asset_id": asset_id,
                "source_path": source_path,
                "state": _external_state(
                    source_path,
                    external_container_root,
                    external_host_root,
                ),
            }
            if uses_revisions:
                record["revision_id"] = revision_id
            external.append(record)
        elif uses_revisions:
            missing_managed_revision_ids.append(revision_id)
        else:
            missing_managed.append(asset_id)

    related_missing: list[str] = []
    related_quarantined: list[str] = []
    related_orphan_asset_ids: list[str] = []
    related_revision_mismatch_ids: list[str] = []
    for row in asset_files:
        file_id = str(row.get("id") or "")
        asset_id = str(row.get("asset_id") or "")
        revision_id = str(row.get("revision_id") or "")
        state, _located = locate_managed(str(row.get("storage_path") or ""))
        if state == "quarantined":
            related_quarantined.append(file_id)
        elif state != "present":
            related_missing.append(file_id)
        if asset_id not in asset_by_id:
            related_orphan_asset_ids.append(file_id)
        if revision_id:
            revision = revision_by_id.get(revision_id)
            if not revision or str(revision.get("asset_id") or "") != asset_id:
                related_revision_mismatch_ids.append(file_id)

    revision_orphan_asset_ids = sorted(
        str(row.get("id") or "")
        for row in revisions
        if str(row.get("asset_id") or "") not in asset_by_id
    )
    missing_current_revision_asset_ids: list[str] = []
    invalid_current_revision_asset_ids: list[str] = []
    if uses_revisions:
        for asset in assets:
            asset_id = str(asset.get("id") or "")
            revision_id = str(asset.get("current_revision_id") or "")
            if not revision_id:
                missing_current_revision_asset_ids.append(asset_id)
                continue
            revision = revision_by_id.get(revision_id)
            if not revision or str(revision.get("asset_id") or "") != asset_id:
                invalid_current_revision_asset_ids.append(asset_id)

    def invalid_prepared_pointer(owner_asset_id: str, pointer: object, revision_id: str = "") -> bool:
        if not pointer:
            return False
        file = file_by_id.get(str(pointer))
        if not file or str(file.get("asset_id") or "") != owner_asset_id:
            return True
        if str(file.get("role") or "") != "prepared":
            return True
        file_revision_id = str(file.get("revision_id") or "")
        return bool(revision_id and file_revision_id != revision_id)

    prepared_pointer_missing = [
        str(asset.get("id") or "")
        for asset in assets
        if invalid_prepared_pointer(
            str(asset.get("id") or ""),
            asset.get("prepared_file_id"),
            str(asset.get("current_revision_id") or "") if uses_revisions else "",
        )
    ]
    invalid_revision_prepared_pointer_ids = [
        str(revision.get("id") or "")
        for revision in revisions
        if invalid_prepared_pointer(
            str(revision.get("asset_id") or ""),
            revision.get("prepared_file_id"),
            str(revision.get("id") or ""),
        )
    ]

    missing_thumbnail_paths: list[str] = []
    thumbnail_paths = {
        normalized_member_name(str(path))
        for path in [
            *(asset.get("current_thumb_path") for asset in assets),
            *(revision.get("preview_thumb_path") for revision in revisions),
        ]
        if path
    }
    for path in sorted(thumbnail_paths):
        if path in storage:
            referenced.add(path)
        else:
            missing_thumbnail_paths.append(path)

    external_counts = {
        state: sum(1 for item in external if item["state"] == state)
        for state in ("available", "unavailable", "unknown", "outside_mapping")
    }
    unknown_quarantine_paths = sorted(
        name
        for name in storage
        if name.startswith(".trash-quarantine/") and name not in known_quarantine_paths
    )
    orphans = sorted(
        name
        for name in storage
        if name not in referenced and not name.startswith("thumbs/")
    )

    expected_project_tables: set[str] = set()
    if schema_version >= 9:
        expected_project_tables.update({"project", "projectmembership"})
    if schema_version >= 10:
        expected_project_tables.add("projectrelationship")
    missing_project_tables = sorted(expected_project_tables - tables)
    membership_keys = {
        (
            str(row.get("project_id") or ""),
            str(row.get("asset_id") or ""),
        )
        for row in project_memberships
    }
    orphan_project_membership_keys = sorted(
        f"{project_id}/{asset_id}"
        for project_id, asset_id in membership_keys
        if project_id not in project_by_id
    )
    orphan_asset_membership_keys = sorted(
        f"{project_id}/{asset_id}"
        for project_id, asset_id in membership_keys
        if asset_id not in asset_by_id
    )
    orphan_relationship_project_ids: list[str] = []
    orphan_relationship_source_asset_ids: list[str] = []
    orphan_relationship_target_asset_ids: list[str] = []
    relationship_nonmember_source_ids: list[str] = []
    relationship_nonmember_target_ids: list[str] = []
    self_relationship_ids: list[str] = []
    invalid_relationship_kind_ids: list[str] = []
    duplicate_relationship_ids: list[str] = []
    canonical_relationships: set[tuple[str, str, str, str]] = set()
    canonical_kinds = {"derived_from", "documentation_for", "component_of"}
    for relationship in project_relationships:
        relationship_id = str(relationship.get("id") or "")
        project_id = str(relationship.get("project_id") or "")
        source_id = str(relationship.get("source_asset_id") or "")
        target_id = str(relationship.get("target_asset_id") or "")
        kind = str(relationship.get("kind") or "")
        if project_id not in project_by_id:
            orphan_relationship_project_ids.append(relationship_id)
        if source_id not in asset_by_id:
            orphan_relationship_source_asset_ids.append(relationship_id)
        elif project_id in project_by_id and (project_id, source_id) not in membership_keys:
            relationship_nonmember_source_ids.append(relationship_id)
        if target_id not in asset_by_id:
            orphan_relationship_target_asset_ids.append(relationship_id)
        elif project_id in project_by_id and (project_id, target_id) not in membership_keys:
            relationship_nonmember_target_ids.append(relationship_id)
        if source_id == target_id:
            self_relationship_ids.append(relationship_id)
        if kind not in canonical_kinds:
            invalid_relationship_kind_ids.append(relationship_id)
        canonical = (project_id, source_id, target_id, kind)
        if canonical in canonical_relationships:
            duplicate_relationship_ids.append(relationship_id)
        canonical_relationships.add(canonical)

    expected_machine_tables: set[str] = set()
    if schema_version >= 11:
        expected_machine_tables.add("machineprofile")
    if schema_version >= 12:
        expected_machine_tables.add("artifactmachine")
    missing_machine_tables = sorted(expected_machine_tables - tables)
    missing_machine_reference_columns: list[str] = []
    if schema_version >= 12:
        if "prepared_machine_id" not in asset_columns:
            missing_machine_reference_columns.append("asset.prepared_machine_id")
        if "prepared_machine_id" not in revision_columns:
            missing_machine_reference_columns.append(
                "artifactrevision.prepared_machine_id"
            )

    valid_machine_categories = {
        "fdm_printer",
        "resin_printer",
        "laser",
        "cnc",
        "pcb",
        "other",
    }
    invalid_machine_category_ids = sorted(
        str(machine.get("id") or "")
        for machine in machines
        if str(machine.get("category") or "") not in valid_machine_categories
    )
    active_name_ids: dict[str, list[str]] = {}
    for machine in machines:
        if machine.get("archived_at"):
            continue
        name_key = str(machine.get("name") or "").casefold()
        active_name_ids.setdefault(name_key, []).append(
            str(machine.get("id") or "")
        )
    duplicate_active_machine_name_ids = sorted({
        machine_id
        for machine_ids in active_name_ids.values()
        if len(machine_ids) > 1
        for machine_id in machine_ids
    })

    association_keys: set[tuple[str, str]] = set()
    duplicate_machine_association_keys: set[str] = set()
    orphan_machine_association_asset_keys: set[str] = set()
    orphan_machine_association_machine_keys: set[str] = set()
    for association in machine_associations:
        asset_id = str(association.get("asset_id") or "")
        machine_id = str(association.get("machine_id") or "")
        display_key = f"{asset_id}/{machine_id}"
        key = (asset_id, machine_id)
        if key in association_keys:
            duplicate_machine_association_keys.add(display_key)
        association_keys.add(key)
        if asset_id not in asset_by_id:
            orphan_machine_association_asset_keys.add(display_key)
        if machine_id not in machine_by_id:
            orphan_machine_association_machine_keys.add(display_key)

    orphan_asset_prepared_machine_ids = sorted(
        str(asset.get("id") or "")
        for asset in assets
        if asset.get("prepared_machine_id")
        and str(asset.get("prepared_machine_id")) not in machine_by_id
    )
    orphan_revision_prepared_machine_ids = sorted(
        str(revision.get("id") or "")
        for revision in revisions
        if revision.get("prepared_machine_id")
        and str(revision.get("prepared_machine_id")) not in machine_by_id
    )
    prepared_machine_mirror_mismatch_asset_ids: list[str] = []
    if uses_revisions:
        for asset in assets:
            asset_id = str(asset.get("id") or "")
            current_revision_id = str(asset.get("current_revision_id") or "")
            revision = revision_by_id.get(current_revision_id)
            if not revision or str(revision.get("asset_id") or "") != asset_id:
                continue
            asset_target = str(asset.get("prepared_machine_id") or "")
            revision_target = str(revision.get("prepared_machine_id") or "")
            if asset_target != revision_target:
                prepared_machine_mirror_mismatch_asset_ids.append(asset_id)

    expected_security_columns: dict[str, set[str]] = {}
    if schema_version >= 13:
        expected_security_columns["useraccount"] = {
            "id", "username", "username_normalized", "display_name", "password_hash",
            "enabled", "password_policy_version", "password_change_required",
            "created_at", "updated_at", "last_login_at",
        }
    if schema_version >= 14:
        expected_security_columns["browsersession"] = {
            "id", "user_id", "secret_digest", "created_at", "last_seen_at",
            "idle_expires_at", "absolute_expires_at", "idle_ttl_seconds",
            "revoked_at", "client_address", "user_agent",
        }
    if schema_version >= 15:
        expected_security_columns.setdefault("useraccount", set()).add("role")
    if schema_version >= 16:
        expected_security_columns.setdefault("browsersession", set()).add(
            "reauthenticated_at"
        )
        expected_security_columns["auditevent"] = {
            "id", "occurred_at", "correlation_id", "actor_user_id",
            "actor_username", "actor_role", "action", "result", "object_type",
            "object_id", "method", "route", "permission", "status_code",
            "source_address", "details_json",
        }
        expected_security_columns["recoverymarker"] = {
            "id", "kind", "created_at", "details_json", "processed_at",
        }
    missing_security_tables = sorted(set(expected_security_columns) - tables)
    missing_security_columns = sorted(
        f"{table}.{column}"
        for table, columns in expected_security_columns.items()
        if table in tables
        for column in columns - security_table_columns[table]
    )

    valid_roles = {"administrator", "member", "viewer"}
    user_ids = {str(user.get("id") or "") for user in users}
    invalid_account_ids = sorted(
        str(user.get("id") or "") for user in users
        if not _canonical_uuid(user.get("id"))
    )
    invalid_account_username_ids: list[str] = []
    normalized_usernames: dict[str, list[str]] = {}
    for user in users:
        user_id = str(user.get("id") or "")
        username = str(user.get("username") or "")
        normalized = str(user.get("username_normalized") or "")
        expected = unicodedata.normalize("NFKC", username).strip().casefold()
        if not expected or len(expected) > 256 or normalized != expected:
            invalid_account_username_ids.append(user_id)
        normalized_usernames.setdefault(normalized, []).append(user_id)
    duplicate_account_username_ids = sorted({
        user_id
        for normalized, ids in normalized_usernames.items()
        if normalized and len(ids) > 1
        for user_id in ids
    })
    invalid_account_role_ids = sorted(
        str(user.get("id") or "") for user in users
        if schema_version >= 15 and str(user.get("role") or "") not in valid_roles
    )
    invalid_account_state_ids = sorted(
        str(user.get("id") or "") for user in users
        if user.get("enabled") not in {0, 1}
        or user.get("password_change_required") not in {0, 1}
        or not isinstance(user.get("password_policy_version"), int)
        or int(user.get("password_policy_version") or 0) < 1
        or not str(user.get("display_name") or "").strip()
        or not str(user.get("password_hash") or "").startswith("$argon2id$v=19$")
        or not _valid_iso_timestamp(user.get("created_at"))
        or not _valid_iso_timestamp(user.get("updated_at"))
        or (
            user.get("last_login_at") is not None
            and not _valid_iso_timestamp(user.get("last_login_at"))
        )
    )
    enabled_administrator_count = sum(
        1 for user in users
        if user.get("enabled") == 1
        and (
            str(user.get("role") or "") == "administrator"
            if schema_version >= 15 else True
        )
    )
    missing_enabled_administrator = bool(
        schema_version >= 15 and enabled_administrator_count == 0
    )

    digest_pattern = re.compile(r"^[0-9a-f]{64}$")
    session_digests: dict[str, list[str]] = {}
    orphan_session_ids: list[str] = []
    invalid_session_ids: list[str] = []
    invalid_session_digest_ids: list[str] = []
    invalid_session_time_ids: list[str] = []
    for browser_session in browser_sessions:
        session_id = str(browser_session.get("id") or "")
        if not _canonical_uuid(session_id):
            invalid_session_ids.append(session_id)
        if str(browser_session.get("user_id") or "") not in user_ids:
            orphan_session_ids.append(session_id)
        digest = str(browser_session.get("secret_digest") or "")
        if not digest_pattern.fullmatch(digest):
            invalid_session_digest_ids.append(session_id)
        session_digests.setdefault(digest, []).append(session_id)
        time_fields = [
            browser_session.get("created_at"),
            browser_session.get("last_seen_at"),
            browser_session.get("idle_expires_at"),
            browser_session.get("absolute_expires_at"),
        ]
        if schema_version >= 16:
            time_fields.append(browser_session.get("reauthenticated_at"))
        valid_times = all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in time_fields
        )
        if valid_times:
            created, last_seen, idle_expires, absolute_expires = time_fields[:4]
            reauthenticated = (
                browser_session.get("reauthenticated_at", created)
                if schema_version >= 16 else created
            )
            valid_times = (
                created <= last_seen < idle_expires <= absolute_expires
                and created <= reauthenticated < absolute_expires
                and isinstance(browser_session.get("idle_ttl_seconds"), int)
                and int(browser_session.get("idle_ttl_seconds") or 0) > 0
                and (
                    browser_session.get("revoked_at") is None
                    or (
                        isinstance(browser_session.get("revoked_at"), int)
                        and browser_session.get("revoked_at") >= created
                    )
                )
            )
        if not valid_times:
            invalid_session_time_ids.append(session_id)
    duplicate_session_digest_ids = sorted({
        session_id
        for digest, ids in session_digests.items()
        if digest and len(ids) > 1
        for session_id in ids
    })

    action_pattern = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
    invalid_audit_event_ids: list[str] = []
    orphan_audit_actor_event_ids: list[str] = []
    for event in audit_events:
        event_id = str(event.get("id") or "")
        actor_id = event.get("actor_user_id")
        if actor_id is not None and str(actor_id) not in user_ids:
            orphan_audit_actor_event_ids.append(event_id)
        actor_fields_valid = (
            actor_id is None
            and event.get("actor_username") is None
            and event.get("actor_role") is None
        ) or (
            actor_id is not None
            and bool(str(event.get("actor_username") or ""))
            and str(event.get("actor_role") or "") in valid_roles
        )
        optional_lengths = (
            ("object_type", 64), ("object_id", 128), ("method", 16),
            ("route", 256), ("permission", 128), ("source_address", 128),
        )
        status_code = event.get("status_code")
        if (
            not _canonical_uuid(event_id)
            or not _canonical_uuid(event.get("correlation_id"))
            or not _valid_iso_timestamp(event.get("occurred_at"))
            or not action_pattern.fullmatch(str(event.get("action") or ""))
            or str(event.get("result") or "") not in {"success", "denied", "failure"}
            or not actor_fields_valid
            or any(
                event.get(field) is not None and len(str(event.get(field))) > maximum
                for field, maximum in optional_lengths
            )
            or (
                status_code is not None
                and (
                    not isinstance(status_code, int)
                    or isinstance(status_code, bool)
                    or status_code < 100
                    or status_code > 599
                )
            )
            or not _valid_audit_details(event.get("details_json"))
        ):
            invalid_audit_event_ids.append(event_id)

    invalid_recovery_marker_ids: list[str] = []
    pending_recovery_marker_count = 0
    for marker in recovery_markers:
        marker_id = str(marker.get("id") or "")
        processed_at = marker.get("processed_at")
        if processed_at is None:
            pending_recovery_marker_count += 1
        if (
            not _canonical_uuid(marker_id)
            or str(marker.get("kind") or "") not in {
                "raw_restore", "administrator_recovery"
            }
            or not _valid_iso_timestamp(marker.get("created_at"))
            or (processed_at is not None and not _valid_iso_timestamp(processed_at))
            or not _valid_recovery_details(
                str(marker.get("kind") or ""), marker.get("details_json"), user_ids
            )
        ):
            invalid_recovery_marker_ids.append(marker_id)

    security_critical_lists = (
        missing_security_tables,
        missing_security_columns,
        invalid_account_ids,
        invalid_account_username_ids,
        duplicate_account_username_ids,
        invalid_account_role_ids,
        invalid_account_state_ids,
        orphan_session_ids,
        invalid_session_ids,
        invalid_session_digest_ids,
        duplicate_session_digest_ids,
        invalid_session_time_ids,
        invalid_audit_event_ids,
        orphan_audit_actor_event_ids,
        invalid_recovery_marker_ids,
    )

    project_critical_lists = (
        missing_project_tables,
        orphan_project_membership_keys,
        orphan_asset_membership_keys,
        orphan_relationship_project_ids,
        orphan_relationship_source_asset_ids,
        orphan_relationship_target_asset_ids,
        relationship_nonmember_source_ids,
        relationship_nonmember_target_ids,
        self_relationship_ids,
        invalid_relationship_kind_ids,
        duplicate_relationship_ids,
    )
    machine_critical_lists = (
        missing_machine_tables,
        missing_machine_reference_columns,
        invalid_machine_category_ids,
        duplicate_active_machine_name_ids,
        sorted(orphan_machine_association_asset_keys),
        sorted(orphan_machine_association_machine_keys),
        sorted(duplicate_machine_association_keys),
        orphan_asset_prepared_machine_ids,
        orphan_revision_prepared_machine_ids,
        prepared_machine_mirror_mismatch_asset_ids,
    )
    critical_lists = (
        missing_managed,
        missing_managed_revision_ids,
        revision_digest_mismatch_ids,
        revision_size_mismatch_ids,
        related_missing,
        related_orphan_asset_ids,
        related_revision_mismatch_ids,
        revision_orphan_asset_ids,
        missing_current_revision_asset_ids,
        invalid_current_revision_asset_ids,
        prepared_pointer_missing,
        invalid_revision_prepared_pointer_ids,
        malformed_purge_operation_ids,
        unknown_quarantine_paths,
        *project_critical_lists,
        *machine_critical_lists,
        *security_critical_lists,
    )
    critical_count = sum(len(items) for items in critical_lists)
    critical_count += int(missing_enabled_administrator)
    result = {
        "status": "ok" if critical_count == 0 else "inconsistent",
        "critical_finding_count": critical_count,
        "active_asset_count": sum(1 for row in assets if not row.get("deleted_at")),
        "trashed_asset_count": sum(1 for row in assets if row.get("deleted_at")),
        "revision_count": len(revisions),
        "managed_primary_present": managed_present,
        "missing_managed_asset_ids": sorted(missing_managed),
        "external_primary_records": sorted(external, key=lambda item: item["asset_id"]),
        "external_state_counts": external_counts,
        "managed_revision_present": managed_revision_present,
        "quarantined_managed_revision_ids": sorted(quarantined_managed_revision_ids),
        "missing_managed_revision_ids": sorted(missing_managed_revision_ids),
        "revision_digest_mismatch_ids": sorted(revision_digest_mismatch_ids),
        "revision_size_mismatch_ids": sorted(revision_size_mismatch_ids),
        "related_file_present": len(asset_files) - len(related_missing),
        "quarantined_related_file_ids": sorted(related_quarantined),
        "missing_related_file_ids": sorted(related_missing),
        "related_file_orphan_asset_ids": sorted(related_orphan_asset_ids),
        "related_file_revision_mismatch_ids": sorted(related_revision_mismatch_ids),
        "revision_orphan_asset_ids": revision_orphan_asset_ids,
        "missing_current_revision_asset_ids": sorted(missing_current_revision_asset_ids),
        "invalid_current_revision_asset_ids": sorted(invalid_current_revision_asset_ids),
        "missing_prepared_pointer_asset_ids": sorted(prepared_pointer_missing),
        "invalid_revision_prepared_pointer_ids": sorted(invalid_revision_prepared_pointer_ids),
        "missing_derived_thumbnail_paths": missing_thumbnail_paths,
        "purge_operation_count": len(purge_operations),
        "purge_operation_status_counts": dict(sorted(purge_status_counts.items())),
        "known_quarantine_files": sorted(known_quarantine_paths),
        "unknown_quarantine_files": unknown_quarantine_paths,
        "malformed_purge_operation_ids": sorted(malformed_purge_operation_ids),
        "unreferenced_storage_files": orphans,
        "derived_thumbnail_files": sum(1 for name in storage if name.startswith("thumbs/")),
    }
    project_domain_present = bool(
        schema_version >= 9
        or {"project", "projectmembership", "projectrelationship"} & tables
    )
    if project_domain_present:
        result.update({
            "active_project_count": sum(
                1 for row in projects if not row.get("deleted_at")
            ),
            "trashed_project_count": sum(
                1 for row in projects if row.get("deleted_at")
            ),
            "project_membership_count": len(project_memberships),
            "project_relationship_count": len(project_relationships),
            "missing_project_tables": missing_project_tables,
            "orphan_project_membership_keys": orphan_project_membership_keys,
            "orphan_asset_membership_keys": orphan_asset_membership_keys,
            "orphan_relationship_project_ids": sorted(
                orphan_relationship_project_ids
            ),
            "orphan_relationship_source_asset_ids": sorted(
                orphan_relationship_source_asset_ids
            ),
            "orphan_relationship_target_asset_ids": sorted(
                orphan_relationship_target_asset_ids
            ),
            "relationship_nonmember_source_ids": sorted(
                relationship_nonmember_source_ids
            ),
            "relationship_nonmember_target_ids": sorted(
                relationship_nonmember_target_ids
            ),
            "self_relationship_ids": sorted(self_relationship_ids),
            "invalid_relationship_kind_ids": sorted(
                invalid_relationship_kind_ids
            ),
            "duplicate_relationship_ids": sorted(duplicate_relationship_ids),
        })
    machine_domain_present = bool(
        schema_version >= 11
        or {"machineprofile", "artifactmachine"} & tables
        or "prepared_machine_id" in asset_columns
        or "prepared_machine_id" in revision_columns
    )
    if machine_domain_present:
        result.update({
            "active_machine_count": sum(
                1 for machine in machines if not machine.get("archived_at")
            ),
            "archived_machine_count": sum(
                1 for machine in machines if machine.get("archived_at")
            ),
            "machine_association_count": len(machine_associations),
            "current_prepared_machine_count": sum(
                1 for asset in assets if asset.get("prepared_machine_id")
            ),
            "revision_prepared_machine_count": sum(
                1 for revision in revisions
                if revision.get("prepared_machine_id")
            ),
            "missing_machine_tables": missing_machine_tables,
            "missing_machine_reference_columns": sorted(
                missing_machine_reference_columns
            ),
            "invalid_machine_category_ids": invalid_machine_category_ids,
            "duplicate_active_machine_name_ids": (
                duplicate_active_machine_name_ids
            ),
            "orphan_machine_association_asset_keys": sorted(
                orphan_machine_association_asset_keys
            ),
            "orphan_machine_association_machine_keys": sorted(
                orphan_machine_association_machine_keys
            ),
            "duplicate_machine_association_keys": sorted(
                duplicate_machine_association_keys
            ),
            "orphan_asset_prepared_machine_ids": (
                orphan_asset_prepared_machine_ids
            ),
            "orphan_revision_prepared_machine_ids": (
                orphan_revision_prepared_machine_ids
            ),
            "prepared_machine_mirror_mismatch_asset_ids": sorted(
                prepared_machine_mirror_mismatch_asset_ids
            ),
        })
    security_domain_present = bool(
        schema_version >= 13
        or {"useraccount", "browsersession", "auditevent", "recoverymarker"} & tables
    )
    if security_domain_present:
        result.update({
            "account_count": len(users),
            "enabled_administrator_count": enabled_administrator_count,
            "browser_session_count": len(browser_sessions),
            "audit_event_count": len(audit_events),
            "recovery_marker_count": len(recovery_markers),
            "pending_recovery_marker_count": pending_recovery_marker_count,
            "missing_security_tables": missing_security_tables,
            "missing_security_columns": missing_security_columns,
            "invalid_account_ids": invalid_account_ids,
            "invalid_account_username_ids": sorted(invalid_account_username_ids),
            "duplicate_account_username_ids": duplicate_account_username_ids,
            "invalid_account_role_ids": invalid_account_role_ids,
            "invalid_account_state_ids": invalid_account_state_ids,
            "missing_enabled_administrator": missing_enabled_administrator,
            "orphan_session_ids": sorted(orphan_session_ids),
            "invalid_session_ids": sorted(invalid_session_ids),
            "invalid_session_digest_ids": sorted(invalid_session_digest_ids),
            "duplicate_session_digest_ids": duplicate_session_digest_ids,
            "invalid_session_time_ids": sorted(invalid_session_time_ids),
            "invalid_audit_event_ids": sorted(invalid_audit_event_ids),
            "orphan_audit_actor_event_ids": sorted(orphan_audit_actor_event_ids),
            "invalid_recovery_marker_ids": sorted(invalid_recovery_marker_ids),
        })
    return result


def _component_metadata(path: Path, members: list[dict]) -> dict:
    return {
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "file_count": len(members),
        "expanded_bytes": sum(int(item["size"]) for item in members),
        "files": members,
    }


def add_path_to_tar(archive: tarfile.TarFile, source: Path, name: str, mode: int = 0o600) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = source.stat().st_size
    info.mode = mode
    info.mtime = int(datetime.now(timezone.utc).timestamp())
    with source.open("rb") as handle:
        archive.addfile(info, handle)


def add_bytes_to_tar(archive: tarfile.TarFile, data: bytes, name: str, mode: int = 0o600) -> None:
    import io

    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mode = mode
    info.mtime = int(datetime.now(timezone.utc).timestamp())
    archive.addfile(info, io.BytesIO(data))


def create_backup(
    database_tar: Path,
    storage_tar: Path,
    output: Path,
    release: str,
    source_revision: str,
    config_env: Optional[Path] = None,
    overwrite: bool = False,
    compose_project: str = "unknown",
    compose_manifest: str = "unknown",
    database_source: str = "unknown",
    storage_source: str = "unknown",
    administrator_recovery_snapshot: bool = False,
) -> dict:
    if output.exists() and not overwrite:
        raise RecoveryError(f"Backup already exists: {output}")
    database_members = validate_component_tar(database_tar)
    storage_members = validate_component_tar(storage_tar)
    with tempfile.TemporaryDirectory(prefix="makersvault-backup-") as temporary:
        database = extract_database_component(database_tar, Path(temporary) / "database")
        summary = database_summary(database)
        if summary["quick_check"] != ["ok"]:
            raise RecoveryError("SQLite quick_check did not return ok")
        audit = consistency_audit(
            database,
            storage_members,
        )
        recoverable_identity_state = bool(
            administrator_recovery_snapshot
            and audit.get("missing_enabled_administrator") is True
            and audit.get("critical_finding_count") == 1
        )
        if audit["status"] != "ok" and not recoverable_identity_state:
            raise RecoveryError("Matched database and storage snapshot is inconsistent")
        components = {
            "database.tar": _component_metadata(database_tar, database_members),
            "storage.tar": _component_metadata(storage_tar, storage_members),
        }
        checksum_lines = [
            f"{components[name]['sha256']}  {name}"
            for name in COMPONENT_NAMES
        ]
        if config_env:
            if not config_env.is_file():
                raise RecoveryError(f"Configuration file does not exist: {config_env}")
            components["config.env"] = {
                "sha256": sha256_file(config_env),
                "bytes": config_env.stat().st_size,
            }
            checksum_lines.append(f"{components['config.env']['sha256']}  config.env")
        manifest = {
            "format": BACKUP_FORMAT,
            "format_version": BACKUP_FORMAT_VERSION,
            "recovery_contract_version": RECOVERY_CONTRACT_VERSION,
            "created_at": utc_timestamp(),
            "release": release,
            "source_revision": source_revision,
            "deployment": {
                "compose_project": compose_project,
                "compose_manifest": compose_manifest,
                "database": {
                    "source": database_source,
                    "container_path": "/app/data",
                },
                "storage": {
                    "source": storage_source,
                    "container_path": "/app/storage",
                },
            },
            "components": components,
            "database": summary,
            "consistency": audit,
            "external_content_included": False,
        }
        if administrator_recovery_snapshot:
            manifest["recovery_purpose"] = "administrator_recovery"
        manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        checksum_lines.append(
            f"{hashlib.sha256(manifest_bytes).hexdigest()}  manifest.json"
        )
        checksums_bytes = ("\n".join(checksum_lines) + "\n").encode()
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
        os.close(fd)
        temporary_output = Path(temporary_name)
        try:
            with tarfile.open(temporary_output, "w:gz") as archive:
                add_bytes_to_tar(archive, manifest_bytes, "manifest.json", 0o600)
                add_bytes_to_tar(archive, checksums_bytes, "checksums.sha256", 0o600)
                add_path_to_tar(archive, database_tar, "database.tar", 0o600)
                add_path_to_tar(archive, storage_tar, "storage.tar", 0o600)
                if config_env:
                    add_path_to_tar(archive, config_env, "config.env", 0o600)
            os.chmod(temporary_output, stat.S_IRUSR | stat.S_IWUSR)
            temporary_output.replace(output)
        finally:
            temporary_output.unlink(missing_ok=True)
    return manifest


def extract_outer_archive(archive_path: Path, destination: Path) -> set[str]:
    destination.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    try:
        archive = tarfile.open(archive_path, "r:gz")
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise RecoveryError("Backup is not a readable gzip tar archive") from exc
    try:
        with archive:
            for member in archive.getmembers():
                name = normalized_member_name(member.name)
                if not name or name in seen:
                    raise RecoveryError("Backup contains an empty or duplicate member")
                if "/" in name or not member.isfile():
                    raise RecoveryError(f"Backup contains an unexpected member: {name}")
                if name not in set(COMPONENT_NAMES + OPTIONAL_NAMES + METADATA_NAMES):
                    raise RecoveryError(f"Backup contains an unknown member: {name}")
                seen.add(name)
                extract_regular_member(archive, member, destination)
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise RecoveryError("Backup archive is unreadable") from exc
    required = set(COMPONENT_NAMES + METADATA_NAMES)
    if not required.issubset(seen):
        raise RecoveryError("Backup is missing one or more required members")
    return seen


def parse_checksums(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, separator, name = line.partition("  ")
        if not separator or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise RecoveryError("Backup checksum inventory is malformed")
        if name in checksums:
            raise RecoveryError("Backup checksum inventory contains a duplicate")
        checksums[name] = digest
    return checksums


def verify_extracted_backup(
    directory: Path,
    seen: set[str],
    allow_administrator_recovery: bool = False,
) -> dict:
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecoveryError("Backup manifest is not valid JSON") from exc
    if manifest.get("format") != BACKUP_FORMAT or manifest.get("format_version") != BACKUP_FORMAT_VERSION:
        raise RecoveryError("Backup format or version is unsupported")
    recovery_purpose = manifest.get("recovery_purpose")
    if recovery_purpose not in {None, "administrator_recovery"}:
        raise RecoveryError("Backup recovery purpose is unsupported")
    recovery_contract = manifest.get("recovery_contract_version")
    if recovery_contract is not None and (
        not isinstance(recovery_contract, int)
        or isinstance(recovery_contract, bool)
        or recovery_contract not in SUPPORTED_RECOVERY_CONTRACT_VERSIONS
    ):
        raise RecoveryError("Backup recovery contract is unsupported")
    checksums = parse_checksums(directory / "checksums.sha256")
    expected_components = set(COMPONENT_NAMES)
    if "config.env" in seen:
        expected_components.add("config.env")
    expected_checksums = expected_components | {"manifest.json"}
    if set(checksums) != expected_checksums:
        raise RecoveryError("Backup checksum inventory does not match its components")
    if checksums["manifest.json"] != sha256_file(directory / "manifest.json"):
        raise RecoveryError("Backup manifest checksum failed")
    manifest_components = manifest.get("components")
    if not isinstance(manifest_components, dict) or set(manifest_components) != expected_components:
        raise RecoveryError("Backup manifest component inventory does not match its archive")
    for name in sorted(expected_components):
        actual = sha256_file(directory / name)
        if checksums[name] != actual or manifest_components[name].get("sha256") != actual:
            raise RecoveryError(f"Backup component checksum failed: {name}")
    database_members = validate_component_tar(directory / "database.tar")
    storage_members = validate_component_tar(directory / "storage.tar")
    with tempfile.TemporaryDirectory(prefix="makersvault-verify-") as temporary:
        database = extract_database_component(directory / "database.tar", Path(temporary) / "database")
        summary = database_summary(database)
        audit = consistency_audit(database, storage_members)
    if summary["quick_check"] != ["ok"]:
        raise RecoveryError("Restored SQLite quick_check did not return ok")

    def report_matches(recorded: object, actual: object, legacy: bool) -> bool:
        if not legacy:
            return recorded == actual
        if isinstance(recorded, dict) and isinstance(actual, dict):
            return all(
                key in actual and report_matches(value, actual[key], legacy)
                for key, value in recorded.items()
            )
        if isinstance(recorded, list) and isinstance(actual, list):
            return recorded == actual
        return recorded == actual

    compatible_older_contract = recovery_contract in {None, 2, 3, 4}
    if not report_matches(
        manifest.get("database"),
        summary,
        compatible_older_contract,
    ):
        raise RecoveryError("Backup database summary does not match its manifest")
    if not report_matches(
        manifest.get("consistency"),
        audit,
        compatible_older_contract,
    ):
        raise RecoveryError("Backup consistency report does not match its contents")
    recoverable_identity_state = bool(
        allow_administrator_recovery
        and recovery_purpose == "administrator_recovery"
        and audit.get("missing_enabled_administrator") is True
        and audit.get("critical_finding_count") == 1
    )
    if audit["status"] != "ok" and not recoverable_identity_state:
        raise RecoveryError("Backup contains an inconsistent database/storage snapshot")
    if manifest_components["database.tar"].get("file_count") != len(database_members):
        raise RecoveryError("Database component file count does not match its manifest")
    if manifest_components["storage.tar"].get("file_count") != len(storage_members):
        raise RecoveryError("Storage component file count does not match its manifest")
    if manifest_components["database.tar"].get("files") != database_members:
        raise RecoveryError("Database file inventory does not match its manifest")
    if manifest_components["storage.tar"].get("files") != storage_members:
        raise RecoveryError("Storage file inventory does not match its manifest")
    return manifest


def verify_backup(
    archive_path: Path,
    allow_administrator_recovery: bool = False,
) -> dict:
    if not archive_path.is_file():
        raise RecoveryError(f"Backup does not exist: {archive_path}")
    with tempfile.TemporaryDirectory(prefix="makersvault-verify-") as temporary:
        directory = Path(temporary)
        seen = extract_outer_archive(archive_path, directory)
        return verify_extracted_backup(
            directory,
            seen,
            allow_administrator_recovery=allow_administrator_recovery,
        )


def extract_backup(archive_path: Path, output_dir: Path) -> dict:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RecoveryError("Backup extraction target must be empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    seen = extract_outer_archive(archive_path, output_dir)
    try:
        return verify_extracted_backup(output_dir, seen)
    except Exception:
        for child in output_dir.iterdir():
            child.unlink(missing_ok=True)
        raise


def storage_files_from_directory(storage_dir: Path) -> list[str]:
    files: list[str] = []
    for path in storage_dir.rglob("*"):
        if path.is_symlink():
            raise RecoveryError(f"Storage contains a symbolic link: {path}")
        if path.is_file():
            files.append(path.relative_to(storage_dir).as_posix())
    return sorted(files)


def audit_live_paths(
    database: Path,
    storage_dir: Path,
    external_container_root: Optional[Path] = None,
    external_host_root: Optional[Path] = None,
) -> dict:
    summary = database_summary(database)
    audit = consistency_audit(
        database,
        storage_files_from_directory(storage_dir),
        external_container_root,
        external_host_root,
    )
    return {"database": summary, "consistency": audit}


def audit_component_tars(database_tar: Path, storage_tar: Path) -> dict:
    """Audit a matched database/storage snapshot without running an app image."""
    storage_members = validate_component_tar(storage_tar)
    with tempfile.TemporaryDirectory(prefix="makersvault-audit-") as temporary:
        database = extract_database_component(database_tar, Path(temporary) / "database")
        summary = database_summary(database)
        audit = consistency_audit(database, storage_members)
    return {"database": summary, "consistency": audit}


def verify_restored_components(
    archive_path: Path,
    database_tar: Path,
    storage_tar: Path,
) -> dict:
    """Prove a live post-restore snapshot matches every archived file byte."""
    manifest = verify_backup(archive_path)
    live_members = {
        "database.tar": validate_component_tar(database_tar),
        "storage.tar": validate_component_tar(storage_tar),
    }
    for name, members in live_members.items():
        if manifest["components"][name].get("files") != members:
            raise RecoveryError(f"Restored {name} content does not match the backup")
    result = audit_component_tars(database_tar, storage_tar)
    return {"matches_backup": True, **result}


def print_json(value: dict) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create, verify, extract, or audit a MakersVault backup")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--database-tar", type=Path, required=True)
    create.add_argument("--storage-tar", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--release", required=True)
    create.add_argument("--source-revision", required=True)
    create.add_argument("--config-env", type=Path)
    create.add_argument("--overwrite", action="store_true")
    create.add_argument("--compose-project", required=True)
    create.add_argument("--compose-manifest", required=True)
    create.add_argument("--database-source", required=True)
    create.add_argument("--storage-source", required=True)
    create.add_argument("--administrator-recovery-snapshot", action="store_true")

    verify = subparsers.add_parser("verify")
    verify.add_argument("--archive", type=Path, required=True)
    verify.add_argument("--administrator-recovery-snapshot", action="store_true")

    extract = subparsers.add_parser("extract")
    extract.add_argument("--archive", type=Path, required=True)
    extract.add_argument("--output-dir", type=Path, required=True)

    audit = subparsers.add_parser("audit")
    audit.add_argument("--database", type=Path, required=True)
    audit.add_argument("--storage-dir", type=Path, required=True)
    audit.add_argument("--external-container-root", type=Path)
    audit.add_argument("--external-host-root", type=Path)

    audit_components = subparsers.add_parser("audit-components")
    audit_components.add_argument("--database-tar", type=Path, required=True)
    audit_components.add_argument("--storage-tar", type=Path, required=True)

    verify_restored = subparsers.add_parser("verify-restored")
    verify_restored.add_argument("--archive", type=Path, required=True)
    verify_restored.add_argument("--database-tar", type=Path, required=True)
    verify_restored.add_argument("--storage-tar", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "create":
            result = create_backup(
                args.database_tar,
                args.storage_tar,
                args.output,
                args.release,
                args.source_revision,
                args.config_env,
                args.overwrite,
                args.compose_project,
                args.compose_manifest,
                args.database_source,
                args.storage_source,
                args.administrator_recovery_snapshot,
            )
        elif args.command == "verify":
            result = verify_backup(
                args.archive,
                allow_administrator_recovery=args.administrator_recovery_snapshot,
            )
        elif args.command == "extract":
            result = extract_backup(args.archive, args.output_dir)
        elif args.command == "audit":
            result = audit_live_paths(
                args.database,
                args.storage_dir,
                args.external_container_root,
                args.external_host_root,
            )
        elif args.command == "audit-components":
            result = audit_component_tars(args.database_tar, args.storage_tar)
        else:
            result = verify_restored_components(
                args.archive,
                args.database_tar,
                args.storage_tar,
            )
        print_json(result)
        if args.command in {"audit", "audit-components", "verify-restored"} and (
            result["database"]["quick_check"] != ["ok"]
            or result["consistency"]["status"] != "ok"
        ):
            return 3
        return 0
    except RecoveryError as exc:
        print(f"Recovery error: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
