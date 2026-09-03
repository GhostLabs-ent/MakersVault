import io
import fcntl
import hashlib
import json
import os
import sqlite3
import tarfile
from pathlib import Path

import pytest

from recovery import (
    RecoveryError,
    audit_component_tars,
    audit_live_paths,
    create_backup,
    extract_backup,
    validate_component_tar,
    verify_backup,
    verify_restored_components,
)
from recovery_mutation import (
    RecoveryMutationError,
    mark_restored_database,
    recover_existing_administrator,
)


MACHINE_REPORT_KEYS = (
    "active_machine_count",
    "archived_machine_count",
    "machine_association_count",
    "current_prepared_machine_count",
    "revision_prepared_machine_count",
    "missing_machine_tables",
    "missing_machine_reference_columns",
    "invalid_machine_category_ids",
    "duplicate_active_machine_name_ids",
    "orphan_machine_association_asset_keys",
    "orphan_machine_association_machine_keys",
    "duplicate_machine_association_keys",
    "orphan_asset_prepared_machine_ids",
    "orphan_revision_prepared_machine_ids",
    "prepared_machine_mirror_mismatch_asset_ids",
)

SECURITY_REPORT_KEYS = (
    "missing_security_tables",
    "missing_security_columns",
    "invalid_account_ids",
    "invalid_account_username_ids",
    "duplicate_account_username_ids",
    "invalid_account_role_ids",
    "invalid_account_state_ids",
    "orphan_session_ids",
    "invalid_session_ids",
    "invalid_session_digest_ids",
    "duplicate_session_digest_ids",
    "invalid_session_time_ids",
    "invalid_audit_event_ids",
    "orphan_audit_actor_event_ids",
    "invalid_recovery_marker_ids",
)


def make_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE folder (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                parent_id TEXT
            );
            CREATE TABLE asset (
                id TEXT PRIMARY KEY,
                name TEXT,
                filename TEXT NOT NULL,
                mime TEXT NOT NULL,
                size INTEGER NOT NULL,
                tags_json TEXT NOT NULL,
                title TEXT,
                notes TEXT,
                creator TEXT,
                collection TEXT,
                folder_id TEXT,
                source_path TEXT,
                storage_path TEXT,
                supporting_file_count INTEGER NOT NULL DEFAULT 0,
                prepared_file_id TEXT,
                prepared_metadata_json TEXT,
                preview_status TEXT NOT NULL DEFAULT 'pending',
                preview_reason TEXT,
                preview_attempts INTEGER NOT NULL DEFAULT 0,
                preview_policy_version INTEGER NOT NULL DEFAULT 1,
                preview_updated_at TEXT,
                preview_source TEXT
            );
            CREATE TABLE assetfile (
                id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                mime TEXT NOT NULL,
                size INTEGER NOT NULL,
                role TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                metadata_json TEXT
            );
            CREATE TABLE appconfig (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE mountscan (
                id TEXT PRIMARY KEY,
                trigger TEXT NOT NULL,
                status TEXT NOT NULL,
                mode TEXT NOT NULL,
                root_path TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                imported INTEGER NOT NULL,
                skipped INTEGER NOT NULL,
                failed INTEGER NOT NULL,
                failure_details_json TEXT NOT NULL,
                failure_details_omitted INTEGER NOT NULL
            );
            CREATE TABLE schema_migration (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO schema_migration(version, name) VALUES
                (1, 'initial_schema'),
                (2, 'nested_folders_and_mount_sources'),
                (3, 'asset_metadata_and_bundles'),
                (4, 'persistent_preview_state'),
                (5, 'persistent_mount_scan_records');
            INSERT INTO folder(id, name, tags_json) VALUES ('folder', 'Fixtures', '[]');
            INSERT INTO asset(
                id, name, filename, mime, size, tags_json, folder_id,
                storage_path, supporting_file_count, prepared_file_id,
                prepared_metadata_json, preview_status
            ) VALUES (
                'managed', 'Managed', 'managed.stl', 'model/stl', 7, '[]', 'folder',
                'Fixtures/Managed/managed.stl', 1, 'prepared',
                '{"printer":"P1S"}', 'ready'
            );
            INSERT INTO asset(
                id, name, filename, mime, size, tags_json, source_path,
                storage_path, preview_status
            ) VALUES (
                'external', 'External', 'external.stl', 'model/stl', 8, '[]',
                '/imports/external.stl', 'Unassigned/External/external.stl', 'pending'
            );
            INSERT INTO assetfile(
                id, asset_id, filename, mime, size, role, storage_path, metadata_json
            ) VALUES
                ('support', 'managed', 'assembly.pdf', 'application/pdf', 7,
                 'supporting', 'bundles/managed/support/assembly.pdf', NULL),
                ('prepared', 'managed', 'prepared.gcode', 'text/plain', 8,
                 'prepared', 'bundles/managed/prepared/prepared.gcode', '{"printer":"P1S"}');
            INSERT INTO appconfig(key, value) VALUES ('mount_import_copy', '0');
            INSERT INTO mountscan(
                id, trigger, status, mode, root_path, started_at, finished_at,
                imported, skipped, failed, failure_details_json, failure_details_omitted
            ) VALUES (
                'scan', 'manual', 'completed', 'index_in_place', '/imports',
                '2026-08-21T00:00:00Z', '2026-08-21T00:00:01Z', 1, 0, 0, '[]', 0
            );
            """
        )
        connection.commit()
    finally:
        connection.close()


def make_schema8_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE asset (
                id TEXT PRIMARY KEY, name TEXT, filename TEXT NOT NULL, mime TEXT NOT NULL,
                size INTEGER NOT NULL, source_path TEXT, storage_path TEXT,
                prepared_file_id TEXT, current_revision_id TEXT, current_thumb_path TEXT,
                deleted_at TEXT
            );
            CREATE TABLE artifactrevision (
                id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, revision_number INTEGER NOT NULL,
                filename TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT,
                storage_path TEXT, source_path TEXT, prepared_file_id TEXT,
                preview_thumb_path TEXT
            );
            CREATE TABLE assetfile (
                id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, filename TEXT NOT NULL,
                role TEXT NOT NULL, storage_path TEXT NOT NULL, revision_id TEXT
            );
            CREATE TABLE trashpurgeoperation (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, asset_ids_json TEXT NOT NULL,
                paths_json TEXT NOT NULL, quarantine_path TEXT
            );
            CREATE TABLE contenthashjob (id TEXT PRIMARY KEY);
            CREATE TABLE contenthashjobitem (job_id TEXT, revision_id TEXT);
            CREATE TABLE schema_migration (
                version INTEGER PRIMARY KEY, name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO schema_migration(version, name) VALUES
                (1, 'initial_schema'),
                (2, 'nested_folders_and_mount_sources'),
                (3, 'asset_metadata_and_bundles'),
                (4, 'persistent_preview_state'),
                (5, 'persistent_mount_scan_records'),
                (6, 'artifact_revisions_and_content_identity'),
                (7, 'immutable_revision_workflows'),
                (8, 'recoverable_trash');
            INSERT INTO asset VALUES
                ('active', 'Active', 'active-v2.stl', 'model/stl', 6, NULL,
                 'revisions/active/2/active-v2.stl', 'active-prepared', 'active-r2',
                 'thumbs/revisions/active-r2.jpg', NULL),
                ('trash', 'Trash', 'trash-v2.3mf', 'model/3mf', 8, NULL,
                 'revisions/trash/2/trash-v2.3mf', NULL, 'trash-r2',
                 'thumbs/revisions/trash-r2.jpg', '2026-08-20T00:00:00Z'),
                ('external', 'External', 'external.3mf', 'model/3mf', 9,
                 '/imports/external.3mf', 'Unassigned/External/external.3mf', NULL,
                 'external-r1', NULL, NULL);
            INSERT INTO artifactrevision VALUES
                ('active-r1', 'active', 1, 'active-v1.stl', 3, NULL,
                 'revisions/active/1/active-v1.stl', NULL, NULL,
                 'thumbs/revisions/active-r1.jpg'),
                ('active-r2', 'active', 2, 'active-v2.stl', 6, NULL,
                 'revisions/active/2/active-v2.stl', NULL, 'active-prepared',
                 'thumbs/revisions/active-r2.jpg'),
                ('trash-r1', 'trash', 1, 'trash-v1.3mf', 3, NULL,
                 'revisions/trash/1/trash-v1.3mf', NULL, NULL,
                 'thumbs/revisions/trash-r1.jpg'),
                ('trash-r2', 'trash', 2, 'trash-v2.3mf', 8, NULL,
                 'revisions/trash/2/trash-v2.3mf', NULL, NULL,
                 'thumbs/revisions/trash-r2.jpg'),
                ('external-r1', 'external', 1, 'external.3mf', 9, NULL,
                 'Unassigned/External/external.3mf', '/imports/external.3mf', NULL, NULL);
            INSERT INTO assetfile VALUES
                ('active-doc', 'active', 'assembly.pdf', 'supporting',
                 'bundles/active/support/assembly.pdf', NULL),
                ('active-prepared', 'active', 'print.gcode', 'prepared',
                 'bundles/active/prepared/print.gcode', 'active-r2'),
                ('trash-note', 'trash', 'notes.txt', 'supporting',
                 'bundles/trash/revisions/trash-r1/notes.txt', 'trash-r1');
            INSERT INTO trashpurgeoperation VALUES (
                'purge-op', 'cleanup_pending', '["already-purged"]',
                '[{"asset_id":"already-purged","source":"revisions/already-purged/1/model.stl","quarantine":".trash-quarantine/purge-op/already-purged/0-model.stl"}]',
                '.trash-quarantine/purge-op'
            );
            """
        )
        for revision_id, payload in {
            "active-r1": b"old",
            "active-r2": b"active",
            "trash-r1": b"old",
            "trash-r2": b"trashed!",
        }.items():
            connection.execute(
                "UPDATE artifactrevision SET sha256 = ? WHERE id = ?",
                (hashlib.sha256(payload).hexdigest(), revision_id),
            )
        connection.commit()
    finally:
        connection.close()


def schema8_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    database_dir = tmp_path / "database-v8"
    storage_dir = tmp_path / "storage-v8"
    database_dir.mkdir()
    storage_dir.mkdir()
    make_schema8_database(database_dir / "app.db")
    files = {
        "revisions/active/1/active-v1.stl": b"old",
        "revisions/active/2/active-v2.stl": b"active",
        "revisions/trash/1/trash-v1.3mf": b"old",
        "revisions/trash/2/trash-v2.3mf": b"trashed!",
        "bundles/active/support/assembly.pdf": b"support",
        "bundles/active/prepared/print.gcode": b"prepared",
        "bundles/trash/revisions/trash-r1/notes.txt": b"notes",
        "thumbs/revisions/active-r1.jpg": b"thumb-a1",
        "thumbs/revisions/active-r2.jpg": b"thumb-a2",
        "thumbs/revisions/trash-r1.jpg": b"thumb-t1",
        "thumbs/revisions/trash-r2.jpg": b"thumb-t2",
        ".trash-quarantine/purge-op/already-purged/0-model.stl": b"purged",
    }
    for relative, payload in files.items():
        target = storage_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    database_tar = tmp_path / "database-v8.tar"
    storage_tar = tmp_path / "storage-v8.tar"
    tar_directory(database_dir, database_tar)
    tar_directory(storage_dir, storage_tar)
    return database_dir, storage_dir, database_tar, storage_tar


def schema10_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    database_dir, storage_dir, database_tar, storage_tar = schema8_fixture(tmp_path)
    connection = sqlite3.connect(database_dir / "app.db")
    try:
        connection.executescript(
            """
            CREATE TABLE project (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, notes TEXT, creator TEXT,
                source_url TEXT, license TEXT, tags_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT
            );
            CREATE TABLE projectmembership (
                project_id TEXT NOT NULL, asset_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE projectrelationship (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                source_asset_id TEXT NOT NULL, target_asset_id TEXT NOT NULL,
                kind TEXT NOT NULL, created_at TEXT NOT NULL
            );
            INSERT INTO schema_migration(version, name) VALUES
                (9, 'project_identity_and_membership'),
                (10, 'project_artifact_relationships');
            INSERT INTO project VALUES
                ('active-project', 'Active Project', NULL, NULL, NULL, NULL, '[]',
                 '2026-08-23T00:00:00Z', '2026-08-23T00:00:00Z', NULL),
                ('trash-project', 'Trash Project', NULL, NULL, NULL, NULL, '[]',
                 '2026-08-23T00:00:00Z', '2026-08-24T00:00:00Z',
                 '2026-08-24T00:00:00Z');
            INSERT INTO projectmembership VALUES
                ('active-project', 'active', '2026-08-23T00:00:00Z'),
                ('active-project', 'trash', '2026-08-23T00:00:00Z'),
                ('trash-project', 'trash', '2026-08-23T00:00:00Z'),
                ('trash-project', 'external', '2026-08-23T00:00:00Z');
            INSERT INTO projectrelationship VALUES
                ('rel-active', 'active-project', 'active', 'trash',
                 'component_of', '2026-08-23T00:00:00Z'),
                ('rel-trash', 'trash-project', 'trash', 'external',
                 'documentation_for', '2026-08-23T00:00:00Z');
            """
        )
        connection.commit()
    finally:
        connection.close()
    tar_directory(database_dir, database_tar)
    tar_directory(storage_dir, storage_tar)
    return database_dir, storage_dir, database_tar, storage_tar


def schema12_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    database_dir, storage_dir, database_tar, storage_tar = schema10_fixture(tmp_path)
    connection = sqlite3.connect(database_dir / "app.db")
    try:
        connection.executescript(
            """
            ALTER TABLE asset ADD COLUMN prepared_machine_id TEXT;
            ALTER TABLE artifactrevision ADD COLUMN prepared_machine_id TEXT;
            CREATE TABLE machineprofile (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
                manufacturer TEXT, model TEXT, location TEXT, notes TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT
            );
            CREATE TABLE artifactmachine (
                asset_id TEXT NOT NULL, machine_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO schema_migration(version, name) VALUES
                (11, 'machine_profiles'),
                (12, 'artifact_machine_context');
            INSERT INTO machineprofile VALUES
                ('machine-active', 'Active Printer', 'fdm_printer', 'Fixture',
                 'Model A', 'Bench', 'Current exact target',
                 '2026-08-27T00:00:00Z', '2026-08-27T00:00:00Z', NULL),
                ('machine-archived', 'Archived Printer', 'resin_printer', 'Fixture',
                 'Model B', 'Shelf', 'Historical exact target',
                 '2026-08-27T00:00:00Z', '2026-08-28T00:00:00Z',
                 '2026-08-28T00:00:00Z'),
                ('machine-laser', 'Workshop Laser', 'laser', 'Fixture',
                 'Model C', 'Bench', 'Neutral association only',
                 '2026-08-27T00:00:00Z', '2026-08-27T00:00:00Z', NULL);
            INSERT INTO artifactmachine VALUES
                ('active', 'machine-active', '2026-08-27T00:00:00Z'),
                ('trash', 'machine-archived', '2026-08-27T00:00:00Z'),
                ('external', 'machine-laser', '2026-08-27T00:00:00Z');
            INSERT INTO assetfile VALUES
                ('active-prepared-old', 'active', 'old.gcode', 'prepared',
                 'bundles/active/revisions/active-r1/prepared/old.gcode',
                 'active-r1');
            UPDATE artifactrevision
            SET prepared_file_id = 'active-prepared-old',
                prepared_machine_id = 'machine-archived'
            WHERE id = 'active-r1';
            UPDATE artifactrevision
            SET prepared_machine_id = 'machine-active'
            WHERE id = 'active-r2';
            UPDATE asset
            SET prepared_machine_id = 'machine-active'
            WHERE id = 'active';
            """
        )
        connection.commit()
    finally:
        connection.close()
    old_prepared = storage_dir / "bundles/active/revisions/active-r1/prepared/old.gcode"
    old_prepared.parent.mkdir(parents=True)
    old_prepared.write_bytes(b"old prepared")
    tar_directory(database_dir, database_tar)
    tar_directory(storage_dir, storage_tar)
    return database_dir, storage_dir, database_tar, storage_tar


def schema16_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    database_dir, storage_dir, database_tar, storage_tar = schema12_fixture(tmp_path)
    administrator_id = "11111111-1111-4111-8111-111111111111"
    member_id = "22222222-2222-4222-8222-222222222222"
    session_id = "33333333-3333-4333-8333-333333333333"
    event_id = "44444444-4444-4444-8444-444444444444"
    correlation_id = "55555555-5555-4555-8555-555555555555"
    marker_id = "66666666-6666-4666-8666-666666666666"
    connection = sqlite3.connect(database_dir / "app.db")
    try:
        connection.executescript(
            f"""
            CREATE TABLE useraccount (
                id TEXT PRIMARY KEY, username TEXT NOT NULL,
                username_normalized TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL, enabled INTEGER NOT NULL,
                password_policy_version INTEGER NOT NULL,
                password_change_required INTEGER NOT NULL, role TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_login_at TEXT
            );
            CREATE TABLE browsersession (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, secret_digest TEXT NOT NULL UNIQUE,
                created_at INTEGER NOT NULL, last_seen_at INTEGER NOT NULL,
                idle_expires_at INTEGER NOT NULL, absolute_expires_at INTEGER NOT NULL,
                idle_ttl_seconds INTEGER NOT NULL, reauthenticated_at INTEGER NOT NULL,
                revoked_at INTEGER, client_address TEXT, user_agent TEXT
            );
            CREATE TABLE auditevent (
                id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL,
                correlation_id TEXT NOT NULL, actor_user_id TEXT, actor_username TEXT,
                actor_role TEXT, action TEXT NOT NULL, result TEXT NOT NULL,
                object_type TEXT, object_id TEXT, method TEXT, route TEXT,
                permission TEXT, status_code INTEGER, source_address TEXT,
                details_json TEXT NOT NULL
            );
            CREATE TABLE recoverymarker (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, created_at TEXT NOT NULL,
                details_json TEXT NOT NULL, processed_at TEXT
            );
            INSERT INTO schema_migration(version, name) VALUES
                (13, 'persistent_administrator_identity'),
                (14, 'revocable_browser_sessions'),
                (15, 'shared_vault_roles'),
                (16, 'account_audit_and_recovery');
            INSERT INTO useraccount VALUES
                ('{administrator_id}', 'Admin', 'admin', 'Administrator',
                 '$argon2id$v=19$fixture', 1, 1, 0, 'administrator',
                 '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z', NULL),
                ('{member_id}', 'Member', 'member', 'Member',
                 '$argon2id$v=19$fixture', 1, 1, 0, 'member',
                 '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z', NULL);
            INSERT INTO browsersession VALUES
                ('{session_id}', '{member_id}', '{'a' * 64}',
                 100, 110, 200, 300, 90, 105, NULL, '127.0.0.1', 'fixture');
            INSERT INTO auditevent VALUES
                ('{event_id}', '2026-09-01T00:00:00Z', '{correlation_id}',
                 '{administrator_id}', 'Admin', 'administrator', 'identity.login',
                 'success', 'user', '{administrator_id}', 'POST', '/login', NULL,
                 200, '127.0.0.1', '{{}}');
            INSERT INTO recoverymarker VALUES
                ('{marker_id}', 'raw_restore', '2026-09-01T00:00:00Z',
                 '{{"revoked_sessions":0}}', '2026-09-01T00:00:01Z');
            """
        )
        connection.commit()
    finally:
        connection.close()
    tar_directory(database_dir, database_tar)
    tar_directory(storage_dir, storage_tar)
    return database_dir, storage_dir, database_tar, storage_tar


def tar_directory(source: Path, output: Path) -> None:
    with tarfile.open(output, "w") as archive:
        archive.add(source, arcname=".", recursive=True)


def rewrite_backup_manifest(
    source: Path,
    output: Path,
    workdir: Path,
    mutate,
) -> None:
    unpacked = workdir / output.stem
    unpacked.mkdir()
    with tarfile.open(source, "r:gz") as archive:
        archive.extractall(unpacked)
    manifest_path = unpacked / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutate(manifest)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    checksums_path = unpacked / "checksums.sha256"
    manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    checksums_path.write_text(
        "\n".join(
            f"{manifest_digest}  manifest.json" if line.endswith("  manifest.json") else line
            for line in checksums_path.read_text(encoding="utf-8").splitlines()
        )
        + "\n",
        encoding="utf-8",
    )
    with tarfile.open(output, "w:gz") as archive:
        for name in (
            "manifest.json",
            "checksums.sha256",
            "database.tar",
            "storage.tar",
        ):
            archive.add(unpacked / name, arcname=name)


def rewrite_backup_database(
    source: Path,
    output: Path,
    workdir: Path,
    mutation: str,
) -> None:
    unpacked = workdir / f"{output.stem}-outer"
    unpacked.mkdir()
    with tarfile.open(source, "r:gz") as archive:
        archive.extractall(unpacked)
    database_dir = workdir / f"{output.stem}-database"
    database_dir.mkdir()
    with tarfile.open(unpacked / "database.tar", "r") as archive:
        archive.extractall(database_dir)
    connection = sqlite3.connect(database_dir / "app.db")
    try:
        connection.execute(mutation)
        connection.commit()
    finally:
        connection.close()
    tar_directory(database_dir, unpacked / "database.tar")

    manifest_path = unpacked / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    database_members = validate_component_tar(unpacked / "database.tar")
    database_digest = hashlib.sha256(
        (unpacked / "database.tar").read_bytes()
    ).hexdigest()
    manifest["components"]["database.tar"] = {
        "sha256": database_digest,
        "bytes": (unpacked / "database.tar").stat().st_size,
        "file_count": len(database_members),
        "expanded_bytes": sum(int(item["size"]) for item in database_members),
        "files": database_members,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    storage_digest = hashlib.sha256((unpacked / "storage.tar").read_bytes()).hexdigest()
    manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    (unpacked / "checksums.sha256").write_text(
        f"{database_digest}  database.tar\n"
        f"{storage_digest}  storage.tar\n"
        f"{manifest_digest}  manifest.json\n",
        encoding="utf-8",
    )
    with tarfile.open(output, "w:gz") as archive:
        for name in (
            "manifest.json",
            "checksums.sha256",
            "database.tar",
            "storage.tar",
        ):
            archive.add(unpacked / name, arcname=name)


def backup_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    database_dir = tmp_path / "database"
    storage_dir = tmp_path / "storage"
    database_dir.mkdir()
    (storage_dir / "Fixtures/Managed").mkdir(parents=True)
    (storage_dir / "bundles/managed/support").mkdir(parents=True)
    (storage_dir / "bundles/managed/prepared").mkdir(parents=True)
    (storage_dir / "thumbs").mkdir(parents=True)
    make_database(database_dir / "app.db")
    (storage_dir / "Fixtures/Managed/managed.stl").write_bytes(b"managed")
    (storage_dir / "bundles/managed/support/assembly.pdf").write_bytes(b"support")
    (storage_dir / "bundles/managed/prepared/prepared.gcode").write_bytes(b"prepared")
    (storage_dir / "thumbs/managed.jpg").write_bytes(b"derived")
    database_tar = tmp_path / "database.tar"
    storage_tar = tmp_path / "storage.tar"
    tar_directory(database_dir, database_tar)
    tar_directory(storage_dir, storage_tar)
    return database_dir, storage_dir, database_tar, storage_tar


def test_backup_round_trip_verifies_manifest_and_sensitive_config(tmp_path: Path) -> None:
    _, _, database_tar, storage_tar = backup_fixture(tmp_path)
    config = tmp_path / ".env"
    config.write_text("AUTH_SECRET=do-not-print-this-value\n", encoding="utf-8")
    archive = tmp_path / "makersvault-v5.1.0.backup.tar.gz"

    manifest = create_backup(
        database_tar,
        storage_tar,
        archive,
        "v5.1.0",
        "fixture-revision",
        config,
    )

    assert archive.stat().st_mode & 0o777 == 0o600
    assert manifest["database"]["quick_check"] == ["ok"]
    assert manifest["database"]["schema_version"] == 5
    assert manifest["consistency"]["status"] == "ok"
    assert manifest["consistency"]["managed_primary_present"] == 1
    assert manifest["consistency"]["external_state_counts"]["unknown"] == 1
    assert manifest["external_content_included"] is False
    assert "do-not-print-this-value" not in json.dumps(manifest)

    verified = verify_backup(archive)
    assert verified == manifest
    restored = verify_restored_components(archive, database_tar, storage_tar)
    assert restored["matches_backup"] is True
    assert restored["consistency"]["status"] == "ok"
    extracted = tmp_path / "extracted"
    assert extract_backup(archive, extracted) == manifest
    assert (extracted / "config.env").read_text() == config.read_text()
    assert validate_component_tar(extracted / "database.tar")


def test_live_audit_maps_available_and_unavailable_external_sources(tmp_path: Path) -> None:
    database_dir, storage_dir, _, _ = backup_fixture(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    (external / "external.stl").write_bytes(b"external")

    available = audit_live_paths(
        database_dir / "app.db",
        storage_dir,
        Path("/imports"),
        external,
    )
    assert available["consistency"]["external_state_counts"]["available"] == 1

    (external / "external.stl").unlink()
    unavailable = audit_live_paths(
        database_dir / "app.db",
        storage_dir,
        Path("/imports"),
        external,
    )
    assert unavailable["consistency"]["status"] == "ok"
    assert unavailable["consistency"]["external_state_counts"]["unavailable"] == 1


def test_component_audit_does_not_require_the_application_image(tmp_path: Path) -> None:
    _, _, database_tar, storage_tar = backup_fixture(tmp_path)

    result = audit_component_tars(database_tar, storage_tar)

    assert result["database"]["schema_version"] == 5
    assert result["consistency"]["status"] == "ok"
    assert result["consistency"]["external_state_counts"]["unknown"] == 1


def test_component_tar_rejects_traversal_and_symbolic_links(tmp_path: Path) -> None:
    traversal = tmp_path / "traversal.tar"
    with tarfile.open(traversal, "w") as archive:
        info = tarfile.TarInfo("../escape")
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(RecoveryError, match="escapes"):
        validate_component_tar(traversal)

    linked = tmp_path / "linked.tar"
    with tarfile.open(linked, "w") as archive:
        info = tarfile.TarInfo("linked")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        archive.addfile(info)
    with pytest.raises(RecoveryError, match="non-regular"):
        validate_component_tar(linked)


def test_extract_refuses_nonempty_target_and_corruption(tmp_path: Path) -> None:
    _, _, database_tar, storage_tar = backup_fixture(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    create_backup(database_tar, storage_tar, archive, "v5.1.0", "fixture")
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("keep")
    with pytest.raises(RecoveryError, match="must be empty"):
        extract_backup(archive, occupied)
    assert (occupied / "keep.txt").read_text() == "keep"

    corrupt = tmp_path / "corrupt.tar.gz"
    data = bytearray(archive.read_bytes())
    data[len(data) // 2] ^= 0xFF
    corrupt.write_bytes(data)
    with pytest.raises(RecoveryError):
        verify_backup(corrupt)


def test_restored_verification_detects_changed_file_bytes(tmp_path: Path) -> None:
    _, storage_dir, database_tar, storage_tar = backup_fixture(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    create_backup(database_tar, storage_tar, archive, "v5.1.0", "fixture")
    (storage_dir / "Fixtures/Managed/managed.stl").write_bytes(b"changed")
    changed_storage_tar = tmp_path / "changed-storage.tar"
    tar_directory(storage_dir, changed_storage_tar)

    with pytest.raises(RecoveryError, match="does not match"):
        verify_restored_components(archive, database_tar, changed_storage_tar)


def test_schema8_backup_round_trip_represents_revisions_trash_and_quarantine(
    tmp_path: Path,
) -> None:
    _, _, database_tar, storage_tar = schema8_fixture(tmp_path)
    archive = tmp_path / "makersvault-schema8.backup.tar.gz"

    manifest = create_backup(
        database_tar,
        storage_tar,
        archive,
        "post-v5.1-gate6",
        "gate6-fixture",
    )

    assert manifest["format_version"] == 1
    assert manifest["recovery_contract_version"] == 5
    assert manifest["database"]["schema_version"] == 8
    assert manifest["database"]["row_counts"]["artifactrevision"] == 5
    assert manifest["database"]["row_counts"]["trashpurgeoperation"] == 1
    audit = manifest["consistency"]
    assert audit["status"] == "ok"
    assert audit["active_asset_count"] == 2
    assert audit["trashed_asset_count"] == 1
    assert audit["revision_count"] == 5
    assert audit["managed_revision_present"] == 4
    assert audit["external_state_counts"]["unknown"] == 1
    assert audit["related_file_present"] == 3
    assert audit["purge_operation_status_counts"] == {"cleanup_pending": 1}
    assert audit["known_quarantine_files"] == [
        ".trash-quarantine/purge-op/already-purged/0-model.stl"
    ]
    assert audit["unknown_quarantine_files"] == []

    assert verify_backup(archive) == manifest
    assert verify_restored_components(
        archive, database_tar, storage_tar
    )["matches_backup"] is True
    extracted = tmp_path / "schema8-extracted"
    assert extract_backup(archive, extracted) == manifest


def test_schema10_backup_round_trip_represents_project_graph(tmp_path: Path) -> None:
    _, _, database_tar, storage_tar = schema10_fixture(tmp_path)
    archive = tmp_path / "makersvault-schema10.backup.tar.gz"

    manifest = create_backup(
        database_tar,
        storage_tar,
        archive,
        "post-v5.1-gate7",
        "gate7-fixture",
    )

    assert manifest["format_version"] == 1
    assert manifest["recovery_contract_version"] == 5
    assert manifest["database"]["schema_version"] == 10
    assert manifest["database"]["row_counts"]["project"] == 2
    assert manifest["database"]["row_counts"]["projectmembership"] == 4
    assert manifest["database"]["row_counts"]["projectrelationship"] == 2
    audit = manifest["consistency"]
    assert audit["status"] == "ok"
    assert audit["active_project_count"] == 1
    assert audit["trashed_project_count"] == 1
    assert audit["project_membership_count"] == 4
    assert audit["project_relationship_count"] == 2
    for key in (
        "orphan_project_membership_keys",
        "orphan_asset_membership_keys",
        "orphan_relationship_project_ids",
        "orphan_relationship_source_asset_ids",
        "orphan_relationship_target_asset_ids",
        "relationship_nonmember_source_ids",
        "relationship_nonmember_target_ids",
        "self_relationship_ids",
        "invalid_relationship_kind_ids",
        "duplicate_relationship_ids",
    ):
        assert audit[key] == []

    assert verify_backup(archive) == manifest
    assert verify_restored_components(
        archive, database_tar, storage_tar
    )["matches_backup"] is True
    extracted = tmp_path / "schema10-extracted"
    assert extract_backup(archive, extracted) == manifest


def test_schema12_backup_round_trip_represents_machine_context(tmp_path: Path) -> None:
    _, _, database_tar, storage_tar = schema12_fixture(tmp_path)
    archive = tmp_path / "makersvault-schema12.backup.tar.gz"

    manifest = create_backup(
        database_tar,
        storage_tar,
        archive,
        "post-v5.1-gate9",
        "gate9-fixture",
    )

    assert manifest["format_version"] == 1
    assert manifest["recovery_contract_version"] == 5
    assert manifest["database"]["schema_version"] == 12
    assert manifest["database"]["row_counts"]["machineprofile"] == 3
    assert manifest["database"]["row_counts"]["artifactmachine"] == 3
    audit = manifest["consistency"]
    assert audit["status"] == "ok"
    assert audit["active_machine_count"] == 2
    assert audit["archived_machine_count"] == 1
    assert audit["machine_association_count"] == 3
    assert audit["current_prepared_machine_count"] == 1
    assert audit["revision_prepared_machine_count"] == 2
    for key in MACHINE_REPORT_KEYS[5:]:
        assert audit[key] == []

    assert verify_backup(archive) == manifest
    assert verify_restored_components(
        archive, database_tar, storage_tar
    )["matches_backup"] is True
    extracted = tmp_path / "schema12-extracted"
    assert extract_backup(archive, extracted) == manifest


def test_schema16_contract5_represents_identity_session_audit_and_recovery(
    tmp_path: Path,
) -> None:
    _, _, database_tar, storage_tar = schema16_fixture(tmp_path)
    archive = tmp_path / "makersvault-schema16.backup.tar.gz"

    manifest = create_backup(
        database_tar, storage_tar, archive, "v5.1.0", "gate11d3-fixture"
    )

    assert manifest["recovery_contract_version"] == 5
    assert manifest["database"]["schema_version"] == 16
    assert manifest["database"]["row_counts"]["useraccount"] == 2
    assert manifest["database"]["row_counts"]["browsersession"] == 1
    assert manifest["database"]["row_counts"]["auditevent"] == 1
    assert manifest["database"]["row_counts"]["recoverymarker"] == 1
    audit = manifest["consistency"]
    assert audit["status"] == "ok"
    assert audit["enabled_administrator_count"] == 1
    assert audit["missing_enabled_administrator"] is False
    for key in SECURITY_REPORT_KEYS:
        assert audit[key] == []
    assert verify_backup(archive) == manifest


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE useraccount SET role = 'owner' WHERE username_normalized = 'member'",
        "UPDATE useraccount SET enabled = 0 WHERE role = 'administrator'",
        "UPDATE browsersession SET user_id = 'missing-user'",
        "UPDATE browsersession SET secret_digest = 'plaintext-secret'",
        "UPDATE browsersession SET idle_expires_at = 50",
        "UPDATE auditevent SET details_json = '[1,2,3]'",
        "UPDATE recoverymarker SET kind = 'unknown-recovery'",
    ],
)
def test_contract5_rejects_security_domain_corruption(
    tmp_path: Path,
    mutation: str,
) -> None:
    _, _, database_tar, storage_tar = schema16_fixture(tmp_path)
    archive = tmp_path / "schema16-current.tar.gz"
    create_backup(database_tar, storage_tar, archive, "v5.1.0", "gate11d3")
    corrupt = tmp_path / f"corrupt-{abs(hash(mutation))}.tar.gz"
    rewrite_backup_database(archive, corrupt, tmp_path, mutation)

    with pytest.raises(RecoveryError, match="consistency|inconsistent"):
        verify_backup(corrupt)


def test_contract4_schema16_is_compatibly_reaudited(tmp_path: Path) -> None:
    _, _, database_tar, storage_tar = schema16_fixture(tmp_path)
    current = tmp_path / "schema16-contract5.tar.gz"
    create_backup(database_tar, storage_tar, current, "v5.1.0", "gate11d3")
    contract4 = tmp_path / "schema16-contract4.tar.gz"

    def contract4_shape(manifest: dict) -> None:
        manifest["recovery_contract_version"] = 4
        for table in ("useraccount", "browsersession", "auditevent", "recoverymarker"):
            manifest["database"]["row_counts"].pop(table)
        for key in (
            "account_count", "enabled_administrator_count", "browser_session_count",
            "audit_event_count", "recovery_marker_count",
            "pending_recovery_marker_count", "missing_enabled_administrator",
            *SECURITY_REPORT_KEYS,
        ):
            manifest["consistency"].pop(key)

    rewrite_backup_manifest(current, contract4, tmp_path, contract4_shape)
    assert verify_backup(contract4)["recovery_contract_version"] == 4

    corrupt = tmp_path / "schema16-contract4-corrupt.tar.gz"
    rewrite_backup_database(
        contract4,
        corrupt,
        tmp_path,
        "UPDATE browsersession SET secret_digest = 'copied-browser-secret'",
    )
    with pytest.raises(RecoveryError, match="consistency|inconsistent"):
        verify_backup(corrupt)


def test_raw_restore_revokes_sessions_and_queues_marker_only(tmp_path: Path) -> None:
    database_dir, _, _, _ = schema16_fixture(tmp_path)
    database = database_dir / "app.db"
    connection = sqlite3.connect(database)
    before = connection.execute(
        "SELECT name, prepared_machine_id FROM asset ORDER BY id"
    ).fetchall()
    connection.close()

    result = mark_restored_database(database)

    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM browsersession WHERE revoked_at IS NULL"
        ).fetchone()[0] == 0
        marker = connection.execute(
            "SELECT kind, details_json, processed_at FROM recoverymarker "
            "WHERE id = ?",
            (result["marker_id"],),
        ).fetchone()
        assert marker[0] == "raw_restore"
        assert json.loads(marker[1]) == {"revoked_sessions": 1}
        assert marker[2] is None
        assert connection.execute(
            "SELECT name, prepared_machine_id FROM asset ORDER BY id"
        ).fetchall() == before
    finally:
        connection.close()


def test_stopped_recovery_refuses_an_already_locked_or_indirect_database(
    tmp_path: Path,
) -> None:
    database_dir, _, _, _ = schema16_fixture(tmp_path)
    database = database_dir / "app.db"
    descriptor = os.open(database, os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RecoveryMutationError, match="lock"):
            mark_restored_database(database)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    linked = tmp_path / "linked.db"
    linked.symlink_to(database)
    with pytest.raises(RecoveryMutationError, match="exact regular"):
        mark_restored_database(linked)


def test_administrator_recovery_requires_exact_backup_and_existing_account(
    tmp_path: Path,
) -> None:
    database_dir, _, database_tar, storage_tar = schema16_fixture(tmp_path)
    database = database_dir / "app.db"
    backup = tmp_path / "prechange.tar.gz"
    create_backup(database_tar, storage_tar, backup, "v5.1.0", "gate11d3")

    with pytest.raises(RecoveryMutationError, match="existing account"):
        recover_existing_administrator(
            database,
            backup,
            "does-not-exist",
            "$argon2id$v=19$unused-hash",
            1,
        )

    result = recover_existing_administrator(
        database,
        backup,
        "Member",
        "$argon2id$v=19$new-temporary-hash",
        1,
    )

    connection = sqlite3.connect(database)
    try:
        account = connection.execute(
            "SELECT enabled, role, password_change_required, password_hash "
            "FROM useraccount WHERE id = ?",
            (result["user_id"],),
        ).fetchone()
        assert account == (1, "administrator", 1, "$argon2id$v=19$new-temporary-hash")
        assert connection.execute(
            "SELECT COUNT(*) FROM browsersession WHERE revoked_at IS NULL"
        ).fetchone()[0] == 0
        marker = connection.execute(
            "SELECT kind, details_json, processed_at FROM recoverymarker WHERE id = ?",
            (result["marker_id"],),
        ).fetchone()
        assert marker[0] == "administrator_recovery"
        assert json.loads(marker[1])["user_id"] == result["user_id"]
        assert marker[2] is None
    finally:
        connection.close()

    with pytest.raises(RecoveryMutationError, match="exact pre-change"):
        recover_existing_administrator(
            database,
            backup,
            "Admin",
            "$argon2id$v=19$another-hash",
            1,
        )


def test_administrator_recovery_snapshot_allows_only_missing_enabled_admin(
    tmp_path: Path,
) -> None:
    database_dir, storage_dir, _, _ = schema16_fixture(tmp_path)
    database = database_dir / "app.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE useraccount SET enabled = 0 WHERE role = 'administrator'"
        )
        connection.commit()
    finally:
        connection.close()
    database_tar = tmp_path / "locked-out-database.tar"
    storage_tar = tmp_path / "locked-out-storage.tar"
    tar_directory(database_dir, database_tar)
    tar_directory(storage_dir, storage_tar)
    archive = tmp_path / "admin-recovery-snapshot.tar.gz"

    with pytest.raises(RecoveryError, match="inconsistent"):
        create_backup(database_tar, storage_tar, archive, "v5.1.0", "gate11d3")
    manifest = create_backup(
        database_tar,
        storage_tar,
        archive,
        "v5.1.0",
        "gate11d3",
        administrator_recovery_snapshot=True,
    )
    assert manifest["recovery_purpose"] == "administrator_recovery"
    assert manifest["consistency"]["critical_finding_count"] == 1
    with pytest.raises(RecoveryError, match="inconsistent"):
        verify_backup(archive)
    assert verify_backup(archive, allow_administrator_recovery=True) == manifest

    result = recover_existing_administrator(
        database,
        archive,
        "Member",
        "$argon2id$v=19$recovered-hash",
        1,
    )
    assert result["username"] == "Member"

    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT enabled, role FROM useraccount WHERE username_normalized = 'member'"
        ).fetchone() == (1, "administrator")
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("mutation", "report_key", "expected"),
    [
        (
            "DROP TABLE machineprofile",
            "missing_machine_tables",
            ["machineprofile"],
        ),
        (
            "DROP TABLE artifactmachine",
            "missing_machine_tables",
            ["artifactmachine"],
        ),
        (
            "ALTER TABLE asset DROP COLUMN prepared_machine_id",
            "missing_machine_reference_columns",
            ["asset.prepared_machine_id"],
        ),
        (
            "ALTER TABLE artifactrevision DROP COLUMN prepared_machine_id",
            "missing_machine_reference_columns",
            ["artifactrevision.prepared_machine_id"],
        ),
        (
            "UPDATE machineprofile SET category = 'router' "
            "WHERE id = 'machine-laser'",
            "invalid_machine_category_ids",
            ["machine-laser"],
        ),
        (
            "UPDATE machineprofile SET name = 'Active Printer' "
            "WHERE id = 'machine-laser'",
            "duplicate_active_machine_name_ids",
            ["machine-active", "machine-laser"],
        ),
        (
            "UPDATE artifactmachine SET asset_id = 'missing-asset' "
            "WHERE asset_id = 'active' AND machine_id = 'machine-active'",
            "orphan_machine_association_asset_keys",
            ["missing-asset/machine-active"],
        ),
        (
            "UPDATE artifactmachine SET machine_id = 'missing-machine' "
            "WHERE asset_id = 'external' AND machine_id = 'machine-laser'",
            "orphan_machine_association_machine_keys",
            ["external/missing-machine"],
        ),
        (
            "INSERT INTO artifactmachine VALUES "
            "('active', 'machine-active', '2026-08-28T00:00:00Z')",
            "duplicate_machine_association_keys",
            ["active/machine-active"],
        ),
        (
            "UPDATE asset SET prepared_machine_id = 'missing-machine' "
            "WHERE id = 'active'",
            "orphan_asset_prepared_machine_ids",
            ["active"],
        ),
        (
            "UPDATE artifactrevision SET prepared_machine_id = 'missing-machine' "
            "WHERE id = 'active-r1'",
            "orphan_revision_prepared_machine_ids",
            ["active-r1"],
        ),
        (
            "UPDATE asset SET prepared_machine_id = 'machine-archived' "
            "WHERE id = 'active'",
            "prepared_machine_mirror_mismatch_asset_ids",
            ["active"],
        ),
    ],
)
def test_schema12_audit_rejects_broken_machine_context(
    tmp_path: Path,
    mutation: str,
    report_key: str,
    expected: list[str],
) -> None:
    database_dir, storage_dir, database_tar, storage_tar = schema12_fixture(tmp_path)
    connection = sqlite3.connect(database_dir / "app.db")
    try:
        connection.execute(mutation)
        connection.commit()
    finally:
        connection.close()

    audit = audit_live_paths(database_dir / "app.db", storage_dir)["consistency"]

    assert audit["status"] == "inconsistent"
    assert audit[report_key] == expected
    tar_directory(database_dir, database_tar)
    with pytest.raises(RecoveryError, match="inconsistent"):
        create_backup(
            database_tar,
            storage_tar,
            tmp_path / "must-not-exist-machine.tar.gz",
            "gate9",
            "broken-machine-context",
        )


@pytest.mark.parametrize(
    ("mutation", "report_key", "expected"),
    [
        (
            "UPDATE projectmembership SET project_id = 'missing-project' "
            "WHERE project_id = 'active-project' AND asset_id = 'active'",
            "orphan_project_membership_keys",
            ["missing-project/active"],
        ),
        (
            "UPDATE projectmembership SET asset_id = 'missing-asset' "
            "WHERE project_id = 'active-project' AND asset_id = 'trash'",
            "orphan_asset_membership_keys",
            ["active-project/missing-asset"],
        ),
        (
            "UPDATE projectrelationship SET project_id = 'missing-project' "
            "WHERE id = 'rel-active'",
            "orphan_relationship_project_ids",
            ["rel-active"],
        ),
        (
            "UPDATE projectrelationship SET source_asset_id = 'missing-asset' "
            "WHERE id = 'rel-active'",
            "orphan_relationship_source_asset_ids",
            ["rel-active"],
        ),
        (
            "UPDATE projectrelationship SET target_asset_id = 'missing-asset' "
            "WHERE id = 'rel-active'",
            "orphan_relationship_target_asset_ids",
            ["rel-active"],
        ),
        (
            "UPDATE projectrelationship SET target_asset_id = 'external' "
            "WHERE id = 'rel-active'",
            "relationship_nonmember_target_ids",
            ["rel-active"],
        ),
        (
            "UPDATE projectrelationship SET source_asset_id = 'external' "
            "WHERE id = 'rel-active'",
            "relationship_nonmember_source_ids",
            ["rel-active"],
        ),
        (
            "UPDATE projectrelationship SET target_asset_id = source_asset_id "
            "WHERE id = 'rel-active'",
            "self_relationship_ids",
            ["rel-active"],
        ),
        (
            "UPDATE projectrelationship SET kind = 'attached_to' "
            "WHERE id = 'rel-active'",
            "invalid_relationship_kind_ids",
            ["rel-active"],
        ),
        (
            "INSERT INTO projectrelationship VALUES "
            "('rel-duplicate', 'active-project', 'active', 'trash', "
            "'component_of', '2026-08-23T00:00:01Z')",
            "duplicate_relationship_ids",
            ["rel-duplicate"],
        ),
        (
            "DROP TABLE projectrelationship",
            "missing_project_tables",
            ["projectrelationship"],
        ),
    ],
)
def test_schema10_audit_rejects_broken_project_ownership(
    tmp_path: Path,
    mutation: str,
    report_key: str,
    expected: list[str],
) -> None:
    database_dir, storage_dir, database_tar, storage_tar = schema10_fixture(tmp_path)
    connection = sqlite3.connect(database_dir / "app.db")
    try:
        connection.execute(mutation)
        connection.commit()
    finally:
        connection.close()

    audit = audit_live_paths(database_dir / "app.db", storage_dir)["consistency"]

    assert audit["status"] == "inconsistent"
    assert audit[report_key] == expected
    tar_directory(database_dir, database_tar)
    with pytest.raises(RecoveryError, match="inconsistent"):
        create_backup(
            database_tar,
            storage_tar,
            tmp_path / "must-not-exist.tar.gz",
            "gate7",
            "broken-project-graph",
        )


def test_schema8_audit_rejects_missing_or_changed_history_and_broken_ownership(
    tmp_path: Path,
) -> None:
    database_dir, storage_dir, _, _ = schema8_fixture(tmp_path)
    database = database_dir / "app.db"

    (storage_dir / "revisions/active/1/active-v1.stl").write_bytes(b"bad")
    (storage_dir / "revisions/trash/1/trash-v1.3mf").unlink()
    unknown = storage_dir / ".trash-quarantine/unknown/orphan.stl"
    unknown.parent.mkdir(parents=True)
    unknown.write_bytes(b"unknown")
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE asset SET current_revision_id = 'trash-r2' WHERE id = 'active'"
        )
        connection.execute(
            "UPDATE assetfile SET revision_id = 'trash-r1' WHERE id = 'active-prepared'"
        )
        connection.commit()
    finally:
        connection.close()

    result = audit_live_paths(database, storage_dir)["consistency"]

    assert result["status"] == "inconsistent"
    assert result["missing_managed_revision_ids"] == ["trash-r1"]
    assert result["invalid_current_revision_asset_ids"] == ["active"]
    assert result["related_file_revision_mismatch_ids"] == ["active-prepared"]
    assert result["invalid_revision_prepared_pointer_ids"] == ["active-r2"]
    assert result["unknown_quarantine_files"] == [
        ".trash-quarantine/unknown/orphan.stl"
    ]

    database_tar = tmp_path / "broken-database.tar"
    storage_tar = tmp_path / "broken-storage.tar"
    tar_directory(database_dir, database_tar)
    tar_directory(storage_dir, storage_tar)
    with pytest.raises(RecoveryError, match="inconsistent"):
        create_backup(
            database_tar,
            storage_tar,
            tmp_path / "must-not-exist.tar.gz",
            "gate6",
            "broken",
        )


def test_schema8_backup_rejects_revision_digest_mismatch(tmp_path: Path) -> None:
    _, storage_dir, database_tar, _ = schema8_fixture(tmp_path)
    (storage_dir / "revisions/active/1/active-v1.stl").write_bytes(b"bad")
    storage_tar = tmp_path / "digest-mismatch-storage.tar"
    tar_directory(storage_dir, storage_tar)

    result = audit_component_tars(database_tar, storage_tar)["consistency"]
    assert result["status"] == "inconsistent"
    assert result["revision_digest_mismatch_ids"] == ["active-r1"]
    with pytest.raises(RecoveryError, match="inconsistent"):
        create_backup(
            database_tar,
            storage_tar,
            tmp_path / "digest-mismatch.backup.tar.gz",
            "gate6",
            "digest-mismatch",
        )


def test_verifier_accepts_contract2_schema8_archive(tmp_path: Path) -> None:
    _, _, database_tar, storage_tar = schema8_fixture(tmp_path)
    current_archive = tmp_path / "current-schema8.tar.gz"
    create_backup(
        database_tar,
        storage_tar,
        current_archive,
        "post-v5.1-gate6",
        "contract2-fixture",
    )
    contract2_archive = tmp_path / "contract2-schema8.tar.gz"
    rewrite_backup_manifest(
        current_archive,
        contract2_archive,
        tmp_path,
        lambda manifest: manifest.__setitem__("recovery_contract_version", 2),
    )

    verified = verify_backup(contract2_archive)

    assert verified["recovery_contract_version"] == 2
    assert verified["database"]["schema_version"] == 8


def test_verifier_accepts_pre_gate7e_contract2_schema10_archive(
    tmp_path: Path,
) -> None:
    _, _, database_tar, storage_tar = schema10_fixture(tmp_path)
    current_archive = tmp_path / "current-schema10.tar.gz"
    create_backup(
        database_tar,
        storage_tar,
        current_archive,
        "post-v5.1-gate7",
        "pre-gate7e-contract2-fixture",
    )
    contract2_archive = tmp_path / "contract2-schema10.tar.gz"

    def contract2_shape(manifest: dict) -> None:
        manifest["recovery_contract_version"] = 2
        for table in ("project", "projectmembership", "projectrelationship"):
            manifest["database"]["row_counts"].pop(table)
        for key in (
            "active_project_count",
            "trashed_project_count",
            "project_membership_count",
            "project_relationship_count",
            "missing_project_tables",
            "orphan_project_membership_keys",
            "orphan_asset_membership_keys",
            "orphan_relationship_project_ids",
            "orphan_relationship_source_asset_ids",
            "orphan_relationship_target_asset_ids",
            "relationship_nonmember_source_ids",
            "relationship_nonmember_target_ids",
            "self_relationship_ids",
            "invalid_relationship_kind_ids",
            "duplicate_relationship_ids",
        ):
            manifest["consistency"].pop(key)

    rewrite_backup_manifest(
        current_archive,
        contract2_archive,
        tmp_path,
        contract2_shape,
    )

    verified = verify_backup(contract2_archive)

    assert verified["recovery_contract_version"] == 2
    assert verified["database"]["schema_version"] == 10


def test_verifier_accepts_pre_gate9d_contract3_schema12_and_reaudits_it(
    tmp_path: Path,
) -> None:
    _, _, database_tar, storage_tar = schema12_fixture(tmp_path)
    current_archive = tmp_path / "current-schema12.tar.gz"
    current = create_backup(
        database_tar,
        storage_tar,
        current_archive,
        "post-v5.1-gate9",
        "pre-gate9d-contract3-fixture",
    )
    assert current["recovery_contract_version"] == 5
    contract3_archive = tmp_path / "contract3-schema12.tar.gz"

    def contract3_shape(manifest: dict) -> None:
        manifest["recovery_contract_version"] = 3
        for table in ("machineprofile", "artifactmachine"):
            manifest["database"]["row_counts"].pop(table)
        for key in MACHINE_REPORT_KEYS:
            manifest["consistency"].pop(key)

    rewrite_backup_manifest(
        current_archive,
        contract3_archive,
        tmp_path,
        contract3_shape,
    )

    verified = verify_backup(contract3_archive)

    assert verified["recovery_contract_version"] == 3
    assert verified["database"]["schema_version"] == 12

    corrupt_archive = tmp_path / "contract3-schema12-corrupt.tar.gz"
    rewrite_backup_database(
        contract3_archive,
        corrupt_archive,
        tmp_path,
        "UPDATE asset SET prepared_machine_id = 'missing-machine' "
        "WHERE id = 'active'",
    )
    with pytest.raises(RecoveryError, match="consistency|inconsistent"):
        verify_backup(corrupt_archive)


def test_verifier_rejects_future_recovery_contract(tmp_path: Path) -> None:
    _, _, database_tar, storage_tar = schema8_fixture(tmp_path)
    current_archive = tmp_path / "current-future.tar.gz"
    create_backup(
        database_tar,
        storage_tar,
        current_archive,
        "post-v5.1-gate7",
        "future-contract-fixture",
    )
    future_archive = tmp_path / "future-contract.tar.gz"
    rewrite_backup_manifest(
        current_archive,
        future_archive,
        tmp_path,
        lambda manifest: manifest.__setitem__("recovery_contract_version", 999),
    )

    with pytest.raises(RecoveryError, match="recovery contract"):
        verify_backup(future_archive)


def test_verifier_accepts_legacy_format1_manifest_shape(tmp_path: Path) -> None:
    _, _, database_tar, storage_tar = backup_fixture(tmp_path)
    current_archive = tmp_path / "current.tar.gz"
    create_backup(database_tar, storage_tar, current_archive, "v5.1.0", "legacy")
    unpacked = tmp_path / "legacy-shape"
    unpacked.mkdir()
    with tarfile.open(current_archive, "r:gz") as archive:
        archive.extractall(unpacked)
    manifest_path = unpacked / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("recovery_contract_version")
    manifest["database"]["row_counts"] = {
        key: manifest["database"]["row_counts"][key]
        for key in ("folder", "asset", "assetfile", "appconfig", "mountscan")
    }
    legacy_consistency_keys = {
        "status",
        "managed_primary_present",
        "missing_managed_asset_ids",
        "external_primary_records",
        "external_state_counts",
        "related_file_present",
        "missing_related_file_ids",
        "missing_prepared_pointer_asset_ids",
        "unreferenced_storage_files",
        "derived_thumbnail_files",
    }
    manifest["consistency"] = {
        key: value
        for key, value in manifest["consistency"].items()
        if key in legacy_consistency_keys
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    checksums_path = unpacked / "checksums.sha256"
    checksums = checksums_path.read_text(encoding="utf-8").splitlines()
    manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    checksums_path.write_text(
        "\n".join(
            f"{manifest_digest}  manifest.json" if line.endswith("  manifest.json") else line
            for line in checksums
        )
        + "\n",
        encoding="utf-8",
    )
    legacy_archive = tmp_path / "legacy-format1.tar.gz"
    with tarfile.open(legacy_archive, "w:gz") as archive:
        for name in (
            "manifest.json",
            "checksums.sha256",
            "database.tar",
            "storage.tar",
        ):
            archive.add(unpacked / name, arcname=name)

    verified = verify_backup(legacy_archive)

    assert "recovery_contract_version" not in verified
    assert verified["database"]["schema_version"] == 5
