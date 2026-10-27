"""Editing metadata must never relocate a managed file (Mf-aoyv).

The storage template only applies to new uploads and imports. Tags, notes,
creator, collection and even a rename change the row and, for a rename, only the
basename on disk - the template is never rendered on an existing asset, so a
template containing ``{tags}`` or ``{folder}`` cannot drag files around as a side
effect of a metadata edit.

Every test works in a temporary storage root: ``db``, ``library_scan`` and
``asset_service`` are all pointed at it (``asset_service`` binds ``STORAGE`` at
import time). The database is shared for the whole test session, so rows and the
storage template created here are restored at teardown.
"""

from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import asset_service
import db
import library_scan
import settings_service
from db import engine
from main import app
from migrations import run_migrations
from models import Asset, Folder

# --- infrastructure ---------------------------------------------------------


def auth_header(client: TestClient) -> dict:
    """Bearer token, or empty when the app is running with auth disabled."""
    health = client.get("/health").json()
    if not health.get("auth_required"):
        return {}
    token = client.post("/login", json={"username": "admin", "password": "super-secret"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def filesystem_snapshot(root: Path) -> tuple:
    """Paths, kinds and sizes of the whole tree; enough to prove nothing moved."""
    return tuple(
        sorted(
            (str(path.relative_to(root)) or ".", path.is_dir(), path.stat().st_size)
            for path in [root, *root.rglob("*")]
        )
    )


def write_placeholder_file(path: Path, payload: bytes = b"placeholder") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def insert_folder_row(name: str, parent_id: Optional[str] = None, storage_path: Optional[str] = None) -> str:
    """Insert a folder row the way a library scan would: no directory, no path."""
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
    source_path: Optional[str] = None,
) -> str:
    asset = Asset(
        filename=filename,
        mime="model/stl",
        size=10,
        name=name,
        folder_id=folder_id,
        storage_path=storage_path,
        source_path=source_path,
    )
    with Session(engine) as session:
        session.add(asset)
        session.commit()
        session.refresh(asset)
        return asset.id


def read_asset(asset_id: str) -> Optional[Asset]:
    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        if asset is not None:
            session.expunge(asset)
    return asset


def read_folder(folder_id: str) -> Optional[Folder]:
    with Session(engine) as session:
        folder = session.get(Folder, folder_id)
        if folder is not None:
            session.expunge(folder)
    return folder


def created_folder(client: TestClient, headers: dict, name: str, parent_id: Optional[str] = None) -> dict:
    response = client.post("/folders", json={"name": name, "tags": [], "parent_id": parent_id}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def set_template(client: TestClient, headers: dict, template: str) -> dict:
    response = client.post("/settings/storage", json={"template": template}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point storage at a temp root, restore the template and undo every row made."""
    storage = tmp_path / "storage"
    (storage / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(library_scan, "STORAGE", storage)
    # asset_service binds STORAGE at import time, so the module global is patched too.
    monkeypatch.setattr(asset_service, "STORAGE", storage)
    # The schema is created by the app lifespan; a single-file run needs it first.
    run_migrations(engine)
    template_before = settings_service.get_storage_template()
    with Session(engine) as session:
        folders_before = {folder.id for folder in session.exec(select(Folder))}
        assets_before = {asset.id for asset in session.exec(select(Asset))}
    yield storage
    settings_service.set_storage_template(template_before)
    with Session(engine) as session:
        for asset in list(session.exec(select(Asset))):
            if asset.id not in assets_before:
                session.delete(asset)
        for folder in list(session.exec(select(Folder))):
            if folder.id not in folders_before:
                session.delete(folder)
        session.commit()


# --- metadata edits never move files ----------------------------------------


def test_tags_edit_leaves_bytes_and_storage_path_alone(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        set_template(client, headers, "{creator}/{tags}/{filename}")
        asset_id = insert_asset_row("Tagged model", None, "Somewhere/model.stl")
        write_placeholder_file(storage / "Somewhere" / "model.stl", b"original bytes")
        before = filesystem_snapshot(storage)

        response = client.post(f"/asset/{asset_id}/tags", json={"tags": ["print", "useful"]}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["tags"] == ["print", "useful"]
        assert filesystem_snapshot(storage) == before

    assert read_asset(asset_id).storage_path == "Somewhere/model.stl"
    assert (storage / "Somewhere" / "model.stl").read_bytes() == b"original bytes"


def test_notes_creator_collection_edit_leaves_bytes_alone(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        set_template(client, headers, "{collection}/{creator}/{filename}")
        asset_id = insert_asset_row("Described model", None, "Somewhere/model.stl")
        write_placeholder_file(storage / "Somewhere" / "model.stl", b"original bytes")
        before = filesystem_snapshot(storage)

        response = client.post(
            f"/asset/{asset_id}/meta",
            json={"notes": "a note", "creator": "Someone", "collection": "Tabletop"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["notes"] == "a note"
        assert body["creator"] == "Someone"
        assert body["collection"] == "Tabletop"
        assert body["storage_path"] == "Somewhere/model.stl"
        assert filesystem_snapshot(storage) == before

    assert (storage / "Somewhere" / "model.stl").read_bytes() == b"original bytes"


def test_explicit_rename_moves_only_the_basename(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        set_template(client, headers, "{folder}/{tags}/{filename}")
        asset_id = insert_asset_row("Renamed model", None, "Somewhere/model.stl")
        write_placeholder_file(storage / "Somewhere" / "model.stl", b"stl bytes")

        response = client.post(f"/asset/{asset_id}/rename", json={"filename": "renamed.stl"}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["filename"] == "renamed.stl"

    asset = read_asset(asset_id)
    assert asset is not None
    assert asset.storage_path == "Somewhere/renamed.stl"
    assert Path(asset.storage_path).parent.as_posix() == "Somewhere"
    assert (storage / "Somewhere" / "renamed.stl").read_bytes() == b"stl bytes"
    assert not (storage / "Somewhere" / "model.stl").exists()


def test_meta_name_change_renames_in_place(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        set_template(client, headers, "{folder}/{tags}/{filename}")
        asset_id = insert_asset_row("Edited model", None, "Somewhere/model.stl")
        write_placeholder_file(storage / "Somewhere" / "model.stl", b"edited bytes")

        response = client.post(f"/asset/{asset_id}/meta", json={"name": "Meta renamed"}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["filename"] == "Meta renamed.stl"

    asset = read_asset(asset_id)
    assert asset is not None
    assert asset.storage_path == "Somewhere/Meta renamed.stl"
    assert Path(asset.storage_path).parent.as_posix() == "Somewhere"
    assert (storage / "Somewhere" / "Meta renamed.stl").read_bytes() == b"edited bytes"
    assert not (storage / "Unassigned").exists()
    assert not (storage / "Untagged").exists()


def test_rename_onto_an_occupied_path_is_rejected(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = insert_asset_row("First model", None, "Somewhere/model.stl")
        insert_asset_row("Other model", None, "Somewhere/taken.stl", filename="taken.stl")
        write_placeholder_file(storage / "Somewhere" / "model.stl", b"first bytes")
        write_placeholder_file(storage / "Somewhere" / "taken.stl", b"taken bytes")

        response = client.post(f"/asset/{asset_id}/rename", json={"filename": "taken.stl"}, headers=headers)
        assert response.status_code == 409, response.text

    assert read_asset(asset_id).storage_path == "Somewhere/model.stl"
    assert (storage / "Somewhere" / "model.stl").read_bytes() == b"first bytes"
    assert (storage / "Somewhere" / "taken.stl").read_bytes() == b"taken bytes"


# --- folder moves land in the folder's own directory ------------------------


def test_folder_move_lands_in_the_folder_directory(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        target = created_folder(client, headers, "Target")
        asset_id = insert_asset_row("Moving model", None, "Somewhere/model.stl")
        write_placeholder_file(storage / "Somewhere" / "model.stl", b"model bytes")

        response = client.post(f"/asset/{asset_id}/folder", json={"folder_id": target["id"]}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["folder_id"] == target["id"]
        assert response.json()["storage_path"] == "Target/model.stl"

    assert read_asset(asset_id).storage_path == "Target/model.stl"
    assert (storage / "Target" / "model.stl").read_bytes() == b"model bytes"
    assert not (storage / "Somewhere").exists()


def test_folder_move_into_scan_created_folder_uses_its_asset_directory(isolated_storage: Path) -> None:
    storage = isolated_storage
    scan_folder_id = insert_folder_row("Scanned", storage_path=None)
    insert_asset_row("Known thing", scan_folder_id, "Loose/Thing.3mf", filename="Thing.3mf")
    write_placeholder_file(storage / "Loose" / "Thing.3mf", b"thing bytes")
    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = insert_asset_row("Incoming model", None, "Somewhere/model.stl")
        write_placeholder_file(storage / "Somewhere" / "model.stl", b"model bytes")

        response = client.post(f"/asset/{asset_id}/folder", json={"folder_id": scan_folder_id}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["storage_path"] == "Loose/model.stl"

    assert read_asset(asset_id).storage_path == "Loose/model.stl"
    assert (storage / "Loose" / "model.stl").read_bytes() == b"model bytes"
    assert (storage / "Loose" / "Thing.3mf").read_bytes() == b"thing bytes"
    # A scan-created folder keeps its NULL path; the move only reads its files.
    assert read_folder(scan_folder_id).storage_path is None


def test_unfiling_lands_at_the_storage_root(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        folder = created_folder(client, headers, "Box")
        asset_id = insert_asset_row("Boxed model", folder["id"], "Box/model.stl")
        write_placeholder_file(storage / "Box" / "model.stl", b"boxed bytes")

        response = client.post(f"/asset/{asset_id}/folder", json={"folder_id": None}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["folder_id"] is None
        assert response.json()["storage_path"] == "model.stl"

    assert (storage / "model.stl").read_bytes() == b"boxed bytes"
    assert not (storage / "Box").exists()

    # The moved file must be the row's own file, not a new one the scan registers.
    state = library_scan.scan_storage_root()
    assert state.registered == 0
    assert state.known == 1


def test_folder_move_of_a_mount_row_touches_no_files(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        target = created_folder(client, headers, "Mount target")
        asset_id = insert_asset_row(
            "Mounted model",
            None,
            "Mount/Thing.3mf",
            filename="Thing.3mf",
            source_path="/mnt/models/Thing.3mf",
        )
        before = filesystem_snapshot(storage)

        response = client.post(f"/asset/{asset_id}/folder", json={"folder_id": target["id"]}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["storage_path"] == "Mount target/Thing.3mf"
        assert filesystem_snapshot(storage) == before

    asset = read_asset(asset_id)
    assert asset is not None
    assert asset.storage_path == "Mount target/Thing.3mf"
    assert asset.source_path == "/mnt/models/Thing.3mf"
    assert asset.folder_id == target["id"]


def test_folder_move_to_the_same_folder_is_a_no_op(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        folder = created_folder(client, headers, "Same place")
        asset_id = insert_asset_row("Settled model", folder["id"], "Same place/model.stl")
        write_placeholder_file(storage / "Same place" / "model.stl", b"settled bytes")
        before = filesystem_snapshot(storage)

        response = client.post(f"/asset/{asset_id}/folder", json={"folder_id": folder["id"]}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["storage_path"] == "Same place/model.stl"
        assert filesystem_snapshot(storage) == before

    assert (storage / "Same place" / "model.stl").read_bytes() == b"settled bytes"


# --- new uploads are the only consumers of the template --------------------


def test_new_upload_uses_the_template_and_a_later_tag_edit_leaves_it_alone(isolated_storage: Path) -> None:
    """New uploads are the only place the storage template is rendered.

    Mf-k0kf wraps mount import over the ``library_scan`` copy mode and depends on
    uploads still landing at the templated path, so pin both halves here: a fresh
    upload honours the template, and a later metadata edit leaves it in place.
    """
    storage = isolated_storage
    payload = b"solid cube\nendsolid cube\n"
    with TestClient(app) as client:
        headers = auth_header(client)
        set_template(client, headers, "{collection}/{model}/{filename}")

        response = client.post(
            "/upload",
            files={"file": ("cube.stl", payload, "model/stl")},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        asset_id = body["id"]
        assert body["storage_path"] == "Uncollected/cube/cube.stl"
        assert (storage / "Uncollected/cube/cube.stl").read_bytes() == payload

        before = filesystem_snapshot(storage)
        response = client.post(f"/asset/{asset_id}/tags", json={"tags": ["print"]}, headers=headers)
        assert response.status_code == 200, response.text
        assert filesystem_snapshot(storage) == before
        assert read_asset(asset_id).storage_path == "Uncollected/cube/cube.stl"

        # Keep the temp tree tidy; the fixture removes the row at teardown.
        assert client.delete(f"/asset/{asset_id}", headers=headers).status_code == 200
