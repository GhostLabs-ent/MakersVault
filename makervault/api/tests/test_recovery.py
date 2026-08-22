import io
import hashlib
import json
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


def tar_directory(source: Path, output: Path) -> None:
    with tarfile.open(output, "w") as archive:
        archive.add(source, arcname=".", recursive=True)


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
    assert manifest["recovery_contract_version"] == 2
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
