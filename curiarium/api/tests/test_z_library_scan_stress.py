"""Scan a large synthetic tree while the API keeps serving reads.

``CURIARIUM_SCAN_STRESS`` sets how many files the tree holds. The default
5000 keeps the normal suite fast; the ticket's acceptance run is

    CURIARIUM_SCAN_STRESS=50000 python -m pytest tests/test_z_library_scan_stress.py -q

Everything is written to a pytest temp root, so nothing here touches a real
mount. The database is shared for the whole session, so the rows are bulk
deleted by storage-path prefix in ``finally`` and again before the scan starts.
"""
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

import library_scan
import main
from db import engine
from models import Asset, Folder

SCAN_FILES = int(os.getenv("CURIARIUM_SCAN_STRESS", "5000"))
FILES_PER_DIR = 100
ROOT_DIR_PREFIX = "zz-scan-stress"
DEADLINE_SECONDS = 900


def _auth_header(client: TestClient) -> dict:
    health = client.get("/health").json()
    if not health.get("auth_required"):
        return {}
    token = client.post("/login", json={"username": "admin", "password": "super-secret"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _build_tree(root: Path, files: int) -> int:
    """Write `files` .stl files over ~files/100 directories; return the tree size."""
    for index in range(files):
        path = root / f"{ROOT_DIR_PREFIX}-{index // FILES_PER_DIR:04d}" / f"part-{index:05d}.stl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"solid stress\n")
    return files


def _cleanup() -> None:
    """Bulk-delete this test's assets and folders, whatever state the run ended in."""
    with Session(engine) as session:
        session.execute(delete(Asset).where(Asset.storage_path.like(f"{ROOT_DIR_PREFIX}-%")))
        session.commit()
    with Session(engine) as session:
        for folder in list(session.exec(select(Folder))):
            if folder.name.startswith(ROOT_DIR_PREFIX):
                session.delete(folder)
        session.commit()


def test_scan_stays_accurate_and_responsive_under_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    expected_folders = (SCAN_FILES + FILES_PER_DIR - 1) // FILES_PER_DIR
    _build_tree(storage, SCAN_FILES)
    monkeypatch.setattr(library_scan, "STORAGE", storage)

    started = time.monotonic()
    try:
        with TestClient(main.app) as client:
            # the lifespan migrated the schema; start from a clean slate in case
            # an earlier run died before its cleanup
            _cleanup()
            headers = _auth_header(client)
            start = client.post("/library/scan", headers=headers)
            assert start.status_code == 202, start.text
            polls = 0
            while True:
                status = client.get("/library/scan", headers=headers)
                assert status.status_code == 200, status.text
                payload = status.json()
                # Reads must keep working while the scan writes: no 5xx, no
                # "database is locked" leaking out of the API.
                assets = client.get("/assets?limit=5", headers=headers)
                assert assets.status_code == 200, assets.text
                polls += 1
                if not payload["running"]:
                    break
                assert time.monotonic() - started < DEADLINE_SECONDS
                time.sleep(0.05)

        assert payload["registered"] == SCAN_FILES
        assert payload["known"] == 0
        assert payload["failed"] == 0
        assert payload["errors"] == []
        assert payload["registered"] + payload["known"] + payload["failed"] == SCAN_FILES

        with Session(engine) as session:
            stored = session.exec(
                select(Asset.id).where(Asset.storage_path.like(f"{ROOT_DIR_PREFIX}-%"))
            ).all()
            folders = [folder.name for folder in session.exec(select(Folder)).all()]
        assert len(stored) == SCAN_FILES
        scanned_folders = [name for name in folders if name.startswith(ROOT_DIR_PREFIX)]
        assert len(scanned_folders) == expected_folders == len(set(scanned_folders))
        assert polls >= 1
    finally:
        _cleanup()
