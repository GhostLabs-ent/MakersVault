"""Storage settings are a template for new files only (Mf-aoyv).

`POST /settings/storage` stores the template and returns; it never reorganizes
what is already on disk. `moved`/`skipped` stay on the response for wire
compatibility but are pinned at 0, and an old client that still sends
`apply_existing` must not be able to make the server move files.

Every test works in a temporary storage root: `db` and `asset_service` are both
pointed at it (`asset_service` binds `STORAGE` at import time). The database is
shared for the whole test session, so the template and the rows created here are
restored at teardown.
"""

from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import asset_service
import db
import settings_service
from asset_service import DEPRECATED_STORAGE_TEMPLATE_TOKENS, STORAGE_TEMPLATE_TOKENS
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


def insert_asset_row(name: str, folder_id: Optional[str], storage_path: Optional[str]) -> str:
    asset = Asset(
        filename="model.stl",
        mime="model/stl",
        size=10,
        name=name,
        folder_id=folder_id,
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


# --- endpoints --------------------------------------------------------------


def test_get_returns_template_default_tokens_and_sample(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        response = client.get("/settings/storage", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()

    assert body["template"] == settings_service.DEFAULT_STORAGE_TEMPLATE
    assert body["default_template"] == settings_service.DEFAULT_STORAGE_TEMPLATE
    # ADR 0003 retired `collection` from the picker: the advertised list is the
    # valid-token set minus the deprecated tokens, and nothing else shrinks.
    assert body["allowed_tokens"] == [t for t in STORAGE_TEMPLATE_TOKENS if t not in DEPRECATED_STORAGE_TEMPLATE_TOKENS]
    assert "collection" not in body["allowed_tokens"]
    assert body["sample_path"] == "Props/Workshop/Cable clip/Cable clip.3mf"
    assert body["moved"] == 0
    assert body["skipped"] == 0


def test_post_changes_the_template_without_moving_existing_files(isolated_storage: Path) -> None:
    storage = isolated_storage
    asset_id = insert_asset_row("Existing model", None, "Existing/model.stl")
    write_placeholder_file(storage / "Existing" / "model.stl", b"existing bytes")
    before = filesystem_snapshot(storage)

    with TestClient(app) as client:
        headers = auth_header(client)
        response = client.post("/settings/storage", json={"template": "{creator}/{filename}"}, headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()

    assert body["template"] == "{creator}/{filename}"
    assert body["sample_path"] == "Example creator/Cable clip.3mf"
    assert body["moved"] == 0
    assert body["skipped"] == 0
    assert filesystem_snapshot(storage) == before
    assert read_asset(asset_id).storage_path == "Existing/model.stl"
    assert (storage / "Existing" / "model.stl").read_bytes() == b"existing bytes"


def test_post_ignores_the_legacy_apply_existing_field(isolated_storage: Path) -> None:
    storage = isolated_storage
    asset_id = insert_asset_row("Legacy model", None, "Legacy/model.stl")
    write_placeholder_file(storage / "Legacy" / "model.stl", b"legacy bytes")
    before = filesystem_snapshot(storage)

    with TestClient(app) as client:
        headers = auth_header(client)
        response = client.post(
            "/settings/storage",
            json={"template": "{collection}/{filename}", "apply_existing": True},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()

    assert body["template"] == "{collection}/{filename}"
    assert body["moved"] == 0
    assert body["skipped"] == 0
    assert filesystem_snapshot(storage) == before
    assert read_asset(asset_id).storage_path == "Legacy/model.stl"
    assert (storage / "Legacy" / "model.stl").read_bytes() == b"legacy bytes"


@pytest.mark.parametrize(
    "template",
    [
        "{bogus}/{filename}",
        "Model",
        "{filename}/nested/file.stl",
    ],
)
def test_post_rejects_an_invalid_template(isolated_storage: Path, template: str) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        response = client.post("/settings/storage", json={"template": template}, headers=headers)
        assert response.status_code == 400, response.text
        # The rejected template must not have been stored.
        assert client.get("/settings/storage", headers=headers).json()["template"] == settings_service.DEFAULT_STORAGE_TEMPLATE


def test_a_saved_collection_template_keeps_working_though_it_is_not_advertised(isolated_storage: Path) -> None:
    """Retiring the token from the picker must not break an install that saved it."""
    with TestClient(app) as client:
        headers = auth_header(client)
        response = client.post("/settings/storage", json={"template": "{collection}/{filename}"}, headers=headers)
        assert response.status_code == 200, response.text

        response = client.get("/settings/storage", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()

    assert body["template"] == "{collection}/{filename}"
    assert body["sample_path"] == "Tabletop/Cable clip.3mf"
    assert "collection" not in body["allowed_tokens"]


def test_get_still_works_after_a_post(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        assert client.post("/settings/storage", json={"template": "{name}/{filename}"}, headers=headers).status_code == 200
        response = client.get("/settings/storage", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["template"] == "{name}/{filename}"
        assert response.json()["sample_path"] == "Cable clip/Cable clip.3mf"
