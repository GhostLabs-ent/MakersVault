"""Tests for the storage-root scanner (filesystem-authoritative library, phase 1)."""
import time
from datetime import datetime, timedelta
from math import ceil
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlmodel import Session, select

import library_scan
import main
from db import STORAGE, engine
from library_scan import scan_storage_root
from migrations import run_migrations
from models import Asset, Folder


@pytest.fixture(scope="module", autouse=True)
def _scan_schema() -> None:
    """Create the schema the way the app lifespan does.

    The database is normally migrated when the app starts; running this module on
    its own must not depend on some other test having started it first.
    """
    run_migrations(engine)


def _write(rel_path: str, payload: bytes = b"data") -> Path:
    path = STORAGE / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _auth_header(client: TestClient) -> dict:
    health = client.get("/health").json()
    if not health.get("auth_required"):
        return {}
    token = client.post("/login", json={"username": "admin", "password": "super-secret"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _assets_by_path() -> dict:
    with Session(engine) as session:
        return {a.storage_path: a for a in session.exec(select(Asset)).all()}


def _cleanup(paths, dirs=("Props", "Loose")):
    with Session(engine) as session:
        for asset in session.exec(select(Asset).where(Asset.storage_path.in_(paths))).all():
            session.delete(asset)
        for folder in session.exec(select(Folder)).all():
            if folder.name in dirs or folder.name == "Gears":
                session.delete(folder)
        session.commit()
    for rel in paths:
        (STORAGE / rel).unlink(missing_ok=True)


@pytest.fixture
def library_root():
    created = []
    yield created
    _cleanup(created)


def test_scan_registers_files_where_they_lie(library_root):
    _write("Props/Gears/gear.stl", b"solid gear\n")
    _write("Props/assembly.pdf", b"%PDF-1.4\n")
    _write("Loose/loose.stl", b"solid loose\n")
    library_root.extend(["Props/Gears/gear.stl", "Props/assembly.pdf", "Loose/loose.stl"])
    # app-owned and hidden entries must be ignored
    _write("thumbs/ignored.jpg", b"junk")
    _write(".hidden.stl", b"hidden")

    scan_storage_root()

    found = _assets_by_path()
    for rel in library_root:
        assert rel in found, f"{rel} was not registered"
        # the row points at the file that is already on disk, unchanged
        assert found[rel].filename == Path(rel).name
        assert (STORAGE / found[rel].storage_path).exists()
        assert found[rel].size > 0
    assert "thumbs/ignored.jpg" not in found
    assert ".hidden.stl" not in found

    with Session(engine) as session:
        names = {f.name for f in session.exec(select(Folder)).all()}
    assert {"Props", "Gears", "Loose"} <= names
    assert found["Props/Gears/gear.stl"].folder_id is not None


def test_scan_is_idempotent(library_root):
    rel = "Loose/run-twice.stl"
    _write(rel, b"solid x\n")
    library_root.append(rel)

    scan_storage_root()
    first = len(_assets_by_path())
    status = scan_storage_root()

    assert len(_assets_by_path()) == first
    assert status.registered == 0
    assert status.known >= 1


def test_missing_files_are_counted_not_deleted(library_root):
    rel = "Loose/vanishing.stl"
    path = _write(rel, b"solid gone\n")
    library_root.append(rel)

    scan_storage_root()
    assert rel in _assets_by_path()

    path.unlink()
    status = scan_storage_root()

    assert status.missing >= 1
    # the row survives: a mount hiccup must not silently lose the catalogue entry
    assert rel in _assets_by_path()
    assert _assets_by_path()[rel].missing_since is not None
    # Keep it in `library_root`: the fixture's cleanup owns every row this test
    # made, so dropping the path here leaks a row into the shared session DB.


def test_scan_endpoint_runs_in_background(library_root):
    rel = "Loose/from-api.stl"
    _write(rel, b"solid api\n")
    library_root.append(rel)

    with TestClient(main.app) as client:
        headers = _auth_header(client)
        start = client.post("/library/scan", headers=headers)
        assert start.status_code == 202, start.text
        assert start.json()["running"] is True

        for _ in range(50):
            status = client.get("/library/scan", headers=headers).json()
            if not status["running"]:
                break
            time.sleep(0.1)
        assert status["running"] is False
        assert status["registered"] >= 1

    assert rel in _assets_by_path()


# --- batched, bounded-memory scanning (Mf-025u) ------------------------------
#
# Everything below scans a temp root instead of the shared test storage. The
# database is shared for the whole session, so rows created here are removed at
# teardown and `missing` is only ever asserted as a delta: a scan of a temp root
# makes every other test's rows look absent.


def _write_under(root: Path, rel_path: str, payload: bytes = b"data") -> Path:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _library_rows(prefix: str) -> dict:
    """Assets whose storage_path starts with `prefix`, keyed by storage path."""
    with Session(engine) as session:
        return {
            asset.storage_path: asset
            for asset in session.exec(select(Asset)).all()
            if (asset.storage_path or "").startswith(prefix)
        }


def _folders_named(name: str) -> list:
    with Session(engine) as session:
        return [
            (folder.id, folder.storage_path)
            for folder in session.exec(select(Folder)).all()
            if folder.name == name
        ]


def _delete_folders_named(name: str) -> None:
    with Session(engine) as session:
        for folder in list(session.exec(select(Folder))):
            if folder.name == name:
                session.delete(folder)
        session.commit()


def _asset_by_id(asset_id: str) -> Optional[Asset]:
    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        if asset is not None:
            session.expunge(asset)
    return asset


@pytest.fixture
def temp_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Scan a temp storage root, then delete every row the test created."""
    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setattr(library_scan, "STORAGE", storage)
    # The schema is created by the app lifespan; a single-file run needs it first.
    run_migrations(engine)
    with Session(engine) as session:
        folders_before = {folder.id for folder in session.exec(select(Folder))}
        assets_before = {asset.id for asset in session.exec(select(Asset))}
    yield storage
    with Session(engine) as session:
        for folder in list(session.exec(select(Folder))):
            if folder.id not in folders_before:
                session.delete(folder)
        for asset in list(session.exec(select(Asset))):
            if asset.id not in assets_before:
                session.delete(asset)
        session.commit()


def test_scan_commits_in_batches(temp_library: Path) -> None:
    total = 450
    # Converge rows left absent by earlier tests first: the counted scan below
    # must do zero flag writes, so its commit count stays deterministic.
    scan_storage_root()
    for index in range(total):
        _write_under(temp_library, f"batched/dir-{index // 50:02d}/part-{index:03d}.stl", b"solid x\n")

    commits = []

    def count_commit(_connection) -> None:
        commits.append(1)

    event.listen(engine, "commit", count_commit)
    try:
        status = scan_storage_root()
    finally:
        event.remove(engine, "commit", count_commit)

    assert status.registered == total
    assert len(_library_rows("batched/")) == total
    # One commit per batch, with slack for folder lookups and stray threads.
    assert len(commits) <= ceil(total / library_scan.BATCH_SIZE) + 2


def test_scan_fails_only_the_row_that_collides(temp_library: Path) -> None:
    # Same stem in one folder: both derive the model name "part", and the unique
    # (folder, name) index makes exactly one of them impossible to insert.
    _write_under(temp_library, "collision/part.stl", b"solid a\n")
    _write_under(temp_library, "collision/part.step", b"step a\n")
    _write_under(temp_library, "collision/other.stl", b"solid b\n")
    _write_under(temp_library, "collision/another.stl", b"solid c\n")

    status = scan_storage_root()

    rows = _library_rows("collision/")
    assert len(rows) == 3
    assert {"collision/other.stl", "collision/another.stl"} <= set(rows)
    assert len(set(rows) & {"collision/part.stl", "collision/part.step"}) == 1
    assert status.registered == 3
    assert status.failed == 1
    assert len(status.errors) == 1
    assert status.errors[0].split(":")[0] in {"collision/part.stl", "collision/part.step"}


def test_interrupted_scan_leaves_whole_committed_batches(temp_library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = temp_library
    total = library_scan.BATCH_SIZE * 4
    for index in range(total):
        _write_under(storage, f"interrupted/dir-{index // 100:02d}/part-{index:03d}.stl", b"solid x\n")

    real_walk = library_scan._walk_storage
    walked = 0

    def interrupting_walk(root):
        nonlocal walked
        for item in real_walk(root):
            yield item
            walked += len(item[1])
            if walked >= library_scan.BATCH_SIZE * 1.5:
                raise RuntimeError("walker interrupted")

    monkeypatch.setattr(library_scan, "_walk_storage", interrupting_walk)
    with pytest.raises(RuntimeError, match="walker interrupted"):
        scan_storage_root()
    monkeypatch.setattr(library_scan, "_walk_storage", real_walk)

    rows = _library_rows("interrupted/")
    # Exactly one whole batch landed; the in-flight batch was rolled back.
    assert len(rows) == library_scan.BATCH_SIZE
    for rel_path, asset in rows.items():
        assert (storage / rel_path).stat().st_size == asset.size

    status = scan_storage_root()
    assert status.known == library_scan.BATCH_SIZE
    assert status.registered == total - library_scan.BATCH_SIZE
    assert len(_library_rows("interrupted/")) == total


def test_missing_counts_only_files_that_are_really_gone(temp_library: Path) -> None:
    storage = temp_library
    for name in ("one", "two", "three"):
        _write_under(storage, f"missing-parity/{name}.stl", b"solid x\n")
    first = scan_storage_root()
    assert first.registered == 3
    baseline = first.missing

    (storage / "missing-parity" / "two.stl").unlink()
    second = scan_storage_root()
    assert second.missing == baseline + 1
    assert second.known == 2
    assert second.registered == 0
    # Counted, never purged.
    assert "missing-parity/two.stl" in _library_rows("missing-parity/")

    # A tracked row under a pruned location is not missing while the file is there.
    _write_under(storage, "thumbs/present.jpg", b"junk")
    with Session(engine) as session:
        session.add(
            Asset(
                filename="present.jpg",
                mime="image/jpeg",
                size=4,
                name="missing-parity-thumb",
                storage_path="thumbs/present.jpg",
            )
        )
        session.commit()

    third = scan_storage_root()
    assert third.missing == baseline + 1


# --- missing_since flagging (Mf-itr4) ----------------------------------------
#
# A scan never deletes rows or files: it stamps `missing_since` when it first
# notices an asset's bytes are gone and clears the flag when they come back.
# The flag pass covers every candidate row in the session database, so these
# tests scope their assertions to their own storage paths.


def test_scan_flags_missing_files_without_deleting(temp_library: Path) -> None:
    storage = temp_library
    rel = "flagged/gone.stl"
    path = _write_under(storage, rel, b"solid gone\n")

    first = scan_storage_root()
    rows = _library_rows("flagged/")
    assert set(rows) == {rel}
    asset_id = rows[rel].id
    assert rows[rel].missing_since is None
    baseline = first.missing

    path.unlink()
    second = scan_storage_root()

    rows = _library_rows("flagged/")
    assert set(rows) == {rel}
    assert rows[rel].id == asset_id
    stamped = rows[rel].missing_since
    assert stamped is not None
    parsed = datetime.fromisoformat(stamped)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)
    assert not (storage / rel).exists()
    assert second.missing == baseline + 1


def test_scan_clears_missing_flag_when_file_returns(temp_library: Path) -> None:
    storage = temp_library
    rel = "returned/model.stl"
    path = _write_under(storage, rel, b"solid gone\n")

    scan_storage_root()
    asset_id = _library_rows("returned/")[rel].id

    path.unlink()
    scan_storage_root()
    assert _library_rows("returned/")[rel].missing_since is not None

    _write_under(storage, rel, b"solid back\n")
    status = scan_storage_root()

    with Session(engine) as session:
        matching = session.exec(select(Asset).where(Asset.storage_path == rel)).all()
    assert len(matching) == 1
    restored = matching[0]
    assert restored.id == asset_id
    assert restored.missing_since is None
    assert status.known >= 1


def test_scan_does_not_flag_reference_assets_when_only_storage_path_is_absent(
    temp_library: Path, tmp_path: Path
) -> None:
    # A mount no-copy row owns no managed file; only its source path matters.
    source = tmp_path / "mount" / "Thing.3mf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"3mf")

    with Session(engine) as session:
        asset = Asset(
            filename="Thing.3mf",
            mime="model/3mf",
            size=3,
            name="reference-thing",
            storage_path="ref-no-copy/Thing.3mf",
            source_path=str(source),
            is_reference=1,
        )
        session.add(asset)
        session.commit()
        session.refresh(asset)
        asset_id = asset.id

    # MOUNT_IMPORT_PATH is deliberately unset: presence must not depend on the
    # mount allowlist that governs serving.
    scan_storage_root()
    assert _asset_by_id(asset_id).missing_since is None

    source.unlink()
    scan_storage_root()
    assert _asset_by_id(asset_id).missing_since is not None


def test_asset_list_exposes_missing_since(temp_library: Path) -> None:
    stamped = "2026-01-02T03:04:05+00:00"
    with Session(engine) as session:
        asset = Asset(
            filename="flagged.stl",
            mime="model/stl",
            size=1,
            name="api-flagged",
            storage_path="api-flag/flagged.stl",
            missing_since=stamped,
        )
        session.add(asset)
        session.commit()
        session.refresh(asset)
        asset_id = asset.id

    with TestClient(main.app) as client:
        headers = _auth_header(client)
        response = client.get("/assets?limit=1000", headers=headers)
    assert response.status_code == 200, response.text
    entries = {item["id"]: item for item in response.json()}
    assert entries[asset_id]["missing_since"] == stamped


def test_delete_asset_with_missing_file_succeeds(temp_library: Path) -> None:
    with Session(engine) as session:
        asset = Asset(
            filename="missing.stl",
            mime="model/stl",
            size=1,
            name="deletable",
            storage_path="deleted/missing.stl",
        )
        session.add(asset)
        session.commit()
        session.refresh(asset)
        asset_id = asset.id

    with TestClient(main.app) as client:
        headers = _auth_header(client)
        response = client.delete(f"/asset/{asset_id}", params={"confirm_name": "missing.stl"}, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    # The bytes are already gone, so nothing moves; the row still goes.
    assert body["ok"] is True
    assert body["trash_path"] is None
    assert body["files"] == 1
    assert _asset_by_id(asset_id) is None


def test_missing_flag_writes_are_batched(temp_library: Path) -> None:
    storage = temp_library
    # Converge rows left absent by earlier tests, so the second scan only writes
    # the flags of the 450 rows this test creates.
    scan_storage_root()

    total = 450
    for index in range(total):
        _write_under(storage, f"flagged-batched/dir-{index // 50:02d}/part-{index:03d}.stl", b"solid x\n")

    first = scan_storage_root()
    assert first.registered == total
    assert all(asset.missing_since is None for asset in _library_rows("flagged-batched/").values())

    for path in storage.rglob("*.stl"):
        path.unlink()

    commits = []

    def count_commit(_connection) -> None:
        commits.append(1)

    event.listen(engine, "commit", count_commit)
    try:
        status = scan_storage_root()
    finally:
        event.remove(engine, "commit", count_commit)

    rows = _library_rows("flagged-batched/")
    assert len(rows) == total
    assert all(asset.missing_since is not None for asset in rows.values())
    assert status.failed == 0
    assert len(commits) <= ceil(total / library_scan.BATCH_SIZE) + 2


def test_folder_move_of_missing_asset_keeps_flag(temp_library: Path) -> None:
    storage = temp_library
    rel = "move-missing/model.stl"
    path = _write_under(storage, rel, b"solid gone\n")

    scan_storage_root()
    asset_id = _library_rows("move-missing/")[rel].id
    path.unlink()
    scan_storage_root()
    stamped = _asset_by_id(asset_id).missing_since
    assert stamped is not None

    with TestClient(main.app) as client:
        headers = _auth_header(client)
        created = client.post("/folders", json={"name": "move-missing-target"}, headers=headers)
        assert created.status_code == 200, created.text
        folder_id = created.json()["id"]
        moved = client.post(f"/asset/{asset_id}/folder", json={"folder_id": folder_id}, headers=headers)
        assert moved.status_code == 200, moved.text
        moved_path = moved.json()["storage_path"]
        assert moved.json()["missing_since"] == stamped

    assert moved_path != rel
    # The moved row points at a new path under the app's real storage root; the
    # move rewrote storage_path without creating the (still missing) file.
    assert not (storage / moved_path).exists()
    assert not (STORAGE / moved_path).exists()
    assert _asset_by_id(asset_id).missing_since == stamped

    scan_storage_root()

    rescanned = _asset_by_id(asset_id)
    assert rescanned.storage_path == moved_path
    assert rescanned.missing_since == stamped
    assert not (storage / moved_path).exists()
    assert not (STORAGE / moved_path).exists()


def test_counters_account_for_every_library_file(temp_library: Path) -> None:
    storage = temp_library
    files = ["counters/a.stl", "counters/nested/b.stl", "counters/nested/deep/c.stl"]
    for rel_path in files:
        _write_under(storage, rel_path, b"solid x\n")
    _write_under(storage, "counters/.hidden.stl", b"hidden")
    _write_under(storage, "counters/nested/.hidden.stl", b"hidden")

    first = scan_storage_root()
    assert first.registered == len(files)
    assert first.registered + first.known + first.failed == len(files)
    assert first.ignored == 2

    second = scan_storage_root()
    assert second.registered == 0
    assert second.known == len(files)
    assert second.registered + second.known + second.failed == len(files)


def test_folders_come_only_from_directories_that_register_files(temp_library: Path) -> None:
    storage = temp_library
    _write_under(storage, "revisited/kept.stl", b"solid kept\n")
    _write_under(storage, "hidden-only/.secret.stl", b"hidden")
    first = scan_storage_root()
    assert first.registered == 1
    assert len(_folders_named("revisited")) == 1
    _delete_folders_named("revisited")

    second = scan_storage_root()
    assert second.registered == 0
    assert second.known == 1
    # Neither a directory holding only tracked files nor one holding only a
    # hidden file gets a folder row.
    assert _folders_named("revisited") == []
    assert _folders_named("hidden-only") == []

    for index in range(library_scan.BATCH_SIZE + 50):
        _write_under(storage, f"fresh/part-{index:03d}.stl", b"solid new\n")
    third = scan_storage_root()
    assert third.registered == library_scan.BATCH_SIZE + 50
    # One row for the directory, even though its files span two batches.
    folders = _folders_named("fresh")
    assert len(folders) == 1
    assert folders[0][1] is None


def test_unreadable_3mf_still_registers_without_prepared_metadata(temp_library: Path) -> None:
    # inspect_prepared_print swallows BadZipFile, so a corrupt archive is not a
    # registration failure - the startup backfill retries the metadata later.
    _write_under(temp_library, "prepared/broken.3mf", b"not a zip at all")

    status = scan_storage_root()

    rows = _library_rows("prepared/")
    assert set(rows) == {"prepared/broken.3mf"}
    assert rows["prepared/broken.3mf"].prepared_metadata_json is None
    assert status.registered == 1
    assert status.failed == 0
    assert status.errors == []


def test_only_root_level_app_owned_dirs_are_pruned(temp_library: Path) -> None:
    """`thumbs`/`bundles` are app-owned at the storage root only, not below it."""
    _write_under(temp_library, "Props/thumbs/reference.jpg", b"jpeg data\n")
    _write_under(temp_library, "thumbs/ignored.jpg", b"junk")

    with Session(engine) as session:
        folders_before = {folder.id for folder in session.exec(select(Folder))}

    status = scan_storage_root()

    # The nested directory holds ordinary library content; the root one is pruned.
    assert set(_library_rows("Props/")) == {"Props/thumbs/reference.jpg"}
    assert set(_library_rows("thumbs/")) == set()
    assert status.registered == 1
    # Root-level app-owned directories are pruned silently, not counted as debris.
    assert status.ignored == 0

    with Session(engine) as session:
        created = [folder for folder in session.exec(select(Folder)) if folder.id not in folders_before]
    props = next(folder for folder in created if folder.name == "Props")
    created_pairs = {(folder.parent_id, folder.name) for folder in created}
    assert (props.id, "thumbs") in created_pairs
    assert (None, "thumbs") not in created_pairs


# --- batch failure recovery (Mf-025u) ----------------------------------------
#
# `_commit_batch` is replaced through the module global, because `_flush_batch`
# resolves it at call time. The replacement keeps the positional signature
# `_commit_batch(session, pending, cache)`.


def test_transient_batch_failure_is_retried_once(temp_library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = temp_library
    total = library_scan.BATCH_SIZE // 4
    for index in range(total):
        _write_under(storage, f"retried/part-{index:03d}.stl", f"solid {index}\n".encode())

    real_commit = library_scan._commit_batch
    batches = []

    def flaky_commit(session, pending, cache):
        batches.append(len(pending))
        if len(batches) == 1:
            raise RuntimeError("database is locked")
        return real_commit(session, pending, cache)

    monkeypatch.setattr(library_scan, "_commit_batch", flaky_commit)
    status = scan_storage_root()

    expected = {f"retried/part-{index:03d}.stl" for index in range(total)}
    rows = _library_rows("retried/")
    assert status.registered == total
    assert status.failed == 0
    assert status.errors == []
    assert set(rows) == expected
    for rel_path, asset in rows.items():
        assert asset.id
        assert (storage / rel_path).stat().st_size == asset.size
    # One batch: the failure was retried once, not looped over every file.
    assert batches == [total, total]
    # The retried batch still created the directory row exactly once.
    assert len(_folders_named("retried")) == 1


def test_commit_time_batch_failure_reinserts_without_duplicates(
    temp_library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure *after* the row savepoints flushed must roll back and re-insert.

    `test_transient_batch_failure_is_retried_once` fails `_commit_batch` before
    anything reaches the database; here every row has already been flushed into
    the transaction when `Session.commit` refuses, so the retry has to undo the
    rows and the folder row and insert them again - once, not twice.
    """
    storage = temp_library
    total = library_scan.BATCH_SIZE // 4
    for index in range(total):
        _write_under(storage, f"commit-retried/part-{index:03d}.stl", f"solid {index}\n".encode())

    real_commit = Session.commit
    attempts = []
    # A dict, so the closure can flip the flag without a `nonlocal` declaration.
    state = {"raised": False}

    def flaky_commit(session) -> None:
        attempts.append(1)
        if not state["raised"]:
            state["raised"] = True
            raise RuntimeError("database is locked")
        real_commit(session)

    monkeypatch.setattr(Session, "commit", flaky_commit)
    status = scan_storage_root()
    commit_attempts = len(attempts)

    expected = {f"commit-retried/part-{index:03d}.stl" for index in range(total)}
    rows = _library_rows("commit-retried/")
    assert status.registered == total
    assert status.failed == 0
    assert status.errors == []
    assert set(rows) == expected
    for rel_path, asset in rows.items():
        assert asset.size == (storage / rel_path).stat().st_size
        assert asset.folder_id is not None
    # Exactly one directory row, created metadata-only by the retried attempt.
    folders = _folders_named("commit-retried")
    assert len(folders) == 1
    assert folders[0][1] is None
    # One raise plus one real commit: rolled back and re-inserted, not duplicated.
    assert commit_attempts == 2


def test_permanent_batch_failure_fails_the_whole_batch(temp_library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = temp_library
    total = library_scan.BATCH_SIZE // 4
    for index in range(total):
        _write_under(storage, f"uncommittable/part-{index:03d}.stl", b"solid x\n")

    attempts = []

    def failing_commit(session, pending, cache):
        attempts.append(len(pending))
        raise RuntimeError("database is locked")

    monkeypatch.setattr(library_scan, "_commit_batch", failing_commit)
    status = scan_storage_root()

    assert status.registered == 0
    # The whole batch is accounted for as failed, not a single counter bump.
    assert status.failed == total
    assert len(status.errors) == 1
    assert status.errors[0].startswith(f"batch of {total} rolled back:")
    # Tried once, retried once, then given up on.
    assert attempts == [total, total]
    assert _library_rows("uncommittable/") == {}


def test_consecutive_batch_failures_stop_the_scan(temp_library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = temp_library
    total = library_scan.MAX_CONSECUTIVE_BATCH_FAILURES * library_scan.BATCH_SIZE
    for index in range(total):
        _write_under(storage, f"circuit/dir-{index // 100:03d}/part-{index:03d}.stl", b"solid x\n")

    def failing_commit(session, pending, cache):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(library_scan, "_commit_batch", failing_commit)
    # The third consecutive failed batch trips the breaker instead of scanning on.
    with pytest.raises(RuntimeError, match="consecutive batches failed to commit"):
        scan_storage_root()

    assert _library_rows("circuit/") == {}
