"""Tests for importing a mounted source tree (Mf-k0kf).

The suite shares one database for the whole session, so every test here starts
from a snapshot of the rows and removes what it created. ``missing_since`` is
also restored, because some tests run scans of a temp storage root and a scan
makes every other test's managed rows look absent.
"""
from math import ceil
from pathlib import Path
from typing import Optional

import pytest
from sqlalchemy import event
from sqlmodel import Session, select

import audit
import library_scan
import mount_import
from db import engine
from library_scan import scan_storage_root
from migrations import run_migrations
from models import AppConfig, Asset, AuditEvent, Folder, ImportRun
from settings_service import set_mount_import_enabled


@pytest.fixture(scope="module", autouse=True)
def _schema() -> None:
    """Create the schema the way the app lifespan does."""
    run_migrations(engine)


def _write(root: Path, rel_path: str, payload: bytes = b"solid x\n") -> Path:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _asset_rows() -> list:
    with Session(engine) as session:
        return list(session.exec(select(Asset)).all())


def _asset_ids() -> set:
    with Session(engine) as session:
        return set(session.exec(select(Asset.id)).all())


def _folder_ids() -> set:
    with Session(engine) as session:
        return set(session.exec(select(Folder.id)).all())


def _folders() -> list:
    with Session(engine) as session:
        return list(session.exec(select(Folder)).all())


def _row_by_storage_path() -> dict:
    """Rows keyed by storage path; other modules' rows are told apart by path."""
    return {asset.storage_path: asset for asset in _asset_rows() if asset.storage_path}


def _tree(root: Path) -> set:
    """Every file under ``root``, as a relative posix path."""
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def _clear_enabled_setting() -> None:
    with Session(engine) as session:
        row = session.get(AppConfig, "mount_import_enabled")
        if row:
            session.delete(row)
            session.commit()


@pytest.fixture
def mount_and_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A temp mount and a temp storage root, with every row they create removed."""
    mount = tmp_path / "mount"
    storage = tmp_path / "storage"
    mount.mkdir()
    storage.mkdir()
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_PATH", str(mount))
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_EXTS_RAW", "")
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_INCLUDE_HIDDEN", False)
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_COPY", True)
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_ENABLED", True)
    # the module global decides, never a leftover row in the shared settings table
    monkeypatch.setattr(mount_import, "get_mount_import_copy", lambda default: default)
    monkeypatch.setattr(library_scan, "STORAGE", storage)

    folders_before = _folder_ids()
    missing_before = {asset.id: asset.missing_since for asset in _asset_rows()}
    with Session(engine) as session:
        runs_before = {run.id for run in session.exec(select(ImportRun))}
    yield mount, storage
    with Session(engine) as session:
        for run in list(session.exec(select(ImportRun))):
            if run.id not in runs_before:
                session.delete(run)
        for folder in list(session.exec(select(Folder))):
            if folder.id not in folders_before:
                session.delete(folder)
        for asset in list(session.exec(select(Asset))):
            if asset.id not in missing_before:
                session.delete(asset)
            else:
                # a scan of the temp storage root flagged rows it could not see
                asset.missing_since = missing_before[asset.id]
        session.commit()


def _require(state) -> None:
    """A run that had to start must not have come back as ``None``."""
    assert state is not None, "the mount import did not run"


def _reference_row(mount: Path, rel_path: str) -> Optional[Asset]:
    source = (mount / rel_path).as_posix()
    for asset in _asset_rows():
        if asset.source_path == source:
            return asset
    return None


@pytest.mark.parametrize("copy_files", [True, False], ids=["copy", "reference"])
def test_mount_rows_are_stamped_as_mount_imports_with_no_actor(
    mount_and_storage, monkeypatch: pytest.MonkeyPatch, copy_files: bool
) -> None:
    """A mount import is background work: no principal, and no creation event."""
    mount, _storage = mount_and_storage
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_COPY", copy_files)
    _write(mount, "a/part.stl")

    _require(mount_import.scan_mount_imports())

    rows = [asset for asset in _asset_rows() if asset.filename == "part.stl"]
    assert len(rows) == 1, [asset.filename for asset in rows]
    row = rows[0]
    assert (row.created_by, row.created_via) == (None, "mount-import")
    with Session(engine) as session:
        events = list(
            session.exec(
                select(AuditEvent).where(AuditEvent.action == audit.ASSET_CREATE, AuditEvent.target == row.id)
            )
        )
    assert events == []


# --- copy mode mirrors the tree ----------------------------------------------


def test_copy_mode_mirrors_the_mount_tree(mount_and_storage) -> None:
    mount, storage = mount_and_storage
    _write(mount, "a/b/part.stl")
    _write(mount, "a/other.stl")
    _write(mount, "top.stl")

    state = mount_import.scan_mount_imports()

    _require(state)
    assert state.registered == 3
    rows = _row_by_storage_path()
    for rel in ("a/b/part.stl", "a/other.stl", "top.stl"):
        assert rel in rows, f"{rel} was not registered"
        assert (storage / rel).is_file()
        assert rows[rel].source_path is None
        assert rows[rel].is_reference == 0
    # the bytes land where the mount has them, never at a templated path
    assert _tree(storage) == {"a/b/part.stl", "a/other.stl", "top.stl"}

    folders = {folder.name: folder for folder in _folders()}
    assert folders["a"].storage_path == "a"
    assert folders["b"].storage_path == "a/b"
    assert folders["b"].parent_id == folders["a"].id
    assert rows["top.stl"].folder_id is None
    assert rows["a/other.stl"].folder_id == folders["a"].id
    assert rows["a/b/part.stl"].folder_id == folders["b"].id


# --- reference mode ----------------------------------------------------------


def test_reference_mode_registers_rows_without_copying(mount_and_storage, monkeypatch) -> None:
    mount, storage = mount_and_storage
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_COPY", False)
    _write(mount, "a/b/part.stl")
    _write(mount, "a/other.stl")
    _write(mount, "top.stl")

    state = mount_import.scan_mount_imports()

    _require(state)
    assert state.registered == 3
    for rel in ("a/b/part.stl", "a/other.stl", "top.stl"):
        row = _reference_row(mount, rel)
        assert row is not None, f"{rel} was not registered"
        assert row.storage_path is None
        assert row.is_reference == 1
        assert row.source_path == (mount / rel).as_posix()
        assert row.size > 0
    # nothing is copied
    assert _tree(storage) == set()

    folders = {folder.name: folder for folder in _folders()}
    assert folders["a"].storage_path is None
    assert folders["b"].storage_path is None


def test_reference_asset_survives_its_source_disappearing(mount_and_storage, monkeypatch) -> None:
    mount, _storage = mount_and_storage
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_COPY", False)
    source = _write(mount, "a/part.stl")

    _require(mount_import.scan_mount_imports())
    row = _reference_row(mount, "a/part.stl")
    assert row is not None
    assert row.missing_since is None
    asset_id = row.id

    scan_storage_root()
    assert _reference_row(mount, "a/part.stl").missing_since is None

    source.unlink()
    first = scan_storage_root()
    gone = _reference_row(mount, "a/part.stl")
    assert gone is not None, "a reference row must never be deleted"
    assert gone.id == asset_id
    assert gone.missing_since is not None

    # a reference row is flagged but never counted as a missing managed file
    second = scan_storage_root()
    assert second.missing == first.missing


# --- idempotency -------------------------------------------------------------


def test_reimport_registers_nothing(mount_and_storage) -> None:
    mount, storage = mount_and_storage
    _write(mount, "a/part.stl")
    _write(mount, "a/other.stl")
    _write(mount, "top.stl")

    _require(mount_import.scan_mount_imports())
    assets = len(_asset_rows())
    folders = len(_folders())
    tree = _tree(storage)

    again = mount_import.scan_mount_imports()

    _require(again)
    assert again.registered == 0
    assert again.known == 3
    assert len(_asset_rows()) == assets
    assert len(_folders()) == folders
    assert _tree(storage) == tree


def test_reference_reimport_registers_nothing(mount_and_storage, monkeypatch) -> None:
    mount, storage = mount_and_storage
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_COPY", False)
    _write(mount, "a/part.stl")
    _write(mount, "a/other.stl")
    _write(mount, "top.stl")

    _require(mount_import.scan_mount_imports())
    assets = len(_asset_rows())
    folders = len(_folders())

    again = mount_import.scan_mount_imports()

    _require(again)
    assert again.registered == 0
    assert again.known == 3
    assert len(_asset_rows()) == assets
    assert len(_folders()) == folders
    assert _tree(storage) == set()


def test_switching_modes_registers_nothing(mount_and_storage, monkeypatch) -> None:
    mount, _storage = mount_and_storage
    _write(mount, "a/part.stl")
    _write(mount, "top.stl")

    # first mode wins: reference rows are not converted by a copy run ...
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_COPY", False)
    _require(mount_import.scan_mount_imports())
    assets = len(_asset_rows())

    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_COPY", True)
    switched = mount_import.scan_mount_imports()

    _require(switched)
    assert switched.registered == 0
    assert switched.failed == 0
    assert len(_asset_rows()) == assets


def test_switching_modes_the_other_way_registers_nothing(mount_and_storage, monkeypatch) -> None:
    mount, storage = mount_and_storage
    _write(mount, "a/part.stl")
    _write(mount, "top.stl")

    # ... and a copy run is not re-imported as a reference either
    _require(mount_import.scan_mount_imports())
    assets = len(_asset_rows())
    tree = _tree(storage)

    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_COPY", False)
    switched = mount_import.scan_mount_imports()

    _require(switched)
    assert switched.registered == 0
    assert switched.failed == 0
    assert len(_asset_rows()) == assets
    assert _tree(storage) == tree


# --- per-file policy ---------------------------------------------------------


def test_same_stem_collision_fails_only_that_row(mount_and_storage) -> None:
    mount, _storage = mount_and_storage
    _write(mount, "a/part.stl")
    _write(mount, "a/part.step", b"step a\n")
    before = _asset_ids()

    state = mount_import.scan_mount_imports()

    _require(state)
    assert state.registered == 1
    assert state.failed == 1
    assert len(state.errors) == 1
    assert state.errors[0].startswith(("a/part.stl", "a/part.step"))
    created = [asset for asset in _asset_rows() if asset.id not in before]
    assert len(created) == 1
    assert created[0].storage_path in {"a/part.stl", "a/part.step"}


def test_hidden_files_and_unlisted_extensions_are_skipped(mount_and_storage) -> None:
    mount, _storage = mount_and_storage
    _write(mount, ".hidden.stl")
    _write(mount, "notes.txt", b"notes\n")
    _write(mount, "part.stl")
    before = _asset_ids()

    state = mount_import.scan_mount_imports()

    _require(state)
    assert state.registered == 1
    assert state.ignored == 2
    created = {asset.storage_path for asset in _asset_rows() if asset.id not in before}
    assert created == {"part.stl"}


# --- startup gate ------------------------------------------------------------


def test_startup_import_is_opt_in(mount_and_storage, monkeypatch) -> None:
    mount, _storage = mount_and_storage
    _write(mount, "part.stl")

    with Session(engine) as session:
        previous = session.get(AppConfig, "mount_import_enabled")
        previous_value = previous.value if previous else None

    def restore_setting() -> None:
        with Session(engine) as session:
            row = session.get(AppConfig, "mount_import_enabled")
            if previous_value is None:
                if row:
                    session.delete(row)
            elif row:
                row.value = previous_value
            else:
                session.add(AppConfig(key="mount_import_enabled", value=previous_value))
            session.commit()

    try:
        # no mount configured: nothing runs, whatever the setting says
        monkeypatch.setattr(mount_import, "MOUNT_IMPORT_PATH", "")
        assert mount_import.mount_import_should_run() is False
        before = _asset_ids()
        assert mount_import.scan_mount_imports() is None
        assert _asset_ids() == before

        # configuring a mount path is the opt-in, and the env default says yes
        monkeypatch.setattr(mount_import, "MOUNT_IMPORT_PATH", str(mount))
        _clear_enabled_setting()
        assert mount_import.mount_import_should_run() is True

        # the database setting is the opt-out
        set_mount_import_enabled(False)
        assert mount_import.mount_import_should_run() is False
    finally:
        restore_setting()


def test_reference_mode_refuses_a_mount_inside_storage(mount_and_storage, monkeypatch) -> None:
    _mount, storage = mount_and_storage
    inside = storage / "sub"
    inside.mkdir()
    payload = _write(inside, "part.stl")
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_COPY", False)
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_PATH", str(inside))
    before = _asset_ids()

    assert mount_import.scan_mount_imports() is None
    assert _asset_ids() == before
    assert payload.read_bytes() == b"solid x\n"


def test_copy_mode_refuses_a_mount_that_contains_the_storage_root(mount_and_storage, monkeypatch) -> None:
    _mount, storage = mount_and_storage
    _write(storage.parent, "outer.stl")
    _write(storage, "already.stl")
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_PATH", str(storage.parent))
    before = _asset_ids()
    tree = _tree(storage)

    # copy mode would import the library into itself: storage/foo.stl and a
    # deeper storage/storage/... mirror on every run
    assert mount_import.scan_mount_imports() is None

    assert _asset_ids() == before
    assert _tree(storage) == tree


def test_copy_mode_tolerates_the_mount_being_the_storage_root(mount_and_storage, monkeypatch) -> None:
    _mount, storage = mount_and_storage
    payload = _write(storage, "part.stl")
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_PATH", str(storage))
    before = _asset_ids()

    state = mount_import.scan_mount_imports()

    _require(state)
    assert state.registered == 1
    created = [asset for asset in _asset_rows() if asset.id not in before]
    assert [asset.storage_path for asset in created] == ["part.stl"]
    # the file already lay where it belongs: no copy, no bytes changed
    assert payload.read_bytes() == b"solid x\n"
    assert _tree(storage) == {"part.stl"}


# --- batching and isolation --------------------------------------------------


def test_copy_batch_retry_rematerialises_folders_with_paths(mount_and_storage, monkeypatch) -> None:
    """A retried copy batch re-runs ``prepare``, so its folders keep their paths."""
    mount, storage = mount_and_storage
    _write(mount, "a/b/part.stl")
    _write(mount, "a/other.stl")
    folders_before = _folder_ids()

    real_commit = Session.commit
    # a dict, so the closure can count commits without a `nonlocal` declaration;
    # the first commit is begin_run's run-row transaction, so fail the first
    # registration batch instead.
    calls = {"count": 0}

    def flaky_commit(session) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("database is locked")
        real_commit(session)

    monkeypatch.setattr(Session, "commit", flaky_commit)
    state = mount_import.scan_mount_imports()

    _require(state)
    assert state.registered == 2
    assert state.failed == 0
    rows = _row_by_storage_path()
    for rel in ("a/b/part.stl", "a/other.stl"):
        assert rel in rows, f"{rel} was not registered"
        assert (storage / rel).read_bytes() == b"solid x\n"

    # the rolled-back folder rows were inserted again with their real paths
    created = [folder for folder in _folders() if folder.id not in folders_before]
    named_a = [folder for folder in created if folder.name == "a"]
    named_b = [folder for folder in created if folder.name == "b"]
    assert len(named_a) == 1
    assert named_a[0].storage_path == "a"
    assert len(named_b) == 1
    assert named_b[0].storage_path == "a/b"


def test_import_commits_in_batches(mount_and_storage) -> None:
    mount, _storage = mount_and_storage
    total = 450
    for index in range(total):
        _write(mount, f"dir-{index // 50:02d}/part-{index:03d}.stl")

    with Session(engine) as session:
        runs_before = {run.id for run in session.exec(select(ImportRun))}
    commits = []

    def count_commit(_connection) -> None:
        commits.append(1)

    event.listen(engine, "commit", count_commit)
    try:
        state = mount_import.scan_mount_imports()
    finally:
        event.remove(engine, "commit", count_commit)

    _require(state)
    assert state.registered == total
    landed = [asset for asset in _asset_rows() if (asset.storage_path or "").startswith("dir-")]
    assert len(landed) == total
    # one commit per batch, with slack for folder lookups and the two run-row
    # transactions (begin_run's insert+prune, finish_run's update)
    assert len(commits) <= ceil(total / library_scan.BATCH_SIZE) + 4
    with Session(engine) as session:
        created_runs = [run for run in session.exec(select(ImportRun)) if run.id not in runs_before]
    assert len(created_runs) == 1
    assert created_runs[0].status == "succeeded"
    assert created_runs[0].registered == total


def test_counters_do_not_leak_into_library_scan_status(mount_and_storage) -> None:
    mount, _storage = mount_and_storage
    _write(mount, "a/part.stl")
    _write(mount, "a/other.stl")
    _write(mount, "top.stl")

    snapshot = library_scan.scan_status()

    state = mount_import.scan_mount_imports()

    _require(state)
    assert state.registered == 3
    assert library_scan.scan_status() == snapshot
