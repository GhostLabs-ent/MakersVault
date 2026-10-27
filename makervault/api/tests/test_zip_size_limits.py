"""Zip extraction is capped per entry and cumulatively (Mf-g4ug).

``IMPORT_MAX_BYTES`` only bounded one entry: an archive of many small entries
could still fill the disk, and ``ZipInfo.file_size`` was never inspected before
decompression started. Two gates now exist in
``zip_service.extract_zip_entries_to_assets``:

* a preflight over the deduped selection sums the declared sizes and rejects the
  whole request with 413 before any folder or asset is written, and
* a running total of the bytes actually streamed catches an archive that lies
  about its declared sizes, cleaning up everything the request created.

Both gates are covered here, plus the fact that only the selected subset counts
against the budget. Storage and the database are shared for the whole session,
so every test works in a temporary storage root and removes what it created.
"""

import copy
from pathlib import Path
from typing import List, Optional
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

import asset_service
import db
import library_scan
import schemas
import settings_service
import zip_service
from db import engine
from migrations import run_migrations
from models import Asset, Folder

# --- infrastructure ---------------------------------------------------------


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


def make_zip(path: Path, entries: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", ZIP_DEFLATED) as zf:
        for name, payload in entries.items():
            zf.writestr(name, payload)
    return path


def payload(size: int) -> bytes:
    """Distinct bytes per size, so an extracted file is identifiable."""
    return bytes(range(32, 32 + size))


def extract_request(entries: List[str], folder_id: Optional[str] = None) -> schemas.ImportZipExtractRequest:
    return schemas.ImportZipExtractRequest(url="upload://archive.zip", entries=entries, folder_id=folder_id)


def asset_ids() -> set[str]:
    with Session(engine) as session:
        return {asset.id for asset in session.exec(select(Asset))}


def folder_ids() -> set[str]:
    with Session(engine) as session:
        return {folder.id for folder in session.exec(select(Folder))}


def files_under(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}


class ShrunkSizeZipFile:
    """A ZipFile whose infolist() understates file_size but serves the real bytes."""

    def __init__(self, path: Path) -> None:
        self._zip = ZipFile(path)
        self._real_infos: dict[int, ZipInfo] = {}

    def __enter__(self) -> "ShrunkSizeZipFile":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._zip.close()

    def infolist(self) -> List[ZipInfo]:
        declared: List[ZipInfo] = []
        for info in self._zip.infolist():
            shrunken = copy.copy(info)
            shrunken.file_size = 1
            self._real_infos[id(shrunken)] = info
            declared.append(shrunken)
        return declared

    def open(self, info: ZipInfo) -> object:
        return self._zip.open(self._real_infos[id(info)])


# --- cumulative preflight ---------------------------------------------------


def test_cumulative_preflight_rejects_before_any_write(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = isolated_storage
    monkeypatch.setattr(zip_service, "IMPORT_MAX_BYTES", 100)
    monkeypatch.setattr(zip_service, "IMPORT_ZIP_MAX_BYTES", 15)
    archive = make_zip(storage.parent / "archive.zip", {"a.stl": payload(10), "b.stl": payload(10)})
    assets_before, folders_before, files_before = asset_ids(), folder_ids(), files_under(storage)

    with pytest.raises(HTTPException) as raised:
        zip_service.extract_zip_entries_to_assets(archive, ["a.stl", "b.stl"], extract_request(["a.stl", "b.stl"]))

    assert raised.value.status_code == 413
    assert "20 bytes" in raised.value.detail
    assert "IMPORT_ZIP_MAX_MB" in raised.value.detail
    assert asset_ids() == assets_before
    assert folder_ids() == folders_before
    assert files_under(storage) == files_before


def test_selected_subset_is_the_only_part_counted(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = isolated_storage
    monkeypatch.setattr(zip_service, "IMPORT_MAX_BYTES", 100)
    monkeypatch.setattr(zip_service, "IMPORT_ZIP_MAX_BYTES", 25)
    archive = make_zip(
        storage.parent / "archive.zip",
        {"a.stl": payload(10), "b.stl": payload(10), "c.stl": payload(10)},
    )

    assets, failed = zip_service.extract_zip_entries_to_assets(archive, ["a.stl", "b.stl"], extract_request(["a.stl", "b.stl"]))
    assert sorted(asset.filename for asset in assets) == ["a.stl", "b.stl"]
    assert failed == []
    created = asset_ids()

    with pytest.raises(HTTPException) as raised:
        zip_service.extract_zip_entries_to_assets(archive, ["a.stl", "b.stl", "c.stl"], extract_request(["a.stl", "b.stl", "c.stl"]))

    assert raised.value.status_code == 413
    assert asset_ids() == created


# --- per-entry declared size ------------------------------------------------


def test_declared_per_entry_oversize_is_one_failed_entry(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = isolated_storage
    monkeypatch.setattr(zip_service, "IMPORT_MAX_BYTES", 10)
    # Room for small.stl alone, but not for small.stl plus the oversized entry:
    # a regression that counts big.stl toward the cumulative total fails here.
    monkeypatch.setattr(zip_service, "IMPORT_ZIP_MAX_BYTES", 15)
    archive = make_zip(
        storage.parent / "archive.zip",
        {"big.stl": payload(20), "small.stl": payload(5)},
    )
    assets_before = asset_ids()

    assets, failed = zip_service.extract_zip_entries_to_assets(
        archive, ["big.stl", "small.stl"], extract_request(["big.stl", "small.stl"])
    )

    assert [asset.filename for asset in assets] == ["small.stl"]
    assert failed == ["big.stl"]
    new_ids = asset_ids() - assets_before
    assert len(new_ids) == 1
    with Session(engine) as session:
        rows = [session.get(Asset, asset_id) for asset_id in new_ids]
    assert sorted(row.filename for row in rows if row is not None) == ["small.stl"]


# --- declared-vs-actual mismatch -------------------------------------------


def test_understated_declared_size_aborts_and_cleans_up(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = isolated_storage
    monkeypatch.setattr(zip_service, "IMPORT_MAX_BYTES", 100)
    monkeypatch.setattr(zip_service, "IMPORT_ZIP_MAX_BYTES", 15)
    archive = make_zip(
        storage.parent / "archive.zip",
        {"a.stl": payload(10), "b.stl": payload(10)},
    )
    monkeypatch.setattr(zip_service, "ZipFile", ShrunkSizeZipFile)
    assets_before, files_before = asset_ids(), files_under(storage)

    with pytest.raises(HTTPException) as raised:
        zip_service.extract_zip_entries_to_assets(archive, ["a.stl", "b.stl"], extract_request(["a.stl", "b.stl"]))

    assert raised.value.status_code == 413
    assert "IMPORT_ZIP_MAX_MB" in raised.value.detail
    assert asset_ids() == assets_before
    assert files_under(storage) == files_before
