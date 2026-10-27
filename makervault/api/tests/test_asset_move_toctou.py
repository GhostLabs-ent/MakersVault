"""Two moves onto one target in one directory must not clobber (Mf-2bvy).

``move_managed_file`` used to check ``new_path.exists()`` and then rename: two
concurrent moves of different assets onto the same basename in the same folder
could both pass the check, and the second ``rename`` silently destroyed the
first asset's already-committed bytes. The move is now arbitered by
``os.link``, which refuses an existing destination atomically; these tests pin
that invariant on the disk, on the fallback path and through the API.

Every test works in a temporary storage root and removes its own rows: the
database is shared for the whole session.
"""

import errno
import os
import threading
from functools import partial
from pathlib import Path
from typing import Callable, List, Optional

import pytest
from fastapi import HTTPException
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


def insert_asset_row(name: str, folder_id: Optional[str], storage_path: Optional[str], *, filename: str) -> str:
    asset = Asset(filename=filename, mime="model/stl", size=10, name=name, folder_id=folder_id, storage_path=storage_path)
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


def write_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


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


# --- the move is no-clobber ------------------------------------------------


def test_concurrent_moves_to_one_target_in_one_directory_never_clobber(
    isolated_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC1: one winner, one 409, no lost bytes when two moves share a target.

    Two gates force the interleaving deterministically for the old code as well
    as the new. The target's ``exists()`` gate reads first and only then holds
    both threads at a barrier, so both have seen the target absent before either
    acts - exactly the window the old check-then-act lost. The ``os.link`` gate
    then holds both threads after they enter the atomic operation, so the new
    code's outcome is order-independent. The assertions are order-independent
    too.
    """
    storage = isolated_storage
    one = storage / "Boxes" / "one.stl"
    two = storage / "Boxes" / "two.stl"
    target = storage / "Boxes" / "target.stl"
    write_file(one, b"one bytes")
    write_file(two, b"two bytes")

    barrier = threading.Barrier(2)
    real_exists = Path.exists
    real_link = os.link

    def gated_exists(self) -> bool:
        if self == target:
            # Read first, then rendezvous: both threads must have seen the target
            # absent before either acts, which is exactly the window the old
            # check-then-act lost.
            absent = real_exists(self)
            barrier.wait()
            return absent
        return real_exists(self)

    def gated_link(src, dst, *args, **kwargs):
        if Path(dst) == target:
            barrier.wait()
        return real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", gated_exists)
    monkeypatch.setattr(os, "link", gated_link)

    outcomes = run_concurrently(
        [
            partial(asset_service.move_managed_file, one, target),
            partial(asset_service.move_managed_file, two, target),
        ]
    )

    unexpected = [outcome for outcome in outcomes if outcome is not True and not isinstance(outcome, HTTPException)]
    assert unexpected == [], unexpected
    winners = [outcome for outcome in outcomes if outcome is True]
    conflicts = [outcome for outcome in outcomes if isinstance(outcome, HTTPException)]
    assert len(winners) == 1
    assert len(conflicts) == 1
    assert conflicts[0].status_code == 409
    assert conflicts[0].detail == "Storage path already exists: Boxes/target.stl"

    payloads = {one: b"one bytes", two: b"two bytes"}
    survivors = [path for path in (one, two) if path.exists()]
    assert len(survivors) == 1
    loser = survivors[0]
    winner = next(path for path in (one, two) if path != loser)
    assert not winner.exists()
    assert target.read_bytes() == payloads[winner]
    assert loser.read_bytes() == payloads[loser]
    assert sorted(path.name for path in target.parent.iterdir()) == sorted(["target.stl", loser.name])


def test_move_never_overwrites_a_committed_file(isolated_storage: Path) -> None:
    """AC1 sequential guard: an occupied target is a 409 and its bytes survive."""
    storage = isolated_storage
    old = storage / "Boxes" / "one.stl"
    target = storage / "Boxes" / "target.stl"
    write_file(old, b"old bytes")
    write_file(target, b"committed bytes")

    with pytest.raises(HTTPException) as error:
        asset_service.move_managed_file(old, target)

    assert error.value.status_code == 409
    assert error.value.detail == "Storage path already exists: Boxes/target.stl"
    assert target.read_bytes() == b"committed bytes"
    assert old.read_bytes() == b"old bytes"


def test_link_unsupported_falls_back_to_locked_rename(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC2: a filesystem without hardlinks still yields one winner and one 409."""

    def unsupported_link(src, dst, *args, **kwargs):
        raise OSError(errno.EOPNOTSUPP, "hardlinks unsupported")

    monkeypatch.setattr(os, "link", unsupported_link)
    storage = isolated_storage
    one = storage / "Boxes" / "one.stl"
    two = storage / "Boxes" / "two.stl"
    target = storage / "Boxes" / "target.stl"
    write_file(one, b"one bytes")
    write_file(two, b"two bytes")

    outcomes = run_concurrently(
        [
            partial(asset_service.move_managed_file, one, target),
            partial(asset_service.move_managed_file, two, target),
        ]
    )

    unexpected = [outcome for outcome in outcomes if outcome is not True and not isinstance(outcome, HTTPException)]
    assert unexpected == [], unexpected
    winners = [outcome for outcome in outcomes if outcome is True]
    conflicts = [outcome for outcome in outcomes if isinstance(outcome, HTTPException)]
    assert len(winners) == 1
    assert len(conflicts) == 1
    assert conflicts[0].status_code == 409
    assert conflicts[0].detail == "Storage path already exists: Boxes/target.stl"

    payloads = {one: b"one bytes", two: b"two bytes"}
    survivors = [path for path in (one, two) if path.exists()]
    assert len(survivors) == 1
    loser = survivors[0]
    winner = next(path for path in (one, two) if path != loser)
    assert not winner.exists()
    assert target.read_bytes() == payloads[winner]
    assert loser.read_bytes() == payloads[loser]


# --- the API keeps every row pointing at its own bytes ----------------------


def test_concurrent_api_renames_in_one_folder_yield_one_200_one_409(isolated_storage: Path) -> None:
    """AC3: through ``POST /asset/{id}/rename`` no row is left pointing at a missing file."""
    storage = isolated_storage
    payloads = {
        insert_asset_row("alpha", None, "Boxes/alpha.stl", filename="alpha.stl"): b"alpha bytes",
        insert_asset_row("beta", None, "Boxes/beta.stl", filename="beta.stl"): b"beta bytes",
    }
    before = {}
    for asset_id, payload in payloads.items():
        asset = read_asset(asset_id)
        assert asset is not None
        before[asset_id] = asset
        write_file(storage / asset.storage_path, payload)

    # The lifespan (migrations included) runs once, in the main thread only.
    with TestClient(app, raise_server_exceptions=False) as bootstrap:
        headers = auth_header(bootstrap)

    def rename(asset_id: str) -> tuple[str, int]:
        thread_client = TestClient(app, raise_server_exceptions=False)
        response = thread_client.post(f"/asset/{asset_id}/rename", json={"filename": "gamma.stl"}, headers=headers)
        return asset_id, response.status_code

    outcomes = run_concurrently([partial(rename, asset_id) for asset_id in payloads])

    unexpected = [outcome for outcome in outcomes if not isinstance(outcome, tuple)]
    assert unexpected == [], unexpected
    statuses = dict(outcomes)
    assert sorted(statuses.values()) == [200, 409]
    winner_id = next(asset_id for asset_id, status in statuses.items() if status == 200)
    loser_id = next(asset_id for asset_id, status in statuses.items() if status == 409)

    for asset_id in payloads:
        asset = read_asset(asset_id)
        assert asset is not None
        stored = storage / asset.storage_path
        assert stored.is_file(), f"asset {asset_id} points at a missing file"
        assert stored.read_bytes() == payloads[asset_id]

    winner = read_asset(winner_id)
    loser = read_asset(loser_id)
    assert winner is not None
    assert loser is not None
    assert winner.name == "gamma"
    assert winner.storage_path == f"{Path(before[winner_id].storage_path).parent.as_posix()}/gamma.stl"
    assert (loser.name, loser.filename, loser.storage_path) == (
        before[loser_id].name,
        before[loser_id].filename,
        before[loser_id].storage_path,
    )
