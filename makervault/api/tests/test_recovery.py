import io
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
