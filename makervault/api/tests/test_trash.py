from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from db import STORAGE, engine
from main import app
from migrations import run_migrations
from models import ArtifactRevision, Asset, TrashPurgeOperation
from revision_service import revision_timestamp
from settings_service import set_trash_retention
import trash_service


def _headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/login",
        json={"username": "admin", "password": "test-only-password"},
    )
    assert response.status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": response.json()["csrf_token"]}


def _upload(
    client: TestClient,
    headers: dict[str, str],
    name: str,
    data: bytes = b"solid trash fixture",
    folder_id: str | None = None,
) -> dict:
    form = {"folder_id": folder_id} if folder_id else {}
    response = client.post(
        "/upload",
        headers=headers,
        data=form,
        files={"file": (name, data, "model/stl")},
    )
    assert response.status_code == 200
    return response.json()


def _permanent(client: TestClient, headers: dict[str, str], *asset_ids: str):
    return client.post(
        "/trash/permanent",
        headers=headers,
        json={
            "asset_ids": list(asset_ids),
            "confirmation": "PERMANENTLY DELETE",
        },
    )


@pytest.fixture(autouse=True)
def safe_retention_policy():
    run_migrations(engine)
    set_trash_retention("never")
    yield
    set_trash_retention("never")


def test_delete_is_metadata_only_hidden_and_restorable() -> None:
    with TestClient(app) as client:
        headers = _headers(client)
        asset = _upload(client, headers, "recoverable.stl")
        client.post(f"/asset/{asset['id']}/tags", headers=headers, json={"tags": ["trash-only-tag"]})
        with Session(engine) as session:
            row = session.get(Asset, asset["id"])
            path = (STORAGE / row.storage_path).resolve()
        deleted = client.delete(f"/asset/{asset['id']}", headers=headers)
        assert deleted.status_code == 200
        assert deleted.json()["trashed"] is True
        assert path.is_file()
        assert all(row["id"] != asset["id"] for row in client.get("/assets", headers=headers).json())
        assert client.get(asset["url"], headers=headers).status_code == 404
        assert client.get(f"/asset/{asset['id']}/revisions", headers=headers).status_code == 404
        assert "trash-only-tag" not in client.get("/tags", headers=headers).json()
        assert client.post(
            f"/asset/{asset['id']}/meta", headers=headers, json={"notes": "blocked"}
        ).status_code == 404
        assert client.post(
            f"/asset/{asset['id']}/revisions",
            headers=headers,
            files={"file": ("blocked.stl", b"blocked", "model/stl")},
        ).status_code == 404
        assert client.post(
            f"/asset/{asset['id']}/files",
            headers=headers,
            files={"file": ("blocked.txt", b"blocked", "text/plain")},
        ).status_code == 404
        assert client.post(
            f"/asset/{asset['id']}/handoff",
            headers=headers,
            json={"tool": "slicer"},
        ).status_code == 404

        trash = client.get("/trash", headers=headers).json()
        item = next(row for row in trash if row["id"] == asset["id"])
        assert item["managed_bytes"] == len(b"solid trash fixture")
        assert item["revision_count"] == 1

        restored = client.post(
            f"/trash/{asset['id']}/restore",
            headers=headers,
            json={"restore_unassigned": False},
        )
        assert restored.status_code == 200
        assert client.get(restored.json()["url"], headers=headers).content == b"solid trash fixture"
        client.delete(f"/asset/{asset['id']}", headers=headers)
        assert _permanent(client, headers, asset["id"]).status_code == 200


def test_restore_requires_confirmation_when_original_folder_is_missing() -> None:
    with TestClient(app) as client:
        headers = _headers(client)
        folder = client.post("/folders", headers=headers, json={"name": "Old", "tags": []}).json()
        asset = _upload(client, headers, "foldered.stl", folder_id=folder["id"])
        client.delete(f"/asset/{asset['id']}", headers=headers)
        assert client.delete(f"/folder/{folder['id']}", headers=headers).status_code == 200

        blocked = client.post(
            f"/trash/{asset['id']}/restore",
            headers=headers,
            json={"restore_unassigned": False},
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "original_folder_missing"
        restored = client.post(
            f"/trash/{asset['id']}/restore",
            headers=headers,
            json={"restore_unassigned": True},
        )
        assert restored.status_code == 200
        assert restored.json()["folder_id"] is None
        client.delete(f"/asset/{asset['id']}", headers=headers)
        _permanent(client, headers, asset["id"])


def test_restore_never_overwrites_an_active_name_conflict() -> None:
    with TestClient(app) as client:
        headers = _headers(client)
        original = _upload(client, headers, "same-name.stl", b"old")
        client.delete(f"/asset/{original['id']}", headers=headers)
        replacement = _upload(client, headers, "same-name.stl", b"new")
        blocked = client.post(
            f"/trash/{original['id']}/restore",
            headers=headers,
            json={},
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "name_conflict"
        assert client.get(replacement["url"], headers=headers).content == b"new"
        client.delete(f"/asset/{replacement['id']}", headers=headers)
        _permanent(client, headers, original["id"], replacement["id"])


def test_permanent_delete_requires_confirmation_and_preserves_external_source(tmp_path: Path) -> None:
    source = tmp_path / "external.stl"
    source.write_bytes(b"external bytes")
    asset = Asset(
        name="External Trash",
        filename="external.stl",
        mime="model/stl",
        size=source.stat().st_size,
        source_path=str(source),
        deleted_at=revision_timestamp(),
    )
    revision = ArtifactRevision(
        asset_id=asset.id,
        revision_number=1,
        created_at=revision_timestamp(),
        filename=asset.filename,
        mime=asset.mime,
        size=asset.size,
        source_path=str(source),
        content_state="ready",
    )
    asset.current_revision_id = revision.id
    asset_id = asset.id
    with Session(engine) as session:
        session.add(asset)
        session.add(revision)
        session.commit()

    with TestClient(app) as client:
        headers = _headers(client)
        denied = client.post(
            "/trash/permanent",
            headers=headers,
            json={"asset_ids": [asset_id], "confirmation": "delete"},
        )
        assert denied.status_code == 400
        purged = _permanent(client, headers, asset_id)
        assert purged.status_code == 200
        assert purged.json()[0]["external_source_preserved"] is True
        assert source.read_bytes() == b"external bytes"
        with Session(engine) as session:
            assert session.get(Asset, asset_id) is None


def test_database_failure_restores_quarantined_files(monkeypatch) -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = _headers(client)
        asset = _upload(client, headers, "rollback-trash.stl", b"recover me")
        client.delete(f"/asset/{asset['id']}", headers=headers)
        with Session(engine) as session:
            row = session.get(Asset, asset["id"])
            path = (STORAGE / row.storage_path).resolve()

        def fail_commit(_session):
            raise RuntimeError("simulated database failure")

        monkeypatch.setattr(trash_service, "_commit_purge_session", fail_commit)
        response = _permanent(client, headers, asset["id"])
        assert response.status_code == 500
        assert path.read_bytes() == b"recover me"
        with Session(engine) as session:
            assert session.get(Asset, asset["id"]).deleted_at is not None
            operation = session.exec(
                select(TrashPurgeOperation).order_by(TrashPurgeOperation.created_at.desc())
            ).first()
            assert operation.status == "rolled_back"


def test_cleanup_failure_is_retryable_and_reconciled(monkeypatch) -> None:
    with TestClient(app) as client:
        headers = _headers(client)
        asset = _upload(client, headers, "cleanup-pending.stl", b"purge me")
        client.delete(f"/asset/{asset['id']}", headers=headers)
        original_rmtree = trash_service.shutil.rmtree

        def fail_cleanup(path, *args, **kwargs):
            if trash_service.QUARANTINE_DIR in str(path):
                raise OSError("simulated cleanup failure")
            return original_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(trash_service.shutil, "rmtree", fail_cleanup)
        purged = _permanent(client, headers, asset["id"])
        assert purged.status_code == 200
        with Session(engine) as session:
            operation = session.exec(
                select(TrashPurgeOperation).order_by(TrashPurgeOperation.created_at.desc())
            ).first()
            assert operation.status == "cleanup_pending"
        monkeypatch.setattr(trash_service.shutil, "rmtree", original_rmtree)
        outcome = trash_service.reconcile_trash_operations()
        assert outcome["reconciled"] >= 1
        with Session(engine) as session:
            assert session.get(TrashPurgeOperation, operation.id).status == "completed"


def test_capacity_policy_selects_oldest_complete_artifacts(monkeypatch) -> None:
    ids = []
    with Session(engine) as session:
        for index, deleted_at in enumerate([
            "2026-01-01T00:00:00Z",
            "2026-01-02T00:00:00Z",
            "2026-01-03T00:00:00Z",
        ]):
            asset = Asset(
                name=f"Capacity {index}",
                filename=f"capacity-{index}.stl",
                mime="model/stl",
                size=1,
                deleted_at=deleted_at,
            )
            session.add(asset)
            ids.append(asset.id)
        session.commit()

    calls: list[str] = []
    monkeypatch.setattr(trash_service, "get_trash_retention", lambda: "until_needed")

    def fake_delete(asset_ids, **_kwargs):
        calls.extend(asset_ids)
        return [{"asset_id": asset_ids[0]}]

    monkeypatch.setattr(trash_service, "permanently_delete", fake_delete)
    monkeypatch.setattr(
        trash_service.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=1000, used=900, free=600 if len(calls) >= 2 else 100),
    )
    trash_service.reclaim_for_capacity(STORAGE, incoming_bytes=100, reserve_bytes=400)
    assert calls == ids[:2]

    with Session(engine) as session:
        for asset_id in ids:
            row = session.get(Asset, asset_id)
            if row:
                session.delete(row)
        session.commit()


def test_never_policy_does_not_purge_for_capacity(monkeypatch) -> None:
    monkeypatch.setattr(trash_service, "get_trash_retention", lambda: "never")
    called = False

    def fake_delete(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(trash_service, "permanently_delete", fake_delete)
    assert trash_service.reclaim_for_capacity(STORAGE, 100, 400) == []
    assert called is False


def test_time_retention_choices_select_only_old_enough_trash() -> None:
    now = datetime.now(timezone.utc)
    ages = [2, 8, 31]
    ids = []
    with Session(engine) as session:
        for age in ages:
            asset = Asset(
                name=f"Age {age}",
                filename=f"age-{age}.stl",
                mime="model/stl",
                size=0,
                deleted_at=(now - timedelta(days=age)).isoformat().replace("+00:00", "Z"),
            )
            session.add(asset)
            ids.append(asset.id)
        session.commit()
    assert [row for row in trash_service.eligible_trash("day") if row in ids] == [ids[2], ids[1], ids[0]]
    assert [row for row in trash_service.eligible_trash("week") if row in ids] == [ids[2], ids[1]]
    assert [row for row in trash_service.eligible_trash("month") if row in ids] == [ids[2]]
    assert trash_service.eligible_trash("never") == []
    with Session(engine) as session:
        for asset_id in ids:
            session.delete(session.get(Asset, asset_id))
        session.commit()


def test_trash_settings_expose_only_approved_choices() -> None:
    with TestClient(app) as client:
        headers = _headers(client)
        settings = client.get("/settings/trash", headers=headers)
        assert settings.status_code == 200
        assert settings.json()["choices"] == ["until_needed", "day", "week", "month", "never"]
        updated = client.post(
            "/settings/trash",
            headers=headers,
            json={"policy": "month"},
        )
        assert updated.status_code == 200
        assert updated.json()["policy"] == "month"


def test_empty_trash_returns_per_artifact_results() -> None:
    with TestClient(app) as client:
        headers = _headers(client)
        first = _upload(client, headers, "empty-one.stl")
        second = _upload(client, headers, "empty-two.stl")
        client.delete(f"/asset/{first['id']}", headers=headers)
        client.delete(f"/asset/{second['id']}", headers=headers)
        denied = client.post(
            "/trash/empty",
            headers=headers,
            json={"asset_ids": [], "confirmation": "empty"},
        )
        assert denied.status_code == 400
        emptied = client.post(
            "/trash/empty",
            headers=headers,
            json={"asset_ids": [], "confirmation": "EMPTY TRASH"},
        )
        assert emptied.status_code == 200
        results = emptied.json()
        result_ids = {row["asset_id"] for row in results}
        assert {first["id"], second["id"]}.issubset(result_ids)
        assert all(row["status"] == "deleted" for row in results)


def test_reconciliation_reports_unknown_quarantine_without_deleting_it() -> None:
    unknown = STORAGE / trash_service.QUARANTINE_DIR / "unknown-operation"
    unknown.mkdir(parents=True, exist_ok=True)
    marker = unknown / "keep.bin"
    marker.write_bytes(b"do not delete")
    outcome = trash_service.reconcile_trash_operations()
    assert "unknown-operation" in outcome["orphaned"]
    assert marker.read_bytes() == b"do not delete"
    marker.unlink()
    unknown.rmdir()
