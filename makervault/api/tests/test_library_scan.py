"""Tests for the storage-root scanner (filesystem-authoritative library, phase 1)."""
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import main
from db import STORAGE, engine
from library_scan import scan_storage_root
from models import Asset, Folder


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
    library_root.remove(rel)


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
