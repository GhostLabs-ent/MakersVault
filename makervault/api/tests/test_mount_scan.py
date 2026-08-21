import time
import threading
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

import main
import mount_import
from asset_service import cleanup_asset, managed_asset_path
from db import engine
from main import app
from migrations import run_migrations
from models import Asset, MountScan
from settings_service import set_mount_import_copy


def auth_headers(client: TestClient) -> dict[str, str]:
    login = client.post(
        "/login",
        json={"username": "admin", "password": "test-only-password"},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def asset_for_source(source: Path) -> Asset | None:
    with Session(engine) as session:
        return session.exec(
            select(Asset).where(Asset.source_path == source.resolve().as_posix())
        ).first()


def cleanup_sources(root: Path) -> None:
    prefix = f"{root.resolve().as_posix().rstrip('/')}/%"
    with Session(engine) as session:
        asset_ids = list(
            session.exec(select(Asset.id).where(Asset.source_path.like(prefix))).all()
        )
        scans = list(
            session.exec(select(MountScan).where(MountScan.root_path == str(root))).all()
        )
        for scan in scans:
            session.delete(scan)
        session.commit()
    for asset_id in asset_ids:
        cleanup_asset(asset_id)


def wait_for_scan(client: TestClient, headers: dict[str, str], scan_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get("/settings/mount-import/scan", headers=headers)
        assert response.status_code == 200
        scan = response.json()
        if scan and scan["id"] == scan_id and scan["status"] != "running":
            return scan
        time.sleep(0.02)
    raise AssertionError("mounted import scan did not finish")


def test_copy_scan_is_repeatable_and_managed_copy_survives_source_removal(tmp_path: Path) -> None:
    run_migrations(engine)
    root = tmp_path / "copy-mount"
    root.mkdir()
    first = root / "first.stl"
    second = root / "second.stl"
    first.write_bytes(b"solid first")
    second.write_bytes(b"solid second")
    (root / "ignored.txt").write_text("not eligible")

    try:
        initial = mount_import.scan_mount_imports(str(root), copy_files=True)
        assert (initial.imported, initial.skipped, initial.failed) == (2, 0, 0)

        assets = [asset_for_source(first), asset_for_source(second)]
        assert all(asset is not None for asset in assets)
        managed = [managed_asset_path(asset) for asset in assets if asset]
        assert all(path.exists() for path in managed)

        repeated = mount_import.scan_mount_imports(str(root), copy_files=True)
        assert (repeated.imported, repeated.skipped, repeated.failed) == (0, 2, 0)

        first.unlink()
        second.unlink()
        assert all(path.exists() for path in managed)
    finally:
        cleanup_sources(root)


def test_failures_are_bounded_and_do_not_abort_later_files(tmp_path: Path, monkeypatch) -> None:
    run_migrations(engine)
    root = tmp_path / "failure-mount"
    root.mkdir()
    good = root / "zz-good.stl"
    good.write_bytes(b"solid good")
    bad_names = []
    for index in range(55):
        name = f"bad-{index:02d}.stl"
        (root / name).write_bytes(b"bad")
        bad_names.append(name)

    real_resolve = mount_import.resolve_safe_mount_file

    def reject_bad(scan_root: Path, candidate: Path) -> Path:
        if candidate.name.startswith("bad-"):
            raise ValueError("fixture rejected")
        return real_resolve(scan_root, candidate)

    monkeypatch.setattr(mount_import, "resolve_safe_mount_file", reject_bad)
    try:
        result = mount_import.scan_mount_imports(str(root), copy_files=False)
        assert (result.imported, result.skipped, result.failed) == (1, 0, 55)
        assert len(result.failure_details) == 50
        assert result.failure_details_omitted == 5
        assert all(not detail["path"].startswith("/") for detail in result.failure_details)
        assert asset_for_source(good) is not None
    finally:
        cleanup_sources(root)


def test_unreadable_directory_does_not_abort_later_files(tmp_path: Path, monkeypatch) -> None:
    run_migrations(engine)
    root = tmp_path / "walk-error-mount"
    root.mkdir()
    good = root / "after-error.stl"
    good.write_bytes(b"solid after error")

    def walk_with_error(scan_root: Path, onerror=None):
        assert onerror is not None
        onerror(PermissionError(13, "Permission denied", str(root / "blocked")))
        yield str(scan_root), [], [good.name]

    monkeypatch.setattr(mount_import.os, "walk", walk_with_error)
    try:
        result = mount_import.scan_mount_imports(str(root), copy_files=False)
        assert (result.imported, result.failed) == (1, 1)
        assert result.failure_details[0]["path"] == "blocked"
        assert str(root) not in result.failure_details[0]["reason"]
        assert asset_for_source(good) is not None
    finally:
        cleanup_sources(root)


def test_manual_scan_api_persists_mode_counts_and_no_copy_ownership(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "index-mount"
    root.mkdir()
    source = root / "indexed.stl"
    source.write_bytes(b"solid indexed")

    with TestClient(app) as client:
        headers = auth_headers(client)
        monkeypatch.setattr(mount_import, "MOUNT_IMPORT_PATH", str(root))
        monkeypatch.setattr(main, "MOUNT_IMPORT_PATH", str(root))
        set_mount_import_copy(False)
        try:
            started = client.post("/settings/mount-import/rescan", headers=headers)
            assert started.status_code == 200
            assert started.json()["started"] is True
            scan = wait_for_scan(client, headers, started.json()["scan"]["id"])
            assert scan["status"] == "completed"
            assert scan["mode"] == "index_in_place"
            assert (scan["imported"], scan["skipped"], scan["failed"]) == (1, 0, 0)

            settings = client.get("/settings/mount-import", headers=headers).json()
            assert settings["last_scan"]["id"] == scan["id"]

            repeated = client.post("/settings/mount-import/rescan", headers=headers).json()
            repeated_scan = wait_for_scan(client, headers, repeated["scan"]["id"])
            assert (repeated_scan["imported"], repeated_scan["skipped"]) == (0, 1)

            asset = asset_for_source(source)
            assert asset is not None
            assert not managed_asset_path(asset).exists()
            deleted = client.delete(f"/asset/{asset.id}", headers=headers)
            assert deleted.status_code == 200
            assert source.exists()
        finally:
            set_mount_import_copy(True)
            cleanup_sources(root)


def test_manual_scan_exposes_relative_failure_details(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "visible-failure-mount"
    root.mkdir()
    source = root / "good.stl"
    source.write_bytes(b"solid good")
    link = root / "rejected.stl"
    link.symlink_to(source)

    with TestClient(app) as client:
        headers = auth_headers(client)
        monkeypatch.setattr(mount_import, "MOUNT_IMPORT_PATH", str(root))
        monkeypatch.setattr(main, "MOUNT_IMPORT_PATH", str(root))
        set_mount_import_copy(False)
        try:
            response = client.post("/settings/mount-import/rescan", headers=headers)
            assert response.status_code == 200
            scan = wait_for_scan(client, headers, response.json()["scan"]["id"])
            assert scan["status"] == "completed_with_failures"
            assert (scan["imported"], scan["failed"]) == (1, 1)
            assert scan["failure_details"] == [
                {"path": "rejected.stl", "reason": "Mounted source contains a symbolic link"}
            ]
            assert scan["failure_details_omitted"] == 0
        finally:
            set_mount_import_copy(True)
            cleanup_sources(root)


def test_scan_coordinator_returns_active_scan_instead_of_overlapping(tmp_path: Path, monkeypatch) -> None:
    run_migrations(engine)
    root = tmp_path / "coordinated-mount"
    root.mkdir()
    entered = threading.Event()
    release = threading.Event()

    def blocking_scan(*_args, **_kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return mount_import.MountScanResult()

    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_PATH", str(root))
    monkeypatch.setattr(mount_import, "scan_mount_imports", blocking_scan)
    first, first_started = mount_import.start_mount_scan("manual")
    assert first_started is True
    assert entered.wait(timeout=5)
    second, second_started = mount_import.start_mount_scan("manual")
    assert second_started is False
    assert second.id == first.id
    release.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        finished = mount_import.get_mount_scan(first.id)
        if finished and finished.status != "running":
            break
        time.sleep(0.02)
    else:
        raise AssertionError("coordinated scan did not finish")
    try:
        assert finished.status == "completed"
    finally:
        with Session(engine) as session:
            persisted = session.get(MountScan, first.id)
            if persisted:
                session.delete(persisted)
                session.commit()


def test_unavailable_root_persists_failed_scan(tmp_path: Path, monkeypatch) -> None:
    run_migrations(engine)
    missing = tmp_path / "missing-mount"
    monkeypatch.setattr(mount_import, "MOUNT_IMPORT_PATH", str(missing))
    scan, started = mount_import.start_mount_scan("manual")
    assert started is True
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        finished = mount_import.get_mount_scan(scan.id)
        if finished and finished.status != "running":
            break
        time.sleep(0.02)
    else:
        raise AssertionError("unavailable-root scan did not finish")
    try:
        assert finished.status == "failed"
        assert finished.failed == 1
        assert "unavailable" in finished.failure_details_json
    finally:
        with Session(engine) as session:
            persisted = session.get(MountScan, scan.id)
            if persisted:
                session.delete(persisted)
                session.commit()


def test_recovery_marks_abandoned_scan_interrupted() -> None:
    run_migrations(engine)
    row = MountScan(
        trigger="startup",
        status="running",
        mode="copy",
        root_path="/fixture/interrupted",
        started_at="2026-08-21T00:00:00Z",
    )
    with Session(engine) as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        scan_id = row.id
    try:
        assert mount_import.recover_interrupted_mount_scans() >= 1
        recovered = mount_import.get_mount_scan(scan_id)
        assert recovered is not None
        assert recovered.status == "interrupted"
        assert recovered.finished_at is not None
        assert "API restart" in recovered.failure_details_json
    finally:
        with Session(engine) as session:
            persisted = session.get(MountScan, scan_id)
            if persisted:
                session.delete(persisted)
                session.commit()
