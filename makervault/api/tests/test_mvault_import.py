import json
import sqlite3
import tarfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine

import mvault_import
from migrations import run_migrations
from mvault_export import export_archive
from mvault_import import (
    MvaultImportError,
    PortableVaultImporter,
    _target_key,
    import_archive,
    main,
)
from mvault_verify import VerificationLimits, verify_archive
from test_mvault_export import fixture_database


def _portable_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "source"
    source.mkdir()
    database, storage = fixture_database(source)
    archive = tmp_path / "portable.mvault"
    export_archive(database, storage, archive, makersvault_version="5.1.0", batch_size=1)
    return archive, database, storage


def _empty_database(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    assert run_migrations(engine) == 12
    engine.dispose()


def _catalog_bytes(path: Path) -> dict[str, bytes]:
    with tarfile.open(path, "r:gz") as archive:
        return {
            member.name: archive.extractfile(member).read()
            for member in archive.getmembers()
            if member.name.startswith("mvault/catalogs/")
        }


def _assert_no_import_work(tmp_path: Path) -> None:
    assert not list(tmp_path.rglob(".mvault-import-*"))


def test_clean_import_preserves_portable_truth_and_rekeys_managed_content(tmp_path):
    archive, _, _ = _portable_fixture(tmp_path)
    database = tmp_path / "restored" / "app.db"
    storage = tmp_path / "restored" / "storage"

    class PublicationProbe(PortableVaultImporter):
        def _after_storage_publish(self):
            assert self.storage.is_dir()
            assert any(self.storage.rglob("*"))
            assert not self.database.exists()

    report = PublicationProbe(archive, database, storage, batch_size=1).restore()

    assert report["publication"]["state"] == "published"
    assert report["staged_audit"]["managed_files"] == 3
    assert report["staged_audit"]["managed_bytes"] == 13
    assert database.stat().st_mode & 0o777 == 0o600
    assert verify_archive(archive)["valid"] is True

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert list(connection.execute("PRAGMA foreign_key_check")) == []
    assert connection.execute("SELECT COUNT(*) FROM asset").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM artifactrevision").fetchone()[0] == 2
    assert connection.execute("SELECT COUNT(*) FROM project").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM machineprofile").fetchone()[0] == 1

    managed = connection.execute("SELECT * FROM artifactrevision WHERE id='r1'").fetchone()
    external = connection.execute("SELECT * FROM artifactrevision WHERE id='r2'").fetchone()
    bundle = connection.execute("SELECT * FROM assetfile WHERE id='af1'").fetchone()
    artifact = connection.execute("SELECT * FROM asset WHERE id='a1'").fetchone()
    assert managed["storage_path"] == _target_key("revisions", "r1")
    assert managed["preview_thumb_path"] == _target_key("derived", "r1")
    assert bundle["storage_path"] == _target_key("files", "af1")
    assert external["content_state"] == "unavailable"
    assert external["content_reason"] == "external_remount_required"
    assert external["source_path"] == "/definitely/missing/cube.3mf"
    assert artifact["current_revision_id"] == "r2"
    assert artifact["source_path"] == external["source_path"]
    assert artifact["storage_path"] is None
    assert artifact["prepared_file_id"] == "af1"
    assert artifact["prepared_machine_id"] == "m1"
    assert json.loads(artifact["prepared_metadata_json"]) == {"filament": "PLA", "nozzle_mm": 0.4}
    assert connection.execute("SELECT value FROM appconfig WHERE key='trash_retention'").fetchone()[0] == "month"
    assert {row[0] for row in connection.execute("SELECT key FROM appconfig")} == {
        "storage_path_template",
        "trash_retention",
    }
    for table in ("mountscan", "contenthashjob", "contenthashjobitem", "trashpurgeoperation"):
        assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    connection.close()

    assert sorted(path.read_bytes() for path in storage.rglob("*") if path.is_file()) == [b"jpg", b"notes", b"solid"]
    restored_archive = tmp_path / "restored.mvault"
    export_archive(database, storage, restored_archive, makersvault_version="5.1.0", batch_size=1)
    assert verify_archive(restored_archive)["valid"] is True
    assert _catalog_bytes(restored_archive) == _catalog_bytes(archive)
    _assert_no_import_work(tmp_path)


def test_import_accepts_an_initialized_but_empty_schema_12_target(tmp_path):
    archive, _, _ = _portable_fixture(tmp_path)
    database = tmp_path / "target" / "app.db"
    database.parent.mkdir()
    _empty_database(database)
    storage = tmp_path / "target" / "storage"
    storage.mkdir()

    assert import_archive(archive, database, storage)["publication"]["state"] == "published"
    assert sqlite3.connect(database).execute("SELECT COUNT(*) FROM asset").fetchone()[0] == 1
    _assert_no_import_work(tmp_path)


@pytest.mark.parametrize("occupied", ["database", "storage"])
def test_import_rejects_nonempty_targets_without_mutation(tmp_path, occupied):
    archive, _, _ = _portable_fixture(tmp_path)
    database = tmp_path / "target" / "app.db"
    database.parent.mkdir()
    _empty_database(database)
    storage = tmp_path / "target" / "storage"
    storage.mkdir()
    if occupied == "database":
        connection = sqlite3.connect(database)
        connection.execute("INSERT INTO folder(id,name,tags_json) VALUES ('occupied','Occupied','[]')")
        connection.commit()
        connection.close()
    else:
        (storage / "occupied").write_bytes(b"keep")
    before_database = database.read_bytes()
    before_storage = {path.relative_to(storage): path.read_bytes() for path in storage.rglob("*") if path.is_file()}

    with pytest.raises(MvaultImportError, match="not empty|empty directory"):
        import_archive(archive, database, storage)

    assert database.read_bytes() == before_database
    assert {path.relative_to(storage): path.read_bytes() for path in storage.rglob("*") if path.is_file()} == before_storage
    _assert_no_import_work(tmp_path)


def test_invalid_archive_and_limits_leave_target_absent(tmp_path):
    invalid = tmp_path / "invalid.mvault"
    invalid.write_bytes(b"not an archive")
    database = tmp_path / "target" / "app.db"
    storage = tmp_path / "target" / "storage"

    with pytest.raises(MvaultImportError, match="verification failed"):
        import_archive(invalid, database, storage)
    assert not database.exists()
    assert not storage.exists()

    archive, _, _ = _portable_fixture(tmp_path)
    with pytest.raises(MvaultImportError, match="verification failed"):
        import_archive(archive, database, storage, limits=VerificationLimits(max_members=1))
    assert not database.exists()
    assert not storage.exists()
    _assert_no_import_work(tmp_path)


def test_capacity_failure_while_staging_payload_leaves_target_absent(tmp_path, monkeypatch):
    archive, _, _ = _portable_fixture(tmp_path)
    database = tmp_path / "target" / "app.db"
    storage = tmp_path / "target" / "storage"
    real_copy = mvault_import._stream_copy
    calls = 0

    def fail_payload_copy(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(28, "No space left on device")
        return real_copy(source, destination)

    monkeypatch.setattr(mvault_import, "_stream_copy", fail_payload_copy)
    with pytest.raises(MvaultImportError, match="No space left"):
        import_archive(archive, database, storage)

    assert not database.exists()
    assert not storage.exists()
    _assert_no_import_work(tmp_path)


def test_failure_after_storage_publication_restores_exact_empty_target(tmp_path):
    archive, _, _ = _portable_fixture(tmp_path)
    database = tmp_path / "target" / "app.db"
    database.parent.mkdir()
    _empty_database(database)
    storage = tmp_path / "target" / "storage"
    storage.mkdir()
    before_database = database.read_bytes()

    class FailAfterStorage(PortableVaultImporter):
        def _after_storage_publish(self):
            raise RuntimeError("injected publication failure")

    with pytest.raises(MvaultImportError, match="injected publication failure"):
        FailAfterStorage(archive, database, storage).restore()

    assert database.read_bytes() == before_database
    assert storage.is_dir() and not list(storage.iterdir())
    _assert_no_import_work(tmp_path)


def test_keyboard_interrupt_after_storage_publication_rolls_back(tmp_path):
    archive, _, _ = _portable_fixture(tmp_path)
    database = tmp_path / "target" / "app.db"
    storage = tmp_path / "target" / "storage"

    class InterruptAfterStorage(PortableVaultImporter):
        def _after_storage_publish(self):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        InterruptAfterStorage(archive, database, storage).restore()

    assert not database.exists()
    assert not storage.exists()
    _assert_no_import_work(tmp_path)


def test_next_invocation_recovers_an_interrupted_storage_first_publication(tmp_path):
    archive, _, _ = _portable_fixture(tmp_path)
    database = tmp_path / "target" / "app.db"
    storage = tmp_path / "target" / "storage"

    class SimulatedCrash(PortableVaultImporter):
        def _after_storage_publish(self):
            raise RuntimeError("simulated process death")

        def _rollback_journal(self, value):
            pass

    with pytest.raises(MvaultImportError, match="simulated process death"):
        SimulatedCrash(archive, database, storage).restore()
    assert storage.exists()
    assert not database.exists()
    assert list(tmp_path.rglob(".mvault-import-*.json"))

    assert import_archive(archive, database, storage)["publication"]["state"] == "published"
    assert sqlite3.connect(database).execute("SELECT COUNT(*) FROM asset").fetchone()[0] == 1
    _assert_no_import_work(tmp_path)


def test_import_rejects_artifact_current_revision_projection_mismatch(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    source_database, source_storage = fixture_database(source)
    connection = sqlite3.connect(source_database)
    connection.execute("UPDATE asset SET preview_source='embedded' WHERE id='a1'")
    connection.commit()
    connection.close()
    archive = tmp_path / "mismatch.mvault"
    export_archive(source_database, source_storage, archive, makersvault_version="5.1.0")
    assert verify_archive(archive)["valid"] is True

    with pytest.raises(MvaultImportError, match="preview does not match"):
        import_archive(archive, tmp_path / "target" / "app.db", tmp_path / "target" / "storage")
    assert not (tmp_path / "target" / "app.db").exists()
    assert not (tmp_path / "target" / "storage").exists()
    _assert_no_import_work(tmp_path)


def test_cli_requires_explicit_stopped_empty_confirmation(tmp_path, capsys):
    archive, _, _ = _portable_fixture(tmp_path)
    arguments = [
        "--archive", str(archive),
        "--database", str(tmp_path / "target" / "app.db"),
        "--storage", str(tmp_path / "target" / "storage"),
    ]
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2
    assert "--confirm-stopped-empty is required" in capsys.readouterr().err

    assert main([*arguments, "--confirm-stopped-empty", "--batch-size", "1", "--progress"]) == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["publication"]["state"] == "published"
    assert report["external_references"] == {
        "records": 1, "requires_remount": 1, "restored_unavailable": 1,
    }
    assert report["source_verification"]["external"]["unavailable"] == 1
    events = [json.loads(line.removeprefix("mvault-progress ")) for line in captured.err.splitlines()]
    assert events[0]["phase"] == "import_started"
    assert events[-1]["phase"] == "import_complete"
    assert events[-1]["external_references"] == 1


def test_cli_cancellation_has_stable_exit_code(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mvault_import, "import_archive", lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert main([
        "--archive", str(tmp_path / "source.mvault"),
        "--database", str(tmp_path / "app.db"),
        "--storage", str(tmp_path / "storage"),
        "--confirm-stopped-empty",
    ]) == 130
    assert "import cancelled" in capsys.readouterr().err


def test_provider_keys_are_portable_and_do_not_embed_record_ids():
    key = _target_key("revisions", "unsafe:windows.id")
    assert key.startswith("revisions/") and key.endswith("/primary")
    assert "unsafe" not in key and ":" not in key
    assert len(key.split("/")[1]) == 64


def test_import_rejects_overlapping_or_symbolic_link_targets(tmp_path):
    archive, _, _ = _portable_fixture(tmp_path)
    with pytest.raises(ValueError, match="must not overlap"):
        PortableVaultImporter(archive, tmp_path / "vault" / "app.db", tmp_path / "vault")

    real_storage = tmp_path / "real-storage"
    real_storage.mkdir()
    linked_storage = tmp_path / "linked-storage"
    linked_storage.symlink_to(real_storage, target_is_directory=True)
    with pytest.raises(MvaultImportError, match="empty directory or absent"):
        import_archive(archive, tmp_path / "target" / "app.db", linked_storage)
    assert not list(real_storage.iterdir())


def test_recovery_journal_rejects_untrusted_cleanup_paths(tmp_path):
    archive = tmp_path / "unused.mvault"
    database = tmp_path / "target" / "app.db"
    storage = tmp_path / "target" / "storage"
    importer = PortableVaultImporter(archive, database, storage)
    operation_id = "00000000-0000-0000-0000-000000000001"
    victim = tmp_path / "victim" / "app.db"
    victim.parent.mkdir()
    victim.write_bytes(b"must survive")
    journal = {
        "version": 1,
        "operation_id": operation_id,
        "archive_sha256": "0" * 64,
        "database": str(database.resolve()),
        "storage": str(storage.resolve()),
        "staged_database": str(victim),
        "staged_storage": str(storage.parent / ".mvault-import-storage-attacker"),
        "database_backup": str(database.parent / f".mvault-import-{operation_id}.db.empty"),
        "storage_backup": str(storage.parent / f".mvault-import-{operation_id}.storage.empty"),
        "database_existed": False,
        "storage_existed": False,
        "state": "prepared",
    }
    importer.journal.write_text(json.dumps(journal))

    with pytest.raises(MvaultImportError, match="unsafe recovery paths"):
        importer.restore()
    assert victim.read_bytes() == b"must survive"
    assert importer.journal.exists()
