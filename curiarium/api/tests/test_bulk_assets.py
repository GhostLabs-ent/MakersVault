"""Bulk asset endpoints: one request, one result per id (Mf-7c68).

Tags, folder moves and deletes are now batched so a library-wide edit is one
request instead of one per asset. The contract is partial success: every item
runs in its own transaction, a failing item lands in ``failed`` with the status
the equivalent single-item route would have returned, and the rest still apply.
Only a request that could change nothing at all (no ids, nothing to change,
unknown folder) is a whole-request 400.

The batch folder move reuses the single-item move verbatim, so these tests also
pin the Mf-2bvy no-clobber guarantee: a conflicting move must leave the source
bytes untouched and the destination's committed bytes intact.

Every test works in a temporary storage root (``db``, ``library_scan``,
``asset_service`` and ``asset_file_service`` all bind ``STORAGE`` at import
time). The database is shared for the whole session, so rows created by a test
are deleted again at teardown.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import asset_file_service
import asset_service
import db
import library_scan
import settings_service
from db import engine
from main import app
from migrations import run_migrations
from models import Asset, AuditEvent, Folder

# --- infrastructure ---------------------------------------------------------


def auth_header(client: TestClient) -> dict:
    """Bearer token, or empty when the app is running with auth disabled."""
    health = client.get("/health").json()
    if not health.get("auth_required"):
        return {}
    token = client.post("/login", json={"username": "admin", "password": "super-secret"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point storage at a temp root, restore the template and undo every row made."""
    storage = tmp_path / "storage"
    (storage / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(library_scan, "STORAGE", storage)
    # asset_service and asset_file_service bind STORAGE at import time, so the
    # module globals are patched too.
    monkeypatch.setattr(asset_service, "STORAGE", storage)
    monkeypatch.setattr(asset_file_service, "STORAGE", storage)
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


def upload(client: TestClient, headers: dict, name: str, payload: bytes, folder_id: str | None = None) -> dict:
    """Upload one model and return its AssetOut body."""
    data = {"folder_id": folder_id} if folder_id else {}
    response = client.post(
        "/upload",
        files={"file": (name, payload, "model/stl")},
        data=data,
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_folder(client: TestClient, headers: dict, name: str) -> dict:
    response = client.post("/folders", json={"name": name, "tags": [], "parent_id": None}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def listed_assets(client: TestClient, headers: dict) -> dict:
    response = client.get("/assets", headers=headers)
    assert response.status_code == 200, response.text
    return {asset["id"]: asset for asset in response.json()}


def audit_rows_for(request_id: str) -> list[AuditEvent]:
    with Session(engine) as session:
        return list(session.exec(select(AuditEvent).where(AuditEvent.request_id == request_id)))


# --- tags -------------------------------------------------------------------


def test_batch_tags_updates_every_asset_in_one_request(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        ids = [upload(client, headers, f"{name}.stl", f"solid {name}\n".encode())["id"] for name in ("alpha", "beta", "gamma")]

        response = client.post("/assets/batch/tags", json={"asset_ids": ids, "add_tags": ["batch"]}, headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["updated"]) == 3
        assert body["failed"] == []
        assert [asset["id"] for asset in body["updated"]] == ids
        assert all(asset["tags"] == ["batch"] for asset in body["updated"])

        # Persisted, not just echoed: a fresh read sees the tag on every asset.
        listed = listed_assets(client, headers)
        assert all(listed[asset_id]["tags"] == ["batch"] for asset_id in ids)

        response = client.post("/assets/batch/tags", json={"asset_ids": ids, "remove_tags": ["batch"]}, headers=headers)
        assert response.status_code == 200, response.text
        assert [asset["tags"] for asset in response.json()["updated"]] == [[], [], []]
        listed = listed_assets(client, headers)
        assert all(listed[asset_id]["tags"] == [] for asset_id in ids)


def test_batch_tags_reports_unknown_id_per_id(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        first = upload(client, headers, "alpha.stl", b"solid alpha\n")["id"]
        second = upload(client, headers, "beta.stl", b"solid beta\n")["id"]

        response = client.post(
            "/assets/batch/tags",
            json={"asset_ids": [first, "does-not-exist", second], "add_tags": ["batch"]},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert [asset["id"] for asset in body["updated"]] == [first, second]
        assert len(body["failed"]) == 1
        failure = body["failed"][0]
        assert failure["id"] == "does-not-exist"
        assert failure["code"] == "not_found"
        assert failure["status"] == 404
        assert failure["error"] == "Asset not found"

        # The neighbours really changed: the failure did not roll them back.
        listed = listed_assets(client, headers)
        assert listed[first]["tags"] == ["batch"]
        assert listed[second]["tags"] == ["batch"]


def test_batch_tags_without_a_change_is_400(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = upload(client, headers, "alpha.stl", b"solid alpha\n")["id"]

        response = client.post(
            "/assets/batch/tags",
            json={"asset_ids": [asset_id], "add_tags": ["  "], "remove_tags": []},
            headers=headers,
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"] == "Provide add_tags or remove_tags"
        assert listed_assets(client, headers)[asset_id]["tags"] == []


def test_batch_tags_without_ids_is_400(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)

        response = client.post("/assets/batch/tags", json={"asset_ids": ["  "], "add_tags": ["batch"]}, headers=headers)
        assert response.status_code == 400, response.text
        assert response.json()["detail"] == "asset_ids is required"


# --- metadata --------------------------------------------------------------


def test_batch_meta_updates_every_asset(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        ids = [upload(client, headers, f"{name}.stl", f"solid {name}\n".encode())["id"] for name in ("alpha", "beta", "gamma")]

        response = client.post(
            "/assets/batch/meta",
            json={"asset_ids": ids, "creator": "  Ada   Lovelace  ", "notes": "batch note"},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["failed"] == []
        assert [asset["id"] for asset in body["updated"]] == ids
        assert all(asset["creator"] == "Ada Lovelace" for asset in body["updated"])
        assert all(asset["notes"] == "batch note" for asset in body["updated"])

        # Persisted, not just echoed: a fresh read sees both values on every asset.
        listed = listed_assets(client, headers)
        assert all(listed[asset_id]["creator"] == "Ada Lovelace" for asset_id in ids)
        assert all(listed[asset_id]["notes"] == "batch note" for asset_id in ids)


def test_batch_meta_clears_on_null_and_blank(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = upload(client, headers, "alpha.stl", b"solid alpha\n")["id"]
        assert (
            client.post(f"/asset/{asset_id}/meta", json={"creator": "Someone", "notes": "a note"}, headers=headers).status_code
            == 200
        )

        # Explicit null clears creator (the batch contract), while an absent
        # notes field leaves notes alone.
        response = client.post("/assets/batch/meta", json={"asset_ids": [asset_id], "creator": None}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["updated"][0]["creator"] is None
        assert response.json()["updated"][0]["notes"] == "a note"

        # A blank string clears notes the same way.
        response = client.post("/assets/batch/meta", json={"asset_ids": [asset_id], "notes": "   "}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["updated"][0]["creator"] is None
        assert response.json()["updated"][0]["notes"] is None

        listed = listed_assets(client, headers)
        assert listed[asset_id]["creator"] is None
        assert listed[asset_id]["notes"] is None


def test_batch_meta_absent_field_is_unchanged(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = upload(client, headers, "alpha.stl", b"solid alpha\n")["id"]
        assert (
            client.post(f"/asset/{asset_id}/meta", json={"creator": "Someone", "notes": "a note"}, headers=headers).status_code
            == 200
        )

        response = client.post("/assets/batch/meta", json={"asset_ids": [asset_id], "creator": "Else"}, headers=headers)

        assert response.status_code == 200, response.text
        assert response.json()["updated"][0]["creator"] == "Else"
        assert response.json()["updated"][0]["notes"] == "a note"


def test_batch_meta_reports_an_unknown_id_per_id(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        first = upload(client, headers, "alpha.stl", b"solid alpha\n")["id"]
        second = upload(client, headers, "beta.stl", b"solid beta\n")["id"]

        response = client.post(
            "/assets/batch/meta",
            json={"asset_ids": [first, "does-not-exist", second], "creator": "Batch creator"},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert [asset["id"] for asset in body["updated"]] == [first, second]
        assert len(body["failed"]) == 1
        failure = body["failed"][0]
        assert failure["id"] == "does-not-exist"
        assert failure["code"] == "not_found"
        assert failure["status"] == 404
        assert failure["error"] == "Asset not found"

        listed = listed_assets(client, headers)
        assert listed[first]["creator"] == "Batch creator"
        assert listed[second]["creator"] == "Batch creator"


def test_batch_meta_without_ids_is_400(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)

        response = client.post("/assets/batch/meta", json={"asset_ids": ["  "], "creator": "Someone"}, headers=headers)

        assert response.status_code == 400, response.text
        assert response.json()["detail"] == "asset_ids is required"


def test_batch_meta_without_a_change_is_400(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = upload(client, headers, "alpha.stl", b"solid alpha\n")["id"]

        response = client.post("/assets/batch/meta", json={"asset_ids": [asset_id]}, headers=headers)

        assert response.status_code == 400, response.text
        assert response.json()["detail"] == "Provide creator or notes"


def test_batch_meta_validates_once_for_the_whole_request(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        ids = [upload(client, headers, f"{name}.stl", f"solid {name}\n".encode())["id"] for name in ("alpha", "beta")]

        response = client.post(
            "/assets/batch/meta",
            json={"asset_ids": ids, "creator": "x" * 121},
            headers=headers,
        )

        assert response.status_code == 422, response.text
        listed = listed_assets(client, headers)
        assert all(listed[asset_id]["creator"] is None for asset_id in ids)


def test_batch_meta_refuses_title_and_name(isolated_storage: Path) -> None:
    """A batch payload cannot alias a rename and mass-move files on disk."""
    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = upload(client, headers, "alpha.stl", b"solid alpha\n")["id"]

        response = client.post(
            "/assets/batch/meta",
            json={"asset_ids": [asset_id], "title": "Mass rename"},
            headers=headers,
        )

        assert response.status_code == 422, response.text
        assert listed_assets(client, headers)[asset_id]["filename"] == "alpha.stl"


def test_batch_meta_never_renames_on_disk(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        uploaded = upload(client, headers, "alpha.stl", b"solid alpha\n")
        before_path = storage / uploaded["storage_path"]
        before_bytes = before_path.read_bytes()

        response = client.post(
            "/assets/batch/meta",
            json={"asset_ids": [uploaded["id"]], "creator": "Someone", "notes": "note"},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["updated"][0]["filename"] == "alpha.stl"
        assert response.json()["updated"][0]["storage_path"] == uploaded["storage_path"]
        assert before_path.read_bytes() == before_bytes

    listed_path = storage / uploaded["storage_path"]
    assert listed_path.exists()
    assert listed_path.read_bytes() == before_bytes


def test_batch_meta_writes_no_audit_event(isolated_storage: Path) -> None:
    """Creator/notes are the exempt metadata class, like tags."""
    request_id = "batch-meta-no-audit"
    with TestClient(app) as client:
        headers = {**auth_header(client), "X-Request-ID": request_id}
        asset_id = upload(client, headers, "alpha.stl", b"solid alpha\n")["id"]

        response = client.post(
            "/assets/batch/meta",
            json={"asset_ids": [asset_id], "creator": "Someone"},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        assert response.headers["X-Request-ID"] == request_id

    assert audit_rows_for(request_id) == []


# --- folder moves -----------------------------------------------------------


def test_batch_folder_moves_every_asset(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        uploaded = [upload(client, headers, f"{name}.stl", f"solid {name}\n".encode()) for name in ("alpha", "beta", "gamma")]
        folder = create_folder(client, headers, "Parts")

        response = client.post("/assets/batch/folder", json={"asset_ids": [a["id"] for a in uploaded], "folder_id": folder["id"]}, headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["failed"] == []
        assert len(body["updated"]) == 3
        for asset in body["updated"]:
            assert asset["folder_id"] == folder["id"]
            assert (storage / asset["storage_path"]).read_bytes() == f"solid {asset['name']}\n".encode()
        for asset in uploaded:
            # The old path is really vacated, not just the row rewritten.
            assert not (storage / asset["storage_path"]).exists()


def test_batch_folder_conflict_is_per_id_and_preserves_bytes(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        folder = create_folder(client, headers, "Parts")
        resident_bytes = b"solid resident cube\n"
        resident = upload(client, headers, "cube.stl", resident_bytes, folder_id=folder["id"])
        conflicting = upload(client, headers, "cube.stl", b"solid root cube\n")
        movable = upload(client, headers, "sphere.stl", b"solid root sphere\n")

        response = client.post(
            "/assets/batch/folder",
            json={"asset_ids": [conflicting["id"], movable["id"]], "folder_id": folder["id"]},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert [asset["id"] for asset in body["updated"]] == [movable["id"]]
        assert len(body["failed"]) == 1
        failure = body["failed"][0]
        assert failure["id"] == conflicting["id"]
        assert failure["code"] == "conflict"
        assert failure["status"] == 409
        assert failure["error"] == 'A model named "cube" already exists in this folder'

        # Mf-2bvy no-clobber, asserted on bytes: the loser is untouched at its
        # original path, its destination is never created, and the resident's
        # bytes are unchanged.
        assert (storage / conflicting["storage_path"]).read_bytes() == b"solid root cube\n"
        assert (storage / resident["storage_path"]).read_bytes() == resident_bytes
        destination = storage / folder["storage_path"] / conflicting["filename"]
        assert not destination.exists()

        # The winner really moved: new path has the bytes, old path is vacated.
        moved = body["updated"][0]
        assert (storage / moved["storage_path"]).read_bytes() == b"solid root sphere\n"
        assert not (storage / movable["storage_path"]).exists()

        # The failed move did not move its row either.
        listed = listed_assets(client, headers)
        assert listed[conflicting["id"]]["folder_id"] is None
        assert listed[movable["id"]]["folder_id"] == folder["id"]
        assert listed[resident["id"]]["folder_id"] == folder["id"]


def test_batch_folder_unknown_folder_is_400(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        ids = [upload(client, headers, f"{name}.stl", f"solid {name}\n".encode())["id"] for name in ("alpha", "beta", "gamma")]

        response = client.post("/assets/batch/folder", json={"asset_ids": ids, "folder_id": "no-such-folder"}, headers=headers)
        assert response.status_code == 400, response.text
        assert response.json()["detail"] == "Folder not found"

        listed = listed_assets(client, headers)
        assert all(listed[asset_id]["folder_id"] is None for asset_id in ids)


# --- deletes ----------------------------------------------------------------


def test_batch_delete_reports_a_missing_id_per_id(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        uploaded = [upload(client, headers, f"{name}.stl", f"solid {name}\n".encode()) for name in ("alpha", "beta", "gamma")]
        gone = uploaded[1]["id"]

        response = client.delete(f"/asset/{gone}", params={"confirm_name": uploaded[1]["filename"]}, headers=headers)
        assert response.status_code == 200, response.text

        response = client.post(
            "/assets/batch/delete",
            json={"asset_ids": [asset["id"] for asset in uploaded], "confirm_count": 3},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["deleted"] == [uploaded[0]["id"], uploaded[2]["id"]]
        assert len(body["failed"]) == 1
        failure = body["failed"][0]
        assert failure["id"] == gone
        assert failure["code"] == "not_found"
        assert failure["status"] == 404

        listed = listed_assets(client, headers)
        assert all(asset["id"] not in listed for asset in uploaded)
        for asset in uploaded:
            assert not (storage / asset["storage_path"]).exists()


# --- the single-item routes still behave the same ---------------------------


def test_single_item_endpoints_still_work(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        tagged = upload(client, headers, "alpha.stl", b"solid alpha\n")

        response = client.post(f"/asset/{tagged['id']}/tags", json={"tags": ["one", "two"]}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["tags"] == ["one", "two"]

        folder = create_folder(client, headers, "Parts")
        upload(client, headers, "cube.stl", b"solid resident cube\n", folder_id=folder["id"])
        conflicting = upload(client, headers, "cube.stl", b"solid root cube\n")

        response = client.post(f"/asset/{conflicting['id']}/folder", json={"folder_id": folder["id"]}, headers=headers)
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == 'A model named "cube" already exists in this folder'
        # A successful move through the same route still works.
        response = client.post(f"/asset/{conflicting['id']}/folder", json={"folder_id": None}, headers=headers)
        assert response.status_code == 200, response.text

        response = client.delete(f"/asset/{tagged['id']}", params={"confirm_name": tagged["filename"]}, headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["trash_path"].startswith(".trash/")
        response = client.delete(f"/asset/{tagged['id']}", params={"confirm_name": tagged["filename"]}, headers=headers)
        assert response.status_code == 404, response.text
