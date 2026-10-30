"""`Asset.collection` is deprecated, not removed (ADR 0003).

ADR 0003 retires the field on the authoring side: the settings token picker stops
advertising it and the API schema carries a deprecation note. Reading it back and
searching by it must keep working, because old clients still send and display it.

Every test works in a temporary storage root and the database is shared for the
whole session, so the rows created here are deleted at teardown.
"""

from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import asset_service
import db
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


def insert_asset_row(name: str, collection: Optional[str]) -> str:
    asset = Asset(
        filename="model.stl",
        mime="model/stl",
        size=10,
        name=name,
        folder_id=None,
        # Derived from the name: storage_path is uniquely indexed, so two rows in
        # one test must not share it.
        storage_path=f"Somewhere/{name}.stl",
        collection=collection,
    )
    with Session(engine) as session:
        session.add(asset)
        session.commit()
        session.refresh(asset)
        return asset.id


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


# --- schema pin -------------------------------------------------------------


def test_openapi_marks_collection_deprecated_on_both_models(isolated_storage: Path) -> None:
    """ADR 0003 calls for a deprecation note in the API schema itself.

    The fields stay on the models (old clients keep working), but the generated
    document must tell new clients to stop using them.
    """
    schemas = app.openapi()["components"]["schemas"]
    assert schemas["AssetOut"]["properties"]["collection"]["deprecated"] is True
    assert schemas["AssetMetaUpdate"]["properties"]["collection"]["deprecated"] is True
    # Still present, just marked: removing them would break old clients.
    assert "collection" in schemas["AssetOut"]["required"]


# --- reading still works ----------------------------------------------------


def test_free_text_search_still_matches_the_collection_value(isolated_storage: Path) -> None:
    """Deprecation targets authoring, not reading: `q` must still find old rows.

    The term appears only in `collection`, never in a name, title, note or
    filename, so this fails if the collection clause leaves the search filter.
    The second row is the negative control.
    """
    asset_id = insert_asset_row("Scenery piece", "Tabletop")
    insert_asset_row("Blank piece", None)
    with TestClient(app) as client:
        headers = auth_header(client)
        response = client.get("/assets", params={"q": "Tabletop"}, headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()

    assert [asset["id"] for asset in body] == [asset_id]
    assert body[0]["collection"] == "Tabletop"
