"""Trash-backed destructive folder delete and explicit purge (Mf-5gh0).

Every test works in a temporary storage root: `trash_service` resolves `db.STORAGE`
and `db.THUMBS` at call time, and the scanner is pointed at the same root, so
nothing ever touches a real library. The database is shared for the whole test
session, so rows created here are removed again at teardown.
"""

import os
import re
import time
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

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


def tree_snapshot(root: Path) -> tuple:
    """Same shape as `filesystem_snapshot`, used where mtimes must be ignored."""
    return filesystem_snapshot(root)


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


def insert_folder_row(name: str, parent_id: Optional[str] = None, storage_path: Optional[str] = None) -> str:
    folder = Folder(name=name, tags_json="[]", parent_id=parent_id, storage_path=storage_path)
    with Session(engine) as session:
        session.add(folder)
        session.commit()
        session.refresh(folder)
        return folder.id


def insert_asset_row(
    name: str,
    folder_id: Optional[str],
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
        folder_id=folder_id,
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


def read_folder(folder_id: str) -> Optional[Folder]:
    with Session(engine) as session:
        folder = session.get(Folder, folder_id)
        if folder is not None:
            session.expunge(folder)
    return folder


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


def created_folder(client: TestClient, headers: dict, name: str, parent_id: Optional[str] = None) -> dict:
    response = client.post("/folders", json={"name": name, "tags": [], "parent_id": parent_id}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point storage and thumbnails at temp roots and undo every row this test made."""
    storage = tmp_path / "storage"
    (storage / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(library_scan, "STORAGE", storage)

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
        parent = created_folder(client, headers, "Parent")
        write_placeholder_file(storage / "Parent" / "model.stl")
        asset_id = insert_asset_row("Delete me", parent["id"], "Parent/model.stl")
        before = filesystem_snapshot(storage)

        for url in (
            f"/folder/{parent['id']}",
            f"/folder/{parent['id']}?confirm_name=parent",
            f"/folder/{parent['id']}?confirm_name=Parent%20(2)",
        ):
            response = client.delete(url, headers=headers)
            assert response.status_code == 400, response.text

        missing = client.delete("/folder/does-not-exist?confirm_name=whatever", headers=headers)
        assert missing.status_code == 404

    assert filesystem_snapshot(storage) == before
    assert not (storage / ".trash").exists()
    assert read_folder(parent["id"]).name == "Parent"
    assert read_asset(asset_id).folder_id == parent["id"]


# --- whole-subtree delete ---------------------------------------------------


def test_delete_moves_subtree_to_trash_and_removes_rows(
    isolated_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = isolated_storage
    calls = []

    def boom(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("reorganize_managed_assets must not run on delete")

    monkeypatch.setattr("main.reorganize_managed_assets", boom)

    with TestClient(app) as client:
        headers = auth_header(client)
        parent = created_folder(client, headers, "Parent")
        child = created_folder(client, headers, "Child", parent_id=parent["id"])
        sibling = created_folder(client, headers, "Sibling")
        write_placeholder_file(storage / "Parent" / "model.stl", b"parent bytes")
        write_placeholder_file(storage / "Parent" / "Child" / "part.stl", b"child bytes")
        write_placeholder_file(storage / "Sibling" / "keep.stl", b"sibling bytes")
        parent_asset = insert_asset_row("Parent model", parent["id"], "Parent/model.stl")
        child_asset = insert_asset_row("Child part", child["id"], "Parent/Child/part.stl")
        sibling_asset = insert_asset_row("Sibling keep", sibling["id"], "Sibling/keep.stl")
        bundle_relative = f"bundles/{parent_asset}/{parent_asset}-notes/notes.txt"
        write_placeholder_file(storage / bundle_relative, b"notes")
        file_row = insert_asset_file_row(parent_asset, bundle_relative)
        parent_thumb = write_thumb(storage, parent_asset)
        child_thumb = write_thumb(storage, child_asset)
        sibling_before = tree_snapshot(storage / "Sibling")
        state_before = storage_state(storage)

        response = client.delete(f"/folder/{parent['id']}?confirm_name=Parent", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["folders"] == 2
        assert body["assets"] == 2
        assert body["bytes"] == 20
        assert re.fullmatch(r"\.trash/\d{8}T\d{6}Z-Parent", body["trash_path"]), body["trash_path"]

    assert calls == []
    entry = storage / body["trash_path"]
    assert (entry / "model.stl").read_bytes() == b"parent bytes"
    assert (entry / "Child" / "part.stl").read_bytes() == b"child bytes"
    assert (entry / ".bundles" / parent_asset / f"{parent_asset}-notes" / "notes.txt").is_file()
    assert not (storage / "Parent").exists()

    with Session(engine) as session:
        assert session.get(Folder, parent["id"]) is None
        assert session.get(Folder, child["id"]) is None
        assert session.get(Asset, parent_asset) is None
        assert session.get(Asset, child_asset) is None
        assert session.get(AssetFile, file_row) is None
    assert read_asset(sibling_asset) is not None
    assert not parent_thumb.exists()
    assert not child_thumb.exists()

    assert tree_snapshot(storage / "Sibling") == sibling_before

    # Everything outside the deleted subtree and its carve-outs is byte-identical.
    state_after = storage_state(storage)
    removed_prefixes = (
        "Parent/",
        "Parent",
        f"bundles/{parent_asset}",
        f"thumbs/{parent_asset}.jpg",
        f"thumbs/{child_asset}.jpg",
    )
    compared_before = {
        key: value
        for key, value in state_before.items()
        if not key.startswith(".trash") and not key.startswith(removed_prefixes)
    }
    compared_after = {
        key: value
        for key, value in state_after.items()
        if not key.startswith(".trash") and not key.startswith(removed_prefixes)
    }
    assert compared_after == compared_before
    assert (storage / ".trash").is_dir()


# --- failed commit ----------------------------------------------------------


def test_failed_row_delete_restores_moves_and_keeps_rows(
    isolated_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure after the moves must undo them and leave every row in place."""
    storage = isolated_storage

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    with TestClient(app) as client:
        headers = auth_header(client)
        parent = created_folder(client, headers, "Parent")
        write_placeholder_file(storage / "Parent" / "model.stl", b"model bytes")
        asset_id = insert_asset_row("model", parent["id"], "Parent/model.stl", size=11)
        bundle_relative = f"bundles/{asset_id}/{asset_id}-notes/notes.txt"
        write_placeholder_file(storage / bundle_relative, b"notes bytes")
        file_id = insert_asset_file_row(asset_id, bundle_relative)
        thumb = write_thumb(storage, asset_id)

        # Fail after the filesystem moves but before the commit.
        monkeypatch.setattr(trash_service, "_delete_rows", boom)
        response = client.delete(f"/folder/{parent['id']}?confirm_name=Parent", headers=headers)

    assert response.status_code == 500, response.text
    assert "no rows were changed" in response.json()["detail"]

    # Bytes are back where they started, including the bundle carve-out.
    assert (storage / "Parent" / "model.stl").read_bytes() == b"model bytes"
    assert (storage / bundle_relative).read_bytes() == b"notes bytes"
    # Thumbnails are unlinked only after a successful commit.
    assert thumb.read_bytes() == b"jpeg"

    assert read_folder(parent["id"]) is not None
    assert read_asset(asset_id) is not None
    assert read_asset_file(file_id) is not None

    # The renamed entry was moved back; only the empty trash root may remain.
    trash = storage / ".trash"
    remaining = list(trash.iterdir()) if trash.exists() else []
    assert remaining == []


# --- reference assets -------------------------------------------------------


def test_reference_assets_lose_rows_only(isolated_storage: Path, tmp_path: Path) -> None:
    storage = isolated_storage
    external = tmp_path / "external"
    external.mkdir()
    external_file = external / "ref.stl"
    external_file.write_bytes(b"external bytes")

    with TestClient(app) as client:
        headers = auth_header(client)
        parent = created_folder(client, headers, "Parent")
        write_placeholder_file(storage / "Parent" / "model.stl")
        asset_id = insert_asset_row(
            "External",
            parent["id"],
            None,
            is_reference=1,
            source_path=str(external_file),
        )
        thumb = write_thumb(storage, asset_id)

        response = client.delete(f"/folder/{parent['id']}?confirm_name=Parent", headers=headers)
        assert response.status_code == 200, response.text

    assert read_asset(asset_id) is None
    assert external_file.read_bytes() == b"external bytes"
    assert not thumb.exists()
    entry = storage / response.json()["trash_path"]
    assert not (entry / "ref.stl").exists()


# --- containment ------------------------------------------------------------


def test_symlinked_folder_is_refused(isolated_storage: Path, tmp_path: Path) -> None:
    storage = isolated_storage
    external = tmp_path / "external"
    external.mkdir()
    (external / "data.stl").write_bytes(b"external bytes")
    link = storage / "Link"
    link.symlink_to(external, target_is_directory=True)
    folder_id = insert_folder_row("Link", storage_path="Link")
    before = tree_snapshot(storage)

    with TestClient(app) as client:
        headers = auth_header(client)
        response = client.delete(f"/folder/{folder_id}?confirm_name=Link", headers=headers)
        assert response.status_code == 400, response.text
        assert "symlink" in response.json()["detail"].lower()

    assert link.is_symlink()
    assert (external / "data.stl").read_bytes() == b"external bytes"
    assert read_folder(folder_id).storage_path == "Link"
    assert tree_snapshot(storage) == before
    assert not (storage / ".trash").exists()


def test_storage_path_escape_is_refused(isolated_storage: Path) -> None:
    storage = isolated_storage
    escape = storage.parent / "escape"
    escape.mkdir()
    (escape / "outside.stl").write_bytes(b"outside bytes")
    folder_id = insert_folder_row("Escape", storage_path="../escape")
    before = tree_snapshot(storage)

    with TestClient(app) as client:
        headers = auth_header(client)
        response = client.delete(f"/folder/{folder_id}?confirm_name=Escape", headers=headers)
        assert response.status_code == 400, response.text

    assert read_folder(folder_id).storage_path == "../escape"
    assert (escape / "outside.stl").read_bytes() == b"outside bytes"
    assert tree_snapshot(storage) == before
    assert not (storage / ".trash").exists()


def test_folder_already_in_trash_is_refused(isolated_storage: Path) -> None:
    storage = isolated_storage
    entry = storage / ".trash" / "20250101T000000Z-Old"
    entry.mkdir(parents=True)
    (entry / "model.stl").write_bytes(b"old bytes")
    folder_id = insert_folder_row("Old", storage_path=".trash/20250101T000000Z-Old")
    before = tree_snapshot(storage)

    with TestClient(app) as client:
        headers = auth_header(client)
        response = client.delete(f"/folder/{folder_id}?confirm_name=Old", headers=headers)
        assert response.status_code == 409, response.text

    assert (entry / "model.stl").read_bytes() == b"old bytes"
    assert read_folder(folder_id).storage_path == ".trash/20250101T000000Z-Old"
    assert tree_snapshot(storage) == before


def test_running_scan_blocks_delete(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        parent = created_folder(client, headers, "Parent")
        write_placeholder_file(storage / "Parent" / "model.stl")
        asset_id = insert_asset_row("model", parent["id"], "Parent/model.stl")
        before = filesystem_snapshot(storage)

        monkeypatch.setattr("main.scan_status", lambda: {"running": True, "errors": []})
        response = client.delete(f"/folder/{parent['id']}?confirm_name=Parent", headers=headers)
        assert response.status_code == 409, response.text
        assert "scan" in response.json()["detail"].lower()

    assert filesystem_snapshot(storage) == before
    assert not (storage / ".trash").exists()
    assert read_folder(parent["id"]) is not None
    assert read_asset(asset_id) is not None


# --- listing and purge ------------------------------------------------------


def test_purge_respects_age_and_touches_nothing_else(isolated_storage: Path) -> None:
    storage = isolated_storage
    old_entry = storage / ".trash" / "20250101T000000Z-Old"
    young_entry = storage / ".trash" / "20250101T000001Z-Young"
    write_placeholder_file(old_entry / "a.stl", b"aaaa")
    write_placeholder_file(old_entry / "nested" / "b.stl", b"bb")
    write_placeholder_file(young_entry / "c.stl", b"ccc")
    live = storage / "Live" / "keep.stl"
    write_placeholder_file(live, b"live bytes")

    old_mtime = time.time() - 30 * 86400
    os.utime(old_entry, (old_mtime, old_mtime))
    old_size = 4 + 2

    with TestClient(app) as client:
        headers = auth_header(client)
        listing = client.get("/trash", headers=headers)
        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert body["total_size"] == old_size + 3
        assert {entry["name"] for entry in body["entries"]} == {"20250101T000000Z-Old", "20250101T000001Z-Young"}
        for entry in body["entries"]:
            assert entry["path"] == f".trash/{entry['name']}"
            assert entry["mtime"].endswith("+00:00")

        purge = client.post("/trash/purge?older_than_days=7", headers=headers)
        assert purge.status_code == 200, purge.text
        assert purge.json() == {"purged": 1, "bytes": old_size, "failed": []}

        assert not old_entry.exists()
        assert young_entry.exists()
        assert live.read_bytes() == b"live bytes"

        purge_all = client.post("/trash/purge", headers=headers)
        assert purge_all.json() == {"purged": 1, "bytes": 3, "failed": []}
        assert client.get("/trash", headers=headers).json() == {"entries": [], "total_size": 0}

    assert live.read_bytes() == b"live bytes"


# --- restore path -----------------------------------------------------------


def test_hand_restore_and_rescan_reregisters_files(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        parent = created_folder(client, headers, "Parent")
        write_placeholder_file(storage / "Parent" / "model.stl", b"solid model")
        asset_id = insert_asset_row("model", parent["id"], "Parent/model.stl")

        response = client.delete(f"/folder/{parent['id']}?confirm_name=Parent", headers=headers)
        assert response.status_code == 200, response.text
        trash_path = response.json()["trash_path"]

    entry = storage / trash_path
    assert (entry / "model.stl").read_bytes() == b"solid model"
    os.rename(entry, storage / "Parent")

    library_scan.scan_storage_root()

    with Session(engine) as session:
        restored = list(session.exec(select(Asset).where(Asset.storage_path == "Parent/model.stl")))
        assert len(restored) == 1
        assert restored[0].id != asset_id
        folder = session.get(Folder, restored[0].folder_id)
        assert folder is not None
        assert folder.name == "Parent"
        assert folder.parent_id is None


def test_scan_ignores_trash_entries(isolated_storage: Path) -> None:
    storage = isolated_storage
    entry = storage / ".trash" / "20250101T000000Z-Old"
    write_placeholder_file(entry / "hidden.stl", b"hidden bytes")

    library_scan.scan_storage_root()

    with Session(engine) as session:
        trash_assets = [
            asset.storage_path
            for asset in session.exec(select(Asset))
            if asset.storage_path and ".trash" in asset.storage_path
        ]
        assert trash_assets == []
        assert ".trash" not in {folder.name for folder in session.exec(select(Folder))}


# --- preview ----------------------------------------------------------------


def test_delete_preview_counts_and_writes_nothing(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        parent = created_folder(client, headers, "Parent")
        child = created_folder(client, headers, "Child", parent_id=parent["id"])
        write_placeholder_file(storage / "Parent" / "model.stl")
        write_placeholder_file(storage / "Parent" / "Child" / "part.stl")
        insert_asset_row("one", parent["id"], "Parent/model.stl", size=10, supporting_file_count=3)
        insert_asset_row("two", child["id"], "Parent/Child/part.stl", size=20)
        before = filesystem_snapshot(storage)

        preview = client.get(f"/folder/{parent['id']}/delete-preview", headers=headers)
        assert preview.status_code == 200, preview.text
        assert preview.json() == {"folders": 2, "assets": 2, "files": 5, "bytes": 30, "in_trash": False}

        missing = client.get("/folder/does-not-exist/delete-preview", headers=headers)
        assert missing.status_code == 404

    assert filesystem_snapshot(storage) == before
    assert not (storage / ".trash").exists()


def test_delete_preview_reports_folder_already_in_trash(isolated_storage: Path) -> None:
    storage = isolated_storage
    entry = storage / ".trash" / "20250101T000000Z-Old"
    entry.mkdir(parents=True)
    folder_id = insert_folder_row("Old", storage_path=".trash/20250101T000000Z-Old")

    with TestClient(app) as client:
        headers = auth_header(client)
        preview = client.get(f"/folder/{folder_id}/delete-preview", headers=headers)

    assert preview.status_code == 200, preview.text
    assert preview.json()["in_trash"] is True


# --- carve-outs -------------------------------------------------------------


def test_bundle_sidecars_and_stray_managed_files_follow_the_entry(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        parent = created_folder(client, headers, "Parent")
        asset_id = insert_asset_row("Stray", parent["id"], None, size=10)
        write_placeholder_file(storage / asset_id / "model.stl", b"stray bytes")
        bundle_relative = f"bundles/{asset_id}/{asset_id}-notes/notes.txt"
        write_placeholder_file(storage / bundle_relative, b"notes bytes")
        insert_asset_file_row(asset_id, bundle_relative)

        response = client.delete(f"/folder/{parent['id']}?confirm_name=Parent", headers=headers)
        assert response.status_code == 200, response.text
        trash_path = response.json()["trash_path"]

    entry = storage / trash_path
    assert (entry / ".assets" / asset_id / "model.stl").read_bytes() == b"stray bytes"
    assert (entry / ".bundles" / asset_id / f"{asset_id}-notes" / "notes.txt").read_bytes() == b"notes bytes"
    assert not (storage / asset_id / "model.stl").exists()
    # The emptied fallback directory must not survive as a future scan folder.
    assert not (storage / asset_id).exists()
    assert not (storage / "bundles" / asset_id).exists()

    with TestClient(app) as client:
        headers = auth_header(client)
        total_size = client.get("/trash", headers=headers).json()["total_size"]
        purged = client.post("/trash/purge", headers=headers).json()

    assert total_size > 0
    assert purged == {"purged": 1, "bytes": total_size, "failed": []}
    assert not (storage / ".trash" / entry.name).exists()
