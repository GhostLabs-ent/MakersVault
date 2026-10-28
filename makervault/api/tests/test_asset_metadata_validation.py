"""Metadata validation rules (Mf-pnc2).

Creator, name, title and notes are normalised by pydantic field validators, so
bad input is a 422 at the request edge - before any rename/sanitising helper can
quietly rewrite it. Every test works in a temporary storage root and the
database is shared for the whole session, so rows created here are deleted at
teardown.
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


def write_placeholder_file(path: Path, payload: bytes = b"placeholder") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def insert_asset_row(
    name: str,
    storage_path: str,
    *,
    filename: str = "model.stl",
    creator: Optional[str] = None,
    notes: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    asset = Asset(
        filename=filename,
        mime="model/stl",
        size=10,
        name=name,
        title=title,
        notes=notes,
        creator=creator,
        folder_id=None,
        storage_path=storage_path,
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


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point storage at a temp root, restore the template and undo every row made."""
    storage = tmp_path / "storage"
    (storage / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(library_scan, "STORAGE", storage)
    monkeypatch.setattr(asset_service, "STORAGE", storage)
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


# --- rejected input is a 422, never a silent rewrite ------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"creator": "x" * 121},
        {"creator": "bad\x00creator"},
        {"creator": "line\nbreak"},
        {"name": "x" * 121},
        {"name": "../../etc/passwd"},
        {"name": "dir\\name"},
        {"name": "   "},
        {"name": ""},
        {"title": "dir/name"},
        {"title": "bad\x07title"},
        {"title": "   "},
        {"notes": "x" * 4001},
        {"notes": "bad\x00note"},
        {"notes": "carriage\rreturn"},
    ],
)
def test_invalid_metadata_is_422(isolated_storage: Path, payload: dict) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = insert_asset_row("Original model", "Validation/model.stl")
        write_placeholder_file(isolated_storage / "Validation" / "model.stl", b"bytes")

        response = client.post(f"/asset/{asset_id}/meta", json=payload, headers=headers)

        assert response.status_code == 422, response.text

    # Nothing was renamed or edited on the way to the 422.
    asset = read_asset(asset_id)
    assert asset is not None
    assert asset.name == "Original model"
    assert asset.filename == "model.stl"
    assert asset.storage_path == "Validation/model.stl"
    assert (isolated_storage / "Validation" / "model.stl").read_bytes() == b"bytes"


def test_path_separator_is_rejected_before_sanitising(isolated_storage: Path) -> None:
    """`../../x` must be a 422, not a name that sanitising turns into `.._.._x`."""
    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = insert_asset_row("Original model", "Validation/model.stl")
        write_placeholder_file(isolated_storage / "Validation" / "model.stl", b"bytes")

        response = client.post(f"/asset/{asset_id}/meta", json={"name": "safe/../../escape"}, headers=headers)

        assert response.status_code == 422, response.text
        assert response.json()["detail"][0]["loc"][-1] == "name"

    assert read_asset(asset_id).name == "Original model"


# --- normalisation ----------------------------------------------------------


def test_creator_is_trimmed_and_collapsed(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = insert_asset_row("Original model", "Validation/model.stl")

        response = client.post(
            f"/asset/{asset_id}/meta", json={"creator": "  Ada   Lovelace  "}, headers=headers
        )

        assert response.status_code == 200, response.text
        assert response.json()["creator"] == "Ada Lovelace"

    assert read_asset(asset_id).creator == "Ada Lovelace"


def test_creator_accepts_unicode_and_apostrophes(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = insert_asset_row("Original model", "Validation/model.stl")

        response = client.post(f"/asset/{asset_id}/meta", json={"creator": "Zoë O'Lovelace ✓"}, headers=headers)

        assert response.status_code == 200, response.text
        assert response.json()["creator"] == "Zoë O'Lovelace ✓"


def test_name_and_title_are_trimmed_and_collapsed(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = insert_asset_row("Original model", "Validation/model.stl")
        write_placeholder_file(isolated_storage / "Validation" / "model.stl", b"bytes")

        response = client.post(f"/asset/{asset_id}/meta", json={"name": "  My   Model  "}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "My Model"
        assert response.json()["filename"] == "My Model.stl"

        # Title follows the same rules and the same rename path.
        response = client.post(f"/asset/{asset_id}/meta", json={"title": "  Other   Name  "}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Other Name"
        assert response.json()["title"] == "Other Name"


def test_name_accepts_unicode_and_punctuation(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = insert_asset_row("Original model", "Validation/model.stl")
        write_placeholder_file(isolated_storage / "Validation" / "model.stl", b"bytes")

        response = client.post(f"/asset/{asset_id}/meta", json={"name": "Café d'Art (v2)"}, headers=headers)

        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Café d'Art (v2)"


def test_notes_keep_internal_whitespace_and_line_breaks(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = insert_asset_row("Original model", "Validation/model.stl")

        response = client.post(
            f"/asset/{asset_id}/meta", json={"notes": "  line one\n  line two\tend  "}, headers=headers
        )

        assert response.status_code == 200, response.text
        assert response.json()["notes"] == "line one\n  line two\tend"


# --- clearing ---------------------------------------------------------------


def test_blank_creator_and_notes_clear(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = insert_asset_row(
            "Original model", "Validation/model.stl", creator="Someone", notes="a note"
        )

        response = client.post(f"/asset/{asset_id}/meta", json={"creator": "   ", "notes": "\n\t "}, headers=headers)

        assert response.status_code == 200, response.text
        assert response.json()["creator"] is None
        assert response.json()["notes"] is None

    asset = read_asset(asset_id)
    assert asset.creator is None
    assert asset.notes is None


def test_explicit_null_still_means_unchanged_on_the_single_endpoint(isolated_storage: Path) -> None:
    """The single editor's legacy contract: absent and null are the same no-op."""
    with TestClient(app) as client:
        headers = auth_header(client)
        asset_id = insert_asset_row(
            "Original model", "Validation/model.stl", creator="Keep me", notes="keep these"
        )

        response = client.post(f"/asset/{asset_id}/meta", json={"creator": None, "notes": None}, headers=headers)

        assert response.status_code == 200, response.text
        assert response.json()["creator"] == "Keep me"
        assert response.json()["notes"] == "keep these"

    asset = read_asset(asset_id)
    assert asset.creator == "Keep me"
    assert asset.notes == "keep these"
