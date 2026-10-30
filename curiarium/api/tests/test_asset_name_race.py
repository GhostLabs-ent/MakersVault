"""Two uploads of one filename race the name and path unique indexes (Mf-lc9j).

``create_asset_record`` used to read the folder, raise 409 when the name was
taken and then commit: a check-then-act window two requests can both pass. The
database already enforces the invariant through the two indexes migration 003
creates - ``idx_asset_folder_name_unique`` on
``COALESCE(folder_id, ''), name COLLATE NOCASE`` and
``idx_asset_storage_path_unique`` on ``storage_path`` - so those indexes are the
arbiter. A losing upload must surface as 409, never as a 500, and a loser that
already moved its file on disk must put the bytes back.

The friendly pre-check stays as a fast path, so the tests that want the index to
decide monkeypatch it out. Every test works in a temporary storage root and
removes its own rows and files: the database is shared for the whole session.
"""

import threading
from functools import partial
from pathlib import Path
from typing import Callable, List, Optional
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import asset_service
import db
import library_scan
import schemas
import settings_service
import zip_service
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


def asset_ids() -> set[str]:
    with Session(engine) as session:
        return {asset.id for asset in session.exec(select(Asset))}


def rows_named(name: str, folder_id: Optional[str] = None) -> int:
    """Rows the folder/name unique index considers equal to ``name``."""
    with Session(engine) as session:
        rows = list(session.exec(select(Asset).where(Asset.folder_id == folder_id)))
    return sum(1 for row in rows if (row.name or "").casefold() == name.casefold())


def set_template(client: TestClient, headers: dict, template: str) -> dict:
    response = client.post("/settings/storage", json={"template": template}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def bypass_name_precheck(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the SELECT-then-raise pre-check always pass, as a stale read would."""

    def always_free(session: Session, requested: str, folder_id: Optional[str], exclude_id: Optional[str] = None) -> str:
        return asset_service.sanitize_path_segment(requested, "Model")

    monkeypatch.setattr(asset_service, "unique_model_name", always_free)


def run_concurrently(workers: List[Callable[[], object]]) -> List[object]:
    """Run every callable behind one barrier, collecting results or exceptions."""
    barrier = threading.Barrier(len(workers))
    outcomes: List[object] = []
    lock = threading.Lock()

    def run(worker: Callable[[], object]) -> None:
        barrier.wait()
        try:
            outcome = worker()
        except BaseException as error:  # recorded, asserted on by the caller
            outcome = error
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=run, args=(worker,)) for worker in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes


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


# --- the pre-check alone cannot decide --------------------------------------


def test_sequential_duplicate_upload_is_409(isolated_storage: Path) -> None:
    storage = isolated_storage
    payload = b"solid cube\nendsolid cube\n"
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = auth_header(client)
        set_template(client, headers, "{folder}/{model}/{filename}")

        first = client.post("/upload", files={"file": ("cube.stl", payload, "model/stl")}, headers=headers)
        assert first.status_code == 200, first.text
        asset_id = first.json()["id"]
        assert first.json()["storage_path"] == "Unassigned/cube/cube.stl"

        second = client.post("/upload", files={"file": ("cube.stl", payload, "model/stl")}, headers=headers)
        assert second.status_code == 409, second.text
        assert second.json()["detail"] == 'A model named "cube" already exists in this folder'

        assert rows_named("cube") == 1
        assert (storage / "Unassigned/cube/cube.stl").read_bytes() == payload
        response = client.delete(
            f"/asset/{asset_id}", params={"confirm_name": first.json()["filename"]}, headers=headers
        )
        assert response.status_code == 200, response.text


def test_stale_precheck_name_collision_is_409(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The name index, not the pre-check, decides: the row that wins is untouched."""
    storage = isolated_storage
    existing_id = insert_asset_row("cube", None, "Somewhere/other.stl", filename="other.stl")
    write_placeholder_file(storage / "Somewhere/other.stl", b"existing bytes")
    bypass_name_precheck(monkeypatch)
    before = asset_ids()

    with TestClient(app, raise_server_exceptions=False) as client:
        headers = auth_header(client)
        set_template(client, headers, "{folder}/{model}/{filename}")
        response = client.post("/upload", files={"file": ("cube.stl", b"solid cube\n", "model/stl")}, headers=headers)
        assert response.status_code == 409, response.text
        assert 'A model named "cube" already exists in this folder' in response.json()["detail"]

    assert asset_ids() == before
    existing = read_asset(existing_id)
    assert existing is not None
    assert existing.name == "cube"
    assert existing.storage_path == "Somewhere/other.stl"
    assert (storage / "Somewhere/other.stl").read_bytes() == b"existing bytes"


def test_stale_precheck_path_collision_is_409(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A different name but the same rendered path: the path index rejects it."""
    storage = isolated_storage
    existing_id = insert_asset_row("placeholder", None, "Unassigned/cube/cube.stl", filename="cube.stl")
    write_placeholder_file(storage / "Unassigned/cube/cube.stl", b"existing bytes")
    bypass_name_precheck(monkeypatch)
    before = asset_ids()

    with TestClient(app, raise_server_exceptions=False) as client:
        headers = auth_header(client)
        set_template(client, headers, "{folder}/{model}/{filename}")
        response = client.post("/upload", files={"file": ("cube.stl", b"solid cube\n", "model/stl")}, headers=headers)
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == "Storage path already exists: Unassigned/cube/cube.stl"

    assert asset_ids() == before
    existing = read_asset(existing_id)
    assert existing is not None
    assert existing.name == "placeholder"
    assert (storage / "Unassigned/cube/cube.stl").read_bytes() == b"existing bytes"


# --- the index is the arbiter under concurrency -----------------------------


def test_concurrent_create_asset_record_yields_one_row(isolated_storage: Path) -> None:
    """Six inserts of one name: one row, five 409s, no 500 and no stray row."""

    def create() -> object:
        return asset_service.create_asset_record("cube.stl", "model/stl", None, None, [], None)

    outcomes = run_concurrently([create] * 6)

    unexpected = [outcome for outcome in outcomes if not isinstance(outcome, (Asset, HTTPException))]
    assert unexpected == [], unexpected
    created = [outcome for outcome in outcomes if isinstance(outcome, Asset)]
    conflicts = [outcome for outcome in outcomes if isinstance(outcome, HTTPException)]
    assert len(created) == 1
    assert len(conflicts) == 5
    assert all(conflict.status_code == 409 for conflict in conflicts)
    assert rows_named("cube") == 1

    asset_service.cleanup_asset(created[0].id)
    assert rows_named("cube") == 0


def test_concurrent_uploads_never_500(isolated_storage: Path) -> None:
    storage = isolated_storage
    payload = b"solid cube\nendsolid cube\n"
    # The lifespan (migrations included) runs once, in the main thread only.
    with TestClient(app, raise_server_exceptions=False) as bootstrap:
        headers = auth_header(bootstrap)
        set_template(bootstrap, headers, "{folder}/{model}/{filename}")

    def upload():
        client = TestClient(app, raise_server_exceptions=False)
        return client.post("/upload", files={"file": ("cube.stl", payload, "model/stl")}, headers=headers)

    outcomes = run_concurrently([upload] * 4)

    unexpected = [outcome for outcome in outcomes if not hasattr(outcome, "status_code")]
    assert unexpected == [], unexpected
    statuses = [outcome.status_code for outcome in outcomes]
    assert sorted(statuses) == [200, 409, 409, 409]
    assert rows_named("cube") == 1
    assert (storage / "Unassigned/cube/cube.stl").read_bytes() == payload

    winner = next(outcome for outcome in outcomes if outcome.status_code == 200)
    winner_id = winner.json()["id"]
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.delete(
            f"/asset/{winner_id}", params={"confirm_name": winner.json()["filename"]}, headers=headers
        )
        assert response.status_code == 200, response.text


def test_concurrent_renames_never_500_and_keep_disk_consistent(isolated_storage: Path) -> None:
    """The loser moved its file before committing, so the bytes must move back."""
    storage = isolated_storage
    payloads = {insert_asset_row("alpha", None, "Alpha/alpha.stl", filename="alpha.stl"): b"alpha bytes"}
    payloads[insert_asset_row("beta", None, "Beta/beta.stl", filename="beta.stl")] = b"beta bytes"
    for asset_id, payload in payloads.items():
        write_placeholder_file(storage / read_asset(asset_id).storage_path, payload)
    before = {asset_id: read_asset(asset_id) for asset_id in payloads}

    with TestClient(app, raise_server_exceptions=False) as client:
        headers = auth_header(client)

        def rename(asset_id: str) -> tuple[str, int]:
            thread_client = TestClient(app, raise_server_exceptions=False)
            response = thread_client.post(f"/asset/{asset_id}/rename", json={"filename": "gamma.stl"}, headers=headers)
            return asset_id, response.status_code

        outcomes = run_concurrently([partial(rename, asset_id) for asset_id in payloads])

    unexpected = [outcome for outcome in outcomes if not isinstance(outcome, tuple)]
    assert unexpected == [], unexpected
    results = dict(outcomes)
    assert sorted(results.values()) == [200, 409]

    loser_id = next(asset_id for asset_id, status in results.items() if status == 409)
    winner_id = next(asset_id for asset_id, status in results.items() if status == 200)

    loser = read_asset(loser_id)
    assert loser is not None
    assert (loser.name, loser.filename, loser.storage_path) == (
        before[loser_id].name,
        before[loser_id].filename,
        before[loser_id].storage_path,
    )
    assert (storage / loser.storage_path).read_bytes() == payloads[loser_id]
    assert not (storage / Path(loser.storage_path).parent / "gamma.stl").exists()

    winner = read_asset(winner_id)
    assert winner is not None
    assert winner.name == "gamma"
    assert winner.filename == "gamma.stl"
    assert winner.storage_path == f"{Path(before[winner_id].storage_path).parent.as_posix()}/gamma.stl"
    assert (storage / winner.storage_path).read_bytes() == payloads[winner_id]


# --- a zip duplicate is one failed entry, not a failed import ---------------


def test_zip_duplicate_entry_lands_in_failed(isolated_storage: Path, tmp_path: Path) -> None:
    storage = isolated_storage
    existing_id = insert_asset_row("taken", None, "Somewhere/taken.stl", filename="taken.stl")
    write_placeholder_file(storage / "Somewhere/taken.stl", b"taken bytes")
    zip_path = tmp_path / "bundle.zip"
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("taken.stl", b"incoming bytes")
    before = asset_ids()

    assets, failed = zip_service.extract_zip_entries_to_assets(
        zip_path,
        ["taken.stl"],
        schemas.ImportZipExtractRequest(
            url="http://example.invalid/bundle.zip",
            entries=["taken.stl"],
            folder_id=None,
            title=None,
            notes=None,
            tags=[],
        ),
    )

    assert assets == []
    assert failed == ["taken.stl"]
    assert asset_ids() == before
    existing = read_asset(existing_id)
    assert existing is not None
    assert existing.storage_path == "Somewhere/taken.stl"
    assert (storage / "Somewhere/taken.stl").read_bytes() == b"taken bytes"
