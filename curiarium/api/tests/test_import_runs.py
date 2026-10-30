"""Tests for durable mounted-import run history (Mf-7fvj).

The suite shares one database for the whole session, so an autouse fixture
snapshots the ``import_run`` ids each test starts with and deletes the rows the
test created. The mount fixture does the same for the asset and folder rows a
real run registers.
"""

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import import_runs
import library_scan
import main
import mount_import
from db import engine
from migrations import run_migrations
from models import Asset, Folder, ImportRun, User, UserSession
from routers.import_runs import run_to_detail, run_to_summary

VIEWER_USERNAME = "history-viewer"
VIEWER_PASSWORD = "history-viewer-password-1"
BREAK_GLASS = {"username": "admin", "password": "super-secret"}


@pytest.fixture(scope="module", autouse=True)
def _schema() -> None:
    run_migrations(engine)


@pytest.fixture(autouse=True)
def clean_import_runs():
    """Delete every run row this test created; the table is shared."""
    with Session(engine) as session:
        before = {run.id for run in session.exec(select(ImportRun))}
    yield
    with Session(engine) as session:
        for run in list(session.exec(select(ImportRun))):
            if run.id not in before:
                session.delete(run)
        session.commit()


def _write(root: Path, rel_path: str, payload: bytes = b"solid x\n") -> Path:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _run_rows() -> list[ImportRun]:
    with Session(engine) as session:
        return list(session.exec(select(ImportRun).order_by(ImportRun.started_at, ImportRun.id)))


def _run_ids() -> set[str]:
    return {run.id for run in _run_rows()}


@pytest.fixture
def mount_and_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A temp mount and storage root, with the asset/folder rows a run creates removed."""
    mount = tmp_path / "mount"
    storage = tmp_path / "storage"
    mount.mkdir()
    storage.mkdir()
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_PATH", str(mount))
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_EXTS_RAW", "")
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_INCLUDE_HIDDEN", False)
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_COPY", True)
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_ENABLED", True)
    monkeypatch.setattr(mount_import, "get_mount_import_copy", lambda default: default)
    monkeypatch.setattr(library_scan, "STORAGE", storage)

    with Session(engine) as session:
        asset_ids_before = {asset.id for asset in session.exec(select(Asset))}
        folder_ids_before = {folder.id for folder in session.exec(select(Folder))}
    yield mount, storage
    with Session(engine) as session:
        for asset in list(session.exec(select(Asset))):
            if asset.id not in asset_ids_before:
                session.delete(asset)
        for folder in list(session.exec(select(Folder))):
            if folder.id not in folder_ids_before:
                session.delete(folder)
        session.commit()


@pytest.fixture
def client():
    with TestClient(main.app) as test_client:
        yield test_client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def auth_header(client: TestClient) -> dict[str, str]:
    token = login(client, **BREAK_GLASS)["token"]
    return bearer(token)


@pytest.fixture
def viewer_token(client: TestClient):
    """A real viewer account, removed with its sessions afterwards."""
    glass = login(client, **BREAK_GLASS)
    with Session(engine) as session:
        user_ids_before = {user.id for user in session.exec(select(User))}
        session_ids_before = {row.id for row in session.exec(select(UserSession))}
    created = client.post(
        "/users",
        json={"username": VIEWER_USERNAME, "password": VIEWER_PASSWORD, "role": "viewer"},
        headers=bearer(glass["token"]),
    )
    assert created.status_code == 201, created.text
    token = login(client, VIEWER_USERNAME, VIEWER_PASSWORD)["token"]
    yield token
    with Session(engine) as session:
        for row in list(session.exec(select(UserSession))):
            if row.id not in session_ids_before:
                session.delete(row)
        for user in list(session.exec(select(User))):
            if user.id not in user_ids_before:
                session.delete(user)
        session.commit()


def test_run_list_is_empty_by_default(client: TestClient) -> None:
    response = client.get("/imports/runs", headers=auth_header(client))

    assert response.status_code == 200, response.text
    assert response.json() == {"runs": [], "total": 0, "limit": 20, "offset": 0}


def test_real_run_persists_counters_and_errors(mount_and_storage) -> None:
    mount, _storage = mount_and_storage
    _write(mount, "a/part.stl")
    _write(mount, "a/part.step", b"step a\n")
    before = _run_ids()

    state = mount_import.scan_mount_imports()

    assert state is not None
    assert state.registered == 1
    assert state.failed == 1
    assert len(state.errors) == 1
    created = [run for run in _run_rows() if run.id not in before]
    assert len(created) == 1
    row = created[0]
    assert row.status == "succeeded"
    assert row.mode == "copy"
    assert row.root == str(mount.resolve())
    assert row.started_at == state.started_at
    assert row.finished_at is not None
    assert row.registered == state.registered
    assert row.known == state.known
    assert row.ignored == state.ignored
    assert row.failed == state.failed
    assert row.rejected == 0
    assert json.loads(row.errors_json) == state.errors


def test_live_overlay_wins_while_a_run_is_running() -> None:
    run_id = import_runs.begin_run("/mnt/live", "copy", time.time())
    state = library_scan.ScanState(
        started_at=time.time(),
        registered=1,
        known=2,
        ignored=3,
        failed=4,
        errors=["live error"],
    )
    import_runs.set_active(run_id, state)
    try:
        row = import_runs.get_run(run_id)
        assert row is not None
        active = import_runs.active_state(run_id)
        summary = run_to_summary(row, active)
        assert summary.registered == 1
        assert summary.known == 2
        assert summary.ignored == 3
        assert summary.failed == 4
        assert summary.discovered == 10
        assert summary.skipped == 5
        assert run_to_detail(row, active).errors == ["live error"]
    finally:
        import_runs.clear_active(run_id)

    row = import_runs.get_run(run_id)
    assert row is not None
    assert import_runs.active_state(run_id) is None
    summary = run_to_summary(row, None)
    assert summary.registered == 0
    assert summary.discovered == 0
    assert run_to_detail(row, None).errors == []


def test_unknown_run_detail_is_404(client: TestClient) -> None:
    response = client.get("/imports/runs/does-not-exist", headers=auth_header(client))

    assert response.status_code == 404
    assert response.json()["detail"] == "Import run not found"


def test_history_is_readable_by_a_viewer_and_refused_anonymously(
    client: TestClient, viewer_token: str
) -> None:
    run_id = import_runs.skip_run("/mnt/viewer", "copy", "viewer test")

    listing = client.get("/imports/runs", headers=bearer(viewer_token))
    assert listing.status_code == 200, listing.text
    assert any(run["id"] == run_id for run in listing.json()["runs"])

    detail = client.get(f"/imports/runs/{run_id}", headers=bearer(viewer_token))
    assert detail.status_code == 200, detail.text
    assert detail.json()["id"] == run_id

    anonymous = client.get("/imports/runs")
    assert anonymous.status_code == 401


def test_mark_interrupted_turns_stale_running_rows() -> None:
    run_id = import_runs.begin_run("/mnt/stale", "copy", time.time())
    assert import_runs.get_run(run_id).status == "running"

    import_runs.mark_interrupted()

    row = import_runs.get_run(run_id)
    assert row is not None
    assert row.status == "interrupted"
    assert row.finished_at is not None


def test_skip_paths_are_recorded_with_reasons(mount_and_storage, monkeypatch: pytest.MonkeyPatch) -> None:
    mount, storage = mount_and_storage
    before = _run_ids()

    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_PATH", str(mount / "missing"))
    assert mount_import.scan_mount_imports() is None

    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_PATH", str(storage))
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_COPY", False)
    assert mount_import.scan_mount_imports() is None

    # storage.parent also contains the storage root, so this is the other
    # overlap branch (`_overlap_kind` reports it as "is inside").
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_PATH", str(storage.parent))
    assert mount_import.scan_mount_imports() is None

    created = [run for run in _run_rows() if run.id not in before]
    assert len(created) == 3
    by_reason = {run.reason: run for run in created}
    assert all(run.status == "skipped" for run in created)
    missing = next(run for reason, run in by_reason.items() if reason and "mount path not found" in reason)
    same_root = by_reason["reference mode needs a source outside the storage root"]
    inside_reason = next(reason for reason in by_reason if reason and "is inside the storage root" in reason)
    assert missing.mode is None
    assert same_root.mode == "reference"
    assert by_reason[inside_reason].mode == "reference"
    assert all(run.started_at == run.finished_at for run in created)


def test_no_mount_path_writes_nothing(mount_and_storage, monkeypatch: pytest.MonkeyPatch) -> None:
    before = _run_ids()
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_PATH", "")

    assert mount_import.scan_mount_imports() is None

    assert _run_ids() == before


def test_aborted_run_is_failed_with_reason(mount_and_storage, monkeypatch: pytest.MonkeyPatch) -> None:
    mount, _storage = mount_and_storage
    _write(mount, "part.stl")
    before = _run_ids()

    def explode(plan, state=None):
        raise RuntimeError("walk exploded")

    monkeypatch.setattr(mount_import, "register_tree", explode)
    assert mount_import.scan_mount_imports() is None

    created = [run for run in _run_rows() if run.id not in before]
    assert len(created) == 1
    row = created[0]
    assert row.status == "failed"
    assert row.reason == "walk exploded"
    assert row.finished_at is not None
    assert import_runs.active_state(row.id) is None


def test_retention_keeps_the_newest_fifty() -> None:
    with Session(engine) as session:
        for index in range(55):
            session.add(ImportRun(id=f"seed-{index:02d}", status="succeeded", started_at=float(index)))
        session.commit()

    run_id = import_runs.begin_run("/mnt/newest", "copy", 1000.0)

    rows, total = import_runs.list_runs(limit=200, offset=0)
    assert total == 50
    assert len(rows) == 50
    assert rows[0].id == run_id
    assert rows[-1].started_at == 6.0


def test_skip_retention_keeps_the_newest_fifty() -> None:
    """A mount that skips on every boot must not grow the table past KEEP."""
    with Session(engine) as session:
        for index in range(55):
            session.add(ImportRun(id=f"seed-{index:02d}", status="succeeded", started_at=float(index)))
        session.commit()

    run_id = import_runs.skip_run("/mnt/missing", None, "mount path not found")

    rows, total = import_runs.list_runs(limit=200, offset=0)
    assert total == 50
    assert len(rows) == 50
    assert rows[0].id == run_id
    assert rows[0].status == "skipped"
    # Keep the newest 50 of 56: the skip row plus seed-06..seed-54.
    assert rows[-1].id == "seed-06"
    assert rows[-1].started_at == 6.0
    kept = {row.id for row in rows}
    assert {"seed-00", "seed-01", "seed-02", "seed-03", "seed-04", "seed-05"}.isdisjoint(kept)
