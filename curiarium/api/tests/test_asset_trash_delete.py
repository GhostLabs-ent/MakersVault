"""Trash-backed per-asset delete (Mf-cea1).

Asset delete now shares the folder standard: bytes move into
`.trash/<UTC timestamp>-<label>/` and the rows go only after that succeeds.
Every test works in a temporary storage root: `trash_service` resolves
`db.STORAGE` and `db.THUMBS` at call time, the scanner is pointed at the same
root, and `asset_service`/`asset_file_service` are patched too because uploads
bind their storage paths at import. Nothing ever touches a real library. The
database is shared for the whole test session, so rows created here are removed
again at teardown.
"""

import errno
import logging
import os
import re
from pathlib import Path
from typing import Optional

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

import asset_file_service
import asset_service
import audit
import db
import library_scan
import trash_service
from db import engine
from main import app
from migrations import run_migrations
from models import Asset, AssetFile, Folder

# --- infrastructure ---------------------------------------------------------


def auth_header(client: TestClient) -> dict:
    """Bearer token, or empty when the app is running with auth disabled."""
    health = client.get("/health").json()
    if not health.get("auth_required"):
        return {}
    token = client.post("/login", json={"username": "admin", "password": "super-secret"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def filesystem_snapshot(root: Path) -> tuple:
    """Paths and sizes of the whole tree; enough to prove nothing moved."""
    return tuple(
        sorted(
            (str(path.relative_to(root)) or ".", path.is_dir(), path.stat().st_size)
            for path in [root, *root.rglob("*")]
        )
    )


def storage_state(root: Path) -> dict:
    """Path -> kind/content map, so byte-level changes are directly comparable."""
    state = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            state[relative] = ("link", os.readlink(path))
        elif path.is_dir():
            state[relative] = ("dir", None)
        else:
            state[relative] = ("file", path.read_bytes())
    return state


def write_placeholder_file(path: Path, payload: bytes = b"placeholder") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def write_thumb(storage: Path, asset_id: str) -> Path:
    path = storage / "thumbs" / f"{asset_id}.jpg"
    write_placeholder_file(path, b"jpeg")
    return path


def insert_asset_row(
    name: str,
    storage_path: Optional[str],
    *,
    filename: str = "model.stl",
    size: int = 10,
    is_reference: int = 0,
    source_path: Optional[str] = None,
    supporting_file_count: int = 0,
) -> str:
    asset = Asset(
        filename=filename,
        mime="model/stl",
        size=size,
        name=name,
        storage_path=storage_path,
        is_reference=is_reference,
        source_path=source_path,
        supporting_file_count=supporting_file_count,
    )
    with Session(engine) as session:
        session.add(asset)
        session.commit()
        session.refresh(asset)
        return asset.id


def insert_asset_file_row(asset_id: str, storage_path: str, size: int = 7) -> str:
    row = AssetFile(
        asset_id=asset_id,
        filename=storage_path.rsplit("/", 1)[-1],
        mime="text/plain",
        size=size,
        storage_path=storage_path,
    )
    with Session(engine) as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def read_asset(asset_id: str) -> Optional[Asset]:
    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        if asset is not None:
            session.expunge(asset)
    return asset


def read_asset_file(file_id: str) -> Optional[AssetFile]:
    with Session(engine) as session:
        row = session.get(AssetFile, file_id)
        if row is not None:
            session.expunge(row)
    return row


def upload(client: TestClient, headers: dict, name: str, payload: bytes) -> dict:
    response = client.post("/upload", files={"file": (name, payload, "model/stl")}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def add_supporting_file(client: TestClient, headers: dict, asset_id: str, name: str, payload: bytes) -> dict:
    """Upload one supporting file and return its AssetFileOut row.

    The upload route answers with the parent ``AssetOut``, so the new file row
    is read back by name; its id is part of the bundle path.
    """
    response = client.post(
        f"/asset/{asset_id}/files",
        files={"file": (name, payload, "text/plain")},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    files = client.get(f"/asset/{asset_id}/files", headers=headers).json()
    return next(row for row in files if row["filename"] == name)


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point storage and thumbnails at temp roots and undo every row this test made."""
    storage = tmp_path / "storage"
    (storage / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(library_scan, "STORAGE", storage)
    # Uploads bind their storage paths at import time, so patch those globals too.
    monkeypatch.setattr(asset_service, "STORAGE", storage)
    monkeypatch.setattr(asset_service, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(asset_file_service, "STORAGE", storage)

    # The schema is created by the app lifespan; a single-file run needs it first.
    run_migrations(engine)
    with Session(engine) as session:
        folders_before = {folder.id for folder in session.exec(select(Folder))}
        assets_before = {asset.id for asset in session.exec(select(Asset))}
        files_before = {row.id for row in session.exec(select(AssetFile))}
    yield storage
    with Session(engine) as session:
        for row in list(session.exec(select(AssetFile))):
            if row.id not in files_before:
                session.delete(row)
        for asset in list(session.exec(select(Asset))):
            if asset.id not in assets_before:
                session.delete(asset)
        for folder in list(session.exec(select(Folder))):
            if folder.id not in folders_before:
                session.delete(folder)
        session.commit()


# --- confirmation gate ------------------------------------------------------


def test_delete_requires_matching_confirm_name(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        write_placeholder_file(storage / "shelf" / "model.stl", b"model bytes")
        asset_id = insert_asset_row("Model", "shelf/model.stl", size=11)
        before = filesystem_snapshot(storage)

        for url in (
            f"/asset/{asset_id}",
            f"/asset/{asset_id}?confirm_name=Model",
            f"/asset/{asset_id}?confirm_name=MODEL.STL",
        ):
            response = client.delete(url, headers=headers)
            assert response.status_code == 400, response.text
            assert "filename" in response.json()["detail"]

        missing = client.delete("/asset/does-not-exist?confirm_name=whatever", headers=headers)
        assert missing.status_code == 404

    assert filesystem_snapshot(storage) == before
    assert not (storage / ".trash").exists()
    assert read_asset(asset_id) is not None


# --- the happy path ---------------------------------------------------------


def test_delete_moves_the_primary_file_to_trash_and_removes_rows(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        write_placeholder_file(storage / "shelf" / "model.stl", b"model bytes")
        keep = storage / "other" / "keep.stl"
        write_placeholder_file(keep, b"keep bytes")
        asset_id = insert_asset_row("Model", "shelf/model.stl", size=11)
        thumb = write_thumb(storage, asset_id)
        state_before = storage_state(storage)

        response = client.delete(f"/asset/{asset_id}?confirm_name=model.stl", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["files"] == 1
        assert body["bytes"] == 11
        assert re.fullmatch(r"\.trash/\d{8}T\d{6}Z-Model", body["trash_path"]), body["trash_path"]

    entry = storage / body["trash_path"]
    assert (entry / ".assets" / asset_id / "model.stl").read_bytes() == b"model bytes"
    assert not (storage / "shelf" / "model.stl").exists()
    # The emptied directory must not survive as a future scan folder.
    assert not (storage / "shelf").exists()
    assert read_asset(asset_id) is None
    assert not thumb.exists()
    assert keep.read_bytes() == b"keep bytes"

    # Everything outside the entry and the two deleted paths is byte-identical.
    state_after = storage_state(storage)
    removed_prefixes = (".trash", "shelf", f"thumbs/{asset_id}.jpg")
    compared_before = {
        key: value for key, value in state_before.items() if not key.startswith(removed_prefixes)
    }
    compared_after = {
        key: value for key, value in state_after.items() if not key.startswith(removed_prefixes)
    }
    assert compared_after == compared_before
    assert (storage / ".trash").is_dir()


def test_supporting_files_follow_the_whole_bundle_directory(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        asset = upload(client, headers, "cube.stl", b"solid cube\n")
        supporting = add_supporting_file(client, headers, asset["id"], "notes.txt", b"layer notes\n")

        response = client.delete(f"/asset/{asset['id']}?confirm_name={asset['filename']}", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        # The primary file plus the one supporting file.
        assert body["files"] == 2

    bundle_relative = f"bundles/{asset['id']}/{supporting['id']}"
    entry = storage / body["trash_path"]
    assert (entry / ".assets" / asset["id"] / asset["filename"]).read_bytes() == b"solid cube\n"
    assert (entry / ".bundles" / asset["id"] / supporting["id"] / "notes.txt").read_bytes() == b"layer notes\n"
    assert not (storage / asset["storage_path"]).exists()
    assert not (storage / bundle_relative).exists()
    assert not (storage / "bundles" / asset["id"]).exists()
    assert read_asset_file(supporting["id"]) is None


def test_purge_reclaims_the_entry_and_reports_the_byte_count(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        write_placeholder_file(storage / "shelf" / "model.stl", b"model bytes")
        asset_id = insert_asset_row("Model", "shelf/model.stl", size=11)
        response = client.delete(f"/asset/{asset_id}?confirm_name=model.stl", headers=headers)
        assert response.status_code == 200, response.text
        entry = storage / response.json()["trash_path"]

        listing = client.get("/trash", headers=headers)
        assert listing.status_code == 200, listing.text
        total_size = listing.json()["total_size"]
        assert total_size == len(b"model bytes")

        purged = client.post("/trash/purge", headers=headers)
        assert purged.json() == {"purged": 1, "bytes": total_size, "failed": []}

    assert not entry.exists()


# --- reference assets -------------------------------------------------------


def test_reference_assets_lose_rows_only(isolated_storage: Path, tmp_path: Path) -> None:
    storage = isolated_storage
    external = tmp_path / "external"
    external.mkdir()
    external_file = external / "ref.stl"
    external_file.write_bytes(b"external bytes")

    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = insert_asset_row(
            "External",
            None,
            filename="ref.stl",
            is_reference=1,
            source_path=str(external_file),
        )
        thumb = write_thumb(storage, asset_id)

        # The UI's delete confirmation reads this flag to say "record only".
        listed = client.get("/assets?limit=1000", headers=headers).json()
        assert {entry["id"]: entry["is_reference"] for entry in listed}[asset_id] is True

        response = client.delete(f"/asset/{asset_id}?confirm_name=ref.stl", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()

    assert body["trash_path"] is None
    assert body["files"] == 0
    # Nothing of ours moved, so nothing of ours is reported as reclaimed.
    assert body["bytes"] == 0
    assert read_asset(asset_id) is None
    assert external_file.read_bytes() == b"external bytes"
    assert not thumb.exists()
    assert not (storage / ".trash").exists()


# --- files that cannot be moved ---------------------------------------------


def test_missing_file_still_deletes_the_row(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = insert_asset_row("Gone", "deleted/missing.stl", filename="missing.stl", size=3)

        response = client.delete(f"/asset/{asset_id}?confirm_name=missing.stl", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()

    assert body["trash_path"] is None
    assert body["files"] == 1
    assert body["bytes"] == 3
    assert read_asset(asset_id) is None
    assert not (storage / ".trash").exists()


def test_storage_path_escape_is_not_moved(isolated_storage: Path) -> None:
    storage = isolated_storage
    escape = storage.parent / "escape"
    escape.mkdir()
    outside = escape / "model.stl"
    outside.write_bytes(b"outside bytes")
    before = filesystem_snapshot(storage)

    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = insert_asset_row("Escape", "../escape/model.stl", size=13)

        response = client.delete(f"/asset/{asset_id}?confirm_name=model.stl", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["trash_path"] is None

    assert read_asset(asset_id) is None
    assert outside.read_bytes() == b"outside bytes"
    assert filesystem_snapshot(storage) == before
    assert not (storage / ".trash").exists()


def test_symlinked_primary_file_is_not_followed(isolated_storage: Path, tmp_path: Path) -> None:
    storage = isolated_storage
    external = tmp_path / "external"
    external.mkdir()
    external_file = external / "real.stl"
    external_file.write_bytes(b"external bytes")
    link = storage / "linked.stl"
    link.symlink_to(external_file)
    before = filesystem_snapshot(storage)

    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = insert_asset_row("Linked", "linked.stl", filename="linked.stl")

        response = client.delete(f"/asset/{asset_id}?confirm_name=linked.stl", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["trash_path"] is None

    assert read_asset(asset_id) is None
    assert link.is_symlink()
    assert external_file.read_bytes() == b"external bytes"
    assert filesystem_snapshot(storage) == before
    assert not (storage / ".trash").exists()


# --- failed commit ----------------------------------------------------------


def explode(_session, _row) -> None:
    raise RuntimeError("audit insert failed")


def test_failed_commit_restores_the_moves_and_keeps_the_row(
    isolated_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure after the moves must undo them and leave every row in place."""
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        write_placeholder_file(storage / "shelf" / "model.stl", b"model bytes")
        asset_id = insert_asset_row("Model", "shelf/model.stl", size=11)
        bundle_relative = f"bundles/{asset_id}/notes/notes.txt"
        write_placeholder_file(storage / bundle_relative, b"notes bytes")
        file_id = insert_asset_file_row(asset_id, bundle_relative)
        thumb = write_thumb(storage, asset_id)

        # Fail after the filesystem moves but before the commit lands.
        monkeypatch.setattr(audit, "_add", explode)
        response = client.delete(f"/asset/{asset_id}?confirm_name=model.stl", headers=headers)

    assert response.status_code == 500, response.text
    assert "no rows were changed" in response.json()["detail"]

    # Bytes are back where they started, including the bundle carve-out.
    assert (storage / "shelf" / "model.stl").read_bytes() == b"model bytes"
    assert (storage / bundle_relative).read_bytes() == b"notes bytes"
    # Thumbnails are unlinked only after a successful commit.
    assert thumb.read_bytes() == b"jpeg"

    assert read_asset(asset_id) is not None
    assert read_asset_file(file_id) is not None

    # The renamed entry was pruned; only the empty trash root may remain.
    trash = storage / ".trash"
    remaining = list(trash.iterdir()) if trash.exists() else []
    assert remaining == []


def test_a_file_owned_by_another_account_is_a_logged_409(
    isolated_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog,
) -> None:
    """The folder bug's asset-shaped twin (Mf-c2gw): refused and unlogged.

    A scan registers a file inside a directory somebody else created, so the API
    user cannot rename it. The rename failure must be a 409 naming the ownership
    remedy and it must be logged. This test drives the single-asset route; the
    bulk delete calls the same service and reports the 409 per item, without
    logging it, so this log line is the operator's only trace there too.

    The image runs pytest as root, where a real chmod/foreign owner cannot
    refuse anything, so the kernel's EACCES is injected at the syscall instead.
    `trash_service.os` is the process-wide `os` module, so the fake delegates
    every other rename to the real one.
    """
    storage = isolated_storage
    real_rename = os.rename
    target = (storage / "shelf" / "model.stl").resolve()

    def refuse_the_file(source, destination, *args, **kwargs):
        if Path(source).resolve() == target:
            raise PermissionError(errno.EACCES, "Permission denied", str(source), None, str(destination))
        return real_rename(source, destination, *args, **kwargs)

    with TestClient(app) as client:
        headers = auth_header(client)
        write_placeholder_file(storage / "shelf" / "model.stl", b"model bytes")
        asset_id = insert_asset_row("Model", "shelf/model.stl", size=11)

        monkeypatch.setattr(trash_service.os, "rename", refuse_the_file)
        with caplog.at_level(logging.ERROR, logger=trash_service.log.name):
            response = client.delete(f"/asset/{asset_id}?confirm_name=model.stl", headers=headers)

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert "shelf/model.stl" in detail
    assert str(storage) not in detail
    assert "CHOWN_MODE=recursive" in detail

    assert "Asset delete failed for asset" in caplog.text
    assert asset_id in caplog.text
    assert "PermissionError" in caplog.text

    assert (storage / "shelf" / "model.stl").read_bytes() == b"model bytes"
    assert read_asset(asset_id) is not None


def test_a_delete_that_loses_the_race_is_a_404_not_a_fabricated_success(
    isolated_storage: Path,
) -> None:
    """A row deleted between the read and the write must not report success.

    The route reads the row, then ``trash_asset`` moves the bytes and deletes the
    row. A concurrent delete that commits in that window leaves this call with a
    stale object; without the rowcount check the ORM delete would affect nothing
    and the caller would get a 200 claiming files it never moved. Here the other
    writer commits before ``trash_asset`` runs, which is the same end state.
    """
    storage = isolated_storage
    write_placeholder_file(storage / "shelf" / "model.stl", b"model bytes")
    asset_id = insert_asset_row("Model", "shelf/model.stl", size=11)

    with Session(engine) as session:
        stale = session.get(Asset, asset_id)
        assert stale is not None
        with Session(engine) as other:
            other.execute(delete(Asset).where(Asset.id == asset_id))
            other.commit()

        with pytest.raises(HTTPException) as error:
            trash_service.trash_asset(session, stale, audit_ctx=None)

    assert error.value.status_code == 404
    # The move of a row nobody owns was undone, and no entry is left behind.
    assert (storage / "shelf" / "model.stl").read_bytes() == b"model bytes"
    props = storage / ".trash"
    assert not props.exists() or list(props.iterdir()) == []
    assert read_asset(asset_id) is None


# --- bulk delete ------------------------------------------------------------


def test_batch_delete_trashes_each_id_and_reports_an_unknown_one(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        first = upload(client, headers, "alpha.stl", b"solid alpha\n")
        second = upload(client, headers, "beta.stl", b"solid beta\n")

        response = client.post(
            "/assets/batch/delete",
            json={"asset_ids": [first["id"], second["id"], "no-such-asset"], "confirm_count": 3},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()

    assert body["deleted"] == [first["id"], second["id"]]
    assert len(body["failed"]) == 1
    failure = body["failed"][0]
    assert failure["id"] == "no-such-asset"
    assert failure["code"] == "not_found"
    assert failure["status"] == 404

    assert read_asset(first["id"]) is None
    assert read_asset(second["id"]) is None
    for asset, payload in ((first, b"solid alpha\n"), (second, b"solid beta\n")):
        assert not (storage / asset["storage_path"]).exists()
        trashed = list((storage / ".trash").rglob(asset["filename"]))
        assert [path.read_bytes() for path in trashed] == [payload]


def test_batch_delete_requires_matching_confirm_count(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        first = upload(client, headers, "alpha.stl", b"solid alpha\n")
        second = upload(client, headers, "beta.stl", b"solid beta\n")
        ids = [first["id"], second["id"]]

        for payload in (
            {"asset_ids": ids},
            {"asset_ids": ids, "confirm_count": 1},
            {"asset_ids": ids, "confirm_count": 3},
        ):
            response = client.post("/assets/batch/delete", json=payload, headers=headers)
            assert response.status_code == 400, response.text
            assert "confirm_count" in response.json()["detail"]

        assert read_asset(first["id"]) is not None
        assert read_asset(second["id"]) is not None

    assert (storage / first["storage_path"]).read_bytes() == b"solid alpha\n"
    assert (storage / second["storage_path"]).read_bytes() == b"solid beta\n"
    assert not (storage / ".trash").exists()


# --- restore path -----------------------------------------------------------


def test_hand_restore_and_rescan_reregisters_the_file(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        write_placeholder_file(storage / "shelf" / "model.stl", b"solid model")
        asset_id = insert_asset_row("Model", "shelf/model.stl")

        response = client.delete(f"/asset/{asset_id}?confirm_name=model.stl", headers=headers)
        assert response.status_code == 200, response.text
        trash_path = response.json()["trash_path"]

    entry = storage / trash_path
    restored_path = storage / "shelf" / "model.stl"
    restored_path.parent.mkdir(parents=True, exist_ok=True)
    os.rename(entry / ".assets" / asset_id / "model.stl", restored_path)

    library_scan.scan_storage_root()

    with Session(engine) as session:
        restored = list(session.exec(select(Asset).where(Asset.storage_path == "shelf/model.stl")))
        assert len(restored) == 1
        assert restored[0].id != asset_id
        folder = session.get(Folder, restored[0].folder_id)
        assert folder is not None
        assert folder.name == "shelf"
