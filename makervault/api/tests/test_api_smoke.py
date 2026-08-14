from fastapi.testclient import TestClient
from fastapi import HTTPException

import main
from main import app
from asset_service import backfill_embedded_thumbnails


def test_health_and_authenticated_library_smoke() -> None:
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json() == {"ok": True, "auth_required": True}

        assert client.get("/assets").status_code == 401

        login = client.post(
            "/login",
            json={"username": "admin", "password": "test-only-password"},
        )
        assert login.status_code == 200
        token = login.json()["token"]

        assets = client.get(
            "/assets",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert assets.status_code == 200
        assert assets.json() == []


def test_failed_primary_upload_removes_database_record(monkeypatch) -> None:
    async def reject_upload(*_args, **_kwargs):
        raise HTTPException(status_code=413, detail="Uploaded file exceeds size limit")

    monkeypatch.setattr(main, "stream_upload_to_file", reject_upload)
    with TestClient(app) as client:
        login = client.post(
            "/login",
            json={"username": "admin", "password": "test-only-password"},
        )
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        before = client.get("/assets", headers=headers).json()

        response = client.post(
            "/upload",
            headers=headers,
            files={"file": ("large.stl", b"solid", "model/stl")},
        )

        assert response.status_code == 413
        assert client.get("/assets", headers=headers).json() == before


def test_preview_policy_and_persistent_state_workflow() -> None:
    with TestClient(app) as client:
        login = client.post(
            "/login",
            json={"username": "admin", "password": "test-only-password"},
        )
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        policy = client.get("/settings/preview-policy", headers=headers)
        assert policy.status_code == 200
        assert policy.json()["active_jobs"] == 1
        assert policy.json()["automatic_max_bytes"] < policy.json()["detail_max_bytes"]

        upload = client.post(
            "/upload",
            headers=headers,
            files={"file": ("preview-state.stl", b"solid test\nendsolid test\n", "model/stl")},
        )
        assert upload.status_code == 200
        asset = upload.json()
        assert asset["preview_status"] == "pending"
        assert asset["preview_reason"] is None

        try:
            failed = client.post(
                f"/asset/{asset['id']}/preview-state",
                headers=headers,
                json={"status": "failed", "reason": "malformed_stl"},
            )
            assert failed.status_code == 200
            assert failed.json()["preview_status"] == "failed"
            assert failed.json()["preview_reason"] == "malformed_stl"

            backfill_embedded_thumbnails()
            persisted = client.get("/assets", headers=headers).json()
            persisted_asset = next(item for item in persisted if item["id"] == asset["id"])
            assert persisted_asset["preview_status"] == "failed"
            assert persisted_asset["preview_reason"] == "malformed_stl"

            invalid = client.post(
                f"/asset/{asset['id']}/preview-state",
                headers=headers,
                json={"status": "failed", "reason": "internal parser details"},
            )
            assert invalid.status_code == 422

            retry = client.post(f"/asset/{asset['id']}/preview-retry", headers=headers)
            assert retry.status_code == 200
            assert retry.json()["preview_status"] == "retry_requested"
            assert retry.json()["preview_reason"] is None
        finally:
            assert client.delete(f"/asset/{asset['id']}", headers=headers).status_code == 200
