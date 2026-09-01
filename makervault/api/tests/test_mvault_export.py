import hashlib
import json
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine

import mvault_export
from identity_service import bootstrap_initial_administrator
from migrations import run_migrations
from mvault_export import MvaultExportError, PortableVaultExporter, export_archive
from mvault_verify import verify_archive


NOW = "2026-08-31T12:00:00Z"


def fixture_database(tmp_path: Path) -> tuple[Path, Path]:
    database = tmp_path / "app.db"
    engine = create_engine(f"sqlite:///{database}")
    assert run_migrations(engine) == 13
    engine.dispose()
    storage = tmp_path / "storage"
    (storage / "revisions/a1/r1").mkdir(parents=True)
    (storage / "revisions/a1/r1/model.stl").write_bytes(b"solid")
    (storage / "bundles/a1/af1").mkdir(parents=True)
    (storage / "bundles/a1/af1/print.gcode").write_bytes(b"notes")
    (storage / "thumbs/revisions").mkdir(parents=True)
    (storage / "thumbs/revisions/r1.jpg").write_bytes(b"jpg")

    connection = sqlite3.connect(database)
    connection.execute("INSERT INTO folder(id,name,tags_json,parent_id) VALUES ('f1','Fixtures','[\"golden\"]',NULL)")
    connection.execute(
        """INSERT INTO machineprofile(
          id,name,category,manufacturer,model,location,notes,created_at,updated_at,archived_at
        ) VALUES ('m1','P1S','fdm_printer','Bambu Lab','P1S','Lab',NULL,?,?,NULL)""",
        (NOW, NOW),
    )
    connection.execute(
        """INSERT INTO asset(
          id,name,filename,mime,size,tags_json,title,notes,creator,collection,folder_id,
          source_path,storage_path,supporting_file_count,prepared_file_id,prepared_metadata_json,
          prepared_machine_id,preview_status,preview_reason,preview_attempts,preview_policy_version,
          preview_updated_at,preview_source,current_revision_id,current_thumb_path,deleted_at,
          trash_original_folder_id,trash_original_folder_name
        ) VALUES (
          'a1','Cube','cube.3mf','model/3mf',1234,'[\"cube\",\"calibration\"]','Cube','Fixture',
          'MakersVault','Calibration','f1','/media/models/cube.3mf',NULL,99,'af1',
          '{\"filament\":\"PLA\",\"nozzle_mm\":0.4}','m1','ready',NULL,0,1,?,'primary',
          'r2',NULL,NULL,NULL,NULL
        )""",
        (NOW,),
    )
    connection.execute(
        """INSERT INTO artifactrevision(
          id,asset_id,revision_number,created_at,origin_revision_id,filename,mime,size,sha256,
          observed_sha256,content_state,content_reason,content_checked_at,storage_path,source_path,
          change_note,prepared_file_id,prepared_metadata_json,prepared_machine_id,preview_status,
          preview_reason,preview_attempts,preview_policy_version,preview_updated_at,preview_source,
          preview_thumb_path
        ) VALUES (
          'r1','a1',1,?,NULL,'model.stl','model/stl',5,
          '4b3d4a0dd732f791ca897e95488b5d63caf128d8691b6f5bbc54f866b9b97054',
          NULL,'ready',NULL,?,'revisions/a1/r1/model.stl',NULL,'Initial','af1','{\"format\":\"gcode\"}',
          'm1','ready',NULL,0,1,?,'embedded','thumbs/revisions/r1.jpg'
        )""",
        (NOW, NOW, NOW),
    )
    connection.execute(
        """INSERT INTO artifactrevision(
          id,asset_id,revision_number,created_at,origin_revision_id,filename,mime,size,sha256,
          content_state,storage_path,source_path,change_note,prepared_file_id,prepared_metadata_json,
          prepared_machine_id,preview_status,
          preview_attempts,preview_policy_version,preview_updated_at,preview_source
        ) VALUES (
          'r2','a1',2,?,'r1','cube.3mf','model/3mf',1234,NULL,'ready',NULL,
          '/definitely/missing/cube.3mf','External layout','af1',
          '{\"filament\":\"PLA\",\"nozzle_mm\":0.4}','m1','ready',0,1,?,'primary'
        )""",
        (NOW, NOW),
    )
    connection.execute(
        """INSERT INTO assetfile(id,asset_id,filename,mime,size,role,storage_path,metadata_json,revision_id)
        VALUES ('af1','a1','print.gcode','text/x.gcode',5,'prepared','bundles/a1/af1/print.gcode','{\"format\":\"gcode\"}','r1')"""
    )
    connection.execute(
        """INSERT INTO project(id,name,notes,creator,source_url,license,tags_json,created_at,updated_at,deleted_at)
        VALUES ('p1','Fixture Project',NULL,'MakersVault',NULL,NULL,'[\"test\"]',?,?,NULL)""",
        (NOW, NOW),
    )
    connection.execute("INSERT INTO projectmembership(project_id,asset_id,created_at) VALUES ('p1','a1',?)", (NOW,))
    connection.execute("INSERT INTO artifactmachine(asset_id,machine_id,created_at) VALUES ('a1','m1',?)", (NOW,))
    connection.execute("INSERT INTO appconfig(key,value) VALUES ('trash_retention','month')")
    connection.commit()
    connection.close()
    return database, storage


def archive_json(archive: Path, member: str):
    with tarfile.open(archive, "r:gz") as source:
        extracted = source.extractfile(member)
        assert extracted is not None
        return json.loads(extracted.read())


def archive_jsonl(archive: Path, member: str):
    with tarfile.open(archive, "r:gz") as source:
        extracted = source.extractfile(member)
        assert extracted is not None
        return [json.loads(line) for line in extracted]


def test_streaming_export_produces_verified_v1_without_mutating_source(tmp_path):
    database, storage = fixture_database(tmp_path)
    output = tmp_path / "portable.mvault"
    before_database = database.read_bytes()

    report = export_archive(database, storage, output, makersvault_version="5.1.0", batch_size=1)

    assert report == verify_archive(output)
    assert report["valid"] is True
    assert database.read_bytes() == before_database
    assert output.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".mvault-export-*"))

    header = archive_json(output, "mvault/header.json")
    assert header["source"] == {"makersvault_version": "5.1.0", "schema_version": 13}
    assert header["optional_features"] == ["derived-thumbnails"]
    artifacts = archive_jsonl(output, "mvault/catalogs/artifacts.jsonl")
    assert artifacts[0]["supporting_file_count"] == 0
    revisions = archive_jsonl(output, "mvault/catalogs/revisions.jsonl")
    assert revisions[0]["content"]["ownership"] == "managed"
    assert revisions[0]["sha256"] == "4b3d4a0dd732f791ca897e95488b5d63caf128d8691b6f5bbc54f866b9b97054"
    assert revisions[1]["content"] == {
        "member": None,
        "ownership": "external",
        "source_path": "/definitely/missing/cube.3mf",
        "state": "unavailable",
    }
    manifest = archive_json(output, "mvault/manifest.json")
    assert manifest["content"] == {
        "authoritative_bytes": 10,
        "authoritative_files": 2,
        "complete_managed_content": True,
        "derived_bytes": 3,
        "derived_files": 1,
    }
    assert manifest["external"]["unavailable"] == 1


def test_schema13_identity_is_excluded_from_portable_v1(tmp_path):
    database, storage = fixture_database(tmp_path)
    engine = create_engine(f"sqlite:///{database}")
    bootstrap_initial_administrator(
        engine,
        username="portable-admin",
        password="portable-test-password",
    )
    engine.dispose()
    output = tmp_path / "identity-excluded.mvault"

    export_archive(database, storage, output, makersvault_version="5.1.0", batch_size=1)

    with tarfile.open(output, "r:gz") as archive:
        member_names = {member.name for member in archive.getmembers()}
        archive_bytes = b"".join(
            source.read()
            for member in archive.getmembers()
            if (source := archive.extractfile(member)) is not None
        )
    assert not any("user" in name or "identity" in name for name in member_names)
    assert b"portable-admin" not in archive_bytes
    assert b"portable-test-password" not in archive_bytes


def test_export_never_overwrites_existing_output(tmp_path):
    database, storage = fixture_database(tmp_path)
    output = tmp_path / "portable.mvault"
    output.write_bytes(b"keep-me")

    with pytest.raises(MvaultExportError, match="output already exists"):
        export_archive(database, storage, output)

    assert output.read_bytes() == b"keep-me"


def test_missing_managed_content_fails_without_publication(tmp_path):
    database, storage = fixture_database(tmp_path)
    (storage / "revisions/a1/r1/model.stl").unlink()
    output = tmp_path / "portable.mvault"

    with pytest.raises(MvaultExportError, match="missing or not a regular file"):
        export_archive(database, storage, output)

    assert not output.exists()
    assert not list(tmp_path.glob(".mvault-export-*"))


def test_digest_mismatch_fails_without_publication(tmp_path):
    database, storage = fixture_database(tmp_path)
    (storage / "revisions/a1/r1/model.stl").write_bytes(b"other")
    output = tmp_path / "portable.mvault"

    with pytest.raises(MvaultExportError, match="digest.*does not match"):
        export_archive(database, storage, output)

    assert not output.exists()


def test_interrupted_catalog_write_cleans_partial_archive(tmp_path, monkeypatch):
    database, storage = fixture_database(tmp_path)
    output = tmp_path / "portable.mvault"
    exporter = PortableVaultExporter(database, storage, output, makersvault_version="5.1.0")

    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(exporter, "_write_catalog", interrupt)
    with pytest.raises(KeyboardInterrupt):
        exporter.export()

    assert not output.exists()
    assert not list(tmp_path.glob(".mvault-export-*"))


def test_capacity_failure_cleans_partial_archive(tmp_path, monkeypatch):
    database, storage = fixture_database(tmp_path)
    output = tmp_path / "portable.mvault"
    exporter = PortableVaultExporter(database, storage, output, makersvault_version="5.1.0")

    def no_space(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(exporter, "_write_archive", no_space)
    with pytest.raises(MvaultExportError, match="No space left"):
        exporter.export()

    assert not output.exists()
    assert not list(tmp_path.glob(".mvault-export-*"))


def test_failed_independent_verification_prevents_publication(tmp_path, monkeypatch):
    database, storage = fixture_database(tmp_path)
    output = tmp_path / "portable.mvault"

    def reject(_archive):
        raise ValueError("simulated verifier rejection")

    monkeypatch.setattr(mvault_export, "verify_archive", reject)
    with pytest.raises(MvaultExportError, match="simulated verifier rejection"):
        export_archive(database, storage, output)

    assert not output.exists()
    assert not list(tmp_path.glob(".mvault-export-*"))


def test_atomic_publication_does_not_overwrite_racing_output(tmp_path, monkeypatch):
    database, storage = fixture_database(tmp_path)
    output = tmp_path / "portable.mvault"
    real_verify = mvault_export.verify_archive

    def verify_then_race(archive):
        report = real_verify(archive)
        output.write_bytes(b"created-by-another-process")
        return report

    monkeypatch.setattr(mvault_export, "verify_archive", verify_then_race)
    with pytest.raises(MvaultExportError, match="appeared during export"):
        export_archive(database, storage, output)

    assert output.read_bytes() == b"created-by-another-process"
    assert not list(tmp_path.glob(".mvault-export-*"))


def test_unknown_schema_fails_before_archive_creation(tmp_path):
    database, storage = fixture_database(tmp_path)
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO schema_migration(version, name) VALUES (14, 'future_schema')"
    )
    connection.commit()
    connection.close()
    output = tmp_path / "portable.mvault"

    with pytest.raises(MvaultExportError, match="schema 14"):
        export_archive(database, storage, output)

    assert not output.exists()


def test_exclusive_source_lock_rejects_busy_database(tmp_path):
    database, storage = fixture_database(tmp_path)
    writer = sqlite3.connect(database, isolation_level=None)
    writer.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(MvaultExportError, match="database is busy"):
            export_archive(database, storage, tmp_path / "portable.mvault")
    finally:
        writer.rollback()
        writer.close()


def test_small_batches_export_large_catalog_without_semantic_change(tmp_path):
    database, storage = fixture_database(tmp_path)
    connection = sqlite3.connect(database)
    connection.executemany(
        "INSERT INTO folder(id,name,tags_json,parent_id) VALUES (?,?,?,NULL)",
        [(f"folder-{index:04d}", f"Folder {index}", "[]") for index in range(250)],
    )
    connection.commit()
    connection.close()
    output = tmp_path / "portable.mvault"

    export_archive(database, storage, output, batch_size=3)

    folders = archive_jsonl(output, "mvault/catalogs/folders.jsonl")
    assert len(folders) == 251
    assert [row["id"] for row in folders] == sorted(row["id"] for row in folders)


def test_large_payload_is_read_in_bounded_chunks(tmp_path, monkeypatch):
    database, storage = fixture_database(tmp_path)
    payload = b"0123456789abcdef" * (384 * 1024)
    primary = storage / "revisions/a1/r1/model.stl"
    primary.write_bytes(payload)
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE artifactrevision SET size=?,sha256=? WHERE id='r1'",
        (len(payload), hashlib.sha256(payload).hexdigest()),
    )
    connection.commit()
    connection.close()
    largest_read = 0
    original = mvault_export.LocalContentStore.open_read

    class GuardedReader:
        def __init__(self, source):
            self.source = source

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.source.close()

        def read(self, size=-1):
            nonlocal largest_read
            if size < 0 or size > 1024 * 1024:
                raise AssertionError(f"unbounded payload read requested: {size}")
            largest_read = max(largest_read, size)
            return self.source.read(size)

    def guarded_open(store, key):
        return GuardedReader(original(store, key))

    monkeypatch.setattr(mvault_export.LocalContentStore, "open_read", guarded_open)
    output = tmp_path / "portable.mvault"

    export_archive(database, storage, output, batch_size=2)

    assert 0 < largest_read <= 1024 * 1024
    assert verify_archive(output)["valid"] is True


def test_cli_requires_explicit_stopped_confirmation(tmp_path):
    database, storage = fixture_database(tmp_path)
    script = Path(__file__).parents[1] / "mvault_export.py"
    result = subprocess.run(
        [sys.executable, str(script), "--database", str(database), "--storage", str(storage), "--output", str(tmp_path / "portable.mvault")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "--confirm-stopped is required" in result.stderr


def test_cli_exports_only_after_confirmation(tmp_path):
    database, storage = fixture_database(tmp_path)
    output = tmp_path / "portable.mvault"
    script = Path(__file__).parents[1] / "mvault_export.py"
    result = subprocess.run(
        [
            sys.executable, str(script), "--database", str(database), "--storage", str(storage),
            "--output", str(output), "--confirm-stopped", "--makersvault-version", "5.1.0", "--progress",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)["verification"]
    assert report["valid"] is True
    assert report["external"] == {
        "available": 0, "changed": 0, "failed": 0, "pending": 0,
        "records": 1, "unavailable": 1,
    }
    events = [json.loads(line.removeprefix("mvault-progress ")) for line in result.stderr.splitlines()]
    assert events[0]["phase"] == "export_started"
    assert events[-1]["phase"] == "export_complete"
    assert events[-1]["external_records"] == 1
    assert verify_archive(output)["valid"] is True


def test_cli_cancellation_has_stable_exit_code(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mvault_export, "export_archive", lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert mvault_export.main([
        "--database", str(tmp_path / "app.db"),
        "--storage", str(tmp_path / "storage"),
        "--output", str(tmp_path / "out.mvault"),
        "--confirm-stopped",
    ]) == 130
    assert "export cancelled" in capsys.readouterr().err
